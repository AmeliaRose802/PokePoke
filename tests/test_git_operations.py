"""Unit tests for git_operations module."""

import subprocess
from unittest.mock import Mock, patch, call
import pytest

from src.pokepoke.git_operations import (
    verify_main_repo_clean,
    handle_beads_auto_commit,
    check_main_repo_ready_for_merge,
    has_uncommitted_changes,
    commit_all_changes
)


class TestVerifyMainRepoClean:
    """Test verify_main_repo_clean function."""
    
    @patch('src.pokepoke.git_operations.subprocess.run')
    def test_clean_repo(self, mock_run: Mock) -> None:
        """Test clean repository with no changes."""
        mock_run.return_value = Mock(
            stdout="",
            returncode=0
        )
        
        is_clean, output, non_beads_changes = verify_main_repo_clean()
        
        assert is_clean is True
        assert output == ""
        assert non_beads_changes == []
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
    
    @patch('src.pokepoke.git_operations.subprocess.run')
    def test_only_beads_changes(self, mock_run: Mock) -> None:
        """Test repository with only beads changes."""
        mock_run.return_value = Mock(
            stdout=" M .beads/issues.jsonl\n M .beads/beads.db",
            returncode=0
        )
        
        is_clean, output, non_beads_changes = verify_main_repo_clean()
        
        assert is_clean is True
        assert ".beads/" in output
        assert non_beads_changes == []
    
    @patch('src.pokepoke.git_operations.subprocess.run')
    def test_non_beads_changes(self, mock_run: Mock) -> None:
        """Test repository with non-beads changes."""
        mock_run.return_value = Mock(
            stdout=" M src/pokepoke/orchestrator.py\n M tests/test_orchestrator.py",
            returncode=0
        )
        
        is_clean, output, non_beads_changes = verify_main_repo_clean()
        
        assert is_clean is False
        assert "orchestrator.py" in output
        assert len(non_beads_changes) == 2
        assert "orchestrator.py" in non_beads_changes[0]
        assert "test_orchestrator.py" in non_beads_changes[1]
    
    @patch('src.pokepoke.git_operations.subprocess.run')
    def test_mixed_changes(self, mock_run: Mock) -> None:
        """Test repository with both beads and non-beads changes."""
        mock_run.return_value = Mock(
            stdout=" M .beads/issues.jsonl\n M src/pokepoke/orchestrator.py",
            returncode=0
        )
        
        is_clean, output, non_beads_changes = verify_main_repo_clean()
        
        assert is_clean is False
        assert len(non_beads_changes) == 1
        assert non_beads_changes[0] == " M src/pokepoke/orchestrator.py"
    
    @patch('src.pokepoke.git_operations.subprocess.run')
    def test_git_error(self, mock_run: Mock) -> None:
        """Test error handling when git command fails."""
        mock_run.side_effect = subprocess.CalledProcessError(1, "git status")
        
        with pytest.raises(RuntimeError, match="Error checking git status"):
            verify_main_repo_clean()
    
    @patch('src.pokepoke.git_operations.subprocess.run')
    def test_empty_lines_filtered(self, mock_run: Mock) -> None:
        """Test that empty lines are filtered out."""
        mock_run.return_value = Mock(
            stdout=" M src/file.py\n\n M other.py",
            returncode=0
        )
        
        is_clean, output, non_beads_changes = verify_main_repo_clean()
        
        assert is_clean is False
        assert len(non_beads_changes) == 2


class TestHandleBeadsAutoCommit:
    """Test handle_beads_auto_commit function."""
    
    @patch('src.pokepoke.git_operations.subprocess.run')
    def test_successful_commit(self, mock_run: Mock) -> None:
        """Test successful beads auto-commit."""
        mock_run.return_value = Mock(returncode=0)
        
        handle_beads_auto_commit()
        
        assert mock_run.call_count == 2
        mock_run.assert_any_call(["git", "add", ".beads/"], check=True, encoding='utf-8', errors='replace', timeout=10)
        mock_run.assert_any_call(
            ["git", "commit", "-m", "chore: sync beads before worktree merge"],
            check=True,
            capture_output=True,
            encoding='utf-8',
            errors='replace',
            timeout=300
        )
    
    @patch('src.pokepoke.git_operations.subprocess.run')
    def test_commit_failure(self, mock_run: Mock) -> None:
        """Test failure during beads commit."""
        mock_run.side_effect = [
            Mock(returncode=0),  # git add succeeds
            subprocess.CalledProcessError(1, "git commit")  # git commit fails
        ]
        
        with pytest.raises(RuntimeError, match="Failed to commit beads changes"):
            handle_beads_auto_commit()
    
    @patch('src.pokepoke.git_operations.subprocess.run')
    def test_add_failure(self, mock_run: Mock) -> None:
        """Test failure during git add."""
        mock_run.side_effect = subprocess.CalledProcessError(1, "git add")
        
        with pytest.raises(RuntimeError, match="Failed to commit beads changes"):
            handle_beads_auto_commit()


class TestCheckMainRepoReadyForMerge:
    """Test check_main_repo_ready_for_merge function."""
    
    @patch('src.pokepoke.git_operations.handle_beads_auto_commit')
    @patch('src.pokepoke.git_operations.verify_main_repo_clean')
    def test_clean_repo(self, mock_verify: Mock, mock_handle: Mock) -> None:
        """Test clean repository ready for merge."""
        mock_verify.return_value = (True, "", [])
        
        is_ready, error_msg = check_main_repo_ready_for_merge()
        
        assert is_ready is True
        assert error_msg == ""
        mock_handle.assert_not_called()
    
    @patch('src.pokepoke.git_operations.handle_beads_auto_commit')
    @patch('src.pokepoke.git_operations.verify_main_repo_clean')
    def test_only_beads_changes_auto_commit(
        self, 
        mock_verify: Mock, 
        mock_handle: Mock
    ) -> None:
        """Test beads-only changes trigger auto-commit."""
        mock_verify.return_value = (True, " M .beads/issues.jsonl", [])
        
        is_ready, error_msg = check_main_repo_ready_for_merge()
        
        assert is_ready is True
        assert error_msg == ""
        mock_handle.assert_called_once()
    
    @patch('src.pokepoke.git_operations.handle_beads_auto_commit')
    @patch('src.pokepoke.git_operations.verify_main_repo_clean')
    def test_non_beads_changes_not_ready(
        self, 
        mock_verify: Mock, 
        mock_handle: Mock
    ) -> None:
        """Test non-beads changes prevent merge."""
        mock_verify.return_value = (
            False, 
            " M src/file.py", 
            [" M src/file.py"]
        )
        
        is_ready, error_msg = check_main_repo_ready_for_merge()
        
        assert is_ready is False
        assert "uncommitted non-beads changes" in error_msg
        assert "src/file.py" in error_msg
        mock_handle.assert_not_called()
    
    @patch('src.pokepoke.git_operations.handle_beads_auto_commit')
    @patch('src.pokepoke.git_operations.verify_main_repo_clean')
    def test_auto_commit_failure(
        self, 
        mock_verify: Mock, 
        mock_handle: Mock
    ) -> None:
        """Test auto-commit failure is caught."""
        mock_verify.return_value = (True, " M .beads/issues.jsonl", [])
        mock_handle.side_effect = RuntimeError("Commit failed")
        
        is_ready, error_msg = check_main_repo_ready_for_merge()
        
        assert is_ready is False
        assert "Error checking main repo status" in error_msg
        assert "Commit failed" in error_msg
    
    @patch('src.pokepoke.git_operations.verify_main_repo_clean')
    def test_verify_exception(self, mock_verify: Mock) -> None:
        """Test exception during verification."""
        mock_verify.side_effect = RuntimeError("Git error")
        
        is_ready, error_msg = check_main_repo_ready_for_merge()
        
        assert is_ready is False
        assert "Error checking main repo status" in error_msg
        assert "Git error" in error_msg


class TestHasUncommittedChanges:
    """Test has_uncommitted_changes function."""
    
    @patch('src.pokepoke.git_operations.subprocess.run')
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
    
    @patch('src.pokepoke.git_operations.subprocess.run')
    def test_has_changes(self, mock_run: Mock) -> None:
        """Test repository with uncommitted changes."""
        mock_run.return_value = Mock(
            stdout=" M src/file.py\n M tests/test.py",
            returncode=0
        )
        
        result = has_uncommitted_changes()
        
        assert result is True
    
    @patch('src.pokepoke.git_operations.subprocess.run')
    def test_whitespace_only(self, mock_run: Mock) -> None:
        """Test output with only whitespace is treated as no changes."""
        mock_run.return_value = Mock(
            stdout="   \n  \n",
            returncode=0
        )
        
        result = has_uncommitted_changes()
        
        assert result is False
    
    @patch('src.pokepoke.git_operations.subprocess.run')
    def test_git_error(self, mock_run: Mock) -> None:
        """Test error handling when git command fails."""
        mock_run.side_effect = subprocess.CalledProcessError(1, "git status")
        
        result = has_uncommitted_changes()
        
        assert result is False


class TestCommitAllChanges:
    """Test commit_all_changes function."""
    
    @patch('src.pokepoke.git_operations.subprocess.run')
    def test_successful_commit(self, mock_run: Mock) -> None:
        """Test successful commit with all changes."""
        mock_run.return_value = Mock(returncode=0, stderr="")
        
        success, error_msg = commit_all_changes("Test commit")
        
        assert success is True
        assert error_msg == ""
        assert mock_run.call_count == 2
        mock_run.assert_any_call(
            ["git", "add", "-A"],
            check=True,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=240,
            cwd=None
        )
        mock_run.assert_any_call(
            ["git", "commit", "-m", "Test commit"],
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=300,
            cwd=None
        )
    
    @patch('src.pokepoke.git_operations.subprocess.run')
    def test_commit_with_default_message(self, mock_run: Mock) -> None:
        """Test commit with default message."""
        mock_run.return_value = Mock(returncode=0, stderr="")
        
        success, error_msg = commit_all_changes()
        
        assert success is True
        # Check default message was used
        calls = mock_run.call_args_list
        assert calls[1][0][0] == ["git", "commit", "-m", "Auto-commit by PokePoke"]
    
    @patch('src.pokepoke.git_operations.subprocess.run')
    def test_commit_failure_with_stderr(self, mock_run: Mock) -> None:
        """Test commit failure with error details in stderr."""
        mock_run.side_effect = [
            Mock(returncode=0),  # git add succeeds
            Mock(
                returncode=1,
                stderr="error: pre-commit hook failed\nTest failed\nhint: use --no-verify"
            )
        ]
        
        success, error_msg = commit_all_changes("Test commit")
        
        assert success is False
        assert "error: pre-commit hook failed" in error_msg
        assert "Test failed" in error_msg
        assert "hint:" not in error_msg  # Hints should be filtered
    
    @patch('src.pokepoke.git_operations.subprocess.run')
    def test_commit_failure_no_stderr(self, mock_run: Mock) -> None:
        """Test commit failure with no error details."""
        mock_run.side_effect = [
            Mock(returncode=0),  # git add succeeds
            Mock(returncode=1, stderr="")
        ]
        
        success, error_msg = commit_all_changes("Test commit")
        
        assert success is False
        assert "Commit failed" in error_msg
    
    @patch('src.pokepoke.git_operations.subprocess.run')
    def test_add_stage_exception(self, mock_run: Mock) -> None:
        """Test exception during git add stage."""
        mock_run.side_effect = subprocess.CalledProcessError(
            1, 
            "git add", 
            stderr="Permission denied"
        )
        
        success, error_msg = commit_all_changes("Test commit")
        
        assert success is False
        assert "Commit error" in error_msg
        assert "Permission denied" in error_msg
    
    @patch('src.pokepoke.git_operations.subprocess.run')
    def test_commit_stage_exception(self, mock_run: Mock) -> None:
        """Test exception during commit stage."""
        mock_run.side_effect = [
            Mock(returncode=0),  # git add succeeds
            subprocess.CalledProcessError(1, "git commit", stderr="Disk full")
        ]
        
        success, error_msg = commit_all_changes("Test commit")
        
        assert success is False
        assert "Commit error" in error_msg
        assert "Disk full" in error_msg
    
    @patch('src.pokepoke.git_operations.subprocess.run')
    def test_error_line_limit(self, mock_run: Mock) -> None:
        """Test that error messages are limited to 5 lines."""
        long_stderr = "\n".join([f"error line {i}" for i in range(10)])
        mock_run.side_effect = [
            Mock(returncode=0),  # git add succeeds
            Mock(returncode=1, stderr=long_stderr)
        ]
        
        success, error_msg = commit_all_changes("Test commit")
        
        assert success is False
        # Should only have first 5 error lines
        error_lines = error_msg.split('\n')
        assert len(error_lines) <= 6  # 5 errors + potential join artifacts
