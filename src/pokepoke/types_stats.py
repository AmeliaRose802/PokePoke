"""Stats and telemetry type definitions extracted from types.py."""
from __future__ import annotations

import threading
from dataclasses import dataclass, field, is_dataclass, replace
from typing import TYPE_CHECKING, Any, ClassVar

from pokepoke.agents.agent_types import (
    AGENT_TYPES,
    _empty_agent_run_counts,
    _normalize_agent_key,
    resolve_agent_type,
)
from pokepoke.git.merge_queue_stats import MergeQueueStats

if TYPE_CHECKING:
    from pokepoke.types import BeadsCreatedItem, BeadsWorkItem


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

    def accumulate(self, other: AgentStats) -> None:
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
    input_tokens: int = 0
    output_tokens: int = 0
    agent_turns: int = 0
    cost: float = 0.0
    retry_attempts: int = 0
    api_duration: float | None = None
    lines_added: int | None = None
    lines_removed: int | None = None
    gate_model: str | None = None  # Model used by the gate agent

class _AgentRunCountsMixin:
    """Shared agent-run-count accessors for frozen and mutable stats."""

    agent_run_counts: dict[str, int]

    def get_agent_run_count(self, agent_type: str) -> int:
        """Return the recorded run count for the requested agent (slug or display)."""
        key = agent_type if agent_type in AGENT_TYPES else resolve_agent_type(agent_type).key
        return self.agent_run_counts.get(key, 0)

    def __getattr__(self, name: str) -> Any:
        if name.endswith("_agent_runs"):
            key = name[: -len("_agent_runs")]
            if key in AGENT_TYPES:
                return self.agent_run_counts.get(key, 0)
        raise AttributeError(f"{self.__class__.__name__!s} object has no attribute {name!r}")


@dataclass(frozen=True)
class SessionStatsSnapshot(_AgentRunCountsMixin):
    """Frozen snapshot of session stats for UI display."""
    agent_stats: AgentStats
    items_completed: int = 0
    items_created: int = 0
    completed_items_list: tuple[BeadsWorkItem, ...] = ()
    created_items_list: tuple[BeadsCreatedItem, ...] = ()
    created_counts_by_agent_type: dict[str, int] = field(default_factory=dict)
    completed_counts_by_agent_type: dict[str, int] = field(default_factory=dict)
    lifetime_items_created: int = 0
    lifetime_items_completed: int = 0
    agent_run_counts: dict[str, int] = field(default_factory=_empty_agent_run_counts)
    janitor_lines_removed: int = 0
    agent_type_elapsed_seconds: dict[str, float] = field(default_factory=dict)
    starting_beads_stats: BeadsStats | None = None
    ending_beads_stats: BeadsStats | None = None
    model_completions: tuple[ModelCompletionRecord, ...] = ()
    merge_queue_stats: MergeQueueStats = field(default_factory=MergeQueueStats)

@dataclass
class SessionStats(_AgentRunCountsMixin):
    """Combined session statistics including agent stats and run counts."""

    # Maximum entries kept in each rolling list before evicting the oldest half.
    # Follows the same pattern as OperationTimingRegistry.max_samples.
    MAX_LIST_ENTRIES: ClassVar[int] = 500

    agent_stats: AgentStats

    # Per-session beads throughput
    items_completed: int = 0  # Number of items successfully completed in this session
    items_created: int = 0  # Number of beads items created by agents in this session
    completed_items_list: list[BeadsWorkItem] = field(default_factory=list)  # Completed items
    created_items_list: list[BeadsCreatedItem] = field(default_factory=list)  # Created items

    # Per-session breakdowns
    created_counts_by_agent_type: dict[str, int] = field(default_factory=dict)
    completed_counts_by_agent_type: dict[str, int] = field(default_factory=dict)

    # Lifetime totals (persisted)
    lifetime_items_created: int = 0
    lifetime_items_completed: int = 0

    # Agent runs
    agent_run_counts: dict[str, int] = field(default_factory=_empty_agent_run_counts)
    janitor_lines_removed: int = 0
    agent_type_elapsed_seconds: dict[str, float] = field(default_factory=dict)
    starting_beads_stats: BeadsStats | None = None
    ending_beads_stats: BeadsStats | None = None
    model_completions: list[ModelCompletionRecord] = field(default_factory=list)
    merge_queue_stats: MergeQueueStats = field(default_factory=MergeQueueStats)

    _created_item_ids: set[str] = field(default_factory=set, init=False, repr=False, compare=False)
    _lock: threading.Lock = field(
        default_factory=threading.Lock, init=False, repr=False, compare=False
    )

    def record_completion(
        self,
        item: BeadsWorkItem,
        items_completed: int | None = None,
        *,
        agent_type: str | None = None,
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
            if len(self.completed_items_list) >= self.MAX_LIST_ENTRIES:
                del self.completed_items_list[: len(self.completed_items_list) // 2]
            if agent_type:
                normalized = agent_type.strip().lower() or "unknown"
                self.completed_counts_by_agent_type[normalized] = (
                    self.completed_counts_by_agent_type.get(normalized, 0) + 1
                )
            return self.items_completed

    def record_created_item(self, item: BeadsCreatedItem) -> int:
        """Record a created beads item (deduped by id)."""
        with self._lock:
            if item.id in self._created_item_ids:
                return self.items_created
            self._created_item_ids.add(item.id)
            self.items_created += 1
            self.created_items_list.append(replace(item))
            if len(self.created_items_list) >= self.MAX_LIST_ENTRIES:
                del self.created_items_list[: len(self.created_items_list) // 2]
            normalized = (item.agent_type or "unknown").strip().lower() or "unknown"
            self.created_counts_by_agent_type[normalized] = (
                self.created_counts_by_agent_type.get(normalized, 0) + 1
            )

            return self.items_created

    def set_lifetime_beads_item_totals(self, *, created: int, completed: int) -> None:
        """Set lifetime created/completed totals (persisted across sessions)."""
        with self._lock:
            self.lifetime_items_created = int(created)
            self.lifetime_items_completed = int(completed)

    def record_agent_run(self, agent_type: str, count: int = 1) -> None:
        """Increment agent run counts safely."""
        if count < 0:
            raise ValueError("count cannot be negative")
        if count == 0:
            return
        agent = resolve_agent_type(agent_type if agent_type else "")
        with self._lock:
            self.agent_run_counts[agent.key] = self.agent_run_counts.get(agent.key, 0) + count

    def record_agent_elapsed_time(self, agent_type: str, elapsed_seconds: float) -> None:
        """Accumulate elapsed wall-clock seconds for an agent type."""
        if elapsed_seconds <= 0:
            return
        normalized = agent_type.lower().replace(" ", "_")
        with self._lock:
            self.agent_type_elapsed_seconds[normalized] = (
                self.agent_type_elapsed_seconds.get(normalized, 0.0) + elapsed_seconds
            )

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
            if len(self.model_completions) >= self.MAX_LIST_ENTRIES:
                del self.model_completions[: len(self.model_completions) // 2]

    def record_janitor_lines_removed(self, lines_removed: int) -> None:
        """Record lines removed by the Janitor agent."""
        with self._lock:
            self.janitor_lines_removed += lines_removed

    def _safe_copy_stats(self, stats: BeadsStats | None) -> BeadsStats | None:
        """Return a defensive copy of beads stats."""
        if stats is None:
            return None
        return replace(stats) if is_dataclass(stats) else stats

    def set_starting_beads_stats(self, stats: BeadsStats | None) -> None:
        """Set starting beads statistics safely."""
        with self._lock:
            self.starting_beads_stats = self._safe_copy_stats(stats)

    def set_ending_beads_stats(self, stats: BeadsStats | None) -> None:
        """Set ending beads statistics safely."""
        with self._lock:
            self.ending_beads_stats = self._safe_copy_stats(stats)

    def record_merge_queue_stats(self, stats: MergeQueueStats) -> None:
        """Copy merge queue stats into the session (called at shutdown)."""
        with self._lock:
            self.merge_queue_stats = stats.copy()

    def snapshot(self) -> SessionStatsSnapshot:
        """Return a frozen snapshot for UI display without holding the lock."""
        with self._lock:
            return SessionStatsSnapshot(
                agent_stats=replace(self.agent_stats),
                items_completed=self.items_completed,
                items_created=self.items_created,
                completed_items_list=tuple(replace(i) for i in self.completed_items_list),
                created_items_list=tuple(replace(i) for i in self.created_items_list),
                created_counts_by_agent_type=dict(self.created_counts_by_agent_type),
                completed_counts_by_agent_type=dict(self.completed_counts_by_agent_type),
                lifetime_items_created=self.lifetime_items_created,
                lifetime_items_completed=self.lifetime_items_completed,
                agent_run_counts=dict(self.agent_run_counts),
                janitor_lines_removed=self.janitor_lines_removed,
                agent_type_elapsed_seconds=dict(self.agent_type_elapsed_seconds),
                starting_beads_stats=self._safe_copy_stats(self.starting_beads_stats),
                ending_beads_stats=self._safe_copy_stats(self.ending_beads_stats),
                model_completions=tuple(replace(mc) for mc in self.model_completions),
                merge_queue_stats=self.merge_queue_stats.copy(),
            )

_SESSION_STATS_INIT = SessionStats.__init__

def _session_stats_init(self: SessionStats, *args: Any, **kwargs: Any) -> None:
    """Backwards-compatible __init__ supporting legacy *_agent_runs kwargs."""
    legacy = {_normalize_agent_key(k[:-len("_agent_runs")]): int(v)
              for k, v in kwargs.items() if k.endswith("_agent_runs")}
    cleaned = {k: v for k, v in kwargs.items() if not k.endswith("_agent_runs")}
    _SESSION_STATS_INIT(self, *args, **cleaned)
    for slug, count in legacy.items():
        if slug not in AGENT_TYPES:
            raise ValueError(f"Unknown agent type: {slug}")
        self.agent_run_counts[slug] = count

SessionStats.__init__ = _session_stats_init  # type: ignore[method-assign]
