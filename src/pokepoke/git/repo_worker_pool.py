"""Per-repo worker pool allocation and rebalancing.

Partitions a global worker budget across repositories based on configured
priority weights and per-repo max_workers caps.  When a repo exhausts its
ready queue the pool dynamically reallocates idle slots to repos that still
have work.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from pathlib import Path

from pokepoke.config import RepoConfig

logger = logging.getLogger(__name__)


@dataclass
class RepoWorkerAllocation:
    """Tracks worker allocation state for a single repository."""

    repo_path: str
    repo_name: str
    max_workers: int  # Per-repo cap (0 = uncapped, limited only by global budget)
    priority_weight: int
    base_allocation: int = 0  # Proportional share before rebalancing
    allocated_workers: int = 0  # Slots currently assigned to this repo
    active_workers: int = 0  # Workers actively running for this repo
    ready_item_count: int = 0  # Last known count of ready items


def _derive_repo_name(config: RepoConfig) -> str:
    """Derive a human-readable repo name from the path."""
    if not config.path:
        return ""
    return Path(config.path).name or config.path


class RepoWorkerPool:
    """Manages per-repo worker allocation with dynamic rebalancing.

    Workers are initially distributed proportionally to each repo's
    ``priority_weight``.  A periodic ``rebalance`` call checks which repos
    have ready items and redistributes idle (allocated but unused) slots from
    repos with no work to repos that still need workers.

    Per-repo ``max_workers`` caps are always respected, even during
    rebalancing — a repo never receives more slots than its cap allows.
    """

    def __init__(self, total_workers: int, repos: list[RepoConfig]) -> None:
        self._total_workers = max(1, total_workers)
        self._repos = [r for r in repos if r.enabled]
        self._allocations: dict[str, RepoWorkerAllocation] = {}
        self._lock = threading.Lock()
        self._initial_allocate()

    # -- public query API ---------------------------------------------------

    @property
    def total_workers(self) -> int:
        return self._total_workers

    def available_slots(self, repo_path: str) -> int:
        """Return the number of dispatch slots available for *repo_path*."""
        with self._lock:
            alloc = self._allocations.get(repo_path)
            if alloc is None:
                return 0
            return max(0, alloc.allocated_workers - alloc.active_workers)

    def get_allocation(self, repo_path: str) -> RepoWorkerAllocation | None:
        """Return a snapshot of the allocation for one repo (or ``None``)."""
        with self._lock:
            alloc = self._allocations.get(repo_path)
            if alloc is None:
                return None
            return RepoWorkerAllocation(
                repo_path=alloc.repo_path,
                repo_name=alloc.repo_name,
                max_workers=alloc.max_workers,
                priority_weight=alloc.priority_weight,
                base_allocation=alloc.base_allocation,
                allocated_workers=alloc.allocated_workers,
                active_workers=alloc.active_workers,
                ready_item_count=alloc.ready_item_count,
            )

    def get_all_allocations(self) -> dict[str, RepoWorkerAllocation]:
        """Return snapshots for every tracked repo."""
        with self._lock:
            return {
                path: RepoWorkerAllocation(
                    repo_path=a.repo_path,
                    repo_name=a.repo_name,
                    max_workers=a.max_workers,
                    priority_weight=a.priority_weight,
                    base_allocation=a.base_allocation,
                    allocated_workers=a.allocated_workers,
                    active_workers=a.active_workers,
                    ready_item_count=a.ready_item_count,
                )
                for path, a in self._allocations.items()
            }

    # -- worker lifecycle ---------------------------------------------------

    def record_worker_start(self, repo_path: str) -> None:
        """Record that a worker started executing for *repo_path*."""
        with self._lock:
            alloc = self._allocations.get(repo_path)
            if alloc is not None:
                alloc.active_workers += 1

    def record_worker_done(self, repo_path: str) -> None:
        """Record that a worker finished (success or failure) for *repo_path*."""
        with self._lock:
            alloc = self._allocations.get(repo_path)
            if alloc is not None:
                alloc.active_workers = max(0, alloc.active_workers - 1)

    # -- rebalancing --------------------------------------------------------

    def rebalance(self, repo_ready_counts: dict[str, int]) -> dict[str, int]:
        """Rebalance worker allocations based on current ready-item counts.

        Repos with no ready items donate their idle (allocated − active) slots
        to repos that still have work, weighted by ``priority_weight``.  Per-repo
        ``max_workers`` caps are respected.

        Args:
            repo_ready_counts: Mapping of repo_path → number of ready items.

        Returns:
            Mapping of repo_path → new allocated_workers after rebalancing.
        """
        with self._lock:
            return self._rebalance_locked(repo_ready_counts)

    # -- internals ----------------------------------------------------------

    def _initial_allocate(self) -> None:
        """Distribute workers proportionally by priority_weight."""
        if not self._repos:
            return

        total_weight = sum(r.priority_weight for r in self._repos)

        for repo in self._repos:
            name = _derive_repo_name(repo)
            self._allocations[repo.path] = RepoWorkerAllocation(
                repo_path=repo.path,
                repo_name=name,
                max_workers=repo.max_workers,
                priority_weight=repo.priority_weight,
            )

        # Proportional allocation with largest-remainder distribution
        raw: list[tuple[str, float]] = []
        for repo in self._repos:
            share = (repo.priority_weight / total_weight) * self._total_workers
            raw.append((repo.path, share))

        # Integer floors first
        allocated = 0
        floors: dict[str, int] = {}
        for path, share in raw:
            floor_val = int(share)
            alloc = self._allocations[path]
            if alloc.max_workers > 0:
                floor_val = min(floor_val, alloc.max_workers)
            floors[path] = floor_val
            allocated += floor_val

        # Distribute remainder by largest fractional part
        remainder = self._total_workers - allocated
        if remainder > 0:
            remainders = [
                (path, share - floors[path])
                for path, share in raw
            ]
            remainders.sort(key=lambda x: -x[1])
            for path, _ in remainders:
                if remainder <= 0:
                    break
                alloc = self._allocations[path]
                cap = alloc.max_workers if alloc.max_workers > 0 else self._total_workers
                if floors[path] < cap:
                    floors[path] += 1
                    remainder -= 1

        for path, count in floors.items():
            alloc = self._allocations[path]
            alloc.base_allocation = count
            alloc.allocated_workers = count

    def _rebalance_locked(self, repo_ready_counts: dict[str, int]) -> dict[str, int]:
        """Core rebalancing logic — must be called under ``_lock``."""
        # Update ready counts
        for path, alloc in self._allocations.items():
            alloc.ready_item_count = repo_ready_counts.get(path, 0)

        # Identify idle (donatable) slots from repos with no ready items
        idle_slots = 0
        for alloc in self._allocations.values():
            if alloc.ready_item_count == 0:
                donatable = max(0, alloc.allocated_workers - alloc.active_workers)
                alloc.allocated_workers -= donatable
                idle_slots += donatable

        if idle_slots == 0:
            return {p: a.allocated_workers for p, a in self._allocations.items()}

        # Distribute idle slots to repos that have work, proportional to weight
        needy = [
            a for a in self._allocations.values()
            if a.ready_item_count > 0
        ]
        if not needy:
            # No repos need work — restore base allocations
            self._restore_base_allocations()
            return {p: a.allocated_workers for p, a in self._allocations.items()}

        total_needy_weight = sum(a.priority_weight for a in needy)
        remaining = idle_slots

        # Sort by weight descending for fair distribution
        needy.sort(key=lambda a: -a.priority_weight)

        for alloc in needy:
            if remaining <= 0:
                break
            cap = alloc.max_workers if alloc.max_workers > 0 else self._total_workers
            headroom = max(0, cap - alloc.allocated_workers)
            # Proportional share of idle slots, capped by headroom and need
            share = max(1, round((alloc.priority_weight / total_needy_weight) * idle_slots))
            grant = min(share, headroom, remaining, alloc.ready_item_count)
            alloc.allocated_workers += grant
            remaining -= grant

        # If there are still remaining slots (due to caps), do a greedy pass
        if remaining > 0:
            for alloc in needy:
                if remaining <= 0:
                    break
                cap = alloc.max_workers if alloc.max_workers > 0 else self._total_workers
                headroom = max(0, cap - alloc.allocated_workers)
                grant = min(headroom, remaining)
                alloc.allocated_workers += grant
                remaining -= grant

        logger.debug(
            "Rebalanced workers: %s",
            {p: a.allocated_workers for p, a in self._allocations.items()},
        )

        return {p: a.allocated_workers for p, a in self._allocations.items()}

    def _restore_base_allocations(self) -> None:
        """Reset all repos to their base (proportional) allocations."""
        for alloc in self._allocations.values():
            alloc.allocated_workers = alloc.base_allocation
