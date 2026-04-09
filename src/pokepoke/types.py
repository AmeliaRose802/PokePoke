"""Type definitions for PokePoke orchestrator."""
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, Protocol

from pokepoke.git.merge_queue_stats import MergeQueueStats as MergeQueueStats  # re-export
from pokepoke.types_stats import AgentStats as AgentStats  # re-export
from pokepoke.types_stats import BeadsStats as BeadsStats  # re-export
from pokepoke.types_stats import ModelCompletionRecord as ModelCompletionRecord  # re-export
from pokepoke.types_stats import SessionStats as SessionStats  # re-export
from pokepoke.types_stats import SessionStatsSnapshot as SessionStatsSnapshot  # re-export
from pokepoke.types_stats import _AgentRunCountsMixin as _AgentRunCountsMixin  # re-export
from pokepoke.types_stats import _session_stats_init as _session_stats_init  # re-export
from pokepoke.work_agent_outcome import (
    WORK_AGENT_OUTCOME_STATUSES as WORK_AGENT_OUTCOME_STATUSES,
)
from pokepoke.work_agent_outcome import (
    WorkAgentOutcome as WorkAgentOutcome,
)
from pokepoke.work_agent_outcome import (
    parse_work_agent_outcome as parse_work_agent_outcome,
)

if TYPE_CHECKING:
    from pokepoke.utils.logging_utils import RunLogger


@dataclass
class BeadsWorkItem:
    """Represents a beads work item from bd ready --json."""
    id: str
    title: str
    status: str
    priority: int
    issue_type: str
    description: str | None = None
    owner: str | None = None
    assignee: str | None = None  # Agent actively working on it (pokepoke_agent_123)
    created_at: str | None = None
    created_by: str | None = None
    updated_at: str | None = None
    labels: list[str] | None = None
    metadata: dict[str, Any] | None = None  # Metadata from beads (gate_rejection_count, etc.)
    is_ephemeral: bool = False  # True for synthetic items (cleanup, maintenance) not in beads DB

@dataclass(frozen=True)
class BeadsCreatedItem:
    """A beads item created by an agent during the session."""
    id: str
    title: str = ""
    agent_type: str = "unknown"

@dataclass
class Dependency:
    """Represents a dependency relationship."""
    id: str
    title: str
    issue_type: str
    dependency_type: str  # parent, blocks, related, discovered-from
    status: str | None = None
    priority: int | None = None
    description: str | None = None
    owner: str | None = None
    created_at: str | None = None
    created_by: str | None = None
    updated_at: str | None = None
    labels: list[str] | None = None
    notes: str | None = None

@dataclass
class IssueWithDependencies:
    """Represents an issue with full dependency information from bd show --json."""
    id: str
    title: str
    status: str
    priority: int
    issue_type: str
    description: str | None = None
    dependencies: list[Dependency] | None = None
    dependents: list[Dependency] | None = None
    owner: str | None = None
    assignee: str | None = None  # Agent actively working on it (pokepoke_agent_123)
    created_at: str | None = None
    created_by: str | None = None
    updated_at: str | None = None
    labels: list[str] | None = None
    notes: str | None = None

@dataclass
class RetryConfig:
    """Configuration for retry logic with backoff.

    Supports two backoff modes:
    - ``"exponential"`` (default): ``initial_delay * backoff_factor ** attempt``
    - ``"linear"``: ``initial_delay * (attempt + 1)``
    """
    max_retries: int = 3
    initial_delay: float = 1.0  # seconds
    max_delay: float = 60.0  # seconds
    backoff_factor: float = 2.0
    jitter: bool = True  # Add random jitter to prevent thundering herd
    backoff_mode: Literal["exponential", "linear"] = "exponential"

@dataclass
class WorkItemResult:
    """Result of processing a single work item."""
    success: bool
    request_count: int
    stats: AgentStats | None = None
    cleanup_agent_runs: int = 0
    gate_agent_runs: int = 0
    model_completion: ModelCompletionRecord | None = None
    failure_reason: str | None = None


class RecordFn(Protocol):
    """Protocol for work item result recording callbacks.

    Used in parallel worker finalization to record completed work item results.
    The return value is ignored by callers.
    """
    def __call__(
        self,
        item: BeadsWorkItem,
        result: WorkItemResult,
        session_stats: "SessionStats",
        run_logger: "RunLogger",
    ) -> Any:
        """Record the result of processing a work item.

        Parameters
        ----------
        item : BeadsWorkItem
            The work item that was processed.
        result : WorkItemResult
            The result of processing the work item.
        session_stats : SessionStats
            Session statistics to update.
        run_logger : RunLogger
            Logger for orchestrator messages.

        Returns
        -------
        Any
            Return value is ignored by callers (may return None or tuple).
        """
        ...

# Re-exported from types_agent for backwards compatibility
from pokepoke.types_agent import CopilotResult as CopilotResult
from pokepoke.types_agent import GateAgentResult as GateAgentResult
