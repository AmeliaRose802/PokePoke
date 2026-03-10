"""Git worktree management for PokePoke."""

import contextlib
import logging
import subprocess
import time
from pathlib import Path

from pokepoke.constants import BRANCH_PREFIX, WORKTREE_DIR
from pokepoke.perf_timing import timed_block
from pokepoke.git_helpers import run_git as _run_git
from pokepoke.git_operations import (
    sanitize_branch_name,
    get_default_branch,
    is_worktree_clean,
    execute_merge_sequence,
    validate_post_merge,
    list_worktrees,
)
from pokepoke.worktree_helpers import (
    validate_worktree_integrity as _validate_worktree_integrity,
    sync_and_ensure_clean_main_repo as _sync_and_ensure_clean_main_repo,
)
from pokepoke.worktree_cleanup import (
    cleanup_after_merge,
    cleanup_worktree_and_branch,
    force_remove_directory,
)
from pokepoke.coordination import with_worktree_lock

logger = logging.getLogger(__name__)


def _find_existing_worktree(worktree_path: Path, branch_name: str, item_id: str) -> Path | None:
    """Check if a worktree for this item already exists and return its path."""
    existing_worktrees = list_worktrees()
    for wt in existing_worktrees:
        wt_path = Path(wt.get("path", ""))
        if wt_path == worktree_path.resolve() or wt.get("branch", "").endswith(branch_name):
            return wt_path
    return None


def _check_existing_directory(worktree_path: Path) -> Path | None:
    """Handle a directory that exists but wasn't in list_worktrees.

    Returns the path if it's a valid worktree to reuse, None if it was removed.
    Raises RuntimeError if it can't be removed.
    """
    logger.warning(f"Worktree directory {worktree_path} already exists but wasn't in list_worktrees")

    is_valid_worktree = False
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=worktree_path,
            capture_output=True,
            text=True,
            check=True
        )
        if result.stdout.strip() == "true":
            is_valid_worktree = True
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass

    if is_valid_worktree:
        logger.info(f"Directory {worktree_path} is a valid worktree, reusing it")
        print(f"   ♻️  Reusing existing worktree directory at {worktree_path}")
        return worktree_path

    logger.warning(f"Directory {worktree_path} is not a valid worktree, removing it")
    print(f"   🧹  Removing stale worktree directory at {worktree_path}")
    if not force_remove_directory(worktree_path):
        raise RuntimeError(f"Failed to remove stale directory {worktree_path}")

    with contextlib.suppress(Exception):
        _run_git(["git", "worktree", "prune"])
    return None


def _handle_branch_already_exists(
    branch_name: str, base_branch: str, worktree_path: Path, item_id: str, creation_start: float, stderr: str
) -> Path | None:
    """Handle 'branch already exists' or 'already checked out' errors.

    Returns the worktree path on recovery, None if unrecoverable.
    Raises RuntimeError on retry failure.
    """
    logger.warning(f"Branch {branch_name} already exists, attempting to find existing worktree")
    existing_worktrees = list_worktrees()
    for wt in existing_worktrees:
        if wt.get("branch", "").endswith(branch_name):
            logger.info(f"Found existing worktree for {branch_name} at {wt['path']}")
            print(f"   ♻️  Reusing existing worktree at {wt['path']}")
            return Path(wt["path"])

    # No active worktree uses this branch — it's a stale leftover.
    if "already exists" in stderr.lower():
        logger.info(f"Branch {branch_name} is stale (no active worktree) — deleting and retrying")
        print(f"   🧹 Cleaning up stale branch {branch_name}...")
        try:
            _run_git(["git", "branch", "-D", branch_name])
            _run_git(["git", "worktree", "add", str(worktree_path), "-b", branch_name, base_branch])
            creation_time = time.time() - creation_start
            logger.info(f"Created worktree for {item_id} after stale branch cleanup in {creation_time:.2f}s")
            _validate_worktree_integrity(worktree_path, item_id)
            return worktree_path
        except subprocess.CalledProcessError as retry_e:
            retry_stderr = retry_e.stderr if retry_e.stderr else 'No stderr'
            raise RuntimeError(f"Failed to create worktree after stale branch cleanup: {retry_stderr}") from retry_e

    return None


def create_worktree(item_id: str, base_branch: str | None = None, lock_timeout: float = 300.0) -> Path:
    """Create a git worktree for a work item. Returns existing path if already exists.

    Uses file-based locking to prevent race conditions when multiple agents
    attempt to create worktrees simultaneously.
    """
    sanitized_id = sanitize_branch_name(item_id)
    worktree_path = (Path(WORKTREE_DIR) / f"task-{sanitized_id}").resolve()
    branch_name = f"{BRANCH_PREFIX}{sanitized_id}"

    # Check if worktree already exists (outside lock - no git operation needed)
    existing = _find_existing_worktree(worktree_path, branch_name, item_id)
    if existing:
        logger.debug(f"Reusing existing worktree for {item_id} at {existing}")
        print(f"   ♻️  Reusing existing worktree at {existing}")
        return existing

    Path(WORKTREE_DIR).mkdir(exist_ok=True)

    if base_branch is None:
        base_branch = get_default_branch()

    lock_start = time.time()
    try:
        with with_worktree_lock(timeout=lock_timeout), timed_block("worktree.create"):
            lock_wait = time.time() - lock_start
            if lock_wait > 0.1:
                logger.info(f"Waited {lock_wait:.2f}s for worktree lock (item: {item_id})")

            # Double-check after acquiring lock
            existing = _find_existing_worktree(worktree_path, branch_name, item_id)
            if existing:
                logger.debug(f"Worktree created by another agent while waiting for lock: {existing}")
                print(f"   ♻️  Reusing worktree created by another agent at {existing}")
                return existing

            if worktree_path.exists():
                reused = _check_existing_directory(worktree_path)
                if reused:
                    return reused

            # Create the worktree
            logger.info(f"Creating worktree for {item_id}: {worktree_path}")
            creation_start = time.time()
            try:
                _run_git(["git", "worktree", "add", str(worktree_path), "-b", branch_name, base_branch])
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
                print(f"   ⚠️  Git error (exit {e.returncode}): {stderr}")

                if "already exists" in stderr.lower() or "already checked out" in stderr.lower():
                    recovered = _handle_branch_already_exists(
                        branch_name, base_branch, worktree_path, item_id, creation_start, stderr
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


def is_worktree_merged(item_id: str, target_branch: str | None = None) -> bool:
    """Check if a worktree's branch has been merged into the target branch."""
    sanitized_id = sanitize_branch_name(item_id)
    branch_name = f"{BRANCH_PREFIX}{sanitized_id}"
    if target_branch is None:
        target_branch = get_default_branch()
    try:
        result = _run_git(["git", "branch", "--merged", target_branch])
        return any(branch_name in branch for branch in result.stdout.splitlines())
    except subprocess.CalledProcessError:
        return False


def _rollback_merge_commit(reason: str) -> None:
    """Attempt to rollback the last merge commit and log the outcome."""
    try:
        _run_git(["git", "reset", "--hard", "HEAD~1"])
        logger.info("Rolled back merge commit: %s", reason)
        print(f"🔄 Rolled back merge commit due to {reason}")
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as reset_err:
        logger.error("Failed to rollback merge commit after %s: %s", reason, reset_err)


def merge_worktree(item_id: str, target_branch: str | None = None, cleanup: bool = True) -> tuple[bool, list[str]]:
    """Merge a worktree's branch into the target branch and optionally clean up.

    Returns (success, unmerged_files). On success: (True, []). On failure: (False, conflicted_files).
    """
    sanitized_id = sanitize_branch_name(item_id)
    branch_name = f"{BRANCH_PREFIX}{sanitized_id}"
    worktree_path = Path(WORKTREE_DIR) / f"task-{sanitized_id}"

    if target_branch is None:
        target_branch = get_default_branch()

    # PRE-MERGE VALIDATION: Verify worktree is clean
    if not is_worktree_clean(worktree_path):
        print("❌ Pre-merge validation failed: Worktree has uncommitted changes")
        return False, []

    print("✅ Pre-merge validation passed: Worktree is clean")

    if not _sync_and_ensure_clean_main_repo(branch_name):
        return False, []

    # Execute merge sequence with proper error handling
    merge_success, merge_error, unmerged_files = execute_merge_sequence(branch_name, target_branch)

    if not merge_success:
        if unmerged_files:
            print(f"❌ Merge conflicts detected in {len(unmerged_files)} file(s):")
            for f in unmerged_files[:10]:
                print(f"   - {f}")
            if len(unmerged_files) > 10:
                print(f"   ... and {len(unmerged_files) - 10} more")
        else:
            print(f"❌ Merge failed: {merge_error}")
        return False, unmerged_files

    print(f"✅ Merged {branch_name} into {target_branch}")

    try:
        if not validate_post_merge(target_branch):
            logger.warning("Post-merge validation failed, rolling back merge commit")
            _rollback_merge_commit("post-merge validation failure")
            return False, []
    except Exception as e:
        logger.error("Post-merge validation raised exception: %s", e)
        _rollback_merge_commit("post-merge validation exception")
        return False, []

    print(f"✅ Post-merge validation passed: {target_branch} is clean")

    try:
        _run_git(["git", "push"], timeout=120)
        print(f"✅ Pushed {target_branch} to remote")
    except subprocess.CalledProcessError as e:
        print(f"❌ Push failed: {e.stderr if e.stderr else str(e)}")
        _rollback_merge_commit("push failure")
        return False, []

    # Verify branch is actually merged (warnings only - push already succeeded)
    if not is_worktree_merged(item_id, target_branch):
        print(f"\u26a0\ufe0f  Post-push merge verification failed for {branch_name}, but push succeeded")
        logger.warning(f"Post-push merge verification failed for {branch_name}, but push to {target_branch} succeeded")
    else:
        print(f"✅ Merge confirmed: {branch_name} is merged into {target_branch}")

    if cleanup:
        cleanup_after_merge(worktree_path, branch_name)

    return True, []  # Merge completed


def cleanup_worktree(item_id: str, force: bool = False) -> bool:
    """Remove a worktree and its associated branch.

    Returns True if cleanup succeeds or if the worktree/branch don't exist.
    """
    sanitized_id = sanitize_branch_name(item_id)
    branch_name = f"{BRANCH_PREFIX}{sanitized_id}"
    expected_worktree_path = Path(WORKTREE_DIR) / f"task-{sanitized_id}"

    # Find the actual worktree for this item (might have unsanitized path if created before fix)
    actual_worktree_path: Path | None = None
    existing_worktrees = list_worktrees()

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
        unsanitized_path = Path(WORKTREE_DIR) / f"task-{item_id}"
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
    )


