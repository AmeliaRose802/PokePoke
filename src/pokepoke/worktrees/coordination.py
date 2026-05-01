"""Cross-process coordination primitives for PokePoke.

Provides OS-kernel-enforced file locks stored in .pokepoke/locks/.
Locks auto-release on process crash since they are backed by filelock.FileLock.
"""

import dataclasses
import json
import logging
import os
import threading
import time
from collections.abc import Generator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path

from filelock import FileLock, Timeout

from pokepoke.worktrees.lock_contention import _contention_tracker
from pokepoke.worktrees.lock_contention import get_lock_contention_stats as get_lock_contention_stats

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
        logger.debug("Failed to read lock file %s", lock_path, exc_info=True)
    return None


def _break_stale_lock_if_needed(
    name: str, lock_path: Path, stale_timeout: float,
) -> None:
    """Detect and remove a stale lock, serialized via a meta-lock to prevent TOCTOU races."""
    if not lock_path.exists():
        return
    # Meta-lock ensures only one process checks-and-removes at a time.
    meta_lock = FileLock(str(lock_path) + ".break")
    try:
        meta_lock.acquire(timeout=30)
    except Timeout:
        logger.debug("Meta-lock for stale detection on %s timed out; skipping.", name)
        return
    try:
        if not lock_path.exists():
            return
        try:
            age = time.time() - lock_path.stat().st_mtime
        except FileNotFoundError:
            return
        if age <= stale_timeout:
            return
        meta = _read_lock_metadata(lock_path)
        raw_pid = meta.get("pid") if meta else None
        holder_pid = int(raw_pid) if isinstance(raw_pid, (int, float)) else None
        if holder_pid is not None and _is_pid_alive(holder_pid):
            logger.info(
                'Lock file %s is %.0f s old but holder PID %s is still alive.',
                lock_path, age, holder_pid,
            )
            return
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
    finally:
        meta_lock.release()


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
            remove the lock if the holder is dead.  Stale detection is
            serialized via a meta-lock to prevent TOCTOU races.
    Raises:
        filelock.Timeout: If *timeout* expires before the lock is acquired.
    """
    lock_path = _lock_path(name)
    lock = FileLock(lock_path)
    if stale_timeout is not None:
        _break_stale_lock_if_needed(name, lock_path, stale_timeout)
    t0 = time.monotonic()
    try:
        lock.acquire(timeout=timeout)
    except Timeout:
        _contention_tracker.record_timeout(name, time.monotonic() - t0)
        raise
    wait = time.monotonic() - t0
    _contention_tracker.record_acquisition(name, wait)
    # Alert if lock acquisition exceeded performance threshold
    from pokepoke.stats.performance_monitor import get_performance_monitor
    get_performance_monitor().check_lock_wait(name, wait)
    _write_lock_metadata(lock_path)
    try:
        yield lock
    finally:
        lock.release()


def try_lock(name: str) -> FileLock | None:
    """Non-blocking lock attempt; returns acquired lock or None."""
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
_MODEL_REGISTRY_LOCK = "model-registry"

_MERGE_LOCK_STALE_AGE = 900.0  # 15 min; beyond any legitimate merge

_WORKTREE_SETUP_STALE = 300.0  # 5 min
_MERGE_STALE = 600.0           # 10 min
_MANIFEST_STALE = 120.0        # 2 min
_CLEANUP_STALE = 300.0         # 5 min
_BEADS_DB_STALE = 300.0        # 5 min
_MODEL_REGISTRY_STALE = 120.0  # 2 min


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


# ── Main-repo git operations lock ────────────────────────────────────
# Threading-based reentrant lock that prevents index.lock contention
# between the poll loop (check_and_commit_main_repo) and the merge
# queue worker thread.  Both must acquire this before running any git
# command whose cwd is the main repository.
_main_repo_git_lock = threading.RLock()


@contextmanager
def main_repo_git_lock() -> Generator[None, None, None]:
    """Serialize git operations on the main repository across threads."""
    _main_repo_git_lock.acquire()
    try:
        yield
    finally:
        _main_repo_git_lock.release()


@contextmanager
def manifest_lock(timeout: float = 30.0) -> Generator[FileLock, None, None]:
    """Serialize worktree manifest read-modify-write operations."""
    with acquire_lock(
        _MANIFEST_LOCK, timeout=timeout, stale_timeout=_MANIFEST_STALE,
    ) as lock:
        yield lock


@contextmanager
def model_registry_lock(timeout: float = 30.0) -> Generator[FileLock, None, None]:
    """Serialize model registry read-modify-write operations."""
    with acquire_lock(
        _MODEL_REGISTRY_LOCK, timeout=timeout, stale_timeout=_MODEL_REGISTRY_STALE,
    ) as lock:
        yield lock


# ── Worktree lock (consolidated from worktree_coordination.py) ───────

_WORKTREE_METRICS_DIR = Path(".pokepoke") / "stats"
_WORKTREE_METRICS_PATH = _WORKTREE_METRICS_DIR / "worktree_metrics.json"

_WORKTREE_LOCK_DEFAULT_TIMEOUT = 300.0  # 5 minutes


@dataclass
class WorktreeMetrics:
    """Metrics tracking worktree creation attempts and wait times."""

    total_attempts: float = 0
    total_successes: float = 0
    total_failures: float = 0
    total_wait_time: float = 0.0
    max_wait_time: float = 0.0


_DEFAULT_WORKTREE_METRICS = WorktreeMetrics()


def _load_worktree_metrics() -> WorktreeMetrics:
    """Load worktree creation metrics from disk."""
    if not _WORKTREE_METRICS_PATH.exists():
        return WorktreeMetrics()
    try:
        with open(_WORKTREE_METRICS_PATH) as f:
            data = json.load(f)
            if isinstance(data, dict):
                return WorktreeMetrics(
                    total_attempts=data.get("total_attempts", 0),
                    total_successes=data.get("total_successes", 0),
                    total_failures=data.get("total_failures", 0),
                    total_wait_time=data.get("total_wait_time", 0.0),
                    max_wait_time=data.get("max_wait_time", 0.0),
                )
    except (json.JSONDecodeError, OSError):
        logger.debug("Failed to load worktree metrics", exc_info=True)
    return WorktreeMetrics()


def _save_worktree_metrics(metrics: WorktreeMetrics) -> None:
    """Save worktree creation metrics to disk."""
    try:
        os.makedirs(_WORKTREE_METRICS_DIR, exist_ok=True)
        with open(_WORKTREE_METRICS_PATH, 'w') as f:
            json.dump(dataclasses.asdict(metrics), f, indent=2)
    except OSError as e:
        logger.warning("Failed to save worktree metrics: %s", e)


def _record_worktree_attempt(success: bool, wait_time: float) -> None:
    """Record a worktree creation attempt in metrics."""
    metrics = _load_worktree_metrics()
    metrics.total_attempts += 1
    if success:
        metrics.total_successes += 1
    else:
        metrics.total_failures += 1
    metrics.total_wait_time += wait_time
    metrics.max_wait_time = max(metrics.max_wait_time, wait_time)
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
