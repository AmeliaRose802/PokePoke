"""Lock contention tracking for PokePoke coordination primitives.

Provides a thread-safe tracker that records per-lock acquisition metrics
including wait durations, timeout counts, stale-lock clearances, and a
histogram of acquisition times.
"""

import copy
import threading
from typing import Any

# Histogram bucket upper-bounds (seconds) for lock acquisition times.
_HISTOGRAM_BUCKETS: tuple[float, ...] = (
    0.01, 0.05, 0.1, 0.5, 1.0, 5.0, 10.0, 30.0, 60.0, 120.0,
)


class LockContentionTracker:
    """Thread-safe tracker for lock acquisition metrics.

    Records per-lock-name counters for acquired/timeout events, cumulative
    and max wait durations, stale-lock clearance frequency, and a histogram
    of acquisition times.
    """

    def __init__(self) -> None:
        self._mu = threading.Lock()
        self._stats: dict[str, dict[str, Any]] = {}

    def _ensure_lock(self, name: str) -> dict[str, Any]:
        """Return (or create) the stats dict for *name*. Caller must hold _mu."""
        if name not in self._stats:
            self._stats[name] = {
                "acquired": 0,
                "timeouts": 0,
                "total_wait": 0.0,
                "max_wait": 0.0,
                "stale_cleared": 0,
                "histogram": {str(b): 0 for b in _HISTOGRAM_BUCKETS},
            }
        return self._stats[name]

    def record_acquisition(self, name: str, wait_seconds: float) -> None:
        """Record a successful lock acquisition."""
        with self._mu:
            s = self._ensure_lock(name)
            s["acquired"] += 1
            s["total_wait"] += wait_seconds
            s["max_wait"] = max(s["max_wait"], wait_seconds)
            self._update_histogram(s, wait_seconds)

    def record_timeout(self, name: str, wait_seconds: float) -> None:
        """Record a failed lock acquisition (timeout)."""
        with self._mu:
            s = self._ensure_lock(name)
            s["timeouts"] += 1
            s["total_wait"] += wait_seconds
            s["max_wait"] = max(s["max_wait"], wait_seconds)

    def record_stale_clearance(self, name: str) -> None:
        """Record that a stale lock was cleared for *name*."""
        with self._mu:
            s = self._ensure_lock(name)
            s["stale_cleared"] += 1

    @staticmethod
    def _update_histogram(stats: dict[str, Any], wait_seconds: float) -> None:
        """Increment the appropriate histogram bucket."""
        for bucket in _HISTOGRAM_BUCKETS:
            if wait_seconds <= bucket:
                stats["histogram"][str(bucket)] += 1
                return
        # Overflows the largest bucket – count in the last one.
        stats["histogram"][str(_HISTOGRAM_BUCKETS[-1])] += 1

    def snapshot(self) -> dict[str, Any]:
        """Return a deep copy of all contention stats."""
        with self._mu:
            result: dict[str, Any] = copy.deepcopy(self._stats)
            return result


# Module-level singleton used by coordination.acquire_lock.
_contention_tracker = LockContentionTracker()


def get_lock_contention_stats() -> dict[str, Any]:
    """Return a snapshot of lock contention metrics.

    The returned dict is keyed by lock name. Each value contains:
    - acquired: number of successful acquisitions
    - timeouts: number of timeout failures
    - total_wait: cumulative wait time in seconds
    - max_wait: maximum single wait time in seconds
    - stale_cleared: number of stale lock clearances
    - histogram: dict mapping bucket upper-bound (str) to count
    """
    return _contention_tracker.snapshot()
