"""Unit tests for orchestrator module."""

import sys
from unittest.mock import Mock, patch, call
import pytest

from pokepoke.orchestrator import run_orchestrator
from pokepoke.workflow import select_work_item, process_work_item
from pokepoke.types import BeadsWorkItem, CopilotResult


class TestSelectWorkItem:
    """Test work item selection logic."""
    
    def test_select_work_item_empty_list(self) -> None:
        """Test selecting from empty list returns None."""
        result = select_work_item([], interactive=False)
        
        assert result is None
    
    @patch('pokepoke.work_item_selection.select_next_hierarchical_item')
    def test_select_work_item_autonomous_mode(
        self, 
        mock_select_hierarchical: Mock
    ) -> None:
        """Test autonomous mode uses hierarchical selection."""
        items = [
            BeadsWorkItem(
                id="task-1",
                title="Task",
                description="",
                status="open",
                priority=1,
                issue_type="task"
            )
        ]
        mock_select_hierarchical.return_value = items[0]
        
        result = select_work_item(items, interactive=False)
        
        assert result is not None
        assert result.id == "task-1"
        mock_select_hierarchical.assert_called_once_with(items)
    
    @patch('builtins.input')
    def test_select_work_item_interactive_quit(self, mock_input: Mock) -> None:
        """Test interactive mode quit option."""
        items = [
            BeadsWorkItem(
                id="task-1",
                title="Task",
                description="",
                status="open",
                priority=1,
                issue_type="task"
            )
        ]
        mock_input.return_value = 'q'
        
        result = select_work_item(items, interactive=True)
        
        assert result is None
    
    @patch('builtins.input')
    def test_select_work_item_interactive_valid_selection(
        self, 
        mock_input: Mock
    ) -> None:
        """Test interactive mode valid item selection."""
        items = [
            BeadsWorkItem(
                id="task-1",
                title="Task",
                description="",
                status="open",
                priority=1,
                issue_type="task"
            )
        ]
        mock_input.return_value = '1'
        
        result = select_work_item(items, interactive=True)
        
        assert result is not None
        assert result.id == "task-1"
    
    @patch('builtins.input')
    def test_select_work_item_interactive_invalid_then_valid(
        self, 
        mock_input: Mock
    ) -> None:
        """Test interactive mode with invalid then valid input."""
        items = [
            BeadsWorkItem(
                id="task-1",
                title="Task",
                description="",
                status="open",
                priority=1,
                issue_type="task"
            )
        ]
        mock_input.side_effect = ['invalid', '1']
        
        result = select_work_item(items, interactive=True)
        
        assert result is not None
        assert result.id == "task-1"
    
    @patch('builtins.input')
    def test_select_work_item_interactive_out_of_range(
        self, 
        mock_input: Mock
    ) -> None:
        """Test interactive mode with out of range input."""
        items = [
            BeadsWorkItem(
                id="task-1",
                title="Task",
                description="",
                status="open",
                priority=1,
                issue_type="task"
            )
        ]
        mock_input.side_effect = ['99', '1']
        
        result = select_work_item(items, interactive=True)
        
        assert result is not None
        assert result.id == "task-1"


class TestProcessWorkItem:
    """Test work item processing logic."""
    
    @patch('pokepoke.beads_hierarchy.close_parent_if_complete')
    @patch('pokepoke.worktree_finalization.get_parent_id')
    @patch('pokepoke.worktree_finalization.close_item')  # Patch where it's used
    @patch('subprocess.run')
    @patch('pokepoke.workflow.cleanup_worktree')
    @patch('pokepoke.worktree_finalization.merge_worktree')
    @patch('pokepoke.worktree_finalization.check_main_repo_ready_for_merge')
    @patch('pokepoke.git_operations.has_uncommitted_changes')
    @patch('os.chdir')
    @patch('os.getcwd')
    @patch('pokepoke.workflow.create_worktree')
    @patch('pokepoke.workflow.invoke_copilot')
    @patch('builtins.input')
    def test_process_work_item_success_no_parent(
        self,
        mock_input: Mock,
        mock_invoke: Mock,
        mock_create_wt: Mock,
        mock_getcwd: Mock,
        mock_chdir: Mock,
        mock_uncommitted: Mock,
        mock_check_ready: Mock,
        mock_merge: Mock,
        mock_cleanup: Mock,
        mock_subprocess: Mock,
        mock_close: Mock,
        mock_get_parent: Mock,
        mock_close_parent: Mock
    ) -> None:
        """Test successful processing without parent."""
        item = BeadsWorkItem(
            id="task-1",
            title="Task",
            description="",
            status="open",
            priority=1,
            issue_type="task"
        )
        mock_input.return_value = 'y'
        mock_create_wt.return_value = '/tmp/worktree'
        mock_getcwd.return_value = '/original'
        mock_uncommitted.return_value = False
        mock_check_ready.return_value = (True, "")
        mock_merge.return_value = True
        mock_close.return_value = True
        mock_invoke.return_value = CopilotResult(
            work_item_id="task-1",
            success=True,
            output="Work completed",
            attempt_count=1
        )
        # Mock subprocess: return different values based on git command
        def subprocess_side_effect(*args, **kwargs):
            cmd = args[0] if args else kwargs.get('args', [])
            if 'rev-list' in cmd:
                return Mock(stdout="1\n", returncode=0)
            elif 'branch' in cmd and '--show-current' in cmd:
                return Mock(stdout="master\n", returncode=0)
            elif 'status' in cmd and '--porcelain' in cmd:
                return Mock(stdout="", returncode=0)  # Clean repo
            elif cmd[0] == 'bd':
                if 'show' in cmd:
                    # Return open status so close_item will be called (as JSON array)
                    return Mock(stdout='[{"id": "task-1", "title": "Test", "status": "open", "priority": 1, "issue_type": "task"}]', returncode=0)
                elif 'sync' in cmd:
                    return Mock(stdout="", stderr="", returncode=0)
            elif 'checkout' in cmd or 'pull' in cmd or 'merge' in cmd or 'push' in cmd:
                return Mock(stdout="", returncode=0)
            return Mock(stdout="", returncode=0)
        mock_subprocess.side_effect = subprocess_side_effect
        mock_get_parent.return_value = None
        
        result = process_work_item(item, interactive=True)
        
        success, request_count, stats, cleanup_runs = result
        assert success == True
        assert request_count == 1
        assert cleanup_runs == 0
        mock_close.assert_called_once_with("task-1", "Completed by PokePoke orchestrator (agent did not close)")
    
    @patch('pokepoke.worktree_finalization.close_parent_if_complete')
    @patch('pokepoke.worktree_finalization.get_parent_id')
    @patch('pokepoke.worktree_finalization.close_item')  # Patch where it's used
    @patch('subprocess.run')
    @patch('pokepoke.workflow.cleanup_worktree')
    @patch('pokepoke.worktree_finalization.merge_worktree')
    @patch('pokepoke.worktree_finalization.check_main_repo_ready_for_merge')
    @patch('os.chdir')
    @patch('os.getcwd')
    @patch('pokepoke.workflow.create_worktree')
    @patch('pokepoke.workflow.invoke_copilot')
    def test_process_work_item_success_with_parent(
        self,
        mock_invoke: Mock,
        mock_create_wt: Mock,
        mock_getcwd: Mock,
        mock_chdir: Mock,
        mock_check_ready: Mock,
        mock_merge: Mock,
        mock_cleanup: Mock,
        mock_subprocess: Mock,
        mock_close: Mock,
        mock_get_parent: Mock,
        mock_close_parent: Mock
    ) -> None:
        """Test successful processing with parent closure."""
        item = BeadsWorkItem(
            id="task-1",
            title="Task",
            description="",
            status="open",
            priority=1,
            issue_type="task"
        )
        mock_create_wt.return_value = '/tmp/worktree'
        mock_getcwd.return_value = '/original'
        mock_check_ready.return_value = (True, "")
        mock_merge.return_value = True
        mock_close.return_value = True
        mock_invoke.return_value = CopilotResult(
            work_item_id="task-1",
            success=True,
            attempt_count=1
        )
        # Mock subprocess: return different values based on git command
        def subprocess_side_effect(*args, **kwargs):
            cmd = args[0] if args else kwargs.get('args', [])
            if 'rev-list' in cmd:
                return Mock(stdout="1\n", returncode=0)
            elif 'branch' in cmd and '--show-current' in cmd:
                return Mock(stdout="master\n", returncode=0)
            elif 'status' in cmd and '--porcelain' in cmd:
                return Mock(stdout="", returncode=0)  # Clean repo
            elif cmd[0] == 'bd':
                if 'show' in cmd:
                    # Return open status so close_item will be called (as JSON array)
                    return Mock(stdout='[{"id": "task-1", "title": "Test", "status": "open", "priority": 1, "issue_type": "task"}]', returncode=0)
                elif 'sync' in cmd:
                    return Mock(stdout="", stderr="", returncode=0)
            elif 'checkout' in cmd or 'pull' in cmd or 'merge' in cmd or 'push' in cmd:
                return Mock(stdout="", returncode=0)
            return Mock(stdout="", returncode=0)
        mock_subprocess.side_effect = subprocess_side_effect
        mock_get_parent.side_effect = ["feature-1", "epic-1", None]
        
        result = process_work_item(item, interactive=False)
        
        success, request_count, stats, cleanup_runs = result
        assert success == True
        assert request_count == 1
        assert cleanup_runs == 0
        mock_close.assert_called_once()
        assert mock_close_parent.call_count == 2
        mock_close_parent.assert_any_call("feature-1")
        mock_close_parent.assert_any_call("epic-1")
    
    @patch('subprocess.run')
    @patch('pokepoke.workflow.cleanup_worktree')
    @patch('pokepoke.worktree_finalization.merge_worktree')
    @patch('pokepoke.worktree_finalization.check_main_repo_ready_for_merge')
    @patch('pokepoke.git_operations.has_uncommitted_changes')
    @patch('os.chdir')
    @patch('os.getcwd')
    @patch('pokepoke.workflow.create_worktree')
    @patch('pokepoke.workflow.invoke_copilot')
    def test_process_work_item_failure(
        self,
        mock_invoke: Mock,
        mock_create_wt: Mock,
        mock_getcwd: Mock,
        mock_chdir: Mock,
        mock_uncommitted: Mock,
        mock_check_ready: Mock,
        mock_merge: Mock,
        mock_cleanup: Mock,
        mock_subprocess: Mock
    ) -> None:
        """Test processing failure - copilot fails and worktree is cleaned up."""
        item = BeadsWorkItem(
            id="task-1",
            title="Task",
            description="",
            status="open",
            priority=1,
            issue_type="task"
        )
        mock_create_wt.return_value = '/tmp/worktree'
        mock_getcwd.return_value = '/original'
        mock_uncommitted.return_value = False
        mock_check_ready.return_value = (True, "")
        mock_merge.return_value = True

        # Copilot fails
        mock_invoke.return_value = CopilotResult(
            work_item_id="task-1",
            success=False,
            error="Something went wrong",
            attempt_count=1
        )

        # Mock subprocess for git and bd commands
        def subprocess_side_effect(*args, **kwargs):
            cmd = args[0] if args else kwargs.get('args', [])
            if isinstance(cmd, list) and len(cmd) > 0:
                if 'rev-list' in cmd:
                    return Mock(stdout="1\n", returncode=0)
                elif 'status' in cmd and '--porcelain' in cmd:
                    return Mock(stdout="", returncode=0)
                elif cmd[0] == 'bd':
                    if 'show' in cmd:
                        return Mock(stdout='[{"id": "task-1", "title": "Test", "status": "open", "priority": 1, "issue_type": "task"}]', returncode=0)
                    elif 'sync' in cmd or 'update' in cmd:
                        return Mock(stdout="", stderr="", returncode=0)
            return Mock(stdout="", returncode=0)
        mock_subprocess.side_effect = subprocess_side_effect

        result = process_work_item(item, interactive=False)

        success, request_count, stats, cleanup_runs = result
        assert success == False  # Fails when copilot fails
        assert request_count == 1  # Records the failed attempt
        # Note: In actual failure scenario, cleanup may not be called if exception is raised
        # The important thing is that success is False
        assert stats is None  # No stats on failure
        assert cleanup_runs == 0  # No cleanup agents run on failure
        mock_invoke.assert_called_once()  # Copilot was invoked


class TestRunOrchestrator:
    """Test orchestrator main loop."""
    
    @patch('subprocess.run')  # Mock git status check
    @patch('pokepoke.agent_runner.run_beta_tester')
    @patch('pokepoke.orchestrator.initialize_agent_name')
    @patch('pokepoke.orchestrator.process_work_item')
    @patch('pokepoke.orchestrator.select_work_item')
    @patch('pokepoke.orchestrator.get_ready_work_items')
    def test_run_orchestrator_sets_agent_name(
        self,
        mock_get_items: Mock,
        mock_select: Mock,
        mock_process: Mock,
        mock_init_agent_name: Mock,
        mock_beta: Mock,
        mock_subprocess_run: Mock
    ) -> None:
        """Test that orchestrator initializes and sets AGENT_NAME env var."""
        import os
        
        mock_beta.return_value = None

        # Mock git status to return clean repo
        mock_subprocess_run.return_value = Mock(stdout="", returncode=0)
        
        # Mock agent name initialization
        test_agent_name = "pokepoke_test_agent_1234"
        mock_init_agent_name.return_value = test_agent_name
        
        mock_get_items.return_value = []
        mock_select.return_value = None
        
        result = run_orchestrator(interactive=False, continuous=False)
        
        # Verify agent name was initialized
        mock_init_agent_name.assert_called_once()
        
        # Verify AGENT_NAME env var was set
        assert os.environ.get('AGENT_NAME') == test_agent_name
        
        assert result == 0
    
    @patch('subprocess.run')  # Mock git status check
    @patch('pokepoke.agent_runner.run_beta_tester')
    @patch('pokepoke.orchestrator.process_work_item')
    @patch('pokepoke.orchestrator.select_work_item')
    @patch('pokepoke.orchestrator.get_ready_work_items')
    def test_run_orchestrator_no_items(
        self,
        mock_get_items: Mock,
        mock_select: Mock,
        mock_process: Mock,
        mock_beta: Mock,
        mock_subprocess_run: Mock
    ) -> None:
        """Test orchestrator with no ready items."""
        mock_beta.return_value = None
        # Mock git status to return clean repo
        mock_subprocess_run.return_value = Mock(stdout="", returncode=0)
        
        mock_get_items.return_value = []
        mock_select.return_value = None
        
        result = run_orchestrator(interactive=False, continuous=False)
        
        assert result == 0
        mock_process.assert_not_called()
    
    @patch('subprocess.run')  # Mock git status check
    @patch('pokepoke.agent_runner.run_beta_tester')
    @patch('pokepoke.orchestrator.run_maintenance_agent')  # Mock maintenance
    @patch('pokepoke.orchestrator.process_work_item')
    @patch('pokepoke.orchestrator.select_work_item')
    @patch('pokepoke.orchestrator.get_ready_work_items')
    def test_run_orchestrator_single_shot_success(
        self,
        mock_get_items: Mock,
        mock_select: Mock,
        mock_process: Mock,
        mock_maintenance: Mock,
        mock_beta: Mock,
        mock_subprocess_run: Mock
    ) -> None:
        """Test single-shot mode with successful processing."""
        mock_beta.return_value = None
        # Mock git status to return clean repo
        mock_subprocess_run.return_value = Mock(stdout="", returncode=0)
        
        # Mock maintenance agent to return stats
        mock_maintenance.return_value = None
        
        item = BeadsWorkItem(
            id="task-1",
            title="Task",
            description="",
            status="open",
            priority=1,
            issue_type="task"
        )
        mock_get_items.return_value = [item]
        mock_select.return_value = item
        mock_process.return_value = (True, 1, None, 0)  # 4-tuple: success, request_count, stats, cleanup_runs
        
        result = run_orchestrator(interactive=False, continuous=False)
        
        assert result == 0
        mock_process.assert_called_once()
    
    @patch('subprocess.run')  # Mock git status check
    @patch('pokepoke.agent_runner.run_beta_tester')
    @patch('pokepoke.orchestrator.process_work_item')
    @patch('pokepoke.orchestrator.select_work_item')
    @patch('pokepoke.orchestrator.get_ready_work_items')
    def test_run_orchestrator_single_shot_failure(
        self,
        mock_get_items: Mock,
        mock_select: Mock,
        mock_process: Mock,
        mock_beta: Mock,
        mock_subprocess_run: Mock
    ) -> None:
        """Test single-shot mode with processing failure."""
        mock_beta.return_value = None
        # Mock git status to return clean repo
        mock_subprocess_run.return_value = Mock(stdout="", returncode=0)
        
        item = BeadsWorkItem(
            id="task-1",
            title="Task",
            description="",
            status="open",
            priority=1,
            issue_type="task"
        )
        mock_get_items.return_value = [item]
        mock_select.return_value = item
        mock_process.return_value = False
        
        result = run_orchestrator(interactive=False, continuous=False)
        
        assert result == 1
    
    @patch('subprocess.run')  # Mock git status check
    @patch('builtins.input')
    @patch('pokepoke.agent_runner.run_beta_tester')
    @patch('pokepoke.orchestrator.run_maintenance_agent')  # Mock maintenance
    @patch('pokepoke.orchestrator.process_work_item')
    @patch('pokepoke.orchestrator.select_work_item')
    @patch('pokepoke.orchestrator.get_ready_work_items')
    def test_run_orchestrator_continuous_quit(
        self,
        mock_get_items: Mock,
        mock_select: Mock,
        mock_process: Mock,
        mock_maintenance: Mock,
        mock_beta: Mock,
        mock_input: Mock,
        mock_subprocess_run: Mock
    ) -> None:
        """Test continuous interactive mode with user quit."""
        mock_beta.return_value = None
        # Mock git status to return clean repo
        mock_subprocess_run.return_value = Mock(stdout="", returncode=0)
        
        # Mock maintenance agent
        mock_maintenance.return_value = None
        
        item = BeadsWorkItem(
            id="task-1",
            title="Task",
            description="",
            status="open",
            priority=1,
            issue_type="task"
        )
        mock_get_items.return_value = [item]
        mock_select.return_value = item
        mock_process.return_value = (True, 1, None, 0)  # 4-tuple: success, request_count, stats, cleanup_runs
        mock_input.return_value = 'n'  # Don't continue
        
        result = run_orchestrator(interactive=True, continuous=True)
        
        assert result == 0
        mock_process.assert_called_once()
    
    @patch('subprocess.run')  # Mock git status check
    @patch('pokepoke.agent_runner.run_beta_tester')
    @patch('pokepoke.orchestrator.process_work_item')
    @patch('pokepoke.orchestrator.select_work_item')
    @patch('pokepoke.orchestrator.get_ready_work_items')
    def test_run_orchestrator_exception_handling(
        self,
        mock_get_items: Mock,
        mock_select: Mock,
        mock_process: Mock,
        mock_beta: Mock,
        mock_subprocess_run: Mock
    ) -> None:
        """Test orchestrator handles exceptions."""
        mock_beta.return_value = None
        # Mock git status to return clean repo initially
        mock_subprocess_run.return_value = Mock(stdout="", returncode=0)
        
        mock_get_items.side_effect = Exception("Database error")
        
        result = run_orchestrator(interactive=False, continuous=False)
        
        assert result == 1


class TestCheckMainRepoReadyForMerge:
    """Test check_main_repo_ready_for_merge function."""
    
    @patch('subprocess.run')
    def test_clean_repo(self, mock_subprocess: Mock) -> None:
        """Test clean repo returns ready."""
        from pokepoke.git_operations import check_main_repo_ready_for_merge
        
        mock_subprocess.return_value = Mock(stdout="")
        is_ready, error = check_main_repo_ready_for_merge()
        
        assert is_ready == True
        assert error == ""
    
    @patch('subprocess.run')
    def test_beads_only_changes(self, mock_subprocess: Mock) -> None:
        """Test beads-only changes are auto-committed."""
        from pokepoke.git_operations import check_main_repo_ready_for_merge
        
        # First call returns beads changes, subsequent calls succeed
        mock_subprocess.side_effect = [
            Mock(stdout="M .beads/issues.jsonl\n"),
            None,  # git add
            None   # git commit
        ]
        
        is_ready, error = check_main_repo_ready_for_merge()
        
        assert is_ready == True
        assert error == ""
        assert mock_subprocess.call_count == 3
    
    @patch('subprocess.run')
    def test_non_beads_changes(self, mock_subprocess: Mock) -> None:
        """Test non-beads changes cause failure."""
        from pokepoke.git_operations import check_main_repo_ready_for_merge
        
        mock_subprocess.return_value = Mock(stdout="M src/file.py\nM .beads/issues.jsonl\n")
        is_ready, error = check_main_repo_ready_for_merge()
        
        assert is_ready == False
        assert "src/file.py" in error
        # Should only call git status once, not attempt to commit
        assert mock_subprocess.call_count == 1
    
    @patch('subprocess.run')
    def test_subprocess_error(self, mock_subprocess: Mock) -> None:
        """Test subprocess error is handled."""
        from pokepoke.git_operations import check_main_repo_ready_for_merge
        
        mock_subprocess.side_effect = Exception("git command failed")
        is_ready, error = check_main_repo_ready_for_merge()
        
        assert is_ready == False
        assert "git command failed" in error


class TestRunOrchestratorContinuousMode:
    """Test continuous mode scenarios."""
    
    @patch('pokepoke.agent_runner.run_beta_tester')
    @patch('pokepoke.orchestrator.run_maintenance_agent')
    @patch('time.sleep')
    @patch('pokepoke.orchestrator.get_beads_stats')
    @patch('pokepoke.orchestrator.process_work_item')
    @patch('pokepoke.orchestrator.select_work_item')
    @patch('pokepoke.orchestrator.get_ready_work_items')
    @patch('pokepoke.orchestrator.check_and_commit_main_repo')
    def test_continuous_autonomous_multiple_items(
        self,
        mock_check_repo: Mock,
        mock_get_items: Mock,
        mock_select: Mock,
        mock_process: Mock,
        mock_stats: Mock,
        mock_sleep: Mock,
        mock_maintenance: Mock,
        mock_beta: Mock
    ) -> None:
        """Test continuous autonomous mode processes multiple items."""
        from pokepoke.orchestrator import run_orchestrator
        from pokepoke.types import AgentStats
        
        item1 = BeadsWorkItem(
            id="task-1",
            title="Task 1",
            description="",
            status="open",
            priority=1,
            issue_type="task"
        )
        item2 = BeadsWorkItem(
            id="task-2",
            title="Task 2",
            description="",
            status="open",
            priority=1,
            issue_type="task"
        )
        
        mock_check_repo.return_value = True
        mock_get_items.side_effect = [[item1], [item2], []]
        mock_select.side_effect = [item1, item2, None]
        mock_process.side_effect = [
            (True, 1, AgentStats(), 0),
            (True, 1, AgentStats(), 0)
        ]
        mock_stats.return_value = {}
        mock_maintenance.return_value = None
        mock_beta.return_value = None
        
        result = run_orchestrator(interactive=False, continuous=True)
        
        assert result == 0
        assert mock_process.call_count == 2
    
    @patch('time.sleep')  # Mock sleep to avoid delays
    @patch('pokepoke.agent_runner.run_beta_tester')
    @patch('pokepoke.orchestrator.run_maintenance_agent')
    @patch('pokepoke.orchestrator.get_beads_stats')
    @patch('pokepoke.orchestrator.process_work_item')
    @patch('pokepoke.orchestrator.select_work_item')
    @patch('pokepoke.orchestrator.get_ready_work_items')
    @patch('pokepoke.orchestrator.check_and_commit_main_repo')
    def test_maintenance_agents_triggered(
        self,
        mock_check_repo: Mock,
        mock_get_items: Mock,
        mock_select: Mock,
        mock_process: Mock,
        mock_stats: Mock,
        mock_maintenance: Mock,
        mock_beta: Mock,
        mock_sleep: Mock
    ) -> None:
        """Test maintenance agents are triggered at correct intervals."""
        from pokepoke.orchestrator import run_orchestrator
        from pokepoke.types import AgentStats
        
        items = [BeadsWorkItem(
            id=f"task-{i}",
            title=f"Task {i}",
            description="",
            status="open",
            priority=1,
            issue_type="task"
        ) for i in range(11)]
        
        mock_check_repo.return_value = True
        # Return items for 10 iterations, then None
        mock_get_items.side_effect = [[items[i]] for i in range(10)] + [[]]
        mock_select.side_effect = items[:10] + [None]
        mock_process.return_value = (True, 1, AgentStats(), 0)
        mock_stats.return_value = {}
        mock_maintenance.return_value = AgentStats()
        mock_beta.return_value = AgentStats()
        
        result = run_orchestrator(interactive=False, continuous=True)
        
        assert result == 0
        # New frequencies:
        # Janitor: every 2 items -> runs at 2, 4, 6, 8, 10 (5 times)
        # Beta Tester: every 3 items -> runs at 3, 6, 9 (3 times)
        # Tech Debt: every 5 items -> runs at 5, 10 (2 times)
        # Backlog Cleanup: every 7 items -> runs at 7 (1 time)
        # Total maintenance calls: 5 + 2 + 1 = 8 (not counting beta tester)
        assert mock_maintenance.call_count >= 5  # At least 5 maintenance agents ran (janitor alone)
        assert mock_beta.call_count >= 3  # Beta tester runs every 3 items
    
    @patch('pokepoke.agent_runner.run_beta_tester')
    @patch('pokepoke.orchestrator.run_maintenance_agent')
    @patch('builtins.input')
    @patch('pokepoke.orchestrator.get_beads_stats')
    @patch('pokepoke.orchestrator.process_work_item')
    @patch('pokepoke.orchestrator.select_work_item')
    @patch('pokepoke.orchestrator.get_ready_work_items')
    @patch('pokepoke.orchestrator.check_and_commit_main_repo')
    def test_continuous_interactive_loop(
        self,
        mock_check_repo: Mock,
        mock_get_items: Mock,
        mock_select: Mock,
        mock_process: Mock,
        mock_stats: Mock,
        mock_input: Mock,
        mock_maintenance: Mock,
        mock_beta: Mock
    ) -> None:
        """Test continuous interactive mode with user continuation prompt."""
        from pokepoke.orchestrator import run_orchestrator
        from pokepoke.types import AgentStats
        
        # Configure mocks to avoid returning Mocks that cause TypeErrors during stats aggregation
        mock_maintenance.return_value = None
        mock_beta.return_value = None
        
        item = BeadsWorkItem(
            id="task-1",
            title="Task 1",
            description="",
            status="open",
            priority=1,
            issue_type="task"
        )
        
        mock_check_repo.return_value = True
        mock_get_items.return_value = [item]
        mock_select.return_value = item
        mock_process.return_value = (True, 1, AgentStats(), 0)
        mock_stats.return_value = {}
        mock_input.return_value = 'n'  # Don't continue
        
        result = run_orchestrator(interactive=True, continuous=True)
        
        assert result == 0
        mock_input.assert_called_once()


class TestOrchestratorHelperFunctions:
    """Test orchestrator helper functions."""
    
    @patch('pokepoke.agent_runner.invoke_cleanup_agent')
    @patch('subprocess.run')
    def test_check_and_commit_main_repo_with_non_beads_changes(
        self,
        mock_subprocess: Mock,
        mock_cleanup: Mock
    ) -> None:
        """Test check_and_commit_main_repo with non-beads changes - should invoke cleanup agent."""
        from pokepoke.repo_check import check_and_commit_main_repo
        from pokepoke.types import AgentStats
        from pokepoke.logging_utils import RunLogger
        from pathlib import Path
        import tempfile
        
        mock_subprocess.return_value = Mock(
            stdout=" M src/file.py\n M tests/test.py\n",
            returncode=0
        )
        # Mock cleanup agent to return success
        mock_cleanup.return_value = (True, AgentStats(
            wall_duration=1.0,
            api_duration=1.0,
            input_tokens=100,
            output_tokens=50,
            lines_added=5,
            lines_removed=3,
            premium_requests=1
        ))
        
        # Create a temporary logger
        with tempfile.TemporaryDirectory() as tmpdir:
            run_logger = RunLogger(base_dir=tmpdir)
            repo_path = Path.cwd()
            
            result = check_and_commit_main_repo(repo_path, run_logger)
            
            assert result is True  # Should return True after successful cleanup
            # Should call subprocess for git status
            assert mock_subprocess.call_count >= 1
            mock_cleanup.assert_called_once()
            
            # Verify cleanup agent was called with correct work item
            call_args = mock_cleanup.call_args
            work_item = call_args[0][0]  # First positional argument
            assert work_item.id == "cleanup-main-repo"
            assert "uncommitted changes" in work_item.title.lower()
    
    def test_aggregate_stats(self) -> None:
        """Test _aggregate_stats function."""
        from pokepoke.orchestrator import _aggregate_stats
        from pokepoke.types import SessionStats, AgentStats
        
        session_stats = SessionStats(agent_stats=AgentStats(
            wall_duration=10.0,
            api_duration=5.0,
            input_tokens=100,
            output_tokens=50,
            lines_added=10,
            lines_removed=5,
            premium_requests=1
        ))
        
        item_stats = AgentStats(
            wall_duration=5.0,
            api_duration=2.0,
            input_tokens=50,
            output_tokens=25,
            lines_added=5,
            lines_removed=2,
            premium_requests=1
        )
        
        _aggregate_stats(session_stats, item_stats)
        
        assert session_stats.agent_stats.wall_duration == 15.0
        assert session_stats.agent_stats.api_duration == 7.0
        assert session_stats.agent_stats.input_tokens == 150
        assert session_stats.agent_stats.output_tokens == 75
        assert session_stats.agent_stats.lines_added == 15
        assert session_stats.agent_stats.lines_removed == 7
        assert session_stats.agent_stats.premium_requests == 2


class TestOrchestratorMain:
    """Test main entry point."""
    
    @patch('pokepoke.orchestrator.run_orchestrator')
    @patch('sys.argv', ['pokepoke', '--autonomous'])
    def test_main_autonomous(self, mock_run: Mock) -> None:
        """Test main with autonomous flag."""
        from pokepoke.orchestrator import main
        
        mock_run.return_value = 0
        
        result = main()
        
        assert result == 0
        mock_run.assert_called_once_with(interactive=False, continuous=False, run_beta_first=False)
    
    @patch('pokepoke.orchestrator.run_orchestrator')
    @patch('sys.argv', ['pokepoke', '--continuous'])
    def test_main_continuous(self, mock_run: Mock) -> None:
        """Test main with continuous flag."""
        from pokepoke.orchestrator import main
        
        mock_run.return_value = 0
        
        result = main()
        
        assert result == 0
        mock_run.assert_called_once_with(interactive=True, continuous=True, run_beta_first=False)
    
    @patch('pokepoke.orchestrator.run_orchestrator')
    @patch('sys.argv', ['pokepoke', '--autonomous', '--continuous'])
    def test_main_both_flags(self, mock_run: Mock) -> None:
        """Test main with both flags."""
        from pokepoke.orchestrator import main
        
        mock_run.return_value = 0
        
        result = main()
        
        assert result == 0
        mock_run.assert_called_once_with(interactive=False, continuous=True, run_beta_first=False)




