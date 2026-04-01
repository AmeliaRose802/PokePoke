"""Tests for run_parallel_loop orchestration and continuous mode behavior.

This module contains integration tests for the main parallel orchestrator loop,
including:
- Basic loop operation (exit conditions, repo checks)
- Item submission and collection
- Continuous vs single-shot mode behavior
- Shutdown handling
- Double-check beads polling
- Dynamic configuration changes
"""

import time
from unittest.mock import MagicMock, Mock, patch

import pytest

from pokepoke.agents.parallel import run_parallel_loop
from pokepoke.types import AgentStats, BeadsWorkItem, SessionStats, WorkItemResult


def _make_item(item_id: str = "t1") -> BeadsWorkItem:
    return BeadsWorkItem(
        id=item_id, title=f"Title-{item_id}", status="open",
        priority=1, issue_type="task",
    )


@pytest.fixture(autouse=True)
def _disable_preflight_health(monkeypatch):
    """Disable preflight health checks and mock beads claim for all parallel tests.

    The preflight system uses a lazy import inside run_parallel_loop.
    We mock get_config to return a config with preflight disabled so that
    tests do not need real git repos / disk space checks.
    We also mock assign_and_sync_item since tests use fake item IDs.
    """
    mock_cfg = MagicMock()
    mock_cfg.preflight_health.enabled = False
    mock_cfg.max_parallel_agents = 10
    monkeypatch.setattr("pokepoke.config.get_config", lambda: mock_cfg)
    monkeypatch.setattr("pokepoke.agents.parallel.assign_and_sync_item", lambda *a, **kw: True)
    monkeypatch.setattr("pokepoke.agents.parallel.unassign_with_retry", lambda *a, **kw: None)
    # Mock parallel_support dependencies so _finalize_workers doesn't call real processes
    monkeypatch.setattr("pokepoke.agents.parallel_support.terminal_ui", MagicMock())


# ── run_parallel_loop ───────────────────────────────────────────────────────

class TestRunParallelLoop:
    """Tests for run_parallel_loop."""

    @patch("pokepoke.agents.parallel.time.sleep")
    @patch("pokepoke.agents.parallel.terminal_ui")
    @patch("pokepoke.agents.parallel.set_executor")
    @patch("pokepoke.agents.parallel.is_shutting_down", side_effect=[False, True])
    @patch("pokepoke.agents.parallel.check_and_commit_main_repo", return_value=True)
    @patch("pokepoke.agents.parallel.get_ready_work_items", return_value=[])
    @patch("pokepoke.agents.parallel.select_multiple_items", return_value=[])
    def test_exits_with_no_items(
        self, mock_sel, mock_ready, mock_repo, mock_shut,
        mock_set_exec, mock_ui, mock_sleep,
    ) -> None:
        """Exits 0 when no items are available and nothing in flight."""
        stats = SessionStats(agent_stats=AgentStats())
        record_fn = Mock()
        finalize_fn = Mock()
        logger = Mock()

        code = run_parallel_loop(
            effective_parallel=2, mode_name="Autonomous",
            main_repo_path="/repo", failed_claim_ids=set(),
            session_stats=stats, start_time=time.time(),
            run_logger=logger, continuous=True,
            record_fn=record_fn, finalize_fn=finalize_fn,
        )

        assert code == 0
        finalize_fn.assert_called_once()

    @patch("pokepoke.agents.parallel.time.sleep")
    @patch("pokepoke.agents.parallel.terminal_ui")
    @patch("pokepoke.agents.parallel.set_executor")
    @patch("pokepoke.agents.parallel.is_shutting_down", return_value=False)
    @patch("pokepoke.agents.parallel.check_and_commit_main_repo", return_value=False)
    @patch("pokepoke.agents.parallel.get_ready_work_items", return_value=[])
    def test_exits_on_repo_check_failure(
        self, mock_ready, mock_repo, mock_shut,
        mock_set_exec, mock_ui, mock_sleep,
    ) -> None:
        """Returns 1 when main repo check fails."""
        stats = SessionStats(agent_stats=AgentStats())
        logger = Mock()

        code = run_parallel_loop(
            effective_parallel=2, mode_name="Autonomous",
            main_repo_path="/repo", failed_claim_ids=set(),
            session_stats=stats, start_time=time.time(),
            run_logger=logger, continuous=True,
            record_fn=Mock(), finalize_fn=Mock(),
        )

        assert code == 1

    @patch("pokepoke.agents.parallel.time.sleep")
    @patch("pokepoke.agents.parallel.terminal_ui")
    @patch("pokepoke.agents.parallel.set_executor")
    @patch("pokepoke.agents.parallel.cancel_stop_after_current")
    @patch("pokepoke.agents.parallel.should_stop_after_current", return_value=True)
    @patch("pokepoke.agents.parallel.is_shutting_down", return_value=False)
    @patch("pokepoke.agents.parallel.check_and_commit_main_repo", return_value=True)
    @patch("pokepoke.agents.parallel.get_ready_work_items", return_value=[])
    @patch("pokepoke.agents.parallel.select_multiple_items", return_value=[])
    def test_stop_after_current_with_no_futures(
        self, mock_sel, mock_ready, mock_repo, mock_shut,
        mock_stop, mock_cancel, mock_set_exec, mock_ui, mock_sleep,
    ) -> None:
        """Exits cleanly when stop-after-current is set and no futures remain."""
        stats = SessionStats(agent_stats=AgentStats())
        logger = Mock()
        finalize_fn = Mock()

        code = run_parallel_loop(
            effective_parallel=2, mode_name="Autonomous",
            main_repo_path="/repo", failed_claim_ids=set(),
            session_stats=stats, start_time=time.time(),
            run_logger=logger, continuous=True,
            record_fn=Mock(), finalize_fn=finalize_fn,
        )

        assert code == 0
        mock_cancel.assert_called_once()
        finalize_fn.assert_called_once()

    @patch("pokepoke.agents.parallel.time.sleep")
    @patch("pokepoke.agents.parallel.terminal_ui")
    @patch("pokepoke.agents.parallel.set_executor")
    @patch("pokepoke.agents.parallel.is_shutting_down", side_effect=[False, True])
    @patch("pokepoke.agents.parallel.check_and_commit_main_repo", return_value=True)
    @patch("pokepoke.agents.parallel.get_ready_work_items")
    @patch("pokepoke.agents.parallel.select_multiple_items", return_value=[])
    def test_double_check_beads_finds_items(
        self, mock_sel, mock_ready, mock_repo, mock_shut,
        mock_set_exec, mock_ui, mock_sleep,
    ) -> None:
        """Double-check of beads finds items and triggers continue, then shutdown exits."""
        item = _make_item("dc1")
        # First call returns empty, second call (double-check) returns item,
        # then is_shutting_down returns True on next iteration
        mock_ready.side_effect = [[], [item], []]
        mock_shut.side_effect = [False, False, True]

        stats = SessionStats(agent_stats=AgentStats())
        logger = Mock()
        finalize_fn = Mock()

        code = run_parallel_loop(
            effective_parallel=2, mode_name="Autonomous",
            main_repo_path="/repo", failed_claim_ids=set(),
            session_stats=stats, start_time=time.time(),
            run_logger=logger, continuous=True,
            record_fn=Mock(), finalize_fn=finalize_fn,
        )

        assert code == 0
        # get_ready_work_items should be called at least 2 times
        assert mock_ready.call_count >= 2

    @patch("pokepoke.agents.parallel.time.sleep")
    @patch("pokepoke.agents.parallel.terminal_ui")
    @patch("pokepoke.agents.parallel.set_executor")
    @patch("pokepoke.agents.parallel.is_shutting_down", side_effect=[False, True])
    @patch("pokepoke.agents.parallel.check_and_commit_main_repo", return_value=True)
    @patch("pokepoke.agents.parallel.get_ready_work_items")
    @patch("pokepoke.agents.parallel.select_multiple_items", return_value=[])
    def test_double_check_beads_exception_handled(
        self, mock_sel, mock_ready, mock_repo, mock_shut,
        mock_set_exec, mock_ui, mock_sleep,
    ) -> None:
        """Double-check beads exception is caught and exit proceeds."""
        # First call returns empty, second call (double-check) raises
        mock_ready.side_effect = [[], RuntimeError("db down")]

        stats = SessionStats(agent_stats=AgentStats())
        logger = Mock()
        finalize_fn = Mock()

        code = run_parallel_loop(
            effective_parallel=2, mode_name="Autonomous",
            main_repo_path="/repo", failed_claim_ids=set(),
            session_stats=stats, start_time=time.time(),
            run_logger=logger, continuous=True,
            record_fn=Mock(), finalize_fn=finalize_fn,
        )

        assert code == 0
        finalize_fn.assert_called_once()


class TestContinuousModeLoopBack:
    """Regression tests for PokePoke-5arw: continuous mode should loop after all workers finish."""

    @patch("pokepoke.agents.parallel.time.sleep")
    @patch("pokepoke.agents.parallel.terminal_ui")
    @patch("pokepoke.agents.parallel.set_executor")
    @patch("pokepoke.agents.parallel.is_shutting_down", side_effect=[False, False, True])
    @patch("pokepoke.agents.parallel.check_and_commit_main_repo", return_value=True)
    @patch("pokepoke.agents.parallel.get_ready_work_items", return_value=[])
    @patch("pokepoke.agents.parallel.select_multiple_items", return_value=[])
    def test_continuous_mode_idle_uses_exponential_backoff(
        self, mock_sel, mock_ready, mock_repo, mock_shut,
        mock_set_exec, mock_ui, mock_sleep,
    ) -> None:
        """Continuous mode should increase idle sleep duration between empty polls."""
        stats = SessionStats(agent_stats=AgentStats())
        finalize_fn = Mock()
        logger = Mock()

        code = run_parallel_loop(
            effective_parallel=2, mode_name="Autonomous",
            main_repo_path="/repo", failed_claim_ids=set(),
            session_stats=stats, start_time=time.time(),
            run_logger=logger, continuous=True,
            record_fn=Mock(), finalize_fn=finalize_fn,
        )

        assert code == 0
        # First idle iteration should sleep with the base delay.
        assert mock_sleep.call_args_list[0].args[0] == 8.0
        # Subsequent idle iterations (if any) should not use a smaller delay.
        for call in mock_sleep.call_args_list[1:]:
            assert call.args[0] >= 8.0

    @patch("pokepoke.agents.parallel.time.sleep")
    @patch("pokepoke.agents.parallel.terminal_ui")
    @patch("pokepoke.agents.parallel.set_executor")
    @patch("pokepoke.agents.parallel.is_shutting_down", side_effect=[False, True])
    @patch("pokepoke.agents.parallel.check_and_commit_main_repo", return_value=True)
    @patch("pokepoke.agents.parallel.get_ready_work_items", return_value=[])
    @patch("pokepoke.agents.parallel.select_multiple_items", return_value=[])
    def test_continuous_mode_loops_back_when_no_items(
        self, mock_sel, mock_ready, mock_repo, mock_shut,
        mock_set_exec, mock_ui, mock_sleep,
    ) -> None:
        """In continuous mode, no ready items triggers sleep+retry rather than exit.

        Regression for PokePoke-5arw: after all workers + maintenance finish,
        the orchestrator should loop back to wait for new work instead of exiting.
        """
        stats = SessionStats(agent_stats=AgentStats())
        finalize_fn = Mock()
        logger = Mock()

        code = run_parallel_loop(
            effective_parallel=2, mode_name="Autonomous",
            main_repo_path="/repo", failed_claim_ids=set(),
            session_stats=stats, start_time=time.time(),
            run_logger=logger, continuous=True,
            record_fn=Mock(), finalize_fn=finalize_fn,
        )

        assert code == 0
        # Must have slept (the retry sleep) before the shutdown check exited the loop.
        mock_sleep.assert_called()
        # Logger should note the idle/retry via log_polling, not an exit.
        retry_logged = any(
            "sleeping" in str(call) or "Continuous" in str(call) or "no items" in str(call).lower()
            for call in logger.log_polling.call_args_list
        )
        assert retry_logged, "Expected continuous-mode retry/idle log message"

    @patch("pokepoke.agents.parallel.time.sleep")
    @patch("pokepoke.agents.parallel.terminal_ui")
    @patch("pokepoke.agents.parallel.set_executor")
    @patch("pokepoke.agents.parallel.is_shutting_down", side_effect=[False, True])
    @patch("pokepoke.agents.parallel.check_and_commit_main_repo", return_value=True)
    @patch("pokepoke.agents.parallel.get_ready_work_items", return_value=[])
    @patch("pokepoke.agents.parallel.select_multiple_items", return_value=[])
    def test_non_continuous_mode_exits_when_no_items(
        self, mock_sel, mock_ready, mock_repo, mock_shut,
        mock_set_exec, mock_ui, mock_sleep,
    ) -> None:
        """Non-continuous mode exits (not loop back) when no items available."""
        stats = SessionStats(agent_stats=AgentStats())
        logger = Mock()
        finalize_fn = Mock()

        code = run_parallel_loop(
            effective_parallel=2, mode_name="Autonomous",
            main_repo_path="/repo", failed_claim_ids=set(),
            session_stats=stats, start_time=time.time(),
            run_logger=logger, continuous=False,
            record_fn=Mock(), finalize_fn=finalize_fn,
        )

        # Non-continuous mode exits without looping; no work to do is not a failure
        assert code == 0
        finalize_fn.assert_called_once()
        # Should NOT have done a retry sleep; exited immediately.
        retry_logged = any(
            "retry" in str(call)
            for call in logger.log_orchestrator.call_args_list
        )
        assert not retry_logged, "Non-continuous mode should not retry"

    @patch("pokepoke.agents.parallel.time.sleep")
    @patch("pokepoke.agents.parallel.terminal_ui")
    @patch("pokepoke.agents.parallel.set_executor")
    @patch("pokepoke.agents.parallel.is_shutting_down", side_effect=[False, True])
    @patch("pokepoke.agents.parallel.check_and_commit_main_repo", return_value=True)
    @patch("pokepoke.agents.parallel.get_ready_work_items", return_value=[])
    @patch("pokepoke.agents.parallel.select_multiple_items", return_value=[])
    def test_record_fn_exception_does_not_crash_loop(
        self, mock_sel, mock_ready, mock_repo, mock_shut,
        mock_set_exec, mock_ui, mock_sleep,
    ) -> None:
        """record_fn raising an exception must not propagate out of _collect_done_futures.

        Regression for PokePoke-5arw: maintenance agent exceptions were re-raised
        inside record_fn, crashing the parallel orchestrator loop.
        """
        import concurrent.futures
        fut: concurrent.futures.Future = concurrent.futures.Future()
        fut.set_result(WorkItemResult(success=True, request_count=1))
        item = _make_item("boom")

        # Simulate a maintenance agent exception propagating through record_fn
        exploding_record_fn = Mock(side_effect=RuntimeError("maintenance exploded"))
        stats = SessionStats(agent_stats=AgentStats())
        logger = Mock()

        # Manually call _collect_done_futures with the exploding record_fn.
        # It must NOT raise, it must swallow the exception and log it.
        from pokepoke.agents.parallel import _collect_done_futures
        futures: dict[concurrent.futures.Future, BeadsWorkItem] = {fut: item}
        total, _any_ok, _successes, _failures = _collect_done_futures(
            futures, set(), 0, stats, logger, exploding_record_fn,
        )

        # The exception was swallowed; collect_done_futures returned normally.
        assert total == 1
        # Logger should have captured the error.
        logger.log_orchestrator.assert_called()
        error_logged = any(
            "Error recording" in str(call) or "error" in str(call).lower()
            for call in logger.log_orchestrator.call_args_list
        )
        assert error_logged


class TestParallelDrainFutureEdgeCases:
    """Tests for drain future edge cases in run_parallel_loop."""

    @patch("pokepoke.agents.parallel.time.sleep")
    @patch("pokepoke.agents.parallel.terminal_ui")
    @patch("pokepoke.agents.parallel.set_executor")
    @patch("pokepoke.agents.parallel.is_shutting_down", side_effect=[False, True])
    @patch("pokepoke.agents.parallel.check_and_commit_main_repo", return_value=True)
    @patch("pokepoke.agents.parallel.get_ready_work_items", return_value=[])
    @patch("pokepoke.agents.parallel.select_multiple_items", return_value=[])
    def test_no_items_continuous_mode_sleeps(
        self, mock_sel, mock_ready, mock_repo, mock_shut,
        mock_set_exec, mock_ui, mock_sleep,
    ) -> None:
        """Covers lines 329-334: continuous mode sleeps when no items."""
        stats = SessionStats(agent_stats=AgentStats())

        result = run_parallel_loop(
            effective_parallel=2, mode_name="Autonomous",
            main_repo_path="/repo", failed_claim_ids=set(),
            session_stats=stats, start_time=time.time(),
            run_logger=Mock(), continuous=True,
            record_fn=Mock(), finalize_fn=Mock(),
        )
        # Should have been shut down, not exit with specific code
        assert result is None or result == 0

    @patch("pokepoke.agents.parallel.time.sleep")
    @patch("pokepoke.agents.parallel.terminal_ui")
    @patch("pokepoke.agents.parallel.set_executor")
    @patch("pokepoke.agents.parallel.is_shutting_down", return_value=False)
    @patch("pokepoke.agents.parallel.check_and_commit_main_repo", return_value=True)
    @patch("pokepoke.agents.parallel.get_ready_work_items", return_value=[])
    @patch("pokepoke.agents.parallel.select_multiple_items", return_value=[])
    def test_no_items_non_continuous_exits(
        self, mock_sel, mock_ready, mock_repo, mock_shut,
        mock_set_exec, mock_ui, mock_sleep,
    ) -> None:
        """Covers lines 336-342: non-continuous mode exits when no items."""
        stats = SessionStats(agent_stats=AgentStats())
        finalize_fn = Mock()

        result = run_parallel_loop(
            effective_parallel=2, mode_name="Autonomous",
            main_repo_path="/repo", failed_claim_ids=set(),
            session_stats=stats, start_time=time.time(),
            run_logger=Mock(), continuous=False,
            record_fn=Mock(), finalize_fn=finalize_fn,
        )

        assert result == 0  # No work to do is not a failure
        finalize_fn.assert_called_once()


class TestRequestSpawnAgent:
    """Test request_spawn_agent function."""

    def test_sets_wakeup_event(self) -> None:
        """Covers line 48: _spawn_wakeup.set()."""
        from pokepoke.agents.parallel import _spawn_wakeup, request_spawn_agent
        _spawn_wakeup.clear()
        request_spawn_agent()
        assert _spawn_wakeup.is_set()
        _spawn_wakeup.clear()
