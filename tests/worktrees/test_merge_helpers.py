"""Tests for worktree merge helper functions."""

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from pokepoke.worktrees.merge_helpers import (
    _log_post_merge_diagnostics,
    is_worktree_merged,
    log_merge_failure,
    rollback_merge_commit,
    validate_post_merge_or_rollback,
)

# ---------------------------------------------------------------------------
# rollback_merge_commit
# ---------------------------------------------------------------------------


class TestRollbackMergeCommit:
    @patch("pokepoke.worktrees.merge_helpers._run_git")
    def test_returns_true_on_success(self, mock_git: MagicMock) -> None:
        mock_git.return_value = subprocess.CompletedProcess([], 0)
        assert rollback_merge_commit("conflict") is True
        mock_git.assert_called_once_with(["git", "reset", "--hard", "HEAD~1"], cwd=None)

    @patch("pokepoke.worktrees.merge_helpers._run_git")
    def test_passes_cwd(self, mock_git: MagicMock) -> None:
        mock_git.return_value = subprocess.CompletedProcess([], 0)
        rollback_merge_commit("reason", cwd="/repo")
        mock_git.assert_called_once_with(["git", "reset", "--hard", "HEAD~1"], cwd="/repo")

    @patch("pokepoke.worktrees.merge_helpers._run_git")
    def test_returns_false_on_called_process_error(self, mock_git: MagicMock) -> None:
        mock_git.side_effect = subprocess.CalledProcessError(1, "git")
        assert rollback_merge_commit("conflict") is False

    @patch("pokepoke.worktrees.merge_helpers._run_git")
    def test_returns_false_on_timeout(self, mock_git: MagicMock) -> None:
        mock_git.side_effect = subprocess.TimeoutExpired("git", 30)
        assert rollback_merge_commit("conflict") is False


# ---------------------------------------------------------------------------
# log_merge_failure
# ---------------------------------------------------------------------------


class TestLogMergeFailure:
    def test_logs_unmerged_files(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level("ERROR"):
            log_merge_failure(None, ["a.py", "b.py"])
        assert "Merge conflicts detected in 2 file(s)" in caplog.text

    def test_truncates_at_10_files(self, caplog: pytest.LogCaptureFixture) -> None:
        files = [f"file{i}.py" for i in range(15)]
        with caplog.at_level("INFO"):
            log_merge_failure(None, files)
        assert "and 5 more" in caplog.text

    def test_logs_merge_error_when_no_files(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level("ERROR"):
            log_merge_failure("bad merge", [])
        assert "Merge failed: bad merge" in caplog.text


# ---------------------------------------------------------------------------
# validate_post_merge_or_rollback
# ---------------------------------------------------------------------------


class TestValidatePostMergeOrRollback:
    @patch("pokepoke.worktrees.merge_helpers.validate_post_merge", return_value=True)
    def test_returns_none_on_success(self, _mock: MagicMock) -> None:
        result = validate_post_merge_or_rollback("master")
        assert result is None

    @patch("pokepoke.worktrees.merge_helpers._run_git")
    @patch("pokepoke.worktrees.merge_helpers.validate_post_merge", return_value=False)
    def test_returns_failure_result_when_validation_fails(
        self, _mock_validate: MagicMock, mock_git: MagicMock,
    ) -> None:
        mock_git.return_value = subprocess.CompletedProcess([], 0, stdout="")
        result = validate_post_merge_or_rollback("master")
        assert result is not None
        assert result.success is False
        assert result.halt_required is True

    @patch("pokepoke.worktrees.merge_helpers._run_git")
    @patch("pokepoke.worktrees.merge_helpers.validate_post_merge", side_effect=RuntimeError("oops"))
    def test_returns_failure_on_exception(
        self, _mock_validate: MagicMock, mock_git: MagicMock,
    ) -> None:
        mock_git.return_value = subprocess.CompletedProcess([], 0, stdout="")
        result = validate_post_merge_or_rollback("master")
        assert result is not None
        assert result.success is False
        assert result.halt_required is True


# ---------------------------------------------------------------------------
# _log_post_merge_diagnostics
# ---------------------------------------------------------------------------


class TestLogPostMergeDiagnostics:
    @patch("pokepoke.worktrees.merge_helpers._run_git")
    def test_collects_all_diagnostics(self, mock_git: MagicMock, caplog: pytest.LogCaptureFixture) -> None:
        mock_git.side_effect = [
            subprocess.CompletedProcess([], 0, stdout=" M foo.py"),
            subprocess.CompletedProcess([], 0, stdout="abc1234 commit msg"),
            subprocess.CompletedProcess([], 0, stdout="feature-branch"),
        ]
        with caplog.at_level("CRITICAL"):
            _log_post_merge_diagnostics("master", None)
        assert "POST-MERGE INVARIANT VIOLATION" in caplog.text
        assert "foo.py" in caplog.text
        assert "feature-branch" in caplog.text

    @patch("pokepoke.worktrees.merge_helpers._run_git", side_effect=Exception("fail"))
    def test_handles_all_git_failures(self, _mock: MagicMock, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level("CRITICAL"):
            _log_post_merge_diagnostics("master", None)
        assert "<unavailable>" in caplog.text


# ---------------------------------------------------------------------------
# is_worktree_merged
# ---------------------------------------------------------------------------


class TestIsWorktreeMerged:
    @patch("pokepoke.worktrees.merge_helpers.get_default_branch", return_value="master")
    @patch("pokepoke.worktrees.merge_helpers._run_git")
    def test_returns_true_when_branch_in_merged_list(
        self, mock_git: MagicMock, _mock_branch: MagicMock,
    ) -> None:
        mock_git.return_value = subprocess.CompletedProcess(
            [], 0, stdout="  task/my-item\n  master\n",
        )
        assert is_worktree_merged("my-item") is True

    @patch("pokepoke.worktrees.merge_helpers.get_default_branch", return_value="master")
    @patch("pokepoke.worktrees.merge_helpers._run_git")
    def test_returns_false_when_branch_not_merged(
        self, mock_git: MagicMock, _mock_branch: MagicMock,
    ) -> None:
        mock_git.return_value = subprocess.CompletedProcess([], 0, stdout="  master\n")
        assert is_worktree_merged("other-item") is False

    @patch("pokepoke.worktrees.merge_helpers._run_git")
    def test_uses_explicit_target_branch(self, mock_git: MagicMock) -> None:
        mock_git.return_value = subprocess.CompletedProcess(
            [], 0, stdout="  task/item-1\n",
        )
        assert is_worktree_merged("item-1", target_branch="develop") is True
        mock_git.assert_called_once_with(
            ["git", "branch", "--merged", "develop"], cwd=None,
        )

    @patch("pokepoke.worktrees.merge_helpers.get_default_branch", return_value="master")
    @patch("pokepoke.worktrees.merge_helpers._run_git")
    def test_returns_false_on_error(
        self, mock_git: MagicMock, _mock_branch: MagicMock,
    ) -> None:
        mock_git.side_effect = subprocess.CalledProcessError(1, "git")
        assert is_worktree_merged("item-1") is False
