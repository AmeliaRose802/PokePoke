"""Tests for cleanup agents."""

import os
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch

import pytest
from pokepoke.cleanup_agents import (
    get_pokepoke_prompts_dir,
    _get_current_git_context,
    invoke_cleanup_agent,
    invoke_merge_conflict_cleanup_agent,
    aggregate_cleanup_stats,
    run_cleanup_loop
)
from pokepoke.types import BeadsWorkItem, CopilotResult, AgentStats


class TestCleanupAgents:
    """Test cleanup agent functions."""

    @patch('pathlib.Path.exists')
    @patch('pathlib.Path.parent', new_callable=Mock)
    def test_get_prompts_dir(self, mock_parent, mock_exists):
        """Test finding prompts directory."""
        mock_exists.return_value = True
        
        with patch('pokepoke.cleanup_agents.Path') as mock_path:
             mock_path.return_value.parent.parent.parent = Path('/root')
             result = get_pokepoke_prompts_dir()
             # Logic is Path(__file__).parent.parent.parent / ".pokepoke" / "prompts"
             # Since it returns a path, validation passes if no exception

    def test_get_prompts_dir_not_found(self):
        """Test error when prompts directory not found."""
        with patch('pokepoke.cleanup_agents.Path') as mock_path:
             # Make exists return False
             mock_dir = Mock()
             mock_dir.exists.return_value = False
             mock_path.return_value.parent.parent.parent.__truediv__.return_value.__truediv__.return_value = mock_dir
             
             with pytest.raises(FileNotFoundError):
                 get_pokepoke_prompts_dir()

    @patch('subprocess.run')
    @patch('os.getcwd')
    def test_get_current_git_context(self, mock_getcwd, mock_run):
        """Test getting git context."""
        mock_getcwd.return_value = "/test/dir"
        
        # Mock branch
        mock_branch = Mock()
        mock_branch.returncode = 0
        mock_branch.stdout = "main"
        
        # Mock worktree
        mock_worktree = Mock()
        mock_worktree.returncode = 0
        mock_worktree.stdout = "true"
        
        mock_run.side_effect = [mock_branch, mock_worktree]
        
        cwd, branch, is_worktree = _get_current_git_context()
        
        assert cwd == "/test/dir"
        assert branch == "main"
        assert is_worktree is True

    @patch('subprocess.run')
    def test_get_current_git_context_failure(self, mock_run):
        """Test getting git context when commands fail."""
        mock_run.side_effect = Exception("Git error")
        
        cwd, branch, is_worktree = _get_current_git_context()
        
        assert branch == "unknown"
        assert is_worktree is False

    @patch('pokepoke.cleanup_agents.get_pokepoke_prompts_dir')
    @patch('pokepoke.cleanup_agents._get_current_git_context')
    @patch('pokepoke.cleanup_agents.invoke_copilot')
    def test_invoke_cleanup_agent(self, mock_invoke, mock_context, mock_get_dir):
        """Test invoking cleanup agent."""
        mock_dir = MagicMock()
        mock_file = Mock()
        mock_file.exists.return_value = True
        mock_file.read_text.return_value = "Instructions {cwd} {branch} {is_worktree}"
        mock_dir.__truediv__.return_value = mock_file
        mock_get_dir.return_value = mock_dir
        
        mock_context.return_value = ("/cur/dir", "feature", True)
        
        mock_invoke.return_value = CopilotResult(
            work_item_id="task-1",
            success=True,
            output="Done",
            attempt_count=1
        )
        
        item = BeadsWorkItem(
            id="123",
            title="Test",
            description="Desc",
            issue_type="task",
            priority=1,
            status="in_progress",
            labels=["test"]
        )
        
        success, stats = invoke_cleanup_agent(item, Path("/repo"))
        
        assert success is True
        mock_invoke.assert_called_once()
        args = mock_invoke.call_args
        prompt = args[1]['prompt']
        assert "/cur/dir" in prompt
        assert "feature" in prompt
        assert "True" in prompt

    @patch('pokepoke.cleanup_agents.get_pokepoke_prompts_dir')
    def test_invoke_cleanup_agent_no_prompt(self, mock_get_dir):
        """Test invoking cleanup agent failing due to missing prompt."""
        mock_get_dir.side_effect = FileNotFoundError("Not found")
        
        item = BeadsWorkItem(id="1", title="T", description="D", status="open", priority=1, issue_type="task")
        success, stats = invoke_cleanup_agent(item, Path("/repo"))
        
        assert success is False
        assert stats is None

    @patch('pokepoke.cleanup_agents.get_pokepoke_prompts_dir')
    @patch('pokepoke.cleanup_agents._get_current_git_context')
    @patch('pokepoke.cleanup_agents.invoke_copilot')
    def test_invoke_merge_conflict_cleanup_agent(self, mock_invoke, mock_context, mock_get_dir):
        """Test invoking merge conflict cleanup agent."""
        mock_dir = MagicMock()
        mock_file = Mock()
        mock_file.exists.return_value = True
        mock_file.read_text.return_value = "Merge fix {merge_error}"
        mock_dir.__truediv__.return_value = mock_file
        mock_get_dir.return_value = mock_dir
        
        mock_context.return_value = ("/cur/dir", "feature", True)
        
        mock_invoke.return_value = CopilotResult(
            work_item_id="task-1",
            success=True,
            output="Fixed",
            attempt_count=1
        )
        
        item = BeadsWorkItem(
            id="123", 
            title="Test", 
            description="Desc",
            issue_type="task",
            priority=1,
            status="in_progress"
        )
        
        success, stats = invoke_merge_conflict_cleanup_agent(item, Path("/repo"), "Merge error")
        
        assert success is True
        mock_invoke.assert_called_once()
        args = mock_invoke.call_args
        prompt = args[1]['prompt']
        assert "Merge error" in prompt

    @patch('pokepoke.cleanup_agents.get_pokepoke_prompts_dir')
    @patch('pokepoke.cleanup_agents.invoke_cleanup_agent')
    def test_invoke_merge_conflict_fallback(self, mock_invoke_cleanup, mock_get_dir):
        """Test fallback to standard cleanup if merge prompt missing."""
        mock_dir = MagicMock()
        mock_file = Mock()
        mock_file.exists.return_value = False
        mock_dir.__truediv__.return_value = mock_file
        mock_get_dir.return_value = mock_dir
        
        mock_invoke_cleanup.return_value = (True, None)
        
        item = BeadsWorkItem(id="1", title="T", description="D", status="open", priority=1, issue_type="task")
        success, stats = invoke_merge_conflict_cleanup_agent(item, Path("/repo"), "Error")
        
        assert success is True
        mock_invoke_cleanup.assert_called_once()


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
    
    @patch('pokepoke.cleanup_agents.invoke_cleanup_agent')
    @patch('pokepoke.cleanup_agents.commit_all_changes')
    @patch('pokepoke.cleanup_agents.verify_main_repo_clean')
    def test_no_uncommitted_changes(
        self, 
        mock_verify: Mock, 
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
        
        # is_clean=True, no uncommitted output, no non-beads changes
        mock_verify.return_value = (True, "", [])
        
        success, cleanup_runs = run_cleanup_loop(item, result, repo_root)
        
        assert success is True
        assert cleanup_runs == 0
        mock_commit.assert_not_called()
        mock_invoke.assert_not_called()
    
    @patch('pokepoke.cleanup_agents.invoke_cleanup_agent')
    @patch('pokepoke.cleanup_agents.commit_all_changes')
    @patch('pokepoke.cleanup_agents.verify_main_repo_clean')
    def test_successful_commit_first_try(
        self, 
        mock_verify: Mock, 
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
        
        # is_clean=False (has non-beads changes), then True after commit
        mock_verify.return_value = (False, " M file.py\n", [" M file.py"])
        mock_commit.return_value = (True, "")
        
        success, cleanup_runs = run_cleanup_loop(item, result, repo_root)
        
        assert success is True
        assert cleanup_runs == 0
        mock_commit.assert_called_once()
        mock_invoke.assert_not_called()
    
    @patch('pokepoke.cleanup_agents.invoke_cleanup_agent')
    @patch('pokepoke.cleanup_agents.commit_all_changes')
    @patch('pokepoke.cleanup_agents.verify_main_repo_clean')
    def test_commit_fails_cleanup_succeeds(
        self, 
        mock_verify: Mock, 
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
        
        # First call: has non-beads changes, second call: clean after cleanup
        mock_verify.side_effect = [
            (False, " M file.py\n", [" M file.py"]),  # Initial state
            (True, "", [])  # After cleanup
        ]
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
    
    @patch('pokepoke.cleanup_agents.invoke_cleanup_agent')
    @patch('pokepoke.cleanup_agents.commit_all_changes')
    @patch('pokepoke.cleanup_agents.verify_main_repo_clean')
    def test_cleanup_agent_fails(
        self, 
        mock_verify: Mock, 
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
        
        # is_clean=False (has non-beads changes)
        mock_verify.return_value = (False, " M file.py\n", [" M file.py"])
        mock_commit.return_value = (False, "Tests failed")
        mock_invoke.return_value = (False, None)
        
        success, cleanup_runs = run_cleanup_loop(item, result, repo_root)
        
        assert success is False
        assert cleanup_runs == 1
        assert result.success is False
        assert "Cleanup agent failed" in result.error
