"""Textual-based Terminal UI for PokePoke orchestrator.

Provides a stable TUI with differential rendering (no flashing), scrollable log
containers, proper async event handling, and native logging widgets.

Layout:
- Header: Work item info
- Body: Horizontal split with Orchestrator logs (left) and Agent logs (right)
- Footer: Session statistics

Requires: textual>=0.40.0
If textual is not installed, this module will raise ImportError and the
caller (terminal_ui.py) will fall back to MinimalUI.
"""

from __future__ import annotations

import sys
import time
import threading
from typing import Optional, Any, Iterator, Callable, TYPE_CHECKING
from contextlib import contextmanager
from queue import Queue, Empty

# These imports will fail if textual is not installed
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.worker import Worker, WorkerState

from pokepoke.textual_widgets import StatsBar, WorkItemHeader, LogPanel

if TYPE_CHECKING:
    from pokepoke.types import SessionStats


class PokePokeApp(App[int]):
    """Main Textual application for PokePoke orchestrator."""

    CSS_PATH = "pokepoke.tcss"

    BINDINGS = [
        Binding("tab", "switch_focus", "Switch Panel"),
        Binding("q", "quit", "Quit", show=True),
        Binding("ctrl+c", "quit", "Quit", show=False),
        Binding("home", "scroll_top", "Scroll Top"),
        Binding("end", "scroll_bottom", "Scroll Bottom"),
    ]

    def __init__(
        self,
        orchestrator_func: Optional[Callable[[], int]] = None,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._orchestrator_func = orchestrator_func
        self._session_start_time: Optional[float] = None
        self._current_stats: Optional[SessionStats] = None
        self._ui_queue: Queue[tuple[str, tuple[Any, ...]]] = Queue()
        self._active_panel: str = "agent"
        self._target_buffer: str = "orchestrator"
        self._lock = threading.Lock()
        self._exit_code: int = 0

    def compose(self) -> ComposeResult:  # pragma: no cover
        """Create child widgets."""
        yield WorkItemHeader(id="work-header")
        with Horizontal(id="log-container"):
            yield LogPanel(
                id="orchestrator-log",
                classes="log-panel",
                title="Orchestrator",
                subtitle="Home/End: jump",
            )
            yield LogPanel(
                id="agent-log",
                classes="log-panel focused",
                title="Agent",
                subtitle="Tab: switch panel",
            )
        yield StatsBar(id="stats-bar")

    def on_mount(self) -> None:  # pragma: no cover
        """Set up the app on mount."""
        self.query_one("#agent-log").focus()
        self.set_interval(1.0, self._update_elapsed_time)
        self.set_interval(0.05, self._process_ui_queue)

        # Start the orchestrator in a worker thread
        if self._orchestrator_func:
            self.run_worker(
                self._run_orchestrator_wrapper,
                thread=True,
                exclusive=True,
            )

    def _run_orchestrator_wrapper(self) -> int:
        """Wrapper to run the orchestrator function."""
        if self._orchestrator_func:
            try:
                return self._orchestrator_func()
            except Exception as e:
                self.log_message(f"Orchestrator error: {e}", "orchestrator", "red")
                return 1
        return 0

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:  # pragma: no cover
        """Handle worker completion."""
        if event.state == WorkerState.SUCCESS:
            self._exit_code = event.worker.result or 0
            self.exit(self._exit_code)
        elif event.state == WorkerState.ERROR:
            self._exit_code = 1
            self.exit(1)

    def _update_elapsed_time(self) -> None:
        """Update elapsed time in stats bar."""
        if self._session_start_time:
            elapsed = time.time() - self._session_start_time
            try:  # pragma: no cover
                stats_bar = self.query_one("#stats-bar", StatsBar)
                stats_bar.elapsed_time = elapsed
            except Exception:
                pass

    def _process_ui_queue(self) -> None:
        """Process pending messages from the UI queue."""
        processed = 0
        max_per_tick = 50

        while processed < max_per_tick:
            try:
                msg_type, args = self._ui_queue.get_nowait()
                self._handle_message(msg_type, args)  # pragma: no cover
                processed += 1  # pragma: no cover
            except Empty:
                break

    def _handle_message(self, msg_type: str, args: tuple[Any, ...]) -> None:  # pragma: no cover
        """Handle a single message from the queue."""
        try:
            if msg_type == "log":
                target, message, style = args
                panel_id = "#agent-log" if target == "agent" else "#orchestrator-log"
                panel = self.query_one(panel_id, LogPanel)
                panel.write_log(message, style)
            elif msg_type == "work_item":
                item_id, title, status = args
                header = self.query_one("#work-header", WorkItemHeader)
                header.update_work_item(item_id, title, status)
            elif msg_type == "stats":
                session_stats, elapsed = args
                stats_bar = self.query_one("#stats-bar", StatsBar)
                stats_bar.update_stats(session_stats, elapsed)
            elif msg_type == "agent_name":
                name = args[0]
                header = self.query_one("#work-header", WorkItemHeader)
                header.set_agent_name(name)
        except Exception:
            pass  # Ignore errors during shutdown

    def action_switch_focus(self) -> None:  # pragma: no cover
        """Switch focus between log panels."""
        orch = self.query_one("#orchestrator-log", LogPanel)
        agent = self.query_one("#agent-log", LogPanel)

        if self._active_panel == "orchestrator":
            self._active_panel = "agent"
            agent.focus()
            agent.add_class("focused")
            orch.remove_class("focused")
        else:
            self._active_panel = "orchestrator"
            orch.focus()
            orch.add_class("focused")
            agent.remove_class("focused")

    def action_scroll_top(self) -> None:  # pragma: no cover
        """Scroll active panel to top."""
        panel_id = (
            "#orchestrator-log" if self._active_panel == "orchestrator" else "#agent-log"
        )
        panel = self.query_one(panel_id, LogPanel)
        panel.scroll_home()

    def action_scroll_bottom(self) -> None:  # pragma: no cover
        """Scroll active panel to bottom."""
        panel_id = (
            "#orchestrator-log" if self._active_panel == "orchestrator" else "#agent-log"
        )
        panel = self.query_one(panel_id, LogPanel)
        panel.scroll_end()

    def log_message(
        self, message: str, target: str = "orchestrator", style: Optional[str] = None
    ) -> None:
        """Thread-safe: Queue a log message for display."""
        self._ui_queue.put(("log", (target, message, style)))

    def update_work_item(self, item_id: str, title: str, status: str = "") -> None:
        """Thread-safe: Update the work item header."""
        self._ui_queue.put(("work_item", (item_id, title, status)))

    def update_stats(
        self, session_stats: Optional[SessionStats], elapsed_time: float = 0.0
    ) -> None:
        """Thread-safe: Update session statistics."""
        self._current_stats = session_stats
        self._ui_queue.put(("stats", (session_stats, elapsed_time)))

    def set_session_start_time(self, start_time: float) -> None:
        """Set the session start time for elapsed time calculation."""
        self._session_start_time = start_time

    def set_current_agent(self, agent_name: Optional[str]) -> None:
        """Thread-safe: Set the current agent name."""
        self._ui_queue.put(("agent_name", (agent_name or "",)))

    def set_target_buffer(self, target: str) -> None:
        """Set which panel receives print output."""
        with self._lock:
            self._target_buffer = target

    def get_target_buffer(self) -> str:
        """Get the current target buffer."""
        with self._lock:
            return self._target_buffer


class TextualUI:
    """UI wrapper that runs the orchestrator inside a Textual app.

    This class provides the same interface as the old PokePokeUI but
    runs Textual as the main event loop with the orchestrator in a worker.
    """

    def __init__(self) -> None:
        self._app: Optional[PokePokeApp] = None
        self._is_running = False
        self._original_print = print
        self._current_style: Optional[str] = None
        self._line_buffer: str = ""

    @property
    def is_running(self) -> bool:
        """Check if the UI is running."""
        return self._is_running

    def run_with_orchestrator(self, orchestrator_func: Callable[[], int]) -> int:  # pragma: no cover
        """Run the Textual app with the orchestrator as a worker.

        This is the main entry point - Textual runs in the main thread
        and the orchestrator runs in a worker thread.

        Args:
            orchestrator_func: The orchestrator function to run

        Returns:
            Exit code from the orchestrator
        """
        self._app = PokePokeApp(orchestrator_func=orchestrator_func)
        self._is_running = True

        # Set up print redirection before running
        import builtins

        builtins.print = self._print_redirect

        try:
            self._app.run()
            return self._app._exit_code
        finally:
            builtins.print = self._original_print
            self._is_running = False

    def start(self) -> None:
        """Resume the UI after a pause (for interactive input prompts)."""
        # In Textual mode, the app runs continuously via run_with_orchestrator
        # This method resumes print redirection after interactive pauses
        self._is_running = True
        if self._app:
            import builtins
            builtins.print = self._print_redirect

    def stop(self) -> None:
        """Pause the UI temporarily (for interactive input prompts).
        
        Note: This doesn't exit the Textual app, just pauses print redirection
        so the user can see prompts and type input.
        """
        # Restore original print for user interaction
        import builtins
        builtins.print = self._original_print
        self._is_running = False

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
        msg = sep.join(str(arg) for arg in args) + end

        self._line_buffer += msg

        while "\n" in self._line_buffer:
            line, self._line_buffer = self._line_buffer.split("\n", 1)
            if line:
                target = self._app.get_target_buffer()
                self._app.log_message(line, target, self._current_style)

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

    def update_stats(
        self, session_stats: Optional[SessionStats], elapsed_time: float = 0.0
    ) -> None:
        """Update the session statistics display."""
        if self._app:
            self._app.update_stats(session_stats, elapsed_time)

    def set_session_start_time(self, start_time: float) -> None:
        """Set the session start time for real-time clock updates."""
        if self._app:
            self._app.set_session_start_time(start_time)

    def log_message(
        self, message: str, target: str = "orchestrator", style: Optional[str] = None
    ) -> None:
        """Directly log a message to a panel."""
        if self._app:
            self._app.log_message(message, target, style)


# Global UI instance
ui = TextualUI()
