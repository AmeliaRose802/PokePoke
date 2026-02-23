"""Cross-process coordination primitives for PokePoke.

Provides OS-kernel-enforced file locks stored in .pokepoke/locks/.
Locks auto-release on process crash since they are backed by filelock.FileLock.
"""

from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from pathlib import Path

from collections.abc import Generator

from filelock import FileLock, Timeout

logger = logging.getLogger(__name__)


def _lock_dir() -> Path:
    """Return (and lazily create) the lock directory."""
    d = Path(".pokepoke") / "locks"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _lock_path(name: str) -> Path:
    """Return the path for a named lock file."""
    return _lock_dir() / f"{name}.lock"


@contextmanager
def acquire_lock(
    name: str,
    timeout: float = -1,
    stale_timeout: float | None = None,
) -> Generator[FileLock]:
    """Blocking context manager that acquires a named file lock.

    Args:
        name: Logical lock name (e.g. ``"worktree-setup"``).
        timeout: Seconds to wait. ``-1`` (default) means wait forever.
        stale_timeout: If set, and the lock file's modification time is older
            than this many seconds, forcibly remove the lock file before
            retrying.  This recovers from crashes where the OS file lock was
            released but the lock file was left behind by a non-filelock tool.
            Use with caution: only safe when you are certain the original
            owner process is no longer running.

    Yields:
        The acquired :class:`filelock.FileLock` instance.

    Raises:
        filelock.Timeout: If *timeout* expires before the lock is acquired.
    """
    lock_path = _lock_path(name)
    lock = FileLock(lock_path)
    if stale_timeout is not None and lock_path.exists():
        age = time.time() - lock_path.stat().st_mtime
        if age > stale_timeout:
            logger.warning(
                'Lock file %s is %.0f seconds old (stale_timeout=%.0f). '
                'Removing stale lock file before acquiring.',
                lock_path, age, stale_timeout,
            )
            try:
                lock_path.unlink(missing_ok=True)
            except OSError as exc:
                logger.warning('Could not remove stale lock file %s: %s', lock_path, exc)
    lock.acquire(timeout=timeout)
    try:
        yield lock
    finally:
        lock.release()


def try_lock(name: str) -> FileLock | None:
    """Non-blocking lock attempt.

    Returns:
        The acquired :class:`filelock.FileLock` if successful, or ``None``
        if the lock is already held by another process.  The caller is
        responsible for calling ``lock.release()`` when done.
    """
    lock = FileLock(_lock_path(name))
    try:
        lock.acquire(timeout=0)
        return lock
    except Timeout:
        return None


_WORKTREE_SETUP_LOCK = "worktree-setup"
_MERGE_LOCK = "merge-queue"
_MANIFEST_LOCK = "worktree-manifest"
_GIT_MAIN_REPO_LOCK = "git-main-repo"

# Age threshold (seconds) after which a merge lock file is considered stale.
# 15 minutes should be well beyond any legitimate merge operation.
_MERGE_LOCK_STALE_AGE = 900.0


@contextmanager
def worktree_setup_lock(timeout: float = 180.0) -> Generator[FileLock, None, None]:
    """Serialize beads assignment + worktree creation across agents."""
    with acquire_lock(_WORKTREE_SETUP_LOCK, timeout=timeout) as lock:
        yield lock


@contextmanager
def merge_lock(timeout: float = 600.0) -> Generator[FileLock, None, None]:
    """Serialize worktree merges across parallel agents.

    This lock is held during the entire merge operation to prevent:
    1. Multiple agents merging concurrently (causing conflicts)
    2. Cleanup agents running while a merge is in progress (leaving dirty state)

    The lock coordinates with cleanup_lock in repo_state_guard.py -
    cleanup agents should wait for this lock before attempting to
    fix uncommitted changes on the main repo.

    A stale lock recovery mechanism removes lock files older than
    ``_MERGE_LOCK_STALE_AGE`` seconds.  This handles the case where a
    process crashed or got stuck and the OS has since released the file
    lock but the lock file remains on disk from a non-filelock tool.

    Args:
        timeout: Seconds to wait. Default 600s (10 minutes) to allow
                 for slow merges with conflict resolution.

    Yields:
        The acquired FileLock instance.
    """
    with acquire_lock(_MERGE_LOCK, timeout=timeout, stale_timeout=_MERGE_LOCK_STALE_AGE) as lock:
        yield lock


def merge_lock_active() -> bool:
    """Return True if another agent currently holds the merge lock."""
    lock = try_lock(_MERGE_LOCK)
    if lock is None:
        return True
    lock.release()
    return False


@contextmanager
def manifest_lock(timeout: float = 30.0) -> Generator[FileLock, None, None]:
    """Serialize worktree manifest read-modify-write operations.

    This lock prevents race conditions when multiple agents concurrently
    update the uncleaned worktrees manifest. Without this lock, parallel
    agents could read the same manifest, both add their entry, and the
    last writer would silently overwrite the other's entry.

    Args:
        timeout: Seconds to wait. Default 30s should be ample since
                 manifest operations are fast (just JSON read/write).

    Yields:
        The acquired FileLock instance.
    """
    with acquire_lock(_MANIFEST_LOCK, timeout=timeout) as lock:
        yield lock


@contextmanager
def git_main_repo_lock(timeout: float = 60.0) -> Generator[FileLock, None, None]:
    """Serialize git operations on the main repository.

    Under high parallelism (e.g. --max-agents 15) multiple agents can run
    ``git status`` or other index-touching git commands against the main
    repository simultaneously, creating ``.git/index.lock`` contention that
    causes timeouts (exit code 0xFFFFFFFF on Windows).

    Callers that perform git operations on the main repository (not a
    worktree) should hold this lock for the duration of those operations.

    Args:
        timeout: Seconds to wait. Default 60s.

    Yields:
        The acquired FileLock instance.
    """
    with acquire_lock(_GIT_MAIN_REPO_LOCK, timeout=timeout) as lock:
        yield lock
