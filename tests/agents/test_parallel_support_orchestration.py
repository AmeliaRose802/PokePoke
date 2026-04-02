"""Tests for orchestration helper functions.

This module tests:
- run_preflight_and_repo_checks: Combined preflight and repository validation
- check_loop_exit: Main loop exit condition checking
- compute_slots: Available worker slot calculation
"""

import concurrent.futures
import time
from unittest.mock import MagicMock, Mock, patch

from pokepoke.agents.parallel_support import (
    check_loop_exit,
    compute_slots,
    run_preflight_and_repo_checks,
)
from pokepoke.types import AgentStats, BeadsWorkItem, SessionStats


def _make_item(item_id: str = "t1") -> BeadsWorkItem:
    return BeadsWorkItem(
        id=item_id, title=f"Title-{item_id}", status="open",
        priority=1, issue_type="task",
    )


class TestRunPreflightAndRepoChecks:
    """Tests for run_preflight_and_repo_checks."""

    @patch("pokepoke.agents.parallel_support.handle_preflight_checks", return_value=(True, False))
    def test_all_checks_pass(self, _preflight):
        run_logger = MagicMock()
        repo_fn = Mock(return_value=True)
        items = [_make_item("r1")]
        ready_fn = Mock(return_value=items)

        ok, failures, result = run_preflight_and_repo_checks(
            "/repo", run_logger, 0, 5, repo_fn, ready_fn,
        )
        assert ok is True
        assert failures == 0
        assert result == items

    @patch("pokepoke.agents.parallel_support.handle_preflight_checks", return_value=(False, True))
    def test_critical_preflight_failure_increments(self, _preflight):
        run_logger = MagicMock()
        ok, failures, result = run_preflight_and_repo_checks(
            "/repo", run_logger, 2, 5, Mock(), Mock(),
        )
        assert ok is False
        assert failures == 3
        assert result == []

    @patch("pokepoke.agents.parallel_support.handle_preflight_checks", return_value=(False, False))
    def test_non_critical_preflight_failure(self, _preflight):
        run_logger = MagicMock()
        ok, failures, _result = run_preflight_and_repo_checks(
            "/repo", run_logger, 1, 5, Mock(), Mock(),
        )
        assert ok is False
        assert failures == 1

    @patch("pokepoke.agents.parallel_support.handle_preflight_checks", return_value=(True, False))
    def test_repo_check_failure(self, _preflight):
        run_logger = MagicMock()
        repo_fn = Mock(return_value=False)
        ok, _failures, result = run_preflight_and_repo_checks(
            "/repo", run_logger, 0, 5, repo_fn, Mock(),
        )
        assert ok is False
        assert result == []

    @patch("pokepoke.agents.parallel_support.handle_preflight_checks", return_value=(True, False))
    def test_ready_items_exception_returns_failure(self, _preflight):
        """Test that exception from get_ready_work_items returns failure (ok=False)."""
        run_logger = MagicMock()
        repo_fn = Mock(return_value=True)
        ready_fn = Mock(side_effect=RuntimeError("beads down"))
        ok, _failures, result = run_preflight_and_repo_checks(
            "/repo", run_logger, 0, 5, repo_fn, ready_fn,
        )
        assert ok is False  # beads failure is now an error, not treated as "no work"
        assert result == []

    @patch("pokepoke.agents.parallel_support.handle_preflight_checks", return_value=(True, False))
    def test_ready_items_returns_none_signals_failure(self, _preflight):
        """Test that None from get_ready_work_items signals system error."""
        run_logger = MagicMock()
        repo_fn = Mock(return_value=True)
        ready_fn = Mock(return_value=None)
        ok, _failures, result = run_preflight_and_repo_checks(
            "/repo", run_logger, 0, 5, repo_fn, ready_fn,
        )
        assert ok is False  # None signals system error
        assert result == []


class TestCheckLoopExit:
    """Tests for check_loop_exit."""

    @patch("pokepoke.agents.parallel.should_stop_after_current", return_value=True)
    @patch("pokepoke.agents.parallel.cancel_stop_after_current")
    @patch("pokepoke.agents.parallel_support.terminal_ui")
    def test_stop_after_current_no_futures(self, mock_tui, _cancel, _stop):
        stats = SessionStats(agent_stats=AgentStats())
        finalize_fn = Mock()
        result = check_loop_exit(
            {}, [], False, False, 1, 0, stats, time.time(), 8.0, "Auto",
            MagicMock(), finalize_fn,
        )
        assert result == "break-success"
        finalize_fn.assert_called_once()

    @patch("pokepoke.agents.parallel.should_stop_after_current", return_value=False)
    @patch("pokepoke.agents.parallel_support.terminal_ui")
    def test_non_continuous_done(self, mock_tui, _stop):
        stats = SessionStats(agent_stats=AgentStats())
        finalize_fn = Mock()
        result = check_loop_exit(
            {}, [], False, True, 5, 1, stats, time.time(), 8.0, "Auto",
            MagicMock(), finalize_fn,
        )
        assert result == "break-done"

    @patch("pokepoke.agents.parallel.should_stop_after_current", return_value=False)
    @patch("pokepoke.agents.parallel_support.terminal_ui")
    def test_no_futures_no_items_recheck_finds_items(self, mock_tui, _stop):
        ready_fn = Mock(return_value=[_make_item("rc1")])
        result = check_loop_exit(
            {}, [], False, False, 0, 0, SessionStats(agent_stats=AgentStats()),
            time.time(), 8.0, "Auto", MagicMock(), Mock(), ready_fn,
        )
        assert result == "recheck"

    @patch("pokepoke.agents.parallel.should_stop_after_current", return_value=False)
    @patch("pokepoke.agents.parallel_support.terminal_ui")
    def test_no_futures_no_items_not_continuous(self, mock_tui, _stop):
        ready_fn = Mock(return_value=[])
        finalize_fn = Mock()
        result = check_loop_exit(
            {}, [], False, False, 0, 0, SessionStats(agent_stats=AgentStats()),
            time.time(), 8.0, "Auto", MagicMock(), finalize_fn, ready_fn,
        )
        assert result == "break-empty"
        finalize_fn.assert_called_once()

    @patch("pokepoke.agents.parallel_support.time.sleep")
    @patch("pokepoke.agents.parallel.should_stop_after_current", return_value=False)
    @patch("pokepoke.agents.parallel_support.terminal_ui")
    def test_continuous_idle_sleep(self, mock_tui, _stop, mock_sleep):
        ready_fn = Mock(return_value=[])
        result = check_loop_exit(
            {}, [], True, False, 0, 0, SessionStats(agent_stats=AgentStats()),
            time.time(), 8.0, "Auto", MagicMock(), Mock(), ready_fn,
        )
        assert result == "idle-continue"
        mock_sleep.assert_called_once_with(8.0)

    @patch("pokepoke.agents.parallel.should_stop_after_current", return_value=False)
    @patch("pokepoke.agents.parallel_support.terminal_ui")
    def test_futures_still_active_returns_none(self, mock_tui, _stop):
        fut = concurrent.futures.Future()
        item = _make_item("active1")
        result = check_loop_exit(
            {fut: item}, [_make_item("r1")], True, False, 0, 0,
            SessionStats(agent_stats=AgentStats()), time.time(), 8.0, "Auto",
            MagicMock(), Mock(),
        )
        assert result is None

    @patch("pokepoke.agents.parallel.should_stop_after_current", return_value=False)
    @patch("pokepoke.agents.parallel_support.terminal_ui")
    def test_recheck_exception_falls_through(self, mock_tui, _stop):
        """If recheck raises, it falls through to break-empty (non-continuous)."""
        ready_fn = Mock(side_effect=RuntimeError("beads error"))
        finalize_fn = Mock()
        result = check_loop_exit(
            {}, [], False, False, 0, 0, SessionStats(agent_stats=AgentStats()),
            time.time(), 8.0, "Auto", MagicMock(), finalize_fn, ready_fn,
        )
        assert result == "break-empty"


class TestComputeSlots:
    """Tests for compute_slots."""

    @patch("pokepoke.utils.memory_utils.apply_memory_backpressure", return_value=(2, 8000))
    @patch("pokepoke.agents.parallel.get_effective_max_agents", return_value=4)
    def test_basic_slot_computation(self, _max, _mem):
        item = _make_item("cs1")
        fut = concurrent.futures.Future()
        futures = {fut: item}
        run_logger = MagicMock()
        active, slots, avail_mb = compute_slots(futures, run_logger)
        assert "cs1" in active
        assert slots == 2
        assert avail_mb == 8000

    @patch("pokepoke.utils.memory_utils.apply_memory_backpressure", return_value=(0, 500))
    @patch("pokepoke.agents.parallel.get_effective_max_agents", return_value=4)
    def test_memory_low_blocks_slots(self, _max, _mem):
        item = _make_item("ml1")
        fut = concurrent.futures.Future()
        futures = {fut: item}
        run_logger = MagicMock()
        _active, slots, avail_mb = compute_slots(futures, run_logger)
        assert slots == 0
        assert avail_mb == 500

    @patch("pokepoke.utils.memory_utils.apply_memory_backpressure", return_value=(1, 2000))
    @patch("pokepoke.agents.parallel.get_effective_max_agents", return_value=4)
    def test_memory_pressure_reduces_slots(self, _max, _mem):
        """Memory pressure: backpressure returns fewer slots than available."""
        run_logger = MagicMock()
        _active, slots, avail_mb = compute_slots({}, run_logger)
        assert slots == 1
        assert avail_mb == 2000
