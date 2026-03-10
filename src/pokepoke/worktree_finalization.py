"""Worktree finalization and merging operations."""

import json
import logging
import subprocess
from pathlib import Path

from .constants import WORKTREE_DIR
from .types import BeadsWorkItem
from .worktrees import cleanup_worktree
from .git_operations import get_default_branch
from .beads_hierarchy import get_parent_id, close_parent_if_complete
from .beads_management import close_item
from .coordination import merge_lock

logger = logging.getLogger(__name__)


def finalize_work_item(
    item: BeadsWorkItem,
    worktree_path: Path,
    parent_agent_id: str | None = None
) -> bool:
    """Finalize work item by merging worktree and closing issue.

    Returns:
        True if successful, False otherwise
    """
    print("\n✅ Successfully completed work item!")
    print("   All changes committed and validated")

    if not check_and_merge_worktree(item, worktree_path, parent_agent_id=parent_agent_id):
        return False

    close_work_item_and_parents(item)

    return True


def check_and_merge_worktree(
    item: BeadsWorkItem,
    worktree_path: Path,
    parent_agent_id: str | None = None
) -> bool:
    """Check if worktree has commits and merge if needed.

    Uses the merge lock to serialize concurrent merge attempts from
    parallel agents. This prevents merge conflict cascades where multiple
    agents try to merge to master simultaneously.
    """
    try:
        # Use the actual target branch from config (not hardcoded)
        target_branch = get_default_branch()
        check_result = subprocess.run(
            ["git", "rev-list", "--count", "HEAD", f"^{target_branch}"],
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            check=True,
            cwd=str(worktree_path),
            timeout=30
        )
        commit_count = int(check_result.stdout.strip())

        if commit_count == 0:
            print("\n⏭️  No commits in worktree - nothing to merge")
            print("   Cleaning up worktree without merge...")
            cleanup_worktree(item.id, force=True)
            return True

    except subprocess.TimeoutExpired:
        logger.error("Git timed out checking commit count for %s — aborting merge", item.id)
        return False
    except (subprocess.CalledProcessError, ValueError) as e:
        # Branch not found or parse error — recoverable, attempt merge
        print(f"\n⚠️  Could not check commit count: {e}")
        print("   Attempting merge anyway...")
    except Exception as e:
        logger.error("Unexpected error checking commit count for %s: %s", item.id, e)
        print("   Aborting merge to prevent data corruption")
        return False

    # Acquire merge lock to serialize with other parallel agents
    logger.info("Waiting for merge lock for item %s", item.id)
    with merge_lock():
        logger.info("Acquired merge lock for item %s", item.id)
        return merge_worktree_to_dev(item, parent_agent_id=parent_agent_id, worktree_path=worktree_path)


def merge_worktree_to_dev(
    item: BeadsWorkItem,
    parent_agent_id: str | None = None,
    repo_root: Path | None = None,
    worktree_path: Path | None = None,
) -> bool:
    """Merge worktree to the default development branch.

    Delegates to perform_worktree_merge (the single source of truth for
    merge-attempt-cleanup-retry logic).

    Args:
        item: Work item being merged.
        parent_agent_id: Optional parent agent ID for UI nesting.
        repo_root: Repository root (defaults to cwd if not provided).
        worktree_path: Worktree directory (defaults to worktrees/task-{id}).
    """
    from .worktree_merge_handler import perform_worktree_merge

    effective_repo_root = repo_root if repo_root is not None else Path.cwd()
    effective_worktree_path = (
        worktree_path if worktree_path is not None
        else effective_repo_root / WORKTREE_DIR / f"task-{item.id}"
    )

    merge_success, _ = perform_worktree_merge(
        item.id,
        item,
        effective_worktree_path,
        effective_repo_root,
        parent_agent_id=parent_agent_id,
    )
    return merge_success


def close_work_item_and_parents(item: BeadsWorkItem) -> None:
    """Close work item and check if parents should be closed."""
    print(f"\n🔍 Checking if agent closed beads item {item.id}...")
    try:
        check_result = subprocess.run(
            ["bd", "show", item.id, "--json"],
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            check=True,
            timeout=30
        )
        # bd show --json returns a list, not a dict - get first element
        items_data = json.loads(check_result.stdout)
        if not items_data:
            raise ValueError(f"No data returned for item {item.id}")
        item_data = items_data[0]

        if item_data.get("status") in ["closed", "completed"]:
            print("   ✅ Agent successfully closed the item")
        else:
            print("   ⚠️  Item not closed by agent, closing now...")
            close_item(item.id, "Completed by PokePoke orchestrator (agent did not close)")
    except Exception as e:
        print(f"   ⚠️  Could not check item status: {e}")
        print("   Closing item as fallback...")
        close_item(item.id, "Completed by PokePoke orchestrator")

    # Check parent hierarchy
    check_parent_hierarchy(item)


def check_parent_hierarchy(item: BeadsWorkItem) -> None:
    """Check and close parent items if all children are complete."""
    parent_id = get_parent_id(item.id)
    if parent_id:
        print(f"\n🔍 Checking parent {parent_id} completion status...")
        close_parent_if_complete(parent_id)

        # Recursively check grandparents
        grandparent_id = get_parent_id(parent_id)
        if grandparent_id:
            close_parent_if_complete(grandparent_id)
