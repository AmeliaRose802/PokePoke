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

from pokepoke.agents.agent_config import CleanupInvocationConfig
from pokepoke.agents.cleanup_agents import invoke_cleanup_agent
from pokepoke.git.git_operations import get_default_branch, is_worktree_clean
from pokepoke.git.repo_state_guard import cleanup_lock
from pokepoke.types_beads import BeadsWorkItem
from pokepoke.types_stats import AgentStats

if TYPE_CHECKING:
    from pokepoke.utils.logging_utils import ItemLogger
    from pokepoke.worktrees.merge_step_tracker import MergeStepTracker
from pokepoke.worktrees.coordination import merge_lock
from pokepoke.worktrees.merge_conflict_retry import run_conflict_retry_loop
from pokepoke.worktrees.merge_result import MergeResult
from pokepoke.worktrees.merge_step_tracker import get_merge_step_tracker
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
    item_logger: ItemLogger | None = None
    max_conflict_retries: int = DEFAULT_MAX_CONFLICT_RETRIES


@dataclass
class _ConflictResolutionNeeded:
    """Signal that conflicted merge was aborted and needs out-of-lock cleanup."""
    conflict_details: str
    unmerged_files: list[str] = field(default_factory=list)


def _run_pre_lock_checks(
    ctx: WorktreeMergeContext, tracker: MergeStepTracker,
) -> tuple[bool, bool] | None:
    """Pre-lock validation: worktree cleanliness + commit count. None = continue."""
    from pokepoke.worktrees.worktree_cleanup import add_uncleaned_worktree
    tracker.begin_step("4", "Checking worktree cleanliness (pre-lock)…")
    if not is_worktree_clean(ctx.worktree_path):
        _diag = ""
        try:
            from pokepoke.git.git_helpers import run_git as _rg
            _diag = _rg(["git", "-C", str(ctx.worktree_path), "status", "--short"]).stdout.strip()
        except Exception:
            _diag = "<unavailable>"
        logger.critical("🚨 INVARIANT VIOLATION: Worktree %s dirty at merge time. Halting.\n%s", ctx.worktree_path, _diag)
        if ctx.item_logger:
            ctx.item_logger.log_error(f"🚨 ORCHESTRATOR: Worktree dirty at merge time. Halting.\n{_diag}")
        tracker.fail_step("4", "CRITICAL: worktree dirty — pipeline bug")
        tracker.finish_run("failed")
        add_uncleaned_worktree(ctx.agent_id, str(ctx.worktree_path), "CRITICAL: Worktree dirty at merge time")
        from pokepoke.utils.shutdown import request_shutdown
        request_shutdown()
        return False, False
    tracker.complete_step("4", "Worktree is clean")

    tracker.begin_step("5", "Checking commit count (pre-lock)…")
    try:
        from pokepoke.git.git_helpers import run_git
        target = get_default_branch(cwd=ctx.repo_path)
        commit_count = int(run_git(["git", "rev-list", "--count", "HEAD", f"^{target}"], cwd=str(ctx.worktree_path)).stdout.strip())
    except Exception as e:
        logger.debug("Could not check commit count pre-lock: %s", e)
        commit_count = -1

    if commit_count == 0:
        tracker.complete_step("5", "0 commits — skip merge")
        logger.info("⏭️  No commits for %s — skipping merge, cleaning up", ctx.agent_id)
        if ctx.item_logger:
            ctx.item_logger.log(f"⏭️  ORCHESTRATOR: No commits for {ctx.agent_id} — skipping merge")
        cleaned = cleanup_worktree(ctx.agent_id, force=True, repo_path=ctx.repo_path)
        tracker.complete_step("11", "Done (no merge needed)")
        tracker.finish_run("success")
        return True, cleaned
    if commit_count > 0:
        tracker.complete_step("5", f"{commit_count} commit(s) ahead")
    return None


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
    early_result = _run_pre_lock_checks(ctx, tracker)
    if early_result is not None:
        return early_result

    # --- Acquire merge lock for the actual merge ---
    tracker.begin_step("1", "Waiting for merge lock…")

    # Fall back to agent_id for cleanup parent if no parent_agent_id
    if not ctx.parent_agent_id:
        ctx.parent_agent_id = ctx.agent_id

    from pokepoke.worktrees.worktree_cleanup import add_uncleaned_worktree
    try:
        with merge_lock():
            tracker.complete_step("1", f"Acquired merge lock for {ctx.agent_id}")
            logger.info("Acquired merge lock for agent %s", ctx.agent_id)
            if ctx.item_logger:
                ctx.item_logger.log(f"🔒 ORCHESTRATOR: Acquired merge lock for {ctx.agent_id}")
            result = perform_worktree_merge(ctx)

        # --- Lock released here ---

        if not isinstance(result, _ConflictResolutionNeeded):
            outcome = "success" if result[0] else "failed"
            tracker.finish_run(outcome)
            return result

        # Merge hit conflicts, was aborted, and lock is now released.
        # Run cleanup agent outside the lock so other agents can merge.
        # Loop up to max_conflict_retries times (cleanup outside lock → retry inside lock).
        result_tuple = run_conflict_retry_loop(ctx, result, tracker)
        return result_tuple
    except Timeout as e:
        logger.warning("Merge lock timeout for agent %s: %s", ctx.agent_id, e)
        if ctx.item_logger:
            ctx.item_logger.log_error(f"🔒 ORCHESTRATOR: Lock timeout for {ctx.agent_id}: {e}")
        tracker.fail_step("1", f"Lock timeout: {e}")
        tracker.finish_run("failed")
        add_uncleaned_worktree(ctx.agent_id, str(ctx.worktree_path), f"Lock timeout: {e}")
        return False, False
    except Exception as e:
        logger.error("Merge coordination error for agent %s: %s", ctx.agent_id, e, exc_info=True)
        if ctx.item_logger:
            ctx.item_logger.log_error(f"🔒 ORCHESTRATOR: Merge coordination error for {ctx.agent_id}: {e}")
        tracker.fail_step("1", f"Coordination error: {e}")
        tracker.finish_run("failed")
        add_uncleaned_worktree(ctx.agent_id, str(ctx.worktree_path), f"Coordination error: {e}")
        return False, False


def _handle_merge_conflict(
    ctx: WorktreeMergeContext,
    tracker: MergeStepTracker,
    repo_cwd: str | None,
    *,
    merge_in_progress: bool,
    unmerged_files: list[str],
) -> tuple[bool, bool] | _ConflictResolutionNeeded:
    """Handle a failed merge — abort if needed and return conflict signal."""
    from pokepoke.git.merge_conflict import abort_merge, get_unmerged_files
    from pokepoke.worktrees.worktree_cleanup import add_uncleaned_worktree

    tracker.fail_step("8", "Merge failed")
    repo_root_path = Path(repo_cwd) if repo_cwd else None

    if merge_in_progress:
        logger.error("\n❌ Worktree merge has conflicts!")
        if ctx.item_logger:
            ctx.item_logger.log_error(f"❌ ORCHESTRATOR: Merge conflicts for {ctx.agent_id}")
    else:
        logger.error("\n❌ Worktree merge failed!")
        if ctx.item_logger:
            ctx.item_logger.log_error(f"❌ ORCHESTRATOR: Merge failed for {ctx.agent_id}")
        if not unmerged_files:
            unmerged_files = get_unmerged_files(repo_path=repo_root_path)

    if unmerged_files:
        logger.info(f"   Conflicted files ({len(unmerged_files)}):")
        for f in unmerged_files[:10]:
            logger.info(f"      - {f}")
        if len(unmerged_files) > 10:
            logger.info(f"      ... and {len(unmerged_files) - 10} more")
        if ctx.item_logger:
            ctx.item_logger.log(
                f"⚠️  ORCHESTRATOR: {len(unmerged_files)} conflicted files: "
                + ", ".join(unmerged_files[:5])
                + (f" ... +{len(unmerged_files) - 5} more" if len(unmerged_files) > 5 else "")
            )

    if not merge_in_progress and not unmerged_files:
        return False, False

    add_uncleaned_worktree(
        ctx.agent_id, str(ctx.worktree_path),
        f"Merge conflict in {len(unmerged_files) if unmerged_files else 0} file(s)",
    )

    conflict_details = ""
    if unmerged_files:
        conflict_details = "\n**Conflicted Files:**\n" + "\n".join(f"- `{f}`" for f in unmerged_files)

    # Ensure merge is aborted before releasing lock. merge_worktree() usually
    # already aborted; only call abort_merge() if MERGE_HEAD still present.
    tracker.begin_step("9", "Ensuring merge is aborted before releasing merge lock…")
    if merge_in_progress:
        abort_success, abort_error = abort_merge(repo_path=repo_root_path)
    else:
        abort_success, abort_error = True, ""
        logger.debug("No merge in progress for %s; skipping redundant abort.", ctx.agent_id)

    if not abort_success:
        from pokepoke.utils.shutdown import request_shutdown
        logger.critical(
            "🚨 abort_merge failed for %s: %s — halting. Manual intervention required.",
            ctx.agent_id, abort_error,
        )
        tracker.fail_step("9", f"Failed to abort: {abort_error}")
        request_shutdown()
        return False, False

    tracker.complete_step("9", "Repo clean; ready for out-of-lock conflict cleanup")
    logger.info("   ✅ Repo clean; conflict cleanup will run outside merge lock")
    return _ConflictResolutionNeeded(
        conflict_details=f"Merge conflict detected in {len(unmerged_files)} file(s){conflict_details}",
        unmerged_files=unmerged_files,
    )


def _ensure_main_repo_ready(
    ctx: WorktreeMergeContext,
    tracker: MergeStepTracker,
    repo_cwd: str | None,
) -> bool:
    """Check repo readiness and invoke cleanup if needed. Returns False to abort."""
    from pokepoke.git.git_operations import check_main_repo_ready_for_merge
    from pokepoke.worktrees.worktree_cleanup import add_uncleaned_worktree, remove_from_manifest

    tracker.begin_step("2", "Checking if main repo is clean…")
    logger.info("\n🔍 Checking if main repo is ready for merge...")
    if ctx.item_logger:
        ctx.item_logger.log("🔍 ORCHESTRATOR: Checking if main repo is ready for merge")
    is_ready, error_msg = check_main_repo_ready_for_merge(cwd=repo_cwd)

    if is_ready:
        tracker.complete_step("2", "Main repo is clean")
        return True

    logger.error(f"\n⚠️  Cannot merge: {error_msg}")
    if ctx.item_logger:
        ctx.item_logger.log(f"⚠️  ORCHESTRATOR: Not ready: {error_msg} — invoking cleanup")
    add_uncleaned_worktree(ctx.agent_id, str(ctx.worktree_path), f"Not ready: {error_msg}")

    _MAX_RETRIES = 3
    for attempt in range(1, _MAX_RETRIES + 1):
        tracker.fail_step("2", f"Not ready: {error_msg}")
        tracker.begin_step("3b", f"Invoking cleanup agent (attempt {attempt}/{_MAX_RETRIES})…")
        logger.info("   Cleanup attempt %d/%d...", attempt, _MAX_RETRIES)
        with cleanup_lock():
            ok, _ = invoke_cleanup_agent(
                ctx.agent_item,
                config=CleanupInvocationConfig(
                    cwd=repo_cwd, parent_agent_id=ctx.parent_agent_id,
                    wait_for_merge=False, item_logger=ctx.item_logger,
                ),
            )
        if not ok:
            logger.error("   Cleanup failed (attempt %d/%d).", attempt, _MAX_RETRIES)
            if ctx.item_logger:
                ctx.item_logger.log_error(f"❌ ORCHESTRATOR: Cleanup failed (attempt {attempt}/{_MAX_RETRIES})")
            tracker.fail_step("3b", f"Cleanup failed (attempt {attempt})")
            continue

        tracker.complete_step("3b", f"Cleanup succeeded (attempt {attempt})")
        tracker.begin_step("3c", "Re-checking main repo…")
        is_ready, error_msg = check_main_repo_ready_for_merge(cwd=repo_cwd)
        if is_ready:
            tracker.complete_step("3c", "Repo clean after cleanup")
            logger.info("   ✅ Repo ready after cleanup attempt %d.", attempt)
            remove_from_manifest(ctx.agent_id)
            return True
        logger.error("   Still dirty after attempt %d: %s", attempt, error_msg)
        if ctx.item_logger:
            ctx.item_logger.log_error(f"❌ ORCHESTRATOR: Still dirty after attempt {attempt}: {error_msg}")
        tracker.fail_step("3c", f"Still dirty: {error_msg}")

    from pokepoke.utils.shutdown import request_shutdown
    logger.critical(
        "🚨 MAIN REPO UNCLEANABLE after %d attempts for %s. Halting.\nLast error: %s",
        _MAX_RETRIES, ctx.agent_id, error_msg,
    )
    if ctx.item_logger:
        ctx.item_logger.log_error(f"🚨 ORCHESTRATOR: Uncleanable after {_MAX_RETRIES} attempts. Halting.")
    tracker.finish_run("failed")
    request_shutdown()
    return False


def perform_worktree_merge(
    ctx: WorktreeMergeContext,
) -> tuple[bool, bool] | _ConflictResolutionNeeded:
    """Core merge logic: readiness check, merge attempt, conflict signal."""
    from pokepoke.git.merge_conflict import is_merge_in_progress
    from pokepoke.worktrees.worktree_cleanup import add_uncleaned_worktree

    repo_cwd = ctx.repo_path
    tracker = get_merge_step_tracker()

    # --- pre-merge readiness check ---
    if not _ensure_main_repo_ready(ctx, tracker, repo_cwd):
        return False, False

    # --- worktree merge (worktree was already validated pre-lock) ---
    tracker.begin_step("8", f"Merging worktree for {ctx.agent_id}")
    logger.info(f"\n🔀 Merging worktree for {ctx.agent_id}...")
    if ctx.item_logger:
        ctx.item_logger.log(f"🔀 ORCHESTRATOR: Merging worktree for {ctx.agent_id} to default branch")
    merge_result = merge_worktree(ctx.agent_id, cleanup=True, repo_path=repo_cwd)
    if not isinstance(merge_result, MergeResult):
        from pokepoke.utils.shutdown import request_shutdown
        logger.critical(
            "🚨 INVARIANT VIOLATION: merge_worktree(%s) returned %s instead of MergeResult. Halting.",
            ctx.agent_id,
            type(merge_result).__name__,
        )
        if ctx.item_logger:
            ctx.item_logger.log_error(
                f"🚨 ORCHESTRATOR: merge_worktree returned invalid type "
                f"({type(merge_result).__name__}) for {ctx.agent_id}. Halting."
            )
        tracker.fail_step("8", "merge_worktree returned invalid type")
        tracker.finish_run("failed")
        request_shutdown()
        return False, False

    merge_success = merge_result.success
    unmerged_files = merge_result.unmerged_files
    rollback_failed = merge_result.rollback_failed
    halt_required = merge_result.halt_required

    if rollback_failed:
        logger.critical("🚨 REPO CORRUPTION: Rollback failed for %s — manual intervention required.", ctx.agent_id)
        if ctx.item_logger:
            ctx.item_logger.log_error(f"🚨 ORCHESTRATOR: REPO CORRUPTION — Rollback failed for {ctx.agent_id}")

    if halt_required:
        from pokepoke.utils.shutdown import request_shutdown
        logger.critical("🚨 Post-merge validation failed for %s — halting.", ctx.agent_id)
        if ctx.item_logger:
            ctx.item_logger.log_error(f"🚨 ORCHESTRATOR: Post-merge validation failed for {ctx.agent_id}")
        tracker.fail_step("9", "Post-merge invariant violation — halt requested")
        tracker.finish_run("failed")
        request_shutdown()
        return False, False

    if not merge_success:
        return _handle_merge_conflict(
            ctx, tracker, repo_cwd, merge_in_progress=is_merge_in_progress(repo_path=Path(repo_cwd) if repo_cwd else None),
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
    status = "and cleaned up" if worktree_cleaned else "(cleanup incomplete)"
    logger.info("   Merged worktree %s", status)
    if ctx.item_logger:
        ctx.item_logger.log(f"✅ ORCHESTRATOR: Merge succeeded for {ctx.agent_id} {status}")

    # Invalidate warm sessions after successful merge
    try:
        from pokepoke.models.warm_session_service import refresh_pool_after_merge
        refresh_pool_after_merge(cwd=ctx.repo_path)
    except Exception:
        pass

    return True, worktree_cleaned
