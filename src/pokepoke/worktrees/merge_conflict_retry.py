"""Retry merge flow after out-of-lock conflict cleanup."""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING

from pokepoke.agents.cleanup_agents import invoke_merge_conflict_cleanup_agent
from pokepoke.git.repo_state_guard import cleanup_lock
from pokepoke.worktrees.worktrees import merge_worktree

if TYPE_CHECKING:
    from pokepoke.worktrees.merge_step_tracker import MergeStepTracker
    from pokepoke.worktrees.worktree_merge_handler import WorktreeMergeContext, _ConflictResolutionNeeded

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


def run_conflict_retry_loop(
    ctx: WorktreeMergeContext,
    conflict_info: _ConflictResolutionNeeded,
    tracker: MergeStepTracker,
) -> tuple[bool, bool]:
    """Retry loop: cleanup outside lock → retry inside lock.

    Returns (merge_success, worktree_cleaned).
    """
    from pokepoke.worktrees.coordination import merge_lock
    from pokepoke.worktrees.worktree_merge_handler import _ConflictResolutionNeeded as _Signal
    from pokepoke.worktrees.worktree_merge_handler import perform_worktree_merge

    max_retries = ctx.max_conflict_retries

    for attempt in range(1, max_retries + 1):
        logger.info(
            "🔓 Released merge lock — running conflict cleanup agent for %s outside lock "
            "(attempt %d/%d)",
            ctx.agent_id, attempt, max_retries,
        )
        if ctx.item_logger:
            ctx.item_logger.log(
                f"🔓 ORCHESTRATOR: Running conflict cleanup outside merge lock "
                f"(attempt {attempt}/{max_retries})"
            )

        cleanup_success = _run_conflict_cleanup_outside_lock(ctx, conflict_info, tracker)

        if not cleanup_success:
            tracker.finish_run("failed")
            return False, False

        # Re-acquire merge lock for retry
        tracker.begin_step("1r", f"Re-acquiring merge lock for retry (attempt {attempt}/{max_retries})…")
        with merge_lock():
            tracker.complete_step("1r", f"Re-acquired merge lock for {ctx.agent_id}")
            logger.info("🔒 Re-acquired merge lock for retry merge of %s", ctx.agent_id)
            retry_result = retry_merge_after_cleanup(ctx, tracker)
            if retry_result[0]:
                tracker.finish_run("success")
                return retry_result

            # Retry failed. If more attempts remain, do a fresh merge
            # (still inside lock) to discover the current conflict set.
            if attempt < max_retries:
                logger.info(
                    "   Retry merge failed (attempt %d/%d) — re-merging to discover fresh conflicts",
                    attempt, max_retries,
                )
                fresh_result = perform_worktree_merge(ctx)
                if not isinstance(fresh_result, _Signal):
                    outcome = "success" if (isinstance(fresh_result, tuple) and fresh_result[0]) else "failed"
                    tracker.finish_run(outcome)
                    return fresh_result if isinstance(fresh_result, tuple) else (False, False)
                conflict_info = fresh_result
                # Lock releases here; loop continues with cleanup outside lock

    logger.error("All %d conflict retry attempts exhausted for %s.", max_retries, ctx.agent_id)
    tracker.finish_run("failed")
    return False, False


def _run_conflict_cleanup_outside_lock(
    ctx: WorktreeMergeContext,
    conflict_info: _ConflictResolutionNeeded,
    tracker: MergeStepTracker,
) -> bool:
    """Invoke merge conflict cleanup agent while merge lock is released.

    The cleanup agent runs with ``cwd`` set to the isolated worktree path so
    that any edits it makes affect ONLY the worktree's branch. The main
    repository is not touched while the merge lock is released.

    Retries up to 3 times on transient failures (timeout, crash, SDK error)
    with exponential backoff.
    """
    max_agent_retries = 3

    for attempt in range(1, max_agent_retries + 1):
        suffix = f" (attempt {attempt}/{max_agent_retries})" if max_agent_retries > 1 else ""
        tracker.begin_step("8C", f"Invoking merge conflict cleanup agent{suffix} (outside merge lock)…")
        logger.info("   Invoking cleanup agent to resolve conflicts in isolated worktree...%s", suffix)
        with cleanup_lock():
            success, _ = invoke_merge_conflict_cleanup_agent(
                ctx.agent_item,
                conflict_info.conflict_details,
                unmerged_files=conflict_info.unmerged_files,
                cwd=str(ctx.worktree_path),
                parent_agent_id=ctx.parent_agent_id,
                wait_for_merge=False,
                item_logger=ctx.item_logger,
            )
        if success:
            tracker.complete_step("8C", f"Merge conflict cleanup agent succeeded{suffix}")
            return True

        if attempt < max_agent_retries:
            backoff = 2 ** attempt
            logger.warning(
                "   Cleanup agent failed%s — retrying in %ds...",
                suffix, backoff,
            )
            if ctx.item_logger:
                ctx.item_logger.log_error(
                    f"⚠️  ORCHESTRATOR: Conflict cleanup failed{suffix} — retrying in {backoff}s"
                )
            tracker.fail_step("8C", f"Cleanup failed{suffix}, retrying in {backoff}s")
            time.sleep(backoff)

    tracker.fail_step("8C", f"Merge conflict cleanup agent failed after {max_agent_retries} attempts")
    logger.error("   Cleanup failed after %d attempts.", max_agent_retries)
    return False
