"""Git worktree management for PokePoke."""

import contextlib
import logging
import subprocess
import time
from pathlib import Path

from pokepoke.git.git_helpers import run_git as _run_git
from pokepoke.git.git_helpers import run_git_with_retry as _run_git_with_retry
from pokepoke.git.git_operations import (
    execute_merge_sequence,
    get_default_branch,
    is_worktree_clean,
    list_worktrees,
    sanitize_branch_name,
    validate_post_merge,
)
from pokepoke.stats.perf_timing import timed_block
from pokepoke.utils.constants import BRANCH_PREFIX, WORKTREE_DIR, WORKTREE_TASK_PREFIX
from pokepoke.worktrees.coordination import with_worktree_lock
from pokepoke.worktrees.merge_result import MergeResult as MergeResult  # re-export
from pokepoke.worktrees.worktree_cleanup import (
    cleanup_after_merge,
    cleanup_worktree_and_branch,
    force_remove_directory,
)
from pokepoke.worktrees.worktree_helpers import (
    sync_and_ensure_clean_main_repo as _sync_and_ensure_clean_main_repo,
)
from pokepoke.worktrees.worktree_helpers import (
    validate_worktree_integrity as _validate_worktree_integrity,
)

logger = logging.getLogger(__name__)


def _find_existing_worktree(worktree_path: Path, branch_name: str, item_id: str, repo_path: str | None = None) -> Path | None:
    """Check if a worktree for this item already exists and return its path.

    Also verifies the worktree is on the expected branch.
    """
    existing_worktrees = list_worktrees(cwd=repo_path)
    for wt in existing_worktrees:
        wt_path = Path(wt.get("path", ""))
        if wt_path == worktree_path.resolve() or wt.get("branch", "").endswith(branch_name):
            # Verify the worktree is actually on the expected branch
            # Only check if the directory actually exists (skip check during testing with mocks)
            if wt_path.exists():
                try:
                    result = _run_git(
                        ["git", "branch", "--show-current"],
                        cwd=str(wt_path),
                        timeout=10,
                        check=False,
                    )
                    if result.returncode == 0:
                        current_branch = result.stdout.strip()
                        if current_branch != branch_name:
                            logger.warning(
                                f"Existing worktree at {wt_path} is on wrong branch '{current_branch}' "
                                f"(expected '{branch_name}'). Ignoring this worktree."
                            )
                            continue
                except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
                    logger.warning(f"Failed to verify branch for worktree at {wt_path}: {e}")
                    continue
            return wt_path
    return None


def _check_existing_directory(worktree_path: Path, repo_path: str | None = None) -> Path | None:
    """Handle a directory that exists but wasn't in list_worktrees.

    Returns the path if it's a valid worktree to reuse, None if it was removed.
    Raises RuntimeError if it can't be removed.
    """
    logger.warning(f"Worktree directory {worktree_path} already exists but wasn't in list_worktrees")

    is_valid_worktree = False
    try:
        result = _run_git(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=str(worktree_path),
            timeout=10,
            check=False,
        )
        if result.stdout.strip() == "true":
            is_valid_worktree = True
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass

    if is_valid_worktree:
        # Additional check: verify it's on the expected branch
        from pokepoke.utils.constants import BRANCH_PREFIX

        # Extract item_id from the path (task-{item_id})
        dir_name = worktree_path.name
        if dir_name.startswith(WORKTREE_TASK_PREFIX):
            sanitized_id = dir_name[len(WORKTREE_TASK_PREFIX):]
            expected_branch = f"{BRANCH_PREFIX}{sanitized_id}"

            try:
                branch_result = _run_git(
                    ["git", "branch", "--show-current"],
                    cwd=str(worktree_path),
                    timeout=10,
                    check=False,
                )
                if branch_result.returncode == 0:
                    current_branch = branch_result.stdout.strip()
                    # Only enforce branch check if we got a valid-looking branch name
                    # (contains slash or starts with expected prefix, and isn't a git status like "true")
                    if (current_branch and (
                        "/" in current_branch or
                        current_branch.startswith(BRANCH_PREFIX) or
                        current_branch.startswith("refs/")
                    ) and current_branch != expected_branch):
                        logger.warning(
                            f"Directory {worktree_path} is on wrong branch '{current_branch}' "
                            f"(expected '{expected_branch}'). Removing it."
                        )
                        logger.info(f"   🧹  Removing worktree with wrong branch at {worktree_path}")
                        if not force_remove_directory(worktree_path):
                            raise RuntimeError(f"Failed to remove worktree with wrong branch {worktree_path}")
                        with contextlib.suppress(Exception):
                            _run_git(["git", "worktree", "prune"], cwd=repo_path)
                        return None
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
                logger.warning(f"Failed to verify branch for worktree at {worktree_path}: {e}")

        logger.info(f"Directory {worktree_path} is a valid worktree, reusing it")
        logger.info(f"   ♻️  Reusing existing worktree directory at {worktree_path}")
        return worktree_path

    logger.warning(f"Directory {worktree_path} is not a valid worktree, removing it")
    logger.info(f"   🧹  Removing stale worktree directory at {worktree_path}")
    if not force_remove_directory(worktree_path):
        raise RuntimeError(f"Failed to remove stale directory {worktree_path}")

    with contextlib.suppress(Exception):
        _run_git(["git", "worktree", "prune"], cwd=repo_path)
    return None


def _handle_branch_already_exists(
    branch_name: str, base_branch: str, worktree_path: Path, item_id: str, creation_start: float, stderr: str,
    repo_path: str | None = None,
) -> Path | None:
    """Handle 'branch already exists' or 'already checked out' errors.

    Returns the worktree path on recovery, None if unrecoverable.
    Raises RuntimeError on retry failure.
    """
    logger.warning(f"Branch {branch_name} already exists, attempting to find existing worktree")
    existing_worktrees = list_worktrees(cwd=repo_path)
    for wt in existing_worktrees:
        if wt.get("branch", "").endswith(branch_name):
            logger.info(f"Found existing worktree for {branch_name} at {wt['path']}")
            logger.info(f"   ♻️  Reusing existing worktree at {wt['path']}")
            return Path(wt["path"])

    # No active worktree uses this branch — it's a stale leftover.
    if "already exists" in stderr.lower():
        logger.info(f"Branch {branch_name} is stale (no active worktree) — deleting and retrying")
        logger.info(f"   🧹 Cleaning up stale branch {branch_name}...")
        try:
            _run_git(["git", "branch", "-D", branch_name], cwd=repo_path)
            _run_git(["git", "worktree", "add", str(worktree_path), "-b", branch_name, base_branch], cwd=repo_path)
            creation_time = time.time() - creation_start
            logger.info(f"Created worktree for {item_id} after stale branch cleanup in {creation_time:.2f}s")
            _validate_worktree_integrity(worktree_path, item_id)
            return worktree_path
        except subprocess.CalledProcessError as retry_e:
            retry_stderr = retry_e.stderr if retry_e.stderr else 'No stderr'
            raise RuntimeError(f"Failed to create worktree after stale branch cleanup: {retry_stderr}") from retry_e

    return None


def create_worktree(item_id: str, base_branch: str | None = None, lock_timeout: float = 300.0, repo_path: str | None = None) -> Path:
    """Create a git worktree for a work item. Returns existing path if already exists.

    Uses file-based locking to prevent race conditions when multiple agents
    attempt to create worktrees simultaneously.

    Args:
        item_id: Work item identifier.
        base_branch: Branch to base worktree on (defaults to repo default branch).
        lock_timeout: Seconds to wait for worktree lock.
        repo_path: Target repo root. Worktree is created under this repo's
            directory tree. Defaults to CWD when None.
    """
    sanitized_id = sanitize_branch_name(item_id)
    # Resolve worktree base directory relative to the target repo
    repo_root = Path(repo_path) if repo_path else Path.cwd()
    worktree_path = (repo_root / WORKTREE_DIR / f"{WORKTREE_TASK_PREFIX}{sanitized_id}").resolve()
    branch_name = f"{BRANCH_PREFIX}{sanitized_id}"
    repo_cwd = repo_path  # cwd for git commands

    # Check if worktree already exists (outside lock - no git operation needed)
    existing = _find_existing_worktree(worktree_path, branch_name, item_id, repo_path=repo_cwd)
    if existing:
        logger.debug(f"Reusing existing worktree for {item_id} at {existing}")
        logger.info(f"   ♻️  Reusing existing worktree at {existing}")
        return existing

    (repo_root / WORKTREE_DIR).mkdir(exist_ok=True)

    if base_branch is None:
        base_branch = get_default_branch(cwd=repo_cwd)

    lock_start = time.time()
    try:
        with with_worktree_lock(timeout=lock_timeout), timed_block("worktree.create"):
            lock_wait = time.time() - lock_start
            if lock_wait > 0.1:
                logger.info(f"Waited {lock_wait:.2f}s for worktree lock (item: {item_id})")

            # Double-check after acquiring lock
            existing = _find_existing_worktree(worktree_path, branch_name, item_id, repo_path=repo_cwd)
            if existing:
                logger.debug(f"Worktree created by another agent while waiting for lock: {existing}")
                logger.info(f"   ♻️  Reusing worktree created by another agent at {existing}")
                return existing

            if worktree_path.exists():
                reused = _check_existing_directory(worktree_path, repo_path=repo_cwd)
                if reused:
                    return reused

            # Create the worktree
            logger.info(f"Creating worktree for {item_id}: {worktree_path}")
            creation_start = time.time()
            try:
                _run_git(["git", "worktree", "add", str(worktree_path), "-b", branch_name, base_branch], cwd=repo_cwd)
                creation_time = time.time() - creation_start
                logger.info(f"Created worktree for {item_id} in {creation_time:.2f}s")

            except subprocess.CalledProcessError as e:
                creation_time = time.time() - creation_start
                stderr = e.stderr if e.stderr else 'No stderr available'
                logger.error(
                    f"Git worktree creation failed for {item_id} after {creation_time:.2f}s:\n"
                    f"  Command: git worktree add {worktree_path} -b {branch_name} {base_branch}\n"
                    f"  Exit code: {e.returncode}\n"
                    f"  Stderr: {stderr}"
                )
                logger.error(f"   ⚠️  Git error (exit {e.returncode}): {stderr}")

                if "already exists" in stderr.lower() or "already checked out" in stderr.lower():
                    recovered = _handle_branch_already_exists(
                        branch_name, base_branch, worktree_path, item_id, creation_start, stderr,
                        repo_path=repo_cwd,
                    )
                    if recovered:
                        return recovered

                if "invalid reference" in stderr.lower() or "not a valid" in stderr.lower():
                    raise RuntimeError(
                        f"Base branch '{base_branch}' does not exist. "
                        "Please create it first or specify a different base branch."
                    ) from e

                raise RuntimeError(f"Failed to create worktree: {stderr}") from e

            except subprocess.TimeoutExpired as e:
                creation_time = time.time() - creation_start
                logger.error(f"Git worktree creation timed out for {item_id} after {creation_time:.2f}s")
                raise RuntimeError(f"Timed out creating worktree after {e.timeout}s") from e

    except RuntimeError:
        raise
    except Exception as e:
        logger.error(f"Unexpected error creating worktree for {item_id}: {e}", exc_info=True)
        raise RuntimeError(f"Unexpected error creating worktree: {e}") from e

    _validate_worktree_integrity(worktree_path, item_id)
    return worktree_path


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


def _rollback_merge_commit(reason: str, cwd: str | None = None) -> bool:
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


def merge_worktree(item_id: str, target_branch: str | None = None, cleanup: bool = True, repo_path: str | None = None) -> MergeResult:
    """Merge a worktree's branch into the target branch and optionally clean up.

    Args:
        item_id: Work item identifier.
        target_branch: Branch to merge into (defaults to repo default branch).
        cleanup: Whether to clean up worktree after merge.
        repo_path: Target repo root for git operations. Defaults to CWD.

    Returns:
        MergeResult with success, unmerged_files, and rollback_failed.
        Supports 2-tuple unpacking: ``success, files = merge_worktree(...)``.
    """
    sanitized_id = sanitize_branch_name(item_id)
    branch_name = f"{BRANCH_PREFIX}{sanitized_id}"
    repo_root = Path(repo_path) if repo_path else Path.cwd()
    worktree_path = repo_root / WORKTREE_DIR / f"{WORKTREE_TASK_PREFIX}{sanitized_id}"
    repo_cwd = repo_path

    if target_branch is None:
        target_branch = get_default_branch(cwd=repo_cwd)

    # PRE-MERGE VALIDATION: Verify worktree is clean
    if not is_worktree_clean(worktree_path):
        logger.error("❌ Pre-merge validation failed: Worktree has uncommitted changes")
        return MergeResult(success=False)

    logger.info("✅ Pre-merge validation passed: Worktree is clean")

    if not _sync_and_ensure_clean_main_repo(branch_name, cwd=repo_cwd):
        return MergeResult(success=False)

    # Execute merge sequence with proper error handling
    merge_success, merge_error, unmerged_files = execute_merge_sequence(branch_name, target_branch, cwd=repo_cwd)

    if not merge_success:
        if unmerged_files:
            logger.error(f"❌ Merge conflicts detected in {len(unmerged_files)} file(s):")
            for f in unmerged_files[:10]:
                logger.info(f"   - {f}")
            if len(unmerged_files) > 10:
                logger.info(f"   ... and {len(unmerged_files) - 10} more")
        else:
            logger.error(f"❌ Merge failed: {merge_error}")
        return MergeResult(success=False, unmerged_files=unmerged_files)

    logger.info(f"✅ Merged {branch_name} into {target_branch}")

    try:
        if not validate_post_merge(target_branch, cwd=repo_cwd):
            logger.warning("Post-merge validation failed, rolling back merge commit")
            rolled_back = _rollback_merge_commit("post-merge validation failure", cwd=repo_cwd)
            if not rolled_back:
                logger.critical(
                    "ROLLBACK FAILED after post-merge validation failure — "
                    "repo has an unpushed merge commit. Manual intervention required."
                )
            return MergeResult(success=False, rollback_failed=not rolled_back)
    except Exception as e:
        logger.error("Post-merge validation raised exception: %s", e)
        rolled_back = _rollback_merge_commit("post-merge validation exception", cwd=repo_cwd)
        if not rolled_back:
            logger.critical(
                "ROLLBACK FAILED after post-merge validation exception — "
                "repo has an unpushed merge commit. Manual intervention required."
            )
        return MergeResult(success=False, rollback_failed=not rolled_back)

    logger.info(f"✅ Post-merge validation passed: {target_branch} is clean")

    try:
        _run_git_with_retry(
            ["git", "push"], timeout=120, cwd=repo_cwd,
            max_retries=3, initial_delay=2.0,
            context="git push",
        )
        logger.info(f"✅ Pushed {target_branch} to remote")
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        if isinstance(e, subprocess.CalledProcessError):
            err_detail = e.stderr or str(e)
        else:
            err_detail = str(e)
        logger.error(f"❌ Push failed after retries: {err_detail}")
        rolled_back = _rollback_merge_commit("push failure", cwd=repo_cwd)
        if not rolled_back:
            logger.critical(
                "ROLLBACK FAILED after push failure — "
                "repo has an unpushed merge commit. Manual intervention required."
            )
        return MergeResult(success=False, rollback_failed=not rolled_back)

    # Verify branch is actually merged (warnings only - push already succeeded)
    if not is_worktree_merged(item_id, target_branch, repo_path=repo_cwd):
        logger.error(f"\u26a0\ufe0f  Post-push merge verification failed for {branch_name}, but push succeeded")
        logger.warning(f"Post-push merge verification failed for {branch_name}, but push to {target_branch} succeeded")
    else:
        logger.info(f"✅ Merge confirmed: {branch_name} is merged into {target_branch}")

    if cleanup:
        cleanup_after_merge(worktree_path, branch_name, cwd=repo_cwd)

    return MergeResult(success=True)


def cleanup_worktree(item_id: str, force: bool = False, repo_path: str | None = None) -> bool:
    """Remove a worktree and its associated branch.

    Args:
        item_id: Work item identifier.
        force: Force removal even if worktree has changes.
        repo_path: Target repo root. Defaults to CWD.

    Returns True if cleanup succeeds or if the worktree/branch don't exist.
    """
    sanitized_id = sanitize_branch_name(item_id)
    branch_name = f"{BRANCH_PREFIX}{sanitized_id}"
    repo_root = Path(repo_path) if repo_path else Path.cwd()
    expected_worktree_path = repo_root / WORKTREE_DIR / f"{WORKTREE_TASK_PREFIX}{sanitized_id}"
    repo_cwd = repo_path

    # Find the actual worktree for this item (might have unsanitized path if created before fix)
    actual_worktree_path: Path | None = None
    existing_worktrees = list_worktrees(cwd=repo_cwd)

    # Search by branch name first
    for wt in existing_worktrees:
        wt_branch = wt.get("branch", "")
        if wt_branch.endswith(branch_name):
            actual_worktree_path = Path(wt["path"])
            break

    # If not found by branch, check if expected path exists
    if actual_worktree_path is None and expected_worktree_path.exists():
        actual_worktree_path = expected_worktree_path

    # Also check for unsanitized path (for backwards compatibility)
    if actual_worktree_path is None:
        unsanitized_path = repo_root / WORKTREE_DIR / f"{WORKTREE_TASK_PREFIX}{item_id}"
        if unsanitized_path.exists():
            actual_worktree_path = unsanitized_path

    return cleanup_worktree_and_branch(
        actual_worktree_path,
        branch_name,
        worktree_id=item_id,
        force=force,
        fallback_branch_name=f"{BRANCH_PREFIX}{item_id}",
        skip_branch_delete_if_dir_exists=True,
        print_success=False,
        cwd=repo_cwd,
    )


