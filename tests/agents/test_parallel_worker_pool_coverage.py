"""Additional tests for parallel_worker_pool.py to achieve 80%+ coverage.

Focuses on untested code paths:
- Helper functions without locks
- Agent health monitoring for stalled agents
- Edge cases in collect_done_futures
"""
import concurrent.futures
import threading
import time
from unittest.mock import Mock, patch

import pytest

from pokepoke.agents.parallel_worker_pool import (
    _check_agent_health,
    _check_high_conflict_active,
    _drain_orphaned_futures,
    _locked_add_to_set,
    _locked_get_skip_and_active,
    _locked_has_futures,
    _locked_pop,
    _locked_register_dispatch,
    _locked_snapshot,
    _safe_unassign,
    _update_failed_ids,
    collect_done_futures,
)
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


class TestHelperFunctionsWithoutLock:
    """Test helper functions when lock=None (no-lock code paths)."""

    def test_locked_snapshot_without_lock(self):
        """Test _locked_snapshot returns copy without lock."""
        futures = {Mock(): create_test_item("item-1")}
        keys, count = _locked_snapshot(None, futures)
        assert len(keys) == 1
        assert count == 1

    def test_locked_pop_without_lock(self):
        """Test _locked_pop removes item without lock."""
        fut = Mock()
        item = create_test_item("item-1")
        futures = {fut: item}
        result = _locked_pop(None, futures, fut)
        assert result == item
        assert len(futures) == 0

    def test_locked_has_futures_without_lock(self):
        """Test _locked_has_futures checks without lock."""
        futures = {Mock(): create_test_item()}
        assert _locked_has_futures(None, futures) is True
        assert _locked_has_futures(None, {}) is False

    def test_locked_add_to_set_without_lock(self):
        """Test _locked_add_to_set adds value without lock."""
        target: set[str] = set()
        _locked_add_to_set(None, target, "item-1")
        assert "item-1" in target

    def test_locked_get_skip_and_active_without_lock(self):
        """Test _locked_get_skip_and_active combines sets without lock."""
        failed = {"failed-1"}
        attempted = {"attempted-1"}
        active = {"active-1"}
        skip, active_snap = _locked_get_skip_and_active(None, failed, attempted, active)
        assert skip == {"failed-1", "attempted-1"}
        assert active_snap == {"active-1"}

    def test_locked_register_dispatch_without_lock(self):
        """Test _locked_register_dispatch registers future without lock."""
        futures: dict = {}
        active: set[str] = set()
        start_times: dict = {}
        fut = Mock()
        item = create_test_item("item-1")

        _locked_register_dispatch(None, futures, active, fut, item, start_times)

        assert fut in futures
        assert futures[fut] == item
        assert "item-1" in active
        assert fut in start_times

    def test_locked_register_dispatch_without_start_times(self):
        """Test _locked_register_dispatch without start times dict."""
        futures: dict = {}
        active: set[str] = set()
        fut = Mock()
        item = create_test_item("item-1")

        _locked_register_dispatch(None, futures, active, fut, item, None)

        assert fut in futures
        assert "item-1" in active

    def test_check_high_conflict_active_without_lock(self):
        """Test _check_high_conflict_active checks without lock."""
        # Items without parent_id are not high conflict
        item = create_test_item("item-1")
        futures = {Mock(): item}
        assert _check_high_conflict_active(None, futures) is False


class TestSafeUnassign:
    """Test _safe_unassign error handling."""

    @patch('pokepoke.agents.parallel.unassign_with_retry')
    def test_safe_unassign_success(self, mock_unassign):
        """Test _safe_unassign calls unassign_with_retry."""
        run_logger = Mock()
        _safe_unassign("item-1", run_logger, "test-reason")
        mock_unassign.assert_called_once_with("item-1")

    @patch('pokepoke.agents.parallel.unassign_with_retry')
    def test_safe_unassign_handles_exception(self, mock_unassign):
        """Test _safe_unassign logs error when unassign fails."""
        mock_unassign.side_effect = Exception("unassign failed")
        run_logger = Mock()

        _safe_unassign("item-1", run_logger, "test-reason")

        run_logger.log_orchestrator.assert_called_once()
        args = run_logger.log_orchestrator.call_args
        assert "Failed to unassign item-1" in args[0][0]
        assert args[1]["level"] == "WARNING"


class TestDrainOrphanedFutures:
    """Test _drain_orphaned_futures cleanup logic."""

    @patch('pokepoke.agents.parallel.unassign_with_retry')
    def test_drain_orphaned_futures_preserves_in_progress(self, mock_unassign):
        """In-progress futures are preserved — no cancel, no unassign."""
        fut = Mock()
        fut.done.return_value = False

        item = create_test_item("item-1")
        futures = {fut: item}
        run_logger = Mock()

        _drain_orphaned_futures(futures, run_logger, None)

        fut.cancel.assert_not_called()
        mock_unassign.assert_not_called()
        assert len(futures) == 0

    @patch('pokepoke.agents.parallel.unassign_with_retry')
    def test_drain_orphaned_futures_unassigns_failed(self, mock_unassign):
        """Done-but-failed futures are unassigned."""
        fut = Mock()
        fut.done.return_value = True
        fut.result.return_value = WorkItemResult(success=False, request_count=0)

        item = create_test_item("item-2")
        futures = {fut: item}
        run_logger = Mock()

        _drain_orphaned_futures(futures, run_logger, None)

        mock_unassign.assert_called_once_with("item-2")
        assert len(futures) == 0


class TestUpdateFailedIds:
    """Test _update_failed_ids logic."""

    def test_update_failed_ids_adds_on_claim_failure(self):
        """Test failed claim (success=False, request_count=0) adds to failed_ids."""
        failed: set[str] = set()
        _update_failed_ids(None, failed, "item-1", success=False, was_exception=False, request_count=0)
        assert "item-1" in failed

    def test_update_failed_ids_discards_on_success(self):
        """Test success removes item from failed_ids."""
        failed = {"item-1"}
        _update_failed_ids(None, failed, "item-1", success=True, was_exception=False, request_count=1)
        assert "item-1" not in failed

    def test_update_failed_ids_ignores_exception_failures(self):
        """Test exception failures (was_exception=True) don't add to failed_ids."""
        failed: set[str] = set()
        _update_failed_ids(None, failed, "item-1", success=False, was_exception=True, request_count=0)
        assert "item-1" not in failed


class TestAgentHealthMonitoring:
    """Test _check_agent_health for stalled agent detection."""

    def test_check_agent_health_no_stalled_agents(self):
        """Test health check when all agents are healthy."""
        futures = {}
        start_times = {}
        run_logger = Mock()

        stalled = _check_agent_health(futures, start_times, run_logger)

        assert stalled == 0
        run_logger.log_orchestrator.assert_not_called()

    def test_check_agent_health_detects_stalled_agent(self):
        """Test health check detects stalled agent after threshold."""
        fut = Mock()
        fut.done.return_value = False
        item = create_test_item("stalled-1")
        futures = {fut: item}

        # Agent started 3h1m ago (> 3 hour threshold)
        start_times = {fut: time.time() - 10860}
        run_logger = Mock()

        stalled = _check_agent_health(futures, start_times, run_logger, None)

        assert stalled == 1
        # Should log warning about stalled agent
        assert run_logger.log_orchestrator.call_count >= 1
        first_call = run_logger.log_orchestrator.call_args_list[0]
        assert "stalled" in first_call[0][0].lower()

    @patch('pokepoke.agents.parallel.unassign_with_retry')
    def test_check_agent_health_cancels_multiple_stalled_agents(self, mock_unassign):
        """Test health check cancels futures when >=3 agents stalled."""
        futures = {}
        start_times = {}

        # Create 3 stalled futures (threshold)
        for i in range(3):
            fut = Mock()
            fut.done.return_value = False
            fut.cancel.return_value = True  # Simulate successful cancel
            item = create_test_item(f"stalled-{i}")
            futures[fut] = item
            start_times[fut] = time.time() - 10860  # 3h1m ago

        run_logger = Mock()

        stalled = _check_agent_health(futures, start_times, run_logger, None)

        assert stalled == 3
        # Should log error about cancelling
        assert any("cancelling" in str(call).lower()
                  for call in run_logger.log_orchestrator.call_args_list)
        # Should attempt to cancel all 3
        assert mock_unassign.call_count == 3

    def test_check_agent_health_with_lock(self):
        """Test health check uses lock when provided."""
        lock = threading.Lock()
        fut = Mock()
        fut.done.return_value = False
        item = create_test_item("stalled-1")
        futures = {fut: item}
        start_times = {fut: time.time() - 10860}
        run_logger = Mock()

        stalled = _check_agent_health(futures, start_times, run_logger, lock)

        assert stalled == 1


class TestCollectDoneFuturesEdgeCases:
    """Test edge cases in collect_done_futures."""

    def test_collect_done_futures_pops_item_from_futures(self):
        """Test that collected futures are removed from dict."""
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)

        def quick_task():
            return WorkItemResult(success=True, request_count=1)

        fut = executor.submit(quick_task)
        time.sleep(0.1)  # Let it complete

        item = create_test_item("item-1")
        futures = {fut: item}
        failed: set[str] = set()
        session_stats = Mock()
        run_logger = Mock()
        record_fn = Mock()

        collect_done_futures(futures, failed, 0, session_stats, run_logger, record_fn, None, None)

        # Future should be removed from dict
        assert len(futures) == 0

        executor.shutdown(wait=True)

    def test_collect_done_futures_without_future_start_times(self):
        """Test collect_done_futures when future_start_times=None."""
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)

        def quick_task():
            return WorkItemResult(success=True, request_count=1)

        fut = executor.submit(quick_task)
        time.sleep(0.1)

        item = create_test_item("item-1")
        futures = {fut: item}
        failed: set[str] = set()
        session_stats = Mock()
        run_logger = Mock()
        record_fn = Mock()

        # Pass None for future_start_times
        _total, any_success, success_count, _ = collect_done_futures(
            futures, failed, 0, session_stats, run_logger, record_fn, None, None
        )

        assert any_success is True
        assert success_count == 1

        executor.shutdown(wait=True)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
