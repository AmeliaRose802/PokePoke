"""Type definitions for PokePoke orchestrator."""
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any, Literal

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

@dataclass
class CopilotResult:
    """Result from invoking Copilot CLI."""
    work_item_id: str
    success: bool
    output: str | None = None
    error: str | None = None
    validation_errors: list[str] | None = None
    attempt_count: int = 1
    is_rate_limited: bool = False  # True if error was due to rate limiting
    stats: AgentStats | None = None
    model: str | None = None  # Model used for this invocation
    session_id: str | None = None  # SDK session ID, reusable for resume on timeout
    last_output_summary: str | None = None  # Truncated output summary for retry context
    work_agent_outcome: WorkAgentOutcome | None = None  # Structured outcome from work agent

@dataclass
class GateAgentResult:
    """Result from running the gate agent."""
    success: bool
    reason: str
    stats: AgentStats | None = None
    crashed: bool = False
    is_timeout: bool = False
    session_id: str | None = None
    last_output_summary: str | None = None
    def __iter__(self) -> 'Iterator[Any]':
        return iter((self.success, self.reason, self.stats, self.crashed))
    def __len__(self) -> int:
        return 4
