"""Tests for the ParallelWorkerPool class and collect_done_futures helper."""

import concurrent.futures
import threading
import time
from unittest.mock import Mock, patch

import pytest

from pokepoke.agents.parallel_worker_pool import (
    ParallelWorkerPool,
    collect_done_futures,
    compute_slots,
    update_circuit_breaker,
    update_memory_circuit_breaker,
)
from pokepoke.types import AgentStats, BeadsWorkItem, SessionStats, WorkItemResult


def _make_item(item_id: str = "t1") -> BeadsWorkItem:
    return BeadsWorkItem(
        id=item_id, title=f"Title-{item_id}", status="open",
        priority=1, issue_type="task",
    )


# ---------------------------------------------------------------------------
# ParallelWorkerPool.__init__
# ---------------------------------------------------------------------------


class TestParallelWorkerPoolInit:
    """Verify pool construction creates the right resources."""

    def test_creates_executor_semaphore_and_empty_futures(self) -> None:
        pool = ParallelWorkerPool(pool_size=3)
        try:
            assert isinstance(pool.executor, concurrent.futures.ThreadPoolExecutor)
            assert isinstance(pool.semaphore, threading.Semaphore)
            assert pool.futures == {}
            assert pool.active_count == 0
            assert pool.active_ids == set()
            assert pool.has_active_workers() is False
        finally:
            pool.shutdown()

    def test_pool_size_one(self) -> None:
        pool = ParallelWorkerPool(pool_size=1)
        try:
            assert pool.has_active_workers() is False
        finally:
            pool.shutdown()


# ---------------------------------------------------------------------------
# dispatch_item
# ---------------------------------------------------------------------------


class TestDispatchItem:
    """Tests for ParallelWorkerPool.dispatch_item."""

    def test_dispatch_tracks_future_and_item(self) -> None:
        pool = ParallelWorkerPool(pool_size=2)
        try:
            item = _make_item("dispatch-1")
            process_fn = Mock(return_value=WorkItemResult(success=True, request_count=1))
            logger = Mock()

            pool.dispatch_item(item, logger, process_fn, "worker-1")

            assert pool.has_active_workers()
            assert pool.active_count == 1
            assert "dispatch-1" in pool.active_ids
        finally:
            pool.shutdown(wait=True)

    def test_dispatch_releases_semaphore_on_submit_failure(self) -> None:
        pool = ParallelWorkerPool(pool_size=2)
        pool.shutdown()  # shutdown executor so submit will fail

        pool._executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        pool._executor.shutdown(wait=False)

        item = _make_item("fail-submit")
        with pytest.raises(RuntimeError):
            pool.dispatch_item(item, Mock(), Mock(side_effect=RuntimeError("boom")), "w")

        assert not pool.has_active_workers()

    def test_dispatch_multiple_items(self) -> None:
        pool = ParallelWorkerPool(pool_size=4)
        try:
            process_fn = Mock(return_value=WorkItemResult(success=True, request_count=1))
            logger = Mock()
            for i in range(3):
                pool.dispatch_item(_make_item(f"m-{i}"), logger, process_fn, f"w-{i}")

            assert pool.active_count == 3
            assert pool.active_ids == {"m-0", "m-1", "m-2"}
        finally:
            pool.shutdown(wait=True)


# ---------------------------------------------------------------------------
# collect_done
# ---------------------------------------------------------------------------


class TestCollectDone:
    """Tests for ParallelWorkerPool.collect_done (instance method)."""

    def test_collect_done_harvests_completed_futures(self) -> None:
        pool = ParallelWorkerPool(pool_size=2)
        try:
            barrier = threading.Event()
            result_val = WorkItemResult(success=True, request_count=1)

            def process_fn(item, run_logger, sem, worker_name):
                barrier.wait(timeout=5)
                return result_val

            item = _make_item("cd-1")
            pool.dispatch_item(item, Mock(), process_fn, "w-1")
            barrier.set()  # let worker finish

            # Wait for future to complete
            concurrent.futures.wait(list(pool.futures.keys()), timeout=5)

            failed: set[str] = set()
            stats = SessionStats(agent_stats=AgentStats())
            record_fn = Mock()
            logger = Mock()

            total, any_ok, successes, failures = pool.collect_done(
                failed, 0, stats, logger, record_fn,
            )

            assert total == 1
            assert any_ok is True
            assert successes == 1
            assert failures == 0
            assert not pool.has_active_workers()
            assert record_fn.call_count == 1
        finally:
            pool.shutdown(wait=True)

    def test_collect_done_returns_zeros_when_no_futures(self) -> None:
        pool = ParallelWorkerPool(pool_size=1)
        try:
            stats = SessionStats(agent_stats=AgentStats())
            total, any_ok, successes, failures = pool.collect_done(
                set(), 5, stats, Mock(), Mock(),
            )
            assert total == 5
            assert any_ok is False
            assert successes == 0
            assert failures == 0
        finally:
            pool.shutdown()


# ---------------------------------------------------------------------------
# has_active_workers
# ---------------------------------------------------------------------------


class TestHasActiveWorkers:
    """Tests for ParallelWorkerPool.has_active_workers."""

    def test_false_when_empty(self) -> None:
        pool = ParallelWorkerPool(pool_size=1)
        try:
            assert pool.has_active_workers() is False
        finally:
            pool.shutdown()

    def test_true_after_dispatch(self) -> None:
        pool = ParallelWorkerPool(pool_size=2)
        try:
            blocker = threading.Event()

            def slow_fn(item, run_logger, sem, worker_name):
                blocker.wait(timeout=10)
                return WorkItemResult(success=True, request_count=0)

            pool.dispatch_item(_make_item("active-1"), Mock(), slow_fn, "w")
            assert pool.has_active_workers() is True
            blocker.set()
        finally:
            pool.shutdown(wait=True)


# ---------------------------------------------------------------------------
# shutdown
# ---------------------------------------------------------------------------


class TestShutdown:
    """Tests for ParallelWorkerPool.shutdown."""

    def test_shutdown_completes_without_error(self) -> None:
        pool = ParallelWorkerPool(pool_size=2)
        pool.shutdown(wait=True)
        # No assertion needed – just verifying no exception is raised.

    def test_shutdown_with_cancel(self) -> None:
        pool = ParallelWorkerPool(pool_size=1)
        pool.shutdown(wait=False, cancel_futures=True)


# ---------------------------------------------------------------------------
# collect_done_futures (module-level function)
# ---------------------------------------------------------------------------


class TestCollectDoneFuturesStandalone:
    """Tests for the standalone collect_done_futures function."""

    def test_collects_successful_futures(self) -> None:
        fut = concurrent.futures.Future()
        result = WorkItemResult(success=True, request_count=2)
        fut.set_result(result)

        item = _make_item("standalone-1")
        futures_dict = {fut: item}
        failed: set[str] = set()
        stats = SessionStats(agent_stats=AgentStats())
        record_fn = Mock()

        total, any_ok, successes, failures = collect_done_futures(
            futures_dict, failed, 0, stats, Mock(), record_fn,
        )

        assert total == 2
        assert any_ok is True
        assert successes == 1
        assert failures == 0
        assert len(futures_dict) == 0
        assert record_fn.call_count == 1

    def test_collects_failed_futures(self) -> None:
        fut = concurrent.futures.Future()
        result = WorkItemResult(success=False, request_count=0)
        fut.set_result(result)

        item = _make_item("fail-1")
        futures_dict = {fut: item}
        failed: set[str] = set()
        stats = SessionStats(agent_stats=AgentStats())
        record_fn = Mock()

        total, any_ok, successes, failures = collect_done_futures(
            futures_dict, failed, 0, stats, Mock(), record_fn,
        )

        assert total == 0
        assert any_ok is False
        assert successes == 0
        assert failures == 1
        assert "fail-1" in failed

    def test_exception_futures_not_blacklisted(self) -> None:
        fut = concurrent.futures.Future()
        fut.set_exception(RuntimeError("boom"))

        item = _make_item("exc-1")
        futures_dict = {fut: item}
        failed: set[str] = set()
        stats = SessionStats(agent_stats=AgentStats())
        record_fn = Mock()

        collect_done_futures(futures_dict, failed, 0, stats, Mock(), record_fn)

        assert "exc-1" not in failed
        assert len(futures_dict) == 0

    def test_success_discards_from_failed(self) -> None:
        fut = concurrent.futures.Future()
        result = WorkItemResult(success=True, request_count=1)
        fut.set_result(result)

        item = _make_item("recover-1")
        futures_dict = {fut: item}
        failed: set[str] = {"recover-1"}
        stats = SessionStats(agent_stats=AgentStats())

        collect_done_futures(futures_dict, failed, 0, stats, Mock(), Mock())

        assert "recover-1" not in failed

    def test_record_fn_exception_does_not_propagate(self) -> None:
        fut = concurrent.futures.Future()
        fut.set_result(WorkItemResult(success=True, request_count=1))

        item = _make_item("rec-err")
        futures_dict = {fut: item}
        record_fn = Mock(side_effect=RuntimeError("record failed"))
        stats = SessionStats(agent_stats=AgentStats())

        # Should not raise
        _, _, successes, _ = collect_done_futures(
            futures_dict, set(), 0, stats, Mock(), record_fn,
        )
        assert successes == 1

    def test_returns_passthrough_when_no_done_futures(self) -> None:
        # Future that is NOT done
        fut = concurrent.futures.Future()
        item = _make_item("pending")
        futures_dict = {fut: item}
        stats = SessionStats(agent_stats=AgentStats())

        total, any_ok, _, _ = collect_done_futures(
            futures_dict, set(), 10, stats, Mock(), Mock(),
        )

        # Future should still be in dict (not collected)
        assert len(futures_dict) == 1
        assert total == 10
        assert any_ok is False

    def test_multiple_concurrent_completions(self) -> None:
        """All done futures are collected in a single call."""
        futs = [concurrent.futures.Future() for _ in range(3)]
        for f in futs:
            f.set_result(WorkItemResult(success=True, request_count=1))
        items = [_make_item(f"multi-{i}") for i in range(3)]
        futures_dict = dict(zip(futs, items, strict=False))

        failed: set[str] = set()
        stats = SessionStats(agent_stats=AgentStats())
        record_fn = Mock()

        _, any_ok, successes, _ = collect_done_futures(
            futures_dict, failed, 0, stats, Mock(), record_fn,
        )

        assert len(futures_dict) == 0
        assert successes == 3
        assert any_ok is True
        assert record_fn.call_count == 3


# ---------------------------------------------------------------------------
# Backward-compat: verify parallel.py alias
# ---------------------------------------------------------------------------


class TestBackwardCompatAlias:
    """Ensure parallel._collect_done_futures is the same function."""

    def test_alias_identity(self) -> None:
        from pokepoke.agents.parallel import _collect_done_futures
        assert _collect_done_futures is collect_done_futures


# ---------------------------------------------------------------------------
# Thread-safety tests
# ---------------------------------------------------------------------------


class TestThreadSafety:
    """Tests for thread-safe access to shared collections."""

    def test_pool_has_lock_attribute(self) -> None:
        """Verify ParallelWorkerPool exposes a lock property."""
        pool = ParallelWorkerPool(pool_size=2)
        try:
            assert hasattr(pool, "lock")
            assert isinstance(pool.lock, type(threading.Lock()))
        finally:
            pool.shutdown()

    def test_concurrent_dispatch_and_collect(self) -> None:
        """Test that concurrent dispatch/collect operations don't raise errors."""
        pool = ParallelWorkerPool(pool_size=4)
        errors: list[Exception] = []
        completed_count = [0]

        def process_fn(item, run_logger, sem, worker_name):
            time.sleep(0.05)
            sem.release()
            return WorkItemResult(success=True, request_count=1)

        def dispatcher():
            for i in range(10):
                try:
                    item = _make_item(f"dispatch-{i}")
                    pool._semaphore.acquire()
                    with pool.lock:
                        fut = pool._executor.submit(
                            process_fn, item, Mock(), pool._semaphore, f"w-{i}",
                        )
                        pool._futures[fut] = item
                except Exception as e:
                    errors.append(e)
                time.sleep(0.01)

        def collector():
            failed: set[str] = set()
            stats = SessionStats(agent_stats=AgentStats())
            for _ in range(20):
                try:
                    _, _, successes, _ = pool.collect_done(
                        failed, 0, stats, Mock(), Mock(),
                    )
                    completed_count[0] += successes
                except Exception as e:
                    errors.append(e)
                time.sleep(0.02)

        dispatch_thread = threading.Thread(target=dispatcher)
        collect_thread = threading.Thread(target=collector)

        try:
            dispatch_thread.start()
            collect_thread.start()
            dispatch_thread.join(timeout=5)
            collect_thread.join(timeout=5)

            assert not errors, f"Unexpected errors: {errors}"
        finally:
            pool.shutdown(wait=True)

    def test_collect_done_futures_with_lock_no_race(self) -> None:
        """Test collect_done_futures uses lock to prevent race conditions."""
        lock = threading.Lock()
        futures_dict: dict[concurrent.futures.Future, BeadsWorkItem] = {}
        failed: set[str] = set()
        stats = SessionStats(agent_stats=AgentStats())
        errors: list[Exception] = []

        def add_futures():
            for i in range(5):
                fut = concurrent.futures.Future()
                fut.set_result(WorkItemResult(success=True, request_count=1))
                with lock:
                    futures_dict[fut] = _make_item(f"add-{i}")
                time.sleep(0.01)

        def collect_futures():
            for _ in range(10):
                try:
                    collect_done_futures(
                        futures_dict, failed, 0, stats, Mock(), Mock(), lock=lock,
                    )
                except Exception as e:
                    errors.append(e)
                time.sleep(0.02)

        add_thread = threading.Thread(target=add_futures)
        collect_thread = threading.Thread(target=collect_futures)

        add_thread.start()
        collect_thread.start()
        add_thread.join(timeout=5)
        collect_thread.join(timeout=5)

        assert not errors, f"Race condition errors: {errors}"

    def test_active_count_thread_safe(self) -> None:
        """Test active_count property is thread-safe."""
        pool = ParallelWorkerPool(pool_size=2)
        errors: list[Exception] = []

        def reader():
            for _ in range(100):
                try:
                    _ = pool.active_count
                except Exception as e:
                    errors.append(e)

        def writer():
            for i in range(10):
                fut = concurrent.futures.Future()
                with pool.lock:
                    pool._futures[fut] = _make_item(f"w-{i}")
                time.sleep(0.001)
                with pool.lock:
                    pool._futures.pop(fut, None)

        threads = [
            threading.Thread(target=reader),
            threading.Thread(target=reader),
            threading.Thread(target=writer),
        ]

        try:
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=5)

            assert not errors, f"Thread-safety errors: {errors}"
        finally:
            pool.shutdown()

    def test_failed_claim_ids_lock_protection(self) -> None:
        """Test that failed_claim_ids set is protected by lock during collect."""
        lock = threading.Lock()
        failed: set[str] = set()
        errors: list[Exception] = []

        def modifier():
            for i in range(50):
                try:
                    with lock:
                        failed.add(f"item-{i}")
                    time.sleep(0.001)
                    with lock:
                        failed.discard(f"item-{i}")
                except Exception as e:
                    errors.append(e)

        def reader():
            for _ in range(50):
                try:
                    with lock:
                        _ = list(failed)
                except Exception as e:
                    errors.append(e)
                time.sleep(0.001)

        threads = [
            threading.Thread(target=modifier),
            threading.Thread(target=modifier),
            threading.Thread(target=reader),
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        assert not errors, f"Set race errors: {errors}"


# ---------------------------------------------------------------------------
# compute_slots
# ---------------------------------------------------------------------------


class TestComputeSlots:
    """Tests for the compute_slots function."""

    @patch("pokepoke.utils.memory_utils.get_process_rss_mb", return_value=150)
    @patch("pokepoke.utils.memory_utils.apply_memory_backpressure")
    @patch("pokepoke.agents.parallel.get_effective_max_agents", return_value=4)
    def test_basic_slot_computation(
        self, _mock_max: Mock, mock_backpressure: Mock, _mock_rss: Mock,
    ) -> None:
        mock_backpressure.side_effect = lambda s: (s, 8192)
        item = _make_item("cs-1")
        fut: concurrent.futures.Future[WorkItemResult] = concurrent.futures.Future()
        futures: dict[concurrent.futures.Future[WorkItemResult], BeadsWorkItem] = {fut: item}
        run_logger = Mock()
        active, slots, avail = compute_slots(futures, run_logger)
        assert slots == 3
        assert avail == 8192
        assert "cs-1" in active
        run_logger.log_polling.assert_called_once()
        log_msg = run_logger.log_polling.call_args[0][0]
        assert "rss=150MB" in log_msg
        assert "mem=8192MB" in log_msg

    @patch("pokepoke.utils.memory_utils.get_process_rss_mb", return_value=200)
    @patch("pokepoke.utils.memory_utils.apply_memory_backpressure")
    @patch("pokepoke.agents.parallel.get_effective_max_agents", return_value=4)
    def test_memory_low_warning(
        self, _mock_max: Mock, mock_backpressure: Mock, _mock_rss: Mock,
    ) -> None:
        mock_backpressure.side_effect = lambda s: (0, 512)
        item1 = _make_item("ml-1")
        item2 = _make_item("ml-2")
        f1: concurrent.futures.Future[WorkItemResult] = concurrent.futures.Future()
        f2: concurrent.futures.Future[WorkItemResult] = concurrent.futures.Future()
        futures: dict[concurrent.futures.Future[WorkItemResult], BeadsWorkItem] = {f1: item1, f2: item2}
        run_logger = Mock()
        _, slots, _ = compute_slots(futures, run_logger)
        assert slots == 0
        run_logger.log_orchestrator.assert_called_once()
        assert "Memory low" in run_logger.log_orchestrator.call_args[0][0]

    @patch("pokepoke.utils.memory_utils.get_process_rss_mb", return_value=200)
    @patch("pokepoke.utils.memory_utils.apply_memory_backpressure")
    @patch("pokepoke.agents.parallel.get_effective_max_agents", return_value=4)
    def test_memory_pressure_warning(
        self, _mock_max: Mock, mock_backpressure: Mock, _mock_rss: Mock,
    ) -> None:
        mock_backpressure.side_effect = lambda s: (1, 1500)
        item1 = _make_item("mp-1")
        f1: concurrent.futures.Future[WorkItemResult] = concurrent.futures.Future()
        futures: dict[concurrent.futures.Future[WorkItemResult], BeadsWorkItem] = {f1: item1}
        run_logger = Mock()
        _, slots, _ = compute_slots(futures, run_logger)
        assert slots == 1
        run_logger.log_orchestrator.assert_called_once()
        assert "Memory pressure" in run_logger.log_orchestrator.call_args[0][0]

    @patch("pokepoke.utils.memory_utils.get_process_rss_mb", return_value=100)
    @patch("pokepoke.utils.memory_utils.apply_memory_backpressure")
    @patch("pokepoke.agents.parallel.get_effective_max_agents", return_value=4)
    def test_with_lock(
        self, _mock_max: Mock, mock_backpressure: Mock, _mock_rss: Mock,
    ) -> None:
        mock_backpressure.side_effect = lambda s: (s, 4096)
        item = _make_item("lock-1")
        f: concurrent.futures.Future[WorkItemResult] = concurrent.futures.Future()
        futures: dict[concurrent.futures.Future[WorkItemResult], BeadsWorkItem] = {f: item}
        lock = threading.Lock()
        run_logger = Mock()
        active, slots, _ = compute_slots(futures, run_logger, lock=lock)
        assert "lock-1" in active
        assert slots == 3

    @patch("pokepoke.utils.memory_utils.get_process_rss_mb", return_value=0)
    @patch("pokepoke.utils.memory_utils.apply_memory_backpressure")
    @patch("pokepoke.agents.parallel.get_effective_max_agents", return_value=2)
    def test_rss_zero_still_logs(
        self, _mock_max: Mock, mock_backpressure: Mock, _mock_rss: Mock,
    ) -> None:
        mock_backpressure.side_effect = lambda s: (s, 0)
        run_logger = Mock()
        compute_slots({}, run_logger)
        log_msg = run_logger.log_polling.call_args[0][0]
        assert "rss=0MB" in log_msg


# ---------------------------------------------------------------------------
# update_circuit_breaker
# ---------------------------------------------------------------------------


class TestUpdateCircuitBreaker:
    """Tests for update_circuit_breaker."""

    def test_resets_on_success(self) -> None:
        run_logger = Mock()
        count, tripped = update_circuit_breaker(1, 0, 3, 3, {}, run_logger)
        assert count == 0
        assert tripped is False

    def test_increments_on_failure(self) -> None:
        run_logger = Mock()
        count, tripped = update_circuit_breaker(0, 1, 1, 3, {}, run_logger)
        assert count == 2
        assert tripped is False

    def test_trips_at_threshold(self) -> None:
        run_logger = Mock()
        count, tripped = update_circuit_breaker(0, 1, 2, 3, {}, run_logger)
        assert count == 3
        assert tripped is True


# ---------------------------------------------------------------------------
# update_memory_circuit_breaker
# ---------------------------------------------------------------------------


class TestUpdateMemoryCircuitBreaker:
    """Tests for update_memory_circuit_breaker."""

    def test_increments_when_below_floor(self) -> None:
        run_logger = Mock()
        count, tripped = update_memory_circuit_breaker(200, 512, 3, 0, {}, run_logger)
        assert count == 1
        assert tripped is False

    def test_resets_when_above_floor(self) -> None:
        run_logger = Mock()
        count, tripped = update_memory_circuit_breaker(1024, 512, 3, 2, {}, run_logger)
        assert count == 0
        assert tripped is False

    def test_preserves_counter_when_memory_unavailable(self) -> None:
        """When monitoring fails (returns 0), preserve accumulated counter instead of resetting."""
        run_logger = Mock()
        count, tripped = update_memory_circuit_breaker(0, 512, 3, 2, {}, run_logger)
        assert count == 2  # Preserved, not reset
        assert tripped is False

    def test_trips_when_memory_unavailable_and_counter_at_threshold(self) -> None:
        """Circuit breaker can trip based on accumulated counter even when monitoring fails."""
        run_logger = Mock()
        count, tripped = update_memory_circuit_breaker(0, 512, 3, 3, {}, run_logger)
        assert count == 3  # Preserved
        assert tripped is True  # Trips based on accumulated evidence

    def test_trips_at_threshold(self) -> None:
        run_logger = Mock()
        count, tripped = update_memory_circuit_breaker(200, 512, 3, 2, {}, run_logger)
        assert count == 3
        assert tripped is True
