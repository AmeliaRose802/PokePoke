"""Lightweight performance monitor with configurable threshold alerting.

Checks configurable thresholds each loop iteration and logs warnings
when metrics exceed safe operating bounds.  Tracks alerts over time
so the orchestrator can surface persistent degradation.
"""

import logging
import threading
import time
from dataclasses import dataclass
from typing import Any

from pokepoke.utils.memory_utils import get_available_memory_mb, get_process_rss_mb

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PerformanceAlert:
    """A single threshold violation."""
    category: str       # e.g. "merge_queue", "lock_wait", "iteration_time"
    message: str
    value: float        # the observed metric value
    threshold: float    # the configured threshold
    timestamp: float    # time.time() when detected


class PerformanceMonitor:
    """Thread-safe monitor that checks operational thresholds and records alerts."""

    def __init__(  # noqa: PLR0913
        self,
        *,
        max_merge_queue_depth: int = 5,
        max_lock_wait_seconds: float = 30.0,
        max_iteration_seconds: float = 30.0,
        min_memory_mb: float = 256.0,
        min_success_rate: float = 0.5,
        max_alerts: int = 500,
        enabled: bool = True,
        rss_monotonic_window: int = 5,
    ) -> None:
        self._enabled = enabled
        self._max_merge_queue_depth = max_merge_queue_depth
        self._max_lock_wait_seconds = max_lock_wait_seconds
        self._max_iteration_seconds = max_iteration_seconds
        self._min_memory_mb = min_memory_mb
        self._min_success_rate = min_success_rate
        self._max_alerts = max_alerts
        self._rss_monotonic_window = rss_monotonic_window

        self._lock = threading.Lock()
        self._alerts: list[PerformanceAlert] = []
        self._total_checks: int = 0
        self._total_alerts: int = 0
        # Running success/failure counters for success-rate tracking
        self._succeeded: int = 0
        self._failed: int = 0
        # RSS history for monotonic growth detection
        self._rss_samples: list[int] = []

    # ── Individual threshold checks ──────────────────────────────

    def check_merge_queue(self, depth: int) -> PerformanceAlert | None:
        """Check whether merge queue depth exceeds the configured maximum."""
        if not self._enabled:
            return None
        if depth > self._max_merge_queue_depth:
            alert = PerformanceAlert(
                category="merge_queue",
                message=f"Merge queue depth {depth} exceeds threshold {self._max_merge_queue_depth}",
                value=float(depth),
                threshold=float(self._max_merge_queue_depth),
                timestamp=time.time(),
            )
            self._record_alert(alert)
            return alert
        return None

    def check_lock_wait(self, name: str, wait_seconds: float) -> PerformanceAlert | None:
        """Check whether a lock acquisition took too long."""
        if not self._enabled:
            return None
        if wait_seconds > self._max_lock_wait_seconds:
            alert = PerformanceAlert(
                category="lock_wait",
                message=(
                    f"Lock '{name}' acquisition took {wait_seconds:.1f}s, "
                    f"exceeds threshold {self._max_lock_wait_seconds:.1f}s"
                ),
                value=wait_seconds,
                threshold=self._max_lock_wait_seconds,
                timestamp=time.time(),
            )
            self._record_alert(alert)
            return alert
        return None

    def check_iteration(self, elapsed_seconds: float) -> PerformanceAlert | None:
        """Check whether a loop iteration exceeded the time threshold."""
        if not self._enabled:
            return None
        if elapsed_seconds > self._max_iteration_seconds:
            alert = PerformanceAlert(
                category="iteration_time",
                message=(
                    f"Loop iteration took {elapsed_seconds:.1f}s, "
                    f"exceeds threshold {self._max_iteration_seconds:.1f}s"
                ),
                value=elapsed_seconds,
                threshold=self._max_iteration_seconds,
                timestamp=time.time(),
            )
            self._record_alert(alert)
            return alert
        return None

    def check_memory(self) -> PerformanceAlert | None:
        """Check whether available system memory is below the minimum threshold."""
        if not self._enabled:
            return None
        available_mb = get_available_memory_mb()
        if available_mb <= 0:
            return None
        if available_mb < self._min_memory_mb:
            alert = PerformanceAlert(
                category="memory",
                message=(
                    f"Available memory {available_mb} MB below "
                    f"threshold {self._min_memory_mb:.0f} MB"
                ),
                value=float(available_mb),
                threshold=self._min_memory_mb,
                timestamp=time.time(),
            )
            self._record_alert(alert)
            return alert
        return None

    def check_rss(self) -> PerformanceAlert | None:
        """Check process RSS for monotonic growth indicating a potential memory leak.

        Samples the current RSS and keeps a sliding window. If the last
        *rss_monotonic_window* samples are strictly monotonically increasing,
        a performance alert is raised.
        """
        if not self._enabled:
            return None
        rss_mb = get_process_rss_mb()
        if rss_mb <= 0:
            return None
        with self._lock:
            self._rss_samples.append(rss_mb)
            # Keep at most 2× window to bound memory
            max_keep = self._rss_monotonic_window * 2
            if len(self._rss_samples) > max_keep:
                self._rss_samples = self._rss_samples[-max_keep:]
            window = self._rss_samples[-self._rss_monotonic_window:]
        if len(window) < self._rss_monotonic_window:
            return None
        if all(window[i] < window[i + 1] for i in range(len(window) - 1)):
            alert = PerformanceAlert(
                category="rss_growth",
                message=(
                    f"Process RSS grew monotonically over {self._rss_monotonic_window} "
                    f"samples: {window[0]}MB → {window[-1]}MB (potential leak)"
                ),
                value=float(rss_mb),
                threshold=float(window[0]),
                timestamp=time.time(),
            )
            self._record_alert(alert)
            return alert
        return None

    def check_success_rate(
        self, succeeded: int, total: int,
    ) -> PerformanceAlert | None:
        """Check whether the agent success rate is below threshold.

        Args:
            succeeded: Total successful completions so far.
            total: Total attempts (succeeded + failed) so far.
        """
        if not self._enabled:
            return None
        if total <= 0:
            return None
        rate = succeeded / total
        if rate < self._min_success_rate:
            alert = PerformanceAlert(
                category="success_rate",
                message=(
                    f"Success rate {rate:.0%} ({succeeded}/{total}) "
                    f"below threshold {self._min_success_rate:.0%}"
                ),
                value=rate,
                threshold=self._min_success_rate,
                timestamp=time.time(),
            )
            self._record_alert(alert)
            return alert
        return None

    def record_result(self, success: bool) -> None:
        """Record a work-item success or failure for success-rate tracking."""
        with self._lock:
            if success:
                self._succeeded += 1
            else:
                self._failed += 1

    # ── Combined check ───────────────────────────────────────────

    def check_all(
        self,
        *,
        iteration_seconds: float | None = None,
        merge_queue_depth: int | None = None,
    ) -> list[PerformanceAlert]:
        """Run all applicable threshold checks and return any alerts."""
        alerts: list[PerformanceAlert] = []
        if not self._enabled:
            return alerts

        with self._lock:
            self._total_checks += 1

        if iteration_seconds is not None:
            alert = self.check_iteration(iteration_seconds)
            if alert:
                alerts.append(alert)

        if merge_queue_depth is not None:
            alert = self.check_merge_queue(merge_queue_depth)
            if alert:
                alerts.append(alert)

        # Memory check (uses system available memory via process_utils)
        alert = self.check_memory()
        if alert:
            alerts.append(alert)

        # Process RSS monotonic growth check
        alert = self.check_rss()
        if alert:
            alerts.append(alert)

        # Success rate (uses internally tracked counters)
        with self._lock:
            total = self._succeeded + self._failed
            succeeded = self._succeeded
        if total > 0:
            alert = self.check_success_rate(succeeded, total)
            if alert:
                alerts.append(alert)

        for a in alerts:
            logger.warning("⚠️  PERF ALERT [%s]: %s", a.category, a.message)

        return alerts

    # ── Alert management ─────────────────────────────────────────

    def _record_alert(self, alert: PerformanceAlert) -> None:
        with self._lock:
            self._alerts.append(alert)
            if len(self._alerts) >= self._max_alerts:
                del self._alerts[: len(self._alerts) // 2]
            self._total_alerts += 1

    def get_alerts(self, *, since: float | None = None) -> list[PerformanceAlert]:
        """Return recorded alerts, optionally filtered by timestamp."""
        with self._lock:
            if since is None:
                return list(self._alerts)
            return [a for a in self._alerts if a.timestamp >= since]

    def clear_alerts(self) -> None:
        """Reset all recorded alerts."""
        with self._lock:
            self._alerts.clear()

    # ── Snapshot for reporting ───────────────────────────────────

    def snapshot(self) -> dict[str, Any]:
        """Return a JSON-serialisable snapshot of monitor state."""
        with self._lock:
            total = self._succeeded + self._failed
            rss_samples = list(self._rss_samples)
            return {
                "enabled": self._enabled,
                "total_checks": self._total_checks,
                "total_alerts": self._total_alerts,
                "succeeded": self._succeeded,
                "failed": self._failed,
                "success_rate": (self._succeeded / total) if total > 0 else None,
                "rss_current_mb": rss_samples[-1] if rss_samples else None,
                "rss_samples": rss_samples[-self._rss_monotonic_window:],
                "thresholds": {
                    "max_merge_queue_depth": self._max_merge_queue_depth,
                    "max_lock_wait_seconds": self._max_lock_wait_seconds,
                    "max_iteration_seconds": self._max_iteration_seconds,
                    "min_memory_mb": self._min_memory_mb,
                    "min_success_rate": self._min_success_rate,
                },
                "recent_alerts": [
                    {
                        "category": a.category,
                        "message": a.message,
                        "value": a.value,
                        "threshold": a.threshold,
                        "timestamp": a.timestamp,
                    }
                    for a in self._alerts[-10:]
                ],
            }

    def reset(self) -> None:
        """Clear all state (useful for testing)."""
        with self._lock:
            self._alerts.clear()
            self._total_checks = 0
            self._total_alerts = 0
            self._succeeded = 0
            self._failed = 0
            self._rss_samples.clear()


# ── Module-level singleton ───────────────────────────────────────

_performance_monitor: PerformanceMonitor | None = None
_singleton_lock = threading.Lock()


def get_performance_monitor() -> PerformanceMonitor:
    """Return the module-level PerformanceMonitor singleton.

    Lazily creates the instance using values from the project config.
    """
    global _performance_monitor
    with _singleton_lock:
        if _performance_monitor is None:
            _performance_monitor = _create_from_config()
        return _performance_monitor


def _create_from_config() -> PerformanceMonitor:
    """Build a PerformanceMonitor from the current project configuration."""
    from pokepoke.config import get_config
    cfg = get_config().performance_thresholds
    return PerformanceMonitor(
        max_merge_queue_depth=cfg.max_merge_queue_depth,
        max_lock_wait_seconds=cfg.max_lock_wait_seconds,
        max_iteration_seconds=cfg.max_iteration_seconds,
        min_memory_mb=cfg.min_memory_mb,
        min_success_rate=cfg.min_success_rate,
        enabled=cfg.enabled,
    )


def reset_performance_monitor() -> None:
    """Reset the singleton (useful for testing)."""
    global _performance_monitor
    with _singleton_lock:
        _performance_monitor = None


def run_iteration_checks(iteration_seconds: float, success: bool) -> None:
    """Convenience: record result and run all checks for one loop iteration."""
    mon = get_performance_monitor()
    mon.record_result(success)
    merge_depth: int | None = None
    try:
        from pokepoke.git.merge_queue import get_merge_queue
        mq = get_merge_queue()
        if mq.is_running:
            merge_depth = mq.pending_count
    except Exception:
        logger.debug("Failed to get merge queue depth", exc_info=True)
    mon.check_all(iteration_seconds=iteration_seconds, merge_queue_depth=merge_depth)
