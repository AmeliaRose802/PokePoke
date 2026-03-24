"""Tests for pokepoke.worktrees.lock_contention module."""

import pytest

from pokepoke.worktrees.lock_contention import (
    _HISTOGRAM_BUCKETS,
    LockContentionTracker,
    _contention_tracker,
    get_lock_contention_stats,
)


class TestLockContentionTracker:
    """Tests for LockContentionTracker standalone logic."""

    def test_record_acquisition(self) -> None:
        tracker = LockContentionTracker()
        tracker.record_acquisition("test-lock", 0.5)
        snap = tracker.snapshot()
        assert snap["test-lock"]["acquired"] == 1
        assert snap["test-lock"]["total_wait"] == pytest.approx(0.5)
        assert snap["test-lock"]["max_wait"] == pytest.approx(0.5)
        assert snap["test-lock"]["timeouts"] == 0

    def test_record_timeout(self) -> None:
        tracker = LockContentionTracker()
        tracker.record_timeout("test-lock", 10.0)
        snap = tracker.snapshot()
        assert snap["test-lock"]["timeouts"] == 1
        assert snap["test-lock"]["acquired"] == 0
        assert snap["test-lock"]["total_wait"] == pytest.approx(10.0)

    def test_record_stale_clearance(self) -> None:
        tracker = LockContentionTracker()
        tracker.record_stale_clearance("old-lock")
        tracker.record_stale_clearance("old-lock")
        snap = tracker.snapshot()
        assert snap["old-lock"]["stale_cleared"] == 2

    def test_histogram_buckets(self) -> None:
        tracker = LockContentionTracker()
        tracker.record_acquisition("h", 0.005)  # ≤ 0.01
        tracker.record_acquisition("h", 0.03)   # ≤ 0.05
        tracker.record_acquisition("h", 200.0)  # overflow → last bucket
        snap = tracker.snapshot()
        assert snap["h"]["histogram"]["0.01"] == 1
        assert snap["h"]["histogram"]["0.05"] == 1
        assert snap["h"]["histogram"][str(_HISTOGRAM_BUCKETS[-1])] >= 1

    def test_max_wait_updates(self) -> None:
        tracker = LockContentionTracker()
        tracker.record_acquisition("m", 1.0)
        tracker.record_acquisition("m", 5.0)
        tracker.record_acquisition("m", 2.0)
        assert tracker.snapshot()["m"]["max_wait"] == pytest.approx(5.0)

    def test_snapshot_returns_deep_copy(self) -> None:
        tracker = LockContentionTracker()
        tracker.record_acquisition("copy", 0.1)
        snap = tracker.snapshot()
        snap["copy"]["acquired"] = 999
        assert tracker.snapshot()["copy"]["acquired"] == 1

    def test_reset_clears_stats(self) -> None:
        tracker = LockContentionTracker()
        tracker.record_acquisition("r", 0.1)
        tracker.reset()
        assert tracker.snapshot() == {}

    def test_multiple_lock_names_independent(self) -> None:
        tracker = LockContentionTracker()
        tracker.record_acquisition("a", 1.0)
        tracker.record_timeout("b", 2.0)
        snap = tracker.snapshot()
        assert snap["a"]["acquired"] == 1
        assert snap["a"]["timeouts"] == 0
        assert snap["b"]["timeouts"] == 1
        assert snap["b"]["acquired"] == 0

    def test_timeout_updates_max_wait(self) -> None:
        tracker = LockContentionTracker()
        tracker.record_timeout("tw", 3.0)
        tracker.record_timeout("tw", 7.0)
        assert tracker.snapshot()["tw"]["max_wait"] == pytest.approx(7.0)

    def test_histogram_all_buckets_covered(self) -> None:
        tracker = LockContentionTracker()
        for b in _HISTOGRAM_BUCKETS:
            tracker.record_acquisition("full", b)
        snap = tracker.snapshot()
        for b in _HISTOGRAM_BUCKETS:
            assert snap["full"]["histogram"][str(b)] >= 1


class TestGetLockContentionStats:
    """Tests for the module-level get_lock_contention_stats function."""

    def test_returns_dict(self) -> None:
        _contention_tracker.reset()
        result = get_lock_contention_stats()
        assert isinstance(result, dict)

    def test_reflects_global_tracker(self) -> None:
        _contention_tracker.reset()
        _contention_tracker.record_acquisition("global-test", 0.42)
        result = get_lock_contention_stats()
        assert "global-test" in result
        assert result["global-test"]["acquired"] == 1
