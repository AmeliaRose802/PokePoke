"""Structured logging filters and formatters for PokePoke.

Provides :class:`WorkItemFilter` for injecting work-item correlation IDs
and other thread-local context into log records, and :class:`JsonFormatter`
for machine-readable JSON-lines output.
"""

import json
import logging
from datetime import datetime


class WorkItemFilter(logging.Filter):
    """Inject work_item_id, repo_name, and agent_type into every log record.

    Reads values from the thread-local context managed by
    :mod:`pokepoke.stats.metrics_context`.  Missing values default to empty
    strings so formatters can always reference the attributes.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        from pokepoke.stats.metrics_context import (
            get_current_agent_type,
            get_current_repo_name,
            get_current_work_item_id,
        )

        record.work_item_id = get_current_work_item_id(default="")
        record.repo_name = get_current_repo_name(default="")
        record.agent_type = get_current_agent_type(default="")
        return True


class EventFilter(logging.Filter):
    """Filter for important events: submissions, completions, errors, warnings.

    Routes messages to orchestrator-events.log. Accepts:
    - WARNING and ERROR level messages
    - INFO messages containing keywords: 'Started processing', 'completed',
      'Submitted', 'SUCCESS', 'FAILURE', 'Error', 'Failed'
    """

    EVENT_KEYWORDS = (
        'Started processing',
        'completed',
        'Submitted',
        'SUCCESS',
        'FAILURE',
        'Error',
        'Failed',
        'Entering idle',
        'Exiting idle',
        'Run Summary',
        'Items completed',
        'Total agent requests',
        'Total time',
        'Session stats',
    )

    def filter(self, record: logging.LogRecord) -> bool:
        # Accept all warnings and errors
        if record.levelno >= logging.WARNING:
            return True

        # Accept INFO messages with event keywords
        if record.levelno == logging.INFO:
            msg = record.getMessage()
            return any(keyword in msg for keyword in self.EVENT_KEYWORDS)

        # Reject DEBUG and other levels
        return False


class MaintenanceFilter(logging.Filter):
    """Filter for maintenance messages: cleanup locks, dirty repo waits, merge locks.

    Routes messages to orchestrator-maintenance.log. Accepts DEBUG/INFO messages
    containing maintenance keywords.
    """

    MAINTENANCE_KEYWORDS = (
        'Cleanup agent still holding lock',
        'still holding lock',
        'lock wait',
        'Waiting for cleanup',
        'dirty repo',
        'merge lock',
        '[MAINTENANCE:',
    )

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        return any(keyword in msg for keyword in self.MAINTENANCE_KEYWORDS)


class LifecycleFilter(logging.Filter):
    """Filter for lifecycle messages: poll iterations, memory tracking.

    Routes messages to orchestrator-lifecycle.log. Accepts DEBUG and INFO messages
    with lifecycle keywords (poll, memory, iteration).
    """

    LIFECYCLE_KEYWORDS = (
        '[poll #',
        'poll cycle',
        'Poll cycle',
        'memory',
        'Memory',
        'iteration',
    )

    def filter(self, record: logging.LogRecord) -> bool:
        # Accept DEBUG and INFO level with lifecycle keywords
        # Skip WARNING/ERROR to avoid duplicates with events log
        if record.levelno >= logging.WARNING:
            return False

        msg = record.getMessage()
        return any(keyword in msg for keyword in self.LIFECYCLE_KEYWORDS)


class JsonFormatter(logging.Formatter):
    """Emit each log record as a single JSON line.

    Includes the structured fields injected by :class:`WorkItemFilter`.
    """

    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(record.created).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        work_item_id = getattr(record, "work_item_id", "")
        if work_item_id:
            entry["work_item_id"] = work_item_id
        repo_name = getattr(record, "repo_name", "")
        if repo_name:
            entry["repo_name"] = repo_name
        agent_type = getattr(record, "agent_type", "")
        if agent_type:
            entry["agent_type"] = agent_type
        if record.exc_info and record.exc_info[1] is not None:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str)
