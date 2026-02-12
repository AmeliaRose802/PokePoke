"""Desktop UI adapter for PokePoke orchestrator.

Provides the same interface as TextualUI but routes all output
through a WebSocket bridge to the Tauri desktop app instead of
the terminal-based Textual TUI.

Usage:
    from pokepoke.desktop_ui import DesktopUI
    ui = DesktopUI()
    exit_code = ui.run_with_orchestrator(orchestrator_func)
"""

from __future__ import annotations

import builtins
import sys
import threading
import time
from typing import Optional, Any, Iterator, Callable, TYPE_CHECKING
from contextlib import contextmanager

from pokepoke.desktop_bridge import DesktopBridge, DEFAULT_WS_PORT
from pokepoke.shutdown import is_shutting_down, request_shutdown

if TYPE_CHECKING:
    from pokepoke.types import SessionStats


class DesktopUI:
    """UI adapter that sends orchestrator output to the desktop app via WebSocket.

    Drop-in replacement for TextualUI. The orchestrator code doesn't need
    to know whether it's rendering to a terminal TUI or a desktop window —
    it calls the same methods either way.

    Key differences from TextualUI:
    - No Textual dependency — runs headless
    - Output goes to WebSocket clients instead of terminal widgets
    - The orchestrator runs in the main thread (no worker needed)
    - Print redirect captures output and forwards it over WebSocket
    """

    def __init__(self, port: int = DEFAULT_WS_PORT) -> None:
        self._bridge = DesktopBridge(port=port)
        self._is_running = False
        self._original_print = builtins.print
        self._current_style: Optional[str] = None
        self._target_buffer: str = "orchestrator"
        self._line_buffer: str = ""
        self._flush_timer: Optional[threading.Timer] = None
        self._buffer_lock = threading.Lock()
        self._port = port

    @property
    def is_running(self) -> bool:
        """Check if the UI is running."""
        return self._is_running

    @property
    def bridge(self) -> DesktopBridge:
        """Access the underlying WebSocket bridge."""
        return self._bridge

    def run_with_orchestrator(self, orchestrator_func: Callable[[], int]) -> int:
        """Run the orchestrator with the desktop bridge active.

        Starts the WebSocket server, redirects print output, runs the
        orchestrator function, then cleans up.

        Returns:
            Exit code from the orchestrator function.
        """
        self._bridge.start()
        self._is_running = True
        builtins.print = self._print_redirect

        # Log startup info to the bridge
        self._bridge.send_log(
            f"🖥️  Desktop bridge started on ws://127.0.0.1:{self._port}",
            "orchestrator",
        )

        try:
            exit_code = orchestrator_func()
            return exit_code
        except KeyboardInterrupt:
            request_shutdown()
            return 130
        except Exception as e:
            self._bridge.send_log(f"Orchestrator error: {e}", "orchestrator", "red")
            return 1
        finally:
            builtins.print = self._original_print
            self._is_running = False
            # Give clients a moment to receive final messages
            time.sleep(0.2)
            self._bridge.stop()

    def start(self) -> None:
        """Resume UI output capture (after interactive prompt pause)."""
        self._is_running = True
        builtins.print = self._print_redirect

    def stop(self) -> None:
        """Pause UI output capture (for interactive prompts).

        Restores original print so the user can see terminal prompts.
        """
        builtins.print = self._original_print
        self._is_running = False

    def stop_and_capture(self) -> None:
        """Stop UI but keep capturing output to the bridge.

        Used during shutdown to ensure stats are still sent to desktop.
        """
        # Keep print redirect active so final output goes to bridge
        self._is_running = False

    def exit(self) -> None:
        """Exit and stop the bridge."""
        self._is_running = False
        self._bridge.stop()

    # ─── Print Redirect ───────────────────────────────────────────────

    def _print_redirect(self, *args: Any, **kwargs: Any) -> None:
        """Redirect print calls to the desktop bridge."""
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

            # Process complete lines immediately
            while "\n" in self._line_buffer:
                line, self._line_buffer = self._line_buffer.split("\n", 1)
                if line:
                    self._bridge.send_log(line, self._target_buffer, self._current_style)
                if self._flush_timer:
                    self._flush_timer.cancel()
                    self._flush_timer = None

            # Deferred flush for streaming tokens
            if flush and self._line_buffer:
                if self._flush_timer:
                    self._flush_timer.cancel()
                self._flush_timer = threading.Timer(0.1, self._deferred_flush)
                self._flush_timer.daemon = True
                self._flush_timer.start()

    def _deferred_flush(self) -> None:
        """Flush the line buffer after a short delay."""
        with self._buffer_lock:
            if self._line_buffer:
                self._bridge.send_log(
                    self._line_buffer, self._target_buffer, self._current_style
                )
                self._line_buffer = ""
            self._flush_timer = None

    # ─── Output Routing ───────────────────────────────────────────────

    @contextmanager
    def orchestrator_output(self) -> Iterator[None]:
        """Context manager to route output to orchestrator panel."""
        prev = self._target_buffer
        self._target_buffer = "orchestrator"
        try:
            yield
        finally:
            self._target_buffer = prev

    @contextmanager
    def agent_output(self) -> Iterator[None]:
        """Context manager to route output to agent panel."""
        prev = self._target_buffer
        self._target_buffer = "agent"
        try:
            yield
        finally:
            self._target_buffer = prev

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

    # ─── State Updates ────────────────────────────────────────────────

    def set_current_agent(self, agent_name: Optional[str]) -> None:
        """Set the currently running agent name."""
        self._bridge.send_agent_name(agent_name or "")

    def update_header(self, item_id: str, title: str, status: str = "") -> None:
        """Update the work item header."""
        self._bridge.send_work_item(item_id, title, status)

    def update_stats(
        self, session_stats: Optional[SessionStats], elapsed_time: float = 0.0
    ) -> None:
        """Update the session statistics display."""
        self._bridge.send_stats(session_stats, elapsed_time)

    def set_session_start_time(self, start_time: float) -> None:
        """Set the session start time for real-time clock updates.

        In desktop mode the frontend handles its own elapsed time
        calculation, so we just forward the start timestamp.
        """
        self._bridge.send_stats(None, time.time() - start_time)

    def log_message(
        self, message: str, target: str = "orchestrator", style: Optional[str] = None
    ) -> None:
        """Directly log a message to a panel."""
        self._bridge.send_log(message, target, style)

    def log_orchestrator(self, message: str, style: Optional[str] = None) -> None:
        """Log a message to the orchestrator panel."""
        self._bridge.send_log(message, "orchestrator", style)

    def log_agent(self, message: str, style: Optional[str] = None) -> None:
        """Log a message to the agent panel."""
        self._bridge.send_log(message, "agent", style)
