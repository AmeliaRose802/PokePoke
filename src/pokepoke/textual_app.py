"""Textual Application for PokePoke orchestrator.

Contains the main PokePokeApp class that provides the TUI interface.

Requires: textual>=0.40.0
"""

from __future__ import annotations

import time
import threading
from typing import Optional, Any, Callable, TYPE_CHECKING
from queue import Queue, Empty

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.widgets import Header, Footer
from textual.worker import Worker, WorkerState

from pokepoke.textual_widgets import StatsBar, WorkItemHeader, LogPanel
from pokepoke.textual_messages import MessageType, UIMessage

if TYPE_CHECKING:
    from pokepoke.types import SessionStats


class PokePokeApp(App[int]):
    """Main Textual application for PokePoke orchestrator.

    Features:
    - Modern header with clock
    - Work item display with status badges
    - Split log panels for orchestrator and agent output
    - Stats footer with real-time updates
    - Keyboard shortcuts for navigation
    """

    CSS_PATH = "pokepoke.tcss"

    BINDINGS = [
        Binding("q", "quit", "Quit", priority=True, show=True),
        Binding("ctrl+c", "quit", "Quit", show=False),
        Binding("tab", "switch_focus", "Switch Panel", show=True),
        Binding("o", "focus_orchestrator", "Orchestrator", show=True),
        Binding("a", "focus_agent", "Agent", show=True),
        Binding("home", "scroll_top", "Top"),
        Binding("end", "scroll_bottom", "Bottom"),
        Binding("pageup", "page_up", "Page Up"),
        Binding("pagedown", "page_down", "Page Down"),
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
        self._ui_msg_queue: Queue[UIMessage] = Queue()
        self._active_panel: str = "agent"
        self._target_buffer: str = "orchestrator"
        self._lock = threading.Lock()
        self._exit_code: int = 0

    def compose(self) -> ComposeResult:  # pragma: no cover
        """Create the application layout."""
        yield Header(show_clock=True)
        yield WorkItemHeader(id="work-header")
        with Horizontal(id="log-container"):
            yield LogPanel(
                id="orchestrator-log",
                classes="log-panel",
                title="🔧 Orchestrator",
                subtitle="[o] focus",
            )
            yield LogPanel(
                id="agent-log",
                classes="log-panel focused",
                title="🤖 Agent",
                subtitle="[a] focus",
            )
        yield StatsBar(id="stats-bar")
        yield Footer()

    def on_mount(self) -> None:  # pragma: no cover
        """Set up the app on mount."""
        self.title = "PokePoke Orchestrator"
        self.sub_title = "Autonomous Workflow Manager"
        self.query_one("#agent-log").focus()
        self.set_interval(1.0, self._update_elapsed_time)
        self.set_interval(0.05, self._process_ui_msg_queue)

        if self._orchestrator_func:
            self.run_worker(
                self._run_orchestrator_wrapper,
                name="orchestrator",
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
        if event.worker.name != "orchestrator":
            return
        if event.state == WorkerState.SUCCESS:
            self._exit_code = event.worker.result or 0
            self.exit(self._exit_code)
        elif event.state == WorkerState.ERROR:
            self._exit_code = 1
            self.exit(1)
        elif event.state == WorkerState.CANCELLED:
            self._exit_code = 130
            self.exit(130)

    def _update_elapsed_time(self) -> None:
        """Update elapsed time in stats bar."""
        if self._session_start_time:
            elapsed = time.time() - self._session_start_time
            try:  # pragma: no cover
                stats_bar = self.query_one("#stats-bar", StatsBar)
                hours = int(elapsed // 3600)
                minutes = int((elapsed % 3600) // 60)
                seconds = int(elapsed % 60)
                stats_bar.elapsed_time = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
            except Exception:
                pass

    def _process_ui_msg_queue(self) -> None:
        """Process pending messages from the message queue."""
        processed = 0
        max_per_tick = 100
        while processed < max_per_tick:
            try:
                msg = self._ui_msg_queue.get_nowait()
                self._handle_message(msg)  # pragma: no cover
                processed += 1  # pragma: no cover
            except Empty:
                break

    def _handle_message(self, msg: UIMessage) -> None:  # pragma: no cover
        """Handle a single message from the queue."""
        try:
            if msg.msg_type == MessageType.LOG:
                target, message, style = msg.args
                self._write_to_panel(target, message, style)
            elif msg.msg_type == MessageType.WORK_ITEM:
                item_id, title, status = msg.args
                header = self.query_one("#work-header", WorkItemHeader)
                header.update_work_item(item_id, title, status)
            elif msg.msg_type == MessageType.STATS:
                session_stats, elapsed = msg.args
                stats_bar = self.query_one("#stats-bar", StatsBar)
                stats_bar.update_stats(session_stats, elapsed)
            elif msg.msg_type == MessageType.AGENT_NAME:
                name = msg.args[0]
                header = self.query_one("#work-header", WorkItemHeader)
                header.set_agent_name(name)
        except Exception:
            pass

    def _write_to_panel(self, target: str, message: str, style: Optional[str]) -> None:  # pragma: no cover
        """Write a message to the specified log panel."""
        panel_id = "#agent-log" if target == "agent" else "#orchestrator-log"
        try:
            panel = self.query_one(panel_id, LogPanel)
            panel.write_log(message, style)
        except Exception:
            pass

    def action_switch_focus(self) -> None:  # pragma: no cover
        """Switch focus between log panels."""
        if self._active_panel == "orchestrator":
            self._focus_panel("agent")
        else:
            self._focus_panel("orchestrator")

    def action_focus_orchestrator(self) -> None:  # pragma: no cover
        """Focus the orchestrator panel."""
        self._focus_panel("orchestrator")

    def action_focus_agent(self) -> None:  # pragma: no cover
        """Focus the agent panel."""
        self._focus_panel("agent")

    def _focus_panel(self, panel_name: str) -> None:  # pragma: no cover
        """Focus a specific panel and update visual state."""
        orch = self.query_one("#orchestrator-log", LogPanel)
        agent = self.query_one("#agent-log", LogPanel)
        if panel_name == "orchestrator":
            self._active_panel = "orchestrator"
            orch.focus()
            orch.add_class("focused")
            agent.remove_class("focused")
        else:
            self._active_panel = "agent"
            agent.focus()
            agent.add_class("focused")
            orch.remove_class("focused")

    def _get_active_panel(self) -> LogPanel:  # pragma: no cover
        """Get the currently active log panel."""
        panel_id = "#orchestrator-log" if self._active_panel == "orchestrator" else "#agent-log"
        return self.query_one(panel_id, LogPanel)

    def action_scroll_top(self) -> None:  # pragma: no cover
        """Scroll active panel to top."""
        self._get_active_panel().scroll_home()

    def action_scroll_bottom(self) -> None:  # pragma: no cover
        """Scroll active panel to bottom."""
        self._get_active_panel().scroll_end()

    def action_page_up(self) -> None:  # pragma: no cover
        """Scroll active panel up one page."""
        self._get_active_panel().scroll_page_up()

    def action_page_down(self) -> None:  # pragma: no cover
        """Scroll active panel down one page."""
        self._get_active_panel().scroll_page_down()

    def log_message(self, message: str, target: str = "orchestrator", style: Optional[str] = None) -> None:
        """Thread-safe: Queue a log message for display."""
        self._ui_msg_queue.put(UIMessage(MessageType.LOG, (target, message, style)))

    def log_orchestrator(self, message: str, style: Optional[str] = None) -> None:
        """Thread-safe: Log a message to the orchestrator panel."""
        self.log_message(message, "orchestrator", style)

    def log_agent(self, message: str, style: Optional[str] = None) -> None:
        """Thread-safe: Log a message to the agent panel."""
        self.log_message(message, "agent", style)

    def update_work_item(self, item_id: str, title: str, status: str = "") -> None:
        """Thread-safe: Update the work item header."""
        self._ui_msg_queue.put(UIMessage(MessageType.WORK_ITEM, (item_id, title, status)))

    def update_stats(self, session_stats: Optional[SessionStats], elapsed_time: float = 0.0) -> None:
        """Thread-safe: Update session statistics."""
        self._current_stats = session_stats
        self._ui_msg_queue.put(UIMessage(MessageType.STATS, (session_stats, elapsed_time)))

    def set_session_start_time(self, start_time: float) -> None:
        """Set the session start time for elapsed time calculation."""
        self._session_start_time = start_time

    def set_current_agent(self, agent_name: Optional[str]) -> None:
        """Thread-safe: Set the current agent name."""
        self._ui_msg_queue.put(UIMessage(MessageType.AGENT_NAME, (agent_name or "",)))

    def set_target_buffer(self, target: str) -> None:
        """Set which panel receives print output."""
        with self._lock:
            self._target_buffer = target

    def get_target_buffer(self) -> str:
        """Get the current target buffer."""
        with self._lock:
            return self._target_buffer
