"""Protocol interfaces for external dependencies.

Defines structural typing contracts for git and beads operations so that
orchestration code can depend on abstractions rather than concrete module
functions.  Default implementations delegate to the existing module-level
helpers.
"""

import subprocess
from typing import Any, Protocol

from pokepoke.types import BeadsStats, BeadsWorkItem, IssueWithDependencies

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
