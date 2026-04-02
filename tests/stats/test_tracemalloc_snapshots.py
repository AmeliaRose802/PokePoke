"""Tests for pokepoke.stats.tracemalloc_snapshots module."""

import pytest

from pokepoke.stats import tracemalloc_snapshots


@pytest.fixture(autouse=True)
def _cleanup_tracemalloc():
    """Ensure tracemalloc is stopped between tests."""
    yield
    tracemalloc_snapshots.stop()
    # Reset internal state
    tracemalloc_snapshots._started = False
    tracemalloc_snapshots._previous_snapshot = None


class TestStart:
    """Tests for start()."""

    def test_start_enables_tracking(self) -> None:
        tracemalloc_snapshots.start()
        assert tracemalloc_snapshots.is_started() is True

    def test_start_is_idempotent(self) -> None:
        tracemalloc_snapshots.start()
        tracemalloc_snapshots.start()  # should not raise
        assert tracemalloc_snapshots.is_started() is True

    def test_is_started_false_before_start(self) -> None:
        assert tracemalloc_snapshots.is_started() is False


class TestSnapshotAndCompare:
    """Tests for snapshot_and_compare()."""

    def test_returns_empty_before_start(self) -> None:
        assert tracemalloc_snapshots.snapshot_and_compare() == []

    def test_returns_list_after_start(self) -> None:
        tracemalloc_snapshots.start()
        # Allocate some memory to ensure differences
        _data = [bytearray(1024) for _ in range(100)]
        result = tracemalloc_snapshots.snapshot_and_compare()
        assert isinstance(result, list)
        # Result entries have expected keys
        for entry in result:
            assert "file" in entry
            assert "line" in entry
            assert "size_diff_kb" in entry
            assert "size_kb" in entry

    def test_consecutive_calls_compare_to_previous(self) -> None:
        tracemalloc_snapshots.start()
        # First comparison: baseline
        tracemalloc_snapshots.snapshot_and_compare()
        # Second comparison: should compare against previous snapshot
        result = tracemalloc_snapshots.snapshot_and_compare()
        assert isinstance(result, list)

    def test_top_n_limits_results(self) -> None:
        tracemalloc_snapshots.start()
        _data = [bytearray(1024) for _ in range(100)]
        result = tracemalloc_snapshots.snapshot_and_compare(top_n=2)
        assert len(result) <= 2


class TestStop:
    """Tests for stop()."""

    def test_stop_disables_tracking(self) -> None:
        tracemalloc_snapshots.start()
        tracemalloc_snapshots.stop()
        assert tracemalloc_snapshots.is_started() is False

    def test_stop_is_idempotent(self) -> None:
        tracemalloc_snapshots.stop()  # not started — should not raise
        assert tracemalloc_snapshots.is_started() is False

    def test_snapshot_returns_empty_after_stop(self) -> None:
        tracemalloc_snapshots.start()
        tracemalloc_snapshots.stop()
        assert tracemalloc_snapshots.snapshot_and_compare() == []
