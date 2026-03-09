"""Cross-process coordination primitives for PokePoke.

Provides OS-kernel-enforced file locks stored in .pokepoke/locks/.
Locks auto-release on process crash since they are backed by filelock.FileLock.
"""

from __future__ import annotations

import json
import logging
import os
import time
from contextlib import contextmanager, suppress
from pathlib import Path
from collections.abc import Generator

from filelock import FileLock, Timeout

from pokepoke.lock_contention import _contention_tracker  # noqa: F401 (used in acquire_lock)
from pokepoke.lock_contention import get_lock_contention_stats as get_lock_contention_stats

logger = logging.getLogger(__name__)


def _lock_dir() -> Path:
    """Return (and lazily create) the lock directory."""
    d = Path(".pokepoke") / "locks"
    # Use os.makedirs so tests that patch Path.mkdir don't break file-lock creation.
    os.makedirs(d, exist_ok=True)
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
    with suppress(OSError):
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
        name: Logical lock name (e.g. "worktree-setup").
        timeout: Seconds to wait (-1 means wait forever).
        stale_timeout: If set and the lock file is old, verify holder PID and
            remove the lock if the holder is dead.
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
                    _contention_tracker.record_stale_clearance(name)
            else:
                logger.info(
                    'Lock file %s is %.0f s old but holder PID %s is still alive.',
                    lock_path, age, holder_pid,
                )
    t0 = time.monotonic()
    try:
        lock.acquire(timeout=timeout)
    except Timeout:
        _contention_tracker.record_timeout(name, time.monotonic() - t0)
        raise
    wait = time.monotonic() - t0
    _contention_tracker.record_acquisition(name, wait)
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
_BEADS_DB_LOCK = "beads-db"

# Age threshold (seconds) after which a merge lock file is considered stale.
# 15 minutes should be beyond any legitimate merge operation.
_MERGE_LOCK_STALE_AGE = 900.0

# Stale-timeout defaults (seconds) for dead-PID lock recovery.
_WORKTREE_SETUP_STALE = 300.0   # 5 min
_MERGE_STALE = 600.0            # 10 min
_MANIFEST_STALE = 120.0         # 2 min
_CLEANUP_STALE = 300.0          # 5 min (main-repo-cleanup)
_BEADS_DB_STALE = 300.0         # 5 min (beads DB mutations)


@contextmanager
def worktree_setup_lock(timeout: float = 180.0) -> Generator[FileLock, None, None]:
    """Serialize beads assignment + worktree creation across agents."""
    with acquire_lock(
        _WORKTREE_SETUP_LOCK, timeout=timeout, stale_timeout=_WORKTREE_SETUP_STALE,
    ) as lock:
        yield lock


@contextmanager
def beads_db_lock(timeout: float = 180.0) -> Generator[FileLock, None, None]:
    """Serialize beads database mutations across agents using a global lock."""
    with acquire_lock(
        _BEADS_DB_LOCK, timeout=timeout, stale_timeout=_BEADS_DB_STALE,
    ) as lock:
        yield lock


@contextmanager
def merge_lock(timeout: float = 600.0) -> Generator[FileLock, None, None]:
    """Serialize worktree merges across parallel agents."""
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
    """Serialize worktree manifest read-modify-write operations."""
    with acquire_lock(
        _MANIFEST_LOCK, timeout=timeout, stale_timeout=_MANIFEST_STALE,
    ) as lock:
        yield lock


# ── Worktree lock (consolidated from worktree_coordination.py) ───────

_WORKTREE_METRICS_DIR = Path(".pokepoke") / "stats"
_WORKTREE_METRICS_PATH = _WORKTREE_METRICS_DIR / "worktree_metrics.json"

_WORKTREE_LOCK_DEFAULT_TIMEOUT = 300.0  # 5 minutes

_DEFAULT_WORKTREE_METRICS: dict[str, float] = {
    "total_attempts": 0, "total_successes": 0, "total_failures": 0,
    "total_wait_time": 0.0, "max_wait_time": 0.0,
}


def _load_worktree_metrics() -> dict[str, float]:
    """Load worktree creation metrics from disk."""
    if not _WORKTREE_METRICS_PATH.exists():
        return dict(_DEFAULT_WORKTREE_METRICS)
    try:
        with open(_WORKTREE_METRICS_PATH) as f:
            data = json.load(f)
            if isinstance(data, dict):
                return data
    except (json.JSONDecodeError, OSError):
        pass
    return dict(_DEFAULT_WORKTREE_METRICS)


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
    """Exclusive worktree creation lock with metrics."""
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


def check_lock_status(lock_name: str) -> tuple[bool, dict[str, object] | None]:
    """Check if a lock exists and return metadata if available."""
    lock_path = _lock_path(lock_name)
    exists = lock_path.exists()

    if not exists:
        return False, None

    metadata = _read_lock_metadata(lock_path)
    return True, metadata


def clear_lock_if_stale(lock_name: str, max_age_seconds: float = 3600) -> bool:
    """Clear a lock if it's stale.

    To avoid deleting an actively-held lock, this function only clears after
    acquiring the FileLock in non-blocking mode.
    """
    lock_path = _lock_path(lock_name)

    if not lock_path.exists():
        return False  # No lock to clear

    lock = FileLock(lock_path)
    try:
        lock.acquire(timeout=0)
    except Timeout:
        logger.info("Lock %s is currently held; skipping stale clear.", lock_name)
        return False

    def _clear(reason: str) -> bool:
        try:
            lock_path.unlink()
            _meta_path(lock_path).unlink(missing_ok=True)
            logger.info("Cleared stale lock %s (%s)", lock_name, reason)
            return True
        except PermissionError as exc:
            if os.name != "nt" or not lock.is_locked:
                logger.warning("Failed to clear stale lock %s: %s", lock_name, exc)
                return False
            lock.release()
            try:
                lock_path.unlink()
                _meta_path(lock_path).unlink(missing_ok=True)
                logger.info("Cleared stale lock %s (%s)", lock_name, reason)
                return True
            except OSError as exc2:
                logger.warning("Failed to clear stale lock %s: %s", lock_name, exc2)
                return False
        except OSError as exc:
            logger.warning("Failed to clear stale lock %s: %s", lock_name, exc)
            return False

    try:
        metadata = _read_lock_metadata(lock_path)
        if not metadata:
            # Lock exists but no metadata - assume stale
            return _clear("no metadata")

        # Check if holder PID is still alive
        pid = metadata.get("pid")
        if isinstance(pid, int) and not _is_pid_alive(pid):
            return _clear(f"PID {pid} dead")

        # Check if lock is too old
        timestamp = metadata.get("timestamp")
        if isinstance(timestamp, (int, float)):
            age = time.time() - timestamp
            if age > max_age_seconds:
                return _clear(f"age {age:.1f}s > {max_age_seconds}s")

        # Lock is active
        return False
    finally:
        if lock.is_locked:
            lock.release()
