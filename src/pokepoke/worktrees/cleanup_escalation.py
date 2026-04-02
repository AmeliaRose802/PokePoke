"""Escalation strategies for worktree cleanup failures.

Provides nuclear removal, quarantine, and retry-with-escalation for
worktree directories that fail normal cleanup.
"""

import contextlib
import logging
import os
import stat
import subprocess
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

_NUCLEAR_FAILURE_THRESHOLD = 3
_QUARANTINE_DIR_NAME = ".quarantine"


def _get_quarantine_dir() -> Path:
    """Return the quarantine directory path, creating it if needed."""
    from pokepoke.utils.constants import POKEPOKE_DIR
    qdir = POKEPOKE_DIR / _QUARANTINE_DIR_NAME
    qdir.mkdir(parents=True, exist_ok=True)
    return qdir


def _nuclear_remove(dir_path: Path) -> bool:
    """Last-resort removal using OS-level commands.

    On Windows, uses ``cmd /c rd /s /q``.  On POSIX, uses ``rm -rf``.
    Returns True if the directory no longer exists afterwards.
    """
    import shutil
    import sys

    logger.warning(f"   💣 Nuclear removal for {dir_path}")

    # Attempt 1: shutil.rmtree with aggressive onerror
    def _on_error(_func: object, path: str, _exc_info: object) -> None:
        with contextlib.suppress(OSError):
            os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
        with contextlib.suppress(OSError):
            os.remove(path)

    try:
        shutil.rmtree(str(dir_path), onerror=_on_error)
        if not dir_path.exists():
            return True
    except OSError:
        pass

    # Attempt 2: OS-level force removal
    try:
        if sys.platform == "win32":
            subprocess.run(
                ["cmd", "/c", "rd", "/s", "/q", str(dir_path)],
                timeout=30, check=False, capture_output=True,
            )
        else:
            subprocess.run(
                ["rm", "-rf", str(dir_path)],
                timeout=30, check=False, capture_output=True,
            )
    except (subprocess.TimeoutExpired, OSError) as e:
        logger.warning(f"   💣 OS-level removal failed: {e}")

    return not dir_path.exists()


def _quarantine_directory(dir_path: Path, worktree_id: str) -> bool:
    """Move a half-deleted directory to quarantine instead of leaving it in-place.

    Returns True if the directory was moved (or no longer exists).
    """
    if not dir_path.exists():
        return True

    qdir = _get_quarantine_dir()
    dest = qdir / f"{worktree_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    try:
        dir_path.rename(dest)
        logger.info(f"   📦 Quarantined {dir_path} → {dest}")
        return True
    except OSError as e:
        logger.warning(f"   ⚠️ Quarantine failed for {dir_path}: {e}")
        return False


def retry_failed_cleanups() -> int:
    """Retry cleanup of worktrees that previously failed to be removed.

    Escalation strategy based on failure count:
    - 1-2 failures: normal ``force_remove_directory()``
    - 3+ failures: nuclear removal (shutil.rmtree + OS-level commands)
    - If nuclear fails: quarantine (move to .pokepoke/.quarantine/)

    Returns the number of worktrees successfully cleaned up.
    """
    # Import module (not names) to allow test patching on the source module
    import pokepoke.worktrees.worktree_cleanup as _wc

    manifest = _wc.load_worktree_manifest()
    if not manifest:
        return 0

    cleaned_count = 0
    logger.error(f"🔄 Found {len(manifest)} worktrees in failed cleanup manifest")

    for worktree_id, entry in list(manifest.items()):
        worktree_path = Path(entry["path"])
        reason = entry.get("reason", "Unknown reason")
        timestamp = entry.get("timestamp", "Unknown time")
        try:
            failure_count = int(entry.get("failure_count", "1"))
        except (ValueError, TypeError):
            failure_count = 1

        logger.info(f"\n🧹 Retrying cleanup for {worktree_id} (attempt #{failure_count + 1}):")
        logger.info(f"   Path: {worktree_path}")
        logger.error(f"   Failed at: {timestamp}")
        logger.info(f"   Reason: {reason}")

        # Check if worktree still exists
        if not worktree_path.exists():
            logger.info("   ✅ Directory no longer exists - removing from manifest")
            _wc.remove_from_manifest(worktree_id)
            cleaned_count += 1
            continue

        removed = False

        if failure_count >= _NUCLEAR_FAILURE_THRESHOLD:
            # Escalate: nuclear removal
            removed = _nuclear_remove(worktree_path)
            if not removed:
                # Last resort: quarantine
                if _quarantine_directory(worktree_path, worktree_id):
                    logger.info(f"   📦 Quarantined worktree {worktree_id}")
                    _wc.remove_from_manifest(worktree_id)
                    cleaned_count += 1
                    continue
        else:
            # Normal retry with force removal
            removed = _wc.force_remove_directory(worktree_path)

        if removed:
            logger.info(f"   ✅ Successfully removed worktree {worktree_id}")
            _wc.remove_from_manifest(worktree_id)
            cleaned_count += 1
        else:
            # Bump failure count in the manifest
            _wc.add_uncleaned_worktree(worktree_id, str(worktree_path), reason)
            logger.error(
                f"   ❌ Still failed to remove {worktree_id} "
                f"(failure #{failure_count + 1}) - will retry later"
            )

    if cleaned_count > 0:
        logger.error(f"\n✅ Successfully cleaned up {cleaned_count} previously failed worktrees")
    else:
        logger.warning("\n⚠️  No additional worktrees could be cleaned up this time")

    return cleaned_count
