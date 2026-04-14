"""Test that the parallel loop doesn't freeze when futures are in a hung state.

This test validates the fix for PokePoke-82v1j: orchestrator main loop freeze bug.
The issue was that concurrent.futures.wait() could hang indefinitely even with a
timeout when futures were in a bad state (deadlocked threads, zombie subprocesses).

The fix removes the blocking wait() call and relies solely on non-blocking .done()
polling, which cannot hang.
"""
import concurrent.futures
import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from pokepoke.agents.parallel_worker_pool import collect_done_futures
from pokepoke.types import WorkItemResult
from pokepoke.types_beads import BeadsWorkItem


def create_test_item(item_id: str = "test-1") -> BeadsWorkItem:
    """Create a test beads work item."""
    return BeadsWorkItem(
        id=item_id,
        title="Test Item",
        status="ready",
        priority=1,
        issue_type="task"
    )


def test_collect_done_futures_no_hang_on_stalled_futures():
    """Test that collect_done_futures doesn't hang when futures are stalled.

    Uses mock futures to avoid creating real blocking threads.
    """
    # Mock a hung future (not done)
    hung_future = MagicMock(spec=concurrent.futures.Future)
    hung_future.done.return_value = False

    # Mock a completed future
    completed_future = MagicMock(spec=concurrent.futures.Future)
    completed_future.done.return_value = True
    completed_future.result.return_value = WorkItemResult(success=True, request_count=1)

    futures = {
        hung_future: create_test_item("hung-1"),
        completed_future: create_test_item("completed-1"),
    }
    failed_claim_ids: set[str] = set()

    start_time = time.time()
    total_requests, any_success, success_count, _failure_count = collect_done_futures(
        futures=futures,
        failed_claim_ids=failed_claim_ids,
        total_requests=0,
        session_stats=MagicMock(),
        run_logger=MagicMock(),
        record_fn=MagicMock(),
        lock=None,
        future_start_times=None,
    )
    elapsed = time.time() - start_time

    assert elapsed < 1.0, f"collect_done_futures hung for {elapsed}s (should be <1s)"
    assert success_count == 1, "Should collect the 1 completed future"
    assert any_success is True, "Should detect success"
    assert total_requests == 1, "Should count request from completed future"
    assert len(futures) == 1, "Hung future should remain in dict"
    assert hung_future in futures, "Hung future should still be tracked"


def test_collect_done_futures_with_threading_lock():
    """Test that collect_done_futures works correctly with a lock (parallel mode)."""
    fut1 = MagicMock(spec=concurrent.futures.Future)
    fut1.done.return_value = True
    fut1.result.return_value = WorkItemResult(success=True, request_count=1)

    fut2 = MagicMock(spec=concurrent.futures.Future)
    fut2.done.return_value = True
    fut2.result.return_value = WorkItemResult(success=True, request_count=1)

    futures = {
        fut1: create_test_item("item-1"),
        fut2: create_test_item("item-2"),
    }
    lock = threading.Lock()

    start_time = time.time()
    _total_requests, _any_success, success_count, _failure_count = collect_done_futures(
        futures=futures,
        failed_claim_ids=set(),
        total_requests=0,
        session_stats=MagicMock(),
        run_logger=MagicMock(),
        record_fn=MagicMock(),
        lock=lock,
        future_start_times=None,
    )
    elapsed = time.time() - start_time

    assert elapsed < 1.0, f"collect_done_futures with lock hung for {elapsed}s"
    assert success_count == 2, "Should collect both completed futures"
    assert len(futures) == 0, "All futures should be removed from dict"


def test_collect_done_futures_no_wait_call():
    """Verify that collect_done_futures doesn't call concurrent.futures.wait()."""
    fut = MagicMock(spec=concurrent.futures.Future)
    fut.done.return_value = True
    fut.result.return_value = WorkItemResult(success=True, request_count=1)

    futures = {fut: create_test_item("item-1")}

    with patch('concurrent.futures.wait', side_effect=AssertionError("wait() should never be called")) as mock_wait:
        collect_done_futures(
            futures=futures,
            failed_claim_ids=set(),
            total_requests=0,
            session_stats=MagicMock(),
            run_logger=MagicMock(),
            record_fn=MagicMock(),
            lock=None,
            future_start_times=None,
        )

        mock_wait.assert_not_called()


def test_collect_done_futures_empty_batch_on_no_completions():
    """Test that collect_done_futures returns empty batch if no futures are done."""
    fut = MagicMock(spec=concurrent.futures.Future)
    fut.done.return_value = False

    futures = {fut: create_test_item("slow-1")}

    start_time = time.time()
    total_requests, any_success, success_count, failure_count = collect_done_futures(
        futures=futures,
        failed_claim_ids=set(),
        total_requests=0,
        session_stats=MagicMock(),
        run_logger=MagicMock(),
        record_fn=MagicMock(),
        lock=None,
        future_start_times=None,
    )
    elapsed = time.time() - start_time

    assert elapsed < 0.5, f"Should return immediately, took {elapsed}s"
    assert success_count == 0, "No futures should be collected"
    assert failure_count == 0, "No failures yet"
    assert any_success is False, "No successes yet"
    assert total_requests == 0, "No requests counted yet"
    assert len(futures) == 1, "Future should still be in dict"


def test_multiple_polling_cycles_collect_progressively():
    """Test that polling multiple times eventually collects all completed futures."""
    fut1 = MagicMock(spec=concurrent.futures.Future)
    fut1.done.return_value = True
    fut1.result.return_value = WorkItemResult(success=True, request_count=1)

    fut2 = MagicMock(spec=concurrent.futures.Future)
    fut2.done.return_value = False  # Not done yet

    fut3 = MagicMock(spec=concurrent.futures.Future)
    fut3.done.return_value = False  # Not done yet

    futures = {
        fut1: create_test_item("item-1"),
        fut2: create_test_item("item-2"),
        fut3: create_test_item("item-3"),
    }

    collected_total = 0

    # Poll 1: Should get fut1 (done)
    _, _, success_count, _ = collect_done_futures(
        futures, set(), 0, MagicMock(), MagicMock(), MagicMock(), None, None)
    collected_total += success_count
    assert success_count == 1, "Should collect fut1"

    # fut2 becomes done
    fut2.done.return_value = True
    fut2.result.return_value = WorkItemResult(success=True, request_count=1)
    _, _, success_count, _ = collect_done_futures(
        futures, set(), 0, MagicMock(), MagicMock(), MagicMock(), None, None)
    collected_total += success_count

    # fut3 becomes done
    fut3.done.return_value = True
    fut3.result.return_value = WorkItemResult(success=True, request_count=1)
    _, _, success_count, _ = collect_done_futures(
        futures, set(), 0, MagicMock(), MagicMock(), MagicMock(), None, None)
    collected_total += success_count

    # Eventually all 3 futures should be collected
    assert collected_total == 3, f"Should collect all 3 futures, got {collected_total}"
    assert len(futures) == 0, "All futures should be removed from dict"


def test_collect_done_futures_with_start_times_tracking():
    """Test that collect_done_futures works with future_start_times tracking."""
    fut1 = MagicMock(spec=concurrent.futures.Future)
    fut1.done.return_value = True
    fut1.result.return_value = WorkItemResult(success=True, request_count=1)

    fut2 = MagicMock(spec=concurrent.futures.Future)
    fut2.done.return_value = True
    fut2.result.return_value = WorkItemResult(success=True, request_count=1)

    futures = {
        fut1: create_test_item("item-1"),
        fut2: create_test_item("item-2"),
    }

    start_time = time.time()
    future_start_times = {
        fut1: start_time,
        fut2: start_time,
    }

    _total, _any_success, success_count, _failures = collect_done_futures(
        futures=futures,
        failed_claim_ids=set(),
        total_requests=0,
        session_stats=MagicMock(),
        run_logger=MagicMock(),
        record_fn=MagicMock(),
        lock=None,
        future_start_times=future_start_times,
    )

    assert success_count == 2, "Should collect both futures"
    assert len(futures) == 0, "Futures removed from dict"
    assert len(future_start_times) == 0, "Start times cleaned up"


def test_collect_done_futures_updates_failed_claim_ids():
    """Test that collect_done_futures correctly updates failed_claim_ids."""
    fut_success = MagicMock(spec=concurrent.futures.Future)
    fut_success.done.return_value = True
    fut_success.result.return_value = WorkItemResult(success=True, request_count=1)

    fut_failed = MagicMock(spec=concurrent.futures.Future)
    fut_failed.done.return_value = True
    fut_failed.result.return_value = WorkItemResult(success=False, request_count=0)

    futures = {
        fut_success: create_test_item("success-1"),
        fut_failed: create_test_item("failed-1"),
    }

    failed_claim_ids: set[str] = set()

    collect_done_futures(
        futures=futures,
        failed_claim_ids=failed_claim_ids,
        total_requests=0,
        session_stats=MagicMock(),
        run_logger=MagicMock(),
        record_fn=MagicMock(),
        lock=None,
        future_start_times=None,
    )

    assert "failed-1" in failed_claim_ids, "Failed claim should be blacklisted"
    assert "success-1" not in failed_claim_ids, "Success should not be blacklisted"


def test_collect_done_futures_with_exception():
    """Test that collect_done_futures handles exceptions in futures correctly."""
    fut = MagicMock(spec=concurrent.futures.Future)
    fut.done.return_value = True
    fut.result.side_effect = RuntimeError("Simulated agent failure")

    futures = {fut: create_test_item("exception-1")}
    failed_claim_ids: set[str] = set()
    run_logger = MagicMock()

    _total, _any_success, success_count, failure_count = collect_done_futures(
        futures=futures,
        failed_claim_ids=failed_claim_ids,
        total_requests=0,
        session_stats=MagicMock(),
        run_logger=run_logger,
        record_fn=MagicMock(),
        lock=None,
        future_start_times=None,
    )

    assert success_count == 0, "Exception should not count as success"
    assert failure_count == 1, "Exception should count as failure"
    assert "exception-1" not in failed_claim_ids, "Exception should not blacklist"
    assert run_logger.log_orchestrator.called, "Should log error"


def test_collect_done_futures_record_fn_exception_handling():
    """Test that collect_done_futures handles exceptions in record_fn gracefully."""
    fut = MagicMock(spec=concurrent.futures.Future)
    fut.done.return_value = True
    fut.result.return_value = WorkItemResult(success=True, request_count=1)

    futures = {fut: create_test_item("item-1")}

    def failing_record_fn(*args, **kwargs):
        raise ValueError("Simulated record failure")

    run_logger = MagicMock()

    _total, _any_success, success_count, _failures = collect_done_futures(
        futures=futures,
        failed_claim_ids=set(),
        total_requests=0,
        session_stats=MagicMock(),
        run_logger=run_logger,
        record_fn=failing_record_fn,
        lock=None,
        future_start_times=None,
    )

    assert len(futures) == 0, "Future should be removed even if record_fn fails"
    assert success_count == 1, "Should still count as success"
    assert run_logger.log_orchestrator.called, "Should log record error"


def test_collect_done_futures_with_lock_and_failed_claim():
    """Test that collect_done_futures correctly handles failed_claim_ids with lock."""
    fut_success = MagicMock(spec=concurrent.futures.Future)
    fut_success.done.return_value = True
    fut_success.result.return_value = WorkItemResult(success=True, request_count=5)

    fut_failed_claim = MagicMock(spec=concurrent.futures.Future)
    fut_failed_claim.done.return_value = True
    fut_failed_claim.result.return_value = WorkItemResult(success=False, request_count=0)

    fut_failed_exception = MagicMock(spec=concurrent.futures.Future)
    fut_failed_exception.done.return_value = True
    fut_failed_exception.result.return_value = WorkItemResult(success=False, request_count=1)

    futures = {
        fut_success: create_test_item("success-1"),
        fut_failed_claim: create_test_item("failed-claim-1"),
        fut_failed_exception: create_test_item("failed-exception-1"),
    }

    failed_claim_ids: set[str] = set()
    lock = threading.Lock()
    failed_claim_ids.add("success-1")  # Will be removed on success

    total_req, _any, _succ, _fail = collect_done_futures(
        futures=futures,
        failed_claim_ids=failed_claim_ids,
        total_requests=0,
        session_stats=MagicMock(),
        run_logger=MagicMock(),
        record_fn=MagicMock(),
        lock=lock,
        future_start_times=None,
    )

    assert "success-1" not in failed_claim_ids, "Success should remove from failed list"
    assert "failed-claim-1" in failed_claim_ids, "Failed claim should be added"
    assert "failed-exception-1" not in failed_claim_ids, "Failed with requests not added"
    assert total_req == 6, "Should count all requests (5 + 0 + 1)"


def test_collect_done_futures_empty_futures_dict():
    """Test that collect_done_futures handles empty futures dict gracefully."""
    futures: dict = {}
    failed_claim_ids: set[str] = set()

    _total, any_success, success_count, failure_count = collect_done_futures(
        futures=futures,
        failed_claim_ids=failed_claim_ids,
        total_requests=10,
        session_stats=MagicMock(),
        run_logger=MagicMock(),
        record_fn=MagicMock(),
        lock=None,
        future_start_times=None,
    )

    # Should return immediately with no changes
    assert _total == 10, "Should preserve total_requests"
    assert any_success is False, "No futures to collect"
    assert success_count == 0, "No successes"
    assert failure_count == 0, "No failures"
    assert len(futures) == 0, "Dict should remain empty"


def test_collect_done_futures_logs_lifecycle_when_futures_collected():
    """Test that collect_done_futures logs agent lifecycle when futures are collected."""
    fut = MagicMock(spec=concurrent.futures.Future)
    fut.done.return_value = True
    fut.result.return_value = WorkItemResult(success=True, request_count=1)

    futures = {fut: create_test_item("item-1")}
    run_logger = MagicMock()

    collect_done_futures(
        futures=futures,
        failed_claim_ids=set(),
        total_requests=0,
        session_stats=MagicMock(),
        run_logger=run_logger,
        record_fn=MagicMock(),
        lock=None,
        future_start_times=None,
    )

    assert run_logger.log_orchestrator.called, "Should log lifecycle"
    log_args = run_logger.log_orchestrator.call_args_list
    assert any("collected" in str(args) for args in log_args), "Should mention collected agents"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
