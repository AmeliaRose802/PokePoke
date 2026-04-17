"""Tests for worker finalization and cleanup functions.

This module tests:
- finalize_workers: Completing and collecting worker results
- _drain_orphaned_futures: Cleaning up incomplete worker tasks
"""

import concurrent.futures
import time
from unittest.mock import MagicMock, Mock, patch

from pokepoke.agents.parallel_support import (
    _drain_orphaned_futures,
    finalize_workers,
)
from pokepoke.types import AgentStats, BeadsWorkItem, SessionStats, WorkItemResult


def _make_item(item_id: str = "t1") -> BeadsWorkItem:
    return BeadsWorkItem(
        id=item_id, title=f"Title-{item_id}", status="open",
        priority=1, issue_type="task",
    )


class TestFinalizeWorkers:
    """Tests for finalize_workers."""

    @patch("pokepoke.agents.parallel_support.terminal_ui")
    def test_empty_futures(self, mock_tui):
        stats = SessionStats(agent_stats=AgentStats())
        run_logger = MagicMock()
        total, timeout = finalize_workers({}, stats, time.time(), 0, run_logger, Mock())
        assert total == 0
        assert timeout is False

    @patch("pokepoke.agents.parallel_support.terminal_ui")
    def test_successful_worker(self, mock_tui):
        item = _make_item("s1")
        result = WorkItemResult(success=True, request_count=3)
        fut = concurrent.futures.Future()
        fut.set_result(result)
        stats = SessionStats(agent_stats=AgentStats())
        run_logger = MagicMock()
        record_fn = Mock()
        total, timeout = finalize_workers({fut: item}, stats, time.time(), 5, run_logger, record_fn)
        assert total == 8  # 5 + 3
        assert timeout is False
        record_fn.assert_called_once()

    @patch("pokepoke.agents.parallel_support.terminal_ui")
    def test_failed_worker(self, mock_tui):
        item = _make_item("f1")
        fut = concurrent.futures.Future()
        fut.set_exception(RuntimeError("boom"))
        stats = SessionStats(agent_stats=AgentStats())
        run_logger = MagicMock()
        record_fn = Mock()
        total, timeout = finalize_workers({fut: item}, stats, time.time(), 2, run_logger, record_fn)
        assert total == 2  # no request_count added from failed result
        assert timeout is False
        record_fn.assert_called_once()

    @patch("pokepoke.agents.parallel_support.terminal_ui")
    def test_record_fn_exception(self, mock_tui):
        """record_fn raising doesn't crash finalize_workers."""
        item = _make_item("r1")
        result = WorkItemResult(success=True, request_count=1)
        fut = concurrent.futures.Future()
        fut.set_result(result)
        stats = SessionStats(agent_stats=AgentStats())
        run_logger = MagicMock()
        record_fn = Mock(side_effect=ValueError("record error"))
        total, timeout = finalize_workers({fut: item}, stats, time.time(), 0, run_logger, record_fn)
        assert total == 1
        assert timeout is False

    @patch("pokepoke.agents.parallel_support.terminal_ui")
    @patch("pokepoke.agents.parallel_support._drain_orphaned_futures")
    @patch("pokepoke.agents.parallel_support.concurrent.futures.as_completed")
    def test_timeout_drains_orphans(self, mock_as_completed, mock_drain, mock_tui):
        """Timeout triggers drain of orphaned futures."""
        mock_as_completed.side_effect = concurrent.futures.TimeoutError()
        item = _make_item("t1")
        fut = concurrent.futures.Future()
        futures = {fut: item}
        stats = SessionStats(agent_stats=AgentStats())
        run_logger = MagicMock()
        record_fn = Mock()
        _total, timeout = finalize_workers(futures, stats, time.time(), 0, run_logger, record_fn)
        assert timeout is True
        mock_drain.assert_called_once()


class TestDrainOrphanedFutures:
    """Tests for _drain_orphaned_futures."""

    @patch("pokepoke.agents.parallel_support.terminal_ui")
    @patch("pokepoke.agents.parallel.unassign_with_retry")
    def test_empty_futures_noop(self, mock_unassign, mock_tui):
        """Empty futures dict is a no-op."""
        futures: dict = {}
        run_logger = MagicMock()
        _drain_orphaned_futures(futures, SessionStats(agent_stats=AgentStats()), time.time(), run_logger, Mock())
        mock_unassign.assert_not_called()

    @patch("pokepoke.agents.parallel_support.terminal_ui")
    @patch("pokepoke.agents.parallel.unassign_with_retry")
    def test_drains_and_records_orphans(self, mock_unassign, mock_tui):
        """Done futures are recorded. Successful ones NOT unassigned. In-progress ones preserved."""
        item1 = _make_item("o1")
        item2 = _make_item("o2")
        fut1 = concurrent.futures.Future()
        fut2 = concurrent.futures.Future()
        # fut1 still running (not done), fut2 completed successfully
        fut2.set_result(WorkItemResult(success=True, request_count=5))
        futures = {fut1: item1, fut2: item2}
        stats = SessionStats(agent_stats=AgentStats())
        run_logger = MagicMock()
        record_fn = Mock()
        mock_unassign.return_value = True

        _drain_orphaned_futures(futures, stats, time.time(), run_logger, record_fn)

        assert len(futures) == 0  # Dict is cleared
        # Only fut2 (done) is recorded; fut1 (in-progress) is skipped entirely
        assert record_fn.call_count == 1
        # fut1 is in-progress — NOT unassigned (worktree preserved)
        # fut2 is successful — NOT unassigned (already finalized)
        mock_unassign.assert_not_called()
        # fut2's actual result should be harvested
        recorded_result = record_fn.call_args[0][1]
        assert recorded_result.success is True
        assert recorded_result.request_count == 5

    @patch("pokepoke.agents.parallel_support.terminal_ui")
    @patch("pokepoke.agents.parallel.unassign_with_retry")
    def test_record_fn_exception_handled(self, mock_unassign, mock_tui):
        """record_fn raising doesn't crash the drain (uses a done-but-failed future)."""
        item = _make_item("e1")
        fut = concurrent.futures.Future()
        fut.set_result(WorkItemResult(success=False, request_count=0))
        futures = {fut: item}
        run_logger = MagicMock()
        record_fn = Mock(side_effect=RuntimeError("record boom"))
        mock_unassign.return_value = True

        _drain_orphaned_futures(futures, SessionStats(agent_stats=AgentStats()), time.time(), run_logger, record_fn)

        record_fn.assert_called_once()
        mock_unassign.assert_called_once_with("e1")

    @patch("pokepoke.agents.parallel_support.terminal_ui")
    @patch("pokepoke.agents.parallel.unassign_with_retry", side_effect=RuntimeError("unassign boom"))
    def test_unassign_exception_handled(self, mock_unassign, mock_tui):
        """unassign_with_retry raising doesn't crash the drain and logs a warning."""
        item = _make_item("u1")
        fut = concurrent.futures.Future()
        fut.set_result(WorkItemResult(success=False, request_count=0))
        futures = {fut: item}
        run_logger = MagicMock()
        record_fn = Mock()

        _drain_orphaned_futures(futures, SessionStats(agent_stats=AgentStats()), time.time(), run_logger, record_fn)

        record_fn.assert_called_once()
        mock_unassign.assert_called_once_with("u1")
        warning_calls = [
            c for c in run_logger.log_orchestrator.call_args_list
            if c.kwargs.get("level") == "WARNING"
        ]
        assert any("u1" in str(c) and "unassign" in str(c).lower() for c in warning_calls)

    @patch("pokepoke.agents.parallel_support.terminal_ui")
    @patch("pokepoke.agents.parallel.unassign_with_retry")
    def test_done_future_with_exception(self, mock_unassign, mock_tui):
        """Orphan future that completed with exception still gets recorded."""
        item = _make_item("x1")
        fut = concurrent.futures.Future()
        fut.set_exception(RuntimeError("worker crashed"))
        futures = {fut: item}
        stats = SessionStats(agent_stats=AgentStats())
        run_logger = MagicMock()
        record_fn = Mock()
        mock_unassign.return_value = True

        _drain_orphaned_futures(futures, stats, time.time(), run_logger, record_fn)

        record_fn.assert_called_once()
        recorded_result = record_fn.call_args[0][1]
        assert recorded_result.success is False
        mock_unassign.assert_called_once_with("x1")

    @patch("pokepoke.agents.parallel_support.terminal_ui")
    @patch("pokepoke.agents.parallel.unassign_with_retry")
    def test_in_progress_futures_preserved(self, mock_unassign, mock_tui):
        """In-progress futures are skipped entirely — no record, no unassign, worktree preserved."""
        item = _make_item("ip1")
        fut = concurrent.futures.Future()  # Not done
        futures = {fut: item}
        run_logger = MagicMock()
        record_fn = Mock()

        _drain_orphaned_futures(futures, SessionStats(agent_stats=AgentStats()), time.time(), run_logger, record_fn)

        record_fn.assert_not_called()
        mock_unassign.assert_not_called()
        # Should log that the worktree is being preserved
        log_calls = [str(c) for c in run_logger.log_orchestrator.call_args_list]
        assert any("preserving" in c.lower() and "ip1" in c for c in log_calls)
