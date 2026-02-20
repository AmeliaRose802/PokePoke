"""Tests for the parallel orchestrator loop module."""

import concurrent.futures
import threading
import time
from unittest.mock import Mock, patch, MagicMock

import pytest

from pokepoke.types import AgentStats, BeadsWorkItem, ModelCompletionRecord, SessionStats
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


# ── _parallel_process_item ────────────────────────────────────

class TestParallelProcessItem:
    """Tests for _parallel_process_item wrapper."""

    @patch("pokepoke.parallel.terminal_ui")
    @patch("pokepoke.parallel.process_work_item")
    def test_success_releases_resources(self, mock_pwi: Mock, mock_ui: Mock) -> None:
        mock_pwi.return_value = (True, 1, None, 0, 0, None)
        sem = threading.Semaphore(0)

        result = _parallel_process_item(_make_item(), Mock(), sem)

        assert result == (True, 1, None, 0, 0, None)
        assert sem.acquire(blocking=False)
        # Agent status should be registered and updated
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
        mock_pwi.return_value = (False, 1, None, 0, 0, None)
        sem = threading.Semaphore(0)

        result = _parallel_process_item(_make_item(), Mock(), sem)

        assert result[0] is False
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
        mock_pwi.return_value = (True, 1, None, 0, 0, None)
        sem = threading.Semaphore(0)

        _parallel_process_item(_make_item(), Mock(), sem)

        # Should use agent_output_for to route output
        mock_ui.ui.agent_output_for.assert_called_once_with("t1")


# ── _collect_done_futures ─────────────────────────────────────

class TestCollectDoneFutures:
    """Tests for _collect_done_futures helper."""

    def test_collects_done_future(self) -> None:
        """A completed future is collected and record_fn is called."""
        fut: concurrent.futures.Future = concurrent.futures.Future()
        fut.set_result((True, 2, AgentStats(), 1, 1, None))
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
        fut.set_result((False, 0, None, 0, 0, None))
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


# ── run_parallel_loop ─────────────────────────────────────────

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
    @patch("pokepoke.parallel.is_shutting_down", side_effect=[False, True])
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
        mock_pwi.return_value = (True, 1, AgentStats(), 0, 1, None)

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
    def test_does_not_resubmit_while_future_tracked(
        self, mock_pwi, mock_collect, mock_sel, mock_ready,
        mock_repo, mock_shut, mock_stop, mock_set_exec, mock_ui, mock_sleep,
    ) -> None:
        """Regression: slot/claimed tracking must be based on futures (worker count).

        If a worker finishes and releases the semaphore but its future hasn't
        been collected yet, we must not consider that slot available.
        """
        item = _make_item("dup1")
        mock_ready.return_value = [item]
        mock_sel.return_value = [item]
        mock_pwi.return_value = (True, 1, AgentStats(), 0, 0, None)
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
    def test_submit_exception_releases_resources(
        self, mock_sel, mock_ready, mock_repo,
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


class TestCollectDoneFuturesWait:
    """Tests for _collect_done_futures wait fallback path."""

    def test_waits_for_not_done_futures(self) -> None:
        """When no futures are immediately done, falls back to wait()."""
        # Create a future that is not immediately done but completes during wait
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            import time as _time
            fut = pool.submit(lambda: (_time.sleep(0.1), (True, 1, None, 0, 0, None))[1])
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
