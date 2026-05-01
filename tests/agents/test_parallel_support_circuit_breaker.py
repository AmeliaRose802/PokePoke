"""Tests for circuit breaker functionality.

This module tests:
- drain_circuit_breaker: Draining remaining workers when circuit breaker trips
- update_circuit_breaker: Tracking failure counts and tripping logic
- update_memory_circuit_breaker: Tracking low-memory polls and tripping logic
"""

import concurrent.futures
from unittest.mock import MagicMock, Mock, patch

from pokepoke.agents.parallel_support import (
    drain_circuit_breaker,
    update_circuit_breaker,
)
from pokepoke.agents.parallel_worker_pool import update_memory_circuit_breaker
from pokepoke.types import AgentStats, BeadsWorkItem, SessionStats


def _make_item(item_id: str = "t1") -> BeadsWorkItem:
    return BeadsWorkItem(
        id=item_id, title=f"Title-{item_id}", status="open",
        priority=1, issue_type="task",
    )

class TestDrainCircuitBreaker:
    """Tests for drain_circuit_breaker."""

    @patch("pokepoke.agents.parallel_support.time.sleep")
    @patch("pokepoke.agents.parallel_support.is_shutting_down", return_value=False)
    @patch("pokepoke.agents.parallel_support.terminal_ui")
    def test_calls_collect_fn_and_returns_total(self, mock_tui, mock_shutdown, mock_sleep):
        collect_fn = Mock(return_value=(42, True, 1, 0))
        futures: dict = {}
        run_logger = MagicMock()
        result = drain_circuit_breaker(
            futures, set(), 10, SessionStats(agent_stats=AgentStats()),
            run_logger, Mock(), collect_fn, "Auto",
        )
        assert result == 42
        collect_fn.assert_called_once()

    @patch("pokepoke.agents.parallel_support.time.sleep")
    @patch("pokepoke.agents.parallel_support.is_shutting_down", return_value=True)
    @patch("pokepoke.agents.parallel_support.terminal_ui")
    def test_exits_early_on_shutdown(self, mock_tui, mock_shutdown, mock_sleep):
        """Drain loop should exit when shutdown signaled."""
        item = _make_item("cb1")
        fut = concurrent.futures.Future()
        futures = {fut: item}
        collect_fn = Mock(return_value=(5, False, 0, 0))
        run_logger = MagicMock()
        result = drain_circuit_breaker(
            futures, set(), 5, SessionStats(agent_stats=AgentStats()),
            run_logger, Mock(), collect_fn, "Auto",
        )
        assert result == 5

    @patch("pokepoke.agents.parallel_support._drain_orphaned_futures")
    @patch("pokepoke.agents.parallel_support.time.sleep")
    @patch("pokepoke.agents.parallel_support.time.time")
    @patch("pokepoke.agents.parallel_support.is_shutting_down", return_value=False)
    @patch("pokepoke.agents.parallel_support.terminal_ui")
    @patch("pokepoke.config.get_config")
    def test_timeout_triggers_orphan_drain(self, mock_config, mock_tui, mock_shutdown,
                                           mock_time, mock_sleep, mock_drain):
        """When drain timeout expires, _drain_orphaned_futures is called."""
        cfg = MagicMock()
        cfg.circuit_breaker_drain_timeout = 60
        mock_config.return_value = cfg
        # First call: initial collect_fn (futures remain), then time checks
        # time() returns: start_time=0, then elapsed=61 (exceeds 60s timeout)
        mock_time.side_effect = [0.0, 61.0]
        item = _make_item("timeout1")
        fut = concurrent.futures.Future()
        futures = {fut: item}
        collect_fn = Mock(return_value=(7, False, 0, 0))
        run_logger = MagicMock()
        record_fn = Mock()
        result = drain_circuit_breaker(
            futures, set(), 7, SessionStats(agent_stats=AgentStats()),
            run_logger, record_fn, collect_fn, "Auto",
        )
        assert result == 7
        mock_drain.assert_called_once()
        # Verify timeout warning was logged
        log_calls = [str(c) for c in run_logger.log_orchestrator.call_args_list]
        assert any("drain timeout" in c and "WARNING" in c for c in log_calls)

    @patch("pokepoke.agents.parallel_support.time.sleep")
    @patch("pokepoke.agents.parallel_support.time.time")
    @patch("pokepoke.agents.parallel_support.is_shutting_down", return_value=False)
    @patch("pokepoke.agents.parallel_support.terminal_ui")
    @patch("pokepoke.config.get_config")
    def test_all_futures_complete_exits_normally(self, mock_config, mock_tui,
                                                  mock_shutdown, mock_time, mock_sleep):
        """When collect_fn clears all futures, drain exits without timeout."""
        cfg = MagicMock()
        cfg.circuit_breaker_drain_timeout = 900
        mock_config.return_value = cfg
        mock_time.return_value = 0.0
        item = _make_item("done1")
        fut = concurrent.futures.Future()
        futures = {fut: item}
        call_count = [0]

        def collect_clears_on_second(futs, *args):
            call_count[0] += 1
            # First call (pre-loop) leaves futures; second call (in loop) clears them
            if call_count[0] >= 2:
                futs.clear()
            return (10, call_count[0] >= 2, 1 if call_count[0] >= 2 else 0, 0)
        collect_fn = Mock(side_effect=collect_clears_on_second)
        run_logger = MagicMock()
        result = drain_circuit_breaker(
            futures, set(), 10, SessionStats(agent_stats=AgentStats()),
            run_logger, Mock(), collect_fn, "Auto",
        )
        assert result == 10
        log_calls = [str(c) for c in run_logger.log_orchestrator.call_args_list]
        assert any("all remaining agents finished" in c for c in log_calls)

    @patch("pokepoke.agents.parallel_support._drain_orphaned_futures")
    @patch("pokepoke.agents.parallel_support.time.sleep")
    @patch("pokepoke.agents.parallel_support.time.time")
    @patch("pokepoke.agents.parallel_support.is_shutting_down", return_value=False)
    @patch("pokepoke.agents.parallel_support.terminal_ui")
    @patch("pokepoke.config.get_config")
    def test_zero_timeout_waits_indefinitely(self, mock_config, mock_tui, mock_shutdown,
                                              mock_time, mock_sleep, mock_drain):
        """When drain_timeout is 0, drain never forces termination (waits for completion)."""
        cfg = MagicMock()
        cfg.circuit_breaker_drain_timeout = 0
        mock_config.return_value = cfg
        # Simulate passage of a long time — no timeout enforced when drain_timeout=0
        # time.time() is called for start_time + each loop iteration
        time_values = [0.0] + [float(i * 100) for i in range(1, 10)]
        mock_time.side_effect = time_values
        item = _make_item("wait1")
        fut = concurrent.futures.Future()
        futures = {fut: item}
        call_count = [0]

        def collect_eventually_clears(futs, *args):
            call_count[0] += 1
            # First call is pre-loop; loop calls start at count 2
            if call_count[0] >= 4:
                futs.clear()
            return (5, call_count[0] >= 4, 1 if call_count[0] >= 4 else 0, 0)
        collect_fn = Mock(side_effect=collect_eventually_clears)
        run_logger = MagicMock()
        result = drain_circuit_breaker(
            futures, set(), 5, SessionStats(agent_stats=AgentStats()),
            run_logger, Mock(), collect_fn, "Auto",
        )
        assert result == 5
        # _drain_orphaned_futures should NOT have been called (no timeout forced)
        mock_drain.assert_not_called()

class TestUpdateCircuitBreaker:
    """Tests for update_circuit_breaker."""

    def test_failures_increment(self):
        run_logger = MagicMock()
        failures, tripped = update_circuit_breaker(0, 3, 2, 10, {}, run_logger)
        assert failures == 3
        assert tripped is False

    def test_success_resets(self):
        run_logger = MagicMock()
        failures, tripped = update_circuit_breaker(1, 0, 5, 10, {}, run_logger)
        assert failures == 0
        assert tripped is False

    def test_trip_threshold(self):
        run_logger = MagicMock()
        failures, tripped = update_circuit_breaker(0, 1, 9, 10, {}, run_logger)
        assert failures == 10
        assert tripped is True

    def test_no_changes_when_both_zero(self):
        run_logger = MagicMock()
        failures, tripped = update_circuit_breaker(0, 0, 3, 10, {}, run_logger)
        assert failures == 3
        assert tripped is False

class TestUpdateMemoryCircuitBreaker:
    """Tests for update_memory_circuit_breaker."""

    def test_low_memory_increments_counter(self):
        """When memory is below floor, consecutive poll counter increments."""
        run_logger = MagicMock()
        consecutive, tripped = update_memory_circuit_breaker(
            available_mb=2048,  # Below 3072 MB floor
            memory_floor_mb=3072,
            threshold_polls=3,
            consecutive_low_polls=1,
            futures={},
            run_logger=run_logger,
        )
        assert consecutive == 2
        assert tripped is False

    def test_sufficient_memory_resets_counter(self):
        """When memory is above floor, consecutive poll counter resets to 0."""
        run_logger = MagicMock()
        consecutive, tripped = update_memory_circuit_breaker(
            available_mb=4096,  # Above 3072 MB floor
            memory_floor_mb=3072,
            threshold_polls=3,
            consecutive_low_polls=2,
            futures={},
            run_logger=run_logger,
        )
        assert consecutive == 0
        assert tripped is False

    def test_trips_at_threshold(self):
        """Circuit breaker trips when consecutive polls reach threshold."""
        run_logger = MagicMock()
        consecutive, tripped = update_memory_circuit_breaker(
            available_mb=2048,
            memory_floor_mb=3072,
            threshold_polls=3,
            consecutive_low_polls=2,  # This will become 3, triggering trip
            futures={},
            run_logger=run_logger,
        )
        assert consecutive == 3
        assert tripped is True
        # Verify error was logged
        run_logger.log_orchestrator.assert_called_once()
        call_args = run_logger.log_orchestrator.call_args
        assert "Memory circuit breaker" in call_args[0][0]
        assert call_args[1]["level"] == "ERROR"

    def test_exact_floor_does_not_trip(self):
        """Memory exactly at floor (not below) should reset counter."""
        run_logger = MagicMock()
        consecutive, tripped = update_memory_circuit_breaker(
            available_mb=3072,  # Exactly at floor
            memory_floor_mb=3072,
            threshold_polls=3,
            consecutive_low_polls=2,
            futures={},
            run_logger=run_logger,
        )
        assert consecutive == 0
        assert tripped is False

    def test_trips_immediately_if_already_at_threshold(self):
        """If consecutive_low_polls already at threshold, trip immediately."""
        run_logger = MagicMock()
        consecutive, tripped = update_memory_circuit_breaker(
            available_mb=1024,  # Very low memory
            memory_floor_mb=3072,
            threshold_polls=3,
            consecutive_low_polls=3,  # Already at threshold
            futures={},
            run_logger=run_logger,
        )
        assert consecutive == 4  # Incremented but already tripped
        assert tripped is True

    def test_logs_futures_count_on_trip(self):
        """When tripping, log should include count of remaining futures."""
        import concurrent.futures
        item = _make_item("mem1")
        fut = concurrent.futures.Future()
        futures = {fut: item}
        run_logger = MagicMock()
        _consecutive, tripped = update_memory_circuit_breaker(
            available_mb=1024,
            memory_floor_mb=3072,
            threshold_polls=3,
            consecutive_low_polls=2,
            futures=futures,
            run_logger=run_logger,
        )
        assert tripped is True

    def test_zero_avail_mb_preserves_counter(self):
        """When avail_mb is 0 (monitoring failure), counter is preserved -- not reset."""
        run_logger = MagicMock()
        consecutive, tripped = update_memory_circuit_breaker(
            available_mb=0,  # Unknown memory status (monitoring failed)
            memory_floor_mb=3072,
            threshold_polls=3,
            consecutive_low_polls=2,  # Below threshold
            futures={},
            run_logger=run_logger,
        )
        assert consecutive == 2  # Preserved, not reset
        assert tripped is False

    def test_zero_avail_mb_preserves_counter_above_threshold(self):
        """When avail_mb is 0 and counter already at/above threshold, trip is maintained."""
        run_logger = MagicMock()
        consecutive, tripped = update_memory_circuit_breaker(
            available_mb=0,  # Unknown memory status (monitoring failed)
            memory_floor_mb=3072,
            threshold_polls=3,
            consecutive_low_polls=10,  # Already above threshold
            futures={},
            run_logger=run_logger,
        )
        assert consecutive == 10  # Preserved
        assert tripped is True

