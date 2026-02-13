"""Windows-safe directory removal utilities for worktree cleanup."""

import os
import shutil
import stat
import subprocess
import time
from pathlib import Path

# Retry settings for worktree removal on Windows
_CLEANUP_MAX_RETRIES = 3
_CLEANUP_RETRY_DELAY_SECONDS = 2.0


def _handle_remove_readonly(func: object, path: str, exc_info: object) -> None:
    """Error handler for shutil.rmtree that clears read-only flags on Windows."""
    os.chmod(path, stat.S_IWRITE)
    func(path)  # type: ignore[operator]


def force_remove_directory(dir_path: Path) -> bool:
    """Force-remove a directory, handling Windows permission issues.

    Retries with delays to allow file handles to be released,
    then falls back to shutil.rmtree with read-only flag clearing.
    Returns True if the directory was removed.
    """
    for attempt in range(_CLEANUP_MAX_RETRIES):
        try:
            subprocess.run(
                ["git", "worktree", "remove", "--force", str(dir_path)],
                check=True, capture_output=True, text=True, encoding='utf-8'
            )
            return True
        except subprocess.CalledProcessError:
            pass

        # Fallback: direct directory removal
        try:
            shutil.rmtree(str(dir_path), onerror=_handle_remove_readonly)
            # Clean up git worktree bookkeeping after manual removal
            subprocess.run(
                ["git", "worktree", "prune"],
                check=False, capture_output=True, text=True, encoding='utf-8'
            )
            return True
        except (OSError, PermissionError):
            if attempt < _CLEANUP_MAX_RETRIES - 1:
                time.sleep(_CLEANUP_RETRY_DELAY_SECONDS)

    return False
