"""Type definitions for PokePoke orchestrator."""

import threading
from dataclasses import dataclass, field, replace, is_dataclass
from typing import Optional, List


@dataclass
class BeadsWorkItem:
    """Represents a beads work item from bd ready --json."""
    id: str
    title: str
    status: str
    priority: int
    issue_type: str
    description: Optional[str] = None
    owner: Optional[str] = None
    assignee: Optional[str] = None  # Agent actively working on it (pokepoke_agent_123)
    created_at: Optional[str] = None
    created_by: Optional[str] = None
    updated_at: Optional[str] = None
    labels: Optional[List[str]] = None
    dependency_count: Optional[int] = None
    dependent_count: Optional[int] = None
    notes: Optional[str] = None


@dataclass
class Dependency:
    """Represents a dependency relationship."""
    id: str
    title: str
    issue_type: str
    dependency_type: str  # parent, blocks, related, discovered-from
    status: Optional[str] = None
    priority: Optional[int] = None
    description: Optional[str] = None
    owner: Optional[str] = None
    created_at: Optional[str] = None
    created_by: Optional[str] = None
    updated_at: Optional[str] = None
    labels: Optional[List[str]] = None
    notes: Optional[str] = None


@dataclass
class IssueWithDependencies:
    """Represents an issue with full dependency information from bd show --json."""
    id: str
    title: str
    status: str
    priority: int
    issue_type: str
    description: Optional[str] = None
    dependencies: Optional[List[Dependency]] = None
    dependents: Optional[List[Dependency]] = None
    owner: Optional[str] = None
    assignee: Optional[str] = None  # Agent actively working on it (pokepoke_agent_123)
    created_at: Optional[str] = None
    created_by: Optional[str] = None
    updated_at: Optional[str] = None
    labels: Optional[List[str]] = None
    notes: Optional[str] = None


@dataclass
class RetryConfig:
    """Configuration for retry logic with exponential backoff."""
    max_retries: int = 3
    initial_delay: float = 1.0  # seconds
    max_delay: float = 60.0  # seconds
    backoff_factor: float = 2.0
    jitter: bool = True  # Add random jitter to prevent thundering herd


@dataclass
class AgentStats:
    """Statistics from agent execution."""
    wall_duration: float = 0.0  # seconds
    api_duration: float = 0.0  # seconds
    input_tokens: int = 0
    output_tokens: int = 0
    lines_added: int = 0
    lines_removed: int = 0
    premium_requests: int = 0
    retries: int = 0
    tool_calls: int = 0


@dataclass
class BeadsStats:
    """Statistics from beads database."""
    total_issues: int = 0
    open_issues: int = 0
    in_progress_issues: int = 0
    closed_issues: int = 0
    ready_issues: int = 0


@dataclass
class ModelCompletionRecord:
    """Record of a single work item completion for a specific model."""
    item_id: str
    model: str
    duration_seconds: float
    gate_passed: Optional[bool] = None  # None = gate not run


_AGENT_RUN_ATTRS = {
    "work": "work_agent_runs",
    "gate": "gate_agent_runs",
    "cleanup": "cleanup_agent_runs",
    "tech_debt": "tech_debt_agent_runs",
    "janitor": "janitor_agent_runs",
    "backlog_cleanup": "backlog_cleanup_agent_runs",
    "beta_tester": "beta_tester_agent_runs",
    "code_review": "code_review_agent_runs",
    "worktree_cleanup": "worktree_cleanup_agent_runs",
}


@dataclass(frozen=True)
class SessionStatsSnapshot:
    """Frozen snapshot of session stats for UI display."""
    agent_stats: AgentStats
    items_completed: int = 0
    completed_items_list: tuple[BeadsWorkItem, ...] = ()
    work_agent_runs: int = 0
    gate_agent_runs: int = 0
    tech_debt_agent_runs: int = 0
    janitor_agent_runs: int = 0
    janitor_lines_removed: int = 0
    backlog_cleanup_agent_runs: int = 0
    cleanup_agent_runs: int = 0
    beta_tester_agent_runs: int = 0
    code_review_agent_runs: int = 0
    worktree_cleanup_agent_runs: int = 0
    starting_beads_stats: Optional[BeadsStats] = None
    ending_beads_stats: Optional[BeadsStats] = None
    model_completions: tuple[ModelCompletionRecord, ...] = ()


@dataclass
class SessionStats:
    """Combined session statistics including agent stats and run counts."""
    agent_stats: AgentStats
    items_completed: int = 0  # Number of items successfully completed in this session
    completed_items_list: List[BeadsWorkItem] = field(default_factory=list)  # List of items successfully completed
    work_agent_runs: int = 0
    gate_agent_runs: int = 0
    tech_debt_agent_runs: int = 0
    janitor_agent_runs: int = 0
    janitor_lines_removed: int = 0
    backlog_cleanup_agent_runs: int = 0
    cleanup_agent_runs: int = 0
    beta_tester_agent_runs: int = 0
    code_review_agent_runs: int = 0
    worktree_cleanup_agent_runs: int = 0
    starting_beads_stats: Optional[BeadsStats] = None
    ending_beads_stats: Optional[BeadsStats] = None
    model_completions: List[ModelCompletionRecord] = field(default_factory=list)
    _lock: threading.Lock = field(
        default_factory=threading.Lock, init=False, repr=False, compare=False
    )

    def record_completion(
        self, item: BeadsWorkItem, items_completed: Optional[int] = None
    ) -> int:
        """Record a completed work item in a thread-safe way."""
        with self._lock:
            if items_completed is None:
                self.items_completed += 1
            else:
                if items_completed < 0:
                    raise ValueError("items_completed cannot be negative")
                self.items_completed = items_completed
            self.completed_items_list.append(replace(item))
            return self.items_completed

    def record_agent_run(self, agent_type: str, count: int = 1) -> None:
        """Increment agent run counts safely."""
        if count < 0:
            raise ValueError("count cannot be negative")
        if count == 0:
            return
        normalized = agent_type.lower().replace(" ", "_")
        attr = _AGENT_RUN_ATTRS.get(normalized)
        if attr is None:
            raise ValueError(f"Unknown agent type: {agent_type}")
        with self._lock:
            setattr(self, attr, getattr(self, attr) + count)

    def record_agent_stats(self, item_stats: AgentStats) -> None:
        """Aggregate per-item stats into the session totals."""
        with self._lock:
            self.agent_stats.wall_duration += item_stats.wall_duration
            self.agent_stats.api_duration += item_stats.api_duration
            self.agent_stats.input_tokens += item_stats.input_tokens
            self.agent_stats.output_tokens += item_stats.output_tokens
            self.agent_stats.lines_added += item_stats.lines_added
            self.agent_stats.lines_removed += item_stats.lines_removed
            self.agent_stats.premium_requests += item_stats.premium_requests
            self.agent_stats.tool_calls += item_stats.tool_calls
            self.agent_stats.retries += item_stats.retries

    def record_retries(self, retries: int) -> None:
        """Track extra retries for a work item."""
        if retries < 0:
            raise ValueError("retries cannot be negative")
        if retries == 0:
            return
        with self._lock:
            self.agent_stats.retries += retries

    def record_model_completion(self, completion: ModelCompletionRecord) -> None:
        """Record a model completion for A/B testing."""
        with self._lock:
            self.model_completions.append(replace(completion))

    def record_janitor_lines_removed(self, lines_removed: int) -> None:
        """Record lines removed by the Janitor agent."""
        with self._lock:
            self.janitor_lines_removed += lines_removed

    def set_starting_beads_stats(self, stats: Optional[BeadsStats]) -> None:
        """Set starting beads statistics safely."""
        with self._lock:
            if stats is None:
                self.starting_beads_stats = None
            elif is_dataclass(stats):
                self.starting_beads_stats = replace(stats)
            else:
                self.starting_beads_stats = stats

    def set_ending_beads_stats(self, stats: Optional[BeadsStats]) -> None:
        """Set ending beads statistics safely."""
        with self._lock:
            if stats is None:
                self.ending_beads_stats = None
            elif is_dataclass(stats):
                self.ending_beads_stats = replace(stats)
            else:
                self.ending_beads_stats = stats

    def snapshot(self) -> SessionStatsSnapshot:
        """Return a frozen snapshot for UI display without holding the lock."""
        with self._lock:
            return SessionStatsSnapshot(
                agent_stats=replace(self.agent_stats),
                items_completed=self.items_completed,
                completed_items_list=tuple(replace(item) for item in self.completed_items_list),
                work_agent_runs=self.work_agent_runs,
                gate_agent_runs=self.gate_agent_runs,
                tech_debt_agent_runs=self.tech_debt_agent_runs,
                janitor_agent_runs=self.janitor_agent_runs,
                janitor_lines_removed=self.janitor_lines_removed,
                backlog_cleanup_agent_runs=self.backlog_cleanup_agent_runs,
                cleanup_agent_runs=self.cleanup_agent_runs,
                beta_tester_agent_runs=self.beta_tester_agent_runs,
                code_review_agent_runs=self.code_review_agent_runs,
                worktree_cleanup_agent_runs=self.worktree_cleanup_agent_runs,
                starting_beads_stats=(
                    replace(self.starting_beads_stats)
                    if self.starting_beads_stats and is_dataclass(self.starting_beads_stats)
                    else self.starting_beads_stats
                ),
                ending_beads_stats=(
                    replace(self.ending_beads_stats)
                    if self.ending_beads_stats and is_dataclass(self.ending_beads_stats)
                    else self.ending_beads_stats
                ),
                model_completions=tuple(replace(mc) for mc in self.model_completions),
            )


@dataclass
class CopilotResult:
    """Result from invoking Copilot CLI."""
    work_item_id: str
    success: bool
    output: Optional[str] = None
    error: Optional[str] = None
    validation_errors: Optional[List[str]] = None
    attempt_count: int = 1
    is_rate_limited: bool = False  # True if error was due to rate limiting
    stats: Optional[AgentStats] = None
    model: Optional[str] = None  # Model used for this invocation
