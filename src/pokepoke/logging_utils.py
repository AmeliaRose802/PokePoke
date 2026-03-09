"""Logging utilities for PokePoke - File-based logging for runs and work items."""

import logging
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING
import uuid

if TYPE_CHECKING:
    from pokepoke.types import SessionStats


def configure_logging(
    log_file: Path | str,
    console_level: int = logging.WARNING,
) -> None:
    """Configure Python logging handlers for a PokePoke entry point.

    Sets up two channels:
    1. FileHandler on the root logger at DEBUG level → *log_file*
    2. StreamHandler(sys.stderr) at *console_level* on the ``pokepoke`` logger

    Safe to call once per process.  ``basicConfig`` only acts when the root
    logger has no handlers, so repeated calls are benign.
    """
    log_file = Path(log_file)
    log_file.parent.mkdir(parents=True, exist_ok=True)

    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        filename=str(log_file),
        filemode="w",
    )

    pokepoke_logger = logging.getLogger("pokepoke")
    # Avoid duplicate console handlers on repeated calls
    has_console = any(
        isinstance(h, logging.StreamHandler)
        and not isinstance(h, logging.FileHandler)
        for h in pokepoke_logger.handlers
    )
    if not has_console:
        console = logging.StreamHandler(sys.stderr)
        console.setLevel(console_level)
        console.setFormatter(
            logging.Formatter("%(levelname)s: %(name)s: %(message)s")
        )
        pokepoke_logger.addHandler(console)


class RunLogger:
    """Manages logging for a PokePoke run.

    Creates a unique directory for each run and manages two types of logs:
    1. Orchestrator log - High-level actions taken by PokePoke (no agent output)
    2. Per-item logs - Detailed agent output for each work item processed
    """

    # Default: only log polling messages at INFO every Nth cycle
    DEFAULT_POLL_LOG_INTERVAL = 50

    def __init__(self, base_dir: str = ".pokepoke/logs", poll_log_interval: int | None = None):
        """Initialize the run logger.

        Args:
            base_dir: Base directory for all log runs (default: ".pokepoke/logs")
            poll_log_interval: Log polling messages at INFO every N cycles (default: 50).
                Other cycles are logged at DEBUG.
        """
        self.run_id = self._generate_run_id()
        # Use absolute path to avoid issues when CWD changes during workflow
        self.base_dir = Path(base_dir).resolve()
        self.run_dir = self.base_dir / self.run_id
        self.run_dir.mkdir(parents=True, exist_ok=True)

        # Create log files
        self.orchestrator_log_path = self.run_dir / "orchestrator.log"
        self.item_logs_dir = self.run_dir / "items"
        self.item_logs_dir.mkdir(exist_ok=True)
        self.maintenance_logs_dir = self.run_dir / "maintenance"
        self.maintenance_logs_dir.mkdir(exist_ok=True)

        # Idle polling state
        self._poll_cycle: int = 0
        self._poll_log_interval: int = poll_log_interval if poll_log_interval is not None else self.DEFAULT_POLL_LOG_INTERVAL
        self._idle_since: float | None = None

        # Write initial orchestrator log entry
        self._init_orchestrator_log()

    def _generate_run_id(self) -> str:
        """Generate a unique run ID in format: YYYYMMDD_HHMMSS_<short-uuid>."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        short_uuid = str(uuid.uuid4())[:8]
        return f"{timestamp}_{short_uuid}"

    def _init_orchestrator_log(self) -> None:
        """Write initial header to orchestrator log."""
        with open(self.orchestrator_log_path, 'w', encoding='utf-8') as f:
            f.write("=" * 80 + "\n")
            f.write("PokePoke Orchestrator Log\n")
            f.write("=" * 80 + "\n")
            f.write(f"Run ID: {self.run_id}\n")
            f.write(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write("=" * 80 + "\n\n")

    def log_orchestrator(self, message: str, level: str = "INFO") -> None:
        """Log a message to the orchestrator log.

        Args:
            message: Message to log
            level: Log level (INFO, WARNING, ERROR, etc.)
        """
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.orchestrator_log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.orchestrator_log_path, 'a', encoding='utf-8') as f:
            f.write(f"[{timestamp}] [{level}] {message}\n")

    def log_polling(self, message: str) -> None:
        """Log a polling-loop message; INFO every Nth cycle, DEBUG otherwise."""
        self._poll_cycle += 1
        level = "INFO" if self._poll_cycle % self._poll_log_interval == 0 else "DEBUG"
        self.log_orchestrator(f"[poll #{self._poll_cycle}] {message}", level=level)

    def enter_idle(self) -> None:
        """Mark the start of an idle period. Subsequent calls are no-ops."""
        if self._idle_since is None:
            self._idle_since = time.time()
            self.log_orchestrator("Entering idle state — no work items available")

    def exit_idle(self) -> None:
        """Mark the end of an idle period, logging duration and poll count."""
        if self._idle_since is not None:
            elapsed = int(time.time() - self._idle_since)
            mins, secs = divmod(elapsed, 60)
            hours, mins = divmod(mins, 60)
            if hours > 0:
                dur = f"{hours}h {mins}m {secs}s"
            elif mins > 0:
                dur = f"{mins}m {secs}s"
            else:
                dur = f"{secs}s"
            self.log_orchestrator(
                f"Exiting idle state — was idle for {dur} "
                f"({self._poll_cycle} poll cycles)"
            )
            self._idle_since = None
            self._poll_cycle = 0

    def _get_item_dir(self, item_id: str) -> Path:
        """Return the per-item log directory, creating it if needed."""
        safe_id = item_id.replace('/', '_').replace('\\', '_')
        item_dir = self.item_logs_dir / safe_id
        item_dir.mkdir(exist_ok=True)
        return item_dir

    def start_item_phase_log(
        self,
        item_id: str,
        item_title: str,
        phase: str,
        attempt: int = 1,
        agent_name: str | None = None,
    ) -> 'ItemLogger':
        """Start logging for a specific work item phase/attempt."""
        if agent_name is None:
            # Defer import to avoid circular dependency at module load
            from pokepoke.agent_context import get_agent_name

            agent_name = get_agent_name(default="agent")

        item_dir = self._get_item_dir(item_id)
        safe_phase = phase.lower()
        attempt_index = attempt if attempt >= 1 else 1
        phase_item_id = f"{item_id}__{safe_phase}_attempt_{attempt_index}"
        if agent_name:
            safe_agent = ItemLogger._sanitize_agent_component(agent_name)
            phase_item_id = f"{phase_item_id}_{safe_agent}"

        return ItemLogger(
            item_dir,
            phase_item_id,
            item_title,
            agent_name=agent_name,
        )

    def start_item_log(
        self,
        item_id: str,
        item_title: str,
        agent_name: str | None = None,
    ) -> 'ItemLogger':
        """Start logging for a specific work item."""
        if agent_name is None:
            # Defer import to avoid circular dependency at module load
            from pokepoke.agent_context import get_agent_name

            agent_name = get_agent_name(default="agent")

        item_logger = ItemLogger(
            self.item_logs_dir,
            item_id,
            item_title,
            agent_name=agent_name,
        )

        agent_suffix = f" (agent: {agent_name})" if agent_name else ""
        self.log_orchestrator(
            f"Started processing work item: {item_id} - {item_title}{agent_suffix}"
        )
        return item_logger

    def log_maintenance(self, agent_type: str, message: str) -> None:
        """Log a maintenance agent action."""
        self.log_orchestrator(f"[MAINTENANCE:{agent_type}] {message}")

    def start_maintenance_log(self, agent_name: str) -> 'ItemLogger':
        """Start logging for a maintenance agent under maintenance/ subdirectory."""
        safe_name = agent_name.lower().replace(' ', '_')
        return ItemLogger(
            self.maintenance_logs_dir,
            safe_name,
            f"{agent_name} Maintenance Agent"
        )

    def finalize(self, items_completed: int, total_requests: int, elapsed: float,
                 session_stats: 'SessionStats | None' = None) -> None:
        """Write final summary to orchestrator log and persist stats to disk."""
        with open(self.orchestrator_log_path, 'a', encoding='utf-8') as f:
            f.write("\n" + "=" * 80 + "\n")
            f.write("Run Summary\n")
            f.write("=" * 80 + "\n")
            f.write(f"Completed: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Items completed: {items_completed}\n")
            f.write(f"Total agent requests: {total_requests}\n")
            f.write(f"Total time: {elapsed / 60:.1f} minutes\n")
            f.write("=" * 80 + "\n")

        # Persist session stats to stats.json
        if session_stats is not None:
            try:
                from pokepoke.stats import save_session_stats_to_disk
                stats_path = save_session_stats_to_disk(
                    self.run_dir, session_stats, elapsed, items_completed, total_requests
                )
                self.log_orchestrator(f"Session stats saved to {stats_path}")
            except Exception as e:
                self.log_orchestrator(f"Failed to save session stats: {e}", level="ERROR")

        self.log_orchestrator("PokePoke run completed")

    def get_run_id(self) -> str:
        """Get the run ID for this logger."""
        return self.run_id

    def get_run_dir(self) -> Path:
        """Get the run directory path."""
        return self.run_dir


class ItemLogger:
    """Manages logging for a single work item's agent interactions."""

    def __init__(
        self,
        logs_dir: Path,
        item_id: str,
        item_title: str,
        agent_name: str | None = None,
    ):
        """Initialize the item logger."""
        self.item_id = item_id
        self.item_title = item_title
        self.agent_name = agent_name

        # Create log file with sanitized filename
        safe_id = item_id.replace('/', '_').replace('\\', '_')
        filename = safe_id
        if agent_name:
            safe_agent = self._sanitize_agent_component(agent_name)
            filename = f"{filename}_{safe_agent}"
        self.log_path = logs_dir / f"{filename}.log"

        # Initialize log file
        with open(self.log_path, 'w', encoding='utf-8') as f:
            f.write("=" * 80 + "\n")
            f.write(f"Work Item: {item_id}\n")
            f.write(f"Title: {item_title}\n")
            f.write("=" * 80 + "\n")
            if agent_name:
                f.write(f"Agent: {agent_name}\n")
                f.write("=" * 80 + "\n")
            f.write(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write("=" * 80 + "\n\n")

    def log(self, message: str) -> None:
        """Log a message to the item log."""
        with open(self.log_path, 'a', encoding='utf-8') as f:
            f.write(message)

    def log_copilot_output(self, text: str) -> None:
        """Log streamed agent output text."""
        with open(self.log_path, 'a', encoding='utf-8') as f:
            f.write(text)

    def log_tool_call(self, tool_name: str, args: str, result: str | None = None,
                      success: bool = True) -> None:
        """Log a tool invocation and optional result."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        status = "✅" if success else "❌"
        with open(self.log_path, 'a', encoding='utf-8') as f:
            f.write(f"\n[{timestamp}] [TOOL] {status} {tool_name}({args})\n")
            if result is not None:
                f.write(f"[{timestamp}] [RESULT] {result}\n")

    def log_error(self, error_msg: str) -> None:
        """Log an error event from the agent session."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(self.log_path, 'a', encoding='utf-8') as f:
            f.write(f"\n[{timestamp}] [ERROR] {error_msg}\n")

    def log_summary(self, success: bool, request_count: int) -> None:
        """Log summary information for the work item."""
        with open(self.log_path, 'a', encoding='utf-8') as f:
            f.write("\n" + "=" * 80 + "\n")
            f.write("Summary\n")
            f.write("=" * 80 + "\n")
            f.write(f"Completed: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Status: {'SUCCESS' if success else 'FAILURE'}\n")
            f.write(f"Agent requests: {request_count}\n")
            f.write("=" * 80 + "\n")

    def close(self) -> None:
        """Close the item logger."""
        # Nothing to do - we use context managers for writes

    @staticmethod
    def _sanitize_agent_component(agent_name: str) -> str:
        """Sanitize agent name for safe filename usage."""
        sanitized_chars: list[str] = []
        for ch in agent_name.lower():
            if ch.isalnum() or ch in {'-', '_'}:
                sanitized_chars.append(ch)
            else:
                sanitized_chars.append('_')
        sanitized = ''.join(sanitized_chars).strip('_')
        return sanitized or "agent"
