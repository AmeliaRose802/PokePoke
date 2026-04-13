"""Integration test combining parallel loop freeze fix with real-world scenarios."""
import time
from unittest.mock import MagicMock

import pytest

from pokepoke.agents.parallel_worker_pool import ParallelWorkerPool
from pokepoke.types import WorkItemResult
from pokepoke.types_beads import BeadsWorkItem


def create_test_item(item_id: str) -> BeadsWorkItem:
    """Create a test beads work item."""
    return BeadsWorkItem(
        id=item_id,
        title="Test Item",
        status="ready",
        priority=1,
        issue_type="task"
    )


def test_parallel_worker_pool_integration_with_freeze_fix():
    """Integration test: ParallelWorkerPool uses freeze-safe collect_done_futures."""
    pool = ParallelWorkerPool(pool_size=2)

    def quick_task(item, run_logger, sem, worker_name):
        time.sleep(0.05)
        sem.release()
        return WorkItemResult(success=True, request_count=1)

    # Dispatch two items
    item1 = create_test_item("int-1")
    item2 = create_test_item("int-2")

    pool.dispatch_item(item1, MagicMock(), quick_task, "worker-1")
    pool.dispatch_item(item2, MagicMock(), quick_task, "worker-2")

    # Wait for completion
    time.sleep(0.2)

    # Collect done futures using the freeze-safe implementation
    _total_req, _any_success, success_count, _failure_count = pool.collect_done(
        failed_claim_ids=set(),
        total_requests=0,
        session_stats=MagicMock(),
        run_logger=MagicMock(),
        record_fn=MagicMock(),
    )

    # Verify collection worked without hanging
    assert success_count == 2, "Both items should complete"
    assert pool.active_count == 0, "All futures collected"

    pool.shutdown(wait=False)


def test_parallel_worker_pool_handles_hung_futures_gracefully():
    """Integration test: Pool doesn't hang on stalled futures."""
    pool = ParallelWorkerPool(pool_size=1)

    def stalled_task(item, run_logger, sem, worker_name):
        # Never release semaphore, never complete
        import threading
        event = threading.Event()
        event.wait(timeout=60)  # Would hang for 60s if wait() was used
        sem.release()
        return WorkItemResult(success=False, request_count=0)

    item = create_test_item("hung-1")
    pool.dispatch_item(item, MagicMock(), stalled_task, "hung-worker")

    # Collect immediately (future not done yet)
    start_time = time.time()
    _total, _any, success_count, _failures = pool.collect_done(
        failed_claim_ids=set(),
        total_requests=0,
        session_stats=MagicMock(),
        run_logger=MagicMock(),
        record_fn=MagicMock(),
    )
    elapsed = time.time() - start_time

    # CRITICAL: Must complete almost immediately (not wait for hung future)
    assert elapsed < 1.0, f"collect_done hung for {elapsed}s with stalled future"
    assert success_count == 0, "Hung future not collected yet"
    assert pool.active_count == 1, "Hung future still tracked"

    pool.shutdown(wait=False, cancel_futures=True)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
