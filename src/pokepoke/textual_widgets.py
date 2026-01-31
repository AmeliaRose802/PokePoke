"""Textual widgets for PokePoke UI.

Contains reusable widget classes for the Textual-based TUI.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional, Any, TYPE_CHECKING

from textual.reactive import reactive
from textual.widgets import Static, RichLog
from rich.text import Text

if TYPE_CHECKING:
    from pokepoke.types import SessionStats


class StatsBar(Static):
    """Footer widget displaying session statistics with reactive updates."""

    # Reactive properties for stats
    elapsed_time: reactive[float] = reactive(0.0)
    items_completed: reactive[int] = reactive(0)
    retries: reactive[int] = reactive(0)
    input_tokens: reactive[int] = reactive(0)
    output_tokens: reactive[int] = reactive(0)
    api_duration: reactive[float] = reactive(0.0)
    tool_calls: reactive[int] = reactive(0)
    work_runs: reactive[int] = reactive(0)
    tech_debt_runs: reactive[int] = reactive(0)
    janitor_runs: reactive[int] = reactive(0)
    backlog_runs: reactive[int] = reactive(0)
    cleanup_runs: reactive[int] = reactive(0)
    beta_runs: reactive[int] = reactive(0)
    review_runs: reactive[int] = reactive(0)

    def render(self) -> Text:
        """Render the stats bar."""
        elapsed_min = self.elapsed_time / 60
        api_min = self.api_duration / 60

        lines = [
            f"⏱️ {elapsed_min:.1f}m  ⚡API: {api_min:.1f}m  "
            f"📥 {self.input_tokens:,}  📤 {self.output_tokens:,}  🔧 Tools: {self.tool_calls}",
            f"✅ Done: {self.items_completed}  🔄 Retries: {self.retries}  │  "
            f"👷 Work:{self.work_runs} 💸 Debt:{self.tech_debt_runs} "
            f"🧹 Jan:{self.janitor_runs} 🗄️ Blog:{self.backlog_runs} "
            f"🧼 Cln:{self.cleanup_runs} 🧪 Beta:{self.beta_runs} 🔍 Rev:{self.review_runs}",
        ]
        return Text("\n".join(lines))

    def _do_update(
        self, session_stats: Optional[SessionStats], elapsed_time: float
    ) -> None:
        """Internal method to update all reactive properties."""
        self.elapsed_time = elapsed_time

        if session_stats:
            agent = session_stats.agent_stats
            self.items_completed = session_stats.items_completed
            self.retries = agent.retries
            self.input_tokens = agent.input_tokens
            self.output_tokens = agent.output_tokens
            self.api_duration = agent.api_duration
            self.tool_calls = agent.tool_calls
            self.work_runs = session_stats.work_agent_runs
            self.tech_debt_runs = session_stats.tech_debt_agent_runs
            self.janitor_runs = session_stats.janitor_agent_runs
            self.backlog_runs = session_stats.backlog_cleanup_agent_runs
            self.cleanup_runs = session_stats.cleanup_agent_runs
            self.beta_runs = session_stats.beta_tester_agent_runs
            self.review_runs = session_stats.code_review_agent_runs

    def update_stats(
        self, session_stats: Optional[SessionStats], elapsed_time: float = 0.0
    ) -> None:
        """Update stats from SessionStats object.
        
        Uses batch update to prevent multiple renders when updating many properties.
        Falls back to direct updates if widget is not mounted in an app.
        """
        try:
            # Batch all reactive property updates to trigger only one render
            with self.app.batch_update():
                self._do_update(session_stats, elapsed_time)
        except Exception:
            # Widget not mounted in app - update directly (for tests)
            self._do_update(session_stats, elapsed_time)


class WorkItemHeader(Static):
    """Header widget displaying current work item info."""

    item_id: reactive[str] = reactive("PokePoke")
    item_title: reactive[str] = reactive("Initializing...")
    item_status: reactive[str] = reactive("")
    agent_name: reactive[str] = reactive("")

    def render(self) -> Text:
        """Render the work item header."""
        text = Text()
        text.append(f"📋 {self.item_id}", style="bold cyan")
        text.append(f" - {self.item_title}", style="white")
        if self.item_status:
            text.append(f" [{self.item_status}]", style="dim")
        if self.agent_name:
            text.append(f"  🤖 {self.agent_name}", style="green")
        return text

    def update_work_item(self, item_id: str, title: str, status: str = "") -> None:
        """Update the displayed work item."""
        self.item_id = item_id
        self.item_title = title
        self.item_status = status

    def set_agent_name(self, name: str) -> None:
        """Set the current agent name."""
        self.agent_name = name


class LogPanel(RichLog):
    """Extended RichLog with auto-scroll and scroll-lock on manual scroll."""

    def __init__(
        self,
        *args: Any,
        title: Optional[str] = None,
        subtitle: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, highlight=True, markup=True, **kwargs)
        self._auto_scroll = True
        if title:
            self.border_title = title
        if subtitle:
            self.border_subtitle = subtitle

    def on_mount(self) -> None:  # pragma: no cover
        """Set up auto-scrolling behavior."""
        self.auto_scroll = True

    def write_log(self, message: str, style: Optional[str] = None) -> None:  # pragma: no cover
        """Write a timestamped log message."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        if style:
            self.write(f"[dim]{timestamp}[/dim] [{style}]{message}[/{style}]")
        else:
            self.write(f"[dim]{timestamp}[/dim] {message}")
