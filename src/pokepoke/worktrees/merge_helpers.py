"""Helper functions for merge operations in worktree management."""

import logging
import subprocess

from pokepoke.git.git_helpers import run_git as _run_git
from pokepoke.git.git_helpers import run_git_with_retry as _run_git_with_retry
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
            "local repo may have a merged commit that was never pushed. "
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
            "repo has an unpushed merge commit. Manual intervention required.",
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
    """Run post-merge validation, rolling back on failure.

    Returns None if validation passed, or a failure MergeResult otherwise.
    """
    try:
        if not validate_post_merge(target_branch, cwd=cwd):
            logger.warning("Post-merge validation failed, rolling back merge commit")
            return rollback_and_fail("post-merge validation failure", cwd=cwd)
    except Exception as e:
        logger.error("Post-merge validation raised exception: %s", e)
        return rollback_and_fail("post-merge validation exception", cwd=cwd)
    return None


def push_or_rollback(target_branch: str, cwd: str | None = None) -> MergeResult | None:
    """Push the merge commit, rolling back on failure.

    Returns None if push succeeded, or a failure MergeResult otherwise.
    """
    try:
        _run_git_with_retry(
            ["git", "push"], timeout=120, cwd=cwd,
            max_retries=3, initial_delay=2.0,
            context="git push",
        )
        logger.info(f"✅ Pushed {target_branch} to remote")
        return None
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        if isinstance(e, subprocess.CalledProcessError):
            err_detail = e.stderr or str(e)
        else:
            err_detail = str(e)
        logger.error(f"❌ Push failed after retries: {err_detail}")
        return rollback_and_fail("push failure", cwd=cwd)


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
