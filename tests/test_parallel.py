"""Tests for the parallel orchestrator loop module."""

import concurrent.futures
import threading
import time
from unittest.mock import Mock, patch, MagicMock

import pytest

from pokepoke.types import AgentStats, BeadsWorkItem, SessionStats, WorkItemResult
from pokepoke.parallel import (
    _parallel_process_item,
    _collect_done_futures,
    run_parallel_loop,
)


def _make_item(item_id: str = "t1") -> BeadsWorkItem:
    return BeadsWorkItem(
        id=item_id, title=f"Title-{item_id}", status="open",
        priority=1, issue_type="task",
    )


# ΓöÇΓöÇ _parallel_process_item ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ

class TestParallelProcessItem:
    """Tests for _parallel_process_item wrapper."""

    @patch("pokepoke.parallel.terminal_ui")
    @patch("pokepoke.parallel.process_work_item")
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
            "agent",
            iteration=1,
            status="running",
            work_item_id="t1",
            work_item_title="Title-t1",
        )
        mock_ui.ui.push_agent_status.assert_any_call(
            "t1",
            "agent",
            iteration=1,
            status="success",
            work_item_id="t1",
            work_item_title="Title-t1",
        )

    @patch("pokepoke.parallel.terminal_ui")
    @patch("pokepoke.parallel.process_work_item", side_effect=RuntimeError("boom"))
    def test_exception_releases_resources(self, mock_pwi: Mock, mock_ui: Mock) -> None:
        sem = threading.Semaphore(0)

        with pytest.raises(RuntimeError):
            _parallel_process_item(_make_item(), Mock(), sem)

        assert sem.acquire(blocking=False)
        # Agent status should be set to failed on exception
        mock_ui.ui.push_agent_status.assert_any_call(
            "t1",
            "agent",
            iteration=1,
            status="failed",
            work_item_id="t1",
            work_item_title="Title-t1",
        )

    @patch("pokepoke.parallel.terminal_ui")
    @patch("pokepoke.parallel.process_work_item")
    def test_failure_sets_agent_failed_status(self, mock_pwi: Mock, mock_ui: Mock) -> None:
        """A work item that returns success=False should set agent status to failed."""
        mock_pwi.return_value = WorkItemResult(success=False, request_count=1)
        sem = threading.Semaphore(0)

        result = _parallel_process_item(_make_item(), Mock(), sem)

        assert result.success is False
        mock_ui.ui.push_agent_status.assert_any_call(
            "t1",
            "agent",
            iteration=1,
            status="failed",
            work_item_id="t1",
            work_item_title="Title-t1",
        )

    @patch("pokepoke.parallel.terminal_ui")
    @patch("pokepoke.parallel.process_work_item")
    def test_output_routed_via_agent_output_for(self, mock_pwi: Mock, mock_ui: Mock) -> None:
        """Verify that agent_output_for context manager is used for output routing."""
        mock_pwi.return_value = WorkItemResult(success=True, request_count=1)
        sem = threading.Semaphore(0)

        _parallel_process_item(_make_item(), Mock(), sem)

        # Should use agent_output_for to route output
        mock_ui.ui.agent_output_for.assert_called_once_with("t1")

    @patch("pokepoke.parallel.terminal_ui")
    @patch("pokepoke.parallel.process_work_item")
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

    @patch("pokepoke.parallel.terminal_ui")
    @patch("pokepoke.parallel.process_work_item")
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

        total, any_ok = _collect_done_futures(
            futures, failed, 0, stats, logger, record_fn,
        )

        assert total == 2
        assert any_ok is True
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
        """An exception in a future is handled gracefully."""
        fut: concurrent.futures.Future = concurrent.futures.Future()
        fut.set_exception(RuntimeError("kaboom"))
        item = _make_item("err1")
        futures = {fut: item}
        failed: set[str] = set()
        stats = SessionStats(agent_stats=AgentStats())
        logger = Mock()
        record_fn = Mock()

        total, any_ok = _collect_done_futures(
            futures, failed, 5, stats, logger, record_fn,
        )

        assert total == 5  # no requests added
        assert any_ok is False
        assert "err1" in failed
        logger.log_orchestrator.assert_called()
        record_fn.assert_called_once()

    def test_no_done_futures_returns_zero(self) -> None:
        """When no futures are done, returns unchanged totals."""
        stats = SessionStats(agent_stats=AgentStats())
        record_fn = Mock()
        # Empty dict
        total, any_ok = _collect_done_futures(
            {}, set(), 3, stats, Mock(), record_fn,
        )
        assert total == 3
        assert any_ok is False
        record_fn.assert_not_called()


# ΓöÇΓöÇ run_parallel_loop ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ

class TestRunParallelLoop:
    """Tests for run_parallel_loop."""

    @patch("pokepoke.parallel.time.sleep")
    @patch("pokepoke.parallel.terminal_ui")
    @patch("pokepoke.parallel.set_executor")
    @patch("pokepoke.parallel.is_shutting_down", side_effect=[False, True])
    @patch("pokepoke.parallel.check_and_commit_main_repo", return_value=True)
    @patch("pokepoke.parallel.get_ready_work_items", return_value=[])
    @patch("pokepoke.parallel.select_multiple_items", return_value=[])
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

    @patch("pokepoke.parallel.time.sleep")
    @patch("pokepoke.parallel.terminal_ui")
    @patch("pokepoke.parallel.set_executor")
    @patch("pokepoke.parallel.is_shutting_down", return_value=False)
    @patch("pokepoke.parallel.check_and_commit_main_repo", return_value=False)
    @patch("pokepoke.parallel.get_ready_work_items", return_value=[])
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

    @patch("pokepoke.parallel.time.sleep")
    @patch("pokepoke.parallel.terminal_ui")
    @patch("pokepoke.parallel.set_executor")
    @patch("pokepoke.parallel.is_shutting_down", side_effect=[False, True, True])
    @patch("pokepoke.parallel.check_and_commit_main_repo", return_value=True)
    @patch("pokepoke.parallel.get_ready_work_items")
    @patch("pokepoke.parallel.select_multiple_items")
    @patch("pokepoke.parallel.process_work_item")
    def test_submits_and_collects_item(
        self, mock_pwi, mock_sel, mock_ready,
        mock_repo, mock_shut, mock_set_exec, mock_ui, mock_sleep,
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

    @patch("pokepoke.parallel.time.sleep")
    @patch("pokepoke.parallel.terminal_ui")
    @patch("pokepoke.parallel.set_executor")
    @patch("pokepoke.parallel.should_stop_after_current", return_value=False)
    @patch("pokepoke.parallel.is_shutting_down")
    @patch("pokepoke.parallel.check_and_commit_main_repo", return_value=True)
    @patch("pokepoke.parallel.get_ready_work_items")
    @patch("pokepoke.parallel.select_multiple_items")
    @patch("pokepoke.parallel._collect_done_futures")
    @patch("pokepoke.parallel.process_work_item")
    @patch("pokepoke.parallel._get_dynamic_max_agents", return_value=3)
    def test_refills_all_slots_after_completions(
        self, mock_dyn_max, mock_pwi, mock_collect, mock_sel, mock_ready,
        mock_repo, mock_shut, mock_stop, mock_set_exec, mock_ui, mock_sleep,
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
                return (total, True)
            return (total, False)

        mock_collect.side_effect = collect_side
        mock_sel.side_effect = [items[:3], items[3:6]]

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
        for call in mock_sel.call_args_list[:2]:
            assert call.kwargs['count'] == 3

    @patch("pokepoke.parallel.time.sleep")
    @patch("pokepoke.parallel.terminal_ui")
    @patch("pokepoke.parallel.set_executor")
    @patch("pokepoke.parallel.should_stop_after_current", return_value=False)
    @patch("pokepoke.parallel.is_shutting_down")
    @patch("pokepoke.parallel.check_and_commit_main_repo", return_value=True)
    @patch("pokepoke.parallel.get_ready_work_items")
    @patch("pokepoke.parallel.select_multiple_items")
    @patch("pokepoke.parallel._collect_done_futures")
    @patch("pokepoke.parallel.process_work_item")
    @patch("pokepoke.parallel._get_dynamic_max_agents", return_value=1)
    def test_does_not_resubmit_while_future_tracked(
        self, mock_dyn_max, mock_pwi, mock_collect, mock_sel, mock_ready,
        mock_repo, mock_shut, mock_stop, mock_set_exec, mock_ui, mock_sleep,
    ) -> None:
        """Regression: slot/claimed tracking must be based on futures (worker count).

        If a worker finishes and releases the semaphore but its future hasn't
        been collected yet, we must not consider that slot available.
        """
        item = _make_item("dup1")
        mock_ready.return_value = [item]
        mock_sel.return_value = [item]
        mock_pwi.return_value = WorkItemResult(success=True, request_count=1, stats=AgentStats())
        mock_collect.side_effect = lambda futures, failed, total, stats, logger, record_fn: (total, False)

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

    @patch("pokepoke.parallel.time.sleep")
    @patch("pokepoke.parallel.terminal_ui")
    @patch("pokepoke.parallel.set_executor")
    @patch("pokepoke.parallel.is_shutting_down", return_value=False)
    @patch("pokepoke.parallel.check_and_commit_main_repo", return_value=True)
    @patch("pokepoke.parallel.get_ready_work_items")
    @patch("pokepoke.parallel.select_multiple_items")
    @patch("pokepoke.parallel._get_dynamic_max_agents", return_value=1)
    def test_submit_exception_releases_resources(
        self, mock_dyn_max, mock_sel, mock_ready, mock_repo,
        mock_shut, mock_set_exec, mock_ui, mock_sleep,
    ) -> None:
        """executor.submit failures should release semaphore and active IDs."""
        item = _make_item("xfail")
        mock_ready.return_value = [item]
        mock_sel.return_value = [item]

        sem = threading.Semaphore(1)
        mock_executor = MagicMock()
        mock_executor.submit.side_effect = RuntimeError("submit failed")
        mock_executor.shutdown = MagicMock()

        with patch("pokepoke.parallel.threading.Semaphore", return_value=sem), \
             patch("pokepoke.parallel.concurrent.futures.ThreadPoolExecutor", return_value=mock_executor):
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

    @patch("pokepoke.parallel.time.sleep")
    @patch("pokepoke.parallel.terminal_ui")
    @patch("pokepoke.parallel.set_executor")
    @patch("pokepoke.parallel.is_shutting_down", side_effect=[False, True])
    @patch("pokepoke.parallel.check_and_commit_main_repo", return_value=True)
    @patch("pokepoke.parallel.get_ready_work_items", side_effect=RuntimeError("db error"))
    @patch("pokepoke.parallel.select_multiple_items", return_value=[])
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

    @patch("pokepoke.parallel.time.sleep")
    @patch("pokepoke.parallel.terminal_ui")
    @patch("pokepoke.parallel.set_executor")
    @patch("pokepoke.parallel.cancel_stop_after_current")
    @patch("pokepoke.parallel.should_stop_after_current", return_value=True)
    @patch("pokepoke.parallel.is_shutting_down", return_value=False)
    @patch("pokepoke.parallel.check_and_commit_main_repo", return_value=True)
    @patch("pokepoke.parallel.get_ready_work_items", return_value=[])
    @patch("pokepoke.parallel.select_multiple_items", return_value=[])
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

    @patch("pokepoke.parallel.time.sleep")
    @patch("pokepoke.parallel.terminal_ui")
    @patch("pokepoke.parallel.set_executor")
    @patch("pokepoke.parallel.is_shutting_down", side_effect=[False, True])
    @patch("pokepoke.parallel.check_and_commit_main_repo", return_value=True)
    @patch("pokepoke.parallel.get_ready_work_items")
    @patch("pokepoke.parallel.select_multiple_items", return_value=[])
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

    @patch("pokepoke.parallel.time.sleep")
    @patch("pokepoke.parallel.terminal_ui")
    @patch("pokepoke.parallel.set_executor")
    @patch("pokepoke.parallel.is_shutting_down", side_effect=[False, True])
    @patch("pokepoke.parallel.check_and_commit_main_repo", return_value=True)
    @patch("pokepoke.parallel.get_ready_work_items")
    @patch("pokepoke.parallel.select_multiple_items", return_value=[])
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

    @patch("pokepoke.parallel.time.sleep")
    @patch("pokepoke.parallel.terminal_ui")
    @patch("pokepoke.parallel.set_executor")
    @patch("pokepoke.parallel.should_stop_after_current", return_value=False)
    @patch("pokepoke.parallel.is_shutting_down", return_value=False)
    @patch("pokepoke.parallel.check_and_commit_main_repo", return_value=True)
    @patch("pokepoke.parallel.get_ready_work_items")
    @patch("pokepoke.parallel.select_multiple_items")
    @patch("pokepoke.parallel.process_work_item")
    @patch("pokepoke.parallel._get_dynamic_max_agents", return_value=2)
    def test_single_shot_drain_updates_stats(
        self, mock_dyn_max, mock_pwi, mock_sel, mock_ready, mock_repo,
        mock_shut, mock_stop, mock_set_exec, mock_ui, mock_sleep,
    ) -> None:
        """UI stats should update after draining remaining futures in single-shot mode."""
        mock_sleep.return_value = None
        fast_item = _make_item("fast")
        slow_item = _make_item("slow")
        mock_ready.return_value = [fast_item, slow_item]
        mock_sel.side_effect = [[fast_item, slow_item], []]

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
        # First call happens inside the main loop, second after drain.
        assert mock_ui.ui.update_stats.call_count >= 2
        last_stats = mock_ui.ui.update_stats.call_args_list[-1][0][0]
        assert last_stats.items_completed == 2

    @patch("pokepoke.parallel.time.sleep")
    @patch("pokepoke.parallel.terminal_ui")
    @patch("pokepoke.parallel.set_executor")
    @patch("pokepoke.parallel.should_stop_after_current", return_value=False)
    @patch("pokepoke.parallel._collect_done_futures")
    @patch("pokepoke.parallel.is_shutting_down")
    @patch("pokepoke.parallel.check_and_commit_main_repo", return_value=True)
    @patch("pokepoke.parallel.get_ready_work_items")
    @patch("pokepoke.parallel.select_multiple_items")
    @patch("pokepoke.parallel.process_work_item")
    def test_shutdown_cleanup_updates_stats(
        self, mock_pwi, mock_sel, mock_ready, mock_repo,
        mock_shut, mock_collect, mock_stop, mock_set_exec,
        mock_ui, mock_sleep,
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
            return total, False

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
        # The final snapshot from the cleanup path should include the completed item.
        assert mock_ui.ui.update_stats.call_count >= 2
        last_stats = mock_ui.ui.update_stats.call_args_list[-1][0][0]
        assert last_stats.items_completed == 1

    @patch("pokepoke.parallel.time.sleep")
    @patch("pokepoke.parallel.terminal_ui")
    @patch("pokepoke.parallel.set_executor")
    @patch("pokepoke.parallel.should_stop_after_current", return_value=False)
    @patch("pokepoke.parallel.is_shutting_down")
    @patch("pokepoke.parallel.check_and_commit_main_repo", return_value=True)
    @patch("pokepoke.parallel.get_ready_work_items")
    @patch("pokepoke.parallel.select_multiple_items")
    @patch("pokepoke.parallel._collect_done_futures")
    @patch("pokepoke.parallel.process_work_item")
    def test_dynamic_max_agents_change_respected(
        self, mock_pwi, mock_collect, mock_sel, mock_ready,
        mock_repo, mock_shut, mock_stop, mock_set_exec, mock_ui, mock_sleep,
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
                return (total, True)
            return (total, False)

        mock_collect.side_effect = collect_side

        # First iteration returns 2, second returns 4 (simulates UI change)
        dynamic_values = iter([2, 4])
        mock_sel.side_effect = [items[:2], items[2:6]]

        mock_shut.side_effect = [False] * 22 + [True] * 5

        with patch("pokepoke.parallel._get_dynamic_max_agents", side_effect=dynamic_values):
            stats = SessionStats(agent_stats=AgentStats())
            run_parallel_loop(
                effective_parallel=2, mode_name="Autonomous",
                main_repo_path="/repo", failed_claim_ids=set(),
                session_stats=stats, start_time=time.time(),
                run_logger=Mock(), continuous=True,
                record_fn=Mock(), finalize_fn=Mock(),
            )

        # First call: count=2 (dynamic max=2, 0 active)
        assert mock_sel.call_args_list[0].kwargs['count'] == 2
        # Second call: count=4 (dynamic max=4, 0 active after clear)
        assert mock_sel.call_args_list[1].kwargs['count'] == 4


class TestContinuousModeLoopBack:
    """Regression tests for PokePoke-5arw: continuous mode should loop after all workers finish."""

    @patch("pokepoke.parallel.time.sleep")
    @patch("pokepoke.parallel.terminal_ui")
    @patch("pokepoke.parallel.set_executor")
    @patch("pokepoke.parallel.is_shutting_down", side_effect=[False, True])
    @patch("pokepoke.parallel.check_and_commit_main_repo", return_value=True)
    @patch("pokepoke.parallel.get_ready_work_items", return_value=[])
    @patch("pokepoke.parallel.select_multiple_items", return_value=[])
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
        # Logger should note the retry, not an exit.
        retry_logged = any(
            "retry" in str(call) or "sleeping" in str(call)
            for call in logger.log_orchestrator.call_args_list
        )
        assert retry_logged, "Expected continuous-mode retry log message"

    @patch("pokepoke.parallel.time.sleep")
    @patch("pokepoke.parallel.terminal_ui")
    @patch("pokepoke.parallel.set_executor")
    @patch("pokepoke.parallel.is_shutting_down", side_effect=[False, True])
    @patch("pokepoke.parallel.check_and_commit_main_repo", return_value=True)
    @patch("pokepoke.parallel.get_ready_work_items", return_value=[])
    @patch("pokepoke.parallel.select_multiple_items", return_value=[])
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

        # Non-continuous mode exits without looping; no items = no success → code 1
        assert code == 1
        finalize_fn.assert_called_once()
        # Should NOT have done a retry sleep; exited immediately.
        retry_logged = any(
            "retry" in str(call)
            for call in logger.log_orchestrator.call_args_list
        )
        assert not retry_logged, "Non-continuous mode should not retry"

    @patch("pokepoke.parallel.time.sleep")
    @patch("pokepoke.parallel.terminal_ui")
    @patch("pokepoke.parallel.set_executor")
    @patch("pokepoke.parallel.is_shutting_down", side_effect=[False, True])
    @patch("pokepoke.parallel.check_and_commit_main_repo", return_value=True)
    @patch("pokepoke.parallel.get_ready_work_items", return_value=[])
    @patch("pokepoke.parallel.select_multiple_items", return_value=[])
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
        total, any_ok = _collect_done_futures(
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

            total, any_ok = _collect_done_futures(
                futures, failed, 0, stats, Mock(), record_fn,
            )

            assert any_ok is True
            assert record_fn.call_count == 1
