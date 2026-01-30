"""Simple tests for agent runner to improve coverage."""
import os
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from pokepoke.agent_runner import _run_worktree_agent
from pokepoke.types import BeadsWorkItem, CopilotResult, AgentStats

class TestAgentRunnerSimple:
    
    @patch('pokepoke.agent_runner.create_worktree')
    @patch('pokepoke.agent_runner.invoke_copilot')
    @patch('pokepoke.agent_runner.cleanup_worktree')
    @patch('os.getcwd')
    @patch('os.chdir')
    def test_run_agent_exception(self, mock_chdir, mock_getcwd, mock_cleanup, mock_invoke, mock_create):
         """Test exception handling in run_agent."""
         mock_create.return_value = Path("/tmp/wt")
         mock_invoke.side_effect = Exception("Boom")
         
         item = BeadsWorkItem(id="1", title="T", description="D", status="open", priority=1, issue_type="task")
         
         res = _run_worktree_agent("Agent", "1", item, "Prompt", Path("/repo"))
         
         assert res is None
         mock_cleanup.assert_called()

    @patch('pokepoke.agent_runner.create_worktree')
    @patch('pokepoke.agent_runner.invoke_copilot')
    @patch('pokepoke.agent_runner.run_cleanup_loop')
    @patch('pokepoke.agent_runner.cleanup_worktree')
    @patch('pokepoke.agent_runner.merge_worktree')
    @patch('pokepoke.git_operations.check_main_repo_ready_for_merge')
    @patch('pokepoke.agent_runner.invoke_merge_conflict_cleanup_agent')
    @patch('pokepoke.agent_runner.parse_agent_stats')
    @patch('pokepoke.git_operations.is_merge_in_progress', return_value=False)
    @patch('pokepoke.git_operations.get_unmerged_files', return_value=[])
    @patch('pokepoke.git_operations.abort_merge', return_value=(True, ""))
    @patch('os.getcwd')
    @patch('os.chdir')
    def test_run_agent_merge_conflict(
        self, 
        mock_chdir, 
        mock_getcwd, 
        mock_abort,
        mock_get_unmerged,
        mock_is_merging,
        mock_parse_stats,
        mock_invoke_cleanup, 
        mock_check_ready,
        mock_merge, 
        mock_cleanup_wt, 
        mock_loop, 
        mock_invoke, 
        mock_create
    ):
         """Test merge conflict handling path."""
         mock_create.return_value = Path("/tmp/wt")
         mock_getcwd.return_value = "/repo"
         
         # 1. Agent runs successfully
         mock_invoke.return_value = CopilotResult(
             work_item_id="1", success=True, output='{"wall_duration": 1}', attempt_count=1
         )
         mock_parse_stats.return_value = AgentStats(wall_duration=1.0)
         
         # 2. Cleanup loop successful
         mock_loop.return_value = (True, 0)
         
         # 3. Main repo ready (first check)
         mock_check_ready.return_value = (True, "")
         
         # 4. Merge FAILS (simulating conflict) - now returns tuple
         # First call returns (False, ['file.py']), second returns (True, [])
         mock_merge.side_effect = [(False, ['file.py']), (True, [])]
         
         # 5. Invoke merge conflict cleanup agent
         # Should happen here. 
         # And assume it runs successfully
         mock_invoke_cleanup.return_value = (True, AgentStats(wall_duration=1))
         
         item = BeadsWorkItem(id="1", title="T", description="D", status="open", priority=1, issue_type="task")
         
         res = _run_worktree_agent("Agent", "1", item, "Prompt", Path("/repo"))
         
         assert res is not None
         mock_invoke_cleanup.assert_called_once()
         assert mock_merge.call_count == 2    
    @patch('pokepoke.agent_runner.create_worktree')
    @patch('pokepoke.agent_runner.invoke_copilot')
    @patch('pokepoke.agent_runner.run_cleanup_loop')
    @patch('pokepoke.agent_runner.cleanup_worktree')
    @patch('pokepoke.agent_runner.merge_worktree')
    @patch('pokepoke.git_operations.check_main_repo_ready_for_merge')
    @patch('pokepoke.agent_runner.invoke_merge_conflict_cleanup_agent')
    @patch('pokepoke.agent_runner.parse_agent_stats')
    @patch('pokepoke.git_operations.is_merge_in_progress')
    @patch('pokepoke.git_operations.get_unmerged_files')
    @patch('pokepoke.git_operations.abort_merge')
    @patch('os.getcwd')
    @patch('os.chdir')
    def test_run_agent_merge_conflict_cleanup_fails(
        self, 
        mock_chdir, 
        mock_getcwd, 
        mock_abort,
        mock_get_unmerged,
        mock_is_merging,
        mock_parse_stats,
        mock_invoke_cleanup, 
        mock_check_ready,
        mock_merge, 
        mock_cleanup_wt, 
        mock_loop, 
        mock_invoke, 
        mock_create
    ):
         """Test merge conflict handling when cleanup fails."""
         mock_create.return_value = Path("/tmp/wt")
         mock_getcwd.return_value = "/repo"
         
         # Agent runs successfully
         mock_invoke.return_value = CopilotResult(
             work_item_id="1", success=True, output='{"wall_duration": 1}', attempt_count=1
         )
         mock_parse_stats.return_value = AgentStats(wall_duration=1.0)
         mock_loop.return_value = (True, 0)
         mock_check_ready.return_value = (True, "")
         
         # Merge FAILS and cleanup also fails
         mock_merge.return_value = (False, ['file.py'])
         mock_invoke_cleanup.return_value = (False, None)
         mock_is_merging.return_value = True
         mock_abort.return_value = (True, "")
         
         item = BeadsWorkItem(id="1", title="T", description="D", status="open", priority=1, issue_type="task")
         
         res = _run_worktree_agent("Agent", "1", item, "Prompt", Path("/repo"))
         
         assert res is None  # Should fail
         mock_abort.assert_called_once()  # Should abort the merge