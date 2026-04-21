"""Helper functions for merge operations in worktree management."""

import logging
import subprocess

from pokepoke.git.git_helpers import run_git as _run_git
from pokepoke.git.git_operations import get_default_branch, sanitize_branch_name, validate_post_merge
from pokepoke.utils.constants import BRANCH_PREFIX
from pokepoke.worktrees.merge_result import MergeResult

logger = logging.getLogger(__name__)


def rollback_merge_commit(reason: str, cwd: str | None = None) -> bool:
    """Attempt to rollback the last merge commit and log the outcome.

    Returns True if rollback succeeded, False otherwise.
    """
    try:
        _run_git(["git", "reset", "--hard", "HEAD~1"], cwd=cwd)
        logger.info("Rolled back merge commit: %s", reason)
        logger.info(f"🔄 Rolled back merge commit due to {reason}")
        return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as reset_err:
        logger.critical(
            "FAILED to rollback merge commit after %s: %s — "
            "local repo may have a merge commit that could not be undone. "
            "Manual intervention required.",
            reason, reset_err,
        )
        return False


def rollback_and_fail(reason: str, cwd: str | None = None) -> MergeResult:
    """Roll back the merge commit and return a failure MergeResult."""
    rolled_back = rollback_merge_commit(reason, cwd=cwd)
    if not rolled_back:
        logger.critical(
            "ROLLBACK FAILED after %s — "
            "repo has a merge commit that could not be undone. Manual intervention required.",
            reason,
        )
    return MergeResult(success=False, rollback_failed=not rolled_back)


def log_merge_failure(merge_error: str | None, unmerged_files: list[str]) -> None:
    """Log details about a merge failure."""
    if unmerged_files:
        logger.error(f"❌ Merge conflicts detected in {len(unmerged_files)} file(s):")
        for f in unmerged_files[:10]:
            logger.info(f"   - {f}")
        if len(unmerged_files) > 10:
            logger.info(f"   ... and {len(unmerged_files) - 10} more")
    else:
        logger.error(f"❌ Merge failed: {merge_error}")


def validate_post_merge_or_rollback(target_branch: str, cwd: str | None = None) -> MergeResult | None:
    """Run post-merge validation.  Failure is a CRITICAL invariant violation.

    After a successful ``git merge --no-ff`` the repo MUST be on the target
    branch with no uncommitted changes.  If either check fails it indicates
    git state corruption, a filesystem issue, or a bug in the merge sequence.

    On failure the repo state is **preserved** (no rollback) so it can be
    inspected manually, and a CRITICAL log with diagnostics is emitted.
    The returned MergeResult has ``halt_required=True`` to signal the
    orchestrator to stop processing further items.

    Returns None if validation passed, or a failure MergeResult otherwise.
    """
    try:
        if not validate_post_merge(target_branch, cwd=cwd):
            _log_post_merge_diagnostics(target_branch, cwd)
            return MergeResult(success=False, halt_required=True)
    except Exception as e:
        logger.critical(
            "POST-MERGE VALIDATION EXCEPTION — repo state preserved for investigation: %s",
            e, exc_info=True,
        )
        _log_post_merge_diagnostics(target_branch, cwd)
        return MergeResult(success=False, halt_required=True)
    return None


def _log_post_merge_diagnostics(target_branch: str, cwd: str | None) -> None:
    """Emit CRITICAL-level diagnostics after a post-merge invariant violation."""
    diag_parts: list[str] = []
    try:
        status = _run_git(["git", "status", "--short"], cwd=cwd).stdout.strip()
        diag_parts.append(f"git status:\n{status or '(clean)'}")
    except Exception:
        diag_parts.append("git status: <unavailable>")
    try:
        log_out = _run_git(
            ["git", "log", "--oneline", "-5"], cwd=cwd,
        ).stdout.strip()
        diag_parts.append(f"git log -5:\n{log_out}")
    except Exception:
        diag_parts.append("git log: <unavailable>")
    try:
        branch = _run_git(
            ["git", "branch", "--show-current"], cwd=cwd,
        ).stdout.strip()
        diag_parts.append(f"current branch: {branch}")
    except Exception:
        diag_parts.append("current branch: <unavailable>")

    diagnostics = "\n".join(diag_parts)
    logger.critical(
        "🚨 POST-MERGE INVARIANT VIOLATION — repo state preserved (no rollback).\n"
        "Expected to be on '%s' with clean status after merge.\n"
        "This indicates git state corruption or a merge sequence bug.\n"
        "The orchestrator will halt. Manual investigation required.\n\n%s",
        target_branch, diagnostics,
    )


def is_worktree_merged(item_id: str, target_branch: str | None = None, repo_path: str | None = None) -> bool:
    """Check if a worktree's branch has been merged into the target branch."""
    sanitized_id = sanitize_branch_name(item_id)
    branch_name = f"{BRANCH_PREFIX}{sanitized_id}"
    if target_branch is None:
        target_branch = get_default_branch(cwd=repo_path)
    try:
        result = _run_git(["git", "branch", "--merged", target_branch], cwd=repo_path)
        return any(branch_name in branch for branch in result.stdout.splitlines())
    except subprocess.CalledProcessError:
        return False
