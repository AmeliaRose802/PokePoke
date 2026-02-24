"""Tests for git_helpers utilities."""

import subprocess
from unittest.mock import Mock, patch

from src.pokepoke.git_helpers import (
    restore_beads_stash,
    verify_branch_pushed,
    _run_git_status_with_retry,
)


class TestVerifyBranchPushed:
    """Tests for verifying remote branches."""

    @patch('src.pokepoke.git_helpers.subprocess.run')
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
            timeout=120
        )

    @patch('src.pokepoke.git_helpers.subprocess.run')
    def test_branch_missing(self, mock_run: Mock) -> None:
        """Handles errors from ls-remote and returns False."""
        mock_run.side_effect = subprocess.CalledProcessError(1, ["git", "ls-remote"])

        assert verify_branch_pushed("feature") is False


class TestRestoreBeadsStash:
    """Tests for restore_beads_stash helper."""

    @patch('src.pokepoke.git_helpers.subprocess.run')
    def test_restore_success(self, mock_run: Mock) -> None:
        """Pop succeeds without attempting drop."""
        restore_beads_stash("context")

        mock_run.assert_called_once()
        assert mock_run.call_args[0][0][:3] == ["git", "stash", "pop"]

    @patch('src.pokepoke.git_helpers.print')
    @patch('src.pokepoke.git_helpers.subprocess.run')
    def test_restore_conflict_drops_stash(
        self,
        mock_run: Mock,
        mock_print: Mock
    ) -> None:
        """Pop failure triggers drop to avoid accumulation."""
        mock_run.side_effect = [
            subprocess.CalledProcessError(1, ["git", "stash", "pop"], stderr="conflict"),
            Mock(returncode=0)
        ]

        restore_beads_stash("pull failure")

        assert mock_run.call_count == 2
        assert mock_run.call_args_list[1][0][0] == ["git", "stash", "drop"]
        mock_print.assert_any_call("⚠️ Dropped beads stash entry to avoid accumulation.")

    @patch('src.pokepoke.git_helpers.print')
    @patch('src.pokepoke.git_helpers.subprocess.run')
    def test_restore_conflict_and_drop_failure(
        self,
        mock_run: Mock,
        mock_print: Mock
    ) -> None:
        """Logs both pop and drop failures."""
        mock_run.side_effect = [
            subprocess.CalledProcessError(1, ["git", "stash", "pop"], stderr="conflict"),
            subprocess.CalledProcessError(1, ["git", "stash", "drop"], stderr="drop failed"),
        ]

        restore_beads_stash("pull failure")

        assert mock_run.call_count == 2
        mock_print.assert_any_call("⚠️ Additionally failed to drop beads stash entry. Run `git stash list` to clean up manually.")


class TestRunGitStatusWithRetry:
    """Tests for _run_git_status_with_retry retry logic."""

    @patch('src.pokepoke.git_helpers.subprocess.run')
    def test_succeeds_on_first_attempt(self, mock_run: Mock) -> None:
        """Happy path: command succeeds immediately."""
        mock_run.return_value = Mock(stdout="", returncode=0)
        _run_git_status_with_retry(["git", "status", "--porcelain"])
        assert mock_run.call_count == 1

    @patch('src.pokepoke.git_helpers.time.sleep')
    @patch('src.pokepoke.git_helpers.subprocess.run')
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

    @patch('src.pokepoke.git_helpers.time.sleep')
    @patch('src.pokepoke.git_helpers.subprocess.run')
    def test_raises_timeout_after_all_retries(self, mock_run: Mock, mock_sleep: Mock) -> None:
        """TimeoutExpired is re-raised after all retries are exhausted."""
        import pytest
        mock_run.side_effect = subprocess.TimeoutExpired("git", 10)
        with pytest.raises(subprocess.TimeoutExpired):
            _run_git_status_with_retry(
                ["git", "status", "--porcelain"], max_retries=2, base_delay=0.1
            )
        assert mock_run.call_count == 2

    @patch('src.pokepoke.git_helpers.time.sleep')
    @patch('src.pokepoke.git_helpers.subprocess.run')
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

    @patch('src.pokepoke.git_helpers.subprocess.run')
    def test_raises_immediately_on_non_lock_error(self, mock_run: Mock) -> None:
        """CalledProcessError without 'index.lock' in stderr propagates immediately."""
        import pytest
        mock_run.side_effect = subprocess.CalledProcessError(1, "git", stderr="fatal: not a repo")
        with pytest.raises(subprocess.CalledProcessError):
            _run_git_status_with_retry(["git", "status", "--porcelain"], max_retries=3)
        assert mock_run.call_count == 1

    @patch('src.pokepoke.git_helpers.time.sleep')
    @patch('src.pokepoke.git_helpers.subprocess.run')
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
