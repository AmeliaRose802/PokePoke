"""Textual-based Terminal UI for PokePoke orchestrator.

Modern, clean TUI with differential rendering, scrollable log containers,
proper async event handling, and native logging widgets.

Requires: textual>=0.40.0
"""

from __future__ import annotations

import sys
import threading
from typing import Optional, Any, Iterator, Callable, TYPE_CHECKING
from contextlib import contextmanager

# Re-export for backward compatibility
from pokepoke.textual_messages import MessageType, UIMessage
from pokepoke.textual_app import PokePokeApp

if TYPE_CHECKING:
    from pokepoke.types import SessionStats


class TextualUI:
    """UI wrapper that runs the orchestrator inside a Textual app.

    This class provides a clean interface for the orchestrator to interact
    with the Textual UI. It handles:
    - Running Textual in the main thread
    - Running the orchestrator in a worker thread
    - Thread-safe message passing
    - Print redirection for output capture
    """

    def __init__(self) -> None:
        self._app: Optional[PokePokeApp] = None
        self._is_running = False
        self._original_print = print
        self._current_style: Optional[str] = None
        self._line_buffer: str = ""
        self._final_output: list[str] = []  # Output to print after UI exits
        self._flush_timer: Optional[threading.Timer] = None
        self._buffer_lock = threading.Lock()

    @property
    def is_running(self) -> bool:
        """Check if the UI is running."""
        return self._is_running

    def run_with_orchestrator(self, orchestrator_func: Callable[[], int]) -> int:  # pragma: no cover
        """Run the Textual app with the orchestrator as a worker.

        This is the main entry point - Textual runs in the main thread
        and the orchestrator runs in a worker thread.
        """
        self._app = PokePokeApp(orchestrator_func=orchestrator_func)
        self._is_running = True
        self._final_output = []  # Reset final output
        import builtins
        builtins.print = self._print_redirect
        try:
            self._app.run()
            return self._app._exit_code
        finally:
            builtins.print = self._original_print
            self._is_running = False
            # Print any final output that was queued during shutdown
            for line in self._final_output:
                self._original_print(line)

    def start(self) -> None:
        """Resume the UI after a pause (for interactive input prompts)."""
        self._is_running = True
        if self._app:
            import builtins
            builtins.print = self._print_redirect

    def stop(self) -> None:
        """Pause the UI temporarily (for interactive input prompts).
        
        Restores original print so user can see prompts and input text.
        """
        import builtins
        builtins.print = self._original_print
        self._is_running = False

    def stop_and_capture(self) -> None:
        """Stop UI and capture remaining output for after Textual exits.
        
        Use this when exiting the orchestrator to ensure stats are printed
        after Textual restores the terminal. Output is captured to _final_output.
        """
        import builtins
        builtins.print = self._capture_final_output
        self._is_running = False

    def _capture_final_output(self, *args: Any, **kwargs: Any) -> None:
        """Capture print output for after Textual exits."""
        file = kwargs.get("file", sys.stdout)
        if file not in (sys.stdout, None):
            self._original_print(*args, **kwargs)
            return
        sep = kwargs.get("sep", " ")
        end = kwargs.get("end", "\n")
        msg = sep.join(str(arg) for arg in args) + end
        self._final_output.append(msg.rstrip('\n'))

    def exit(self) -> None:
        """Exit the Textual app completely."""
        if self._app:
            try:
                self._app.exit()  # pragma: no cover
            except Exception:
                pass  # pragma: no cover
        self._is_running = False

    def _print_redirect(self, *args: Any, **kwargs: Any) -> None:
        """Redirect print calls to the Textual UI."""
        file = kwargs.get("file", sys.stdout)
        if file not in (sys.stdout, None):
            self._original_print(*args, **kwargs)
            return
        if not self._app or not self._is_running:
            self._original_print(*args, **kwargs)
            return
        sep = kwargs.get("sep", " ")
        end = kwargs.get("end", "\n")
        flush = kwargs.get("flush", False)
        msg = sep.join(str(arg) for arg in args) + end

        with self._buffer_lock:
            self._line_buffer += msg

            # Process complete lines immediately
            while "\n" in self._line_buffer:
                line, self._line_buffer = self._line_buffer.split("\n", 1)
                if line:
                    target = self._app.get_target_buffer()
                    self._app.log_message(line, target, self._current_style)
                # Cancel pending flush timer - we already flushed a complete line
                if self._flush_timer:
                    self._flush_timer.cancel()
                    self._flush_timer = None

            # For streaming output (flush=True with no newline), schedule a
            # deferred flush so multiple tokens are batched into one line
            # instead of each token getting its own timestamped line.
            if flush and self._line_buffer:
                if self._flush_timer:
                    self._flush_timer.cancel()
                self._flush_timer = threading.Timer(0.1, self._deferred_flush)
                self._flush_timer.daemon = True
                self._flush_timer.start()

    def _deferred_flush(self) -> None:
        """Flush the line buffer after a short delay (batches streaming tokens)."""
        with self._buffer_lock:
            if self._line_buffer and self._app and self._is_running:
                target = self._app.get_target_buffer()
                self._app.log_message(self._line_buffer, target, self._current_style)
                self._line_buffer = ""
            self._flush_timer = None

    @contextmanager
    def orchestrator_output(self) -> Iterator[None]:
        """Context manager to route output to orchestrator panel."""
        if not self._app:
            yield
            return
        prev = self._app.get_target_buffer()
        self._app.set_target_buffer("orchestrator")
        try:
            yield
        finally:
            self._app.set_target_buffer(prev)

    @contextmanager
    def agent_output(self) -> Iterator[None]:
        """Context manager to route output to agent panel."""
        if not self._app:
            yield
            return
        prev = self._app.get_target_buffer()
        self._app.set_target_buffer("agent")
        try:
            yield
        finally:
            self._app.set_target_buffer(prev)

    @contextmanager
    def styled_output(self, style: str) -> Iterator[None]:
        """Context manager to apply a Rich style to output."""
        prev_style = self._current_style
        self._current_style = style
        try:
            yield
        finally:
            self._current_style = prev_style

    def set_style(self, style: Optional[str]) -> None:
        """Set the current text style for logs."""
        self._current_style = style

    def set_current_agent(self, agent_name: Optional[str]) -> None:
        """Set the currently running agent name for display."""
        if self._app:
            self._app.set_current_agent(agent_name)

    def update_header(self, item_id: str, title: str, status: str = "") -> None:
        """Update the work item header."""
        if self._app:
            self._app.update_work_item(item_id, title, status)

    def update_stats(self, session_stats: Optional[SessionStats], elapsed_time: float = 0.0) -> None:
        """Update the session statistics display."""
        if self._app:
            self._app.update_stats(session_stats, elapsed_time)

    def set_session_start_time(self, start_time: float) -> None:
        """Set the session start time for real-time clock updates."""
        if self._app:
            self._app.set_session_start_time(start_time)

    def log_message(self, message: str, target: str = "orchestrator", style: Optional[str] = None) -> None:
        """Directly log a message to a panel."""
        if self._app:
            self._app.log_message(message, target, style)

    def log_orchestrator(self, message: str, style: Optional[str] = None) -> None:
        """Log a message to the orchestrator panel."""
        if self._app:
            self._app.log_orchestrator(message, style)

    def log_agent(self, message: str, style: Optional[str] = None) -> None:
        """Log a message to the agent panel."""
        if self._app:
            self._app.log_agent(message, style)


def create_ui() -> TextualUI:
    """Factory function to create a new TextualUI instance."""
    return TextualUI()


# Global UI instance for compatibility
ui = TextualUI()
