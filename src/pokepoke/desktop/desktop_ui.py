"""Desktop UI adapter for PokePoke orchestrator using pywebview."""
from __future__ import annotations

import builtins
import logging
import sys
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

from pokepoke.desktop.desktop_api import DesktopAPI
from pokepoke.desktop.desktop_log_handler import DesktopLogHandler
from pokepoke.desktop.pywebview_patches import apply_runtime_patches
from pokepoke.desktop.thread_output_router import ThreadOutputRouter
from pokepoke.desktop.window_manager import DesktopWindowManager
from pokepoke.utils.shutdown import is_shutting_down, request_shutdown

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from pokepoke.types_stats import SessionStats

def _shutdown_threading_excepthook(args: threading.ExceptHookArgs) -> None:
    """Suppress noisy UnicodeDecodeError tracebacks from background threads during shutdown."""
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


class DesktopUI:
    """UI adapter that opens a native pywebview window and forwards state/logs to DesktopAPI."""
    def __init__(self) -> None:
        self._api = DesktopAPI()
        self._is_running = False
        self._original_print = builtins.print
        self._current_style: str | None = None
        self._target_buffer: str = "orchestrator"
        self._line_buffer: str = ""
        self._flush_timer: threading.Timer | None = None
        self._buffer_lock = threading.Lock()
        self._log_handler = DesktopLogHandler(
            self._api, self._target_buffer, self._buffer_lock,
            lambda: self._current_style,
        )
        self._log_handler.setLevel(logging.INFO)

    @property
    def is_running(self) -> bool:
        return self._is_running

    def wait_for_setup_complete(self, timeout: float | None = None) -> bool:
        """Block until the setup wizard signals completion."""
        return self._api.wait_for_setup_complete(timeout)

    def run_with_orchestrator(self, orchestrator_func: Callable[[], int]) -> int:
        """Run orchestrator on a background thread while pywebview runs on the main thread."""
        apply_runtime_patches()
        # Install a threading excepthook that suppresses UnicodeDecodeError
        # during shutdown (the Copilot SDK subprocess can emit non-UTF-8
        # bytes when forcefully terminated).
        global _original_excepthook
        _original_excepthook = threading.excepthook
        threading.excepthook = _shutdown_threading_excepthook
        self._is_running = True
        builtins.print = self._print_redirect
        self._install_log_handler()
        try:
            self._api.push_log(
                "🖥️  PokePoke Desktop started (pywebview native window)",
                "orchestrator",
            )
            # Resolve frontend via DesktopWindowManager
            wm = DesktopWindowManager()
            frontend = wm.resolve_frontend()
            if frontend is None:
                builtins.print = self._original_print
                logger.error("❌ Desktop frontend not built. Run:")
                logger.info("   cd desktop && npm install && npm run build")
                return 1
            window_url, is_dev_mode = frontend
            if is_dev_mode:
                self._api.push_log(
                    f"🔥 Hot reload enabled — loading from {window_url}",
                    "orchestrator",
                )
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
            orchestrator_started = False
            # Create native window pointing at the built React app
            window = wm.create_window(window_url, self._api)
            def on_window_loaded() -> None:
                """Called after the webview window is ready."""
                nonlocal orchestrator_started
                wm.apply_window_icon(window)
                self._api.set_window(window)
                orch_thread.start()
                orchestrator_started = True
            # Run pywebview on the main thread (blocks until window closes)
            try:
                wm.start_event_loop(
                    on_loaded=on_window_loaded,
                    debug=wm.is_debug_requested(is_dev_mode),
                )
            except Exception as e:
                # pywebview can throw during teardown on window-close (WinForms
                # backend uses a blocking Join). Treat this as a clean close
                # path if the orchestrator was already running.
                if not orchestrator_started and not is_shutting_down():
                    self._api.push_log(f"❌ Desktop UI error: {e}", "orchestrator", "red")
                    exit_code_box[0] = 1
            # Window closed (or UI failed) — dispose window then shut down
            self._api.dispose()
            request_shutdown()
            self._is_running = False
            builtins.print = self._original_print
            self._remove_log_handler()
            # Wait for orchestrator to finish (needs enough time to collect
            # beads stats and print the session summary).
            if orch_thread.is_alive():
                orch_thread.join(timeout=15.0)
            return exit_code_box[0]
        finally:
            self._is_running = False
            builtins.print = self._original_print
            self._remove_log_handler()
            if _original_excepthook is not None:
                threading.excepthook = _original_excepthook

    def start(self) -> None:
        """Resume UI output capture (after interactive prompt pause)."""
        self._is_running = True
        builtins.print = self._print_redirect
        self._install_log_handler()

    def stop(self) -> None:
        """Pause UI output capture (for interactive prompts)."""
        builtins.print = self._original_print
        self._remove_log_handler()
        self._is_running = False

    def stop_and_capture(self) -> None:
        """Stop UI but keep capturing output."""
        self._is_running = False

    def exit(self) -> None:
        self._is_running = False

    def _install_log_handler(self) -> None:
        pokepoke_logger = logging.getLogger("pokepoke")
        if self._log_handler not in pokepoke_logger.handlers:
            pokepoke_logger.addHandler(self._log_handler)

    def _remove_log_handler(self) -> None:
        pokepoke_logger = logging.getLogger("pokepoke")
        if self._log_handler in pokepoke_logger.handlers:
            pokepoke_logger.removeHandler(self._log_handler)

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
        # Resolve per-thread overrides (set by context managers)
        target: str = ThreadOutputRouter.get_thread_target() or self._target_buffer
        style: str | None = ThreadOutputRouter.get_thread_style()
        if style is None:
            with self._buffer_lock:
                style = self._current_style
        agent_id: str | None = ThreadOutputRouter.get_thread_agent_id()
        # Use per-thread line buffer to avoid interleaving partial lines
        # across parallel agents.  The main thread (no agent_id) still
        # uses the shared instance buffer for backward compatibility.
        if agent_id:
            line_buf: str = ThreadOutputRouter.get_thread_line_buffer()
            line_buf += msg
            while "\n" in line_buf:
                line, line_buf = line_buf.split("\n", 1)
                if line:
                    self._api.push_agent_log(agent_id, line)
            ThreadOutputRouter.set_thread_line_buffer(line_buf)
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
        """Route print output on this thread to orchestrator log."""
        with ThreadOutputRouter.orchestrator_output():
            yield

    @contextmanager
    def agent_output(self) -> Iterator[None]:
        """Route print output on this thread to agent log."""
        with ThreadOutputRouter.agent_output():
            yield

    @contextmanager
    def agent_output_for(self, agent_id: str) -> Iterator[None]:
        """Route print output on this thread to a specific agent's log buffer."""
        with ThreadOutputRouter.agent_output_for(agent_id):
            yield

    def set_style(self, style: str | None) -> None:
        with self._buffer_lock:
            self._current_style = style

    # ─── State Updates ────────────────────────────────────────────────

    def set_current_agent(self, agent_name: str | None) -> None:
        self._api.push_agent_name(agent_name or "")

    def update_header(
        self,
        item_id: str,
        title: str,
        status: str = "",
        labels: list[str] | None = None,
    ) -> None:
        self._api.push_work_item(item_id, title, status, labels)

    def update_stats(
        self, session_stats: SessionStats | None, elapsed_time: float = 0.0
    ) -> None:
        self._api.push_stats(session_stats, elapsed_time)

    def set_session_start_time(self, start_time: float) -> None:
        self._api.set_session_start_time(start_time)

    def set_session_end_time(self, end_time: float) -> None:
        self._api.set_session_end_time(end_time)

    def set_logs_dir(self, logs_dir: str) -> None:
        self._api.set_logs_dir(logs_dir)

    def log_orchestrator(self, message: str, style: str | None = None) -> None:
        self._api.push_log(message, "orchestrator", style)

    def push_agent_status(self, agent_id: str, name: str, iteration: int = 1,
                          status: str = "running", model: str | None = None,
                          parent_agent_id: str | None = None,
                          work_item_id: str | None = None,
                          work_item_title: str | None = None,
                          agent_prompt: str | None = None,
                          modified_files: list[str] | None = None,
                          agent_type: str | None = None,
                          resume_in_place: bool = False) -> None:
        """Register or update a running agent card."""
        self._api.push_agent_status(
            agent_id, name, iteration, status, model, parent_agent_id,
            work_item_id, work_item_title, agent_prompt, modified_files, agent_type,
            resume_in_place=resume_in_place,
        )

    def push_agent_log(self, agent_id: str, line: str) -> None:
        self._api.push_agent_log(agent_id, line)
    def push_agent_tokens(self, agent_id: str, input_tokens: int,
                          output_tokens: int) -> None:
        self._api.push_agent_tokens(agent_id, input_tokens, output_tokens)

    def remove_agent(self, agent_id: str) -> None:
        self._api.remove_agent(agent_id)
    def pause_agent(self, agent_id: str) -> bool:
        return bool(self._api.pause_agent(agent_id).get("paused", False))

    def resume_agent(self, agent_id: str) -> bool:
        return bool(self._api.resume_agent(agent_id).get("resumed", False))

    def is_agent_paused(self, agent_id: str) -> bool:
        return self._api.is_agent_paused(agent_id)

    def has_active_child_agents(self, agent_id: str) -> bool:
        """Check if an agent has any active (running/pending) child agents."""
        return self._api.has_active_child_agents(agent_id)

    def get_child_agent_activity_time(self, agent_id: str) -> float | None:
        """Get the most recent activity timestamp from any child agent."""
        return self._api.get_child_agent_activity_time(agent_id)

