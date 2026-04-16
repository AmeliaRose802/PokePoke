"""Tests for orchestrator deadlock prevention mechanisms (PokePoke-82v1j)."""

import concurrent.futures
import time
from unittest.mock import Mock

from pokepoke.agents.parallel_worker_pool import (
    _check_agent_health,
    collect_done_futures,
)
from pokepoke.types_beads import BeadsWorkItem


class FakeRunLogger:
    """Minimal fake RunLogger for testing."""

    def __init__(self):
        self.orchestrator_messages: list[str] = []
        self.polling_messages: list[str] = []

    def log_orchestrator(self, message: str, level: str = "INFO") -> None:
        self.orchestrator_messages.append(f"[{level}] {message}")

    def log_polling(self, message: str, level: str = "INFO") -> None:
        self.polling_messages.append(f"[{level}] {message}")


def test_health_monitoring_detects_stalled_agents():
    """Test that health monitoring detects agents stalled beyond threshold."""
    futures: dict[concurrent.futures.Future, BeadsWorkItem] = {}
    future_start_times: dict[concurrent.futures.Future, float] = {}
    run_logger = FakeRunLogger()

    # Create a mock future that never completes
    fut = Mock(spec=concurrent.futures.Future)
    fut.done.return_value = False

    item = BeadsWorkItem(
        id="stalled-1",
        title="Stalled Item",
        status="in_progress",
        priority=1,
        issue_type="task",
    )

    futures[fut] = item
    # Set start time to 4 hours ago (beyond 3 hour threshold)
    future_start_times[fut] = time.time() - 14400.0

    # Run health check
    stalled_count = _check_agent_health(futures, future_start_times, run_logger, lock=None)

    assert stalled_count == 1
    assert any("stalled" in msg.lower() for msg in run_logger.orchestrator_messages)


def test_health_monitoring_cancels_multiple_stalled_agents():
    """Test that health monitoring cancels stalled agents when threshold is reached."""
    futures: dict[concurrent.futures.Future, BeadsWorkItem] = {}
    future_start_times: dict[concurrent.futures.Future, float] = {}
    run_logger = FakeRunLogger()

    # Create 3 stalled futures (meets _MAX_STALLED_AGENTS threshold)
    stalled_futures = []
    for i in range(3):
        fut = Mock(spec=concurrent.futures.Future)
        fut.done.return_value = False
        fut.cancel.return_value = True  # Successfully cancelled

        item = BeadsWorkItem(
            id=f"stalled-{i}",
            title=f"Stalled Item {i}",
            status="in_progress",
            priority=1,
            issue_type="task",
        )

        futures[fut] = item
        future_start_times[fut] = time.time() - 14400.0  # 4 hours ago
        stalled_futures.append(fut)

    # Run health check (it will try to cancel stalled futures)
    stalled_count = _check_agent_health(futures, future_start_times, run_logger, lock=None)

    assert stalled_count == 3

    # Check that futures were cancelled
    for fut in stalled_futures:
        fut.cancel.assert_called_once()

    # Check that we logged the cancellation
    assert any("Cancelled" in msg and "stalled" in msg.lower()
               for msg in run_logger.orchestrator_messages)


def test_health_check_invoked_when_future_start_times_provided():
    """Test that health monitoring is invoked when future_start_times is provided."""
    futures_dict: dict[concurrent.futures.Future, BeadsWorkItem] = {}
    future_start_times: dict[concurrent.futures.Future, float] = {}
    failed_claim_ids: set[str] = set()
    run_logger = FakeRunLogger()
    session_stats = Mock()
    session_stats.items_completed = 0

    def record_fn(item, result, stats, logger):
        pass

    # Create a stalled future
    fut = Mock(spec=concurrent.futures.Future)
    fut.done.return_value = False

    item = BeadsWorkItem(
        id="monitored-1",
        title="Monitored Item",
        status="in_progress",
        priority=1,
        issue_type="task",
    )

    futures_dict[fut] = item
    future_start_times[fut] = time.time() - 14400.0  # 4 hours ago

    # Call collect_done_futures with future_start_times
    # This should trigger health monitoring
    _,_, _, _ = collect_done_futures(
        futures_dict,
        failed_claim_ids,
        total_requests=0,
        session_stats=session_stats,
        run_logger=run_logger,
        record_fn=record_fn,
        lock=None,
        future_start_times=future_start_times,
    )

    # Health check should have detected the stalled agent
    assert any("stalled" in msg.lower() for msg in run_logger.orchestrator_messages)


def test_collect_done_futures_uses_nonblocking_polling():
    """Test that collect_done_futures uses non-blocking .done() polling instead of wait().

    The fix for PokePoke-82v1j removed concurrent.futures.wait() which could hang
    indefinitely. This test verifies the function never calls wait() and instead
    relies solely on non-blocking .done() checks.
    """
    from unittest.mock import patch

    futures_dict: dict[concurrent.futures.Future, BeadsWorkItem] = {}
    failed_claim_ids: set[str] = set()
    run_logger = FakeRunLogger()
    session_stats = Mock()
    session_stats.items_completed = 0

    def record_fn(item, result, stats, logger):
        pass

    # Create a future that is not done (would cause wait() to block)
    fut = Mock(spec=concurrent.futures.Future)
    fut.done.return_value = False

    item = BeadsWorkItem(
        id="blocking-1",
        title="Blocking Item",
        status="in_progress",
        priority=1,
        issue_type="task",
    )

    futures_dict[fut] = item

    # Patch concurrent.futures.wait to detect if it's ever called
    with patch('concurrent.futures.wait') as mock_wait:
        _, _, _, _ = collect_done_futures(
            futures_dict,
            failed_claim_ids,
            total_requests=0,
            session_stats=session_stats,
            run_logger=run_logger,
            record_fn=record_fn,
            lock=None,
            future_start_times=None,
        )

        # wait() must never be called — the fix uses .done() polling only
        mock_wait.assert_not_called()

    # The not-done future should remain in the dict (not collected)
    assert fut in futures_dict
    # .done() was called to check status
    fut.done.assert_called()
