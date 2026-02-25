"""Coordination mechanisms for parallel worktree operations.

Provides file-based locking to prevent race conditions when multiple
agents attempt to create worktrees simultaneously.
"""

import json
import logging
import os
import time
from contextlib import contextmanager
from pathlib import Path
from collections.abc import Iterator

from filelock import FileLock, Timeout

logger = logging.getLogger(__name__)

# Lock file location
_LOCK_DIR = Path(".pokepoke/locks")
_WORKTREE_LOCK_PATH = _LOCK_DIR / "worktree-setup.lock"

# Metrics file location
_STATS_DIR = Path(".pokepoke/stats")
_METRICS_PATH = _STATS_DIR / "worktree_metrics.json"

# Lock timeout (5 minutes should be more than enough for any git operation)
_DEFAULT_TIMEOUT = 300


def _ensure_dirs() -> None:
    """Ensure lock and stats directories exist."""
    # Use os.makedirs so tests that mock Path.mkdir don't break lock acquisition.
    os.makedirs(_LOCK_DIR, exist_ok=True)
    os.makedirs(_STATS_DIR, exist_ok=True)


def _load_metrics() -> dict[str, float]:
    """Load worktree creation metrics from disk."""
    if not _METRICS_PATH.exists():
        return {
            "total_attempts": 0,
            "total_successes": 0,
            "total_failures": 0,
            "total_wait_time": 0.0,
            "max_wait_time": 0.0,
        }
    try:
        with open(_METRICS_PATH) as f:
            data = json.load(f)
            # Ensure we return the correct type
            if isinstance(data, dict):
                return data
            return {
                "total_attempts": 0,
                "total_successes": 0,
                "total_failures": 0,
                "total_wait_time": 0.0,
                "max_wait_time": 0.0,
            }
    except (json.JSONDecodeError, OSError):
        return {
            "total_attempts": 0,
            "total_successes": 0,
            "total_failures": 0,
            "total_wait_time": 0.0,
            "max_wait_time": 0.0,
        }


def _save_metrics(metrics: dict[str, float]) -> None:
    """Save worktree creation metrics to disk."""
    try:
        os.makedirs(_STATS_DIR, exist_ok=True)
        with open(_METRICS_PATH, 'w') as f:
            json.dump(metrics, f, indent=2)
    except OSError as e:
        logger.warning(f"Failed to save worktree metrics: {e}")


def _record_attempt(success: bool, wait_time: float) -> None:
    """Record a worktree creation attempt in metrics."""
    metrics = _load_metrics()
    metrics["total_attempts"] += 1
    if success:
        metrics["total_successes"] += 1
    else:
        metrics["total_failures"] += 1
    metrics["total_wait_time"] += wait_time
    if wait_time > metrics["max_wait_time"]:
        metrics["max_wait_time"] = wait_time
    _save_metrics(metrics)


@contextmanager
def with_worktree_lock(timeout: float = _DEFAULT_TIMEOUT) -> Iterator[None]:
    """Context manager for exclusive worktree creation lock.

    Ensures only one agent can create a worktree at a time, preventing
    race conditions when multiple git worktree operations access
    .git/worktrees simultaneously.

    Args:
        timeout: Maximum time to wait for lock acquisition (seconds)

    Yields:
        None - Lock is held for duration of context

    Raises:
        Timeout: If lock cannot be acquired within timeout period

    Example:
        >>> with with_worktree_lock():
        ...     create_worktree("my-item-123")
    """
    _ensure_dirs()

    lock = FileLock(str(_WORKTREE_LOCK_PATH), timeout=timeout)
    wait_start = time.time()
    success = False

    try:
        logger.debug(f"Acquiring worktree lock (timeout={timeout}s)...")
        with lock:
            wait_time = time.time() - wait_start
            if wait_time > 0.1:  # Log only if we actually waited
                logger.info(f"Acquired worktree lock after {wait_time:.2f}s")
            success = True
            yield
            # Lock released automatically on exit
    except Timeout as e:
        wait_time = time.time() - wait_start
        logger.error(f"Failed to acquire worktree lock after {wait_time:.2f}s")
        _record_attempt(success=False, wait_time=wait_time)
        raise RuntimeError(
            f"Timed out waiting for worktree lock after {timeout}s. "
            "Another agent may be stuck creating a worktree."
        ) from e
    finally:
        # Record successful attempt
        if success:
            wait_time = time.time() - wait_start
            _record_attempt(success=True, wait_time=wait_time)
