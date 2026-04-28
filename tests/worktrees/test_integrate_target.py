"""Tests for integrate_target_into_worktree — pre-merge integration step."""

import subprocess
from pathlib import Path
from unittest.mock import Mock, patch

from pokepoke.worktrees.merge_helpers import integrate_target_into_worktree


class TestIntegrateTargetIntoWorktree:
    """Tests for integrate_target_into_worktree."""

    WORKTREE = Path("/fake/worktrees/task-item-1")
    TARGET = "main"

    @patch("pokepoke.worktrees.merge_helpers._run_git")
    def test_success_clean_merge(self, mock_run_git):
        """Successful integration when no conflicts."""
        mock_run_git.return_value = Mock(stdout="", returncode=0)

        result = integrate_target_into_worktree(self.WORKTREE, self.TARGET)

        assert result.success is True
        assert result.unmerged_files == []
        mock_run_git.assert_called_once_with(
            ["git", "merge", "main", "--no-verify",
             "-m", "Integrate main before merge to mainline"],
            cwd=str(self.WORKTREE), timeout=120,
        )

    @patch("pokepoke.worktrees.merge_helpers._run_git")
    @patch("pokepoke.git.merge_conflict.is_merge_in_progress")
    @patch("pokepoke.git.merge_conflict.get_unmerged_files")
    @patch("pokepoke.git.merge_conflict.abort_merge")
    def test_conflict_aborts_in_worktree(
        self, mock_abort, mock_unmerged, mock_merging, mock_run_git,
    ):
        """Conflicts abort in the worktree and return unmerged files."""
        mock_run_git.side_effect = subprocess.CalledProcessError(1, "git merge")
        mock_merging.return_value = True
        mock_unmerged.return_value = ["src/a.py", "src/b.py"]
        mock_abort.return_value = (True, "")

        result = integrate_target_into_worktree(self.WORKTREE, self.TARGET)

        assert result.success is False
        assert result.unmerged_files == ["src/a.py", "src/b.py"]
        # Verify abort was called on the WORKTREE, not the main repo
        mock_abort.assert_called_once_with(repo_path=self.WORKTREE)

    @patch("pokepoke.worktrees.merge_helpers._run_git")
    @patch("pokepoke.git.merge_conflict.is_merge_in_progress")
    @patch("pokepoke.git.merge_conflict.get_unmerged_files")
    @patch("pokepoke.git.git_operations._auto_resolve_pokepoke_conflicts")
    def test_auto_resolves_pokepoke_conflicts(
        self, mock_auto_resolve, mock_unmerged, mock_merging, mock_run_git,
    ):
        """Auto-resolve .pokepoke/ conflicts and complete the merge."""
        # First call: merge fails. Second call: commit succeeds.
        mock_run_git.side_effect = [
            subprocess.CalledProcessError(1, "git merge"),
            Mock(stdout="", returncode=0),  # commit --no-edit
        ]
        mock_merging.return_value = True
        mock_unmerged.return_value = [".pokepoke/state.json"]
        mock_auto_resolve.return_value = []  # all conflicts resolved

        result = integrate_target_into_worktree(self.WORKTREE, self.TARGET)

        assert result.success is True

    @patch("pokepoke.worktrees.merge_helpers._run_git")
    @patch("pokepoke.git.merge_conflict.is_merge_in_progress")
    @patch("pokepoke.git.merge_conflict.get_unmerged_files")
    @patch("pokepoke.git.merge_conflict.abort_merge")
    @patch("pokepoke.git.git_operations._auto_resolve_pokepoke_conflicts")
    def test_partial_pokepoke_auto_resolve(
        self, mock_auto_resolve, mock_abort, mock_unmerged, mock_merging, mock_run_git,
    ):
        """When some conflicts are .pokepoke/ and some are real, fail with remaining."""
        mock_run_git.side_effect = subprocess.CalledProcessError(1, "git merge")
        mock_merging.return_value = True
        mock_unmerged.return_value = [".pokepoke/state.json", "src/real.py"]
        mock_abort.return_value = (True, "")
        mock_auto_resolve.return_value = ["src/real.py"]  # .pokepoke resolved, real file remains

        result = integrate_target_into_worktree(self.WORKTREE, self.TARGET)

        assert result.success is False
        assert result.unmerged_files == ["src/real.py"]

    @patch("pokepoke.worktrees.merge_helpers._run_git")
    @patch("pokepoke.git.merge_conflict.is_merge_in_progress")
    @patch("pokepoke.git.merge_conflict.get_unmerged_files")
    @patch("pokepoke.git.merge_conflict.abort_merge")
    def test_no_merge_in_progress_after_failure(
        self, mock_abort, mock_unmerged, mock_merging, mock_run_git,
    ):
        """When CalledProcessError but no merge in progress, skip abort."""
        mock_run_git.side_effect = subprocess.CalledProcessError(1, "git merge")
        mock_merging.return_value = False
        mock_unmerged.return_value = []

        result = integrate_target_into_worktree(self.WORKTREE, self.TARGET)

        assert result.success is False
        mock_abort.assert_not_called()

    @patch("pokepoke.worktrees.merge_helpers._run_git")
    @patch("pokepoke.git.merge_conflict.is_merge_in_progress")
    @patch("pokepoke.git.merge_conflict.abort_merge")
    def test_timeout_aborts(self, mock_abort, mock_merging, mock_run_git):
        """TimeoutExpired aborts the merge in the worktree."""
        mock_run_git.side_effect = subprocess.TimeoutExpired("git merge", 120)
        mock_merging.return_value = True
        mock_abort.return_value = (True, "")

        result = integrate_target_into_worktree(self.WORKTREE, self.TARGET)

        assert result.success is False
        mock_abort.assert_called_once_with(repo_path=self.WORKTREE)

    @patch("pokepoke.worktrees.merge_helpers._run_git")
    @patch("pokepoke.git.merge_conflict.is_merge_in_progress")
    def test_timeout_no_merge_in_progress(self, mock_merging, mock_run_git):
        """TimeoutExpired without merge in progress skips abort."""
        mock_run_git.side_effect = subprocess.TimeoutExpired("git merge", 120)
        mock_merging.return_value = False

        result = integrate_target_into_worktree(self.WORKTREE, self.TARGET)

        assert result.success is False
