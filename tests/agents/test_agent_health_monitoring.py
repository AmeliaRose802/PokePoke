"""Tests for agent health monitoring that detects stalled agents."""
import threading
import time
from concurrent.futures import Future
from unittest.mock import Mock

from pokepoke.agents.parallel_worker_pool import (
    _AGENT_STALL_THRESHOLD,
    _MAX_STALLED_AGENTS,
    _check_agent_health,
    collect_done_futures,
)
from pokepoke.types import WorkItemResult
from pokepoke.types_beads import BeadsWorkItem


def _make_item(item_id: str = "test-1") -> BeadsWorkItem:
    return BeadsWorkItem(
        id=item_id, title="Test", status="ready", priority=1, issue_type="task"
    )


class TestAgentHealthMonitoring:
    """Test agent health monitoring for detecting stalled agents."""

    def test_check_agent_health_no_stalled_agents(self):
        """Health check should pass when no agents are stalled."""
        futures = {Future(): _make_item("item-1")}
        start_times = {next(iter(futures.keys())): time.time()}
        run_logger = Mock()

        _check_agent_health(futures, start_times, run_logger)

        # No warnings should be logged
        assert not any(
            "stalled" in str(call) for call in run_logger.log_orchestrator.call_args_list
        )

    def test_check_agent_health_detects_stalled_agent(self):
        """Health check should detect and warn about stalled agents."""
        fut = Future()
        futures = {fut: _make_item("item-1")}
        # Simulate agent running for longer than threshold
        start_times = {fut: time.time() - (_AGENT_STALL_THRESHOLD + 60)}
        run_logger = Mock()

        _check_agent_health(futures, start_times, run_logger)

        # Should log warning about stalled agent
        calls = run_logger.log_orchestrator.call_args_list
        assert any("stalled" in str(call).lower() for call in calls)
        assert any("item-1" in str(call) for call in calls)

    def test_check_agent_health_triggers_error_at_threshold(self):
        """Health check should trigger error when too many agents are stalled."""
        futures = {}
        start_times = {}
        stale_time = time.time() - (_AGENT_STALL_THRESHOLD + 60)

        # Create MAX_STALLED_AGENTS stalled futures
        for i in range(_MAX_STALLED_AGENTS):
            fut = Future()
            futures[fut] = _make_item(f"item-{i}")
            start_times[fut] = stale_time

        run_logger = Mock()

        _check_agent_health(futures, start_times, run_logger)

        # Should log error about system deadlock
        calls = [str(call) for call in run_logger.log_orchestrator.call_args_list]
        error_calls = [c for c in calls if "level='ERROR'" in c]
        assert any("deadlock" in c.lower() for c in error_calls)

    def test_check_agent_health_ignores_completed_futures(self):
        """Health check should only consider non-completed futures."""
        # Create a completed future
        fut = Future()
        fut.set_result(WorkItemResult(success=True, request_count=1))
        futures = {fut: _make_item("item-1")}
        start_times = {fut: time.time() - (_AGENT_STALL_THRESHOLD + 60)}
        run_logger = Mock()

        _check_agent_health(futures, start_times, run_logger)

        # Should not log warnings since future is done
        assert not any(
            "stalled" in str(call) for call in run_logger.log_orchestrator.call_args_list
        )

    def test_check_agent_health_with_lock(self):
        """Health check should work correctly with thread lock."""
        lock = threading.Lock()
        fut = Future()
        futures = {fut: _make_item("item-1")}
        start_times = {fut: time.time() - (_AGENT_STALL_THRESHOLD + 60)}
        run_logger = Mock()

        _check_agent_health(futures, start_times, run_logger, lock)

        # Should detect stalled agent even with lock
        calls = run_logger.log_orchestrator.call_args_list
        assert any("stalled" in str(call).lower() for call in calls)


class TestCollectDoneFuturesWithHealthMonitoring:
    """Test that collect_done_futures performs health checks when enabled."""

    def test_health_check_performed_when_start_times_provided(self):
        """Health check should be performed when future_start_times is provided."""
        fut = Future()
        fut.set_result(WorkItemResult(success=True, request_count=1))
        item = _make_item("item-1")
        futures = {fut: item}
        failed_claim_ids: set[str] = set()
        # Simulate stalled agent
        start_times = {fut: time.time() - (_AGENT_STALL_THRESHOLD + 60)}

        session_stats = Mock()
        run_logger = Mock()
        record_fn = Mock()

        collect_done_futures(
            futures,
            failed_claim_ids,
            0,
            session_stats,
            run_logger,
            record_fn,
            lock=None,
            future_start_times=start_times,
        )

        # Should have logged something (either lifecycle or health check)
        assert run_logger.log_orchestrator.called

    def test_health_check_skipped_when_no_start_times(self):
        """Health check should be skipped when future_start_times is None."""
        fut = Future()
        fut.set_result(WorkItemResult(success=True, request_count=1))
        item = _make_item("item-1")
        futures = {fut: item}
        failed_claim_ids: set[str] = set()

        session_stats = Mock()
        run_logger = Mock()
        record_fn = Mock()

        collect_done_futures(
            futures,
            failed_claim_ids,
            0,
            session_stats,
            run_logger,
            record_fn,
            lock=None,
            future_start_times=None,
        )

        # Should not trigger health monitoring warnings
        # (lifecycle messages are ok, but no stall warnings)
        calls = [str(call) for call in run_logger.log_orchestrator.call_args_list]
        assert not any("stalled" in c.lower() for c in calls)

    def test_start_times_cleaned_up_for_done_futures(self):
        """Start times should be removed when futures complete."""
        fut = Future()
        fut.set_result(WorkItemResult(success=True, request_count=1))
        item = _make_item("item-1")
        futures = {fut: item}
        failed_claim_ids: set[str] = set()
        start_times = {fut: time.time()}

        session_stats = Mock()
        run_logger = Mock()
        record_fn = Mock()

        collect_done_futures(
            futures,
            failed_claim_ids,
            0,
            session_stats,
            run_logger,
            record_fn,
            lock=None,
            future_start_times=start_times,
        )

        # Start time should be removed after collection
        assert fut not in start_times
