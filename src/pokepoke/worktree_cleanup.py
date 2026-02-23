"""Windows-safe directory removal utilities for worktree cleanup."""

import json
import logging
import os
import shutil
import stat
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import cast

logger = logging.getLogger(__name__)

# Retry settings for worktree removal on Windows
_CLEANUP_MAX_RETRIES = 5  # Increased from 3
_CLEANUP_RETRY_DELAY_SECONDS = 3.0  # Increased from 2.0 seconds
_CLEANUP_MAX_DELAY_SECONDS = 30.0  # Cap on exponential backoff


def _handle_remove_readonly(func: object, path: str, exc_info: object) -> None:
    """Error handler for shutil.rmtree that clears read-only flags on Windows."""
    os.chmod(path, stat.S_IWRITE)
    func(path)  # type: ignore[operator]


def force_remove_directory(dir_path: Path) -> bool:
    """Force-remove a directory, handling Windows permission issues.

    Enhanced retry logic with better error detection and backoff for Windows file locking.
    Returns True if the directory was removed.
    """
    # Import here to avoid circular dependency
    from pokepoke.process_utils import wait_for_process_cleanup

    print(f"🔄 Attempting force removal of worktree: {dir_path}")

    for attempt in range(_CLEANUP_MAX_RETRIES):
        if attempt > 0:
            # Wait for processes to clean up before retry
            wait_for_process_cleanup(max_wait=3.0)

            # Calculate delay with capped exponential backoff
            delay = min(_CLEANUP_RETRY_DELAY_SECONDS * (2 ** (attempt - 1)), _CLEANUP_MAX_DELAY_SECONDS)
            print(f"   ⏳ Retry {attempt + 1}/{_CLEANUP_MAX_RETRIES} after {delay:.1f}s...")
            time.sleep(delay)

        # First try git worktree remove --force
        try:
            subprocess.run(
                ["git", "worktree", "remove", "--force", str(dir_path)],
                check=True, capture_output=True, text=True, encoding='utf-8',
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
                timeout=30
            )
            print("   ✅ Direct removal and git prune successful")
            return True
        except (OSError, PermissionError) as e:
            if _is_windows_lock_error(str(e)):
                print(f"   🔒 Windows lock on direct removal (attempt {attempt + 1}): {e}")
            else:
                print(f"   ❌ Direct removal failed (attempt {attempt + 1}): {e}")

    print(f"   ❌ All {_CLEANUP_MAX_RETRIES} removal attempts failed")
    return False


def _is_windows_lock_error(error_text: str) -> bool:
    """Detect Windows file locking related errors."""
    if not error_text:
        return False

    error_lower = error_text.lower()
    windows_lock_indicators = [
        "permission denied",
        "being used by another process",
        "cannot access the file",
        "sharing violation",
        "access is denied",
        "device or resource busy",
        "directory not empty",
        "invalid argument"  # Sometimes seen with locked files on Windows
    ]

    return any(indicator in error_lower for indicator in windows_lock_indicators)


def get_worktree_manifest_path() -> Path:
    """Get the path to the uncleaned worktrees manifest file."""
    pokepoke_dir = Path(".pokepoke")
    return pokepoke_dir / "uncleaned_worktrees.json"


def load_worktree_manifest() -> dict[str, dict[str, str]]:
    """Load the uncleaned worktrees manifest."""
    manifest_path = get_worktree_manifest_path()
    if not manifest_path.exists():
        return {}

    try:
        with open(manifest_path, encoding='utf-8') as f:
            raw = json.load(f)
            if isinstance(raw, dict):
                return cast(dict[str, dict[str, str]], raw)
            return {}
    except (json.JSONDecodeError, OSError):
        return {}


def save_worktree_manifest(manifest: dict[str, dict[str, str]]) -> None:
    """Save the uncleaned worktrees manifest."""
    manifest_path = get_worktree_manifest_path()
    try:
        manifest_path.parent.mkdir(exist_ok=True)
        with open(manifest_path, 'w', encoding='utf-8') as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)
    except OSError as e:
        logger.warning('Failed to save worktree manifest to %s: %s', manifest_path, e)
        # Extract worktree paths from manifest for diagnostic context
        worktree_paths = [entry.get('path', 'unknown') for entry in manifest.values()]
        if worktree_paths:
            logger.warning(
                'Worktrees at the following paths may become orphaned (not tracked for cleanup): %s',
                ', '.join(worktree_paths)
            )


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


def cleanup_after_merge(worktree_path: Path, branch_name: str) -> None:
    """Cleanup worktree and branch after successful merge."""
    if worktree_path.exists():
        try:
            subprocess.run(
                ["git", "worktree", "remove", str(worktree_path)],
                check=True, capture_output=True, text=True, encoding='utf-8',
                timeout=30
            )
            print(f"✅ Removed worktree at {worktree_path}")
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            stderr = getattr(e, 'stderr', None) or str(e)

            if _is_windows_lock_error(stderr):
                print("⚠️ Worktree removal failed (likely locked). Retrying with enhanced force removal...")
                if force_remove_directory(worktree_path):
                    print(f"✅ Force-removed worktree at {worktree_path}")
                    if branch_name.startswith("task/"):
                        remove_from_manifest(branch_name.split("/", 1)[1])
                else:
                    print(f"⚠️ Could not remove worktree after retries: {worktree_path}")
                    print("   Merge successful - worktree cleanup can be done later")
                    worktree_id = branch_name.split("/", 1)[1] if branch_name.startswith("task/") else worktree_path.name
                    add_uncleaned_worktree(worktree_id, str(worktree_path), f"Post-merge cleanup failed: {stderr}")
            else:
                print(f"⚠️ Could not remove worktree: {stderr}")
                print("   Merge successful - worktree cleanup can be done later")
                worktree_id = branch_name.split("/", 1)[1] if branch_name.startswith("task/") else worktree_path.name
                add_uncleaned_worktree(worktree_id, str(worktree_path), f"Post-merge cleanup warning: {stderr}")

    try:
        subprocess.run(
            ["git", "branch", "-d", branch_name],
            check=True, capture_output=True, text=True, encoding='utf-8',
            timeout=30
        )
        print(f"✅ Deleted branch {branch_name}")
    except subprocess.CalledProcessError as e:
        print(f"⚠️ Could not delete branch: {e.stderr or e}")


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
    from pokepoke.worktrees import list_worktrees
    worktrees = list_worktrees()
    task_worktrees = [
        wt for wt in worktrees
        if "worktrees" in wt.get("path", "") and "task-" in wt.get("path", "")
    ]
    if task_worktrees:
        return True
    manifest = load_worktree_manifest()
    return len(manifest) > 0
