"""Unit tests for agent_runner module."""

import subprocess
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch, call, mock_open
import pytest

from pokepoke.agent_runner import (
    run_maintenance_agent,
    _run_beads_only_agent,
    _run_worktree_agent
)
from pokepoke.git_operations import has_uncommitted_changes, commit_all_changes
from pokepoke.types import BeadsWorkItem, AgentStats, CopilotResult


class TestHasUncommittedChanges:
    """Test has_uncommitted_changes function."""
    
    @patch('pokepoke.git_operations.subprocess.run')
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
            timeout=10
        )
    
    @patch('pokepoke.git_operations.subprocess.run')
    def test_has_changes(self, mock_run: Mock) -> None:
        """Test repository with uncommitted changes."""
        mock_run.return_value = Mock(
            stdout=" M src/file.py",
            returncode=0
        )
        
        result = has_uncommitted_changes()
        
        assert result is True
    
    @patch('pokepoke.git_operations.subprocess.run')
    def test_git_error(self, mock_run: Mock) -> None:
        """Test error handling when git command fails."""
        mock_run.side_effect = subprocess.CalledProcessError(1, "git status")
        
        result = has_uncommitted_changes()
        
        assert result is False


class TestCommitAllChanges:
    """Test commit_all_changes function."""
    
    @patch('pokepoke.git_operations.subprocess.run')
    def test_successful_commit(self, mock_run: Mock) -> None:
        """Test successful commit."""
        mock_run.return_value = Mock(returncode=0, stderr="")
        
        success, error_msg = commit_all_changes("Test commit")
        
        assert success is True
        assert error_msg == ""
        assert mock_run.call_count == 2
    
    @patch('pokepoke.git_operations.subprocess.run')
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






class TestRunMaintenanceAgent:
    """Test run_maintenance_agent function."""
    
    @patch('pokepoke.agent_runner._run_beads_only_agent')
    @patch('pathlib.Path.read_text')
    @patch('pathlib.Path.exists')
    @patch('pathlib.Path.cwd')
    def test_beads_only_agent(
        self, 
        mock_cwd: Mock, 
        mock_exists: Mock, 
        mock_read: Mock, 
        mock_run_beads: Mock
    ) -> None:
        """Test running beads-only maintenance agent."""
        mock_cwd.return_value = Path("/fake/repo")
        mock_exists.return_value = True
        mock_read.return_value = "Agent instructions"
        mock_run_beads.return_value = AgentStats(
            wall_duration=10.0,
            api_duration=5.0,
            input_tokens=100,
            output_tokens=50,
            lines_added=0,
            lines_removed=0,
            premium_requests=1
        )
        
        stats = run_maintenance_agent(
            "TestAgent", 
            "test.md", 
            needs_worktree=False
        )
        
        assert stats is not None
        assert stats.wall_duration == 10.0
        mock_run_beads.assert_called_once()
    
    @patch('pokepoke.agent_runner._run_worktree_agent')
    @patch('pathlib.Path.read_text')
    @patch('pathlib.Path.exists')
    @patch('pathlib.Path.cwd')
    def test_worktree_agent(
        self, 
        mock_cwd: Mock, 
        mock_exists: Mock, 
        mock_read: Mock, 
        mock_run_wt: Mock
    ) -> None:
        """Test running worktree maintenance agent."""
        mock_cwd.return_value = Path("/fake/repo")
        mock_exists.return_value = True
        mock_read.return_value = "Agent instructions"
        mock_run_wt.return_value = AgentStats(
            wall_duration=20.0,
            api_duration=10.0,
            input_tokens=200,
            output_tokens=100,
            lines_added=10,
            lines_removed=5,
            premium_requests=2
        )
        
        stats = run_maintenance_agent(
            "TestAgent", 
            "test.md", 
            needs_worktree=True
        )
        
        assert stats is not None
        assert stats.wall_duration == 20.0
        mock_run_wt.assert_called_once()
    
    @patch('pathlib.Path.exists')
    @patch('pathlib.Path.cwd')
    def test_missing_prompt_file(self, mock_cwd: Mock, mock_exists: Mock) -> None:
        """Test maintenance agent with missing prompt file."""
        mock_cwd.return_value = Path("/fake/repo")
        mock_exists.return_value = False
        
        stats = run_maintenance_agent("TestAgent", "missing.md")
        
        assert stats is None


class TestRunBeadsOnlyAgent:
    """Test _run_beads_only_agent function."""
    
    @patch('pokepoke.agent_runner.parse_agent_stats')
    @patch('pokepoke.agent_runner.invoke_copilot')
    def test_successful_beads_agent(
        self, 
        mock_invoke: Mock, 
        mock_parse: Mock
    ) -> None:
        """Test successful beads-only agent."""
        agent_item = BeadsWorkItem(
            id="maintenance-test",
            title="Test Maintenance",
            description="Test",
            status="in_progress",
            priority=0,
            issue_type="task",
            labels=["maintenance"]
        )
        
        mock_invoke.return_value = CopilotResult(
            work_item_id="maintenance-test",
            success=True,
            output="Completed",
            attempt_count=1
        )
        mock_parse.return_value = AgentStats(
            wall_duration=10.0,
            api_duration=5.0,
            input_tokens=100,
            output_tokens=50,
            lines_added=0,
            lines_removed=0,
            premium_requests=1
        )
        
        stats = _run_beads_only_agent("Test", agent_item, "Test prompt")
        
        assert stats is not None
        mock_invoke.assert_called_once_with(
            agent_item, 
            prompt="Test prompt", 
            deny_write=True
        )
    
    @patch('pokepoke.agent_runner.invoke_copilot')
    def test_failed_beads_agent(self, mock_invoke: Mock) -> None:
        """Test failed beads-only agent."""
        agent_item = BeadsWorkItem(
            id="maintenance-test",
            title="Test Maintenance",
            description="Test",
            status="in_progress",
            priority=0,
            issue_type="task",
            labels=["maintenance"]
        )
        
        mock_invoke.return_value = CopilotResult(
            work_item_id="maintenance-test",
            success=False,
            output="",
            error="Agent failed",
            attempt_count=1
        )
        
        stats = _run_beads_only_agent("Test", agent_item, "Test prompt")
        
        assert stats is None


class TestRunWorktreeAgent:
    """Test _run_worktree_agent function."""
    
    @patch('pokepoke.git_operations.check_main_repo_ready_for_merge')  # Patch at module level
    @patch('pokepoke.agent_runner.cleanup_worktree')
    @patch('pokepoke.agent_runner.merge_worktree')
    @patch('pokepoke.agent_runner.parse_agent_stats')
    @patch('pokepoke.agent_runner.run_cleanup_loop')
    @patch('os.chdir')
    @patch('os.getcwd')
    @patch('pokepoke.agent_runner.invoke_copilot')
    @patch('pokepoke.agent_runner.create_worktree')
    def test_successful_worktree_agent(
        self,
        mock_create: Mock,
        mock_invoke: Mock,
        mock_getcwd: Mock,
        mock_chdir: Mock,
        mock_cleanup_loop: Mock,
        mock_parse: Mock,
        mock_merge: Mock,
        mock_cleanup: Mock,
        mock_check_ready: Mock
    ) -> None:
        """Test successful worktree agent."""
        agent_item = BeadsWorkItem(
            id="maintenance-test",
            title="Test Maintenance",
            description="Test",
            status="in_progress",
            priority=0,
            issue_type="task",
            labels=["maintenance"]
        )
        
        mock_create.return_value = Path("/fake/worktree")
        mock_getcwd.return_value = "/original"
        mock_invoke.return_value = CopilotResult(
            work_item_id="maintenance-test",
            success=True,
            output="Completed",
            attempt_count=1
        )
        mock_cleanup_loop.return_value = (True, 0)
        mock_parse.return_value = AgentStats(
            wall_duration=10.0,
            api_duration=5.0,
            input_tokens=100,
            output_tokens=50,
            lines_added=10,
            lines_removed=5,
            premium_requests=1
        )
        mock_check_ready.return_value = (True, "")
        mock_merge.return_value = True
        
        stats = _run_worktree_agent(
            "Test", 
            "maintenance-test", 
            agent_item, 
            "Test prompt",
            Path("/fake/repo")
        )
        
        assert stats is not None
        mock_create.assert_called_once()
        mock_merge.assert_called_once_with("maintenance-test", cleanup=True)
        mock_cleanup.assert_not_called()
    
    @patch('pokepoke.agent_runner.create_worktree')
    def test_worktree_creation_failure(self, mock_create: Mock) -> None:
        """Test worktree agent when worktree creation fails."""
        agent_item = BeadsWorkItem(
            id="maintenance-test",
            title="Test Maintenance",
            description="Test",
            status="in_progress",
            priority=0,
            issue_type="task",
            labels=["maintenance"]
        )
        
        mock_create.side_effect = Exception("Failed to create worktree")
        
        stats = _run_worktree_agent(
            "Test",
            "maintenance-test",
            agent_item,
            "Test prompt",
            Path("/fake/repo")
        )
        
        assert stats is None
    
    @patch('pokepoke.agent_runner.cleanup_worktree')
    @patch('os.chdir')
    @patch('os.getcwd')
    @patch('pokepoke.agent_runner.run_cleanup_loop')
    @patch('pokepoke.agent_runner.invoke_copilot')
    @patch('pokepoke.agent_runner.create_worktree')
    def test_worktree_agent_failure(
        self,
        mock_create: Mock,
        mock_invoke: Mock,
        mock_cleanup_loop: Mock,
        mock_getcwd: Mock,
        mock_chdir: Mock,
        mock_cleanup: Mock
    ) -> None:
        """Test worktree agent when agent fails."""
        agent_item = BeadsWorkItem(
            id="maintenance-test",
            title="Test Maintenance",
            description="Test",
            status="in_progress",
            priority=0,
            issue_type="task",
            labels=["maintenance"]
        )
        
        mock_create.return_value = Path("/fake/worktree")
        mock_getcwd.return_value = "/original"
        mock_invoke.return_value = CopilotResult(
            work_item_id="maintenance-test",
            success=False,
            output="",
            error="Agent failed",
            attempt_count=1
        )
        mock_cleanup_loop.return_value = (True, 0)
        
        stats = _run_worktree_agent(
            "Test",
            "maintenance-test",
            agent_item,
            "Test prompt",
            Path("/fake/repo")
        )
        
        assert stats is None

    @patch('pokepoke.agent_runner.invoke_merge_conflict_cleanup_agent')
    @patch('pokepoke.agent_runner.cleanup_worktree')
    @patch('pokepoke.agent_runner.merge_worktree')
    @patch('pokepoke.git_operations.check_main_repo_ready_for_merge')
    @patch('os.chdir')
    @patch('os.getcwd')
    @patch('pokepoke.agent_runner.run_cleanup_loop')
    @patch('pokepoke.agent_runner.invoke_copilot')
    @patch('pokepoke.agent_runner.create_worktree')
    def test_worktree_merge_failure(
        self,
        mock_create: Mock,
        mock_invoke: Mock,
        mock_cleanup_loop: Mock,
        mock_getcwd: Mock,
        mock_chdir: Mock,
        mock_check_ready: Mock,
        mock_merge: Mock,
        mock_cleanup: Mock,
        mock_invoke_merge_cleanup: Mock
    ) -> None:
        """Test worktree agent when merge fails."""
        agent_item = BeadsWorkItem(
            id="maintenance-test",
            title="Test Maintenance",
            description="Test",
            status="in_progress",
            priority=0,
            issue_type="task",
            labels=["maintenance"]
        )
        
        mock_create.return_value = Path("/fake/worktree")
        mock_getcwd.return_value = "/original"
        # Mock successful agent run
        mock_invoke.return_value = CopilotResult(
            work_item_id="maintenance-test",
            success=True,
            output='{"wall_duration": 10.0, "input_tokens": 100, "output_tokens": 50}',
            error="",
            attempt_count=1
        )
        mock_cleanup_loop.return_value = (True, 0)
        
        # Repo ready, but merge fails
        mock_check_ready.return_value = (True, "")
        mock_merge.return_value = False
        
        # Cleanup fails too
        mock_invoke_merge_cleanup.return_value = (False, None)
        
        stats = _run_worktree_agent(
            "Test",
            "maintenance-test",
            agent_item,
            "Test prompt",
            Path("/fake/repo")
        )
        
        assert stats is None
        # Verify cleanup invoked
        mock_invoke_merge_cleanup.assert_called_once()
        mock_cleanup.assert_not_called()


class TestRunBetaTester:
    """Test run_beta_tester function."""
    
    @patch('pokepoke.agent_runner.parse_agent_stats')
    @patch('pokepoke.agent_runner.get_pokepoke_prompts_dir')
    @patch('pokepoke.agent_runner.invoke_copilot')
    @patch('subprocess.run')
    @patch('pathlib.Path.exists')
    @patch('pathlib.Path.read_text')
    def test_beta_tester_success(
        self,
        mock_read: Mock,
        mock_exists: Mock,
        mock_run: Mock,
        mock_invoke: Mock,
        mock_get_prompts: Mock,
        mock_parse: Mock
    ) -> None:
        """Test successful beta tester run."""
        mock_exists.return_value = True
        mock_read.return_value = "Beta test prompt"
        mock_run.return_value = Mock(returncode=0)
        
        mock_invoke.return_value = CopilotResult(
            work_item_id="beta-tester",
            success=True,
            output='{"wall_duration": 10.0, "input_tokens": 100, "output_tokens": 50}',
            attempt_count=1
        )
        
        mock_parse.return_value = AgentStats(
            wall_duration=10.0,
            api_duration=5.0,
            input_tokens=100,
            output_tokens=50,
            lines_added=10,
            lines_removed=5,
            premium_requests=1
        )
        
        # Mock prompts dir
        mock_dir = MagicMock()
        mock_get_prompts.return_value = mock_dir
        mock_file = Mock()
        mock_file.exists.return_value = True
        mock_file.read_text.return_value = "Beta test prompt"
        mock_dir.__truediv__.return_value = mock_file
        
        from pokepoke.agent_runner import run_beta_tester
        stats = run_beta_tester()
        
        assert stats is not None
        assert stats.wall_duration == 10.0
        mock_invoke.assert_called_once()
        mock_run.assert_called()  # Restart script

    @patch('pokepoke.agent_runner.parse_agent_stats')
    @patch('pokepoke.agent_runner.get_pokepoke_prompts_dir')
    @patch('pokepoke.agent_runner.invoke_copilot')
    @patch('subprocess.run')
    @patch('pathlib.Path.exists')
    @patch('pathlib.Path.read_text')
    def test_beta_tester_restart_missing_keeps_going(
        self, 
        mock_read: Mock, 
        mock_exists: Mock, 
        mock_run: Mock, 
        mock_invoke: Mock, 
        mock_get_prompts: Mock,
        mock_parse: Mock
    ) -> None:
        """Test restart script missing but proceeds."""
        # restart_script.exists() -> False
        # prompt_path.exists() -> True
        mock_exists.side_effect = [False, True]
        mock_read.return_value = "prompt"
        
        mock_invoke.return_value = CopilotResult(
            work_item_id="beta", success=True, output="{}", attempt_count=1
        )
        
        mock_parse.return_value = AgentStats(
            wall_duration=10.0,
            api_duration=5.0,
            input_tokens=100,
            output_tokens=50,
            lines_added=10,
            lines_removed=5,
            premium_requests=1
        )
        
        mock_dir = MagicMock()
        mock_get_prompts.return_value = mock_dir
        mock_file = Mock()
        mock_file.exists.return_value = True
        mock_file.read_text.return_value = "prompt"
        mock_dir.__truediv__.return_value = mock_file
        
        from pokepoke.agent_runner import run_beta_tester
        stats = run_beta_tester()
        
        assert stats is not None # It proceeded!
        mock_run.assert_not_called() # Did not run restart

    @patch('pokepoke.agent_runner.get_pokepoke_prompts_dir')
    @patch('subprocess.run')
    @patch('pathlib.Path.exists')
    def test_beta_tester_prompt_missing(
        self, 
        mock_exists: Mock, 
        mock_run: Mock, 
        mock_get_prompts: Mock
    ) -> None:
        """Test prompt file missing returns None."""
        # restart_script.exists() -> True
        # prompt_path.exists() -> False
        mock_exists.side_effect = [True, False]
        mock_run.return_value = Mock(returncode=0)
        
        mock_dir = MagicMock()
        mock_get_prompts.return_value = mock_dir
        mock_file = Mock()
        mock_file.exists.return_value = False # Explicitly false here too
        mock_dir.__truediv__.return_value = mock_file
        
        from pokepoke.agent_runner import run_beta_tester
        stats = run_beta_tester()
        assert stats is None

    @patch('pokepoke.agent_runner.get_pokepoke_prompts_dir')
    @patch('pokepoke.agent_runner.invoke_copilot')
    @patch('subprocess.run')
    @patch('pathlib.Path.exists')
    @patch('pathlib.Path.read_text')
    def test_beta_tester_invoke_failure(
        self, 
        mock_read: Mock, 
        mock_exists: Mock, 
        mock_run: Mock, 
        mock_invoke: Mock,
        mock_get_prompts: Mock
    ) -> None:
        """Test failure in invoke_copilot returns None."""
        mock_exists.return_value = True
        mock_run.return_value = Mock(returncode=0)
        mock_read.return_value = "prompt"
        
        mock_dir = MagicMock()
        mock_get_prompts.return_value = mock_dir
        mock_file = Mock()
        mock_file.exists.return_value = True
        mock_file.read_text.return_value = "prompt"
        mock_dir.__truediv__.return_value = mock_file
        
        mock_invoke.return_value = CopilotResult(
            work_item_id="beta", success=False, output=None, attempt_count=1, error="Failed"
        )
        
        from pokepoke.agent_runner import run_beta_tester
        stats = run_beta_tester()
        assert stats is None

