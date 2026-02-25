"""Cross-process coordination primitives for PokePoke.

Provides OS-kernel-enforced file locks stored in .pokepoke/locks/.
Locks auto-release on process crash since they are backed by filelock.FileLock.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
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


def _is_pid_alive(pid: int) -> bool:
    """Check if a process with the given PID is still running (cross-platform)."""
    if pid <= 0:
        return False
    if os.name == "nt":
        # On Windows, os.kill(pid, 0) can hang or send CTRL_C_EVENT.
        # Use ctypes OpenProcess to check existence instead.
        import ctypes
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(
            PROCESS_QUERY_LIMITED_INFORMATION, False, pid,
        )
        if handle:
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
        return False
    # POSIX: signal 0 checks existence without sending a real signal
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # Process exists but we can't signal it
    except OSError:
        return False


def _meta_path(lock_path: Path) -> Path:
    """Return the sidecar metadata path for a lock file."""
    return lock_path.with_suffix(".lock.meta")


def _write_lock_metadata(lock_path: Path) -> None:
    """Write PID and timestamp into a sidecar file after lock acquisition."""
    with contextlib.suppress(OSError):
        _meta_path(lock_path).write_text(json.dumps({
            "pid": os.getpid(),
            "timestamp": time.time(),
        }))


def _read_lock_metadata(lock_path: Path) -> dict[str, object] | None:
    """Read PID/timestamp metadata from a lock's sidecar file."""
    mp = _meta_path(lock_path)
    try:
        text = mp.read_text().strip()
        if not text:
            return None
        data = json.loads(text)
        if isinstance(data, dict) and "pid" in data:
            return data
    except (OSError, json.JSONDecodeError, ValueError):
        pass
    return None


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
            than this many seconds, check whether the holding process is still
            alive (via PID recorded in the lock file).  If the holder is dead,
            forcibly remove the stale lock and re-acquire.

    Yields:
        The acquired :class:`filelock.FileLock` instance.

    Raises:
        filelock.Timeout: If *timeout* expires before the lock is acquired.
    """
    lock_path = _lock_path(name)
    lock = FileLock(lock_path)
    if stale_timeout is not None and lock_path.exists():
        try:
            age = time.time() - lock_path.stat().st_mtime
        except FileNotFoundError:
            age = 0.0  # File disappeared between exists() and stat()
        if age > stale_timeout:
            meta = _read_lock_metadata(lock_path)
            raw_pid = meta.get("pid") if meta else None
            holder_pid = int(raw_pid) if isinstance(raw_pid, (int, float)) else None
            # Only force-remove if holder PID is dead (or unknown)
            if holder_pid is None or not _is_pid_alive(holder_pid):
                logger.warning(
                    'Lock file %s is %.0f s old (stale_timeout=%.0f), '
                    'holder PID %s is dead. Removing stale lock.',
                    lock_path, age, stale_timeout, holder_pid,
                )
                try:
                    lock_path.unlink(missing_ok=True)
                except OSError as exc:
                    logger.warning('Could not remove stale lock file %s: %s', lock_path, exc)
            else:
                logger.info(
                    'Lock file %s is %.0f s old but holder PID %s is still alive.',
                    lock_path, age, holder_pid,
                )
    lock.acquire(timeout=timeout)
    _write_lock_metadata(lock_path)
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
    lp = _lock_path(name)
    lock = FileLock(lp)
    try:
        lock.acquire(timeout=0)
        _write_lock_metadata(lp)
        return lock
    except Timeout:
        return None


_WORKTREE_SETUP_LOCK = "worktree-setup"
_MERGE_LOCK = "merge-queue"
_MANIFEST_LOCK = "worktree-manifest"

# Age threshold (seconds) after which a merge lock file is considered stale.
# 15 minutes should be well beyond any legitimate merge operation.
_MERGE_LOCK_STALE_AGE = 900.0

# Stale-timeout defaults (seconds).  When a lock file is older than this AND
# the recorded holder PID is dead, the lock is forcibly removed.
_WORKTREE_SETUP_STALE = 300.0   # 5 min
_MERGE_STALE = 600.0            # 10 min
_MANIFEST_STALE = 120.0         # 2 min
_CLEANUP_STALE = 300.0          # 5 min (main-repo-cleanup)


@contextmanager
def worktree_setup_lock(timeout: float = 180.0) -> Generator[FileLock, None, None]:
    """Serialize beads assignment + worktree creation across agents."""
    with acquire_lock(
        _WORKTREE_SETUP_LOCK, timeout=timeout, stale_timeout=_WORKTREE_SETUP_STALE,
    ) as lock:
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

    Stale-lock recovery is PID-gated: the lock is only force-removed when
    the recorded holder PID is confirmed dead, so legitimate long-running
    merges are never interrupted.

    Args:
        timeout: Seconds to wait. Default 600s (10 minutes) to allow
                 for slow merges with conflict resolution.

    Yields:
        The acquired FileLock instance.
    """
    with acquire_lock(
        _MERGE_LOCK, timeout=timeout, stale_timeout=_MERGE_STALE,
    ) as lock:
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
    with acquire_lock(
        _MANIFEST_LOCK, timeout=timeout, stale_timeout=_MANIFEST_STALE,
    ) as lock:
        yield lock


# ── Worktree lock (consolidated from worktree_coordination.py) ───────

_WORKTREE_METRICS_DIR = Path(".pokepoke") / "stats"
_WORKTREE_METRICS_PATH = _WORKTREE_METRICS_DIR / "worktree_metrics.json"

# Default timeout for worktree lock (5 minutes)
_WORKTREE_LOCK_DEFAULT_TIMEOUT = 300.0


def _load_worktree_metrics() -> dict[str, float]:
    """Load worktree creation metrics from disk."""
    if not _WORKTREE_METRICS_PATH.exists():
        return {
            "total_attempts": 0,
            "total_successes": 0,
            "total_failures": 0,
            "total_wait_time": 0.0,
            "max_wait_time": 0.0,
        }
    try:
        with open(_WORKTREE_METRICS_PATH) as f:
            data = json.load(f)
            if isinstance(data, dict):
                return data
    except (json.JSONDecodeError, OSError):
        pass
    return {
        "total_attempts": 0,
        "total_successes": 0,
        "total_failures": 0,
        "total_wait_time": 0.0,
        "max_wait_time": 0.0,
    }


def _save_worktree_metrics(metrics: dict[str, float]) -> None:
    """Save worktree creation metrics to disk."""
    try:
        os.makedirs(_WORKTREE_METRICS_DIR, exist_ok=True)
        with open(_WORKTREE_METRICS_PATH, 'w') as f:
            json.dump(metrics, f, indent=2)
    except OSError as e:
        logger.warning("Failed to save worktree metrics: %s", e)


def _record_worktree_attempt(success: bool, wait_time: float) -> None:
    """Record a worktree creation attempt in metrics."""
    metrics = _load_worktree_metrics()
    metrics["total_attempts"] += 1
    if success:
        metrics["total_successes"] += 1
    else:
        metrics["total_failures"] += 1
    metrics["total_wait_time"] += wait_time
    if wait_time > metrics["max_wait_time"]:
        metrics["max_wait_time"] = wait_time
    _save_worktree_metrics(metrics)


@contextmanager
def with_worktree_lock(
    timeout: float = _WORKTREE_LOCK_DEFAULT_TIMEOUT,
) -> Generator[None, None, None]:
    """Context manager for exclusive worktree creation lock.

    Ensures only one agent can create a worktree at a time, preventing
    race conditions when multiple git worktree operations access
    .git/worktrees simultaneously.  Records metrics about wait times.

    Args:
        timeout: Maximum time to wait for lock acquisition (seconds).

    Yields:
        None – Lock is held for duration of context.

    Raises:
        RuntimeError: If lock cannot be acquired within *timeout*.
    """
    wait_start = time.time()
    success = False

    try:
        logger.debug("Acquiring worktree lock (timeout=%ss)...", timeout)
        with worktree_setup_lock(timeout=timeout):
            wait_time = time.time() - wait_start
            if wait_time > 0.1:
                logger.info("Acquired worktree lock after %.2fs", wait_time)
            success = True
            yield
    except Timeout as e:
        wait_time = time.time() - wait_start
        logger.error("Failed to acquire worktree lock after %.2fs", wait_time)
        _record_worktree_attempt(success=False, wait_time=wait_time)
        raise RuntimeError(
            f"Timed out waiting for worktree lock after {timeout}s. "
            "Another agent may be stuck creating a worktree."
        ) from e
    finally:
        if success:
            wait_time = time.time() - wait_start
            _record_worktree_attempt(success=True, wait_time=wait_time)
