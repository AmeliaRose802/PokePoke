"""Worktree cleanup orchestration for PokePoke.

High-level cleanup operations: manifest management, branch deletion,
worktree-and-branch cleanup, and error handling.

Low-level directory removal lives in :mod:`worktree_removal`.
Escalation strategies (nuclear, quarantine) live in :mod:`cleanup_escalation`.
"""

import logging
import subprocess
from datetime import datetime
from pathlib import Path

from pokepoke.git.git_helpers import run_git
from pokepoke.types import RetryConfig
from pokepoke.utils.constants import BRANCH_PREFIX, WORKTREE_DIR, WORKTREE_TASK_PREFIX
from pokepoke.utils.retry_utils import sleep_with_backoff

# Re-export removal utilities so existing imports keep working
from pokepoke.worktrees.worktree_removal import (
    _CLEANUP_MAX_DELAY_SECONDS,
    _CLEANUP_MAX_RETRIES,
    _CLEANUP_RETRY_DELAY_SECONDS,
    PathBoundaryError,
    SymlinkFoundError,
    _is_junction,
    _is_windows_lock_error,
    _release_known_lock_files,
    _safe_rmtree,
    _validate_within_worktrees_dir,
)

logger = logging.getLogger(__name__)

# Explicit exports for mypy (re-exported names from sub-modules)
__all__ = [
    "PathBoundaryError",
    "SymlinkFoundError",
    "_is_junction",
    "_is_windows_lock_error",
    "_release_known_lock_files",
    "_safe_rmtree",
    "_validate_within_worktrees_dir",
    "force_remove_directory",
    "retry_failed_cleanups",
    "_nuclear_remove",
    "_quarantine_directory",
    "_get_quarantine_dir",
    "cleanup_worktree_and_branch",
    "cleanup_after_merge",
    "add_uncleaned_worktree",
    "remove_from_manifest",
    "load_worktree_manifest",
    "save_worktree_manifest",
    "get_worktree_manifest_path",
    "get_uncleaned_worktree_count",
    "has_unmerged_worktrees",
]


def force_remove_directory(dir_path: Path, *, max_attempts: int | None = None, repo_root: Path | None = None) -> bool:
    """Force-remove a directory, handling Windows permission issues.

    Returns True if the directory was removed.

    Raises:
        PathBoundaryError: If *dir_path* is not inside a ``worktrees/`` directory.
        SymlinkFoundError: If *dir_path* itself is a symlink or junction.
    """
    from pokepoke.utils.process_utils import wait_for_process_cleanup

    if max_attempts is None:
        max_attempts = _CLEANUP_MAX_RETRIES

    _validate_within_worktrees_dir(dir_path, repo_root=repo_root)

    if dir_path.is_symlink() or _is_junction(dir_path):
        raise SymlinkFoundError(
            f"Refusing to remove {dir_path}: the worktree path itself "
            "is a symlink or junction"
        )

    logger.info(f"🔄 Attempting force removal of worktree: {dir_path}")

    retry_config = RetryConfig(
        max_retries=max_attempts,
        initial_delay=_CLEANUP_RETRY_DELAY_SECONDS,
        max_delay=_CLEANUP_MAX_DELAY_SECONDS,
        backoff_factor=2.0,
        jitter=True,
    )

    for attempt in range(max_attempts):
        if attempt > 0:
            wait_for_process_cleanup(max_wait=3.0)
            delay = sleep_with_backoff(attempt - 1, retry_config, f'worktree cleanup {dir_path.name}')
            logger.info(f"   ⏳ Retry {attempt + 1}/{max_attempts} after {delay:.1f}s...")

        try:
            run_git(["git", "worktree", "remove", "--force", str(dir_path)])
            logger.info("   ✅ Git worktree remove successful")
            return True
        except subprocess.CalledProcessError as e:
            stderr = e.stderr or ""
            if _is_windows_lock_error(stderr):
                logger.info(f"   🔒 Windows lock detected on attempt {attempt + 1}: {stderr.strip()}")
            elif attempt == 0:
                logger.error(f"   ⚠️ Git worktree remove failed: {stderr.strip()}")
        except subprocess.TimeoutExpired:
            logger.info(f"   ⏱️ Git worktree remove timed out on attempt {attempt + 1}")

        try:
            logger.info("   🔨 Attempting direct directory removal...")
            _safe_rmtree(dir_path)
            run_git(["git", "worktree", "prune"], check=False)
            logger.info("   ✅ Direct removal and git prune successful")
            return True
        except (OSError, PermissionError) as e:
            if _is_windows_lock_error(str(e)):
                logger.info(f"   🔒 Windows lock on direct removal (attempt {attempt + 1}): {e}")
            else:
                logger.error(f"   ❌ Direct removal failed (attempt {attempt + 1}): {e}")

    logger.error(f"   ❌ All {max_attempts} removal attempts failed")
    return False


_WORKTREE_MANIFEST = "uncleaned_worktrees.json"


def get_worktree_manifest_path() -> Path:
    """Get the path to the uncleaned worktrees manifest file."""
    from pokepoke.utils.manifest_utils import get_manifest_path
    return get_manifest_path(_WORKTREE_MANIFEST)


def load_worktree_manifest() -> dict[str, dict[str, str]]:
    """Load the uncleaned worktrees manifest."""
    from pokepoke.utils.manifest_utils import load_manifest_from_path
    return load_manifest_from_path(get_worktree_manifest_path())


def save_worktree_manifest(manifest: dict[str, dict[str, str]]) -> None:
    """Save the uncleaned worktrees manifest."""
    from pokepoke.utils.manifest_utils import save_manifest_to_path
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
    concurrently update the manifest.  Tracks ``failure_count`` so that
    :func:`retry_failed_cleanups` can escalate its removal strategy.
    """
    from pokepoke.worktrees.coordination import manifest_lock

    with manifest_lock():
        manifest = load_worktree_manifest()
        existing = manifest.get(worktree_id)
        failure_count = 1
        if existing:
            try:
                failure_count = int(existing.get("failure_count", "0")) + 1
            except (ValueError, TypeError):
                failure_count = 1
        manifest[worktree_id] = {
            "path": worktree_path,
            "reason": reason,
            "timestamp": datetime.now().isoformat(),
            "failure_count": str(failure_count),
        }
        save_worktree_manifest(manifest)


def remove_from_manifest(worktree_id: str) -> None:
    """Remove a worktree from the uncleaned manifest.

    Uses file locking to prevent race conditions when multiple agents
    concurrently update the manifest.
    """
    from pokepoke.worktrees.coordination import manifest_lock

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
        logger.error("⚠️  Worktree removal failed (likely locked). Retrying with enhanced force removal...")
    else:
        logger.error(f"⚠️  Worktree removal failed: {stderr.strip()}. Attempting force removal...")

    # Use a single attempt (fire-and-forget) to avoid blocking the worker
    # thread for up to 78s.  If this quick attempt fails the worktree is
    # added to the uncleaned manifest and the maintenance cleanup agent
    # will retry asynchronously.
    if force_remove_directory(worktree_path, max_attempts=1):
        if worktree_id is not None:
            remove_from_manifest(worktree_id)
        if print_success:
            logger.info(f"✅ Force-removed worktree at {worktree_path}")
        return

    if post_merge:
        logger.warning(f"⚠️ Could not remove worktree after retries: {worktree_path}")
        logger.info("✅ Merge successful, but cleanup had issues. You may need to manually remove this worktree later.")
    else:
        logger.warning(f"⚠️  Could not remove worktree directory after retries: {worktree_path}")

    if worktree_id is not None and worktree_path.exists():
        reason_prefix = "Post-merge cleanup" if post_merge else "Worktree removal"
        add_uncleaned_worktree(worktree_id, str(worktree_path), f"{reason_prefix} failed: {stderr}")


def cleanup_worktree_and_branch(  # noqa: PLR0913
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
                logger.info(f"✅ Removed worktree at {worktree_path}")

        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            _handle_worktree_removal_error(e, worktree_path, worktree_id, post_merge, print_success)

    # If the worktree directory still exists, do not delete the branch.
    if skip_branch_delete_if_dir_exists and worktree_path is not None and worktree_path.exists():
        logger.warning(f"⚠️  Skipping branch deletion because worktree directory still exists: {worktree_path}")
        return False

    return _delete_branch(branch_name, fallback_branch_name, force, print_success, post_merge, cwd=cwd)


def _run_git(cmd: list[str], cwd: str | None = None) -> subprocess.CompletedProcess[str]:
    """Run a git command with standard options — delegates to git_helpers.run_git."""
    from pokepoke.git.git_helpers import run_git
    return run_git(cmd, cwd=cwd)


def _delete_branch(  # noqa: PLR0913
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
            logger.info(f"✅ Deleted branch {branch_name}")
        return True
    except subprocess.CalledProcessError as exc:
        if not fallback_branch_name:
            logger.warning(f"⚠️ Could not delete branch: {exc.stderr or exc}")
            return True

    # Try fallback branch name
    try:
        _run_git(["git", "branch", delete_flag, fallback_branch_name], cwd=cwd)
        if print_success:
            logger.info(f"✅ Deleted branch {fallback_branch_name}")
        return True
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr or ""
        if "not found" in stderr.lower() or "does not exist" in stderr.lower():
            return True
        logger.warning(f"⚠️  Branch deletion warning: {stderr if stderr else str(exc)}")
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


_NUCLEAR_FAILURE_THRESHOLD = 3  # Re-exported from cleanup_escalation

# Re-export escalation functions for backward compatibility
from pokepoke.worktrees.cleanup_escalation import (
    _get_quarantine_dir,
    _nuclear_remove,
    _quarantine_directory,
    retry_failed_cleanups,
)


def get_uncleaned_worktree_count() -> int:
    """Get the count of worktrees that failed to be cleaned up."""
    manifest = load_worktree_manifest()
    return len(manifest)


def has_unmerged_worktrees() -> bool:
    """Check if there are any task worktrees or uncleaned manifest entries."""
    from pokepoke.git.git_operations import list_worktrees
    worktrees = list_worktrees()
    task_worktrees = [
        wt for wt in worktrees
        if WORKTREE_DIR in wt.get("path", "") and WORKTREE_TASK_PREFIX in wt.get("path", "")
    ]
    if task_worktrees:
        return True
    manifest = load_worktree_manifest()
    return len(manifest) > 0
