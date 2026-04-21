"""Worktree merge handling — single source of truth for merge-attempt-cleanup-retry logic.

Both the task-finalization path (worktree_finalization.merge_worktree_to_dev) and
the maintenance-agent path (handle_worktree_merge) delegate to perform_worktree_merge.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from filelock import Timeout

from pokepoke.agents.cleanup_agents import invoke_cleanup_agent, invoke_merge_conflict_cleanup_agent
from pokepoke.git.git_operations import get_default_branch, is_worktree_clean
from pokepoke.git.repo_state_guard import cleanup_lock
from pokepoke.types_beads import BeadsWorkItem
from pokepoke.types_stats import AgentStats
from pokepoke.utils.constants import WORKTREE_DIR, WORKTREE_TASK_PREFIX

if TYPE_CHECKING:
    from pokepoke.utils.logging_utils import ItemLogger
    from pokepoke.worktrees.merge_step_tracker import MergeStepTracker
from pokepoke.worktrees.coordination import merge_lock
from pokepoke.worktrees.merge_step_tracker import get_merge_step_tracker
from pokepoke.worktrees.merge_conflict_retry import retry_merge_after_cleanup
from pokepoke.worktrees.worktree_cleanup import add_uncleaned_worktree
from pokepoke.worktrees.worktrees import cleanup_worktree, merge_worktree

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
    item_logger: 'ItemLogger | None' = None


@dataclass
class _ConflictResolutionNeeded:
    """Signal that conflicted merge was aborted and needs out-of-lock cleanup."""
    conflict_details: str
    unmerged_files: list[str] = field(default_factory=list)


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
    tracker = get_merge_step_tracker()
    item_id = ctx.agent_item.id if ctx.agent_item else ctx.agent_id
    tracker.begin_run(ctx.agent_id, item_id)
    tracker.complete_step("0", "Agent work complete")

    # --- Pre-lock checks (read-only on isolated worktree, no lock needed) ---

    # Step 4: worktree clean?
    # If dirty at this point, it's a pipeline invariant violation — the cleanup
    # phase already ran after the work agent.  CRITICAL + halt.
    tracker.begin_step("4", "Checking worktree cleanliness (pre-lock)…")
    if not is_worktree_clean(ctx.worktree_path):
        # Collect git status for diagnostics
        _diag = ""
        try:
            from pokepoke.git.git_helpers import run_git as _diag_run_git
            _diag = _diag_run_git(
                ["git", "-C", str(ctx.worktree_path), "status", "--short"],
            ).stdout.strip()
        except Exception:
            _diag = "<unavailable>"

        logger.critical(
            "🚨 INVARIANT VIOLATION: Worktree %s has uncommitted changes at merge time. "
            "The cleanup phase should have handled this — this indicates a pipeline bug. "
            "Halting orchestrator. Manual investigation required.\n"
            "git status:\n%s",
            ctx.worktree_path, _diag,
        )
        tracker.fail_step("4", "CRITICAL: worktree dirty after cleanup phase — pipeline bug")
        tracker.finish_run("failed")
        add_uncleaned_worktree(
            ctx.agent_id,
            str(ctx.worktree_path),
            "CRITICAL: Worktree dirty at merge time — invariant violation",
        )
        from pokepoke.utils.shutdown import request_shutdown
        request_shutdown()
        return False, False
    tracker.complete_step("4", "Worktree is clean")

    # Step 5: any commits on the branch?
    tracker.begin_step("5", "Checking commit count (pre-lock)…")
    try:
        from pokepoke.git.git_helpers import run_git
        target_branch = get_default_branch(cwd=ctx.repo_path)
        revlist = run_git(
            ["git", "rev-list", "--count", "HEAD", f"^{target_branch}"],
            cwd=str(ctx.worktree_path),
        )
        commit_count = int(revlist.stdout.strip())
    except Exception as e:
        # Can't determine commit count — proceed to merge (it will check again)
        logger.debug("Could not check commit count pre-lock: %s", e)
        commit_count = -1  # sentinel: unknown

    if commit_count == 0:
        tracker.complete_step("5", "0 commits — skip merge")
        tracker.begin_step("5a", "Cleaning up empty worktree (no lock needed)…")
        logger.info("⏭️  No commits in worktree for %s — skipping merge, cleaning up", ctx.agent_id)
        cleaned = cleanup_worktree(ctx.agent_id, force=True, repo_path=ctx.repo_path)
        tracker.complete_step("5a", "Worktree cleaned up")
        tracker.complete_step("11", "Done (no merge needed)")
        tracker.finish_run("success")
        return True, cleaned

    if commit_count > 0:
        tracker.complete_step("5", f"{commit_count} commit(s) ahead")

    # --- Acquire merge lock for the actual merge ---
    tracker.begin_step("1", "Waiting for merge lock…")

    # Fall back to agent_id for cleanup parent if no parent_agent_id
    if not ctx.parent_agent_id:
        ctx.parent_agent_id = ctx.agent_id

    try:
        with merge_lock():
            tracker.complete_step("1", f"Acquired merge lock for {ctx.agent_id}")
            logger.info("Acquired merge lock for agent %s", ctx.agent_id)
            result = perform_worktree_merge(ctx)

        # --- Lock released here ---

        if not isinstance(result, _ConflictResolutionNeeded):
            outcome = "success" if result[0] else "failed"
            tracker.finish_run(outcome)
            return result

        # Merge hit conflicts, was aborted, and lock is now released.
        # Run cleanup agent outside the lock so other agents can merge.
        conflict_info = result
        logger.info(
            "🔓 Released merge lock — running conflict cleanup agent for %s outside lock",
            ctx.agent_id,
        )

        cleanup_success = _run_conflict_cleanup_outside_lock(ctx, conflict_info, tracker)

        if not cleanup_success:
            tracker.finish_run("failed")
            return False, False

        # Re-acquire merge lock for retry
        tracker.begin_step("1r", "Re-acquiring merge lock for retry…")
        with merge_lock():
            tracker.complete_step("1r", f"Re-acquired merge lock for {ctx.agent_id}")
            logger.info("🔒 Re-acquired merge lock for retry merge of %s", ctx.agent_id)
            retry_result = retry_merge_after_cleanup(ctx, tracker)
            outcome = "success" if retry_result[0] else "failed"
            tracker.finish_run(outcome)
            return retry_result
    except Timeout as e:
        logger.warning("Merge lock timeout for agent %s: %s", ctx.agent_id, e)
        tracker.fail_step("1", f"Lock timeout: {e}")
        tracker.finish_run("failed")

        add_uncleaned_worktree(
            ctx.agent_id,
            str(ctx.worktree_path),
            f"Merge lock timeout after 10 minutes: {e}"
        )
        return False, False
    except Exception as e:
        logger.error("Merge coordination error for agent %s: %s", ctx.agent_id, e, exc_info=True)
        tracker.fail_step("1", f"Coordination error: {e}")
        tracker.finish_run("failed")

        add_uncleaned_worktree(
            ctx.agent_id,
            str(ctx.worktree_path),
            f"Merge coordination error: {e}"
        )
        return False, False


def _run_conflict_cleanup_outside_lock(
    ctx: WorktreeMergeContext,
    conflict_info: _ConflictResolutionNeeded,
    tracker: MergeStepTracker,
) -> bool:
    """Invoke merge conflict cleanup agent while merge lock is released.

    The cleanup agent runs with ``cwd`` set to the isolated worktree path so
    that any edits it makes (e.g. merging the target branch into the
    feature branch and resolving conflicts there) affect ONLY the worktree's
    branch. The main repository is not touched while the merge lock is
    released, so other agents can safely take the lock and merge their own
    work.
    """
    tracker.begin_step("3b", "Invoking merge conflict cleanup agent (outside merge lock)…")
    logger.info("   Invoking cleanup agent to resolve conflicts in isolated worktree...")
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
        tracker.complete_step("3b", "Merge conflict cleanup agent succeeded")
        return True
    tracker.fail_step("3b", "Merge conflict cleanup agent failed")
    logger.error("   Cleanup failed.")
    return False
def perform_worktree_merge(  # noqa: C901
    ctx: WorktreeMergeContext,
) -> tuple[bool, bool] | _ConflictResolutionNeeded:
    """Core merge-attempt-cleanup-retry logic (single source of truth).

    Called by both the task-finalization path and the maintenance-agent path.

    Args:
        ctx: Merge context bundle with agent and worktree information

    Returns:
        Tuple of (merge_success, worktree_cleaned).
    """
    from pokepoke.git.git_operations import check_main_repo_ready_for_merge
    from pokepoke.git.merge_conflict import abort_merge, get_unmerged_files, is_merge_in_progress
    from pokepoke.worktrees.worktree_cleanup import add_uncleaned_worktree, remove_from_manifest

    repo_cwd = ctx.repo_path
    tracker = get_merge_step_tracker()

    # --- pre-merge readiness check ---
    tracker.begin_step("2", "Checking if main repo is clean…")
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

        # Retry cleanup agent up to _MAX_CLEANUP_RETRIES times.
        # If the main repo can't be cleaned, NO merges can succeed — halt.
        _MAX_CLEANUP_RETRIES = 3
        cleaned_up = False
        for attempt in range(1, _MAX_CLEANUP_RETRIES + 1):
            tracker.fail_step("2", f"Not ready: {error_msg}")
            tracker.begin_step("3b", f"Invoking cleanup agent (attempt {attempt}/{_MAX_CLEANUP_RETRIES})…")
            logger.info("   Invoking cleanup agent to resolve uncommitted changes (attempt %d/%d)...", attempt, _MAX_CLEANUP_RETRIES)
            with cleanup_lock():
                cleanup_success, _ = invoke_cleanup_agent(
                    ctx.agent_item,
                    cwd=repo_cwd,
                    parent_agent_id=ctx.parent_agent_id,
                    wait_for_merge=False,
                    item_logger=ctx.item_logger,
                )

            if not cleanup_success:
                logger.error("   Cleanup agent failed (attempt %d/%d).", attempt, _MAX_CLEANUP_RETRIES)
                tracker.fail_step("3b", f"Cleanup agent failed (attempt {attempt})")
                continue

            tracker.complete_step("3b", f"Cleanup agent succeeded (attempt {attempt})")
            tracker.begin_step("3c", "Re-checking main repo…")
            logger.info("   Cleanup successful, retrying merge check...")
            is_ready, error_msg = check_main_repo_ready_for_merge(cwd=repo_cwd)
            if is_ready:
                tracker.complete_step("3c", "Repo clean after cleanup")
                logger.info("   ✅ Repo is ready after cleanup, continuing with merge.")
                remove_from_manifest(ctx.agent_id)
                cleaned_up = True
                break
            else:
                logger.error("   Still failing after cleanup attempt %d: %s", attempt, error_msg)
                tracker.fail_step("3c", f"Still dirty after attempt {attempt}: {error_msg}")

        if not cleaned_up:
            # All retries exhausted — this is an invariant violation.
            # No further merges can succeed while the main repo is dirty.
            from pokepoke.utils.shutdown import request_shutdown
            logger.critical(
                "🚨 MAIN REPO UNCLEANABLE after %d cleanup attempts for %s. "
                "No further merges can succeed while the main repo has dirty files. "
                "Halting orchestrator. Manual cleanup required.\n"
                "Last error: %s",
                _MAX_CLEANUP_RETRIES, ctx.agent_id, error_msg,
            )
            tracker.finish_run("failed")
            request_shutdown()
            return False, False

    # Step 2 passed if we reach here without cleanup
    if tracker._current_run and tracker._current_run.steps["2"].status.value == "active":
        tracker.complete_step("2", "Main repo is clean")

    # --- worktree merge (worktree was already validated pre-lock) ---
    tracker.begin_step("8", f"Merging worktree for {ctx.agent_id}")
    logger.info(f"\n🔀 Merging worktree for {ctx.agent_id}...")
    merge_result = merge_worktree(ctx.agent_id, cleanup=True, repo_path=repo_cwd)
    merge_success = merge_result.success
    unmerged_files = merge_result.unmerged_files

    if merge_result.rollback_failed:
        logger.critical(
            "🚨 REPO CORRUPTION: Rollback failed for %s — "
            "local repo has a merge commit that could not be undone. "
            "Manual intervention required (git reset --hard HEAD~1).",
            ctx.agent_id,
        )

    if merge_result.halt_required:
        from pokepoke.utils.shutdown import request_shutdown
        logger.critical(
            "🚨 Post-merge validation failed for %s — halting orchestrator. "
            "Repo state preserved for manual investigation.",
            ctx.agent_id,
        )
        tracker.fail_step("9", "Post-merge invariant violation — halt requested")
        tracker.finish_run("failed")
        request_shutdown()
        return False, False

    if not merge_success:
        tracker.fail_step("8", "Merge failed")
        repo_root_path = Path(repo_cwd) if repo_cwd else None
        merge_in_progress = is_merge_in_progress(repo_path=repo_root_path)
        if merge_in_progress:
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

        if not merge_in_progress and not unmerged_files:
            return False, False

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

        # Ensure the main repo is clean before releasing the merge lock.
        # merge_worktree() → _handle_merge_failure() already runs
        # `git merge --abort` on conflict, so MERGE_HEAD is usually gone by
        # now. Only invoke abort_merge() when a merge is still in progress
        # (i.e. the internal abort failed); otherwise proceed directly to
        # out-of-lock cleanup.
        tracker.begin_step("9", "Ensuring merge is aborted before releasing merge lock…")
        if merge_in_progress:
            abort_success, abort_error = abort_merge(repo_path=repo_root_path)
        else:
            abort_success, abort_error = True, ""
            logger.debug("No merge in progress for %s; skipping redundant abort.", ctx.agent_id)

        if not abort_success:
            # CRITICAL: merge is still in progress and abort failed. The
            # `with merge_lock()` wrapper WILL release the lock on return,
            # so halt the orchestrator to prevent other agents from
            # operating on the dirty repo.
            from pokepoke.utils.shutdown import request_shutdown
            logger.critical(
                "🚨 abort_merge failed for %s: %s — main repo stuck in "
                "merge-in-progress state. Halting orchestrator. Manual "
                "intervention required (git merge --abort or git reset --hard HEAD).",
                ctx.agent_id, abort_error,
            )
            tracker.fail_step("9", f"Failed to abort conflicted merge: {abort_error}")
            request_shutdown()
            return False, False
        tracker.complete_step("9", "Repo clean; ready for out-of-lock conflict cleanup")
        logger.info("   ✅ Repo clean; conflict cleanup will run outside merge lock")

        return _ConflictResolutionNeeded(
            conflict_details=f"Merge conflict detected in {len(unmerged_files)} file(s){conflict_details}",
            unmerged_files=unmerged_files,
        )

    # Mark remaining merge steps as done for the success path
    tracker.complete_step("8", "Merge succeeded")
    for sid in ("6", "7", "9"):
        if tracker._current_run and tracker._current_run.steps[sid].status.value == "pending":
            tracker.complete_step(sid)

    # Verify worktree was actually cleaned up
    worktree_cleaned = not ctx.worktree_path.exists()
    if not worktree_cleaned:
        logger.error("Worktree directory persists after merge: %s", ctx.worktree_path)
        add_uncleaned_worktree(ctx.agent_id, str(ctx.worktree_path), "Worktree persists after successful merge")
    else:
        tracker.complete_step("10", "Worktree removed")
    tracker.complete_step("11", "Merge lock released")
    logger.info("   Merged worktree" + (" and cleaned up" if worktree_cleaned else " (cleanup incomplete)"))

    # Invalidate warm sessions after successful merge (codebase may have changed)
    try:
        from pokepoke.models.warm_session_service import refresh_pool_after_merge
        refresh_pool_after_merge(cwd=ctx.repo_path)
    except Exception as e:
        logger.debug(f"Failed to refresh warm session pool after merge: {e}")

    return True, worktree_cleaned
