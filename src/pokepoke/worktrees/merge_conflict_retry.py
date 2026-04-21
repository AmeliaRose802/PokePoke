"""Retry loop for merge conflict resolution via cleanup agents."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from pokepoke.agents.cleanup_agents import invoke_merge_conflict_cleanup_agent
from pokepoke.git.repo_state_guard import cleanup_lock

if TYPE_CHECKING:
    from pokepoke.worktrees.merge_result import MergeResult
    from pokepoke.worktrees.merge_step_tracker import MergeStepTracker
    from pokepoke.worktrees.worktree_merge_handler import WorktreeMergeContext

logger = logging.getLogger(__name__)


def retry_merge_with_conflict_cleanup(
    ctx: WorktreeMergeContext,
    unmerged_files: list[str] | None,
    repo_cwd: str | None,
    repo_root_path: Path | None,
    tracker: MergeStepTracker,
    merge_worktree_fn: Callable[..., MergeResult],
    remove_from_manifest_fn: Callable[[str], None],
    add_uncleaned_fn: Callable[[str, str, str], None],
    get_unmerged_fn: Callable[..., list[str]],
    is_merge_in_progress_fn: Callable[..., bool],
    abort_merge_fn: Callable[..., tuple[bool, str]],
) -> tuple[bool, bool]:
    """Retry loop: invoke conflict cleanup agent, abort stale merge, retry."""
    max_retries = ctx.max_conflict_retries
    previous_attempts: list[str] = []
    for attempt in range(1, max_retries + 1):
        conflict_details = ""
        if unmerged_files:
            conflict_details = "\n**Conflicted Files:**\n" + "\n".join(
                f"- `{f}`" for f in unmerged_files
            )

        attempt_context = ""
        if previous_attempts:
            attempt_context = (
                f"\n\n**Previous attempt context** (attempt {attempt}/{max_retries}):\n"
                + "\n".join(previous_attempts)
            )

        tracker.begin_step("11l", f"Conflict cleanup attempt {attempt}/{max_retries}")
        logger.info("   Invoking cleanup agent (attempt %d/%d)...", attempt, max_retries)
        if ctx.item_logger:
            conflict_count = len(unmerged_files) if unmerged_files else 0
            ctx.item_logger.log(
                f"🔧 ORCHESTRATOR: Invoking merge conflict cleanup agent "
                f"(attempt {attempt}/{max_retries}, {conflict_count} conflicted files)"
            )
        with cleanup_lock():
            cleanup_ok, _ = invoke_merge_conflict_cleanup_agent(
                ctx.agent_item,
                f"Merge conflict detected in {len(unmerged_files) if unmerged_files else 0} file(s)"
                f"{conflict_details}{attempt_context}",
                unmerged_files=unmerged_files,
                cwd=repo_cwd,
                parent_agent_id=ctx.parent_agent_id,
                wait_for_merge=False,
                item_logger=ctx.item_logger,
            )

        if not cleanup_ok:
            return _handle_cleanup_failure(
                ctx, attempt, max_retries, tracker, repo_root_path,
                is_merge_in_progress_fn, abort_merge_fn,
            )

        logger.info("   Cleanup successful, retrying merge (attempt %d/%d)...", attempt, max_retries)
        if ctx.item_logger:
            ctx.item_logger.log(
                f"🔄 ORCHESTRATOR: Conflict cleanup successful — retrying merge (attempt {attempt}/{max_retries})"
            )
        if not _abort_if_merge_in_progress(ctx, repo_root_path, is_merge_in_progress_fn, abort_merge_fn):
            return False, False

        retry_result = merge_worktree_fn(ctx.agent_id, cleanup=True, repo_path=repo_cwd)
        if retry_result.rollback_failed:
            logger.critical(
                "🚨 REPO CORRUPTION: Rollback failed during retry merge for %s — "
                "local repo has a merge commit that could not be undone. "
                "Manual intervention required.",
                ctx.agent_id,
            )
        if retry_result.success:
            return _handle_retry_success(
                ctx, attempt, tracker, remove_from_manifest_fn, add_uncleaned_fn,
            )

        # Merge still failed — collect context for next attempt
        new_unmerged = retry_result.unmerged_files or get_unmerged_fn(repo_path=repo_root_path)
        previous_attempts.append(
            f"- Attempt {attempt}: cleanup succeeded but merge still failed "
            f"with {len(new_unmerged)} conflict(s): {', '.join(new_unmerged[:5])}"
            + (f" (+{len(new_unmerged) - 5} more)" if len(new_unmerged) > 5 else "")
        )
        logger.error(
            "   Merge failed after cleanup attempt %d/%d (%d conflict(s) remain).",
            attempt, max_retries, len(new_unmerged),
        )
        tracker.fail_step("11l", f"Merge still conflicted after attempt {attempt}")

        if attempt < max_retries:
            if is_merge_in_progress_fn(repo_path=repo_root_path):
                abort_success, abort_error = abort_merge_fn(repo_path=repo_root_path)
                if not abort_success:
                    logger.error("Failed to abort merge between retries for %s: %s", ctx.agent_id, abort_error)
                    return False, False
            unmerged_files = new_unmerged
        else:
            logger.error("   All %d conflict retry attempts exhausted for %s.", max_retries, ctx.agent_id)
            if is_merge_in_progress_fn(repo_path=repo_root_path):
                abort_success, abort_error = abort_merge_fn(repo_path=repo_root_path)
                if not abort_success:
                    logger.error("Failed to abort merge after final retry for %s: %s", ctx.agent_id, abort_error)
            return False, False

    return False, False


def _handle_cleanup_failure(
    ctx: WorktreeMergeContext,
    attempt: int,
    max_retries: int,
    tracker: MergeStepTracker,
    repo_root_path: Path | None,
    is_merge_in_progress_fn: Callable[..., bool],
    abort_merge_fn: Callable[..., tuple[bool, str]],
) -> tuple[bool, bool]:
    """Handle failure of the cleanup agent."""
    logger.error("   Cleanup failed (attempt %d/%d).", attempt, max_retries)
    tracker.fail_step("11l", f"Cleanup agent failed (attempt {attempt})")
    if ctx.item_logger:
        ctx.item_logger.log_error("❌ ORCHESTRATOR: Merge conflict cleanup agent failed")
    if is_merge_in_progress_fn(repo_path=repo_root_path):
        logger.info("   Aborting merge to reset state...")
        if ctx.item_logger:
            ctx.item_logger.log("🔄 ORCHESTRATOR: Aborting merge to reset state after cleanup failure")
        abort_success, abort_error = abort_merge_fn(repo_path=repo_root_path)
        if not abort_success:
            logger.error("Failed to abort merge after cleanup failure for %s: %s", ctx.agent_id, abort_error)
            logger.warning("   ⚠️  Repository may be stuck in merge-in-progress state")
    return False, False


def _abort_if_merge_in_progress(
    ctx: WorktreeMergeContext,
    repo_root_path: Path | None,
    is_merge_in_progress_fn: Callable[..., bool],
    abort_merge_fn: Callable[..., tuple[bool, str]],
) -> bool:
    """Abort an in-progress merge if detected. Returns False if abort fails."""
    if not is_merge_in_progress_fn(repo_path=repo_root_path):
        return True
    logger.warning("   ⚠️  Merge still in progress after cleanup - aborting to reset state")
    if ctx.item_logger:
        ctx.item_logger.log("⚠️  ORCHESTRATOR: Merge still in progress after cleanup — aborting to reset state")
    abort_success, abort_error = abort_merge_fn(repo_path=repo_root_path)
    if not abort_success:
        logger.error(f"   ❌ Failed to abort merge: {abort_error}")
        if ctx.item_logger:
            ctx.item_logger.log_error(f"❌ ORCHESTRATOR: Failed to abort merge: {abort_error}")
        return False
    logger.info("   ✅ Merge aborted, will retry")
    return True


def _handle_retry_success(
    ctx: WorktreeMergeContext,
    attempt: int,
    tracker: MergeStepTracker,
    remove_from_manifest_fn: Callable[[str], None],
    add_uncleaned_fn: Callable[[str, str, str], None],
) -> tuple[bool, bool]:
    """Handle a successful retry merge."""
    tracker.complete_step("11l", f"Merge succeeded on attempt {attempt}")
    remove_from_manifest_fn(ctx.agent_id)
    worktree_cleaned = not ctx.worktree_path.exists()
    if not worktree_cleaned:
        logger.error("Worktree directory persists after retry merge: %s", ctx.worktree_path)
        add_uncleaned_fn(ctx.agent_id, str(ctx.worktree_path), "Worktree persists after successful retry merge")
    logger.info("   Merged worktree" + (" and cleaned up" if worktree_cleaned else " (cleanup incomplete)"))
    if ctx.item_logger:
        ctx.item_logger.log(
            f"✅ ORCHESTRATOR: Retry merge succeeded"
            f"{' and cleaned up' if worktree_cleaned else ' (cleanup incomplete)'}"
        )
    return True, worktree_cleaned
