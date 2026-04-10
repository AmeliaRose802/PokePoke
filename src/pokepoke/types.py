"""Type definitions for PokePoke orchestrator."""
from dataclasses import dataclass
from typing import Literal

from pokepoke.git.merge_queue_stats import MergeQueueStats as MergeQueueStats  # re-export
from pokepoke.types_beads import BeadsCreatedItem as BeadsCreatedItem  # re-export
from pokepoke.types_beads import BeadsWorkItem as BeadsWorkItem  # re-export
from pokepoke.types_beads import Dependency as Dependency  # re-export
from pokepoke.types_beads import IssueWithDependencies as IssueWithDependencies  # re-export
from pokepoke.types_beads import RecordFn as RecordFn  # re-export
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

# Re-exported from types_agent for backwards compatibility
from pokepoke.types_agent import CopilotResult as CopilotResult
from pokepoke.types_agent import GateAgentResult as GateAgentResult
