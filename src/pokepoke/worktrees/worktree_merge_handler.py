"""Worktree merge handling — single source of truth for merge-attempt-cleanup-retry logic.

Both the task-finalization path (worktree_finalization.merge_worktree_to_dev) and
the maintenance-agent path (handle_worktree_merge) delegate to perform_worktree_merge.
"""

import logging
from dataclasses import dataclass
from pathlib import Path

from filelock import Timeout

from pokepoke.agents.cleanup_agents import invoke_cleanup_agent, invoke_merge_conflict_cleanup_agent
from pokepoke.git.repo_state_guard import cleanup_lock
from pokepoke.types_beads import BeadsWorkItem
from pokepoke.types_stats import AgentStats
from pokepoke.utils.constants import WORKTREE_DIR, WORKTREE_TASK_PREFIX
from pokepoke.worktrees.coordination import merge_lock
from pokepoke.worktrees.worktree_cleanup import add_uncleaned_worktree
from pokepoke.worktrees.worktrees import merge_worktree

logger = logging.getLogger(__name__)


@dataclass
class WorktreeMergeContext:
    """Context bundle for worktree merge parameters."""
    agent_id: str
    agent_item: BeadsWorkItem
    agent_name: str
    worktree_path: Path
    repo_root: Path
    parent_agent_id: str | None = None
    repo_path: str | None = None


def handle_worktree_merge(
    ctx: WorktreeMergeContext,
    agent_stats: AgentStats | None = None,
) -> tuple[bool, bool]:
    """Handle worktree merge with conflict resolution.

    Uses the merge lock to serialize concurrent merge attempts from
    parallel agents. This prevents merge conflict cascades.

    Args:
        ctx: Merge context bundle with agent and worktree information
        agent_stats: Agent statistics (unused, kept for API compatibility)

    Returns:
        Tuple of (merge_success, worktree_cleaned)
    """
    # Acquire merge lock to serialize with other parallel agents
    logger.info("Waiting for merge lock for agent %s", ctx.agent_id)

    try:
        with merge_lock():
            logger.info("Acquired merge lock for agent %s", ctx.agent_id)
            # Fall back to agent_id for cleanup parent if no parent_agent_id
            if not ctx.parent_agent_id:
                ctx.parent_agent_id = ctx.agent_id
            return perform_worktree_merge(ctx)
    except Timeout as e:
        logger.warning("Merge lock timeout for agent %s: %s", ctx.agent_id, e)

        add_uncleaned_worktree(
            ctx.agent_id,
            str(ctx.worktree_path),
            f"Merge lock timeout after 10 minutes: {e}"
        )
        return False, False
    except Exception as e:
        logger.error("Merge coordination error for agent %s: %s", ctx.agent_id, e, exc_info=True)

        add_uncleaned_worktree(
            ctx.agent_id,
            str(ctx.worktree_path),
            f"Merge coordination error: {e}"
        )
        return False, False


def perform_worktree_merge(  # noqa: C901
    ctx: WorktreeMergeContext,
) -> tuple[bool, bool]:
    """Core merge-attempt-cleanup-retry logic (single source of truth).

    Called by both the task-finalization path and the maintenance-agent path.

    Args:
        ctx: Merge context bundle with agent and worktree information

    Returns:
        Tuple of (merge_success, worktree_cleaned).
    """
    from pokepoke.git.git_operations import (
        check_main_repo_ready_for_merge,
    )
    from pokepoke.git.merge_conflict import (
        abort_merge,
        get_unmerged_files,
        is_merge_in_progress,
    )
    from pokepoke.worktrees.worktree_cleanup import add_uncleaned_worktree, remove_from_manifest

    repo_cwd = ctx.repo_path

    # --- pre-merge readiness check ---
    logger.info("\n🔍 Checking if main repo is ready for merge...")
    is_ready, error_msg = check_main_repo_ready_for_merge(cwd=repo_cwd)

    if not is_ready:
        logger.error(f"\n⚠️  Cannot merge: {error_msg}")
        logger.info(f"   Worktree preserved at {WORKTREE_DIR}/{WORKTREE_TASK_PREFIX}{ctx.agent_id} - requires cleanup")

        add_uncleaned_worktree(
            ctx.agent_id,
            str(ctx.worktree_path),
            f"Main repo not ready for merge: {error_msg}",
        )

        logger.info("   Invoking cleanup agent to resolve uncommitted changes before merge...")
        with cleanup_lock():
            # Don't wait for merge lock since we already hold it
            cleanup_success, _ = invoke_cleanup_agent(
                ctx.agent_item,
                parent_agent_id=ctx.parent_agent_id,
                wait_for_merge=False
            )

        if cleanup_success:
            logger.info("   Cleanup successful, retrying merge check...")
            is_ready, error_msg = check_main_repo_ready_for_merge(cwd=repo_cwd)
            if not is_ready:
                logger.error(f"   Still failing after cleanup: {error_msg}")
                return False, False
            logger.info("   ✅ Repo is ready after cleanup, continuing with merge.")
            remove_from_manifest(ctx.agent_id)
        else:
            logger.error("   Cleanup failed.")
            return False, False

    # --- attempt merge ---
    logger.info(f"\n🔀 Merging worktree for {ctx.agent_id}...")
    merge_result = merge_worktree(ctx.agent_id, cleanup=True, repo_path=repo_cwd)
    merge_success = merge_result.success
    unmerged_files = merge_result.unmerged_files

    if merge_result.rollback_failed:
        logger.critical(
            "🚨 REPO CORRUPTION: Rollback failed for %s — "
            "local repo has an unpushed merge commit that could not be undone. "
            "Manual intervention required (git reset --hard HEAD~1).",
            ctx.agent_id,
        )

    if not merge_success:
        repo_root_path = Path(repo_cwd) if repo_cwd else None
        if is_merge_in_progress(repo_path=repo_root_path):
            logger.error("\n❌ Worktree merge has conflicts!")
        else:
            logger.error("\n❌ Worktree merge failed!")
            if not unmerged_files:
                unmerged_files = get_unmerged_files(repo_path=repo_root_path)

        if unmerged_files:
            logger.info(f"   Conflicted files ({len(unmerged_files)}):")
            for f in unmerged_files[:10]:
                logger.info(f"      - {f}")
            if len(unmerged_files) > 10:
                logger.info(f"      ... and {len(unmerged_files) - 10} more")

        logger.info(f"   Worktree preserved at {WORKTREE_DIR}/{WORKTREE_TASK_PREFIX}{ctx.agent_id} - requires conflict resolution")

        add_uncleaned_worktree(
            ctx.agent_id,
            str(ctx.worktree_path),
            f"Merge conflict in {len(unmerged_files) if unmerged_files else 0} file(s)",
        )

        # Build detailed conflict info for the cleanup agent prompt
        conflict_details = ""
        if unmerged_files:
            conflict_details = "\n**Conflicted Files:**\n" + "\n".join(
                f"- `{f}`" for f in unmerged_files
            )

        logger.info("   Invoking cleanup agent to resolve conflicts...")
        with cleanup_lock():
            # Don't wait for merge lock since we already hold it
            success, _ = invoke_merge_conflict_cleanup_agent(
                ctx.agent_item,
                f"Merge conflict detected in {len(unmerged_files)} file(s){conflict_details}",
                unmerged_files=unmerged_files,
                parent_agent_id=ctx.parent_agent_id,
                wait_for_merge=False
            )

        if success:
            logger.info("   Cleanup successful, retrying merge...")
            if is_merge_in_progress(repo_path=repo_root_path):
                logger.warning("   ⚠️  Merge still in progress after cleanup - aborting to reset state")
                abort_success, abort_error = abort_merge(repo_path=repo_root_path)
                if not abort_success:
                    logger.error(f"   ❌ Failed to abort merge: {abort_error}")
                    return False, False
                logger.info("   ✅ Merge aborted, will retry")

            retry_result = merge_worktree(ctx.agent_id, cleanup=True, repo_path=repo_cwd)
            merge_success = retry_result.success
            if retry_result.rollback_failed:
                logger.critical(
                    "🚨 REPO CORRUPTION: Rollback failed during retry merge for %s — "
                    "local repo has an unpushed merge commit. Manual intervention required.",
                    ctx.agent_id,
                )
            if merge_success:
                remove_from_manifest(ctx.agent_id)
                worktree_cleaned = not ctx.worktree_path.exists()
                if not worktree_cleaned:
                    logger.error("Worktree directory persists after retry merge: %s", ctx.worktree_path)
                    add_uncleaned_worktree(ctx.agent_id, str(ctx.worktree_path), "Worktree persists after successful retry merge")
                logger.info("   Merged worktree" + (" and cleaned up" if worktree_cleaned else " (cleanup incomplete)"))
                return True, worktree_cleaned
            else:
                logger.error("   Merge failed again after cleanup.")
                if is_merge_in_progress(repo_path=repo_root_path):
                    abort_success, abort_error = abort_merge(repo_path=repo_root_path)
                    if not abort_success:
                        logger.error("Failed to abort merge after retry failure for %s: %s", ctx.agent_id, abort_error)
                        logger.error(f"   ❌ Failed to abort merge: {abort_error}")
                        logger.warning("   ⚠️  Repository may be stuck in merge-in-progress state")
                return False, False
        else:
            logger.error("   Cleanup failed.")
            if is_merge_in_progress(repo_path=repo_root_path):
                logger.info("   Aborting merge to reset state...")
                abort_success, abort_error = abort_merge(repo_path=repo_root_path)
                if not abort_success:
                    logger.error("Failed to abort merge after cleanup failure for %s: %s", ctx.agent_id, abort_error)
                    logger.error(f"   ❌ Failed to abort merge: {abort_error}")
                    logger.warning("   ⚠️  Repository may be stuck in merge-in-progress state")
            return False, False

    # Verify worktree was actually cleaned up
    worktree_cleaned = not ctx.worktree_path.exists()
    if not worktree_cleaned:
        logger.error("Worktree directory persists after merge: %s", ctx.worktree_path)
        add_uncleaned_worktree(ctx.agent_id, str(ctx.worktree_path), "Worktree persists after successful merge")
    logger.info("   Merged worktree" + (" and cleaned up" if worktree_cleaned else " (cleanup incomplete)"))

    # Invalidate warm sessions after successful merge (codebase may have changed)
    try:
        from pokepoke.models.warm_session_service import refresh_pool_after_merge
        refresh_pool_after_merge(cwd=ctx.repo_path)
    except Exception as e:
        logger.debug(f"Failed to refresh warm session pool after merge: {e}")

    return True, worktree_cleaned
