"""Worktree finalization and merging operations."""

import json
import logging
import subprocess
from pathlib import Path

from pokepoke.beads.beads_hierarchy import close_parent_if_complete, get_parent_id
from pokepoke.beads.beads_management import close_item
from pokepoke.beads.beads_query import _run_bd_with_retry
from pokepoke.git.git_helpers import run_git
from pokepoke.git.git_operations import get_default_branch
from pokepoke.types import BeadsWorkItem
from pokepoke.utils.constants import WORKTREE_DIR, WORKTREE_TASK_PREFIX

from .coordination import merge_lock
from .worktrees import cleanup_worktree

logger = logging.getLogger(__name__)


def finalize_work_item(
    item: BeadsWorkItem,
    worktree_path: Path,
    parent_agent_id: str | None = None,
    repo_path: str | None = None,
) -> bool:
    """Finalize work item by merging worktree and closing issue.

    Args:
        item: Work item to finalize.
        worktree_path: Path to the worktree.
        parent_agent_id: Optional parent agent ID for UI nesting.
        repo_path: Target repo root for git operations.

    Returns:
        True if successful, False otherwise
    """
    logger.info("\n✅ Successfully completed work item!")
    logger.info("   All changes committed and validated")

    if not check_and_merge_worktree(item, worktree_path, parent_agent_id=parent_agent_id, repo_path=repo_path):
        return False

    close_work_item_and_parents(item)

    return True


def check_and_merge_worktree(
    item: BeadsWorkItem,
    worktree_path: Path,
    parent_agent_id: str | None = None,
    repo_path: str | None = None,
) -> bool:
    """Check if worktree has commits and merge if needed.

    Uses the merge lock to serialize concurrent merge attempts from
    parallel agents. This prevents merge conflict cascades where multiple
    agents try to merge to master simultaneously.
    """
    try:
        # Use the actual target branch from config (not hardcoded)
        target_branch = get_default_branch(cwd=repo_path)
        check_result = run_git(
            ["git", "rev-list", "--count", "HEAD", f"^{target_branch}"],
            cwd=str(worktree_path),
        )
        commit_count = int(check_result.stdout.strip())

        if commit_count == 0:
            logger.info("\n⏭️  No commits in worktree - nothing to merge")
            logger.info("   Cleaning up worktree without merge...")
            cleanup_worktree(item.id, force=True, repo_path=repo_path)
            return True

    except subprocess.TimeoutExpired:
        logger.error("Git timed out checking commit count for %s — aborting merge", item.id)
        return False
    except (subprocess.CalledProcessError, ValueError) as e:
        # Branch not found or parse error — recoverable, attempt merge
        logger.warning(f"\n⚠️  Could not check commit count: {e}")
        logger.info("   Attempting merge anyway...")
    except Exception as e:
        logger.error("Unexpected error checking commit count for %s: %s", item.id, e)
        logger.info("   Aborting merge to prevent data corruption")
        return False

    # Acquire merge lock to serialize with other parallel agents
    logger.info("Waiting for merge lock for item %s", item.id)
    with merge_lock():
        logger.info("Acquired merge lock for item %s", item.id)
        return merge_worktree_to_dev(item, parent_agent_id=parent_agent_id, worktree_path=worktree_path, repo_path=repo_path)


def merge_worktree_to_dev(
    item: BeadsWorkItem,
    parent_agent_id: str | None = None,
    repo_root: Path | None = None,
    worktree_path: Path | None = None,
    repo_path: str | None = None,
) -> bool:
    """Merge worktree to the default development branch.

    Delegates to perform_worktree_merge (the single source of truth for
    merge-attempt-cleanup-retry logic).

    Args:
        item: Work item being merged.
        parent_agent_id: Optional parent agent ID for UI nesting.
        repo_root: Repository root (defaults to repo_path or cwd if not provided).
        worktree_path: Worktree directory (defaults to worktrees/task-{id}).
        repo_path: Target repo root for git operations.
    """
    from .worktree_merge_handler import WorktreeMergeContext, perform_worktree_merge

    effective_repo_root = repo_root if repo_root is not None else (Path(repo_path) if repo_path else Path.cwd())
    effective_worktree_path = (
        worktree_path if worktree_path is not None
        else effective_repo_root / WORKTREE_DIR / f"{WORKTREE_TASK_PREFIX}{item.id}"
    )

    ctx = WorktreeMergeContext(
        agent_id=item.id,
        agent_item=item,
        agent_name="",  # Not used in perform_worktree_merge
        worktree_path=effective_worktree_path,
        repo_root=effective_repo_root,
        parent_agent_id=parent_agent_id,
        repo_path=repo_path,
    )
    merge_success, _ = perform_worktree_merge(ctx)
    return merge_success


def close_work_item_and_parents(item: BeadsWorkItem) -> None:
    """Close work item and check if parents should be closed."""
    if item.is_ephemeral:
        logger.info("Skipping beads close for ephemeral item %s", item.id)
        return

    logger.info(f"\n🔍 Checking if agent closed beads item {item.id}...")
    try:
        check_result = _run_bd_with_retry(
            ["show", item.id, "--json"],
            timeout=30,
        )
        # bd show --json returns a list, not a dict - get first element
        items_data = json.loads(check_result.stdout)
        if not items_data:
            raise ValueError(f"No data returned for item {item.id}")
        item_data = items_data[0]

        if item_data.get("status") in ["closed", "completed"]:
            logger.info("   ✅ Agent successfully closed the item")
        else:
            logger.warning("   ⚠️  Item not closed by agent, closing now...")
            close_item(item.id, "Completed by PokePoke orchestrator (agent did not close)")
    except Exception as e:
        logger.warning(f"   ⚠️  Could not check item status: {e}")
        logger.info("   Closing item as fallback...")
        close_item(item.id, "Completed by PokePoke orchestrator")

    # Check parent hierarchy
    check_parent_hierarchy(item)


def check_parent_hierarchy(item: BeadsWorkItem) -> None:
    """Check and close parent items if all children are complete."""
    parent_id = get_parent_id(item.id)
    if parent_id:
        logger.info(f"\n🔍 Checking parent {parent_id} completion status...")
        close_parent_if_complete(parent_id)

        # Recursively check grandparents
        grandparent_id = get_parent_id(parent_id)
        if grandparent_id:
            close_parent_if_complete(grandparent_id)
