"""Tests for pokepoke.performance_monitor module."""

import threading
import time

import pytest

from pokepoke.performance_monitor import (
    PerformanceAlert,
    PerformanceMonitor,
    get_performance_monitor,
    reset_performance_monitor,
)


class TestPerformanceAlert:
    """Tests for the PerformanceAlert dataclass."""

    def test_frozen(self) -> None:
        alert = PerformanceAlert(
            category="test", message="msg", value=1.0, threshold=0.5, timestamp=0.0,
        )
        with pytest.raises(AttributeError):
            alert.category = "changed"  # type: ignore[misc]

    def test_fields(self) -> None:
        alert = PerformanceAlert(
            category="merge_queue", message="depth exceeded",
            value=10.0, threshold=5.0, timestamp=12345.0,
        )
        assert alert.category == "merge_queue"
        assert alert.value == 10.0
        assert alert.threshold == 5.0


class TestPerformanceMonitorMergeQueue:
    """Tests for merge queue depth threshold checking."""

    def test_no_alert_within_threshold(self) -> None:
        mon = PerformanceMonitor(max_merge_queue_depth=5)
        assert mon.check_merge_queue(3) is None
        assert mon.check_merge_queue(5) is None

    def test_alert_exceeds_threshold(self) -> None:
        mon = PerformanceMonitor(max_merge_queue_depth=5)
        alert = mon.check_merge_queue(6)
        assert alert is not None
        assert alert.category == "merge_queue"
        assert alert.value == 6.0
        assert alert.threshold == 5.0

    def test_disabled_returns_none(self) -> None:
        mon = PerformanceMonitor(max_merge_queue_depth=1, enabled=False)
        assert mon.check_merge_queue(100) is None


class TestPerformanceMonitorLockWait:
    """Tests for lock acquisition wait time threshold."""

    def test_no_alert_within_threshold(self) -> None:
        mon = PerformanceMonitor(max_lock_wait_seconds=30.0)
        assert mon.check_lock_wait("test-lock", 10.0) is None

    def test_alert_exceeds_threshold(self) -> None:
        mon = PerformanceMonitor(max_lock_wait_seconds=30.0)
        alert = mon.check_lock_wait("merge", 45.0)
        assert alert is not None
        assert alert.category == "lock_wait"
        assert "merge" in alert.message
        assert alert.value == 45.0

    def test_at_boundary_no_alert(self) -> None:
        mon = PerformanceMonitor(max_lock_wait_seconds=30.0)
        assert mon.check_lock_wait("x", 30.0) is None


class TestPerformanceMonitorIteration:
    """Tests for loop iteration time threshold."""

    def test_no_alert_fast_iteration(self) -> None:
        mon = PerformanceMonitor(max_iteration_seconds=30.0)
        assert mon.check_iteration(5.0) is None

    def test_alert_slow_iteration(self) -> None:
        mon = PerformanceMonitor(max_iteration_seconds=30.0)
        alert = mon.check_iteration(45.0)
        assert alert is not None
        assert alert.category == "iteration_time"
        assert alert.value == 45.0


class TestPerformanceMonitorMemory:
    """Tests for memory threshold checking."""

    def test_returns_none_when_memory_unavailable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mon = PerformanceMonitor(min_memory_mb=256.0)
        monkeypatch.setattr(
            "pokepoke.performance_monitor.get_available_memory_mb", lambda: 0,
        )
        assert mon.check_memory() is None

    def test_no_alert_with_enough_memory(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mon = PerformanceMonitor(min_memory_mb=256.0)
        monkeypatch.setattr(
            "pokepoke.performance_monitor.get_available_memory_mb", lambda: 4096,
        )
        assert mon.check_memory() is None

    def test_alert_when_memory_low(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mon = PerformanceMonitor(min_memory_mb=512.0)
        monkeypatch.setattr(
            "pokepoke.performance_monitor.get_available_memory_mb", lambda: 200,
        )
        alert = mon.check_memory()
        assert alert is not None
        assert alert.category == "memory"
        assert alert.value == 200.0
        assert alert.threshold == 512.0

    def test_alert_at_boundary(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mon = PerformanceMonitor(min_memory_mb=256.0)
        monkeypatch.setattr(
            "pokepoke.performance_monitor.get_available_memory_mb", lambda: 256,
        )
        # Exactly at threshold — no alert (only below fires)
        assert mon.check_memory() is None

    def test_disabled_returns_none(self) -> None:
        mon = PerformanceMonitor(min_memory_mb=99999999.0, enabled=False)
        assert mon.check_memory() is None


class TestPerformanceMonitorSuccessRate:
    """Tests for agent success rate threshold."""

    def test_no_alert_above_threshold(self) -> None:
        mon = PerformanceMonitor(min_success_rate=0.5)
        assert mon.check_success_rate(8, 10) is None

    def test_alert_below_threshold(self) -> None:
        mon = PerformanceMonitor(min_success_rate=0.5)
        alert = mon.check_success_rate(2, 10)
        assert alert is not None
        assert alert.category == "success_rate"
        assert alert.value == pytest.approx(0.2)
        assert alert.threshold == 0.5

    def test_zero_total_no_alert(self) -> None:
        mon = PerformanceMonitor(min_success_rate=0.5)
        assert mon.check_success_rate(0, 0) is None

    def test_at_boundary_no_alert(self) -> None:
        mon = PerformanceMonitor(min_success_rate=0.5)
        assert mon.check_success_rate(5, 10) is None


class TestRecordResult:
    """Tests for success/failure tracking via record_result."""

    def test_record_success(self) -> None:
        mon = PerformanceMonitor()
        mon.record_result(True)
        mon.record_result(True)
        snap = mon.snapshot()
        assert snap["succeeded"] == 2
        assert snap["failed"] == 0

    def test_record_failure(self) -> None:
        mon = PerformanceMonitor()
        mon.record_result(False)
        snap = mon.snapshot()
        assert snap["succeeded"] == 0
        assert snap["failed"] == 1


class TestCheckAll:
    """Tests for the combined check_all method."""

    def test_no_alerts_when_healthy(self) -> None:
        mon = PerformanceMonitor(
            max_iteration_seconds=60.0,
            max_merge_queue_depth=10,
            min_memory_mb=1.0,  # Very low so memory check doesn't fire
        )
        alerts = mon.check_all(iteration_seconds=5.0, merge_queue_depth=2)
        assert alerts == []

    def test_multiple_alerts(self) -> None:
        mon = PerformanceMonitor(
            max_iteration_seconds=10.0,
            max_merge_queue_depth=3,
            min_success_rate=0.8,
        )
        # Pre-record low success rate
        for _ in range(8):
            mon.record_result(False)
        for _ in range(2):
            mon.record_result(True)

        alerts = mon.check_all(iteration_seconds=20.0, merge_queue_depth=5)
        categories = {a.category for a in alerts}
        assert "iteration_time" in categories
        assert "merge_queue" in categories
        assert "success_rate" in categories

    def test_increments_total_checks(self) -> None:
        mon = PerformanceMonitor()
        mon.check_all()
        mon.check_all()
        mon.check_all()
        assert mon.snapshot()["total_checks"] == 3

    def test_disabled_returns_empty(self) -> None:
        mon = PerformanceMonitor(enabled=False)
        alerts = mon.check_all(iteration_seconds=9999.0, merge_queue_depth=9999)
        assert alerts == []

    def test_none_params_skip_checks(self) -> None:
        mon = PerformanceMonitor(max_iteration_seconds=1.0, max_merge_queue_depth=1)
        alerts = mon.check_all(iteration_seconds=None, merge_queue_depth=None)
        # No iteration or merge alerts since params are None
        categories = {a.category for a in alerts}
        assert "iteration_time" not in categories
        assert "merge_queue" not in categories


class TestAlertManagement:
    """Tests for alert recording, retrieval, and clearing."""

    def test_get_alerts_returns_all(self) -> None:
        mon = PerformanceMonitor(max_merge_queue_depth=1)
        mon.check_merge_queue(5)
        mon.check_merge_queue(10)
        alerts = mon.get_alerts()
        assert len(alerts) == 2

    def test_get_alerts_since_filter(self) -> None:
        mon = PerformanceMonitor(max_merge_queue_depth=1)
        mon.check_merge_queue(5)
        time.sleep(0.05)
        cutoff = time.time() + 0.001  # Ensure cutoff is after first alert
        time.sleep(0.05)
        mon.check_merge_queue(10)
        alerts = mon.get_alerts(since=cutoff)
        assert len(alerts) == 1
        assert alerts[0].value == 10.0

    def test_clear_alerts(self) -> None:
        mon = PerformanceMonitor(max_merge_queue_depth=1)
        mon.check_merge_queue(5)
        assert len(mon.get_alerts()) == 1
        mon.clear_alerts()
        assert len(mon.get_alerts()) == 0


class TestSnapshot:
    """Tests for the snapshot method."""

    def test_snapshot_structure(self) -> None:
        mon = PerformanceMonitor(
            max_merge_queue_depth=5,
            max_lock_wait_seconds=30.0,
            max_iteration_seconds=30.0,
            min_memory_mb=256.0,
            min_success_rate=0.5,
        )
        snap = mon.snapshot()
        assert snap["enabled"] is True
        assert snap["total_checks"] == 0
        assert snap["total_alerts"] == 0
        assert snap["succeeded"] == 0
        assert snap["failed"] == 0
        assert snap["success_rate"] is None
        assert snap["thresholds"]["max_merge_queue_depth"] == 5
        assert snap["thresholds"]["max_lock_wait_seconds"] == 30.0
        assert snap["recent_alerts"] == []

    def test_snapshot_success_rate(self) -> None:
        mon = PerformanceMonitor()
        mon.record_result(True)
        mon.record_result(True)
        mon.record_result(False)
        snap = mon.snapshot()
        assert snap["success_rate"] == pytest.approx(2 / 3)

    def test_snapshot_recent_alerts_capped(self) -> None:
        mon = PerformanceMonitor(max_merge_queue_depth=1)
        for i in range(15):
            mon.check_merge_queue(i + 2)
        snap = mon.snapshot()
        assert len(snap["recent_alerts"]) == 10  # Last 10


class TestReset:
    """Tests for the reset method."""

    def test_reset_clears_all(self) -> None:
        mon = PerformanceMonitor(max_merge_queue_depth=1)
        mon.check_merge_queue(5)
        mon.record_result(True)
        mon.check_all(iteration_seconds=1.0)
        mon.reset()
        snap = mon.snapshot()
        assert snap["total_checks"] == 0
        assert snap["total_alerts"] == 0
        assert snap["succeeded"] == 0
        assert snap["failed"] == 0
        assert snap["recent_alerts"] == []


class TestThreadSafety:
    """Tests for thread-safe operation."""

    def test_concurrent_checks(self) -> None:
        mon = PerformanceMonitor(max_merge_queue_depth=1, max_iteration_seconds=1.0)
        errors: list[Exception] = []

        def worker() -> None:
            try:
                for _ in range(50):
                    mon.check_merge_queue(5)
                    mon.check_iteration(5.0)
                    mon.record_result(True)
                    mon.snapshot()
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []
        snap = mon.snapshot()
        assert snap["total_alerts"] == 400  # 4 threads × 50 × 2 checks each
        assert snap["succeeded"] == 200  # 4 threads × 50


class TestSingleton:
    """Tests for module-level singleton management."""

    def test_get_returns_monitor(self) -> None:
        reset_performance_monitor()
        mon = get_performance_monitor()
        assert isinstance(mon, PerformanceMonitor)

    def test_get_returns_same_instance(self) -> None:
        reset_performance_monitor()
        a = get_performance_monitor()
        b = get_performance_monitor()
        assert a is b

    def test_reset_clears_singleton(self) -> None:
        reset_performance_monitor()
        a = get_performance_monitor()
        reset_performance_monitor()
        b = get_performance_monitor()
        assert a is not b


class TestConfigIntegration:
    """Tests for config-driven initialization."""

    def test_default_thresholds(self) -> None:
        reset_performance_monitor()
        mon = get_performance_monitor()
        snap = mon.snapshot()
        assert snap["thresholds"]["max_merge_queue_depth"] == 5
        assert snap["thresholds"]["max_lock_wait_seconds"] == 30.0
        assert snap["thresholds"]["max_iteration_seconds"] == 30.0
        assert snap["thresholds"]["min_memory_mb"] == 256.0
        assert snap["thresholds"]["min_success_rate"] == 0.5
