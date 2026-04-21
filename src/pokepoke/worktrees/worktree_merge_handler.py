"""Worktree merge handling — single source of truth for merge-attempt-cleanup-retry logic.

Both the task-finalization path (worktree_finalization.merge_worktree_to_dev) and
the maintenance-agent path (handle_worktree_merge) delegate to perform_worktree_merge.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
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
from pokepoke.worktrees.coordination import merge_lock
from pokepoke.worktrees.merge_step_tracker import get_merge_step_tracker
from pokepoke.worktrees.worktree_cleanup import add_uncleaned_worktree
from pokepoke.worktrees.worktrees import cleanup_worktree, merge_worktree

logger = logging.getLogger(__name__)

DEFAULT_MAX_CONFLICT_RETRIES = 3


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
    max_conflict_retries: int = DEFAULT_MAX_CONFLICT_RETRIES


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

    try:
        with merge_lock():
            tracker.complete_step("1", f"Acquired merge lock for {ctx.agent_id}")
            logger.info("Acquired merge lock for agent %s", ctx.agent_id)
            # Fall back to agent_id for cleanup parent if no parent_agent_id
            if not ctx.parent_agent_id:
                ctx.parent_agent_id = ctx.agent_id
            result = perform_worktree_merge(ctx)
            outcome = "success" if result[0] else "failed"
            tracker.finish_run(outcome)
            return result
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

        # Retry loop: invoke conflict cleanup agent, abort stale merge, retry
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
            with cleanup_lock():
                cleanup_ok, _ = invoke_merge_conflict_cleanup_agent(
                    ctx.agent_item,
                    f"Merge conflict detected in {len(unmerged_files)} file(s)"
                    f"{conflict_details}{attempt_context}",
                    unmerged_files=unmerged_files,
                    cwd=repo_cwd,
                    parent_agent_id=ctx.parent_agent_id,
                    wait_for_merge=False,
                    item_logger=ctx.item_logger,
                )

            if not cleanup_ok:
                logger.error("   Cleanup failed (attempt %d/%d).", attempt, max_retries)
                tracker.fail_step("11l", f"Cleanup agent failed (attempt {attempt})")
                if is_merge_in_progress(repo_path=repo_root_path):
                    logger.info("   Aborting merge to reset state...")
                    abort_success, abort_error = abort_merge(repo_path=repo_root_path)
                    if not abort_success:
                        logger.error("Failed to abort merge after cleanup failure for %s: %s", ctx.agent_id, abort_error)
                        logger.warning("   ⚠️  Repository may be stuck in merge-in-progress state")
                return False, False

            logger.info("   Cleanup successful, retrying merge (attempt %d/%d)...", attempt, max_retries)
            if is_merge_in_progress(repo_path=repo_root_path):
                logger.warning("   ⚠️  Merge still in progress after cleanup - aborting to reset state")
                abort_success, abort_error = abort_merge(repo_path=repo_root_path)
                if not abort_success:
                    logger.error(f"   ❌ Failed to abort merge: {abort_error}")
                    return False, False
                logger.info("   ✅ Merge aborted, will retry")

            retry_result = merge_worktree(ctx.agent_id, cleanup=True, repo_path=repo_cwd)
            if retry_result.rollback_failed:
                logger.critical(
                    "🚨 REPO CORRUPTION: Rollback failed during retry merge for %s — "
                    "local repo has a merge commit that could not be undone. "
                    "Manual intervention required.",
                    ctx.agent_id,
                )
            if retry_result.success:
                tracker.complete_step("11l", f"Merge succeeded on attempt {attempt}")
                remove_from_manifest(ctx.agent_id)
                worktree_cleaned = not ctx.worktree_path.exists()
                if not worktree_cleaned:
                    logger.error("Worktree directory persists after retry merge: %s", ctx.worktree_path)
                    add_uncleaned_worktree(ctx.agent_id, str(ctx.worktree_path), "Worktree persists after successful retry merge")
                logger.info("   Merged worktree" + (" and cleaned up" if worktree_cleaned else " (cleanup incomplete)"))
                return True, worktree_cleaned

            # Merge still failed — collect context for next attempt
            new_unmerged = retry_result.unmerged_files or get_unmerged_files(repo_path=repo_root_path)
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
                if is_merge_in_progress(repo_path=repo_root_path):
                    abort_success, abort_error = abort_merge(repo_path=repo_root_path)
                    if not abort_success:
                        logger.error("Failed to abort merge between retries for %s: %s", ctx.agent_id, abort_error)
                        return False, False
                unmerged_files = new_unmerged
            else:
                logger.error("   All %d conflict retry attempts exhausted for %s.", max_retries, ctx.agent_id)
                if is_merge_in_progress(repo_path=repo_root_path):
                    abort_success, abort_error = abort_merge(repo_path=repo_root_path)
                    if not abort_success:
                        logger.error("Failed to abort merge after final retry for %s: %s", ctx.agent_id, abort_error)
                return False, False

        return False, False

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
