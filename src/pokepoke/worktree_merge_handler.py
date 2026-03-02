"""Worktree merge handling — single source of truth for merge-attempt-cleanup-retry logic.

Both the task-finalization path (worktree_finalization.merge_worktree_to_dev) and
the maintenance-agent path (handle_worktree_merge) delegate to perform_worktree_merge.
"""

import logging
from pathlib import Path
from filelock import Timeout

from pokepoke.types import BeadsWorkItem, AgentStats
from pokepoke.worktrees import merge_worktree
from pokepoke.cleanup_agents import invoke_cleanup_agent, invoke_merge_conflict_cleanup_agent
from pokepoke.repo_state_guard import cleanup_lock
from pokepoke.coordination import merge_lock
from pokepoke.worktree_cleanup import add_uncleaned_worktree

logger = logging.getLogger(__name__)


def handle_worktree_merge(
    agent_id: str,
    agent_item: BeadsWorkItem,
    agent_name: str,
    worktree_path: Path,
    repo_root: Path,
    agent_stats: AgentStats | None,
    parent_agent_id: str | None = None
) -> tuple[bool, bool]:
    """Handle worktree merge with conflict resolution.

    Uses the merge lock to serialize concurrent merge attempts from
    parallel agents. This prevents merge conflict cascades.

    Args:
        agent_id: Agent ID for worktree tracking
        agent_item: Work item for the agent
        agent_name: Display name of the agent
        worktree_path: Path to the worktree
        repo_root: Repository root path
        agent_stats: Agent statistics (unused, kept for API compatibility)
        parent_agent_id: Optional parent agent ID for UI nesting of sub-agents

    Returns:
        Tuple of (merge_success, worktree_cleaned)
    """
    # Acquire merge lock to serialize with other parallel agents
    logger.info("Waiting for merge lock for agent %s", agent_id)

    try:
        with merge_lock():
            logger.info("Acquired merge lock for agent %s", agent_id)
            print("   ✅ Lock acquired, proceeding with merge")
            # Fall back to agent_id for cleanup parent if no parent_agent_id
            cleanup_parent_id = parent_agent_id if parent_agent_id else agent_id
            return perform_worktree_merge(
                agent_id, agent_item, worktree_path, repo_root,
                parent_agent_id=cleanup_parent_id,
            )
    except Timeout as e:
        logger.warning("Merge lock timeout for agent %s: %s", agent_id, e)
        print("   Adding worktree to uncleaned list for later retry")

        add_uncleaned_worktree(
            agent_id,
            str(worktree_path),
            f"Merge lock timeout after 10 minutes: {e}"
        )
        return False, False
    except Exception as e:
        logger.error("Merge coordination error for agent %s: %s", agent_id, e, exc_info=True)

        add_uncleaned_worktree(
            agent_id,
            str(worktree_path),
            f"Merge coordination error: {e}"
        )
        return False, False


def perform_worktree_merge(
    item_id: str,
    item: BeadsWorkItem,
    worktree_path: Path,
    repo_root: Path,
    parent_agent_id: str | None = None,
) -> tuple[bool, bool]:
    """Core merge-attempt-cleanup-retry logic (single source of truth).

    Called by both the task-finalization path and the maintenance-agent path.

    Args:
        item_id: Identifier used for the worktree branch (e.g. item.id).
        item: Work item associated with the merge.
        worktree_path: Absolute path to the worktree directory.
        repo_root: Repository root path passed to cleanup agents.
        parent_agent_id: Optional parent agent ID for UI nesting of sub-agents.

    Returns:
        Tuple of (merge_success, worktree_cleaned).
    """
    from pokepoke.git_operations import (
        check_main_repo_ready_for_merge,
        is_merge_in_progress,
        get_unmerged_files,
        abort_merge,
    )
    from pokepoke.worktree_cleanup import add_uncleaned_worktree, remove_from_manifest

    # --- pre-merge readiness check ---
    print("\n🔍 Checking if main repo is ready for merge...")
    is_ready, error_msg = check_main_repo_ready_for_merge()

    if not is_ready:
        print(f"\n⚠️  Cannot merge: {error_msg}")
        print(f"   Worktree preserved at worktrees/task-{item_id} - requires cleanup")

        add_uncleaned_worktree(
            item_id,
            str(worktree_path),
            f"Main repo not ready for merge: {error_msg}",
        )

        print("   Invoking cleanup agent to resolve uncommitted changes before merge...")
        with cleanup_lock():
            # Don't wait for merge lock since we already hold it
            cleanup_success, _ = invoke_cleanup_agent(
                item,
                parent_agent_id=parent_agent_id,
                wait_for_merge=False
            )

        if cleanup_success:
            print("   Cleanup successful, retrying merge check...")
            is_ready, error_msg = check_main_repo_ready_for_merge()
            if not is_ready:
                print(f"   Still failing after cleanup: {error_msg}")
                return False, False
            print("   ✅ Repo is ready after cleanup, continuing with merge.")
            remove_from_manifest(item_id)
        else:
            print("   Cleanup failed.")
            return False, False

    # --- attempt merge ---
    print(f"\n🔀 Merging worktree for {item_id}...")
    merge_success, unmerged_files = merge_worktree(item_id, cleanup=True)

    if not merge_success:
        if is_merge_in_progress():
            print("\n❌ Worktree merge has conflicts!")
        else:
            print("\n❌ Worktree merge failed!")
            if not unmerged_files:
                unmerged_files = get_unmerged_files()

        if unmerged_files:
            print(f"   Conflicted files ({len(unmerged_files)}):")
            for f in unmerged_files[:10]:
                print(f"      - {f}")
            if len(unmerged_files) > 10:
                print(f"      ... and {len(unmerged_files) - 10} more")

        print(f"   Worktree preserved at worktrees/task-{item_id} - requires conflict resolution")

        add_uncleaned_worktree(
            item_id,
            str(worktree_path),
            f"Merge conflict in {len(unmerged_files) if unmerged_files else 0} file(s)",
        )

        # Build detailed conflict info for the cleanup agent prompt
        conflict_details = ""
        if unmerged_files:
            conflict_details = "\n**Conflicted Files:**\n" + "\n".join(
                f"- `{f}`" for f in unmerged_files
            )

        print("   Invoking cleanup agent to resolve conflicts...")
        with cleanup_lock():
            # Don't wait for merge lock since we already hold it
            success, _ = invoke_merge_conflict_cleanup_agent(
                item,
                f"Merge conflict detected in {len(unmerged_files)} file(s){conflict_details}",
                unmerged_files=unmerged_files,
                parent_agent_id=parent_agent_id,
                wait_for_merge=False
            )

        if success:
            print("   Cleanup successful, retrying merge...")
            if is_merge_in_progress():
                print("   ⚠️  Merge still in progress after cleanup - aborting to reset state")
                abort_success, abort_error = abort_merge()
                if not abort_success:
                    print(f"   ❌ Failed to abort merge: {abort_error}")
                    return False, False
                print("   ✅ Merge aborted, will retry")

            merge_success, _ = merge_worktree(item_id, cleanup=True)
            if merge_success:
                remove_from_manifest(item_id)
                worktree_cleaned = not worktree_path.exists()
                if not worktree_cleaned:
                    logger.error("Worktree directory persists after retry merge: %s", worktree_path)
                    add_uncleaned_worktree(item_id, str(worktree_path), "Worktree persists after successful retry merge")
                print("   Merged worktree" + (" and cleaned up" if worktree_cleaned else " (cleanup incomplete)"))
                return True, worktree_cleaned
            else:
                print("   Merge failed again after cleanup.")
                if is_merge_in_progress():
                    abort_success, abort_error = abort_merge()
                    if not abort_success:
                        logger.error("Failed to abort merge after retry failure for %s: %s", item_id, abort_error)
                        print(f"   ❌ Failed to abort merge: {abort_error}")
                        print("   ⚠️  Repository may be stuck in merge-in-progress state")
                return False, False
        else:
            print("   Cleanup failed.")
            if is_merge_in_progress():
                print("   Aborting merge to reset state...")
                abort_success, abort_error = abort_merge()
                if not abort_success:
                    logger.error("Failed to abort merge after cleanup failure for %s: %s", item_id, abort_error)
                    print(f"   ❌ Failed to abort merge: {abort_error}")
                    print("   ⚠️  Repository may be stuck in merge-in-progress state")
            return False, False

    # Verify worktree was actually cleaned up
    worktree_cleaned = not worktree_path.exists()
    if not worktree_cleaned:
        logger.error("Worktree directory persists after merge: %s", worktree_path)
        add_uncleaned_worktree(item_id, str(worktree_path), "Worktree persists after successful merge")
    print("   Merged worktree" + (" and cleaned up" if worktree_cleaned else " (cleanup incomplete)"))
    return True, worktree_cleaned
