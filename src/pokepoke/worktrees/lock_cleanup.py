"""Helpers to remove stale or owned lock files from .pokepoke/locks/."""

import json
import logging
import os
from pathlib import Path

from pokepoke.worktrees.coordination import (
    _get_related_files,
    get_owned_lock_paths,
)

logger = logging.getLogger(__name__)


def cleanup_owned_lock_files() -> int:
    """Remove all lock artefacts currently tracked by this process.

    Returns the number of files actually deleted.
    """
    removed = 0
    for lock_path in get_owned_lock_paths():
        for fp in _get_related_files(lock_path):
            try:
                fp.unlink(missing_ok=True)
                if not fp.exists():
                    logger.debug("Removed lock file: %s", fp)
                    removed += 1
            except OSError:
                logger.debug("Failed to remove %s", fp, exc_info=True)
    return removed


def cleanup_all_lock_files_for_pid(pid: int | None = None) -> int:
    """Scan .pokepoke/locks/ and remove all lock artefacts owned by *pid*.

    If *pid* is ``None`` the current process PID is used.
    Returns the number of files actually deleted.
    """
    if pid is None:
        pid = os.getpid()

    locks_dir = Path(".pokepoke") / "locks"
    if not locks_dir.is_dir():
        return 0

    removed = 0
    for meta_file in locks_dir.glob("*.lock.meta"):
        try:
            data = json.loads(meta_file.read_text())
        except (OSError, json.JSONDecodeError, ValueError):
            continue

        if not isinstance(data, dict) or data.get("pid") != pid:
            continue

        # Derive the base .lock path from the .lock.meta path
        lock_path = meta_file.with_suffix("")  # strip .meta → .lock
        for fp in [lock_path, meta_file, lock_path.with_suffix(".lock.break")]:
            try:
                fp.unlink(missing_ok=True)
                logger.debug("Removed lock file for pid %d: %s", pid, fp)
                removed += 1
            except OSError:
                logger.debug("Failed to remove %s", fp, exc_info=True)

    return removed
