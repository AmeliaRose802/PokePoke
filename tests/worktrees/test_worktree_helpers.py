"""Tests for worktree_helpers module.

Covers validate_worktree_integrity and sync_and_ensure_clean_main_repo.
"""

import subprocess
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from pokepoke.worktrees.worktree_helpers import (
    sync_and_ensure_clean_main_repo,
    validate_worktree_integrity,
)

# ---------------------------------------------------------------------------
# validate_worktree_integrity
# ---------------------------------------------------------------------------

class TestValidateWorktreeIntegrity:
    """Tests for validate_worktree_integrity function."""

    def test_raises_if_worktree_path_does_not_exist(self, tmp_path: Path) -> None:
        """RuntimeError when worktree directory doesn't exist (line 25-28)."""
        missing = tmp_path / "nonexistent"
        with pytest.raises(RuntimeError, match="does not exist after creation"):
            validate_worktree_integrity(missing, "item-1")

    def test_raises_on_iterdir_os_error(self, tmp_path: Path) -> None:
        """RuntimeError when iterdir raises OSError (lines 32-33)."""
        wt = tmp_path / "wt"
        wt.mkdir()

        with patch.object(Path, "iterdir", side_effect=OSError("disk error")), \
             pytest.raises(RuntimeError, match="Cannot read worktree directory"):
            validate_worktree_integrity(wt, "item-1")

    def test_raises_on_empty_directory(self, tmp_path: Path) -> None:
        """RuntimeError when worktree directory is empty (lines 35-39)."""
        wt = tmp_path / "wt"
        wt.mkdir()
        with pytest.raises(RuntimeError, match=r"empty.*0 files"):
            validate_worktree_integrity(wt, "item-1")

    @patch("pokepoke.worktrees.worktree_helpers.run_git")
    def test_raises_when_not_inside_work_tree(self, mock_git, tmp_path: Path) -> None:
        """RuntimeError when rev-parse says not a work tree (lines 48-52)."""
        wt = tmp_path / "wt"
        wt.mkdir()
        (wt / "file.txt").write_text("x")

        mock_git.return_value = Mock(returncode=128, stdout="", stderr="not a work tree")
        with pytest.raises(RuntimeError, match="not recognized by git"):
            validate_worktree_integrity(wt, "item-1")

    @patch("pokepoke.worktrees.worktree_helpers.run_git")
    def test_raises_on_rev_parse_timeout(self, mock_git, tmp_path: Path) -> None:
        """RuntimeError when rev-parse times out (lines 53-54)."""
        wt = tmp_path / "wt"
        wt.mkdir()
        (wt / "file.txt").write_text("x")

        mock_git.side_effect = subprocess.TimeoutExpired("git", 10)
        with pytest.raises(RuntimeError, match="rev-parse timed out"):
            validate_worktree_integrity(wt, "item-1")

    @patch("pokepoke.worktrees.worktree_helpers.run_git")
    def test_raises_when_branch_check_fails(self, mock_git, tmp_path: Path) -> None:
        """RuntimeError when branch --show-current returns non-zero (lines 64-68)."""
        wt = tmp_path / "wt"
        wt.mkdir()
        (wt / "file.txt").write_text("x")

        rev_parse_result = Mock(returncode=0, stdout="true", stderr="")
        branch_result = Mock(returncode=1, stdout="", stderr="detached HEAD")
        mock_git.side_effect = [rev_parse_result, branch_result]

        with pytest.raises(RuntimeError, match="Failed to get current branch"):
            validate_worktree_integrity(wt, "item-1")

    @patch("pokepoke.worktrees.worktree_helpers.run_git")
    @patch("pokepoke.git.git_operations.sanitize_branch_name", return_value="item-1")
    def test_raises_on_wrong_branch(self, mock_sanitize, mock_git, tmp_path: Path) -> None:
        """RuntimeError when worktree is on wrong branch (lines 76-80)."""
        wt = tmp_path / "wt"
        wt.mkdir()
        (wt / "file.txt").write_text("x")

        rev_parse_result = Mock(returncode=0, stdout="true", stderr="")
        branch_result = Mock(returncode=0, stdout="feature/wrong-branch", stderr="")
        mock_git.side_effect = [rev_parse_result, branch_result]

        with pytest.raises(RuntimeError, match=r"wrong branch.*wrong-branch"):
            validate_worktree_integrity(wt, "item-1")

    @patch("pokepoke.worktrees.worktree_helpers.run_git")
    @patch("pokepoke.git.git_operations.sanitize_branch_name", return_value="item-1")
    def test_branch_timeout_raises(self, mock_sanitize, mock_git, tmp_path: Path) -> None:
        """RuntimeError when branch --show-current times out (lines 81-82)."""
        wt = tmp_path / "wt"
        wt.mkdir()
        (wt / "file.txt").write_text("x")

        rev_parse_result = Mock(returncode=0, stdout="true", stderr="")
        mock_git.side_effect = [rev_parse_result, subprocess.TimeoutExpired("git", 10)]

        with pytest.raises(RuntimeError, match="branch --show-current timed out"):
            validate_worktree_integrity(wt, "item-1")

    @patch("pokepoke.worktrees.worktree_helpers.run_git")
    @patch("pokepoke.git.git_operations.sanitize_branch_name", return_value="item-1")
    def test_success_on_correct_branch(self, mock_sanitize, mock_git, tmp_path: Path) -> None:
        """No error when everything is valid (line 84)."""
        wt = tmp_path / "wt"
        wt.mkdir()
        (wt / "file.txt").write_text("x")

        rev_parse_result = Mock(returncode=0, stdout="true", stderr="")
        branch_result = Mock(returncode=0, stdout="task/item-1", stderr="")
        mock_git.side_effect = [rev_parse_result, branch_result]

        validate_worktree_integrity(wt, "item-1")  # should not raise

    @patch("pokepoke.worktrees.worktree_helpers.run_git")
    @patch("pokepoke.git.git_operations.sanitize_branch_name", return_value="item-1")
    def test_true_branch_name_is_tolerated(self, mock_sanitize, mock_git, tmp_path: Path) -> None:
        """Branch name 'true' from test mocks is tolerated (line 76)."""
        wt = tmp_path / "wt"
        wt.mkdir()
        (wt / "file.txt").write_text("x")

        rev_parse_result = Mock(returncode=0, stdout="true", stderr="")
        branch_result = Mock(returncode=0, stdout="true", stderr="")
        mock_git.side_effect = [rev_parse_result, branch_result]

        validate_worktree_integrity(wt, "item-1")  # should not raise

    @patch("pokepoke.worktrees.worktree_helpers.run_git")
    @patch("pokepoke.git.git_operations.sanitize_branch_name", return_value="item-1")
    def test_empty_branch_name_is_tolerated(self, mock_sanitize, mock_git, tmp_path: Path) -> None:
        """Empty branch name (detached HEAD) is tolerated (line 76 guard)."""
        wt = tmp_path / "wt"
        wt.mkdir()
        (wt / "file.txt").write_text("x")

        rev_parse_result = Mock(returncode=0, stdout="true", stderr="")
        branch_result = Mock(returncode=0, stdout="", stderr="")
        mock_git.side_effect = [rev_parse_result, branch_result]

        validate_worktree_integrity(wt, "item-1")  # should not raise


# ---------------------------------------------------------------------------
# sync_and_ensure_clean_main_repo
# ---------------------------------------------------------------------------

class TestSyncAndEnsureCleanMainRepo:
    """Tests for sync_and_ensure_clean_main_repo function."""

    @patch("pokepoke.worktrees.worktree_helpers.run_git")
    @patch("pokepoke.worktrees.worktree_helpers.run_bd_sync_with_retry")
    def test_clean_repo_returns_true(self, mock_sync, mock_git) -> None:
        """Clean repo with no changes returns True (line 136)."""
        mock_sync.return_value = Mock(returncode=0, stdout="", stderr="")
        mock_git.return_value = Mock(stdout="", stderr="")

        assert sync_and_ensure_clean_main_repo("task/x") is True

    @patch("pokepoke.worktrees.worktree_helpers.run_git")
    @patch("pokepoke.worktrees.worktree_helpers.run_bd_sync_with_retry")
    def test_bd_sync_non_zero_continues(self, mock_sync, mock_git) -> None:
        """Non-zero bd sync return code logs warning but continues (lines 97-100)."""
        mock_sync.return_value = Mock(returncode=1, stdout="out", stderr="err")
        mock_git.return_value = Mock(stdout="", stderr="")

        assert sync_and_ensure_clean_main_repo("task/x") is True

    @patch("pokepoke.worktrees.worktree_helpers.run_git")
    @patch("pokepoke.worktrees.worktree_helpers.run_bd_sync_with_retry")
    def test_bd_sync_timeout_continues(self, mock_sync, mock_git) -> None:
        """bd sync timeout logs warning but continues (lines 101-102)."""
        mock_sync.side_effect = subprocess.TimeoutExpired("bd sync", 30)
        mock_git.return_value = Mock(stdout="", stderr="")

        assert sync_and_ensure_clean_main_repo("task/x") is True

    @patch("pokepoke.worktrees.worktree_helpers.commit_all_changes", return_value=(True, ""))
    @patch("pokepoke.worktrees.worktree_helpers.categorize_git_changes")
    @patch("pokepoke.worktrees.worktree_helpers.run_git")
    @patch("pokepoke.worktrees.worktree_helpers.run_bd_sync_with_retry")
    def test_other_changes_committed(self, mock_sync, mock_git, mock_cat, mock_commit) -> None:
        """Pending 'other' changes are committed (lines 110-119)."""
        mock_sync.return_value = Mock(returncode=0)

        status_result = Mock(stdout=" M src/file.py\n")
        mock_git.side_effect = [status_result]  # only git status call
        mock_cat.return_value = {
            "other": [" M src/file.py"],
            "beads": [],
                    }

        result = sync_and_ensure_clean_main_repo("task/x")

        assert result is True
        mock_commit.assert_called_once()

    @patch("pokepoke.worktrees.worktree_helpers.commit_all_changes", return_value=(False, "commit failed"))
    @patch("pokepoke.worktrees.worktree_helpers.categorize_git_changes")
    @patch("pokepoke.worktrees.worktree_helpers.run_git")
    @patch("pokepoke.worktrees.worktree_helpers.run_bd_sync_with_retry")
    def test_commit_failure_returns_false(self, mock_sync, mock_git, mock_cat, mock_commit) -> None:
        """Failed commit of pending changes returns False (lines 116-118)."""
        mock_sync.return_value = Mock(returncode=0)
        mock_git.return_value = Mock(stdout=" M src/file.py\n")
        mock_cat.return_value = {
            "other": [" M src/file.py"],
            "beads": [],
                    }

        assert sync_and_ensure_clean_main_repo("task/x") is False

    @patch("pokepoke.worktrees.worktree_helpers.categorize_git_changes")
    @patch("pokepoke.worktrees.worktree_helpers.run_git")
    @patch("pokepoke.worktrees.worktree_helpers.run_bd_sync_with_retry")
    def test_beads_changes_committed(self, mock_sync, mock_git, mock_cat) -> None:
        """Beads changes are committed separately (lines 120-127)."""
        mock_sync.return_value = Mock(returncode=0)

        status_result = Mock(stdout=" M .beads/db.json\n")
        commit_result = Mock(returncode=0)
        mock_git.side_effect = [status_result, None, commit_result]
        mock_cat.return_value = {
            "other": [],
            "beads": [" M .beads/db.json"],
                    }

        result = sync_and_ensure_clean_main_repo("task/x")
        assert result is True

        # Verify git add .beads/ was called
        git_calls = mock_git.call_args_list
        add_call = git_calls[1]
        assert ".beads/" in str(add_call)

    @patch("pokepoke.worktrees.worktree_helpers.categorize_git_changes")
    @patch("pokepoke.worktrees.worktree_helpers.run_git")
    @patch("pokepoke.worktrees.worktree_helpers.run_bd_sync_with_retry")
    def test_no_worktree_category_in_changes(self, mock_sync, mock_git, mock_cat) -> None:
        """No 'worktree' category exists — worktrees/ is gitignored.

        categorize_git_changes only returns 'other', 'beads', 'untracked'.
        If worktree files somehow appear they land in 'other'.
        """
        mock_sync.return_value = Mock(returncode=0)

        # Status is clean — nothing to do
        mock_git.return_value = Mock(stdout="")

        result = sync_and_ensure_clean_main_repo("task/x")
        assert result is True
        # Only the status call, no add/commit for worktrees
        assert mock_git.call_count == 1

    @patch("pokepoke.worktrees.worktree_helpers.run_git")
    @patch("pokepoke.worktrees.worktree_helpers.run_bd_sync_with_retry")
    def test_git_status_error_returns_false(self, mock_sync, mock_git) -> None:
        """CalledProcessError from git status returns False (lines 137-139)."""
        mock_sync.return_value = Mock(returncode=0)
        mock_git.side_effect = subprocess.CalledProcessError(1, "git status")

        assert sync_and_ensure_clean_main_repo("task/x") is False

    @patch("pokepoke.worktrees.worktree_helpers.run_git")
    @patch("pokepoke.worktrees.worktree_helpers.run_bd_sync_with_retry")
    def test_git_status_timeout_returns_false(self, mock_sync, mock_git) -> None:
        """TimeoutExpired from git status returns False (line 137)."""
        mock_sync.return_value = Mock(returncode=0)
        mock_git.side_effect = subprocess.TimeoutExpired("git", 30)

        assert sync_and_ensure_clean_main_repo("task/x") is False

    @patch("pokepoke.worktrees.worktree_helpers.commit_all_changes", return_value=(True, ""))
    @patch("pokepoke.worktrees.worktree_helpers.categorize_git_changes")
    @patch("pokepoke.worktrees.worktree_helpers.run_git")
    @patch("pokepoke.worktrees.worktree_helpers.run_bd_sync_with_retry")
    def test_many_other_changes_truncated(self, mock_sync, mock_git, mock_cat, mock_commit) -> None:
        """When >10 other changes, only 10 are logged (lines 113-114)."""
        mock_sync.return_value = Mock(returncode=0)
        mock_git.return_value = Mock(stdout="changes\n")
        mock_cat.return_value = {
            "other": [f" M file{i}.py" for i in range(15)],
            "beads": [],
                    }

        result = sync_and_ensure_clean_main_repo("task/x")
        assert result is True

    @patch("pokepoke.worktrees.worktree_helpers.commit_all_changes", return_value=(True, ""))
    @patch("pokepoke.worktrees.worktree_helpers.categorize_git_changes")
    @patch("pokepoke.worktrees.worktree_helpers.run_git")
    @patch("pokepoke.worktrees.worktree_helpers.run_bd_sync_with_retry")
    def test_all_change_types_committed(self, mock_sync, mock_git, mock_cat, mock_commit) -> None:
        """Both 'other' and 'beads' changes committed in sequence.

        worktrees/ is gitignored so no 'worktree' category exists.
        """
        mock_sync.return_value = Mock(returncode=0)

        mock_git.side_effect = [
            Mock(stdout=" M src/f.py\n M .beads/x\n"),
            None,  # git add .beads/
            None,  # git commit beads
        ]
        mock_cat.return_value = {
            "other": [" M src/f.py"],
            "beads": [" M .beads/x"],
        }

        result = sync_and_ensure_clean_main_repo("task/x")
        assert result is True
        mock_commit.assert_called_once()

    @patch("pokepoke.worktrees.worktree_helpers.run_git")
    @patch("pokepoke.worktrees.worktree_helpers.run_bd_sync_with_retry")
    def test_cwd_passed_to_git(self, mock_sync, mock_git) -> None:
        """cwd parameter is forwarded to git commands."""
        mock_sync.return_value = Mock(returncode=0)
        mock_git.return_value = Mock(stdout="")

        sync_and_ensure_clean_main_repo("task/x", cwd="/my/repo")

        git_call = mock_git.call_args
        assert git_call.kwargs.get("cwd") == "/my/repo" or "/my/repo" in str(git_call)
