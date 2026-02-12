"""Cross-process coordination primitives for PokePoke.

Provides OS-kernel-enforced file locks stored in .pokepoke/locks/.
Locks auto-release on process crash since they are backed by filelock.FileLock.
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Generator, Optional

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
) -> Generator[FileLock, None, None]:
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


def try_lock(name: str) -> Optional[FileLock]:
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
