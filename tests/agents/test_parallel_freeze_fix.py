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
    """Test that collect_done_futures doesn't hang when futures are stalled."""
    # Create a future that will never complete (simulates hung agent)
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=2)

    # Create a future that blocks forever (simulating deadlock)
    def hung_task():
        event = threading.Event()
        event.wait()  # Never set, will block forever
        return WorkItemResult(success=True, request_count=1)

    hung_future = executor.submit(hung_task)

    # Create a completed future for comparison
    def quick_task():
        return WorkItemResult(success=True, request_count=1)

    completed_future = executor.submit(quick_task)
    time.sleep(0.1)  # Let completed future finish

    # Setup test data
    futures = {
        hung_future: create_test_item("hung-1"),
        completed_future: create_test_item("completed-1"),
    }
    failed_claim_ids: set[str] = set()
    session_stats = MagicMock()
    run_logger = MagicMock()
    record_fn = MagicMock()

    # CRITICAL: This call must not hang (it should complete in milliseconds)
    start_time = time.time()
    total_requests, any_success, success_count, _failure_count = collect_done_futures(
        futures=futures,
        failed_claim_ids=failed_claim_ids,
        total_requests=0,
        session_stats=session_stats,
        run_logger=run_logger,
        record_fn=record_fn,
        lock=None,
        future_start_times=None,
    )
    elapsed = time.time() - start_time

    # The call should complete almost instantly (well under 1 second)
    # If it takes more than 1 second, the fix didn't work
    assert elapsed < 1.0, f"collect_done_futures hung for {elapsed}s (should be <1s)"

    # Should have collected only the completed future
    assert success_count == 1, "Should collect the 1 completed future"
    assert any_success is True, "Should detect success"
    assert total_requests == 1, "Should count request from completed future"

    # The hung future should still be in the dict (not collected)
    assert len(futures) == 1, "Hung future should remain in dict"
    assert hung_future in futures, "Hung future should still be tracked"

    # Cleanup
    executor.shutdown(wait=False, cancel_futures=True)


def test_collect_done_futures_with_threading_lock():
    """Test that collect_done_futures works correctly with a lock (parallel mode)."""
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=2)

    def quick_task():
        return WorkItemResult(success=True, request_count=1)

    fut1 = executor.submit(quick_task)
    fut2 = executor.submit(quick_task)
    time.sleep(0.1)  # Let futures complete

    futures = {
        fut1: create_test_item("item-1"),
        fut2: create_test_item("item-2"),
    }
    failed_claim_ids: set[str] = set()
    lock = threading.Lock()
    session_stats = MagicMock()
    run_logger = MagicMock()
    record_fn = MagicMock()

    start_time = time.time()
    _total_requests, _any_success, success_count, _failure_count = collect_done_futures(
        futures=futures,
        failed_claim_ids=failed_claim_ids,
        total_requests=0,
        session_stats=session_stats,
        run_logger=run_logger,
        record_fn=record_fn,
        lock=lock,
        future_start_times=None,
    )
    elapsed = time.time() - start_time

    assert elapsed < 1.0, f"collect_done_futures with lock hung for {elapsed}s"
    assert success_count == 2, "Should collect both completed futures"
    assert len(futures) == 0, "All futures should be removed from dict"

    executor.shutdown(wait=False)


def test_collect_done_futures_no_wait_call():
    """Verify that collect_done_futures doesn't call concurrent.futures.wait()."""
    # This test ensures the fix stays in place - we should NEVER call wait()
    # because it can hang indefinitely even with a timeout.

    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)

    def quick_task():
        return WorkItemResult(success=True, request_count=1)

    fut = executor.submit(quick_task)
    time.sleep(0.1)

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

        # Verify wait() was never called
        mock_wait.assert_not_called()

    executor.shutdown(wait=False)


def test_collect_done_futures_empty_batch_on_no_completions():
    """Test that collect_done_futures returns empty batch if no futures are done."""
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)

    # Create a future that won't complete for a while
    def slow_task():
        time.sleep(10)
        return WorkItemResult(success=True, request_count=1)

    fut = executor.submit(slow_task)

    futures = {fut: create_test_item("slow-1")}

    # Call immediately (future won't be done yet)
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

    # Should return immediately (not wait for the future)
    assert elapsed < 0.5, f"Should return immediately, took {elapsed}s"

    # Should return empty batch
    assert success_count == 0, "No futures should be collected"
    assert failure_count == 0, "No failures yet"
    assert any_success is False, "No successes yet"
    assert total_requests == 0, "No requests counted yet"

    # Future should still be tracked
    assert len(futures) == 1, "Future should still be in dict"

    executor.shutdown(wait=False, cancel_futures=True)


def test_multiple_polling_cycles_collect_progressively():
    """Test that polling multiple times eventually collects all completed futures."""
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=3)

    # Create futures that complete at different times
    def delayed_task(delay: float):
        time.sleep(delay)
        return WorkItemResult(success=True, request_count=1)

    fut1 = executor.submit(delayed_task, 0.0)  # Immediate
    fut2 = executor.submit(delayed_task, 0.1)  # 100ms
    fut3 = executor.submit(delayed_task, 0.2)  # 200ms

    futures = {
        fut1: create_test_item("item-1"),
        fut2: create_test_item("item-2"),
        fut3: create_test_item("item-3"),
    }

    collected_total = 0

    # Poll 1: Should get fut1 (immediate completion)
    time.sleep(0.05)
    _, _, success_count, _ = collect_done_futures(
        futures, set(), 0, MagicMock(), MagicMock(), MagicMock(), None, None)
    collected_total += success_count
    assert success_count >= 1, "Should collect at least fut1"

    # Poll 2: Should get fut2 (if not already collected)
    time.sleep(0.1)
    _, _, success_count, _ = collect_done_futures(
        futures, set(), 0, MagicMock(), MagicMock(), MagicMock(), None, None)
    collected_total += success_count

    # Poll 3: Should get fut3 (if not already collected)
    time.sleep(0.1)
    _, _, success_count, _ = collect_done_futures(
        futures, set(), 0, MagicMock(), MagicMock(), MagicMock(), None, None)
    collected_total += success_count

    # Eventually all 3 futures should be collected
    assert collected_total == 3, f"Should collect all 3 futures, got {collected_total}"
    assert len(futures) == 0, "All futures should be removed from dict"

    executor.shutdown(wait=False)


def test_collect_done_futures_with_start_times_tracking():
    """Test that collect_done_futures works with future_start_times tracking."""
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=2)

    def quick_task():
        return WorkItemResult(success=True, request_count=1)

    fut1 = executor.submit(quick_task)
    fut2 = executor.submit(quick_task)
    time.sleep(0.1)

    futures = {
        fut1: create_test_item("item-1"),
        fut2: create_test_item("item-2"),
    }

    # Track start times
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

    executor.shutdown(wait=False)


def test_collect_done_futures_updates_failed_claim_ids():
    """Test that collect_done_futures correctly updates failed_claim_ids."""
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=2)

    def success_task():
        return WorkItemResult(success=True, request_count=1)

    def failed_claim_task():
        return WorkItemResult(success=False, request_count=0)  # Failed claim

    fut_success = executor.submit(success_task)
    fut_failed = executor.submit(failed_claim_task)
    time.sleep(0.1)

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

    # Failed claim should be added to failed_claim_ids
    assert "failed-1" in failed_claim_ids, "Failed claim should be blacklisted"
    assert "success-1" not in failed_claim_ids, "Success should not be blacklisted"

    executor.shutdown(wait=False)


def test_collect_done_futures_with_exception():
    """Test that collect_done_futures handles exceptions in futures correctly."""
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)

    def raising_task():
        raise RuntimeError("Simulated agent failure")

    fut = executor.submit(raising_task)
    time.sleep(0.1)

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

    # Exception should be treated as failure
    assert success_count == 0, "Exception should not count as success"
    assert failure_count == 1, "Exception should count as failure"
    # Exception should NOT add to failed_claim_ids (not a claim failure)
    assert "exception-1" not in failed_claim_ids, "Exception should not blacklist"
    # Should log the error
    assert run_logger.log_orchestrator.called, "Should log error"

    executor.shutdown(wait=False)


def test_collect_done_futures_record_fn_exception_handling():
    """Test that collect_done_futures handles exceptions in record_fn gracefully."""
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)

    def success_task():
        return WorkItemResult(success=True, request_count=1)

    fut = executor.submit(success_task)
    time.sleep(0.1)

    futures = {fut: create_test_item("item-1")}

    # Create a record_fn that raises
    def failing_record_fn(*args, **kwargs):
        raise ValueError("Simulated record failure")

    run_logger = MagicMock()

    # Should not propagate the exception
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

    # Future should still be collected despite record_fn failure
    assert len(futures) == 0, "Future should be removed even if record_fn fails"
    assert success_count == 1, "Should still count as success"
    # Should log the record error
    assert run_logger.log_orchestrator.called, "Should log record error"

    executor.shutdown(wait=False)


def test_collect_done_futures_with_lock_and_failed_claim():
    """Test that collect_done_futures correctly handles failed_claim_ids with lock."""
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=2)

    def success_with_requests():
        return WorkItemResult(success=True, request_count=5)

    def failed_claim():
        return WorkItemResult(success=False, request_count=0)  # Claim failed

    def failed_with_exception():
        return WorkItemResult(success=False, request_count=1)  # Failed but had requests

    fut_success = executor.submit(success_with_requests)
    fut_failed_claim = executor.submit(failed_claim)
    fut_failed_exception = executor.submit(failed_with_exception)
    time.sleep(0.1)

    futures = {
        fut_success: create_test_item("success-1"),
        fut_failed_claim: create_test_item("failed-claim-1"),
        fut_failed_exception: create_test_item("failed-exception-1"),
    }

    failed_claim_ids: set[str] = set()
    lock = threading.Lock()

    # Add one item to failed list beforehand to test discard path
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

    # Check failed_claim_ids updated correctly
    assert "success-1" not in failed_claim_ids, "Success should remove from failed list"
    assert "failed-claim-1" in failed_claim_ids, "Failed claim should be added"
    assert "failed-exception-1" not in failed_claim_ids, "Failed with requests not added"

    # Check request counting
    assert total_req == 6, "Should count all requests (5 + 0 + 1)"

    executor.shutdown(wait=False)


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
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)

    def quick_task():
        return WorkItemResult(success=True, request_count=1)

    fut = executor.submit(quick_task)
    time.sleep(0.1)

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

    # Should log agent lifecycle message when futures are collected
    assert run_logger.log_orchestrator.called, "Should log lifecycle"
    # Check the log message contains "collected"
    log_args = run_logger.log_orchestrator.call_args_list
    assert any("collected" in str(args) for args in log_args), "Should mention collected agents"

    executor.shutdown(wait=False)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
