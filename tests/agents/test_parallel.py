"""Tests for the parallel orchestrator loop module."""

import concurrent.futures
import os
import threading
import time
from unittest.mock import Mock, patch, MagicMock

import pytest

from pokepoke.types import AgentStats, BeadsWorkItem, SessionStats, WorkItemResult
from pokepoke.agents.parallel import (
    _parallel_process_item,
    _collect_done_futures,
    run_parallel_loop,
)


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
    monkeypatch.setattr("pokepoke.agents.parallel_support.kill_orphaned_copilot_processes", lambda **kw: None)
    monkeypatch.setattr("pokepoke.agents.parallel_support.terminal_ui", MagicMock())


# ΓöÇΓöÇ _parallel_process_item ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ

class TestParallelProcessItem:
    """Tests for _parallel_process_item wrapper."""

    @patch.dict(os.environ, {"AGENT_NAME": ""}, clear=False)
    @patch("pokepoke.agents.parallel.terminal_ui")
    @patch("pokepoke.agents.parallel.process_work_item")
    def test_success_releases_resources(self, mock_pwi: Mock, mock_ui: Mock) -> None:
        mock_pwi.return_value = WorkItemResult(success=True, request_count=1)
        sem = threading.Semaphore(0)

        result = _parallel_process_item(_make_item(), Mock(), sem)

        assert result == WorkItemResult(success=True, request_count=1)
        assert sem.acquire(blocking=False)
        # Agent status should be registered and updated (agent_id is item.id
        # when no worker_agent_name is provided)
        mock_ui.ui.push_agent_status.assert_any_call(
            "t1",
            "pokepoke",
            iteration=1,
            status="running",
            work_item_id="t1",
            work_item_title="Title-t1",
            agent_type="work",
        )
        mock_ui.ui.push_agent_status.assert_any_call(
            "t1",
            "pokepoke",
            iteration=1,
            status="success",
            work_item_id="t1",
            work_item_title="Title-t1",
            agent_type="work",
        )

    @patch.dict(os.environ, {"AGENT_NAME": ""}, clear=False)
    @patch("pokepoke.agents.parallel.terminal_ui")
    @patch("pokepoke.agents.parallel.process_work_item", side_effect=RuntimeError("boom"))
    def test_exception_releases_resources(self, mock_pwi: Mock, mock_ui: Mock) -> None:
        sem = threading.Semaphore(0)

        with pytest.raises(RuntimeError):
            _parallel_process_item(_make_item(), Mock(), sem)

        assert sem.acquire(blocking=False)
        # Agent status should be set to failed on exception
        mock_ui.ui.push_agent_status.assert_any_call(
            "t1",
            "pokepoke",
            iteration=1,
            status="failed",
            work_item_id="t1",
            work_item_title="Title-t1",
            agent_type="work",
        )

    @patch.dict(os.environ, {"AGENT_NAME": ""}, clear=False)
    @patch("pokepoke.agents.parallel.terminal_ui")
    @patch("pokepoke.agents.parallel.process_work_item")
    def test_failure_sets_agent_failed_status(self, mock_pwi: Mock, mock_ui: Mock) -> None:
        """A work item that returns success=False should set agent status to failed."""
        mock_pwi.return_value = WorkItemResult(success=False, request_count=1)
        sem = threading.Semaphore(0)

        result = _parallel_process_item(_make_item(), Mock(), sem)

        assert result.success is False
        mock_ui.ui.push_agent_status.assert_any_call(
            "t1",
            "pokepoke",
            iteration=1,
            status="failed",
            work_item_id="t1",
            work_item_title="Title-t1",
            agent_type="work",
        )

    @patch("pokepoke.agents.parallel.terminal_ui")
    @patch("pokepoke.agents.parallel.process_work_item")
    def test_output_routed_via_agent_output_for(self, mock_pwi: Mock, mock_ui: Mock) -> None:
        """Verify that agent_output_for context manager is used for output routing."""
        mock_pwi.return_value = WorkItemResult(success=True, request_count=1)
        sem = threading.Semaphore(0)

        _parallel_process_item(_make_item(), Mock(), sem)

        # Should use agent_output_for to route output
        mock_ui.ui.agent_output_for.assert_called_once_with("t1")

    @patch("pokepoke.agents.parallel.terminal_ui")
    @patch("pokepoke.agents.parallel.process_work_item")
    def test_same_item_different_workers_get_unique_agent_ids(
        self, mock_pwi: Mock, mock_ui: Mock,
    ) -> None:
        """Two workers on the same item must use distinct agent_ids (PokePoke-kluq)."""
        mock_pwi.return_value = WorkItemResult(success=True, request_count=1)

        item = _make_item("dup-item")
        sem1 = threading.Semaphore(0)
        sem2 = threading.Semaphore(0)

        _parallel_process_item(item, Mock(), sem1, worker_agent_name="worker-1")
        _parallel_process_item(item, Mock(), sem2, worker_agent_name="worker-2")

        # Collect all agent_ids passed to push_agent_status
        agent_ids = {
            call.args[0] for call in mock_ui.ui.push_agent_status.call_args_list
        }
        # Must have two distinct agent_ids for the two workers
        assert len(agent_ids) == 2
        assert "dup-item:worker-1" in agent_ids
        assert "dup-item:worker-2" in agent_ids

    @patch("pokepoke.agents.parallel.terminal_ui")
    @patch("pokepoke.agents.parallel.process_work_item")
    def test_process_work_item_receives_agent_id(
        self, mock_pwi: Mock, mock_ui: Mock,
    ) -> None:
        """process_work_item should receive the derived agent_id for gating."""
        mock_pwi.return_value = WorkItemResult(success=True, request_count=1)
        sem = threading.Semaphore(0)
        item = _make_item("gate-1")

        _parallel_process_item(item, Mock(), sem, worker_agent_name="worker-A")

        assert mock_pwi.call_args
        _, kwargs = mock_pwi.call_args
        assert kwargs["agent_id"] == "gate-1:worker-A"


# ΓöÇΓöÇ _collect_done_futures ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ

class TestCollectDoneFutures:
    """Tests for _collect_done_futures helper."""

    def test_collects_done_future(self) -> None:
        """A completed future is collected and record_fn is called."""
        fut: concurrent.futures.Future = concurrent.futures.Future()
        fut.set_result(WorkItemResult(success=True, request_count=2, stats=AgentStats(), cleanup_agent_runs=1, gate_agent_runs=1))
        item = _make_item()
        futures = {fut: item}
        failed: set[str] = set()
        stats = SessionStats(agent_stats=AgentStats())
        logger = Mock()
        record_fn = Mock()

        total, any_ok, successes, failures = _collect_done_futures(
            futures, failed, 0, stats, logger, record_fn,
        )

        assert total == 2
        assert any_ok is True
        assert successes == 1
        assert failures == 0
        assert len(futures) == 0
        record_fn.assert_called_once()

    def test_records_failed_claim(self) -> None:
        """A failure with 0 requests adds item to failed_claim_ids."""
        fut: concurrent.futures.Future = concurrent.futures.Future()
        fut.set_result(WorkItemResult(success=False, request_count=0))
        item = _make_item("fail1")
        futures = {fut: item}
        failed: set[str] = set()
        stats = SessionStats(agent_stats=AgentStats())
        logger = Mock()
        record_fn = Mock()

        _collect_done_futures(futures, failed, 0, stats, logger, record_fn)

        assert "fail1" in failed

    def test_exception_in_future(self) -> None:
        """An exception in a future is handled gracefully.

        Crashed workers must NOT be added to failed_claim_ids so they
        remain eligible for retry (fixes PokePoke-8o4o).
        """
        fut: concurrent.futures.Future = concurrent.futures.Future()
        fut.set_exception(RuntimeError("kaboom"))
        item = _make_item("err1")
        futures = {fut: item}
        failed: set[str] = set()
        stats = SessionStats(agent_stats=AgentStats())
        logger = Mock()
        record_fn = Mock()

        total, any_ok, successes, failures = _collect_done_futures(
            futures, failed, 5, stats, logger, record_fn,
        )

        assert total == 5  # no requests added
        assert any_ok is False
        assert successes == 0
        assert failures == 1
        # Exception-crashed items must NOT be blacklisted (PokePoke-8o4o fix)
        assert "err1" not in failed
        logger.log_orchestrator.assert_called()
        record_fn.assert_called_once()

    def test_claim_failure_is_blacklisted(self) -> None:
        """A returned claim failure (request_count=0, no exception) IS blacklisted."""
        fut: concurrent.futures.Future = concurrent.futures.Future()
        fut.set_result(WorkItemResult(success=False, request_count=0))
        item = _make_item("claim-fail")
        futures = {fut: item}
        failed: set[str] = set()
        stats = SessionStats(agent_stats=AgentStats())
        record_fn = Mock()

        _collect_done_futures(futures, failed, 0, stats, Mock(), record_fn)

        assert "claim-fail" in failed

    def test_no_done_futures_returns_zero(self) -> None:
        """When no futures are done, returns unchanged totals."""
        stats = SessionStats(agent_stats=AgentStats())
        record_fn = Mock()
        # Empty dict
        total, any_ok, successes, failures = _collect_done_futures(
            {}, set(), 3, stats, Mock(), record_fn,
        )
        assert total == 3
        assert any_ok is False
        assert successes == 0
        assert failures == 0
        record_fn.assert_not_called()


# ΓöÇΓöÇ run_parallel_loop ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ

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

    @patch("pokepoke.agents.parallel.is_item_claimable", return_value=True)
    @patch("pokepoke.agents.parallel.time.sleep")
    @patch("pokepoke.agents.parallel.terminal_ui")
    @patch("pokepoke.agents.parallel.set_executor")
    @patch("pokepoke.agents.parallel.is_shutting_down", side_effect=[False, True, True])
    @patch("pokepoke.agents.parallel.check_and_commit_main_repo", return_value=True)
    @patch("pokepoke.agents.parallel.get_ready_work_items")
    @patch("pokepoke.agents.parallel.select_multiple_items")
    @patch("pokepoke.agents.parallel.process_work_item")
    def test_submits_and_collects_item(
        self, mock_pwi, mock_sel, mock_ready,
        mock_repo, mock_shut, mock_set_exec, mock_ui, mock_sleep, mock_claimable,
    ) -> None:
        """Submits an item and collects its result in single-shot mode."""
        item = _make_item("x1")
        mock_ready.return_value = [item]
        mock_sel.return_value = [item]
        mock_pwi.return_value = WorkItemResult(success=True, request_count=1, stats=AgentStats(), gate_agent_runs=1)

        stats = SessionStats(agent_stats=AgentStats())
        record_fn = Mock()
        finalize_fn = Mock()
        logger = Mock()

        code = run_parallel_loop(
            effective_parallel=2, mode_name="Autonomous",
            main_repo_path="/repo", failed_claim_ids=set(),
            session_stats=stats, start_time=time.time(),
            run_logger=logger, continuous=False,
            record_fn=record_fn, finalize_fn=finalize_fn,
        )

        assert code == 0
        finalize_fn.assert_called_once()
        # record_fn should be called at least once (from collect or drain)
        assert record_fn.call_count >= 1

    @patch("pokepoke.agents.parallel.is_item_claimable", return_value=True)
    @patch("pokepoke.agents.parallel.time.sleep")
    @patch("pokepoke.agents.parallel.terminal_ui")
    @patch("pokepoke.utils.process_utils.apply_memory_backpressure", side_effect=lambda s: (s, 0))
    @patch("pokepoke.agents.parallel.set_executor")
    @patch("pokepoke.agents.parallel.should_stop_after_current", return_value=False)
    @patch("pokepoke.agents.parallel.is_shutting_down")
    @patch("pokepoke.agents.parallel.check_and_commit_main_repo", return_value=True)
    @patch("pokepoke.agents.parallel.get_ready_work_items")
    @patch("pokepoke.agents.parallel.select_multiple_items")
    @patch("pokepoke.agents.parallel._collect_done_futures")
    @patch("pokepoke.agents.parallel.process_work_item")
    @patch("pokepoke.agents.parallel._get_dynamic_max_agents", return_value=3)
    def test_refills_all_slots_after_completions(
        self, mock_dyn_max, mock_pwi, mock_collect, mock_sel, mock_ready,
        mock_repo, mock_shut, mock_stop, mock_set_exec, mock_mem, mock_ui, mock_sleep, mock_claimable,
    ) -> None:
        """Regression (PokePoke-qagy): all empty slots refilled after batch completes."""
        items = [_make_item(f"r{i}") for i in range(6)]
        mock_ready.return_value = items
        mock_pwi.return_value = WorkItemResult(success=True, request_count=1, stats=AgentStats())

        # Iteration 1: collect does nothing (no completed futures yet).
        # Iteration 2: collect clears all 3 futures (simulates 3 completions).
        call_idx = [0]

        def collect_side(futures, failed, total, stats, logger, record_fn):
            call_idx[0] += 1
            if call_idx[0] == 2:
                futures.clear()
                return (total, True, 3, 0)
            return (total, False, 0, 0)

        mock_collect.side_effect = collect_side
        mock_sel.side_effect = [items[:3], [], items[3:6], []]

        # Enough False for 2 full iterations (1 while + 10 sleep each) + shutdown
        mock_shut.side_effect = [False] * 22 + [True] * 5

        stats = SessionStats(agent_stats=AgentStats())
        run_parallel_loop(
            effective_parallel=3, mode_name="Autonomous",
            main_repo_path="/repo", failed_claim_ids=set(),
            session_stats=stats, start_time=time.time(),
            run_logger=Mock(), continuous=True,
            record_fn=Mock(), finalize_fn=Mock(),
        )

        # Both calls to select_multiple_items should request count=3
        assert mock_sel.call_count >= 2
        # Find actual dispatch calls (with items, not empty terminators)
        dispatch_calls = [c for c in mock_sel.call_args_list if c.kwargs.get('count') == 3]
        assert len(dispatch_calls) >= 2

    @patch("pokepoke.agents.parallel.is_item_claimable", return_value=True)
    @patch("pokepoke.agents.parallel.time.sleep")
    @patch("pokepoke.agents.parallel.terminal_ui")
    @patch("pokepoke.agents.parallel.set_executor")
    @patch("pokepoke.agents.parallel.is_shutting_down", side_effect=([False] + ([False] * 10) + [True]))
    @patch("pokepoke.agents.parallel.check_and_commit_main_repo", return_value=True)
    @patch("pokepoke.agents.parallel.get_ready_work_items")
    @patch("pokepoke.agents.parallel.select_multiple_items", return_value=[])
    @patch("pokepoke.agents.parallel._collect_done_futures", return_value=(0, False, 0, 0))
    @patch("pokepoke.agents.parallel._get_dynamic_max_agents", return_value=2)
    def test_cli_override_uses_effective_parallel_over_config(
        self, mock_dyn_max, mock_collect, mock_sel, mock_ready,
        mock_repo, mock_shut, mock_set_exec, mock_ui, mock_sleep, mock_claimable,
    ) -> None:
        """Regression (PokePoke-snio): CLI --max-agents must not be capped by config."""
        mock_ready.return_value = [_make_item(f"c{i}") for i in range(10)]

        stats = SessionStats(agent_stats=AgentStats())
        run_parallel_loop(
            effective_parallel=6, mode_name="Autonomous",
            main_repo_path="/repo", failed_claim_ids=set(),
            session_stats=stats, start_time=time.time(),
            run_logger=Mock(), continuous=True,
            record_fn=Mock(), finalize_fn=Mock(),
            cli_override=True,
        )

        assert mock_sel.call_count >= 1
        assert mock_sel.call_args_list[0].kwargs["count"] == 6

    @patch("pokepoke.agents.parallel.is_item_claimable", return_value=True)
    @patch("pokepoke.agents.parallel.time.sleep")
    @patch("pokepoke.agents.parallel.terminal_ui")
    @patch("pokepoke.agents.parallel.set_executor")
    @patch("pokepoke.agents.parallel.should_stop_after_current", return_value=False)
    @patch("pokepoke.agents.parallel.is_shutting_down")
    @patch("pokepoke.agents.parallel.check_and_commit_main_repo", return_value=True)
    @patch("pokepoke.agents.parallel.get_ready_work_items")
    @patch("pokepoke.agents.parallel.select_multiple_items")
    @patch("pokepoke.agents.parallel._collect_done_futures")
    @patch("pokepoke.agents.parallel.process_work_item")
    @patch("pokepoke.agents.parallel._get_dynamic_max_agents", return_value=1)
    def test_does_not_resubmit_while_future_tracked(
        self, mock_dyn_max, mock_pwi, mock_collect, mock_sel, mock_ready,
        mock_repo, mock_shut, mock_stop, mock_set_exec, mock_ui, mock_sleep, mock_claimable,
    ) -> None:
        """Regression: slot/claimed tracking must be based on futures (worker count).

        If a worker finishes and releases the semaphore but its future hasn't
        been collected yet, we must not consider that slot available.
        """
        item = _make_item("dup1")
        mock_ready.return_value = [item]
        mock_sel.return_value = [item]
        mock_pwi.return_value = WorkItemResult(success=True, request_count=1, stats=AgentStats())
        mock_collect.side_effect = lambda futures, failed, total, stats, logger, record_fn: (total, False, 0, 0)

        # Two full loop iterations + shutdown, accounting for the inner sleep loop checks.
        mock_shut.side_effect = [False] + ([False] * 10) + [False, True, True]

        stats = SessionStats(agent_stats=AgentStats())
        record_fn = Mock()
        finalize_fn = Mock()
        logger = Mock()

        code = run_parallel_loop(
            effective_parallel=1, mode_name="Autonomous",
            main_repo_path="/repo", failed_claim_ids=set(),
            session_stats=stats, start_time=time.time(),
            run_logger=logger, continuous=True,
            record_fn=record_fn, finalize_fn=finalize_fn,
        )

        assert code == 0
        # Must not submit again while the original future is still tracked.
        assert mock_sel.call_count == 1

    @patch("pokepoke.agents.parallel.is_item_claimable", return_value=True)
    @patch("pokepoke.agents.parallel.time.sleep")
    @patch("pokepoke.agents.parallel.terminal_ui")
    @patch("pokepoke.agents.parallel.set_executor")
    @patch("pokepoke.agents.parallel.is_shutting_down", return_value=False)
    @patch("pokepoke.agents.parallel.check_and_commit_main_repo", return_value=True)
    @patch("pokepoke.agents.parallel.get_ready_work_items")
    @patch("pokepoke.agents.parallel.select_multiple_items")
    @patch("pokepoke.agents.parallel._get_dynamic_max_agents", return_value=1)
    def test_submit_exception_releases_resources(
        self, mock_dyn_max, mock_sel, mock_ready, mock_repo,
        mock_shut, mock_set_exec, mock_ui, mock_sleep, mock_claimable,
    ) -> None:
        """executor.submit failures should release semaphore and active IDs."""
        item = _make_item("xfail")
        mock_ready.return_value = [item]
        mock_sel.return_value = [item]

        sem = threading.Semaphore(1)
        mock_executor = MagicMock()
        mock_executor.submit.side_effect = RuntimeError("submit failed")
        mock_executor.shutdown = MagicMock()

        with patch("pokepoke.agents.parallel.threading.Semaphore", return_value=sem), \
             patch("pokepoke.agents.parallel.concurrent.futures.ThreadPoolExecutor", return_value=mock_executor):
            stats = SessionStats(agent_stats=AgentStats())
            logger = Mock()

            with pytest.raises(RuntimeError):
                run_parallel_loop(
                    effective_parallel=1, mode_name="Autonomous",
                    main_repo_path="/repo", failed_claim_ids=set(),
                    session_stats=stats, start_time=time.time(),
                    run_logger=logger, continuous=True,
                    record_fn=Mock(), finalize_fn=Mock(),
                )

        assert sem.acquire(blocking=False)
        mock_executor.shutdown.assert_called_once()

    @patch("pokepoke.agents.parallel.time.sleep")
    @patch("pokepoke.agents.parallel.terminal_ui")
    @patch("pokepoke.agents.parallel.set_executor")
    @patch("pokepoke.agents.parallel.is_shutting_down", side_effect=[False, True])
    @patch("pokepoke.agents.parallel.check_and_commit_main_repo", return_value=True)
    @patch("pokepoke.agents.parallel.get_ready_work_items", side_effect=RuntimeError("db error"))
    @patch("pokepoke.agents.parallel.select_multiple_items", return_value=[])
    def test_get_ready_items_exception_handled(
        self, mock_sel, mock_ready, mock_repo, mock_shut,
        mock_set_exec, mock_ui, mock_sleep,
    ) -> None:
        """get_ready_work_items exception is caught and loop continues."""
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

    @patch("pokepoke.agents.parallel.is_item_claimable", return_value=True)
    @patch("pokepoke.agents.parallel.time.sleep")
    @patch("pokepoke.agents.parallel.terminal_ui")
    @patch("pokepoke.agents.parallel.set_executor")
    @patch("pokepoke.agents.parallel.should_stop_after_current", return_value=False)
    @patch("pokepoke.agents.parallel.is_shutting_down", return_value=False)
    @patch("pokepoke.agents.parallel.check_and_commit_main_repo", return_value=True)
    @patch("pokepoke.agents.parallel.get_ready_work_items")
    @patch("pokepoke.agents.parallel.select_multiple_items")
    @patch("pokepoke.agents.parallel.process_work_item")
    @patch("pokepoke.agents.parallel._get_dynamic_max_agents", return_value=2)
    def test_single_shot_drain_updates_stats(
        self, mock_dyn_max, mock_pwi, mock_sel, mock_ready, mock_repo,
        mock_shut, mock_stop, mock_set_exec, mock_ui, mock_sleep, mock_claimable,
    ) -> None:
        """UI stats should update after both items complete in single-shot mode.

        Previously the loop had an explicit drain path triggered by any_success.
        Now both items complete through natural loop iterations; the exit fires
        when futures is empty (not continuous and not futures).  The stats must
        show items_completed == 2 in both cases.
        """
        mock_sleep.return_value = None
        fast_item = _make_item("fast")
        slow_item = _make_item("slow")
        mock_ready.return_value = [fast_item, slow_item]
        # Extra [] entries accommodate loop iterations that fire select after
        # fast completes (futures={slow}) and after slow completes (futures={}).
        mock_sel.side_effect = [[fast_item, slow_item], [], []]

        slow_release = threading.Event()
        threading.Timer(0.05, slow_release.set).start()

        def _process(item: BeadsWorkItem, *args, **kwargs):
            if item.id == "slow":
                assert slow_release.wait(timeout=1), "Slow worker never released"
            return WorkItemResult(success=True, request_count=1, stats=AgentStats())

        mock_pwi.side_effect = _process

        stats = SessionStats(agent_stats=AgentStats())
        logger = Mock()

        def record_fn(item, result, s, _logger):
            if result.success:
                s.items_completed += 1

        code = run_parallel_loop(
            effective_parallel=2, mode_name="Autonomous",
            main_repo_path="/repo", failed_claim_ids=set(),
            session_stats=stats, start_time=time.time(),
            run_logger=logger, continuous=False,
            record_fn=record_fn, finalize_fn=Mock(),
        )

        assert code == 0
        assert slow_release.is_set()
        # Stats must be updated at least twice during the loop.
        assert mock_ui.ui.update_stats.call_count >= 2
        last_stats = mock_ui.ui.update_stats.call_args_list[-1][0][0]
        assert last_stats.items_completed == 2

    @patch("pokepoke.agents.parallel.is_item_claimable", return_value=True)
    @patch("pokepoke.agents.parallel.time.sleep")
    @patch("pokepoke.agents.parallel.terminal_ui")
    @patch("pokepoke.agents.parallel.set_executor")
    @patch("pokepoke.agents.parallel.should_stop_after_current", return_value=False)
    @patch("pokepoke.agents.parallel._collect_done_futures")
    @patch("pokepoke.agents.parallel.is_shutting_down")
    @patch("pokepoke.agents.parallel.check_and_commit_main_repo", return_value=True)
    @patch("pokepoke.agents.parallel.get_ready_work_items")
    @patch("pokepoke.agents.parallel.select_multiple_items")
    @patch("pokepoke.agents.parallel.process_work_item")
    def test_shutdown_cleanup_updates_stats(
        self, mock_pwi, mock_sel, mock_ready, mock_repo,
        mock_shut, mock_collect, mock_stop, mock_set_exec,
        mock_ui, mock_sleep, mock_claimable,
    ) -> None:
        """Draining during shutdown should push updated stats to the UI."""
        mock_sleep.return_value = None
        slow_item = _make_item("slow-shutdown")
        mock_ready.return_value = [slow_item]
        mock_sel.return_value = [slow_item]
        mock_pwi.return_value = WorkItemResult(success=True, request_count=1, stats=AgentStats())

        shutdown_flag = {"value": False}
        mock_shut.side_effect = lambda: shutdown_flag["value"]

        def collect_side_effect(futures, failed, total, stats, logger, record_fn):
            # Simulate shutdown being requested while futures are still pending.
            shutdown_flag["value"] = True
            return total, False, 0, 0

        mock_collect.side_effect = collect_side_effect

        stats = SessionStats(agent_stats=AgentStats())
        logger = Mock()

        def record_fn(item, result, s, _logger):
            if result.success:
                s.items_completed += 1

        code = run_parallel_loop(
            effective_parallel=1, mode_name="Autonomous",
            main_repo_path="/repo", failed_claim_ids=set(),
            session_stats=stats, start_time=time.time(),
            run_logger=logger, continuous=True,
            record_fn=record_fn, finalize_fn=Mock(),
        )

        assert code == 0
        # Stats are updated in the main loop; _finalize_workers also updates
        # via parallel_support.terminal_ui (separate mock).
        assert mock_ui.ui.update_stats.call_count >= 1
        last_stats = mock_ui.ui.update_stats.call_args_list[-1][0][0]
        assert last_stats.items_completed >= 1

    @patch("pokepoke.utils.process_utils.apply_memory_backpressure", side_effect=lambda s: (s, 0))
    @patch("pokepoke.agents.parallel.is_item_claimable", return_value=True)
    @patch("pokepoke.agents.parallel.time.sleep")
    @patch("pokepoke.agents.parallel.terminal_ui")
    @patch("pokepoke.agents.parallel.set_executor")
    @patch("pokepoke.agents.parallel.should_stop_after_current", return_value=False)
    @patch("pokepoke.agents.parallel.is_shutting_down")
    @patch("pokepoke.agents.parallel.check_and_commit_main_repo", return_value=True)
    @patch("pokepoke.agents.parallel.get_ready_work_items")
    @patch("pokepoke.agents.parallel.select_multiple_items")
    @patch("pokepoke.agents.parallel._collect_done_futures")
    @patch("pokepoke.agents.parallel.process_work_item")
    def test_dynamic_max_agents_change_respected(
        self, mock_pwi, mock_collect, mock_sel, mock_ready,
        mock_repo, mock_shut, mock_stop, mock_set_exec, mock_ui, mock_sleep,
        mock_claimable, mock_mem,
    ) -> None:
        """Slot count should reflect dynamic config changes without restart."""
        items = [_make_item(f"d{i}") for i in range(6)]
        mock_ready.return_value = items
        mock_pwi.return_value = WorkItemResult(success=True, request_count=1, stats=AgentStats())

        call_idx = [0]

        def collect_side(futures, failed, total, stats, logger, record_fn):
            call_idx[0] += 1
            if call_idx[0] == 2:
                futures.clear()
                return (total, True, 3, 0)
            return (total, False, 0, 0)

        mock_collect.side_effect = collect_side

        # First iteration returns 2, second returns 4 (simulates UI change)
        dynamic_values = iter([2, 4])
        mock_sel.side_effect = [items[:2], [], items[2:6], []]

        mock_shut.side_effect = [False] * 22 + [True] * 5

        with patch("pokepoke.agents.parallel._get_dynamic_max_agents", side_effect=dynamic_values):
            stats = SessionStats(agent_stats=AgentStats())
            run_parallel_loop(
                effective_parallel=2, mode_name="Autonomous",
                main_repo_path="/repo", failed_claim_ids=set(),
                session_stats=stats, start_time=time.time(),
                run_logger=Mock(), continuous=True,
                record_fn=Mock(), finalize_fn=Mock(),
            )

        # First dispatch call: count=2 (dynamic max=2, 0 active)
        assert mock_sel.call_args_list[0].kwargs['count'] == 2
        # After clear, second dispatch call: count=4 (dynamic max=4, 0 active)
        # Find the call with count=4 (skipping empty-list terminator calls)
        count_4_calls = [c for c in mock_sel.call_args_list if c.kwargs.get('count') == 4]
        assert len(count_4_calls) >= 1


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
        fut: concurrent.futures.Future = concurrent.futures.Future()
        fut.set_result(WorkItemResult(success=True, request_count=1))
        item = _make_item("boom")

        # Simulate a maintenance agent exception propagating through record_fn
        exploding_record_fn = Mock(side_effect=RuntimeError("maintenance exploded"))
        stats = SessionStats(agent_stats=AgentStats())
        logger = Mock()

        # Manually call _collect_done_futures with the exploding record_fn.
        # It must NOT raise, it must swallow the exception and log it.
        futures: dict[concurrent.futures.Future, BeadsWorkItem] = {fut: item}
        total, any_ok, successes, failures = _collect_done_futures(
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


class TestCollectDoneFuturesWait:
    """Tests for _collect_done_futures wait fallback path."""

    def test_waits_for_not_done_futures(self) -> None:
        """When no futures are immediately done, falls back to wait()."""
        # Create a future that is not immediately done but completes during wait
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            import time as _time
            fut = pool.submit(lambda: (_time.sleep(0.1), WorkItemResult(success=True, request_count=1))[1])
            item = _make_item("w1")
            futures = {fut: item}
            failed: set[str] = set()
            stats = SessionStats(agent_stats=AgentStats())
            record_fn = Mock()

            total, any_ok, successes, failures = _collect_done_futures(
                futures, failed, 0, stats, Mock(), record_fn,
            )

            assert any_ok is True
            assert record_fn.call_count == 1


# -- Dynamic parallel ceiling (PokePoke-4yvi) ---------------------------------

class TestDynamicParallelCeiling:
    """Pool/semaphore should scale to effective_parallel, not a hardcoded ceiling."""

    @patch("pokepoke.agents.parallel.time.sleep")
    @patch("pokepoke.agents.parallel.terminal_ui")
    @patch("pokepoke.agents.parallel.set_executor")
    @patch("pokepoke.agents.parallel.is_shutting_down", side_effect=[False, True])
    @patch("pokepoke.agents.parallel.check_and_commit_main_repo", return_value=True)
    @patch("pokepoke.agents.parallel.get_ready_work_items", return_value=[])
    @patch("pokepoke.agents.parallel.select_multiple_items", return_value=[])
    def test_pool_sized_above_default_when_effective_parallel_exceeds_ceiling(
        self, mock_sel, mock_ready, mock_repo, mock_shut,
        mock_set_exec, mock_ui, mock_sleep,
    ) -> None:
        """ThreadPoolExecutor should clamp max_workers to ceiling."""
        from pokepoke.agents.parallel import _DEFAULT_PARALLEL_CEILING
        stats = SessionStats(agent_stats=AgentStats())

        with patch("pokepoke.agents.parallel.concurrent.futures.ThreadPoolExecutor") as MockTPE:
            mock_executor = MagicMock()
            MockTPE.return_value = mock_executor

            run_parallel_loop(
                effective_parallel=12, mode_name="Autonomous",
                main_repo_path="/repo", failed_claim_ids=set(),
                session_stats=stats, start_time=time.time(),
                run_logger=Mock(), continuous=True,
                record_fn=Mock(), finalize_fn=Mock(),
            )

            MockTPE.assert_called_once()
            call_kwargs = MockTPE.call_args
            assert call_kwargs[1]["max_workers"] == _DEFAULT_PARALLEL_CEILING

    @patch("pokepoke.agents.parallel.time.sleep")
    @patch("pokepoke.agents.parallel.terminal_ui")
    @patch("pokepoke.agents.parallel.set_executor")
    @patch("pokepoke.agents.parallel.is_shutting_down", side_effect=[False, True])
    @patch("pokepoke.agents.parallel.check_and_commit_main_repo", return_value=True)
    @patch("pokepoke.agents.parallel.get_ready_work_items", return_value=[])
    @patch("pokepoke.agents.parallel.select_multiple_items", return_value=[])
    def test_pool_uses_effective_parallel_when_smaller_than_ceiling(
        self, mock_sel, mock_ready, mock_repo, mock_shut,
        mock_set_exec, mock_ui, mock_sleep,
    ) -> None:
        """When effective_parallel < default ceiling, pool uses effective_parallel."""
        stats = SessionStats(agent_stats=AgentStats())

        with patch("pokepoke.agents.parallel.concurrent.futures.ThreadPoolExecutor") as MockTPE:
            mock_executor = MagicMock()
            MockTPE.return_value = mock_executor

            run_parallel_loop(
                effective_parallel=3, mode_name="Autonomous",
                main_repo_path="/repo", failed_claim_ids=set(),
                session_stats=stats, start_time=time.time(),
                run_logger=Mock(), continuous=True,
                record_fn=Mock(), finalize_fn=Mock(),
            )

            call_kwargs = MockTPE.call_args
            assert call_kwargs[1]["max_workers"] == 3

    @patch("pokepoke.agents.parallel.time.sleep")
    @patch("pokepoke.agents.parallel.terminal_ui")
    @patch("pokepoke.agents.parallel.set_executor")
    @patch("pokepoke.agents.parallel.is_shutting_down", side_effect=[False, True])
    @patch("pokepoke.agents.parallel.check_and_commit_main_repo", return_value=True)
    @patch("pokepoke.agents.parallel.get_ready_work_items", return_value=[])
    @patch("pokepoke.agents.parallel.select_multiple_items", return_value=[])
    def test_warning_logged_when_exceeding_default_ceiling(
        self, mock_sel, mock_ready, mock_repo, mock_shut,
        mock_set_exec, mock_ui, mock_sleep,
    ) -> None:
        """A warning should be logged when effective_parallel > default ceiling."""
        stats = SessionStats(agent_stats=AgentStats())

        with patch("pokepoke.agents.parallel.logger") as mock_logger:
            run_parallel_loop(
                effective_parallel=10, mode_name="Autonomous",
                main_repo_path="/repo", failed_claim_ids=set(),
                session_stats=stats, start_time=time.time(),
                run_logger=Mock(), continuous=True,
                record_fn=Mock(), finalize_fn=Mock(),
            )

            mock_logger.warning.assert_called_once()
            warning_msg = mock_logger.warning.call_args[0][0]
            assert "exceeds ceiling" in warning_msg


class TestRequestSpawnAgent:
    """Test request_spawn_agent function."""

    def test_sets_wakeup_event(self) -> None:
        """Covers line 48: _spawn_wakeup.set()."""
        from pokepoke.agents.parallel import request_spawn_agent, _spawn_wakeup
        _spawn_wakeup.clear()
        request_spawn_agent()
        assert _spawn_wakeup.is_set()
        _spawn_wakeup.clear()


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


class TestParallelReplenishmentBug:
    """Regression tests for PokePoke-8o4o: batch replenishment fills all slots.

    When multiple agents exit together (or over a short window), the loop must
    replenish UP TO the configured maximum, not just one agent per iteration.
    """

    @patch("pokepoke.agents.parallel.is_item_claimable", return_value=True)
    @patch("pokepoke.agents.parallel.time.sleep")
    @patch("pokepoke.agents.parallel.terminal_ui")
    @patch("pokepoke.agents.parallel.set_executor")
    @patch("pokepoke.agents.parallel.should_stop_after_current", return_value=False)
    @patch("pokepoke.agents.parallel.is_shutting_down")
    @patch("pokepoke.agents.parallel.check_and_commit_main_repo", return_value=True)
    @patch("pokepoke.agents.parallel.get_ready_work_items")
    @patch("pokepoke.agents.parallel.select_multiple_items")
    @patch("pokepoke.agents.parallel._collect_done_futures")
    @patch("pokepoke.agents.parallel.process_work_item")
    @patch("pokepoke.agents.parallel._get_dynamic_max_agents", return_value=10)
    def test_all_agents_exit_replenishes_to_limit(
        self, mock_dyn_max, mock_pwi, mock_collect, mock_sel, mock_ready,
        mock_repo, mock_shut, mock_stop, mock_set_exec, mock_ui, mock_sleep, mock_claimable,
    ) -> None:
        """When all N agents exit, the next iteration must request N replacements.

        Regression for PokePoke-8o4o: the replacement count was 1 instead of
        (max_parallel - currently_active).
        """
        items = [_make_item(f"item-{i}") for i in range(20)]
        mock_ready.return_value = items

        call_idx = [0]

        def collect_side(futures, failed, total, stats, logger, record_fn):
            call_idx[0] += 1
            if call_idx[0] == 2:
                # Simulate all 10 agents completing simultaneously.
                # Use success_count=1 to avoid tripping the circuit breaker
                # (which triggers at _MAX_CONSECUTIVE_FAILURES=10).
                futures.clear()
                return (total, False, 1, 9)
            return (total, False, 0, 0)

        mock_collect.side_effect = collect_side
        mock_sel.side_effect = [items[:10], items[10:20]]
        # 2 full iterations (each: 1 while check + up to 10 inner sleep checks)
        mock_shut.side_effect = [False] * 22 + [True] * 5
        mock_pwi.return_value = WorkItemResult(success=False, request_count=0, stats=AgentStats())

        stats = SessionStats(agent_stats=AgentStats())
        run_parallel_loop(
            effective_parallel=10, mode_name="Autonomous",
            main_repo_path="/repo", failed_claim_ids=set(),
            session_stats=stats, start_time=time.time(),
            run_logger=Mock(), continuous=True,
            record_fn=Mock(), finalize_fn=Mock(),
        )

        # Both select calls must request count=10 (fill all slots, not just 1).
        assert mock_sel.call_count >= 2
        first_count = mock_sel.call_args_list[0].kwargs["count"]
        second_count = mock_sel.call_args_list[1].kwargs["count"]
        assert first_count == 10, f"First select should request 10 slots, got {first_count}"
        assert second_count == 10, f"Second select should request 10 slots after all exit, got {second_count}"

    @patch("pokepoke.agents.parallel.is_item_claimable", return_value=True)
    @patch("pokepoke.agents.parallel.time.sleep")
    @patch("pokepoke.agents.parallel.terminal_ui")
    @patch("pokepoke.agents.parallel.set_executor")
    @patch("pokepoke.agents.parallel.should_stop_after_current", return_value=False)
    @patch("pokepoke.agents.parallel.is_shutting_down")
    @patch("pokepoke.agents.parallel.check_and_commit_main_repo", return_value=True)
    @patch("pokepoke.agents.parallel.get_ready_work_items")
    @patch("pokepoke.agents.parallel.select_multiple_items")
    @patch("pokepoke.agents.parallel._collect_done_futures")
    @patch("pokepoke.agents.parallel.process_work_item")
    @patch("pokepoke.agents.parallel._get_dynamic_max_agents", return_value=10)
    def test_success_does_not_block_replenishment_continuous(
        self, mock_dyn_max, mock_pwi, mock_collect, mock_sel, mock_ready,
        mock_repo, mock_shut, mock_stop, mock_set_exec, mock_ui, mock_sleep, mock_claimable,
    ) -> None:
        """A successful agent must not prevent other slots from being filled in continuous mode.

        Regression for PokePoke-8o4o: when any_success=True the loop used to
        break before replenishing the remaining (max - active) empty slots.
        """
        items = [_make_item(f"item-{i}") for i in range(20)]
        mock_ready.return_value = items

        call_idx = [0]

        def collect_side(futures, failed, total, stats, logger, record_fn):
            call_idx[0] += 1
            if call_idx[0] == 2:
                # 9 failures + 1 success; all slots freed.
                futures.clear()
                return (total, True, 1, 9)  # any_success=True
            return (total, False, 0, 0)

        mock_collect.side_effect = collect_side
        mock_sel.side_effect = [items[:10], items[10:20]]
        mock_shut.side_effect = [False] * 22 + [True] * 5
        mock_pwi.return_value = WorkItemResult(success=True, request_count=1, stats=AgentStats())

        stats = SessionStats(agent_stats=AgentStats())
        run_parallel_loop(
            effective_parallel=10, mode_name="Autonomous",
            main_repo_path="/repo", failed_claim_ids=set(),
            session_stats=stats, start_time=time.time(),
            run_logger=Mock(), continuous=True,
            record_fn=Mock(), finalize_fn=Mock(),
        )

        # Even with any_success=True, replenishment must still request 10 slots.
        assert mock_sel.call_count >= 2
        second_count = mock_sel.call_args_list[1].kwargs["count"]
        assert second_count == 10, (
            f"Replenishment count should be 10 even after success, got {second_count}"
        )

    @patch("pokepoke.agents.parallel.is_item_claimable", return_value=True)
    @patch("pokepoke.agents.parallel.time.sleep")
    @patch("pokepoke.agents.parallel.terminal_ui")
    @patch("pokepoke.agents.parallel.set_executor")
    @patch("pokepoke.agents.parallel.should_stop_after_current", return_value=False)
    @patch("pokepoke.agents.parallel.is_shutting_down")
    @patch("pokepoke.agents.parallel.check_and_commit_main_repo", return_value=True)
    @patch("pokepoke.agents.parallel.get_ready_work_items")
    @patch("pokepoke.agents.parallel.select_multiple_items")
    @patch("pokepoke.agents.parallel._collect_done_futures")
    @patch("pokepoke.agents.parallel.process_work_item")
    @patch("pokepoke.agents.parallel._get_dynamic_max_agents", return_value=2)
    def test_single_shot_stops_replenishing_after_success(
        self, mock_dyn_max, mock_pwi, mock_collect, mock_sel, mock_ready,
        mock_repo, mock_shut, mock_stop, mock_set_exec, mock_ui, mock_sleep, mock_claimable,
    ) -> None:
        """Non-continuous runs stop launching new work after the first success.

        Once any worker succeeds, the parallel loop should refrain from
        replenishing additional items and instead drain the remaining
        in-flight workers before exiting.
        """
        items = [_make_item(f"item-{i}") for i in range(3)]
        mock_ready.return_value = items

        call_idx = [0]

        def collect_side(futures, failed, total, stats, logger, record_fn):
            call_idx[0] += 1
            if call_idx[0] == 1:
                # First iteration: no completions yet.
                return (total, False, 0, 0)
            if call_idx[0] == 2:
                # Second iteration: both active workers complete and at least
                # one succeeds; all slots are now free.
                futures.clear()
                return (total + 2, True, 1, 1)
            return (total, False, 0, 0)

        mock_collect.side_effect = collect_side
        mock_sel.side_effect = [items[:2], items[2:3]]
        # Provide enough values: the wait loop (lines 358-362) calls
        # is_shutting_down() up to 10 times per iteration.
        mock_shut.side_effect = [False] * 22 + [True] * 5
        mock_pwi.return_value = WorkItemResult(success=True, request_count=1, stats=AgentStats())

        stats = SessionStats(agent_stats=AgentStats())
        code = run_parallel_loop(
            effective_parallel=2, mode_name="Autonomous",
            main_repo_path="/repo", failed_claim_ids=set(),
            session_stats=stats, start_time=time.time(),
            run_logger=Mock(), continuous=False,
            record_fn=Mock(), finalize_fn=Mock(),
        )

        assert code == 0
        # Only the initial replenishment should occur; after success, no new
        # items should be selected even though slots are available.
        assert mock_sel.call_count == 1

    def test_collect_done_futures_second_sweep_catches_concurrent_completions(
        self,
    ) -> None:
        """Second sweep after FIRST_COMPLETED collects all concurrently finished futures.

        Regression for PokePoke-8o4o: without the second sweep, only the first
        completed future was detected, leaving (N-1) slots unclaimed and forcing
        the loop to add only 1 replacement instead of N.
        """
        import concurrent.futures as cf

        # Three futures all complete at approximately the same time.
        with cf.ThreadPoolExecutor(max_workers=3) as pool:
            futs = [
                pool.submit(lambda: WorkItemResult(success=True, request_count=1))
                for _ in range(3)
            ]
            items = [_make_item(f"concurrent-{i}") for i in range(3)]
            futures_dict: dict[cf.Future, BeadsWorkItem] = dict(zip(futs, items, strict=False))  # type: ignore[type-arg]

            # Wait for all to finish so they are all "done" at call time.
            cf.wait(futs, timeout=5)

            failed: set[str] = set()
            stats = SessionStats(agent_stats=AgentStats())
            record_fn = Mock()

            from pokepoke.agents.parallel import _collect_done_futures
            total, any_ok, successes, failures = _collect_done_futures(
                futures_dict, failed, 0, stats, Mock(), record_fn,
            )

        # All three must be collected in a single call — none left in futures_dict.
        assert len(futures_dict) == 0, (
            f"{len(futures_dict)} future(s) were NOT collected; "
            "replenishment would under-count available slots"
        )
        assert record_fn.call_count == 3
        assert any_ok is True
        assert successes == 3
        assert failures == 0

    def test_exception_crashed_items_not_blacklisted(self) -> None:
        """Workers that crash with exceptions must NOT be added to failed_claim_ids.

        Regression for PokePoke-8o4o: the exception handler in _collect_done_futures
        created WorkItemResult(request_count=0) which incorrectly added crashed items
        to failed_claim_ids, permanently preventing replacement agents from being
        launched for those items.
        """
        import concurrent.futures as cf

        # Simulate 3 workers that all crash with exceptions.
        futs = [cf.Future() for _ in range(3)]
        for fut in futs:
            fut.set_exception(RuntimeError("worker crashed"))
        items = [_make_item(f"crash-{i}") for i in range(3)]
        futures_dict: dict[cf.Future, BeadsWorkItem] = dict(zip(futs, items, strict=False))  # type: ignore[type-arg]

        failed: set[str] = set()
        stats = SessionStats(agent_stats=AgentStats())
        record_fn = Mock()

        from pokepoke.agents.parallel import _collect_done_futures
        _collect_done_futures(futures_dict, failed, 0, stats, Mock(), record_fn)

        # No crashed items should be in failed_claim_ids — they must remain
        # eligible for retry so replacement agents can pick them up.
        assert len(failed) == 0, (
            f"Exception-crashed items were blacklisted: {failed}; "
            "this prevents replacement agents from being launched"
        )
        assert len(futures_dict) == 0  # all collected
        assert record_fn.call_count == 3


# ── Circuit Breaker ──────────────────────────────────────────────────────────


class TestCircuitBreaker:
    """Tests for the circuit breaker that stops dispatch after consecutive failures."""

    @patch("pokepoke.agents.parallel.is_item_claimable", return_value=True)
    @patch("pokepoke.agents.parallel.time.sleep")
    @patch("pokepoke.agents.parallel.terminal_ui")
    @patch("pokepoke.agents.parallel.set_executor")
    @patch("pokepoke.agents.parallel.should_stop_after_current", return_value=False)
    @patch("pokepoke.agents.parallel.is_shutting_down")
    @patch("pokepoke.agents.parallel.check_and_commit_main_repo", return_value=True)
    @patch("pokepoke.agents.parallel.get_ready_work_items")
    @patch("pokepoke.agents.parallel.select_multiple_items")
    @patch("pokepoke.agents.parallel._collect_done_futures")
    @patch("pokepoke.agents.parallel.process_work_item")
    @patch("pokepoke.agents.parallel._get_dynamic_max_agents", return_value=5)
    def test_circuit_breaker_trips_after_max_consecutive_failures(
        self, mock_dyn_max, mock_pwi, mock_collect, mock_sel, mock_ready,
        mock_repo, mock_shut, mock_stop, mock_set_exec, mock_ui, mock_sleep, mock_claimable,
    ) -> None:
        """After _MAX_CONSECUTIVE_FAILURES *rounds* of all-failures, no new workers dispatched."""
        from pokepoke.agents.parallel import _MAX_CONSECUTIVE_FAILURES

        items = [_make_item(f"cb-{i}") for i in range(_MAX_CONSECUTIVE_FAILURES * 2)]
        mock_ready.return_value = items

        call_idx = [0]

        def collect_side(futures, failed, total, stats, logger, record_fn):
            call_idx[0] += 1
            if call_idx[0] >= 2:
                # Report 1 failure per round; circuit breaker trips after
                # _MAX_CONSECUTIVE_FAILURES rounds (not individual item count).
                futures.clear()
                return (total, False, 0, 1)
            return (total, False, 0, 0)

        mock_collect.side_effect = collect_side
        mock_sel.return_value = items[:5]
        # Need enough False entries: each outer iteration consumes up to 11 calls.
        mock_shut.side_effect = [False] * (_MAX_CONSECUTIVE_FAILURES * 20) + [True] * 5
        mock_pwi.return_value = WorkItemResult(success=False, request_count=0, stats=AgentStats())

        stats = SessionStats(agent_stats=AgentStats())
        logger = Mock()

        code = run_parallel_loop(
            effective_parallel=5, mode_name="Autonomous",
            main_repo_path="/repo", failed_claim_ids=set(),
            session_stats=stats, start_time=time.time(),
            run_logger=logger, continuous=True,
            record_fn=Mock(), finalize_fn=Mock(),
        )

        assert code == 1
        # Should log circuit breaker tripping.
        assert any(
            "Circuit breaker" in str(call) or "circuit breaker" in str(call)
            for call in logger.log_orchestrator.call_args_list
        )

    @patch("pokepoke.agents.parallel.is_item_claimable", return_value=True)
    @patch("pokepoke.agents.parallel.time.sleep")
    @patch("pokepoke.agents.parallel.terminal_ui")
    @patch("pokepoke.agents.parallel.set_executor")
    @patch("pokepoke.agents.parallel.should_stop_after_current", return_value=False)
    @patch("pokepoke.agents.parallel.is_shutting_down")
    @patch("pokepoke.agents.parallel.check_and_commit_main_repo", return_value=True)
    @patch("pokepoke.agents.parallel.get_ready_work_items")
    @patch("pokepoke.agents.parallel.select_multiple_items")
    @patch("pokepoke.agents.parallel._collect_done_futures")
    @patch("pokepoke.agents.parallel.process_work_item")
    @patch("pokepoke.agents.parallel._get_dynamic_max_agents", return_value=2)
    def test_circuit_breaker_resets_on_success(
        self, mock_dyn_max, mock_pwi, mock_collect, mock_sel, mock_ready,
        mock_repo, mock_shut, mock_stop, mock_set_exec, mock_ui, mock_sleep, mock_claimable,
    ) -> None:
        """A successful round resets the consecutive failure counter."""
        items = [_make_item(f"rs-{i}") for i in range(10)]
        mock_ready.return_value = items

        call_idx = [0]

        def collect_side(futures, failed, total, stats, logger, record_fn):
            call_idx[0] += 1
            if call_idx[0] == 2:
                # 5 failures in one round → counts as 1 failure-round
                futures.clear()
                return (total, False, 0, 5)
            if call_idx[0] == 4:
                # 1 success — resets counter
                futures.clear()
                return (total, True, 1, 0)
            if call_idx[0] == 6:
                # 5 more failures in one round → counts as 1 failure-round.
                # Total rounds-without-success = 1 (reset by earlier success).
                futures.clear()
                return (total, False, 0, 5)
            return (total, False, 0, 0)

        mock_collect.side_effect = collect_side
        mock_sel.return_value = items[:2]
        mock_shut.side_effect = [False] * 50 + [True] * 5
        mock_pwi.return_value = WorkItemResult(success=True, request_count=1, stats=AgentStats())

        stats = SessionStats(agent_stats=AgentStats())

        code = run_parallel_loop(
            effective_parallel=2, mode_name="Autonomous",
            main_repo_path="/repo", failed_claim_ids=set(),
            session_stats=stats, start_time=time.time(),
            run_logger=Mock(), continuous=True,
            record_fn=Mock(), finalize_fn=Mock(),
        )

        # Should NOT trip circuit breaker (failures reset by success).
        assert code == 0


class TestCollectDoneFuturesSuccessFailureCounts:
    """Tests that _collect_done_futures returns correct success/failure counts."""

    def test_mixed_results_counts(self) -> None:
        """Mixed successes and failures return correct counts."""
        futs = []
        items = []
        for i in range(3):
            fut = concurrent.futures.Future()
            fut.set_result(WorkItemResult(success=True, request_count=1))
            futs.append(fut)
            items.append(_make_item(f"s{i}"))
        for i in range(2):
            fut = concurrent.futures.Future()
            fut.set_result(WorkItemResult(success=False, request_count=1))
            futs.append(fut)
            items.append(_make_item(f"f{i}"))

        futures_dict = dict(zip(futs, items, strict=False))
        stats = SessionStats(agent_stats=AgentStats())

        total, any_ok, successes, failures = _collect_done_futures(
            futures_dict, set(), 0, stats, Mock(), Mock(),
        )

        assert successes == 3
        assert failures == 2
        assert any_ok is True
        assert total == 5
