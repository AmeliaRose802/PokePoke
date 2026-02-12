"""Desktop UI adapter for PokePoke orchestrator using pywebview.

Opens a native OS window (via Edge WebView2 on Windows) and runs the
React frontend inside it. Communication is direct in-process method
calls — no WebSocket, no server, no port.

Architecture:
    - pywebview creates a native window that renders the React app
    - DesktopAPI class exposes Python methods to JavaScript directly
    - The frontend polls for new logs / state via window.pywebview.api
    - The orchestrator runs on a background thread

Usage:
    python -m pokepoke.orchestrator --desktop
"""

from __future__ import annotations

import builtins
import os
import sys
import threading
import time
from pathlib import Path
from typing import Optional, Any, Iterator, Callable, TYPE_CHECKING
from contextlib import contextmanager

from pokepoke.desktop_api import DesktopAPI
from pokepoke.shutdown import is_shutting_down, request_shutdown

if TYPE_CHECKING:
    from pokepoke.types import SessionStats


def _find_frontend_dist() -> Optional[Path]:
    """Locate the pre-built React frontend dist/ directory."""
    # Look relative to this file: src/pokepoke/desktop_ui.py → ../../desktop/dist
    src_root = Path(__file__).resolve().parent.parent.parent
    dist = src_root / "desktop" / "dist"
    if dist.is_dir() and (dist / "index.html").exists():
        return dist
    return None


class DesktopUI:
    """UI adapter that opens a native pywebview window.

    Drop-in replacement for TextualUI. The orchestrator calls the same
    methods — this one pushes state to the DesktopAPI which the frontend
    reads via direct in-process calls (window.pywebview.api).

    Single process. No server. No ports.
    """

    def __init__(self) -> None:
        self._api = DesktopAPI()
        self._is_running = False
        self._original_print = builtins.print
        self._current_style: Optional[str] = None
        self._target_buffer: str = "orchestrator"
        self._line_buffer: str = ""
        self._flush_timer: Optional[threading.Timer] = None
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
        import webview  # type: ignore[import-not-found]

        self._is_running = True
        builtins.print = self._print_redirect

        self._api.push_log(
            "🖥️  PokePoke Desktop started (pywebview native window)",
            "orchestrator",
        )

        # Find the frontend
        dist_dir = _find_frontend_dist()
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

        def on_window_loaded() -> None:
            """Called after the webview window is ready."""
            self._api.set_window(window)
            orch_thread.start()

        # Create native window pointing at the built React app
        window = webview.create_window(
            title="PokePoke - Autonomous Workflow Manager",
            url=str(dist_dir / "index.html"),
            js_api=self._api,
            width=1280,
            height=800,
            min_size=(900, 600),
            text_select=True,
        )

        # Run pywebview on the main thread (blocks until window closes)
        webview.start(
            func=on_window_loaded,
            debug=(os.environ.get("POKEPOKE_DEBUG", "").lower() in ("1", "true")),
        )

        # Window closed — tell orchestrator to shut down
        request_shutdown()
        self._is_running = False
        builtins.print = self._original_print

        # Wait for orchestrator to finish (give it a moment)
        if orch_thread.is_alive():
            orch_thread.join(timeout=3.0)

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
        """Redirect print calls to the desktop API log buffer."""
        file = kwargs.get("file", sys.stdout)
        if file not in (sys.stdout, None):
            self._original_print(*args, **kwargs)
            return

        sep = kwargs.get("sep", " ")
        end = kwargs.get("end", "\n")
        flush = kwargs.get("flush", False)
        msg = sep.join(str(arg) for arg in args) + end

        with self._buffer_lock:
            self._line_buffer += msg

            while "\n" in self._line_buffer:
                line, self._line_buffer = self._line_buffer.split("\n", 1)
                if line:
                    self._api.push_log(line, self._target_buffer, self._current_style)
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
        prev = self._target_buffer
        self._target_buffer = "orchestrator"
        try:
            yield
        finally:
            self._target_buffer = prev

    @contextmanager
    def agent_output(self) -> Iterator[None]:
        prev = self._target_buffer
        self._target_buffer = "agent"
        try:
            yield
        finally:
            self._target_buffer = prev

    @contextmanager
    def styled_output(self, style: str) -> Iterator[None]:
        prev_style = self._current_style
        self._current_style = style
        try:
            yield
        finally:
            self._current_style = prev_style

    def set_style(self, style: Optional[str]) -> None:
        self._current_style = style

    # ─── State Updates ────────────────────────────────────────────────

    def set_current_agent(self, agent_name: Optional[str]) -> None:
        self._api.push_agent_name(agent_name or "")

    def update_header(self, item_id: str, title: str, status: str = "") -> None:
        self._api.push_work_item(item_id, title, status)

    def update_stats(
        self, session_stats: Optional["SessionStats"], elapsed_time: float = 0.0
    ) -> None:
        self._api.push_stats(session_stats, elapsed_time)

    def set_session_start_time(self, start_time: float) -> None:
        self._api.push_stats(None, time.time() - start_time)

    def log_message(
        self, message: str, target: str = "orchestrator", style: Optional[str] = None
    ) -> None:
        self._api.push_log(message, target, style)

    def log_orchestrator(self, message: str, style: Optional[str] = None) -> None:
        self._api.push_log(message, "orchestrator", style)

    def log_agent(self, message: str, style: Optional[str] = None) -> None:
        self._api.push_log(message, "agent", style)

