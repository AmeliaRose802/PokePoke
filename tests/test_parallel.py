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

    @patch("pokepoke.parallel.process_work_item")
    def test_success_releases_resources(self, mock_pwi: Mock) -> None:
        mock_pwi.return_value = (True, 1, None, 0, 0, None)
        sem = threading.Semaphore(1)
        ids = {"t1"}
        lock = threading.Lock()

        result = _parallel_process_item(_make_item(), Mock(), sem, ids, lock)

        assert result == (True, 1, None, 0, 0, None)
        assert "t1" not in ids
        assert sem.acquire(blocking=False)

    @patch("pokepoke.parallel.process_work_item", side_effect=RuntimeError("boom"))
    def test_exception_releases_resources(self, mock_pwi: Mock) -> None:
        sem = threading.Semaphore(1)
        ids = {"t1"}
        lock = threading.Lock()

        with pytest.raises(RuntimeError):
            _parallel_process_item(_make_item(), Mock(), sem, ids, lock)

        assert "t1" not in ids
        assert sem.acquire(blocking=False)


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
