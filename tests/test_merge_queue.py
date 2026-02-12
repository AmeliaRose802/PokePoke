"""Tests for merge queue coordinator."""

import threading
import time
from concurrent.futures import Future
from pathlib import Path
from queue import Empty
from unittest.mock import MagicMock, patch, call

import pytest

import pokepoke.merge_queue
from pokepoke.merge_queue import (
    MergeQueue,
    MergeResult,
    MergeStatus,
    _MergeRequest,
    _rebase_worktree,
    get_merge_queue,
    reset_merge_queue,
)
from pokepoke.types import BeadsWorkItem


def _make_item(item_id: str = "TEST-001", title: str = "Test item") -> BeadsWorkItem:
    """Create a test BeadsWorkItem."""
    return BeadsWorkItem(
        id=item_id,
        title=title,
        status="in_progress",
        priority=1,
        issue_type="task",
    )


class TestMergeStatus:
    """Tests for MergeStatus enum."""

    def test_status_values(self):
        assert MergeStatus.SUCCESS.value == "success"
        assert MergeStatus.CONFLICT.value == "conflict"
        assert MergeStatus.FAILED.value == "failed"
        assert MergeStatus.SHUTDOWN.value == "shutdown"


class TestMergeResult:
    """Tests for MergeResult dataclass."""

    def test_defaults(self):
        result = MergeResult(status=MergeStatus.SUCCESS, item_id="X")
        assert result.message == ""

    def test_with_message(self):
        result = MergeResult(
            status=MergeStatus.FAILED, item_id="Y", message="conflict"
        )
        assert result.status == MergeStatus.FAILED
        assert result.item_id == "Y"
        assert result.message == "conflict"


class TestMergeQueue:
    """Tests for MergeQueue class."""

    def setup_method(self):
        self.queue = MergeQueue()

    def teardown_method(self):
        if self.queue.is_running:
            self.queue.shutdown(timeout=5)

    def test_initial_state(self):
        assert not self.queue.is_running
        assert self.queue.pending_count == 0

    def test_start(self):
        self.queue.start()
        assert self.queue.is_running

    def test_start_idempotent(self):
        self.queue.start()
        self.queue.start()  # Should not raise
        assert self.queue.is_running

    def test_shutdown_when_not_started(self):
        self.queue.shutdown()  # Should not raise

    @patch("pokepoke.merge_queue.is_shutting_down", return_value=False)
    @patch("pokepoke.merge_queue._rebase_worktree", return_value=True)
    @patch("pokepoke.merge_queue.MergeQueue._process_request")
    def test_submit_auto_starts(self, mock_process, mock_rebase, mock_shutdown):
        mock_process.side_effect = lambda req: req.future.set_result(
            MergeResult(status=MergeStatus.SUCCESS, item_id=req.item.id)
        )
        item = _make_item()
        future = self.queue.submit(Path("worktrees/task-TEST-001"), item)
        assert self.queue.is_running
        result = future.result(timeout=5)
        assert result.status == MergeStatus.SUCCESS

    @patch("pokepoke.merge_queue.is_shutting_down", return_value=False)
    @patch("pokepoke.merge_queue._rebase_worktree", return_value=True)
    def test_submit_and_merge_success(self, mock_rebase, mock_shutdown):
        with patch(
            "pokepoke.worktree_finalization.merge_worktree_to_dev", return_value=True
        ):
            self.queue.start()
            item = _make_item()
            future = self.queue.submit(Path("worktrees/task-TEST-001"), item)
            result = future.result(timeout=10)

        assert result.status == MergeStatus.SUCCESS
        assert result.item_id == "TEST-001"
        mock_rebase.assert_called_once()

    @patch("pokepoke.merge_queue.is_shutting_down", return_value=False)
    @patch("pokepoke.merge_queue._rebase_worktree", return_value=True)
    def test_submit_merge_failure(self, mock_rebase, mock_shutdown):
        with patch(
            "pokepoke.worktree_finalization.merge_worktree_to_dev", return_value=False
        ):
            self.queue.start()
            item = _make_item()
            future = self.queue.submit(Path("worktrees/task-TEST-001"), item)
            result = future.result(timeout=10)

        assert result.status == MergeStatus.FAILED
        assert result.item_id == "TEST-001"

    @patch("pokepoke.merge_queue.is_shutting_down", return_value=False)
    @patch("pokepoke.merge_queue._rebase_worktree", return_value=True)
    def test_submit_merge_exception(self, mock_rebase, mock_shutdown):
        with patch(
            "pokepoke.worktree_finalization.merge_worktree_to_dev",
            side_effect=RuntimeError("git exploded"),
        ):
            self.queue.start()
            item = _make_item()
            future = self.queue.submit(Path("worktrees/task-TEST-001"), item)
            result = future.result(timeout=10)

        assert result.status == MergeStatus.FAILED
        assert "git exploded" in result.message

    @patch("pokepoke.merge_queue.is_shutting_down", return_value=False)
    @patch("pokepoke.merge_queue._rebase_worktree", return_value=False)
    def test_rebase_failure_still_attempts_merge(self, mock_rebase, mock_shutdown):
        with patch(
            "pokepoke.worktree_finalization.merge_worktree_to_dev", return_value=True
        ):
            self.queue.start()
            item = _make_item()
            future = self.queue.submit(Path("worktrees/task-TEST-001"), item)
            result = future.result(timeout=10)

        assert result.status == MergeStatus.SUCCESS

    @patch("pokepoke.merge_queue.is_shutting_down", return_value=False)
    @patch("pokepoke.merge_queue._rebase_worktree", return_value=True)
    def test_serialized_merges(self, mock_rebase, mock_shutdown):
        """Verify merges are processed one at a time in order."""
        merge_order: list[str] = []
        merge_lock = threading.Lock()

        def mock_merge(item):
            with merge_lock:
                merge_order.append(item.id)
            time.sleep(0.05)  # Simulate merge work
            return True

        with patch(
            "pokepoke.worktree_finalization.merge_worktree_to_dev",
            side_effect=mock_merge,
        ):
            self.queue.start()
            futures = []
            for i in range(3):
                item = _make_item(f"ITEM-{i}")
                f = self.queue.submit(Path(f"worktrees/task-ITEM-{i}"), item)
                futures.append(f)

            for f in futures:
                result = f.result(timeout=15)
                assert result.status == MergeStatus.SUCCESS

        assert merge_order == ["ITEM-0", "ITEM-1", "ITEM-2"]

    def test_shutdown_drains_pending(self):
        """Pending items get SHUTDOWN result when queue shuts down."""
        # Directly test _drain_on_shutdown without starting the worker
        item = _make_item()
        future: Future[MergeResult] = Future()
        request = _MergeRequest(
            worktree_path=Path("x"), item=item, future=future
        )
        self.queue._queue.put(request)

        self.queue._drain_on_shutdown()

        assert future.done()
        result = future.result(timeout=1)
        assert result.status == MergeStatus.SHUTDOWN

    @patch("pokepoke.merge_queue.is_shutting_down", return_value=True)
    def test_worker_exits_on_global_shutdown(self, mock_shutdown):
        """Worker exits when global shutdown is signaled."""
        self.queue.start()
        # Worker should notice is_shutting_down and exit
        time.sleep(0.2)
        # The worker thread should have stopped (or be about to)
        self.queue.shutdown(timeout=5)
        assert not self.queue.is_running

    def test_pending_count(self):
        self.queue._queue.put(
            _MergeRequest(
                worktree_path=Path("x"),
                item=_make_item(),
                future=Future(),
            )
        )
        assert self.queue.pending_count == 1

    def test_drain_on_shutdown_skips_sentinels(self):
        """_drain_on_shutdown should skip None sentinel values."""
        self.queue._queue.put(None)
        item = _make_item("DRAIN-1")
        future: Future[MergeResult] = Future()
        self.queue._queue.put(
            _MergeRequest(worktree_path=Path("x"), item=item, future=future)
        )
        self.queue._drain_on_shutdown()
        assert future.done()
        assert future.result().status == MergeStatus.SHUTDOWN


class TestRebaseWorktree:
    """Tests for _rebase_worktree helper."""

    @patch("subprocess.run")
    def test_success(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        with patch.object(Path, "exists", return_value=True):
            assert _rebase_worktree(Path("worktrees/task-X")) is True

        mock_run.assert_called_once()
        args = mock_run.call_args
        assert args[0][0] == ["git", "pull", "--rebase"]

    @patch("subprocess.run")
    def test_nonexistent_path(self, mock_run):
        with patch.object(Path, "exists", return_value=False):
            assert _rebase_worktree(Path("nonexistent")) is False
        mock_run.assert_not_called()

    @patch("subprocess.run")
    def test_rebase_failure_aborts(self, mock_run):
        """On rebase failure, should abort and return False."""
        import subprocess as sp

        mock_run.side_effect = [
            sp.CalledProcessError(1, "git", stderr="conflict"),
            MagicMock(returncode=0),  # rebase --abort
        ]
        with patch.object(Path, "exists", return_value=True):
            assert _rebase_worktree(Path("worktrees/task-X")) is False

        # Should have called rebase --abort
        assert mock_run.call_count == 2
        abort_call = mock_run.call_args_list[1]
        assert "rebase" in abort_call[0][0]
        assert "--abort" in abort_call[0][0]

    @patch("subprocess.run")
    def test_timeout(self, mock_run):
        import subprocess as sp

        mock_run.side_effect = sp.TimeoutExpired("git", 120)
        with patch.object(Path, "exists", return_value=True):
            assert _rebase_worktree(Path("worktrees/task-X")) is False


class TestSingleton:
    """Tests for module-level singleton management."""

    def teardown_method(self):
        reset_merge_queue()

    def test_get_merge_queue_returns_same_instance(self):
        q1 = get_merge_queue()
        q2 = get_merge_queue()
        assert q1 is q2

    def test_reset_creates_new_instance(self):
        q1 = get_merge_queue()
        reset_merge_queue()
        q2 = get_merge_queue()
        assert q1 is not q2

    def test_reset_shuts_down_existing(self):
        q = get_merge_queue()
        q.start()
        assert q.is_running
        reset_merge_queue()
        # After reset, the old queue should be shut down
        assert not q.is_running
