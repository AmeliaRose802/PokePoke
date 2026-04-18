"""Integration-style tests for merge_queue.py.

Exercises real MergeQueue lifecycle (start/submit/shutdown/drain) and
rebase helpers. Mocks only external I/O: subprocess, git_operations,
worktree_finalization, beads, shutdown.
"""

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

from pokepoke.git.merge_queue import (
    MergeQueue,
    MergeResult,
    MergeStatus,
    _abort_rebase,
    _rebase_worktree,
    get_merge_queue,
    reset_merge_queue,
)
from pokepoke.types import BeadsWorkItem


def _item(id: str = "test-1") -> BeadsWorkItem:
    return BeadsWorkItem(id=id, title=f"Item {id}", status="ready",
                         priority=1, issue_type="task")


# ── MergeStatus / MergeResult ──────────────────────────────────────

class TestMergeEnums:
    def test_status_values(self):
        assert MergeStatus.SUCCESS.value == "success"
        assert MergeStatus.CONFLICT.value == "conflict"
        assert MergeStatus.FAILED.value == "failed"
        assert MergeStatus.SHUTDOWN.value == "shutdown"

    def test_result_defaults(self):
        r = MergeResult(status=MergeStatus.SUCCESS, item_id="x")
        assert r.message == ""
        assert r.item_id == "x"


# ── MergeQueue lifecycle ───────────────────────────────────────────

class TestMergeQueueLifecycle:
    def setup_method(self):
        self.queue = MergeQueue()

    def teardown_method(self):
        if self.queue.is_running:
            self.queue.shutdown(timeout=5.0)

    def test_initial_state(self):
        assert not self.queue.is_running
        assert self.queue.pending_count == 0

    @patch("pokepoke.git.merge_queue.is_shutting_down", return_value=False)
    def test_start_creates_worker(self, mock_shutdown):
        self.queue.start()
        assert self.queue.is_running
        # Shutdown by sending sentinel
        self.queue.shutdown(timeout=5.0)
        assert not self.queue.is_running

    @patch("pokepoke.git.merge_queue.is_shutting_down", return_value=False)
    def test_double_start_is_idempotent(self, mock_shutdown):
        self.queue.start()
        self.queue.start()  # Should not raise
        assert self.queue.is_running

    @patch("pokepoke.git.merge_queue.is_shutting_down", return_value=False)
    def test_shutdown_without_start(self, mock_shutdown):
        self.queue.shutdown(timeout=1.0)  # Should not raise

    @patch("pokepoke.git.merge_queue.is_shutting_down", return_value=False)
    @patch("pokepoke.git.merge_queue.is_high_conflict_risk", return_value=False)
    @patch("pokepoke.git.merge_queue.get_default_branch", return_value="main")
    @patch("pokepoke.git.merge_queue.is_worktree_clean", return_value=True)
    @patch("subprocess.run")
    def test_submit_and_process(self, mock_subproc, mock_clean,  # noqa: PLR0913
                                mock_branch, mock_conflict, mock_shutdown,
                                tmp_path):
        with patch("pokepoke.worktrees.worktree_finalization.merge_worktree_to_dev", return_value=True):
            mock_subproc.return_value = MagicMock(returncode=0)
            self.queue.start()
            future = self.queue.submit(tmp_path, _item("merge-1"))
            result = future.result(timeout=10.0)
            assert result.status == MergeStatus.SUCCESS
            assert result.item_id == "merge-1"

    @patch("pokepoke.git.merge_queue.is_shutting_down", return_value=False)
    def test_drain_on_shutdown(self, mock_shutdown):
        self.queue.start()
        # Submit items then immediately shutdown
        items = [_item(f"drain-{i}") for i in range(3)]
        futures = []
        for item in items:
            futures.append(self.queue.submit(Path("/fake"), item))
        self.queue.shutdown(timeout=10.0)
        # All futures should resolve (either processed or shutdown)
        for f in futures:
            result = f.result(timeout=5.0)
            assert result.status in (MergeStatus.SUCCESS, MergeStatus.FAILED,
                                     MergeStatus.SHUTDOWN)


# ── _rebase_worktree ───────────────────────────────────────────────

class TestRebaseWorktree:
    @patch("pokepoke.git.merge_queue.get_default_branch", return_value="main")
    @patch("subprocess.run")
    def test_successful_rebase(self, mock_run, mock_branch, tmp_path):
        mock_run.return_value = MagicMock(returncode=0)
        result = _rebase_worktree(tmp_path)
        assert result is True
        assert mock_run.call_count == 2  # fetch + rebase

    @patch("pokepoke.git.merge_queue.get_default_branch", return_value="main")
    @patch("subprocess.run")
    def test_rebase_with_explicit_branch(self, mock_run, mock_branch, tmp_path):
        mock_run.return_value = MagicMock(returncode=0)
        result = _rebase_worktree(tmp_path, target_branch="develop")
        assert result is True
        # Should use "develop" not call get_default_branch
        fetch_call = mock_run.call_args_list[0]
        assert "develop" in fetch_call[0][0]

    @patch("pokepoke.git.merge_queue.get_default_branch", return_value="main")
    @patch("subprocess.run")
    def test_rebase_failure_aborts(self, mock_run, mock_branch, tmp_path):
        # Fetch succeeds, rebase fails
        mock_run.side_effect = [
            MagicMock(returncode=0),  # fetch
            subprocess.CalledProcessError(1, "git rebase", stderr="conflict"),
            MagicMock(returncode=0),  # abort
        ]
        result = _rebase_worktree(tmp_path)
        assert result is False

    @patch("pokepoke.git.merge_queue.get_default_branch", return_value="main")
    @patch("subprocess.run")
    def test_rebase_timeout_aborts(self, mock_run, mock_branch, tmp_path):
        mock_run.side_effect = [
            MagicMock(returncode=0),  # fetch
            subprocess.TimeoutExpired("git rebase", 120),
            MagicMock(returncode=0),  # abort
        ]
        result = _rebase_worktree(tmp_path)
        assert result is False

    def test_nonexistent_path(self):
        result = _rebase_worktree(Path("/nonexistent/path"))
        assert result is False


# ── _abort_rebase ──────────────────────────────────────────────────

class TestAbortRebase:
    @patch("subprocess.run")
    def test_successful_abort(self, mock_run, tmp_path):
        mock_run.return_value = MagicMock(returncode=0)
        _abort_rebase(tmp_path)  # Should not raise
        mock_run.assert_called_once()

    @patch("subprocess.run")
    def test_abort_failure_logs_warning(self, mock_run, tmp_path):
        mock_run.side_effect = [
            subprocess.CalledProcessError(1, "git rebase --abort", stderr="err"),
            MagicMock(returncode=0, stdout=""),  # status check
        ]
        _abort_rebase(tmp_path)  # Should not raise

    @patch("subprocess.run")
    def test_abort_timeout(self, mock_run, tmp_path):
        mock_run.side_effect = [
            subprocess.TimeoutExpired("git rebase --abort", 30),
            MagicMock(returncode=0, stdout="M file.txt"),  # status shows dirty
        ]
        _abort_rebase(tmp_path)  # Should not raise


# ── Singleton management ───────────────────────────────────────────

class TestSingleton:
    def test_get_returns_same_instance(self):
        reset_merge_queue()
        q1 = get_merge_queue()
        q2 = get_merge_queue()
        assert q1 is q2
        reset_merge_queue()

    def test_reset_creates_new_instance(self):
        reset_merge_queue()
        q1 = get_merge_queue()
        reset_merge_queue()
        q2 = get_merge_queue()
        assert q1 is not q2
        reset_merge_queue()


# ── _process_request (high-conflict path) ──────────────────────────

class TestProcessRequest:
    def setup_method(self):
        self.queue = MergeQueue()

    def teardown_method(self):
        if self.queue.is_running:
            self.queue.shutdown(timeout=5.0)

    @patch("pokepoke.git.merge_queue.is_shutting_down", return_value=False)
    @patch("pokepoke.git.merge_queue.is_high_conflict_risk", return_value=True)
    @patch("pokepoke.git.merge_queue.get_default_branch", return_value="main")
    @patch("pokepoke.git.merge_queue.is_worktree_clean", return_value=True)
    @patch("subprocess.run")
    def test_high_conflict_does_double_rebase(self, mock_run, mock_clean,  # noqa: PLR0913
                                              mock_branch, mock_conflict,
                                              mock_shutdown, tmp_path):
        mock_run.return_value = MagicMock(returncode=0)
        with patch("pokepoke.worktrees.worktree_finalization.merge_worktree_to_dev", return_value=True):
            self.queue.start()
            future = self.queue.submit(tmp_path, _item("hc-1"))
            result = future.result(timeout=10.0)
            assert result.status == MergeStatus.SUCCESS
            # Double rebase means 4 subprocess calls (2x fetch + 2x rebase)
            assert mock_run.call_count == 4

    @patch("pokepoke.git.merge_queue.is_shutting_down", return_value=False)
    @patch("pokepoke.git.merge_queue.is_high_conflict_risk", return_value=False)
    @patch("pokepoke.git.merge_queue.get_default_branch", return_value="main")
    @patch("pokepoke.git.merge_queue.is_worktree_clean", return_value=False)
    @patch("subprocess.run")
    def test_rebase_fail_dirty_worktree_marks_failed(self, mock_run, mock_clean,  # noqa: PLR0913
                                                     mock_branch, mock_conflict,
                                                     mock_shutdown, tmp_path):
        # Fetch OK, rebase fails
        mock_run.side_effect = [
            MagicMock(returncode=0),  # fetch
            subprocess.CalledProcessError(1, "rebase", stderr="conflict"),
            MagicMock(returncode=0),  # abort
        ]
        with patch("pokepoke.worktrees.worktree_cleanup.add_uncleaned_worktree"):
            self.queue.start()
            future = self.queue.submit(tmp_path, _item("dirty-1"))
            result = future.result(timeout=10.0)
            assert result.status == MergeStatus.FAILED
            assert "dirty" in result.message.lower()

    @patch("pokepoke.git.merge_queue.is_shutting_down", return_value=False)
    @patch("pokepoke.git.merge_queue.is_high_conflict_risk", return_value=False)
    @patch("pokepoke.git.merge_queue.get_default_branch", return_value="main")
    @patch("pokepoke.git.merge_queue.is_worktree_clean", return_value=True)
    @patch("subprocess.run")
    def test_merge_exception_marks_failed(self, mock_run, mock_clean,  # noqa: PLR0913
                                          mock_branch, mock_conflict,
                                          mock_shutdown, tmp_path):
        mock_run.return_value = MagicMock(returncode=0)
        with patch("pokepoke.worktrees.worktree_finalization.merge_worktree_to_dev",
                    side_effect=RuntimeError("merge exploded")):
            self.queue.start()
            future = self.queue.submit(tmp_path, _item("exc-1"))
            result = future.result(timeout=10.0)
            assert result.status == MergeStatus.FAILED
            assert "merge exploded" in result.message

    @patch("pokepoke.git.merge_queue.is_shutting_down", return_value=False)
    @patch("pokepoke.git.merge_queue.is_high_conflict_risk", return_value=False)
    @patch("pokepoke.git.merge_queue.get_default_branch", return_value="main")
    @patch("pokepoke.git.merge_queue.is_worktree_clean", return_value=True)
    @patch("subprocess.run")
    def test_merge_returns_false(self, mock_run, mock_clean,  # noqa: PLR0913
                                 mock_branch, mock_conflict, mock_shutdown,
                                 tmp_path):
        mock_run.return_value = MagicMock(returncode=0)
        with patch("pokepoke.worktrees.worktree_finalization.merge_worktree_to_dev",
                    return_value=False):
            self.queue.start()
            future = self.queue.submit(tmp_path, _item("fail-1"))
            result = future.result(timeout=10.0)
            assert result.status == MergeStatus.FAILED
