"""Tests for the ParallelWorkerPool class and collect_done_futures helper."""

import concurrent.futures
import threading
from unittest.mock import Mock

import pytest

from pokepoke.agents.parallel_worker_pool import (
    ParallelWorkerPool,
    collect_done_futures,
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
