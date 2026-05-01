"""Tests for merge queue coordinator."""

import threading
import time
from concurrent.futures import Future
from pathlib import Path
from unittest.mock import MagicMock, patch

import pokepoke.git.merge_queue  # noqa: F401  # imported for coverage tracking
from pokepoke.git.merge_queue import (
    MergeQueue,
    MergeResult,
    MergeStatus,
    _MergeRequest,
    _rebase_worktree,
)
from pokepoke.types import BeadsWorkItem


def _make_item(
    item_id: str = "TEST-001",
    title: str = "Test item",
    labels: list[str] | None = None,
) -> BeadsWorkItem:
    """Create a test BeadsWorkItem."""
    return BeadsWorkItem(
        id=item_id,
        title=title,
        status="in_progress",
        priority=1,
        issue_type="task",
        labels=labels,
    )

class TestMergeStatus:
    """Tests for MergeStatus enum."""

    def test_status_values(self):
        assert MergeStatus.SUCCESS.value == "success"
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

    @patch("pokepoke.git.merge_queue.is_shutting_down", return_value=False)
    @patch("pokepoke.git.merge_queue._rebase_worktree", return_value=True)
    @patch("pokepoke.git.merge_queue.MergeQueue._process_request")
    def test_submit_auto_starts(self, mock_process, mock_rebase, mock_shutdown):
        mock_process.side_effect = lambda req: req.future.set_result(
            MergeResult(status=MergeStatus.SUCCESS, item_id=req.item.id)
        )
        item = _make_item()
        future = self.queue.submit(Path("worktrees/task-TEST-001"), item)
        assert self.queue.is_running
        result = future.result(timeout=5)
        assert result.status == MergeStatus.SUCCESS

    @patch("pokepoke.git.merge_queue.get_default_branch", return_value="main")
    @patch("pokepoke.git.merge_queue.is_shutting_down", return_value=False)
    @patch("pokepoke.git.merge_queue._rebase_worktree", return_value=True)
    def test_submit_and_merge_success(self, mock_rebase, mock_shutdown, mock_branch):
        with patch(
            "pokepoke.worktrees.worktree_finalization.merge_worktree_to_dev", return_value=True
        ):
            self.queue.start()
            item = _make_item()
            future = self.queue.submit(Path("worktrees/task-TEST-001"), item)
            result = future.result(timeout=10)

        assert result.status == MergeStatus.SUCCESS
        assert result.item_id == "TEST-001"
        mock_rebase.assert_called_once()

    @patch("pokepoke.git.merge_queue.get_default_branch", return_value="main")
    @patch("pokepoke.git.merge_queue.is_shutting_down", return_value=False)
    @patch("pokepoke.git.merge_queue._rebase_worktree", return_value=True)
    def test_submit_merge_failure(self, mock_rebase, mock_shutdown, mock_branch):
        with patch(
            "pokepoke.worktrees.worktree_finalization.merge_worktree_to_dev", return_value=False
        ):
            self.queue.start()
            item = _make_item()
            future = self.queue.submit(Path("worktrees/task-TEST-001"), item)
            result = future.result(timeout=10)

        assert result.status == MergeStatus.FAILED
        assert result.item_id == "TEST-001"

    @patch("pokepoke.git.merge_queue.get_default_branch", return_value="main")
    @patch("pokepoke.git.merge_queue.is_shutting_down", return_value=False)
    @patch("pokepoke.git.merge_queue._rebase_worktree", return_value=True)
    def test_submit_merge_exception(self, mock_rebase, mock_shutdown, mock_branch):
        with patch(
            "pokepoke.worktrees.worktree_finalization.merge_worktree_to_dev",
            side_effect=RuntimeError("git exploded"),
        ):
            self.queue.start()
            item = _make_item()
            future = self.queue.submit(Path("worktrees/task-TEST-001"), item)
            result = future.result(timeout=10)

        assert result.status == MergeStatus.FAILED
        assert "git exploded" in result.message

    @patch("pokepoke.git.merge_queue.get_default_branch", return_value="main")
    @patch("pokepoke.git.merge_queue.is_worktree_clean", return_value=True)
    @patch("pokepoke.git.merge_queue.is_shutting_down", return_value=False)
    @patch("pokepoke.git.merge_queue._rebase_worktree", return_value=False)
    def test_rebase_failure_clean_worktree_attempts_merge(self, mock_rebase, mock_shutdown, mock_clean, mock_branch):
        """If rebase fails but worktree is clean (abort succeeded), merge proceeds."""
        with patch(
            "pokepoke.worktrees.worktree_finalization.merge_worktree_to_dev", return_value=True
        ):
            self.queue.start()
            item = _make_item()
            future = self.queue.submit(Path("worktrees/task-TEST-001"), item)
            result = future.result(timeout=10)

        assert result.status == MergeStatus.SUCCESS

    @patch("pokepoke.git.merge_queue.get_default_branch", return_value="main")
    @patch("pokepoke.worktrees.worktree_cleanup.add_uncleaned_worktree")
    @patch("pokepoke.git.merge_queue.is_worktree_clean", return_value=False)
    @patch("pokepoke.git.merge_queue.is_shutting_down", return_value=False)
    @patch("pokepoke.git.merge_queue._rebase_worktree", return_value=False)
    def test_rebase_failure_dirty_worktree_skips_merge(
        self, mock_rebase, mock_shutdown, mock_clean, mock_add_uncleaned, mock_branch
    ):
        """If rebase fails and worktree is dirty, skip merge and track worktree."""
        with patch(
            "pokepoke.worktrees.worktree_finalization.merge_worktree_to_dev"
        ) as mock_merge:
            self.queue.start()
            item = _make_item()
            future = self.queue.submit(Path("worktrees/task-TEST-001"), item)
            result = future.result(timeout=10)

            mock_merge.assert_not_called()

        assert result.status == MergeStatus.FAILED
        assert "dirty state" in result.message
        mock_add_uncleaned.assert_called_once_with(
            worktree_id="TEST-001",
            worktree_path="worktrees\\task-TEST-001",
            reason="Rebase failed and abort left worktree in dirty state",
        )

    @patch("pokepoke.git.merge_queue.get_default_branch", return_value="main")
    @patch("pokepoke.git.merge_queue.time.sleep")
    @patch("pokepoke.git.merge_queue.is_shutting_down", return_value=False)
    @patch("pokepoke.git.merge_queue._rebase_worktree", return_value=True)
    def test_high_conflict_triggers_cautious_strategy(
        self, mock_rebase, mock_shutdown, mock_sleep, mock_branch
    ):
        """High-conflict items should apply slower, double-rebase strategy."""
        with patch(
            "pokepoke.worktrees.worktree_finalization.merge_worktree_to_dev", return_value=True
        ):
            self.queue.start()
            item = _make_item(labels=["high-conflict-risk"])
            future = self.queue.submit(Path("worktrees/task-TEST-001"), item)
            result = future.result(timeout=10)

        assert result.status == MergeStatus.SUCCESS
        assert mock_rebase.call_count == 2
        mock_sleep.assert_called_once()

    @patch("pokepoke.git.merge_queue.get_default_branch", return_value="main")
    @patch("pokepoke.git.merge_queue.is_shutting_down", return_value=False)
    @patch("pokepoke.git.merge_queue._rebase_worktree", return_value=True)
    def test_serialized_merges(self, mock_rebase, mock_shutdown, mock_branch):
        """Verify merges are processed one at a time in order."""
        merge_order: list[str] = []
        merge_lock = threading.Lock()

        def mock_merge(item, **kwargs):
            with merge_lock:
                merge_order.append(item.id)
            time.sleep(0.05)  # Simulate merge work
            return True

        with patch(
            "pokepoke.worktrees.worktree_finalization.merge_worktree_to_dev",
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

    @patch("pokepoke.git.merge_queue.is_shutting_down", return_value=True)
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

    @patch("pokepoke.git.merge_queue.is_shutting_down", return_value=False)
    @patch("pokepoke.git.merge_queue.get_default_branch", side_effect=RuntimeError("Git timeout"))
    def test_exception_before_try_block_resolves_future(self, mock_branch, mock_shutdown):
        """Verify exceptions before the main try block still resolve the Future.

        This tests the bug fix for PokePoke-8cn2: exceptions in get_default_branch(),
        is_high_conflict_risk(), is_worktree_clean(), or add_uncleaned_worktree()
        should not orphan the Future or kill the worker thread.
        """
        with patch("pokepoke.git.merge_queue.is_high_conflict_risk", return_value=False):
            self.queue.start()
            item = _make_item("TEST-EXCEPTION")
            future = self.queue.submit(Path("worktrees/task-TEST-EXCEPTION"), item)

            # The Future should be resolved with FAILED status, not hang forever
            result = future.result(timeout=5)

            assert result.status == MergeStatus.FAILED
            assert "Git timeout" in result.message or "Unhandled exception" in result.message
            assert result.item_id == "TEST-EXCEPTION"

            # Worker thread should still be alive and can process next request
            assert self.queue.is_running

            # Verify worker can handle another request
            with (
                patch("pokepoke.git.merge_queue.get_default_branch", return_value="main"),
                patch("pokepoke.git.merge_queue._rebase_worktree", return_value=True),
                patch("pokepoke.worktrees.worktree_finalization.merge_worktree_to_dev", return_value=True),
            ):
                item2 = _make_item("TEST-RECOVERY")
                future2 = self.queue.submit(Path("worktrees/task-TEST-RECOVERY"), item2)
                result2 = future2.result(timeout=5)
                assert result2.status == MergeStatus.SUCCESS

    @patch("pokepoke.git.merge_queue.is_shutting_down", return_value=False)
    @patch("pokepoke.git.merge_queue.is_high_conflict_risk", side_effect=Exception("Beads read failure"))
    def test_exception_in_high_conflict_check_resolves_future(self, mock_conflict, mock_shutdown):
        """Verify exception in is_high_conflict_risk() resolves the Future."""
        self.queue.start()
        item = _make_item("TEST-CONFLICT-FAIL")
        future = self.queue.submit(Path("worktrees/task-TEST-CONFLICT-FAIL"), item)

        # Should not hang, should get FAILED result
        result = future.result(timeout=5)

        assert result.status == MergeStatus.FAILED
        assert "Beads read failure" in result.message or "Unhandled exception" in result.message
        assert self.queue.is_running  # Worker still alive

class TestRebaseWorktree:
    """Tests for _rebase_worktree helper."""

    @patch("pokepoke.git.merge_queue.get_default_branch", return_value="main")
    @patch("subprocess.run")
    def test_success(self, mock_run, mock_branch):
        mock_run.return_value = MagicMock(returncode=0)
        with patch.object(Path, "exists", return_value=True):
            assert _rebase_worktree(Path("worktrees/task-X")) is True

        assert mock_run.call_count == 2
        fetch_call = mock_run.call_args_list[0]
        assert fetch_call[0][0] == ["git", "fetch", "origin", "main"]
        rebase_call = mock_run.call_args_list[1]
        assert rebase_call[0][0] == ["git", "rebase", "origin/main"]

    @patch("subprocess.run")
    def test_nonexistent_path(self, mock_run):
        with patch.object(Path, "exists", return_value=False):
            assert _rebase_worktree(Path("nonexistent"), target_branch="main") is False
        mock_run.assert_not_called()

    @patch("subprocess.run")
    def test_rebase_failure_aborts(self, mock_run):
        """On rebase failure, should abort and return False."""
        import subprocess as sp

        mock_run.side_effect = [
            MagicMock(returncode=0),  # git fetch origin main
            sp.CalledProcessError(1, "git", stderr="conflict"),  # git rebase
            MagicMock(returncode=0),  # rebase --abort
        ]
        with patch.object(Path, "exists", return_value=True):
            assert _rebase_worktree(Path("worktrees/task-X"), target_branch="main") is False

        # Should have called fetch, rebase (failed), rebase --abort
        assert mock_run.call_count == 3
        abort_call = mock_run.call_args_list[2]
        assert "rebase" in abort_call[0][0]
        assert "--abort" in abort_call[0][0]

    @patch("subprocess.run")
    def test_timeout(self, mock_run):
        """On timeout, should abort and return False."""
        import subprocess as sp

        mock_run.side_effect = [
            MagicMock(returncode=0),  # git fetch origin main
            sp.TimeoutExpired("git", 120),  # git rebase
            MagicMock(returncode=0),  # rebase --abort
        ]
        with patch.object(Path, "exists", return_value=True):
            assert _rebase_worktree(Path("worktrees/task-X"), target_branch="main") is False

        assert mock_run.call_count == 3
        abort_call = mock_run.call_args_list[2]
        assert "rebase" in abort_call[0][0]
        assert "--abort" in abort_call[0][0]

    @patch("subprocess.run")
    def test_explicit_target_branch(self, mock_run):
        """When target_branch is passed, it should be used directly."""
        mock_run.return_value = MagicMock(returncode=0)
        with patch.object(Path, "exists", return_value=True):
            assert _rebase_worktree(Path("worktrees/task-X"), target_branch="develop") is True

        assert mock_run.call_count == 2
        fetch_call = mock_run.call_args_list[0]
        assert fetch_call[0][0] == ["git", "fetch", "origin", "develop"]
        rebase_call = mock_run.call_args_list[1]
        assert rebase_call[0][0] == ["git", "rebase", "origin/develop"]
