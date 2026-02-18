"""Type definitions for PokePoke orchestrator."""

import threading
from dataclasses import dataclass, field, replace, is_dataclass


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
    dependency_count: int | None = None
    dependent_count: int | None = None
    notes: str | None = None


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

    def accumulate(self, other: 'AgentStats') -> None:
        """Add all fields from another AgentStats into this one."""
        self.wall_duration += other.wall_duration
        self.api_duration += other.api_duration
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens
        self.lines_added += other.lines_added
        self.lines_removed += other.lines_removed
        self.premium_requests += other.premium_requests
        self.retries += other.retries
        self.tool_calls += other.tool_calls


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
    gate_passed: bool | None = None  # None = gate not run


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
    starting_beads_stats: BeadsStats | None = None
    ending_beads_stats: BeadsStats | None = None
    model_completions: tuple[ModelCompletionRecord, ...] = ()


@dataclass
class SessionStats:
    """Combined session statistics including agent stats and run counts."""
    agent_stats: AgentStats
    items_completed: int = 0  # Number of items successfully completed in this session
    completed_items_list: list[BeadsWorkItem] = field(default_factory=list)  # List of items successfully completed
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
    starting_beads_stats: BeadsStats | None = None
    ending_beads_stats: BeadsStats | None = None
    model_completions: list[ModelCompletionRecord] = field(default_factory=list)
    _lock: threading.Lock = field(
        default_factory=threading.Lock, init=False, repr=False, compare=False
    )

    def record_completion(
        self, item: BeadsWorkItem, items_completed: int | None = None
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
            self.agent_stats.accumulate(item_stats)

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

    def set_starting_beads_stats(self, stats: BeadsStats | None) -> None:
        """Set starting beads statistics safely."""
        with self._lock:
            if stats is None:
                self.starting_beads_stats = None
            elif is_dataclass(stats):
                self.starting_beads_stats = replace(stats)
            else:
                self.starting_beads_stats = stats

    def set_ending_beads_stats(self, stats: BeadsStats | None) -> None:
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
    output: str | None = None
    error: str | None = None
    validation_errors: list[str] | None = None
    attempt_count: int = 1
    is_rate_limited: bool = False  # True if error was due to rate limiting
    stats: AgentStats | None = None
    model: str | None = None  # Model used for this invocation
