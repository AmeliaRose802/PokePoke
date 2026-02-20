"""Desktop UI adapter for PokePoke orchestrator using pywebview.

Opens a native OS window (via Edge WebView2 on Windows) and runs the
React frontend inside it.  Communication is direct in-process method
calls — no WebSocket, no server, no port.

Architecture:
    pywebview creates a native window, DesktopAPI exposes Python methods
    to JavaScript directly, and the frontend polls via window.pywebview.api.
    The orchestrator runs on a background thread.
"""

from __future__ import annotations

import builtins
import os
import sys
import threading
from typing import Any, TYPE_CHECKING
from collections.abc import Iterator, Callable
from contextlib import contextmanager

from pokepoke.desktop_api import DesktopAPI
from pokepoke.shutdown import is_shutting_down, request_shutdown
from pokepoke.frontend_discovery import find_frontend_dist
from pokepoke.native_icon import set_native_window_icon

if TYPE_CHECKING:
    from pokepoke.types import SessionStats


def _shutdown_threading_excepthook(args: threading.ExceptHookArgs) -> None:
    """Suppress UnicodeDecodeError in background threads during shutdown.

    When the pywebview window closes, the Copilot SDK subprocess may emit
    non-UTF-8 bytes as it is forcefully terminated.  Python's
    ``subprocess._readerthread`` tries to decode with strict UTF-8 and
    raises ``UnicodeDecodeError`` in a daemon thread.  This hook
    silences that traceback so the user sees a clean exit with stats.
    """
    if is_shutting_down() and isinstance(args.exc_value, UnicodeDecodeError):
        # Swallow the noisy traceback — the process is exiting anyway.
        return
    # Fall back to the default hook for everything else.
    if _original_excepthook is not None:
        _original_excepthook(args)
    else:
        # Last resort: print it ourselves.
        import traceback as _tb
        _tb.print_exception(args.exc_type, args.exc_value, args.exc_traceback)


# Saved so we can delegate non-shutdown exceptions.
_original_excepthook: Callable[..., Any] | None = None


# Thread-local storage for per-thread output routing.
_thread_output = threading.local()


class DesktopUI:
    """UI adapter that opens a native pywebview window.

    The orchestrator calls the standard UI methods — this adapter pushes
    state to the DesktopAPI which the frontend reads via direct
    in-process calls (window.pywebview.api).

    Single process. No server. No ports.
    """

    def __init__(self) -> None:
        self._api = DesktopAPI()
        self._is_running = False
        self._original_print = builtins.print
        self._current_style: str | None = None
        self._target_buffer: str = "orchestrator"
        self._line_buffer: str = ""
        self._flush_timer: threading.Timer | None = None
        self._buffer_lock = threading.Lock()

    @property
    def is_running(self) -> bool:
        return self._is_running

    def run_with_orchestrator(self, orchestrator_func: Callable[[], int]) -> int:
        """Run the orchestrator with a native desktop window.

        pywebview must own the main thread (Windows requirement), so:
        1. Start the orchestrator on a background thread
        2. Create the pywebview window on the main thread
        3. When the window closes, signal shutdown
        """
        import webview

        # Install a threading excepthook that suppresses UnicodeDecodeError
        # during shutdown (the Copilot SDK subprocess can emit non-UTF-8
        # bytes when forcefully terminated).
        global _original_excepthook
        _original_excepthook = threading.excepthook
        threading.excepthook = _shutdown_threading_excepthook

        self._is_running = True
        builtins.print = self._print_redirect

        self._api.push_log(
            "🖥️  PokePoke Desktop started (pywebview native window)",
            "orchestrator",
        )

        # Find the frontend
        dist_dir = find_frontend_dist()
        if dist_dir is None:
            builtins.print = self._original_print
            print("❌ Desktop frontend not built. Run:", file=sys.stderr)
            print("   cd desktop && npm install && npm run build", file=sys.stderr)
            return 1

        # Result container for the orchestrator thread
        exit_code_box: list[int] = [0]

        def run_orchestrator() -> None:
            try:
                exit_code_box[0] = orchestrator_func()
            except KeyboardInterrupt:
                request_shutdown()
                exit_code_box[0] = 130
            except Exception as e:
                self._api.push_log(f"❌ Orchestrator error: {e}", "orchestrator", "red")
                exit_code_box[0] = 1
            finally:
                builtins.print = self._original_print
                self._is_running = False

        # Start orchestrator on background thread
        orch_thread = threading.Thread(
            target=run_orchestrator,
            daemon=True,
            name="orchestrator",
        )

        # Create native window pointing at the built React app
        icon_path = dist_dir / "pokepoke.ico"

        def on_window_loaded() -> None:
            """Called after the webview window is ready."""
            # pywebview's icon parameter only works on GTK/QT — on Windows
            # the WinForms backend extracts the icon from sys.executable
            # (python.exe → Python logo).  Override it via the native form.
            set_native_window_icon(window, icon_path)
            self._api.set_window(window)
            orch_thread.start()

        window_kwargs: dict[str, Any] = {
            "title": "PokePoke - Autonomous Workflow Manager",
            "url": str(dist_dir / "index.html"),
            "js_api": self._api,
            "width": 1280,
            "height": 800,
            "min_size": (900, 600),
            "text_select": True,
        }
        window = webview.create_window(**window_kwargs)

        # Run pywebview on the main thread (blocks until window closes)
        start_kwargs: dict[str, Any] = {
            "func": on_window_loaded,
            "debug": os.environ.get("POKEPOKE_DEBUG", "").lower() in ("1", "true"),
        }
        if icon_path.exists():
            start_kwargs["icon"] = str(icon_path)
        webview.start(**start_kwargs)

        # Window closed — tell orchestrator to shut down
        request_shutdown()
        self._is_running = False
        builtins.print = self._original_print

        # Wait for orchestrator to finish (needs enough time to collect
        # beads stats and print the session summary).
        if orch_thread.is_alive():
            orch_thread.join(timeout=15.0)

        # Restore the original threading excepthook
        if _original_excepthook is not None:
            threading.excepthook = _original_excepthook

        return exit_code_box[0]

    def start(self) -> None:
        """Resume UI output capture (after interactive prompt pause)."""
        self._is_running = True
        builtins.print = self._print_redirect

    def stop(self) -> None:
        """Pause UI output capture (for interactive prompts)."""
        builtins.print = self._original_print
        self._is_running = False

    def stop_and_capture(self) -> None:
        """Stop UI but keep capturing output."""
        self._is_running = False

    def exit(self) -> None:
        """Exit."""
        self._is_running = False

    # ─── Print Redirect ───────────────────────────────────────────────

    def _print_redirect(self, *args: Any, **kwargs: Any) -> None:
        """Redirect print calls to the desktop API log buffer.

        When a thread has set a thread-local agent_id (via
        :meth:`agent_output_for`), output is routed to that agent's
        per-agent log buffer in the :class:`AgentRegistry` instead of
        the shared orchestrator/agent log stream.  This prevents
        interleaving of output from parallel agents (dtqz) and ensures
        the Agents panel has live log data (ukr0).
        """
        file = kwargs.get("file", sys.stdout)
        if file not in (sys.stdout, None):
            self._original_print(*args, **kwargs)
            return

        sep = kwargs.get("sep", " ")
        end = kwargs.get("end", "\n")
        flush = kwargs.get("flush", False)
        msg = sep.join(str(arg) for arg in args) + end

        # Resolve per-thread overrides (set by context managers)
        target: str = getattr(_thread_output, "target", None) or self._target_buffer
        style: str | None = getattr(_thread_output, "style", None) or self._current_style
        agent_id: str | None = getattr(_thread_output, "agent_id", None)

        # Use per-thread line buffer to avoid interleaving partial lines
        # across parallel agents.  The main thread (no agent_id) still
        # uses the shared instance buffer for backward compatibility.
        if agent_id:
            line_buf: str = getattr(_thread_output, "line_buffer", "")
            line_buf += msg

            while "\n" in line_buf:
                line, line_buf = line_buf.split("\n", 1)
                if line:
                    self._api.push_agent_log(agent_id, line)

            _thread_output.line_buffer = line_buf
        else:
            with self._buffer_lock:
                self._line_buffer += msg

                while "\n" in self._line_buffer:
                    line, self._line_buffer = self._line_buffer.split("\n", 1)
                    if line:
                        self._api.push_log(line, target, style)
                    if self._flush_timer:
                        self._flush_timer.cancel()
                        self._flush_timer = None

                if flush and self._line_buffer:
                    if self._flush_timer:
                        self._flush_timer.cancel()
                    self._flush_timer = threading.Timer(0.1, self._deferred_flush)
                    self._flush_timer.daemon = True
                    self._flush_timer.start()

    def _deferred_flush(self) -> None:
        with self._buffer_lock:
            if self._line_buffer:
                self._api.push_log(
                    self._line_buffer, self._target_buffer, self._current_style
                )
                self._line_buffer = ""
            self._flush_timer = None

    # ─── Output Routing ───────────────────────────────────────────────

    @contextmanager
    def orchestrator_output(self) -> Iterator[None]:
        prev = getattr(_thread_output, "target", None)
        _thread_output.target = "orchestrator"
        try:
            yield
        finally:
            _thread_output.target = prev

    @contextmanager
    def agent_output(self) -> Iterator[None]:
        prev = getattr(_thread_output, "target", None)
        _thread_output.target = "agent"
        try:
            yield
        finally:
            _thread_output.target = prev

    @contextmanager
    def agent_output_for(self, agent_id: str) -> Iterator[None]:
        """Route print output on this thread to a specific agent's log buffer."""
        prev_agent_id = getattr(_thread_output, "agent_id", None)
        _thread_output.agent_id = agent_id
        try:
            yield
        finally:
            _thread_output.agent_id = prev_agent_id

    @contextmanager
    def styled_output(self, style: str) -> Iterator[None]:
        prev_style = self._current_style
        self._current_style = style
        try:
            yield
        finally:
            self._current_style = prev_style

    def set_style(self, style: str | None) -> None:
        self._current_style = style

    # ─── State Updates ────────────────────────────────────────────────

    def set_current_agent(self, agent_name: str | None) -> None:
        self._api.push_agent_name(agent_name or "")

    def update_header(self, item_id: str, title: str, status: str = "") -> None:
        self._api.push_work_item(item_id, title, status)

    def update_stats(
        self, session_stats: SessionStats | None, elapsed_time: float = 0.0
    ) -> None:
        self._api.push_stats(session_stats, elapsed_time)

    def set_session_start_time(self, start_time: float) -> None:
        self._api.set_session_start_time(start_time)

    def set_session_end_time(self, end_time: float) -> None:
        self._api.set_session_end_time(end_time)

    def log_message(
        self, message: str, target: str = "orchestrator", style: str | None = None
    ) -> None:
        self._api.push_log(message, target, style)

    def log_orchestrator(self, message: str, style: str | None = None) -> None:
        self._api.push_log(message, "orchestrator", style)

    def log_agent(self, message: str, style: str | None = None) -> None:
        self._api.push_log(message, "agent", style)

    def push_agent_status(
        self,
        agent_id: str,
        name: str,
        iteration: int = 1,
        status: str = "running",
        model: str | None = None,
        parent_agent_id: str | None = None,
        work_item_id: str | None = None,
        work_item_title: str | None = None,
        modified_files: list[str] | None = None,
    ) -> None:
        """Register or update a running agent card."""
        self._api.push_agent_status(
            agent_id, name, iteration, status, model, parent_agent_id,
            work_item_id, work_item_title, modified_files,
        )

    def push_agent_log(self, agent_id: str, line: str) -> None:
        self._api.push_agent_log(agent_id, line)

    def remove_agent(self, agent_id: str) -> None:
        self._api.remove_agent(agent_id)

    def pause_agent(self, agent_id: str) -> bool:
        return bool(self._api.pause_agent(agent_id).get("paused", False))

    def resume_agent(self, agent_id: str) -> bool:
        return bool(self._api.resume_agent(agent_id).get("resumed", False))

    def is_agent_paused(self, agent_id: str) -> bool:
        return self._api.is_agent_paused(agent_id)

