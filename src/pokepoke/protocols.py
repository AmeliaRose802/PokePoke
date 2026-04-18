"""Protocol interfaces for external dependencies.

Defines structural typing contracts for git and beads operations so that
orchestration code can depend on abstractions rather than concrete module
functions.  Default implementations delegate to the existing module-level
helpers.
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
# Git
# ---------------------------------------------------------------------------


class GitClient(Protocol):
    """Structural interface for git operations."""

    def run_git(
        self,
        cmd: list[str],
        *,
        timeout: int = 30,
        cwd: str | None = None,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]: ...

    def verify_branch_pushed(self, branch_name: str) -> bool: ...

    def list_worktrees(self, cwd: str | None = None) -> list[dict[str, str]]: ...


class DefaultGitClient:
    """Default :class:`GitClient` that delegates to module-level helpers."""

    def run_git(
        self,
        cmd: list[str],
        *,
        timeout: int = 30,
        cwd: str | None = None,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        from pokepoke.git.git_helpers import run_git

        return run_git(cmd, timeout=timeout, cwd=cwd, check=check)

    def verify_branch_pushed(self, branch_name: str) -> bool:
        from pokepoke.git.git_helpers import verify_branch_pushed

        return verify_branch_pushed(branch_name)

    def list_worktrees(self, cwd: str | None = None) -> list[dict[str, str]]:
        from pokepoke.git.git_helpers import list_worktrees

        return list_worktrees(cwd=cwd)


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


class DefaultBeadsClient:
    """Default :class:`BeadsClient` that delegates to module-level helpers."""

    def get_ready_work_items(self) -> list[BeadsWorkItem] | None:
        from pokepoke.beads.beads_query import get_ready_work_items

        return get_ready_work_items()

    def assign_and_sync_item(
        self, item_id: str, agent_name: str | None = None
    ) -> bool:
        from pokepoke.beads.beads_management import assign_and_sync_item

        return assign_and_sync_item(item_id, agent_name=agent_name)

    def close_item(self, item_id: str, reason: str) -> bool:
        from pokepoke.beads.beads_management import close_item

        return close_item(item_id, message=reason)

    def add_comment(self, item_id: str, message: str) -> bool:
        from pokepoke.beads.beads_management import add_comment

        return add_comment(item_id, comment=message)

    def get_item_comments(self, item_id: str) -> list[dict[str, Any]]:
        from pokepoke.beads.beads_query import get_item_comments

        return get_item_comments(item_id)

    def block_item(self, item_id: str, reason: str) -> bool:
        from pokepoke.beads.beads_management import block_item

        return block_item(item_id, reason=reason)

    def defer_item(self, item_id: str, reason: str) -> bool:
        from pokepoke.beads.beads_management import defer_item

        return defer_item(item_id, reason=reason)

    def unassign_item(self, item_id: str) -> bool:
        from pokepoke.beads.beads_management import unassign_item

        return unassign_item(item_id)

    def unassign_with_retry(self, item_id: str) -> bool:
        from pokepoke.beads.beads_manifest_utils import unassign_with_retry

        return unassign_with_retry(item_id)

    def is_item_claimable(self, item_id: str) -> bool:
        from pokepoke.beads.beads_management import is_item_claimable

        return is_item_claimable(item_id)

    def select_next_hierarchical_item(
        self, items: list[BeadsWorkItem]
    ) -> BeadsWorkItem | None:
        from pokepoke.beads.beads_management import select_next_hierarchical_item

        return select_next_hierarchical_item(items)

    def get_beads_stats(self) -> BeadsStats | None:
        from pokepoke.beads.beads_query import get_beads_stats

        return get_beads_stats()

    def get_issue_dependencies(
        self, issue_id: str
    ) -> IssueWithDependencies | None:
        from pokepoke.beads.beads_query import get_issue_dependencies

        return get_issue_dependencies(issue_id)

    def increment_total_attempts(self, item_id: str) -> bool:
        from pokepoke.beads.beads_management import increment_total_attempts

        return increment_total_attempts(item_id)

    def fail_task(
        self, item_id: str, reason: str, agent_type: str = "work"
    ) -> bool:
        from pokepoke.beads.beads_management import fail_task

        return fail_task(item_id, reason, agent_type=agent_type)

    def retry_failed_unassigns(self) -> int:
        from pokepoke.beads.beads_recovery import retry_failed_unassigns

        return retry_failed_unassigns()

    def get_failed_unassign_count(self) -> int:
        from pokepoke.beads.beads_recovery import get_failed_unassign_count

        return get_failed_unassign_count()

    def run_bd_sync_with_retry(
        self,
        max_attempts: int = 3,
        base_delay: float = 0.5,
        timeout: int | None = 60,
    ) -> subprocess.CompletedProcess[str]:
        from pokepoke.beads.beads_management import run_bd_sync_with_retry

        return run_bd_sync_with_retry(
            max_attempts=max_attempts,
            base_delay=base_delay,
            timeout=timeout,
        )


# ---------------------------------------------------------------------------
# Parallel Loop
# ---------------------------------------------------------------------------


class ParallelLoop(Protocol):
    """Structural interface for parallel orchestrator loop operations.

    Defines the contract between parallel.py and orchestrator.py for running
    multiple work items concurrently with a ThreadPoolExecutor.
    """

    def __call__(  # noqa: PLR0913
        self,
        effective_parallel: int,
        mode_name: str,
        main_repo_path: Any,
        failed_claim_ids: set[str],
        session_stats: SessionStats,
        start_time: float,
        run_logger: RunLogger,
        continuous: bool,
        record_fn: RecordFn,
        finalize_fn: Any,
        *,
        cli_override: bool = False,
        external_lock: threading.Lock | None = None,
    ) -> int:
        """Run the parallel orchestrator loop with a ThreadPoolExecutor.

        Parameters
        ----------
        effective_parallel : int
            Number of parallel agents to run concurrently.
        mode_name : str
            Display name for the orchestration mode (e.g., "Parallel", "Hybrid").
        main_repo_path : Any
            Path to the main repository for preflight checks.
        failed_claim_ids : set[str]
            Set of work item IDs that failed to be claimed. Thread-safe access
            is coordinated via external_lock if provided.
        session_stats : SessionStats
            Session statistics dataclass for tracking throughput and agent runs.
        start_time : float
            Unix timestamp when the orchestration session started.
        run_logger : RunLogger
            Logger instance for orchestrator messages and events.
        continuous : bool
            If True, continue processing items until no more work is available.
            If False, exit after processing initial batch.
        record_fn : RecordFn
            Callback function to record completed work item results.
            Signature: (item, result, session_stats, run_logger) -> Any
        finalize_fn : Any
            Callback function to finalize the session on exit.
            Expected signature: (session_stats, start_time, items_completed,
            total_requests, run_logger, run_post_mortem: bool) -> None
        cli_override : bool, optional
            If True, indicates parallel limits were set via CLI argument.
            Default is False.
        external_lock : threading.Lock | None, optional
            Optional external lock for coordinating failed_claim_ids access
            with other threads (e.g., main orchestrator in hybrid mode).
            If None, parallel loop uses its internal pool lock.

        Returns
        -------
        int
            Exit code: 0 for success, 1 for failure.
        """
        ...


# ---------------------------------------------------------------------------
# Parallel Support Callbacks
# ---------------------------------------------------------------------------

_Future = concurrent.futures.Future[WorkItemResult]


class CollectFn(Protocol):
    """Protocol for collecting completed futures and recording results."""
    def __call__(  # noqa: PLR0913
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
