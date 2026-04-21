"""Retry merge flow after out-of-lock conflict cleanup."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from pokepoke.worktrees.worktrees import merge_worktree

if TYPE_CHECKING:
    from pokepoke.worktrees.merge_step_tracker import MergeStepTracker
    from pokepoke.worktrees.worktree_merge_handler import WorktreeMergeContext

logger = logging.getLogger(__name__)


def retry_merge_after_cleanup(
    ctx: WorktreeMergeContext,
    tracker: MergeStepTracker,
) -> tuple[bool, bool]:
    """Retry merge while lock is held after conflict cleanup."""
    from pokepoke.git.merge_conflict import abort_merge, is_merge_in_progress
    from pokepoke.worktrees.worktree_cleanup import add_uncleaned_worktree, remove_from_manifest

    repo_root_path = Path(ctx.repo_path) if ctx.repo_path else None
    tracker.begin_step("8", f"Retrying merge for {ctx.agent_id}")
    retry_result = merge_worktree(ctx.agent_id, cleanup=True, repo_path=ctx.repo_path)
    if retry_result.rollback_failed:
        logger.critical(
            "🚨 REPO CORRUPTION: Rollback failed during retry merge for %s — "
            "local repo has a merge commit that could not be undone. Manual intervention required.",
            ctx.agent_id,
        )
    if retry_result.halt_required:
        from pokepoke.utils.shutdown import request_shutdown

        logger.critical(
            "🚨 Post-merge validation failed during retry for %s — halting orchestrator. "
            "Repo state preserved for manual investigation.",
            ctx.agent_id,
        )
        tracker.fail_step("9", "Post-merge invariant violation — halt requested")
        request_shutdown()
        return False, False
    if not retry_result.success:
        tracker.fail_step("8", "Retry merge failed")
        logger.error("   Merge failed again after cleanup.")
        if is_merge_in_progress(repo_path=repo_root_path):
            abort_success, abort_error = abort_merge(repo_path=repo_root_path)
            if not abort_success:
                logger.error("Failed to abort merge after retry failure for %s: %s", ctx.agent_id, abort_error)
                logger.error(f"   ❌ Failed to abort merge: {abort_error}")
                logger.warning("   ⚠️  Repository may be stuck in merge-in-progress state")
        return False, False
    tracker.complete_step("8", "Retry merge succeeded")
    for sid in ("6", "7", "9"):
        if tracker._current_run and tracker._current_run.steps[sid].status.value == "pending":
            tracker.complete_step(sid)

    remove_from_manifest(ctx.agent_id)
    worktree_cleaned = not ctx.worktree_path.exists()
    if not worktree_cleaned:
        logger.error("Worktree directory persists after retry merge: %s", ctx.worktree_path)
        add_uncleaned_worktree(ctx.agent_id, str(ctx.worktree_path), "Worktree persists after successful retry merge")
    else:
        tracker.complete_step("10", "Worktree removed")
    tracker.complete_step("11", "Merge lock released")
    logger.info("   Merged worktree" + (" and cleaned up" if worktree_cleaned else " (cleanup incomplete)"))
    try:
        from pokepoke.models.warm_session_service import refresh_pool_after_merge

        refresh_pool_after_merge(cwd=ctx.repo_path)
    except Exception as e:
        logger.debug(f"Failed to refresh warm session pool after merge: {e}")
    return True, worktree_cleaned
