"""Unit tests for agent_runner module."""

import subprocess
from pathlib import Path
from unittest.mock import Mock, patch, call, mock_open
import pytest

from src.pokepoke.agent_runner import (
    has_uncommitted_changes,
    commit_all_changes,
    invoke_cleanup_agent,
    aggregate_cleanup_stats,
    run_cleanup_loop,
    run_maintenance_agent,
    _run_beads_only_agent,
    _run_worktree_agent
)
from src.pokepoke.types import BeadsWorkItem, AgentStats, CopilotResult


class TestHasUncommittedChanges:
    """Test has_uncommitted_changes function."""
    
    @patch('src.pokepoke.agent_runner.subprocess.run')
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
            check=True
        )
    
    @patch('src.pokepoke.agent_runner.subprocess.run')
    def test_has_changes(self, mock_run: Mock) -> None:
        """Test repository with uncommitted changes."""
        mock_run.return_value = Mock(
            stdout=" M src/file.py",
            returncode=0
        )
        
        result = has_uncommitted_changes()
        
        assert result is True
    
    @patch('src.pokepoke.agent_runner.subprocess.run')
    def test_git_error(self, mock_run: Mock) -> None:
        """Test error handling when git command fails."""
        mock_run.side_effect = subprocess.CalledProcessError(1, "git status")
        
        result = has_uncommitted_changes()
        
        assert result is False


class TestCommitAllChanges:
    """Test commit_all_changes function."""
    
    @patch('src.pokepoke.agent_runner.subprocess.run')
    def test_successful_commit(self, mock_run: Mock) -> None:
        """Test successful commit."""
        mock_run.return_value = Mock(returncode=0, stderr="")
        
        success, error_msg = commit_all_changes("Test commit")
        
        assert success is True
        assert error_msg == ""
        assert mock_run.call_count == 2
    
    @patch('src.pokepoke.agent_runner.subprocess.run')
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


class TestInvokeCleanupAgent:
    """Test invoke_cleanup_agent function."""
    
    @patch('src.pokepoke.agent_runner.invoke_copilot_cli')
    @patch('pathlib.Path.read_text')
    @patch('pathlib.Path.exists')
    def test_successful_cleanup(
        self, 
        mock_exists: Mock, 
        mock_read: Mock, 
        mock_invoke: Mock
    ) -> None:
        """Test successful cleanup agent invocation."""
        item = BeadsWorkItem(
            id="task-1",
            title="Test Task",
            description="Test description",
            status="in_progress",
            priority=1,
            issue_type="task",
            labels=["test"]
        )
        repo_root = Path("/fake/repo")
        
        mock_exists.return_value = True
        mock_read.return_value = "Cleanup instructions"
        mock_invoke.return_value = CopilotResult(
            work_item_id="task-1-cleanup",
            success=True,
            output="Cleanup completed",
            attempt_count=1,
            stats=AgentStats(
                wall_duration=10.0,
                api_duration=5.0,
                input_tokens=100,
                output_tokens=50,
                lines_added=10,
                lines_removed=5,
                premium_requests=1
            )
        )
        
        success, stats = invoke_cleanup_agent(item, repo_root)
        
        assert success is True
        assert stats is not None
        assert stats.wall_duration == 10.0
        assert stats.input_tokens == 100
        mock_invoke.assert_called_once()
        
        # Verify cleanup item was created with correct properties
        call_args = mock_invoke.call_args
        cleanup_item = call_args[0][0]
        assert cleanup_item.id == "task-1-cleanup"
        assert "cleanup" in cleanup_item.labels
        assert "automated" in cleanup_item.labels
    
    @patch('pathlib.Path.exists')
    def test_missing_cleanup_prompt(self, mock_exists: Mock) -> None:
        """Test cleanup when prompt file is missing."""
        item = BeadsWorkItem(
            id="task-1",
            title="Test Task",
            description="",
            status="in_progress",
            priority=1,
            issue_type="task"
        )
        repo_root = Path("/fake/repo")
        
        mock_exists.return_value = False
        
        success, stats = invoke_cleanup_agent(item, repo_root)
        
        assert success is False
        assert stats is None
    
    @patch('src.pokepoke.agent_runner.invoke_copilot_cli')
    @patch('pathlib.Path.read_text')
    @patch('pathlib.Path.exists')
    def test_cleanup_failure(
        self, 
        mock_exists: Mock, 
        mock_read: Mock, 
        mock_invoke: Mock
    ) -> None:
        """Test cleanup agent failure."""
        item = BeadsWorkItem(
            id="task-1",
            title="Test Task",
            description="",
            status="in_progress",
            priority=1,
            issue_type="task"
        )
        repo_root = Path("/fake/repo")
        
        mock_exists.return_value = True
        mock_read.return_value = "Cleanup instructions"
        mock_invoke.return_value = CopilotResult(
            work_item_id="task-1-cleanup",
            success=False,
            output="",
            error="Cleanup failed",
            attempt_count=1
        )
        
        success, stats = invoke_cleanup_agent(item, repo_root)
        
        assert success is False
        assert stats is None
    
    @patch('src.pokepoke.agent_runner.invoke_copilot_cli')
    @patch('pathlib.Path.read_text')
    @patch('pathlib.Path.exists')
    def test_cleanup_with_labels(
        self, 
        mock_exists: Mock, 
        mock_read: Mock, 
        mock_invoke: Mock
    ) -> None:
        """Test cleanup includes work item labels in context."""
        item = BeadsWorkItem(
            id="task-1",
            title="Test Task",
            description="Test description",
            status="in_progress",
            priority=1,
            issue_type="task",
            labels=["backend", "api"]
        )
        repo_root = Path("/fake/repo")
        
        mock_exists.return_value = True
        mock_read.return_value = "Cleanup instructions"
        mock_invoke.return_value = CopilotResult(
            work_item_id="task-1-cleanup",
            success=True,
            output="",
            attempt_count=1
        )
        
        invoke_cleanup_agent(item, repo_root)
        
        # Verify prompt includes labels
        call_args = mock_invoke.call_args
        prompt = call_args[1]['prompt']
        assert "backend" in prompt
        assert "api" in prompt


class TestAggregateCleanupStats:
    """Test aggregate_cleanup_stats function."""
    
    def test_aggregate_with_both_stats(self) -> None:
        """Test aggregating cleanup stats into result stats."""
        result_stats = AgentStats(
            wall_duration=10.0,
            api_duration=5.0,
            input_tokens=100,
            output_tokens=50,
            lines_added=10,
            lines_removed=5,
            premium_requests=1
        )
        cleanup_stats = AgentStats(
            wall_duration=5.0,
            api_duration=2.0,
            input_tokens=50,
            output_tokens=25,
            lines_added=5,
            lines_removed=2,
            premium_requests=1
        )
        
        aggregate_cleanup_stats(result_stats, cleanup_stats)
        
        assert result_stats.wall_duration == 15.0
        assert result_stats.api_duration == 7.0
        assert result_stats.input_tokens == 150
        assert result_stats.output_tokens == 75
        assert result_stats.lines_added == 15
        assert result_stats.lines_removed == 7
        assert result_stats.premium_requests == 2
    
    def test_aggregate_with_none_cleanup_stats(self) -> None:
        """Test aggregating when cleanup stats is None."""
        result_stats = AgentStats(
            wall_duration=10.0,
            api_duration=5.0,
            input_tokens=100,
            output_tokens=50,
            lines_added=10,
            lines_removed=5,
            premium_requests=1
        )
        
        aggregate_cleanup_stats(result_stats, None)
        
        # Should remain unchanged
        assert result_stats.wall_duration == 10.0
        assert result_stats.input_tokens == 100
    
    def test_aggregate_with_none_result_stats(self) -> None:
        """Test aggregating when result stats is None."""
        cleanup_stats = AgentStats(
            wall_duration=5.0,
            api_duration=2.0,
            input_tokens=50,
            output_tokens=25,
            lines_added=5,
            lines_removed=2,
            premium_requests=1
        )
        
        # Should not raise exception
        aggregate_cleanup_stats(None, cleanup_stats)


class TestRunCleanupLoop:
    """Test run_cleanup_loop function."""
    
    @patch('src.pokepoke.agent_runner.invoke_cleanup_agent')
    @patch('src.pokepoke.agent_runner.commit_all_changes')
    @patch('src.pokepoke.agent_runner.has_uncommitted_changes')
    def test_no_uncommitted_changes(
        self, 
        mock_uncommitted: Mock, 
        mock_commit: Mock, 
        mock_invoke: Mock
    ) -> None:
        """Test cleanup loop when no uncommitted changes."""
        item = BeadsWorkItem(
            id="task-1",
            title="Test",
            description="",
            status="in_progress",
            priority=1,
            issue_type="task"
        )
        result = CopilotResult(
            work_item_id="task-1",
            success=True,
            output="",
            attempt_count=1
        )
        repo_root = Path("/fake/repo")
        
        mock_uncommitted.return_value = False
        
        success, cleanup_runs = run_cleanup_loop(item, result, repo_root)
        
        assert success is True
        assert cleanup_runs == 0
        mock_commit.assert_not_called()
        mock_invoke.assert_not_called()
    
    @patch('src.pokepoke.agent_runner.invoke_cleanup_agent')
    @patch('src.pokepoke.agent_runner.commit_all_changes')
    @patch('src.pokepoke.agent_runner.has_uncommitted_changes')
    def test_successful_commit_first_try(
        self, 
        mock_uncommitted: Mock, 
        mock_commit: Mock, 
        mock_invoke: Mock
    ) -> None:
        """Test cleanup loop with successful commit on first try."""
        item = BeadsWorkItem(
            id="task-1",
            title="Test",
            description="",
            status="in_progress",
            priority=1,
            issue_type="task"
        )
        result = CopilotResult(
            work_item_id="task-1",
            success=True,
            output="",
            attempt_count=1
        )
        repo_root = Path("/fake/repo")
        
        mock_uncommitted.return_value = True
        mock_commit.return_value = (True, "")
        
        success, cleanup_runs = run_cleanup_loop(item, result, repo_root)
        
        assert success is True
        assert cleanup_runs == 0
        mock_commit.assert_called_once()
        mock_invoke.assert_not_called()
    
    @patch('src.pokepoke.agent_runner.invoke_cleanup_agent')
    @patch('src.pokepoke.agent_runner.commit_all_changes')
    @patch('src.pokepoke.agent_runner.has_uncommitted_changes')
    def test_commit_fails_cleanup_succeeds(
        self, 
        mock_uncommitted: Mock, 
        mock_commit: Mock, 
        mock_invoke: Mock
    ) -> None:
        """Test cleanup loop with commit failure then cleanup success."""
        item = BeadsWorkItem(
            id="task-1",
            title="Test",
            description="",
            status="in_progress",
            priority=1,
            issue_type="task"
        )
        result = CopilotResult(
            work_item_id="task-1",
            success=True,
            output="",
            attempt_count=1,
            stats=AgentStats(
                wall_duration=10.0,
                api_duration=5.0,
                input_tokens=100,
                output_tokens=50,
                lines_added=10,
                lines_removed=5,
                premium_requests=1
            )
        )
        repo_root = Path("/fake/repo")
        
        # First call: has changes, second call: no changes
        mock_uncommitted.side_effect = [True, False]
        mock_commit.return_value = (False, "Tests failed")
        mock_invoke.return_value = (
            True,
            AgentStats(
                wall_duration=5.0,
                api_duration=2.0,
                input_tokens=50,
                output_tokens=25,
                lines_added=5,
                lines_removed=2,
                premium_requests=1
            )
        )
        
        success, cleanup_runs = run_cleanup_loop(item, result, repo_root)
        
        assert success is True
        assert cleanup_runs == 1
        mock_commit.assert_called_once()
        mock_invoke.assert_called_once()
        # Stats should be aggregated
        assert result.stats.wall_duration == 15.0
    
    @patch('src.pokepoke.agent_runner.invoke_cleanup_agent')
    @patch('src.pokepoke.agent_runner.commit_all_changes')
    @patch('src.pokepoke.agent_runner.has_uncommitted_changes')
    def test_cleanup_agent_fails(
        self, 
        mock_uncommitted: Mock, 
        mock_commit: Mock, 
        mock_invoke: Mock
    ) -> None:
        """Test cleanup loop when cleanup agent fails."""
        item = BeadsWorkItem(
            id="task-1",
            title="Test",
            description="",
            status="in_progress",
            priority=1,
            issue_type="task"
        )
        result = CopilotResult(
            work_item_id="task-1",
            success=True,
            output="",
            attempt_count=1
        )
        repo_root = Path("/fake/repo")
        
        mock_uncommitted.return_value = True
        mock_commit.return_value = (False, "Tests failed")
        mock_invoke.return_value = (False, None)
        
        success, cleanup_runs = run_cleanup_loop(item, result, repo_root)
        
        assert success is False
        assert cleanup_runs == 1
        assert result.success is False
        assert "Cleanup agent failed" in result.error


class TestRunMaintenanceAgent:
    """Test run_maintenance_agent function."""
    
    @patch('src.pokepoke.agent_runner._run_beads_only_agent')
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
    
    @patch('src.pokepoke.agent_runner._run_worktree_agent')
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
    
    @patch('src.pokepoke.agent_runner.parse_agent_stats')
    @patch('src.pokepoke.agent_runner.invoke_copilot_cli')
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
    
    @patch('src.pokepoke.agent_runner.invoke_copilot_cli')
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
    @patch('src.pokepoke.agent_runner.cleanup_worktree')
    @patch('src.pokepoke.agent_runner.merge_worktree')
    @patch('src.pokepoke.agent_runner.parse_agent_stats')
    @patch('src.pokepoke.agent_runner.run_cleanup_loop')
    @patch('os.chdir')
    @patch('os.getcwd')
    @patch('src.pokepoke.agent_runner.invoke_copilot_cli')
    @patch('src.pokepoke.agent_runner.create_worktree')
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
    
    @patch('src.pokepoke.agent_runner.create_worktree')
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
    
    @patch('src.pokepoke.agent_runner.cleanup_worktree')
    @patch('os.chdir')
    @patch('os.getcwd')
    @patch('src.pokepoke.agent_runner.run_cleanup_loop')
    @patch('src.pokepoke.agent_runner.invoke_copilot_cli')
    @patch('src.pokepoke.agent_runner.create_worktree')
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
        mock_cleanup.assert_called_once_with("maintenance-test", force=True)
