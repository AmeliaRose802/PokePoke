"""Tests for pokepoke.perf_timing module."""

import threading
import time

import pytest

from pokepoke.perf_timing import (
    OperationTimingRegistry,
    _percentile,
    get_registry,
    reset_registry,
    timed_block,
    timed_operation,
)


class TestPercentile:
    """Tests for the _percentile helper."""

    def test_single_value(self):
        assert _percentile([5.0], 50) == 5.0

    def test_two_values_p50(self):
        result = _percentile([1.0, 3.0], 50)
        assert result == 2.0

    def test_p0_returns_min(self):
        assert _percentile([1.0, 2.0, 3.0], 0) == 1.0

    def test_p100_returns_max(self):
        assert _percentile([1.0, 2.0, 3.0], 100) == 3.0

    def test_interpolation(self):
        data = [10.0, 20.0, 30.0, 40.0, 50.0]
        # p25 should interpolate between 10 and 20 → 20.0
        assert _percentile(data, 25) == 20.0

    def test_unsorted_input(self):
        data = [50.0, 10.0, 30.0, 20.0, 40.0]
        assert _percentile(data, 50) == 30.0

    def test_empty_raises(self):
        with pytest.raises(ValueError, match="empty"):
            _percentile([], 50)


class TestOperationTimingRegistry:
    """Tests for OperationTimingRegistry."""

    def test_record_and_count(self):
        reg = OperationTimingRegistry()
        reg.record("op1", 1.0)
        reg.record("op1", 2.0)
        assert reg.count("op1") == 2

    def test_count_unknown_name(self):
        reg = OperationTimingRegistry()
        assert reg.count("nonexistent") == 0

    def test_percentile_with_data(self):
        reg = OperationTimingRegistry()
        for v in [1.0, 2.0, 3.0, 4.0, 5.0]:
            reg.record("op", v)
        assert reg.percentile("op", 50) == 3.0

    def test_percentile_no_data(self):
        reg = OperationTimingRegistry()
        assert reg.percentile("missing", 50) is None

    def test_p50_p95_p99_shortcuts(self):
        reg = OperationTimingRegistry()
        for i in range(1, 101):
            reg.record("op", float(i))
        p50 = reg.p50("op")
        p95 = reg.p95("op")
        p99 = reg.p99("op")
        assert p50 is not None
        assert p95 is not None
        assert p99 is not None
        assert p50 < p95 < p99

    def test_p50_p95_p99_no_data(self):
        reg = OperationTimingRegistry()
        assert reg.p50("x") is None
        assert reg.p95("x") is None
        assert reg.p99("x") is None

    def test_mean(self):
        reg = OperationTimingRegistry()
        reg.record("op", 2.0)
        reg.record("op", 4.0)
        assert reg.mean("op") == 3.0

    def test_mean_no_data(self):
        reg = OperationTimingRegistry()
        assert reg.mean("missing") is None

    def test_total(self):
        reg = OperationTimingRegistry()
        reg.record("op", 1.5)
        reg.record("op", 2.5)
        assert reg.total("op") == 4.0

    def test_total_no_data(self):
        reg = OperationTimingRegistry()
        assert reg.total("missing") == 0.0

    def test_names(self):
        reg = OperationTimingRegistry()
        reg.record("b_op", 1.0)
        reg.record("a_op", 2.0)
        assert reg.names() == ["a_op", "b_op"]

    def test_names_empty(self):
        reg = OperationTimingRegistry()
        assert reg.names() == []

    def test_snapshot_returns_copy(self):
        reg = OperationTimingRegistry()
        reg.record("op", 1.0)
        snap = reg.snapshot("op")
        snap.append(999.0)  # mutating the copy
        assert reg.count("op") == 1  # original unchanged

    def test_snapshot_empty(self):
        reg = OperationTimingRegistry()
        assert reg.snapshot("missing") == []

    def test_summary(self):
        reg = OperationTimingRegistry()
        for v in [1.0, 2.0, 3.0]:
            reg.record("op", v)
        s = reg.summary()
        assert "op" in s
        assert s["op"]["count"] == 3
        assert s["op"]["min"] <= s["op"]["p50"] <= s["op"]["max"]
        assert "mean" in s["op"]
        assert "total" in s["op"]
        assert "p95" in s["op"]
        assert "p99" in s["op"]

    def test_summary_empty(self):
        reg = OperationTimingRegistry()
        assert reg.summary() == {}

    def test_clear_specific_name(self):
        reg = OperationTimingRegistry()
        reg.record("op1", 1.0)
        reg.record("op2", 2.0)
        reg.clear("op1")
        assert reg.count("op1") == 0
        assert reg.count("op2") == 1

    def test_clear_all(self):
        reg = OperationTimingRegistry()
        reg.record("op1", 1.0)
        reg.record("op2", 2.0)
        reg.clear()
        assert reg.names() == []

    def test_clear_nonexistent(self):
        reg = OperationTimingRegistry()
        reg.clear("nonexistent")  # should not raise

    def test_max_samples_eviction(self):
        reg = OperationTimingRegistry(max_samples=10)
        for i in range(15):
            reg.record("op", float(i))
        # After eviction, should have fewer than 15 but more than 0
        count = reg.count("op")
        assert 0 < count <= 10

    def test_thread_safety(self):
        """Verify concurrent writes don't corrupt the registry."""
        reg = OperationTimingRegistry()
        errors: list[Exception] = []

        def writer(name: str, n: int) -> None:
            try:
                for i in range(n):
                    reg.record(name, float(i))
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=writer, args=(f"op{i}", 100))
            for i in range(8)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        for i in range(8):
            assert reg.count(f"op{i}") == 100


class TestTimedOperation:
    """Tests for the @timed_operation decorator."""

    def test_records_duration(self):
        reg = OperationTimingRegistry()

        @timed_operation("test.op", registry=reg)
        def slow_fn():
            time.sleep(0.05)
            return 42

        result = slow_fn()
        assert result == 42
        assert reg.count("test.op") == 1
        duration = reg.snapshot("test.op")[0]
        assert duration >= 0.04  # allow some timing slack

    def test_preserves_exceptions(self):
        reg = OperationTimingRegistry()

        @timed_operation("test.fail", registry=reg)
        def failing_fn():
            raise ValueError("boom")

        with pytest.raises(ValueError, match="boom"):
            failing_fn()
        # Duration still recorded even on exception
        assert reg.count("test.fail") == 1

    def test_preserves_function_metadata(self):
        reg = OperationTimingRegistry()

        @timed_operation("test.meta", registry=reg)
        def my_function():
            """My docstring."""

        assert my_function.__name__ == "my_function"
        assert my_function.__doc__ == "My docstring."

    def test_uses_global_registry_by_default(self):
        reset_registry()
        global_reg = get_registry()

        @timed_operation("test.global")
        def fn():
            return 1

        fn()
        assert global_reg.count("test.global") == 1

    def test_with_args_and_kwargs(self):
        reg = OperationTimingRegistry()

        @timed_operation("test.args", registry=reg)
        def add(a, b, extra=0):
            return a + b + extra

        assert add(1, 2, extra=3) == 6
        assert reg.count("test.args") == 1


class TestTimedBlock:
    """Tests for the timed_block context manager."""

    def test_records_duration(self):
        reg = OperationTimingRegistry()
        with timed_block("test.block", registry=reg):
            time.sleep(0.05)
        assert reg.count("test.block") == 1
        duration = reg.snapshot("test.block")[0]
        assert duration >= 0.04

    def test_records_on_exception(self):
        reg = OperationTimingRegistry()
        with pytest.raises(RuntimeError), timed_block("test.block_fail", registry=reg):
            raise RuntimeError("fail")
        assert reg.count("test.block_fail") == 1

    def test_uses_global_registry_by_default(self):
        reset_registry()
        global_reg = get_registry()
        with timed_block("test.global_block"):
            pass
        assert global_reg.count("test.global_block") == 1

    def test_nested_blocks(self):
        reg = OperationTimingRegistry()
        with timed_block("outer", registry=reg), timed_block("inner", registry=reg):
            time.sleep(0.02)
        assert reg.count("outer") == 1
        assert reg.count("inner") == 1
        outer_dur = reg.snapshot("outer")[0]
        inner_dur = reg.snapshot("inner")[0]
        assert outer_dur >= inner_dur


class TestGlobalRegistry:
    """Tests for get_registry / reset_registry singleton."""

    def test_get_registry_returns_same_instance(self):
        reset_registry()
        a = get_registry()
        b = get_registry()
        assert a is b

    def test_reset_creates_new_instance(self):
        reset_registry()
        a = get_registry()
        reset_registry()
        b = get_registry()
        assert a is not b

    def test_reset_clears_data(self):
        reset_registry()
        reg = get_registry()
        reg.record("test", 1.0)
        reset_registry()
        new_reg = get_registry()
        assert new_reg.count("test") == 0
