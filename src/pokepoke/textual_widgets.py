"""Textual widgets for PokePoke UI.

Contains modern, well-styled widget classes for the Textual-based TUI.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional, Any, TYPE_CHECKING

from textual.reactive import reactive
from textual.widgets import Static, RichLog
from textual.timer import Timer
from rich.text import Text

if TYPE_CHECKING:
    from pokepoke.types import SessionStats


class ProgressIndicator(Static):
    """Animated spinner widget for showing activity."""

    SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

    is_active: reactive[bool] = reactive(False)
    status_text: reactive[str] = reactive("")
    _frame: int = 0
    _timer: Optional[Timer] = None

    def render(self) -> Text:
        """Render the spinner with status text."""
        if self.is_active:
            frame = self.SPINNER_FRAMES[self._frame % len(self.SPINNER_FRAMES)]
            return Text(f"{frame} {self.status_text}", style="bold cyan")
        elif self.status_text:
            return Text(f"● {self.status_text}", style="dim")
        return Text("", style="dim")

    def on_mount(self) -> None:
        """Start the animation timer."""
        self._timer = self.set_interval(0.1, self._advance_frame)

    def _advance_frame(self) -> None:
        """Advance the spinner animation frame."""
        if self.is_active:
            self._frame = (self._frame + 1) % len(self.SPINNER_FRAMES)
            self.refresh()

    def start(self, status: str = "Working...") -> None:
        """Start the spinner with a status message."""
        self.status_text = status
        self.is_active = True
        self.add_class("active")
        self.remove_class("idle")

    def stop(self, status: str = "") -> None:
        """Stop the spinner."""
        self.status_text = status
        self.is_active = False
        self.remove_class("active")
        self.add_class("idle")


class StatsBar(Static):
    """Footer widget displaying session statistics with reactive updates."""

    # Reactive properties for stats
    elapsed_time: reactive[str] = reactive("00:00:00")
    items_completed: reactive[int] = reactive(0)
    retries: reactive[int] = reactive(0)
    input_tokens: reactive[int] = reactive(0)
    output_tokens: reactive[int] = reactive(0)
    api_duration: reactive[float] = reactive(0.0)
    tool_calls: reactive[int] = reactive(0)
    work_runs: reactive[int] = reactive(0)
    gate_runs: reactive[int] = reactive(0)
    tech_debt_runs: reactive[int] = reactive(0)
    janitor_runs: reactive[int] = reactive(0)
    backlog_runs: reactive[int] = reactive(0)
    cleanup_runs: reactive[int] = reactive(0)
    beta_runs: reactive[int] = reactive(0)
    review_runs: reactive[int] = reactive(0)

    def _format_tokens(self, count: int) -> str:
        """Format token count with K/M suffix."""
        if count >= 1_000_000:
            return f"{count / 1_000_000:.1f}M"
        elif count >= 1_000:
            return f"{count / 1_000:.1f}K"
        return str(count)

    def _format_duration(self, seconds: float) -> str:
        """Format duration in human-readable form."""
        if seconds < 60:
            return f"{seconds:.0f}s"
        elif seconds < 3600:
            return f"{seconds / 60:.1f}m"
        else:
            return f"{seconds / 3600:.1f}h"

    def render(self) -> Text:
        """Render the stats bar with clean formatting."""
        text = Text()

        # Line 1: Time and API stats
        text.append("⏱️ ", style="dim")
        text.append(self.elapsed_time, style="bold cyan")
        text.append("  ⚡ API: ", style="dim")
        text.append(self._format_duration(self.api_duration), style="yellow")
        text.append("  📥 ", style="dim")
        text.append(self._format_tokens(self.input_tokens), style="green")
        text.append("  📤 ", style="dim")
        text.append(self._format_tokens(self.output_tokens), style="magenta")
        text.append("  🔧 ", style="dim")
        text.append(str(self.tool_calls), style="cyan")
        text.append("\n")

        # Line 2: Completion stats
        text.append("✅ Done: ", style="dim")
        text.append(str(self.items_completed), style="bold green")
        text.append("  🔄 Retries: ", style="dim")
        retry_style = "bold red" if self.retries > 3 else ("yellow" if self.retries > 0 else "dim")
        text.append(str(self.retries), style=retry_style)
        text.append("\n")

        # Line 3: Agent runs
        text.append("👷 Work:", style="dim")
        text.append(str(self.work_runs), style="white")
        text.append(" � Gate:", style="dim")
        text.append(str(self.gate_runs), style="white")
        text.append(" �💸 Debt:", style="dim")
        text.append(str(self.tech_debt_runs), style="white")
        text.append(" 🧹 Jan:", style="dim")
        text.append(str(self.janitor_runs), style="white")
        text.append(" 🗄️ Blog:", style="dim")
        text.append(str(self.backlog_runs), style="white")
        text.append(" 🧼 Cln:", style="dim")
        text.append(str(self.cleanup_runs), style="white")
        text.append(" 🧪 Beta:", style="dim")
        text.append(str(self.beta_runs), style="white")
        text.append(" 🔍 Rev:", style="dim")
        text.append(str(self.review_runs), style="white")

        return text

    def _do_update(
        self, session_stats: Optional[SessionStats], elapsed_seconds: float
    ) -> None:
        """Internal method to update all reactive properties."""
        # Format elapsed time as HH:MM:SS
        hours = int(elapsed_seconds // 3600)
        minutes = int((elapsed_seconds % 3600) // 60)
        seconds = int(elapsed_seconds % 60)
        self.elapsed_time = f"{hours:02d}:{minutes:02d}:{seconds:02d}"

        if session_stats:
            agent = session_stats.agent_stats
            self.items_completed = session_stats.items_completed
            self.retries = agent.retries
            self.input_tokens = agent.input_tokens
            self.output_tokens = agent.output_tokens
            self.api_duration = agent.api_duration
            self.tool_calls = agent.tool_calls
            self.work_runs = session_stats.work_agent_runs
            self.gate_runs = session_stats.gate_agent_runs
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
    """Header widget displaying current work item info with status badge."""

    AGENT_FRAMES = ["◐", "◓", "◑", "◒"]

    item_id: reactive[str] = reactive("PokePoke")
    item_title: reactive[str] = reactive("Initializing...")
    item_status: reactive[str] = reactive("")
    agent_name: reactive[str] = reactive("")
    _agent_frame: int = 0
    _timer: Optional[Timer] = None

    def on_mount(self) -> None:
        """Start the agent animation timer."""
        self._timer = self.set_interval(0.25, self._advance_agent_frame)

    def _advance_agent_frame(self) -> None:
        """Advance the agent animation frame."""
        if self.agent_name:
            self._agent_frame = (self._agent_frame + 1) % len(self.AGENT_FRAMES)
            self.refresh()

    def _get_status_style(self, status: str) -> str:
        """Get style for status badge."""
        status_lower = status.lower()
        if status_lower in ("in_progress", "in progress", "working"):
            return "bold yellow"
        elif status_lower in ("ready", "pending"):
            return "bold green"
        elif status_lower in ("blocked", "failed"):
            return "bold red"
        elif status_lower in ("done", "completed", "closed"):
            return "bold cyan"
        return "dim"

    def _truncate_title(self, title: str, max_len: int = 60) -> str:
        """Truncate title with ellipsis if too long."""
        if len(title) > max_len:
            return title[: max_len - 3] + "..."
        return title

    def render(self) -> Text:
        """Render the work item header with status badge."""
        text = Text()

        # Line 1: ID and Title
        text.append("🎫 ", style="dim")
        text.append(self.item_id, style="bold cyan")
        text.append(" │ ", style="dim")
        text.append(self._truncate_title(self.item_title), style="white")
        text.append("\n")

        # Line 2: Status and Agent
        if self.item_status:
            style = self._get_status_style(self.item_status)
            text.append("   [", style="dim")
            text.append(self.item_status.upper(), style=style)
            text.append("]", style="dim")

        if self.agent_name:
            frame = self.AGENT_FRAMES[self._agent_frame]
            text.append("  ", style="dim")
            text.append(frame, style="green")
            text.append(" ", style="dim")
            text.append(self.agent_name, style="bold green")

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
    """Enhanced RichLog with timestamps, log levels, and auto-scroll."""

    LOG_ICONS = {
        "error": "❌",
        "warning": "⚠️",
        "success": "✅",
        "info": "ℹ️",
        "debug": "🔍",
    }

    LOG_STYLES = {
        "error": "bold red",
        "warning": "yellow",
        "success": "green",
        "info": "white",
        "debug": "dim",
    }

    def __init__(
        self,
        *args: Any,
        title: Optional[str] = None,
        subtitle: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, highlight=True, markup=True, max_lines=10000, **kwargs)
        self._auto_scroll = True
        if title:
            self.border_title = title
        if subtitle:
            self.border_subtitle = subtitle

    def on_mount(self) -> None:  # pragma: no cover
        """Set up auto-scrolling behavior."""
        self.auto_scroll = True

    def _detect_log_level(self, message: str) -> str:
        """Detect log level from message content."""
        msg_lower = message.lower()
        if "error" in msg_lower or "failed" in msg_lower or "exception" in msg_lower:
            return "error"
        elif "warn" in msg_lower:
            return "warning"
        elif "success" in msg_lower or "completed" in msg_lower or "✅" in message:
            return "success"
        elif "debug" in msg_lower:
            return "debug"
        return "info"

    def write_log(
        self, message: str, style: Optional[str] = None, level: Optional[str] = None
    ) -> None:  # pragma: no cover
        """Write a timestamped log message with optional level styling."""
        timestamp = datetime.now().strftime("%H:%M:%S")

        # Auto-detect level if not provided
        if level is None and style is None:
            level = self._detect_log_level(message)

        text = Text()
        text.append(f"{timestamp} ", style="dim cyan")

        if level and level in self.LOG_ICONS:
            text.append(f"{self.LOG_ICONS[level]} ", style=self.LOG_STYLES.get(level, "white"))
            text.append(message, style=style or self.LOG_STYLES.get(level, "white"))
        elif style:
            text.append(message, style=style)
        else:
            text.append(message)

        self.write(text)

    def log_error(self, message: str) -> None:
        """Write an error log message."""
        self.write_log(message, level="error")

    def log_warning(self, message: str) -> None:
        """Write a warning log message."""
        self.write_log(message, level="warning")

    def log_success(self, message: str) -> None:
        """Write a success log message."""
        self.write_log(message, level="success")

    def log_info(self, message: str) -> None:
        """Write an info log message."""
        self.write_log(message, level="info")

    def log_debug(self, message: str) -> None:
        """Write a debug log message."""
        self.write_log(message, level="debug")

    def get_all_text(self) -> str:
        """Get all log text as a plain string for copying.

        Returns:
            All log content as plain text with newlines between lines.
        """
        text_lines = []
        for strip in self.lines:
            # Strip objects have a 'text' property that returns plain text
            if hasattr(strip, "text"):
                text_lines.append(strip.text)
            else:
                text_lines.append(str(strip))
        return "\n".join(text_lines)
