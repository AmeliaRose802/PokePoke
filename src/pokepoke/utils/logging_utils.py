"""Logging utilities for PokePoke - File-based logging for runs and work items."""

import logging
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from pokepoke.utils.logging_filters import JsonFormatter, WorkItemFilter

if TYPE_CHECKING:
    from pokepoke.otel_config import OtelConfig
    from pokepoke.types import SessionStats


# Re-export so existing ``from pokepoke.utils.logging_utils import …`` still works.
__all__ = [
    "ItemLogger",
    "JsonFormatter",
    "RunLogger",
    "WorkItemFilter",
    "configure_logging",
]


def configure_logging(
    log_file: Path | str,
    console_level: int = logging.WARNING,
    json_output: bool = False,
    otel_config: 'OtelConfig | None' = None,
) -> None:
    """Configure Python logging handlers for a PokePoke entry point.

    Attaches a :class:`WorkItemFilter` to every handler so that all records
    carry ``work_item_id``, ``repo_name``, and ``agent_type``.  When
    *json_output* is True the file handler uses :class:`JsonFormatter`.

    When *otel_config* is supplied and enabled, an OpenTelemetry logging
    handler is added to the root logger so that every log record is also
    exported to the configured OTEL backend.
    """
    log_file = Path(log_file)
    log_file.parent.mkdir(parents=True, exist_ok=True)

    text_format = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"

    logging.basicConfig(
        level=logging.DEBUG,
        format=text_format,
        filename=str(log_file),
        filemode="w",
    )

    root = logging.getLogger()

    # Ensure the WorkItemFilter is attached to every root handler exactly once
    work_item_filter = WorkItemFilter()
    for handler in root.handlers:
        if not any(isinstance(f, WorkItemFilter) for f in handler.filters):
            handler.addFilter(work_item_filter)

    # Apply JSON formatter to the file handler when requested
    if json_output:
        for handler in root.handlers:
            if isinstance(handler, logging.FileHandler):
                handler.setFormatter(JsonFormatter())

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
        if not any(isinstance(f, WorkItemFilter) for f in console.filters):
            console.addFilter(WorkItemFilter())
        pokepoke_logger.addHandler(console)

    # Set up OpenTelemetry logging handler if configured
    if otel_config is not None:
        from pokepoke.utils.otel_logging import setup_otel_logging

        otel_handler = setup_otel_logging(otel_config)
        if otel_handler is not None:
            if not any(isinstance(f, WorkItemFilter) for f in otel_handler.filters):
                otel_handler.addFilter(WorkItemFilter())
            root.addHandler(otel_handler)


class RunLogger:
    """Manages logging for a PokePoke run with per-item subdirectories.

    Orchestrator events are emitted via :mod:`logging` so callers can adjust
    verbosity, attach handlers, or filter by module name.
    """

    DEFAULT_POLL_LOG_INTERVAL = 50

    def __init__(
        self,
        base_dir: str = ".pokepoke/logs",
        poll_log_interval: int | None = None,
        repo_name: str = "",
    ):
        """Initialize the run logger."""
        self.repo_name = repo_name
        self.run_id = self._generate_run_id()
        self.base_dir = Path(base_dir).resolve()
        self.run_dir = self.base_dir / self.run_id
        self.run_dir.mkdir(parents=True, exist_ok=True)

        self.orchestrator_log_path = self.run_dir / "orchestrator.log"
        self.item_logs_dir = self.run_dir / "items"
        self.item_logs_dir.mkdir(exist_ok=True)
        self.maintenance_logs_dir = self.run_dir / "maintenance"
        self.maintenance_logs_dir.mkdir(exist_ok=True)

        self._poll_cycle: int = 0
        self._poll_log_interval: int = poll_log_interval if poll_log_interval is not None else self.DEFAULT_POLL_LOG_INTERVAL
        self._idle_since: float | None = None

        # Run-scoped logger; messages propagate to pokepoke.orchestration.orchestrator / root.
        self._py_logger = logging.getLogger(
            f"pokepoke.orchestration.orchestrator.run_{self.run_id}"
        )
        self._py_logger.setLevel(logging.DEBUG)

        self._orch_handler = logging.FileHandler(
            self.orchestrator_log_path, mode="w", encoding="utf-8"
        )
        self._orch_handler.setLevel(logging.DEBUG)
        self._orch_handler.setFormatter(logging.Formatter(
            "[%(asctime)s] [%(levelname)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        ))
        self._orch_handler.addFilter(WorkItemFilter())
        self._py_logger.addHandler(self._orch_handler)

        self._init_orchestrator_log()

    def _generate_run_id(self) -> str:
        """Generate a unique run ID in format: YYYYMMDD_HHMMSS_<short-uuid>."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        short_uuid = str(uuid.uuid4())[:8]
        return f"{timestamp}_{short_uuid}"

    def _init_orchestrator_log(self) -> None:
        """Write decorative header directly to the handler's stream."""
        repo_line = f"Repository: {self.repo_name}\n" if self.repo_name else ""
        self._orch_handler.stream.write(
            f"{'=' * 80}\nPokePoke Orchestrator Log\n{'=' * 80}\n"
            f"Run ID: {self.run_id}\n{repo_line}"
            f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"{'=' * 80}\n\n"
        )
        self._orch_handler.stream.flush()

    def log_orchestrator(self, message: str, level: str = "INFO") -> None:
        """Log an orchestrator event through Python's standard logging."""
        from pokepoke.stats.metrics_context import get_current_repo_name

        repo = self.repo_name or get_current_repo_name()
        repo_tag = f"[{repo}] " if repo else ""

        py_level = getattr(logging, level.upper(), logging.INFO)
        self._py_logger.log(py_level, "%s%s", repo_tag, message)

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
            from pokepoke.agents.agent_context import get_agent_name

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
            from pokepoke.agents.agent_context import get_agent_name

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
        sep = "=" * 60
        for line in (sep, "Run Summary", sep,
                     f"Completed: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                     f"Items completed: {items_completed}",
                     f"Total agent requests: {total_requests}",
                     f"Total time: {elapsed / 60:.1f} minutes", sep):
            self.log_orchestrator(line)

        if session_stats is not None:
            try:
                from pokepoke.stats.stats import save_session_stats_to_disk
                stats_path = save_session_stats_to_disk(
                    self.run_dir, session_stats, elapsed, items_completed, total_requests
                )
                self.log_orchestrator(f"Session stats saved to {stats_path}")
            except Exception as e:
                self.log_orchestrator(f"Failed to save session stats: {e}", level="ERROR")

        self.log_orchestrator("PokePoke run completed")

    def get_run_id(self) -> str:
        return self.run_id

    def get_run_dir(self) -> Path:
        return self.run_dir

    # -- resource management ------------------------------------------------

    def close(self) -> None:
        """Remove and close the orchestrator file handler.  Safe to call multiple times."""
        handler = getattr(self, "_orch_handler", None)
        if handler is not None and handler in self._py_logger.handlers:
            self._py_logger.removeHandler(handler)
            handler.close()

    def __enter__(self) -> 'RunLogger':
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


class ItemLogger:
    """Manages logging for a single work item's agent interactions."""

    def __init__(
        self,
        logs_dir: Path,
        item_id: str,
        item_title: str,
        agent_name: str | None = None,
    ):
        self.item_id = item_id
        self.item_title = item_title
        self.agent_name = agent_name

        safe_logger_id = item_id.replace('/', '.').replace('\\', '.')
        self._py_logger = logging.getLogger(f"pokepoke.item.{safe_logger_id}")

        safe_id = item_id.replace('/', '_').replace('\\', '_')
        filename = safe_id
        if agent_name:
            filename = f"{filename}_{self._sanitize_agent_component(agent_name)}"
        self.log_path = logs_dir / f"{filename}.log"

        agent_hdr = f"Agent: {agent_name}\n{'=' * 80}\n" if agent_name else ""
        with open(self.log_path, 'w', encoding='utf-8') as f:
            f.write(
                f"{'=' * 80}\nWork Item: {item_id}\nTitle: {item_title}\n"
                f"{'=' * 80}\n{agent_hdr}"
                f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                f"{'=' * 80}\n\n"
            )

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

        log_level = logging.DEBUG if success else logging.WARNING
        self._py_logger.log(log_level, "TOOL %s %s(%s) result=%s", status, tool_name, args, result)

    def log_error(self, error_msg: str) -> None:
        """Log an error event from the agent session."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(self.log_path, 'a', encoding='utf-8') as f:
            f.write(f"\n[{timestamp}] [ERROR] {error_msg}\n")

        self._py_logger.error("%s", error_msg)

    def log_summary(self, success: bool, request_count: int) -> None:
        """Log summary information for the work item."""
        status = "SUCCESS" if success else "FAILURE"
        with open(self.log_path, 'a', encoding='utf-8') as f:
            f.write(
                f"\n{'=' * 80}\nSummary\n{'=' * 80}\n"
                f"Completed: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                f"Status: {status}\nAgent requests: {request_count}\n"
                f"{'=' * 80}\n"
            )
        py_level = logging.INFO if success else logging.WARNING
        self._py_logger.log(py_level, "Item %s completed: status=%s requests=%d",
                            self.item_id, status, request_count)

    def close(self) -> None:
        pass

    @staticmethod
    def _sanitize_agent_component(agent_name: str) -> str:
        """Sanitize agent name for safe filename usage."""
        sanitized = ''.join(
            ch if ch.isalnum() or ch in {'-', '_'} else '_'
            for ch in agent_name.lower()
        ).strip('_')
        return sanitized or "agent"
