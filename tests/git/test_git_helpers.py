"""Tests for git_helpers utilities."""

import subprocess
from unittest.mock import Mock, patch

from pokepoke.git.git_helpers import (
    restore_beads_stash,
    verify_branch_pushed,
    _run_git_status_with_retry,
    validate_post_merge,
    list_worktrees,
)


class TestVerifyBranchPushed:
    """Tests for verifying remote branches."""

    @patch('pokepoke.git.git_helpers.subprocess.run')
    def test_branch_exists(self, mock_run: Mock) -> None:
        """Returns True when ls-remote finds the branch."""
        mock_run.return_value = Mock(stdout="refs/heads/main", returncode=0)

        assert verify_branch_pushed("main") is True

        mock_run.assert_called_once_with(
            ["git", "ls-remote", "--heads", "origin", "main"],
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            check=True,
            timeout=120,
            cwd=None
        )

    @patch('pokepoke.git.git_helpers.subprocess.run')
    def test_branch_missing(self, mock_run: Mock) -> None:
        """Handles errors from ls-remote and returns False."""
        mock_run.side_effect = subprocess.CalledProcessError(1, ["git", "ls-remote"])

        assert verify_branch_pushed("feature") is False


class TestRestoreBeadsStash:
    """Tests for restore_beads_stash helper."""

    @patch('pokepoke.git.git_helpers.subprocess.run')
    def test_restore_success(self, mock_run: Mock) -> None:
        """Pop succeeds without attempting drop."""
        restore_beads_stash("context")

        mock_run.assert_called_once()
        assert mock_run.call_args[0][0][:3] == ["git", "stash", "pop"]

    @patch('pokepoke.git.git_helpers.print')
    @patch('pokepoke.git.git_helpers.subprocess.run')
    def test_restore_conflict_force_applies_beads(
        self,
        mock_run: Mock,
        mock_print: Mock
    ) -> None:
        """Pop failure force-applies .beads/ from stash then drops."""
        mock_run.side_effect = [
            subprocess.CalledProcessError(1, ["git", "stash", "pop"], stderr="conflict"),
            Mock(returncode=0),  # git checkout -- .
            Mock(returncode=0),  # git checkout stash@{0} -- .beads/
            Mock(returncode=0),  # git stash drop
        ]

        restore_beads_stash("pull failure")

        assert mock_run.call_count == 4
        assert mock_run.call_args_list[1][0][0] == ["git", "checkout", "--", ".beads/"]
        assert mock_run.call_args_list[2][0][0] == ["git", "checkout", "stash@{0}", "--", ".beads/"]
        assert mock_run.call_args_list[3][0][0] == ["git", "stash", "drop"]
        mock_print.assert_any_call("✅ Force-applied .beads/ changes from stash.")

    @patch('pokepoke.git.git_helpers._get_stash_ref', return_value="stash@{0}: On main: beads-daemon-changes")
    @patch('pokepoke.git.git_helpers.print')
    @patch('pokepoke.git.git_helpers.subprocess.run')
    def test_restore_checkout_failure_preserves_stash(
        self,
        mock_run: Mock,
        mock_print: Mock,
        mock_stash_ref: Mock,
    ) -> None:
        """When force-apply fails, stash is preserved with ref logged."""
        mock_run.side_effect = [
            subprocess.CalledProcessError(1, ["git", "stash", "pop"], stderr="conflict"),
            Mock(returncode=0),  # git checkout -- .
            subprocess.CalledProcessError(1, ["git", "checkout"], stderr="checkout failed"),
        ]

        restore_beads_stash("pull failure")

        # Stash drop should NOT be called — stash is preserved
        assert mock_run.call_count == 3
        mock_print.assert_any_call(
            "⚠️ Could not recover .beads/ from stash (ref: stash@{0}: On main: beads-daemon-changes). "
            "Stash preserved — run `git stash list` to inspect."
        )

    @patch('pokepoke.git.git_helpers.print')
    @patch('pokepoke.git.git_helpers.subprocess.run')
    def test_restore_force_apply_ok_drop_fails(
        self,
        mock_run: Mock,
        mock_print: Mock,
    ) -> None:
        """Force-apply succeeds but drop fails — warns user."""
        mock_run.side_effect = [
            subprocess.CalledProcessError(1, ["git", "stash", "pop"], stderr="conflict"),
            Mock(returncode=0),  # git checkout -- .
            Mock(returncode=0),  # git checkout stash@{0} -- .beads/
            subprocess.CalledProcessError(1, ["git", "stash", "drop"], stderr="drop failed"),
        ]

        restore_beads_stash("pull failure")

        assert mock_run.call_count == 4
        mock_print.assert_any_call("✅ Force-applied .beads/ changes from stash.")
        mock_print.assert_any_call("⚠️ Could not drop stash after recovery. Run `git stash list` to clean up.")


class TestRunGitStatusWithRetry:
    """Tests for _run_git_status_with_retry retry logic."""

    @patch('pokepoke.git.git_helpers.subprocess.run')
    def test_succeeds_on_first_attempt(self, mock_run: Mock) -> None:
        """Happy path: command succeeds immediately."""
        mock_run.return_value = Mock(stdout="", returncode=0)
        _run_git_status_with_retry(["git", "status", "--porcelain"])
        assert mock_run.call_count == 1

    @patch('pokepoke.git.git_helpers.time.sleep')
    @patch('pokepoke.git.git_helpers.subprocess.run')
    def test_retries_on_timeout(self, mock_run: Mock, mock_sleep: Mock) -> None:
        """TimeoutExpired triggers up to max_retries attempts."""
        mock_run.side_effect = [
            subprocess.TimeoutExpired("git", 10),
            subprocess.TimeoutExpired("git", 10),
            Mock(stdout="", returncode=0),
        ]
        _run_git_status_with_retry(
            ["git", "status", "--porcelain"], max_retries=3, base_delay=0.1
        )
        assert mock_run.call_count == 3
        assert mock_sleep.call_count == 2

    @patch('pokepoke.git.git_helpers.time.sleep')
    @patch('pokepoke.git.git_helpers.subprocess.run')
    def test_raises_timeout_after_all_retries(self, mock_run: Mock, mock_sleep: Mock) -> None:
        """TimeoutExpired is re-raised after all retries are exhausted."""
        import pytest
        mock_run.side_effect = subprocess.TimeoutExpired("git", 10)
        with pytest.raises(subprocess.TimeoutExpired):
            _run_git_status_with_retry(
                ["git", "status", "--porcelain"], max_retries=2, base_delay=0.1
            )
        assert mock_run.call_count == 2

    @patch('pokepoke.git.git_helpers.time.sleep')
    @patch('pokepoke.git.git_helpers.subprocess.run')
    def test_retries_on_index_lock_in_stderr(self, mock_run: Mock, mock_sleep: Mock) -> None:
        """CalledProcessError with 'index.lock' in stderr triggers retry."""
        index_lock_error = subprocess.CalledProcessError(
            128, "git", stderr="fatal: Unable to create '.git/index.lock': File exists"
        )
        mock_run.side_effect = [index_lock_error, Mock(stdout="", returncode=0)]
        _run_git_status_with_retry(
            ["git", "status", "--porcelain"], max_retries=3, base_delay=0.1
        )
        assert mock_run.call_count == 2
        mock_sleep.assert_called_once()

    @patch('pokepoke.git.git_helpers.subprocess.run')
    def test_raises_immediately_on_non_lock_error(self, mock_run: Mock) -> None:
        """CalledProcessError without 'index.lock' in stderr propagates immediately."""
        import pytest
        mock_run.side_effect = subprocess.CalledProcessError(1, "git", stderr="fatal: not a repo")
        with pytest.raises(subprocess.CalledProcessError):
            _run_git_status_with_retry(["git", "status", "--porcelain"], max_retries=3)
        assert mock_run.call_count == 1

    @patch('pokepoke.git.git_helpers.time.sleep')
    @patch('pokepoke.git.git_helpers.subprocess.run')
    def test_exponential_backoff_delays(self, mock_run: Mock, mock_sleep: Mock) -> None:
        """Back-off delays double on each retry."""
        mock_run.side_effect = [
            subprocess.TimeoutExpired("git", 10),
            subprocess.TimeoutExpired("git", 10),
            Mock(stdout="", returncode=0),
        ]
        _run_git_status_with_retry(
            ["git", "status", "--porcelain"], max_retries=3, base_delay=1.0
        )
        delays = [c.args[0] for c in mock_sleep.call_args_list]
        assert delays == [1.0, 2.0]


class TestValidatePostMerge:
    """Tests for validate_post_merge helper."""

    @patch('pokepoke.git.git_helpers.subprocess.run')
    def test_valid_merge(self, mock_run: Mock) -> None:
        """Returns True when on correct branch with clean status."""
        mock_run.side_effect = [
            Mock(stdout="main\n"),   # git branch --show-current
            Mock(stdout=""),         # git status --porcelain
        ]
        assert validate_post_merge("main") is True

    @patch('pokepoke.git.git_helpers.subprocess.run')
    def test_wrong_branch(self, mock_run: Mock) -> None:
        """Returns False when on wrong branch."""
        mock_run.return_value = Mock(stdout="feature\n")
        assert validate_post_merge("main") is False

    @patch('pokepoke.git.git_helpers.subprocess.run')
    def test_dirty_working_tree(self, mock_run: Mock) -> None:
        """Returns False when working tree has uncommitted changes."""
        mock_run.side_effect = [
            Mock(stdout="main\n"),         # correct branch
            Mock(stdout="M file.py\n"),    # dirty status
        ]
        assert validate_post_merge("main") is False


class TestListWorktrees:
    """Tests for list_worktrees helper."""

    @patch('pokepoke.git.git_helpers.subprocess.run')
    def test_parses_porcelain_output(self, mock_run: Mock) -> None:
        """Parses git worktree list --porcelain output."""
        mock_run.return_value = Mock(stdout=(
            "worktree /repo\n"
            "HEAD abc123\n"
            "branch refs/heads/main\n"
            "\n"
            "worktree /repo/worktrees/task-1\n"
            "HEAD def456\n"
            "branch refs/heads/task-1\n"
        ))
        result = list_worktrees()
        assert len(result) == 2
        assert result[0]["path"] == "/repo"
        assert result[0]["branch"] == "refs/heads/main"
        assert result[1]["path"] == "/repo/worktrees/task-1"

    @patch('pokepoke.git.git_helpers.subprocess.run')
    def test_returns_empty_on_error(self, mock_run: Mock) -> None:
        """Returns empty list on CalledProcessError."""
        mock_run.side_effect = subprocess.CalledProcessError(1, "git")
        assert list_worktrees() == []

    @patch('pokepoke.git.git_helpers.subprocess.run')
    def test_returns_empty_on_timeout(self, mock_run: Mock) -> None:
        """Returns empty list on TimeoutExpired."""
        mock_run.side_effect = subprocess.TimeoutExpired("git", 30)
        assert list_worktrees() == []
