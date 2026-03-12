"""Windows-safe directory removal utilities for worktree cleanup."""

import logging
import os
import shutil
import stat
import subprocess
import time
from datetime import datetime
from pathlib import Path

from pokepoke.constants import BRANCH_PREFIX, WORKTREE_DIR, WORKTREE_TASK_PREFIX

logger = logging.getLogger(__name__)

# Retry settings for worktree removal on Windows
_CLEANUP_MAX_RETRIES = 5  # Increased from 3
_CLEANUP_RETRY_DELAY_SECONDS = 3.0  # Increased from 2.0 seconds
_CLEANUP_MAX_DELAY_SECONDS = 30.0  # Cap on exponential backoff


def _handle_remove_readonly(func: object, path: str, exc_info: object) -> None:
    """Error handler for shutil.rmtree that clears read-only flags on Windows."""
    os.chmod(path, stat.S_IWRITE)
    func(path)  # type: ignore[operator]


def force_remove_directory(dir_path: Path, *, max_attempts: int | None = None) -> bool:
    """Force-remove a directory, handling Windows permission issues.

    Enhanced retry logic with better error detection and backoff for Windows file locking.
    Returns True if the directory was removed.

    Args:
        dir_path: Directory to remove.
        max_attempts: Maximum removal attempts. Defaults to ``_CLEANUP_MAX_RETRIES``.
            Pass ``1`` for a single non-blocking attempt (fire-and-forget cleanup).
    """
    # Import here to avoid circular dependency
    from pokepoke.process_utils import wait_for_process_cleanup

    if max_attempts is None:
        max_attempts = _CLEANUP_MAX_RETRIES

    print(f"🔄 Attempting force removal of worktree: {dir_path}")

    for attempt in range(max_attempts):
        if attempt > 0:
            # Wait for processes to clean up before retry
            wait_for_process_cleanup(max_wait=3.0)

            # Calculate delay with capped exponential backoff
            delay = min(_CLEANUP_RETRY_DELAY_SECONDS * (2 ** (attempt - 1)), _CLEANUP_MAX_DELAY_SECONDS)
            print(f"   ⏳ Retry {attempt + 1}/{max_attempts} after {delay:.1f}s...")
            time.sleep(delay)

        # First try git worktree remove --force
        try:
            subprocess.run(
                ["git", "worktree", "remove", "--force", str(dir_path)],
                check=True, capture_output=True, text=True, encoding='utf-8',
                errors='replace',
                timeout=30
            )
            print("   ✅ Git worktree remove successful")
            return True
        except subprocess.CalledProcessError as e:
            stderr = e.stderr or ""
            if _is_windows_lock_error(stderr):
                print(f"   🔒 Windows lock detected on attempt {attempt + 1}: {stderr.strip()}")
            elif attempt == 0:  # Only log git errors on first attempt
                print(f"   ⚠️ Git worktree remove failed: {stderr.strip()}")
        except subprocess.TimeoutExpired:
            print(f"   ⏱️ Git worktree remove timed out on attempt {attempt + 1}")

        # Fallback: direct directory removal with enhanced error handling
        try:
            print("   🔨 Attempting direct directory removal...")
            shutil.rmtree(str(dir_path), onerror=_handle_remove_readonly)

            # Clean up git worktree bookkeeping after manual removal
            subprocess.run(
                ["git", "worktree", "prune"],
                check=False, capture_output=True, text=True, encoding='utf-8',
                errors='replace',
                timeout=30
            )
            print("   ✅ Direct removal and git prune successful")
            return True
        except (OSError, PermissionError) as e:
            if _is_windows_lock_error(str(e)):
                print(f"   🔒 Windows lock on direct removal (attempt {attempt + 1}): {e}")
            else:
                print(f"   ❌ Direct removal failed (attempt {attempt + 1}): {e}")

    print(f"   ❌ All {max_attempts} removal attempts failed")
    return False


def _is_windows_lock_error(error_text: str) -> bool:
    """Detect Windows file locking related errors.

    Only matches errors that are strong indicators of Windows file locking,
    not generic filesystem errors that could have other causes.  Patterns
    like 'directory not empty' and 'device or resource busy' are intentionally
    excluded because they can originate from non-locking scenarios.
    """
    if not error_text:
        return False

    error_lower = error_text.lower()
    windows_lock_indicators = [
        # WinError 32 – ERROR_SHARING_VIOLATION
        "being used by another process",
        # WinError 33 – ERROR_LOCK_VIOLATION
        "locked a portion of the file",
        # Windows sharing-violation phrasing
        "sharing violation",
        # Explicit Windows error codes in Python exception strings
        "[winerror 32]",
        "[winerror 33]",
    ]

    return any(indicator in error_lower for indicator in windows_lock_indicators)


_WORKTREE_MANIFEST = "uncleaned_worktrees.json"


def get_worktree_manifest_path() -> Path:
    """Get the path to the uncleaned worktrees manifest file."""
    from pokepoke.manifest_utils import get_manifest_path
    return get_manifest_path(_WORKTREE_MANIFEST)


def load_worktree_manifest() -> dict[str, dict[str, str]]:
    """Load the uncleaned worktrees manifest."""
    from pokepoke.manifest_utils import load_manifest_from_path
    return load_manifest_from_path(get_worktree_manifest_path())


def save_worktree_manifest(manifest: dict[str, dict[str, str]]) -> None:
    """Save the uncleaned worktrees manifest."""
    from pokepoke.manifest_utils import save_manifest_to_path
    worktree_paths = [entry.get('path', 'unknown') for entry in manifest.values()]
    warn_context = ""
    if worktree_paths:
        warn_context = (
            "Worktrees at the following paths may become orphaned "
            f"(not tracked for cleanup): {', '.join(worktree_paths)}"
        )
    save_manifest_to_path(get_worktree_manifest_path(), manifest, warn_context=warn_context)


def add_uncleaned_worktree(worktree_id: str, worktree_path: str, reason: str) -> None:
    """Add a worktree to the uncleaned manifest.

    Uses file locking to prevent race conditions when multiple agents
    concurrently update the manifest.
    """
    from pokepoke.coordination import manifest_lock

    with manifest_lock():
        manifest = load_worktree_manifest()
        manifest[worktree_id] = {
            "path": worktree_path,
            "reason": reason,
            "timestamp": datetime.now().isoformat()
        }
        save_worktree_manifest(manifest)


def remove_from_manifest(worktree_id: str) -> None:
    """Remove a worktree from the uncleaned manifest.

    Uses file locking to prevent race conditions when multiple agents
    concurrently update the manifest.
    """
    from pokepoke.coordination import manifest_lock

    with manifest_lock():
        manifest = load_worktree_manifest()
        if worktree_id in manifest:
            del manifest[worktree_id]
            save_worktree_manifest(manifest)


def _handle_worktree_removal_error(
    e: subprocess.CalledProcessError | subprocess.TimeoutExpired,
    worktree_path: Path,
    worktree_id: str | None,
    post_merge: bool,
    print_success: bool,
) -> None:
    """Handle errors during git worktree remove."""
    stderr = getattr(e, "stderr", None) or str(e)
    stderr_lower = stderr.lower()

    if "not a working tree" in stderr_lower or "no such file" in stderr_lower:
        return

    # Always attempt force removal regardless of error type.  Use lock
    # detection only for log differentiation so that transient failures
    # (e.g. "directory not empty" caused by a locked file inside) still
    # get a retry without being misclassified as a lock error.
    if _is_windows_lock_error(stderr):
        print("⚠️  Worktree removal failed (likely locked). Retrying with enhanced force removal...")
    else:
        print(f"⚠️  Worktree removal failed: {stderr.strip()}. Attempting force removal...")

    # Use a single attempt (fire-and-forget) to avoid blocking the worker
    # thread for up to 78s.  If this quick attempt fails the worktree is
    # added to the uncleaned manifest and the maintenance cleanup agent
    # will retry asynchronously.
    if force_remove_directory(worktree_path, max_attempts=1):
        if worktree_id is not None:
            remove_from_manifest(worktree_id)
        if print_success:
            print(f"✅ Force-removed worktree at {worktree_path}")
        return

    if post_merge:
        print(f"⚠️ Could not remove worktree after retries: {worktree_path}")
        print("✅ Merge successful, but cleanup had issues. You may need to manually remove this worktree later.")
    else:
        print(f"⚠️  Could not remove worktree directory after retries: {worktree_path}")

    if worktree_id is not None and worktree_path.exists():
        reason_prefix = "Post-merge cleanup" if post_merge else "Worktree removal"
        add_uncleaned_worktree(worktree_id, str(worktree_path), f"{reason_prefix} failed: {stderr}")


def cleanup_worktree_and_branch(
    worktree_path: Path | None,
    branch_name: str,
    *,
    worktree_id: str | None = None,
    force: bool = False,
    fallback_branch_name: str | None = None,
    skip_branch_delete_if_dir_exists: bool = True,
    post_merge: bool = False,
    print_success: bool = False,
    cwd: str | None = None,
) -> bool:
    """Remove a worktree directory and delete its branch.

    This is the shared implementation used by both interactive cleanup and
    post-merge cleanup.

    Returns True when cleanup succeeds (or the worktree/branch are already gone).
    Returns False when the worktree directory still exists or branch deletion
    fails with a non-ignorable error.
    """
    if worktree_id is None:
        if branch_name.startswith(BRANCH_PREFIX):
            worktree_id = branch_name.split("/", 1)[1]
        elif worktree_path is not None:
            worktree_id = worktree_path.name

    # Remove worktree if found
    if worktree_path is not None and worktree_path.exists():
        try:
            cmd = ["git", "worktree", "remove", str(worktree_path)]
            if force:
                cmd.append("--force")

            _run_git(cmd, cwd=cwd)
            if worktree_id is not None:
                remove_from_manifest(worktree_id)
            if print_success:
                print(f"✅ Removed worktree at {worktree_path}")

        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            _handle_worktree_removal_error(e, worktree_path, worktree_id, post_merge, print_success)

    # If the worktree directory still exists, do not delete the branch.
    if skip_branch_delete_if_dir_exists and worktree_path is not None and worktree_path.exists():
        print(f"⚠️  Skipping branch deletion because worktree directory still exists: {worktree_path}")
        return False

    return _delete_branch(branch_name, fallback_branch_name, force, print_success, post_merge, cwd=cwd)


def _run_git(cmd: list[str], cwd: str | None = None) -> subprocess.CompletedProcess[str]:
    """Run a git command with standard options — delegates to git_helpers.run_git."""
    from pokepoke.git_helpers import run_git
    return run_git(cmd, cwd=cwd)


def _delete_branch(
    branch_name: str,
    fallback_branch_name: str | None,
    force: bool,
    print_success: bool,
    post_merge: bool,
    cwd: str | None = None,
) -> bool:
    """Delete a git branch, optionally trying a fallback name."""
    delete_flag = "-D" if force else "-d"

    try:
        _run_git(["git", "branch", delete_flag, branch_name], cwd=cwd)
        if print_success:
            print(f"✅ Deleted branch {branch_name}")
        return True
    except subprocess.CalledProcessError as exc:
        if not fallback_branch_name:
            print(f"⚠️ Could not delete branch: {exc.stderr or exc}")
            return True

    # Try fallback branch name
    try:
        _run_git(["git", "branch", delete_flag, fallback_branch_name], cwd=cwd)
        if print_success:
            print(f"✅ Deleted branch {fallback_branch_name}")
        return True
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr or ""
        if "not found" in stderr.lower() or "does not exist" in stderr.lower():
            return True
        print(f"⚠️  Branch deletion warning: {stderr if stderr else str(exc)}")
        return False


def cleanup_after_merge(worktree_path: Path, branch_name: str, cwd: str | None = None) -> None:
    """Cleanup worktree and branch after successful merge."""
    cleanup_worktree_and_branch(
        worktree_path,
        branch_name,
        skip_branch_delete_if_dir_exists=True,
        post_merge=True,
        print_success=True,
        cwd=cwd,
    )


def retry_failed_cleanups() -> int:
    """Retry cleanup of worktrees that previously failed to be removed.

    Returns the number of worktrees successfully cleaned up.
    """
    manifest = load_worktree_manifest()
    if not manifest:
        return 0

    cleaned_count = 0
    print(f"🔄 Found {len(manifest)} worktrees in failed cleanup manifest")

    for worktree_id, entry in list(manifest.items()):
        worktree_path = Path(entry["path"])
        reason = entry.get("reason", "Unknown reason")
        timestamp = entry.get("timestamp", "Unknown time")

        print(f"\n🧹 Retrying cleanup for {worktree_id}:")
        print(f"   Path: {worktree_path}")
        print(f"   Failed at: {timestamp}")
        print(f"   Reason: {reason}")

        # Check if worktree still exists
        if not worktree_path.exists():
            print("   ✅ Directory no longer exists - removing from manifest")
            remove_from_manifest(worktree_id)
            cleaned_count += 1
            continue

        # Try enhanced force removal
        if force_remove_directory(worktree_path):
            print(f"   ✅ Successfully removed worktree {worktree_id}")
            remove_from_manifest(worktree_id)
            cleaned_count += 1
        else:
            print(f"   ❌ Still failed to remove {worktree_id} - will retry later")

    if cleaned_count > 0:
        print(f"\n✅ Successfully cleaned up {cleaned_count} previously failed worktrees")
    else:
        print("\n⚠️  No additional worktrees could be cleaned up this time")

    return cleaned_count


def get_uncleaned_worktree_count() -> int:
    """Get the count of worktrees that failed to be cleaned up."""
    manifest = load_worktree_manifest()
    return len(manifest)


def has_unmerged_worktrees() -> bool:
    """Check if there are any task worktrees or uncleaned manifest entries."""
    from pokepoke.git_operations import list_worktrees
    worktrees = list_worktrees()
    task_worktrees = [
        wt for wt in worktrees
        if WORKTREE_DIR in wt.get("path", "") and WORKTREE_TASK_PREFIX in wt.get("path", "")
    ]
    if task_worktrees:
        return True
    manifest = load_worktree_manifest()
    return len(manifest) > 0
