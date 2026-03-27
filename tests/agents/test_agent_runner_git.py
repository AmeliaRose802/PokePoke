"""Unit tests for agent_runner module."""

import subprocess
from unittest.mock import Mock, patch

from pokepoke.git.git_operations import commit_all_changes, has_uncommitted_changes


class TestHasUncommittedChanges:
    """Test has_uncommitted_changes function."""

    @patch('pokepoke.git.git_operations.subprocess.run')
    def test_no_changes(self, mock_run: Mock) -> None:
        """Test repository with no uncommitted changes."""
        mock_run.return_value = Mock(
            stdout="",
            returncode=0
        )

        result = has_uncommitted_changes()

        assert result is False
        mock_run.assert_called_once_with(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            check=True,
            timeout=10,
            cwd=None
        )

    @patch('pokepoke.git.git_operations.subprocess.run')
    def test_has_changes(self, mock_run: Mock) -> None:
        """Test repository with uncommitted changes."""
        mock_run.return_value = Mock(
            stdout=" M src/file.py",
            returncode=0
        )

        result = has_uncommitted_changes()

        assert result is True

    @patch('pokepoke.git.git_operations.subprocess.run')
    def test_git_error(self, mock_run: Mock) -> None:
        """Test error handling when git command fails.

        When git fails, assume dirty to prevent data loss during merge operations.
        """
        mock_run.side_effect = subprocess.CalledProcessError(1, "git status")

        result = has_uncommitted_changes()

        assert result is True  # Assume dirty when git fails to prevent data loss


class TestCommitAllChanges:
    """Test commit_all_changes function."""

    @patch('pokepoke.git.git_operations.subprocess.run')
    def test_successful_commit(self, mock_run: Mock) -> None:
        """Test successful commit."""
        mock_run.return_value = Mock(returncode=0, stderr="")

        success, error_msg = commit_all_changes("Test commit")

        assert success is True
        assert error_msg == ""
        assert mock_run.call_count == 2

    @patch('pokepoke.git.git_operations.subprocess.run')
    def test_commit_failure_with_errors(self, mock_run: Mock) -> None:
        """Test commit failure with error messages."""
        mock_run.side_effect = [
            Mock(returncode=0),  # git add succeeds
            Mock(
                returncode=1,
                stderr="error: pre-commit hook failed\nTests failed"
            )
        ]

        success, error_msg = commit_all_changes("Test commit")

        assert success is False
        assert "pre-commit hook failed" in error_msg
