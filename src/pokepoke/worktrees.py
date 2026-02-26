"""Git worktree management for PokePoke."""

import logging
import subprocess
import time
from pathlib import Path

from pokepoke.git_operations import (
    sanitize_branch_name,
    get_default_branch,
    is_worktree_clean,
    execute_merge_sequence,
    validate_post_merge,
    categorize_git_changes,
    commit_all_changes,
    list_worktrees,
)
from pokepoke.beads_management import run_bd_sync_with_retry
from pokepoke.worktree_cleanup import (
    add_uncleaned_worktree,
    cleanup_after_merge,
    force_remove_directory,
    remove_from_manifest,
    _is_windows_lock_error,
)
from pokepoke.coordination import with_worktree_lock

logger = logging.getLogger(__name__)


def _run_git(cmd: list[str], *, timeout: int = 30, check: bool = True,
             capture_output: bool = True) -> subprocess.CompletedProcess[str]:
    """Run a git command with standard encoding settings."""
    return subprocess.run(
        cmd, check=check, capture_output=capture_output,
        text=True, encoding='utf-8', errors='replace', timeout=timeout
    )


def create_worktree(item_id: str, base_branch: str | None = None, lock_timeout: float = 300.0) -> Path:
    """Create a git worktree for a work item. Returns existing path if already exists.

    Uses file-based locking to prevent race conditions when multiple agents
    attempt to create worktrees simultaneously.
    """
    # Sanitize the item_id for use in branch names
    sanitized_id = sanitize_branch_name(item_id)

    # Worktree path: ./worktrees/task-{sanitized_id}
    worktree_path = Path("worktrees") / f"task-{sanitized_id}"

    # Branch name for the worktree
    branch_name = f"task/{sanitized_id}"

    # Check if worktree already exists (outside lock - no git operation needed)
    existing_worktrees = list_worktrees()
    for wt in existing_worktrees:
        wt_path = Path(wt.get("path", ""))
        # Check if this is our worktree (by path or branch)
        if wt_path == worktree_path.resolve() or wt.get("branch", "").endswith(branch_name):
            logger.debug(f"Reusing existing worktree for {item_id} at {wt_path}")
            print(f"   ♻️  Reusing existing worktree at {wt_path}")
            return wt_path

    # Create worktrees directory if it doesn't exist
    Path("worktrees").mkdir(exist_ok=True)

    # Resolve default base branch if not provided
    if base_branch is None:
        base_branch = get_default_branch()

    # CRITICAL: Use lock to serialize worktree creation across parallel agents
    # This prevents race conditions when multiple git worktree operations
    # access .git/worktrees simultaneously
    lock_start = time.time()
    try:
        with with_worktree_lock(timeout=lock_timeout):
            lock_wait = time.time() - lock_start
            if lock_wait > 0.1:
                logger.info(f"Waited {lock_wait:.2f}s for worktree lock (item: {item_id})")

            # Double-check worktree doesn't exist (another agent may have created it while we waited)
            existing_worktrees = list_worktrees()
            for wt in existing_worktrees:
                wt_path = Path(wt.get("path", ""))
                if wt_path == worktree_path.resolve() or wt.get("branch", "").endswith(branch_name):
                    logger.debug(f"Worktree created by another agent while waiting for lock: {wt_path}")
                    print(f"   ♻️  Reusing worktree created by another agent at {wt_path}")
                    return wt_path

            # Check if the directory already exists but wasn't in list_worktrees
            if worktree_path.exists():
                logger.warning(f"Worktree directory {worktree_path} already exists but wasn't in list_worktrees")
                
                # Check if it's a valid git worktree
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
                else:
                    logger.warning(f"Directory {worktree_path} is not a valid worktree, removing it")
                    print(f"   🧹  Removing stale worktree directory at {worktree_path}")
                    if not force_remove_directory(worktree_path):
                        raise RuntimeError(f"Failed to remove stale directory {worktree_path}")
                    
                    # Also run git worktree prune just in case
                    try:
                        _run_git(["git", "worktree", "prune"])
                    except Exception:
                        pass

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

                # Log detailed error information
                logger.error(
                    f"Git worktree creation failed for {item_id} after {creation_time:.2f}s:\n"
                    f"  Command: git worktree add {worktree_path} -b {branch_name} {base_branch}\n"
                    f"  Exit code: {e.returncode}\n"
                    f"  Stderr: {stderr}"
                )
                print(f"   ⚠️  Git error (exit {e.returncode}): {stderr}")

                # Check if error is because branch already exists
                if "already exists" in stderr.lower() or "already checked out" in stderr.lower():
                    logger.warning(f"Branch {branch_name} already exists, attempting to find existing worktree")
                    # Try to find the existing worktree
                    existing_worktrees = list_worktrees()
                    for wt in existing_worktrees:
                        if wt.get("branch", "").endswith(branch_name):
                            logger.info(f"Found existing worktree for {branch_name} at {wt['path']}")
                            print(f"   ♻️  Reusing existing worktree at {wt['path']}")
                            return Path(wt["path"])

                # Check if the base branch doesn't exist
                if "invalid reference" in stderr.lower() or "not a valid" in stderr.lower():
                    logger.error(f"Base branch '{base_branch}' does not exist")
                    raise RuntimeError(
                        f"Base branch '{base_branch}' does not exist. "
                        "Please create it first or specify a different base branch."
                    ) from e

                # If we couldn't recover, re-raise the error with more context
                raise RuntimeError(f"Failed to create worktree: {stderr}") from e

            except subprocess.TimeoutExpired as e:
                creation_time = time.time() - creation_start
                logger.error(f"Git worktree creation timed out for {item_id} after {creation_time:.2f}s")
                raise RuntimeError(f"Timed out creating worktree after {e.timeout}s") from e

    except RuntimeError:
        # Lock timeout or git error - already logged above
        raise
    except Exception as e:
        logger.error(f"Unexpected error creating worktree for {item_id}: {e}", exc_info=True)
        raise RuntimeError(f"Unexpected error creating worktree: {e}") from e

    return worktree_path


def is_worktree_merged(item_id: str, target_branch: str | None = None) -> bool:
    """Check if a worktree's branch has been merged into the target branch."""
    sanitized_id = sanitize_branch_name(item_id)
    branch_name = f"task/{sanitized_id}"
    if target_branch is None:
        target_branch = get_default_branch()
    try:
        result = _run_git(["git", "branch", "--merged", target_branch])
        return any(branch_name in branch for branch in result.stdout.splitlines())
    except subprocess.CalledProcessError:
        return False


def merge_worktree(item_id: str, target_branch: str | None = None, cleanup: bool = True) -> tuple[bool, list[str]]:
    """Merge a worktree's branch into the target branch and optionally clean up.

    Returns (success, unmerged_files). On success: (True, []). On failure: (False, conflicted_files).
    """
    sanitized_id = sanitize_branch_name(item_id)
    branch_name = f"task/{sanitized_id}"
    worktree_path = Path("worktrees") / f"task-{sanitized_id}"

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

    if not validate_post_merge(target_branch):
        return False, []

    print(f"✅ Post-merge validation passed: {target_branch} is clean")

    try:
        _run_git(["git", "push"], timeout=120)
        print(f"✅ Pushed {target_branch} to remote")
    except subprocess.CalledProcessError as e:
        print(f"❌ Push failed: {e.stderr if e.stderr else str(e)}")
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
    branch_name = f"task/{sanitized_id}"
    expected_worktree_path = Path("worktrees") / f"task-{sanitized_id}"

    # Find the actual worktree for this item (might have unsanitized path if created before fix)
    actual_worktree_path = None
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
        unsanitized_path = Path("worktrees") / f"task-{item_id}"
        if unsanitized_path.exists():
            actual_worktree_path = unsanitized_path

    # Remove worktree if found
    if actual_worktree_path and actual_worktree_path.exists():
        try:
            cmd = ["git", "worktree", "remove", str(actual_worktree_path)]
            if force:
                cmd.append("--force")

            _run_git(cmd)
            remove_from_manifest(item_id)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            stderr = getattr(e, 'stderr', None) or str(e)
            stderr_lower = stderr.lower()

            # Check if error is because worktree doesn't exist
            if "not a working tree" in stderr_lower or "no such file" in stderr_lower:
                # Already gone, that's fine
                pass
            elif _is_windows_lock_error(stderr):
                print("⚠️  Worktree removal failed (likely locked). Retrying with enhanced force removal...")
                if force_remove_directory(actual_worktree_path):
                    remove_from_manifest(item_id)
                else:
                    print(f"⚠️  Could not remove worktree directory after retries: {actual_worktree_path}")
                    add_uncleaned_worktree(item_id, str(actual_worktree_path), f"Worktree removal failed: {stderr}")
            else:
                print(f"⚠️  Worktree removal warning: {stderr}")
                if actual_worktree_path.exists():
                    add_uncleaned_worktree(item_id, str(actual_worktree_path), f"Worktree removal warning: {stderr}")
                # Continue to try branch deletion

    # If the worktree directory still exists, do not delete the branch.
    # Deleting the branch while the worktree remains creates a dangling worktree.
    if actual_worktree_path is not None and actual_worktree_path.exists():
        print(f"⚠️  Skipping branch deletion because worktree directory still exists: {actual_worktree_path}")
        return False

    # Delete branch (try both sanitized and unsanitized branch names)
    delete_flag = "-D" if force else "-d"

    # Try sanitized branch name first
    try:
        _run_git(["git", "branch", delete_flag, branch_name])
    except subprocess.CalledProcessError:
        # Try unsanitized branch name as fallback
        try:
            unsanitized_branch = f"task/{item_id}"
            _run_git(["git", "branch", delete_flag, unsanitized_branch])
        except subprocess.CalledProcessError as e2:
            # Check if branch doesn't exist
            if e2.stderr and ("not found" in e2.stderr.lower() or "does not exist" in e2.stderr.lower()):
                # Already gone, that's fine
                pass
            else:
                print(f"⚠️  Branch deletion warning: {e2.stderr if e2.stderr else str(e2)}")
                # If both worktree and branch operations failed, return False
                if actual_worktree_path is not None:
                    return False

    return True


def _sync_and_ensure_clean_main_repo(branch_name: str) -> bool:
    """Sync beads and ensure main repo is clean before merge."""

    print("🔄 Syncing beads database before merge...")
    try:
        bd_sync_result = run_bd_sync_with_retry(timeout=30)
        if bd_sync_result.returncode != 0:
            print(f"⚠️  bd sync returned non-zero: {bd_sync_result.returncode}")
            print(f"   stdout: {bd_sync_result.stdout}")
            print(f"   stderr: {bd_sync_result.stderr}")
    except subprocess.TimeoutExpired:
        print("⚠️  bd sync timed out")
    try:
        main_status = _run_git(["git", "status", "--porcelain"]).stdout.strip()

        if main_status:
            lines = main_status.split('\n')
            changes = categorize_git_changes(lines)

            if changes['other']:
                for line in changes['other'][:10]:
                    print(f"   ⚠️  pending: {line}")
                if len(changes['other']) > 10:
                    print(f"   ... and {len(changes['other']) - 10} more")
                ok, err = commit_all_changes(f"chore: commit pending changes before merge of {branch_name}")
                if not ok:
                    print(f"❌ Cannot merge: failed to commit pending changes: {err}")
                    return False
                print("✅ Pending main-branch changes committed")

            if changes['beads']:
                print("🔧 Committing beads database changes...")
                _run_git(["git", "add", ".beads/"], capture_output=False)
                _run_git(["git", "commit", "-m", f"chore: sync beads before merge of {branch_name}"], timeout=60)
                print("✅ Beads changes committed")

            if changes['worktree']:
                print("🧹 Committing worktree cleanup changes...")
                _run_git(["git", "add", "worktrees/"], capture_output=False)
                _run_git(["git", "commit", "-m", "chore: cleanup deleted worktree directories"], timeout=60)
                print("✅ Worktree cleanup committed")

        return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        print(f"❌ Failed to check/clean main repo: {e}")
        return False

