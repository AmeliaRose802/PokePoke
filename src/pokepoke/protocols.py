"""Protocol interfaces for external dependencies.

Defines structural typing contracts for beads operations and parallel-loop
callbacks so that orchestration code can depend on abstractions rather than
concrete module functions.
"""

from __future__ import annotations

import concurrent.futures
import subprocess
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from pokepoke.types import WorkItemResult
from pokepoke.types_beads import BeadsWorkItem, IssueWithDependencies, RecordFn
from pokepoke.types_stats import BeadsStats, SessionStats

if TYPE_CHECKING:
    from pokepoke.utils.logging_utils import RunLogger

# ---------------------------------------------------------------------------
# Beads
# ---------------------------------------------------------------------------


class BeadsClient(Protocol):
    """Structural interface for beads issue-tracker operations."""

    def get_ready_work_items(self) -> list[BeadsWorkItem] | None: ...

    def assign_and_sync_item(
        self, item_id: str, agent_name: str | None = None
    ) -> bool: ...

    def close_item(self, item_id: str, reason: str) -> bool: ...

    def add_comment(self, item_id: str, message: str) -> bool: ...

    def get_item_comments(self, item_id: str) -> list[dict[str, Any]]: ...

    def block_item(self, item_id: str, reason: str) -> bool: ...

    def defer_item(self, item_id: str, reason: str) -> bool: ...

    def unassign_item(self, item_id: str) -> bool: ...

    def unassign_with_retry(self, item_id: str) -> bool: ...

    def is_item_claimable(self, item_id: str) -> bool: ...

    def select_next_hierarchical_item(
        self, items: list[BeadsWorkItem]
    ) -> BeadsWorkItem | None: ...

    def get_beads_stats(self) -> BeadsStats | None: ...

    def get_issue_dependencies(
        self, issue_id: str
    ) -> IssueWithDependencies | None: ...

    def increment_total_attempts(self, item_id: str) -> bool: ...

    def fail_task(
        self, item_id: str, reason: str, agent_type: str = "work"
    ) -> bool: ...

    def retry_failed_unassigns(self) -> int: ...

    def get_failed_unassign_count(self) -> int: ...

    def run_bd_sync_with_retry(
        self,
        max_attempts: int = 3,
        base_delay: float = 0.5,
        timeout: int | None = 60,
    ) -> subprocess.CompletedProcess[str]: ...


# ---------------------------------------------------------------------------
# Parallel Support Callbacks
# ---------------------------------------------------------------------------

_Future = concurrent.futures.Future[WorkItemResult]


class CollectFn(Protocol):
    """Protocol for collecting completed futures and recording results."""
    def __call__(
        self,
        futures: dict[_Future, BeadsWorkItem],
        failed_claim_ids: set[str],
        total_requests: int,
        session_stats: SessionStats,
        run_logger: RunLogger,
        record_fn: RecordFn,
        lock: threading.Lock | None = None,
    ) -> tuple[int, bool, int, int]:
        """Collect completed futures.

        Returns (total_requests, any_success, success_count, failure_count).
        """
        ...


class BuildWorkerNameFn(Protocol):
    """Protocol for building worker names."""
    def __call__(self, base_agent_name: str, item_id: str, counter: int) -> str:
        """Build a worker name from base agent name, item ID, and counter."""
        ...


class ProcessItemFn(Protocol):
    """Protocol for processing work items in parallel workers."""
    def __call__(
        self,
        item: BeadsWorkItem,
        run_logger: RunLogger,
        semaphore: threading.Semaphore,
        worker_agent_name: str | None = None,
        repo_path: str | None = None,
    ) -> WorkItemResult:
        """Process a work item and return the result."""
        ...


class CheckAndCommitMainRepoFn(Protocol):
    """Protocol for checking and committing main repository."""
    def __call__(self, repo_path: Path, run_logger: RunLogger, /) -> bool:
        """Check main repository status and commit if needed.

        Returns True if successful, False otherwise.
        """
        ...


class GetReadyWorkItemsFn(Protocol):
    """Protocol for fetching ready work items from beads."""
    def __call__(self) -> list[BeadsWorkItem] | None:
        """Fetch and return list of ready work items."""
        ...


class FinalizeFn(Protocol):
    """Protocol for finalizing session and collecting stats."""
    def __call__(
        self,
        session_stats: SessionStats,
        start_time: float,
        items_completed: int,
        total_requests: int,
        run_logger: RunLogger,
    ) -> None:
        """Finalize session, print summary, and clean up."""
        ...
