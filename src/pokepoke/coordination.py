"""Cross-process coordination primitives for PokePoke.

Provides OS-kernel-enforced file locks stored in .pokepoke/locks/.
Locks auto-release on process crash since they are backed by filelock.FileLock.
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

from collections.abc import Generator

from filelock import FileLock, Timeout


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
) -> Generator[FileLock]:
    """Blocking context manager that acquires a named file lock.

    Args:
        name: Logical lock name (e.g. ``"worktree-setup"``).
        timeout: Seconds to wait. ``-1`` (default) means wait forever.

    Yields:
        The acquired :class:`filelock.FileLock` instance.

    Raises:
        filelock.Timeout: If *timeout* expires before the lock is acquired.
    """
    lock = FileLock(_lock_path(name))
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

    Args:
        timeout: Seconds to wait. Default 600s (10 minutes) to allow
                 for slow merges with conflict resolution.

    Yields:
        The acquired FileLock instance.
    """
    with acquire_lock(_MERGE_LOCK, timeout=timeout) as lock:
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
