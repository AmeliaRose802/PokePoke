"""Tests for git_helpers utilities."""

import subprocess
from unittest.mock import Mock, patch

from src.pokepoke.git_helpers import restore_beads_stash, verify_branch_pushed


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
            check=True
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
