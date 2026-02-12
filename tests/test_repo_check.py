"""Tests for repository check utilities."""

import subprocess
from pathlib import Path
from unittest.mock import Mock, patch
from pokepoke.repo_check import check_and_commit_main_repo


class TestCheckAndCommitMainRepo:
    """Test check_and_commit_main_repo function."""
    
    def test_clean_repository_returns_true(self):
        """Test that a clean repository returns True."""
        mock_logger = Mock()
        repo_path = Path("/fake/repo")
        
        with patch('subprocess.run') as mock_run:
            # Mock git status showing no changes
            mock_run.return_value = Mock(
                returncode=0,
                stdout="",
                stderr=""
            )
            
            result = check_and_commit_main_repo(repo_path, mock_logger)
            
            assert result is True
            mock_run.assert_called_once()
            assert mock_run.call_args[0][0] == ["git", "status", "--porcelain"]
    
    def test_beads_changes_only_continues(self):
        """Test that only beads changes allows continuation."""
        mock_logger = Mock()
        repo_path = Path("/fake/repo")
        
        with patch('subprocess.run') as mock_run, \
             patch('builtins.print') as mock_print:
            # Mock git status showing only beads changes
            mock_run.return_value = Mock(
                returncode=0,
                stdout=" M .beads/database.json\n M .beads/cache/item1.json",
                stderr=""
            )
            
            result = check_and_commit_main_repo(repo_path, mock_logger)
            
            assert result is True
            # Should print info about beads sync
            assert any("Beads database changes" in str(call) for call in mock_print.call_args_list)
    
    def test_worktree_changes_auto_commit(self):
        """Test that worktree changes are automatically committed."""
        mock_logger = Mock()
        repo_path = Path("/fake/repo")
        
        with patch('subprocess.run') as mock_run:
            # First call: git status showing worktree changes
            # Subsequent calls: git add and git commit
            mock_run.side_effect = [
                Mock(returncode=0, stdout=" D worktrees/task-1/file.py", stderr=""),
                Mock(returncode=0),  # git add
                Mock(returncode=0)   # git commit
            ]
            
            result = check_and_commit_main_repo(repo_path, mock_logger)
            
            assert result is True
            assert mock_run.call_count == 3
            # Check git add was called
            assert mock_run.call_args_list[1][0][0] == ["git", "add", "worktrees/"]
            # Check git commit was called
            assert "git" in mock_run.call_args_list[2][0][0]
            assert "commit" in mock_run.call_args_list[2][0][0]
    
    def test_git_status_failure_not_a_repo(self):
        """Test handling git status failure when not a git repo."""
        mock_logger = Mock()
        repo_path = Path("/fake/repo")
        
        with patch('subprocess.run') as mock_run, \
             patch('pathlib.Path.exists') as mock_exists:
            # Mock git status failing
            mock_run.side_effect = subprocess.CalledProcessError(
                returncode=128,
                cmd=["git", "status"],
                stderr="fatal: not a git repository"
            )
            # Mock .git directory not existing
            mock_exists.return_value = False
            
            result = check_and_commit_main_repo(repo_path, mock_logger)
            
            assert result is False
            mock_logger.log_orchestrator.assert_any_call(
                f"{repo_path} is not a git repository",
                level="ERROR"
            )
    
    def test_git_status_failure_other_error_continues(self):
        """Test that other git errors allow continuation."""
        mock_logger = Mock()
        repo_path = Path("/fake/repo")
        
        with patch('subprocess.run') as mock_run, \
             patch('pathlib.Path.exists') as mock_exists:
            # Mock git status failing
            mock_run.side_effect = subprocess.CalledProcessError(
                returncode=1,
                cmd=["git", "status"],
                stderr="some other error"
            )
            # Mock .git directory existing
            mock_exists.return_value = True
            
            result = check_and_commit_main_repo(repo_path, mock_logger)
            
            assert result is True
            mock_logger.log_orchestrator.assert_any_call(
                "git status failed: some other error",
                level="WARNING"
            )
    
    def test_other_changes_invoke_cleanup_agent_success(self):
        """Test that other changes invoke cleanup agent successfully."""
        mock_logger = Mock()
        repo_path = Path("/fake/repo")
        
        with patch('subprocess.run') as mock_run, \
             patch('pokepoke.agent_runner.invoke_cleanup_agent') as mock_cleanup:
            # Mock git status showing regular changes
            mock_run.return_value = Mock(
                returncode=0,
                stdout=" M src/module.py\n M README.md",
                stderr=""
            )
            # Mock cleanup agent succeeding
            mock_cleanup.return_value = (True, Mock())
            
            result = check_and_commit_main_repo(repo_path, mock_logger)
            
            assert result is True
            mock_cleanup.assert_called_once()
            # Verify cleanup item was created with correct properties
            cleanup_item = mock_cleanup.call_args[0][0]
            assert cleanup_item.id == "cleanup-main-repo"
            assert "uncommitted changes" in cleanup_item.title.lower()
    
    def test_other_changes_invoke_cleanup_agent_failure(self):
        """Test that cleanup agent failure returns False."""
        mock_logger = Mock()
        repo_path = Path("/fake/repo")
        
        with patch('subprocess.run') as mock_run, \
             patch('pokepoke.agent_runner.invoke_cleanup_agent') as mock_cleanup:
            # Mock git status showing regular changes
            mock_run.return_value = Mock(
                returncode=0,
                stdout=" M src/module.py",
                stderr=""
            )
            # Mock cleanup agent failing
            mock_cleanup.return_value = (False, Mock())
            
            result = check_and_commit_main_repo(repo_path, mock_logger)
            
            assert result is False
            mock_logger.log_orchestrator.assert_any_call(
                "Cleanup agent failed to resolve uncommitted changes",
                level="ERROR"
            )
    
    def test_untracked_files_ignored(self):
        """Test that untracked files don't trigger cleanup agent."""
        mock_logger = Mock()
        repo_path = Path("/fake/repo")
        
        with patch('subprocess.run') as mock_run:
            # Mock git status showing only untracked files
            mock_run.return_value = Mock(
                returncode=0,
                stdout="?? new_file.py\n?? temp/",
                stderr=""
            )
            
            result = check_and_commit_main_repo(repo_path, mock_logger)
            
            assert result is True
    
    def test_mixed_changes_triggers_cleanup(self):
        """Test that mixed changes (beads + other) still trigger cleanup."""
        mock_logger = Mock()
        repo_path = Path("/fake/repo")
        
        with patch('subprocess.run') as mock_run, \
             patch('pokepoke.agent_runner.invoke_cleanup_agent') as mock_cleanup:
            # Mock git status with beads and other changes
            mock_run.return_value = Mock(
                returncode=0,
                stdout=" M .beads/database.json\n M src/main.py",
                stderr=""
            )
            mock_cleanup.return_value = (True, Mock())
            
            result = check_and_commit_main_repo(repo_path, mock_logger)
            
            assert result is True
            # Should invoke cleanup agent for non-beads changes
            mock_cleanup.assert_called_once()
    
    def test_many_other_changes_truncated_output(self):
        """Test that many changes are truncated in output."""
        mock_logger = Mock()
        repo_path = Path("/fake/repo")
        
        with patch('subprocess.run') as mock_run, \
             patch('pokepoke.agent_runner.invoke_cleanup_agent') as mock_cleanup, \
             patch('builtins.print') as mock_print:
            # Mock git status with 15 changes
            changes = [f" M file{i}.py" for i in range(15)]
            mock_run.return_value = Mock(
                returncode=0,
                stdout="\n".join(changes),
                stderr=""
            )
            mock_cleanup.return_value = (True, Mock())
            
            result = check_and_commit_main_repo(repo_path, mock_logger)
            
            assert result is True
            # Should print "and X more" message
            print_calls = [str(call) for call in mock_print.call_args_list]
            assert any("and 5 more" in call for call in print_calls)
    
    def test_git_error_no_stderr(self):
        """Test git error handling when stderr is empty."""
        mock_logger = Mock()
        repo_path = Path("/fake/repo")
        
        with patch('subprocess.run') as mock_run, \
             patch('pathlib.Path.exists') as mock_exists:
            # Mock git status failing with no stderr
            mock_run.side_effect = subprocess.CalledProcessError(
                returncode=1,
                cmd=["git", "status"],
                stderr=""
            )
            mock_exists.return_value = True
            
            result = check_and_commit_main_repo(repo_path, mock_logger)
            
            assert result is True
            # Should use "exit code X" format
            log_calls = [str(call) for call in mock_logger.log_orchestrator.call_args_list]
            assert any("exit code 1" in call for call in log_calls)
