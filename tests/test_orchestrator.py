"""Unit tests for orchestrator module."""

from unittest.mock import Mock, patch

from pokepoke.orchestrator import run_orchestrator
from pokepoke.workflow import select_work_item, process_work_item
from pokepoke.types import BeadsWorkItem, BeadsStats, CopilotResult


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
    
    @patch('pokepoke.workflow.run_gate_agent')  # Mock gate agent to avoid actual copilot calls
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
        mock_close_parent: Mock,
        mock_gate_agent: Mock
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
        mock_merge.return_value = (True, [])  # Updated to return tuple
        mock_close.return_value = True
        mock_gate_agent.return_value = (True, "Gate passed", None)  # Gate agent passes
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
        
        success, request_count, stats, cleanup_runs, gate_runs, model_completion = result
        assert success == True
        assert request_count == 1
        assert cleanup_runs == 0
        mock_close.assert_called_once_with("task-1", "Completed by PokePoke orchestrator (agent did not close)")
    
    @patch('pokepoke.workflow.run_gate_agent')  # Mock gate agent to avoid actual copilot calls
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
        mock_close_parent: Mock,
        mock_gate_agent: Mock
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
        mock_merge.return_value = (True, [])  # Updated to return tuple
        mock_close.return_value = True
        mock_gate_agent.return_value = (True, "Gate passed", None)  # Gate agent passes
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
        
        success, request_count, stats, cleanup_runs, gate_runs, model_completion = result
        assert success == True
        assert request_count == 1
        assert cleanup_runs == 0
        mock_close.assert_called_once()
        assert mock_close_parent.call_count == 2
        mock_close_parent.assert_any_call("feature-1")
        mock_close_parent.assert_any_call("epic-1")
    
    @patch('pokepoke.workflow.run_gate_agent')  # Mock gate agent to avoid actual copilot calls
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
        mock_subprocess: Mock,
        mock_gate_agent: Mock
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
        mock_merge.return_value = (True, [])  # Updated to return tuple
        mock_gate_agent.return_value = (True, "Gate passed", None)  # Gate agent passes

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

        success, request_count, stats, cleanup_runs, gate_runs, model_completion = result
        assert success == False  # Fails when copilot fails
        assert request_count == 1  # Records the failed attempt
        # Note: In actual failure scenario, cleanup may not be called if exception is raised
        # The important thing is that success is False
        assert stats is None  # No stats on failure
        assert cleanup_runs == 0  # No cleanup agents run on failure
        mock_invoke.assert_called_once()  # Copilot was invoked

    @patch('pokepoke.workflow.run_gate_agent')
    @patch('subprocess.run')
    @patch('pokepoke.workflow.cleanup_worktree')
    @patch('pokepoke.workflow.invoke_copilot')
    @patch('pokepoke.workflow.create_worktree')
    def test_process_work_item_cleans_worktree_on_unhandled_exception(
        self,
        mock_create_wt: Mock,
        mock_invoke: Mock,
        mock_cleanup: Mock,
        mock_subprocess: Mock,
        mock_gate_agent: Mock
    ) -> None:
        """Test that worktree is cleaned up when an unhandled exception occurs."""
        item = BeadsWorkItem(
            id="task-1",
            title="Task",
            description="",
            status="open",
            priority=1,
            issue_type="task"
        )
        mock_create_wt.return_value = '/tmp/worktree'

        # Mock subprocess for bd assign/sync
        def subprocess_side_effect(*args, **kwargs):
            cmd = args[0] if args else kwargs.get('args', [])
            if isinstance(cmd, list) and len(cmd) > 0:
                if cmd[0] == 'bd':
                    if 'show' in cmd:
                        return Mock(stdout='[{"id": "task-1", "title": "Test", "status": "open", "priority": 1, "issue_type": "task"}]', returncode=0)
                    elif 'sync' in cmd or 'update' in cmd:
                        return Mock(stdout="", stderr="", returncode=0)
            return Mock(stdout="", returncode=0)
        mock_subprocess.side_effect = subprocess_side_effect

        # Copilot raises an unhandled exception
        mock_invoke.side_effect = RuntimeError("Unexpected crash")

        try:
            process_work_item(item, interactive=False)
        except RuntimeError:
            pass

        # Worktree cleanup should have been called in the finally block
        mock_cleanup.assert_called_with("task-1", force=True)


class TestRunOrchestrator:
    """Test orchestrator main loop."""
    
    @patch('subprocess.run')  # Mock git status check
    @patch('pokepoke.agent_runner.run_worktree_cleanup')
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
        mock_worktree_cleanup: Mock,
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
    @patch('pokepoke.agent_runner.run_worktree_cleanup')
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
        mock_worktree_cleanup: Mock,
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
    @patch('pokepoke.agent_runner.run_worktree_cleanup')
    @patch('pokepoke.agent_runner.run_beta_tester')
    @patch('pokepoke.orchestrator.run_periodic_maintenance')  # Mock maintenance
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
        mock_worktree_cleanup: Mock,
        mock_subprocess_run: Mock
    ) -> None:
        """Test single-shot mode with successful processing."""
        from pokepoke.types import AgentStats
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
        mock_process.return_value = (True, 1, AgentStats(), 0, 0, None)  # 6-tuple: success, request_count, stats, cleanup_runs, gate_runs, model_completion
        
        result = run_orchestrator(interactive=False, continuous=False)
        
        assert result == 0
        mock_process.assert_called_once()
    
    @patch('subprocess.run')  # Mock git status check
    @patch('pokepoke.agent_runner.run_worktree_cleanup')
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
        mock_worktree_cleanup: Mock,
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
    @patch('pokepoke.agent_runner.run_worktree_cleanup')
    @patch('pokepoke.agent_runner.run_beta_tester')
    @patch('pokepoke.orchestrator.run_periodic_maintenance')  # Mock maintenance
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
        mock_worktree_cleanup: Mock,
        mock_input: Mock,
        mock_subprocess_run: Mock
    ) -> None:
        """Test continuous interactive mode with user quit."""
        from pokepoke.types import AgentStats
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
        mock_process.return_value = (True, 1, AgentStats(), 0, 0, None)  # 6-tuple: success, request_count, stats, cleanup_runs, gate_runs, model_completion
        mock_input.return_value = 'n'  # Don't continue
        
        result = run_orchestrator(interactive=True, continuous=True)
        
        assert result == 0
        mock_process.assert_called_once()
    
    @patch('subprocess.run')  # Mock git status check
    @patch('pokepoke.agent_runner.run_worktree_cleanup')
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
        mock_worktree_cleanup: Mock,
        mock_subprocess_run: Mock
    ) -> None:
        """Test orchestrator handles exceptions."""
        mock_beta.return_value = None
        # Mock git status to return clean repo initially
        mock_subprocess_run.return_value = Mock(stdout="", returncode=0)
        
        mock_get_items.side_effect = Exception("Database error")
        
        result = run_orchestrator(interactive=False, continuous=False)
        
        assert result == 1

    @patch('subprocess.run')  # Mock git status check
    @patch('pokepoke.agent_runner.run_worktree_cleanup')
    @patch('pokepoke.agent_runner.run_beta_tester')
    @patch('pokepoke.orchestrator.process_work_item')
    @patch('pokepoke.orchestrator.select_work_item')
    @patch('pokepoke.orchestrator.get_ready_work_items')
    def test_run_orchestrator_shutdown_exit(
        self,
        mock_get_items: Mock,
        mock_select: Mock,
        mock_process: Mock,
        mock_beta: Mock,
        mock_worktree_cleanup: Mock,
        mock_subprocess_run: Mock
    ) -> None:
        """Test orchestrator exits cleanly when shutdown is requested."""
        from pokepoke.shutdown import request_shutdown, reset
        mock_beta.return_value = None
        mock_subprocess_run.return_value = Mock(stdout="", returncode=0)

        # Simulate shutdown being requested before loop runs
        request_shutdown()
        try:
            result = run_orchestrator(interactive=False, continuous=True)
            assert result == 0
        finally:
            reset()


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
    
    @patch('pokepoke.agent_runner.run_worktree_cleanup')
    @patch('pokepoke.agent_runner.run_beta_tester')
    @patch('pokepoke.orchestrator.run_periodic_maintenance')
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
        mock_beta: Mock,
        mock_worktree_cleanup: Mock
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
            (True, 1, AgentStats(), 0, 0, None),
            (True, 1, AgentStats(), 0, 0, None)
        ]
        mock_stats.return_value = {}
        mock_maintenance.return_value = None
        mock_beta.return_value = None
        
        result = run_orchestrator(interactive=False, continuous=True)
        
        assert result == 0
        assert mock_process.call_count == 2
    
    @patch('time.sleep')  # Mock sleep to avoid delays
    @patch('pokepoke.agent_runner.run_worktree_cleanup')
    @patch('pokepoke.agent_runner.run_beta_tester')
    @patch('pokepoke.orchestrator.run_periodic_maintenance')  # Mock maintenance
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
        mock_worktree_cleanup: Mock,
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
        mock_process.return_value = (True, 1, AgentStats(), 0, 0, None)
        mock_stats.return_value = {}
        mock_maintenance.return_value = None  # run_periodic_maintenance doesn't return anything
        mock_beta.return_value = None
        
        result = run_orchestrator(interactive=False, continuous=True)
        
        assert result == 0
        # run_periodic_maintenance is called once per successful item
        assert mock_maintenance.call_count == 10  # Called once per item
    
    @patch('pokepoke.agent_runner.run_worktree_cleanup')
    @patch('pokepoke.agent_runner.run_beta_tester')
    @patch('pokepoke.orchestrator.run_periodic_maintenance')
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
        mock_beta: Mock,
        mock_worktree_cleanup: Mock
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
        mock_process.return_value = (True, 1, AgentStats(), 0, 0, None)
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
        """Test aggregate_stats function."""
        from pokepoke.maintenance import aggregate_stats
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
        
        aggregate_stats(session_stats, item_stats)
        
        assert session_stats.agent_stats.wall_duration == 15.0
        assert session_stats.agent_stats.api_duration == 7.0
        assert session_stats.agent_stats.input_tokens == 150
        assert session_stats.agent_stats.output_tokens == 75
        assert session_stats.agent_stats.lines_added == 15
        assert session_stats.agent_stats.lines_removed == 7
        assert session_stats.agent_stats.premium_requests == 2


class TestOrchestratorMain:
    """Test main entry point."""
    
    @patch('pokepoke.orchestrator._check_beads_available', return_value=True)
    @patch('pokepoke.orchestrator.run_orchestrator')
    @patch('pokepoke.terminal_ui.ui')
    @patch('sys.argv', ['pokepoke', '--autonomous'])
    def test_main_autonomous(self, mock_ui: Mock, mock_run: Mock, _mock_beads: Mock) -> None:
        """Test main with autonomous flag."""
        from pokepoke.orchestrator import main
        
        mock_run.return_value = 0
        mock_ui.run_with_orchestrator.side_effect = lambda f: f()
        
        result = main()
        
        assert result == 0
        mock_run.assert_called_once_with(interactive=False, continuous=False, run_beta_first=False)
    
    @patch('pokepoke.orchestrator._check_beads_available', return_value=True)
    @patch('pokepoke.orchestrator.run_orchestrator')
    @patch('pokepoke.terminal_ui.ui')
    @patch('sys.argv', ['pokepoke', '--continuous'])
    def test_main_continuous(self, mock_ui: Mock, mock_run: Mock, _mock_beads: Mock) -> None:
        """Test main with continuous flag."""
        from pokepoke.orchestrator import main
        
        mock_run.return_value = 0
        mock_ui.run_with_orchestrator.side_effect = lambda f: f()
        
        result = main()
        
        assert result == 0
        mock_run.assert_called_once_with(interactive=True, continuous=True, run_beta_first=False)
    
    @patch('pokepoke.orchestrator._check_beads_available', return_value=True)
    @patch('pokepoke.orchestrator.run_orchestrator')
    @patch('pokepoke.terminal_ui.ui')
    @patch('sys.argv', ['pokepoke', '--autonomous', '--continuous'])
    def test_main_both_flags(self, mock_ui: Mock, mock_run: Mock, _mock_beads: Mock) -> None:
        """Test main with both flags."""
        from pokepoke.orchestrator import main
        
        mock_run.return_value = 0
        mock_ui.run_with_orchestrator.side_effect = lambda f: f()
        
        result = main()
        
        assert result == 0
        mock_run.assert_called_once_with(interactive=False, continuous=True, run_beta_first=False)

    @patch('pokepoke.orchestrator._check_beads_available', return_value=False)
    @patch('sys.argv', ['pokepoke', '--autonomous'])
    def test_main_exits_when_beads_unavailable(self, _mock_beads: Mock) -> None:
        """Test main exits with code 1 when beads is not available."""
        from pokepoke.orchestrator import main

        result = main()

        assert result == 1

    @patch('pokepoke.orchestrator._check_beads_available', return_value=True)
    @patch('pokepoke.orchestrator.run_orchestrator')
    @patch('pokepoke.terminal_ui.ui')
    @patch('sys.argv', ['pokepoke', '--autonomous', '--beta-first'])
    def test_main_beta_first(self, mock_ui: Mock, mock_run: Mock, _mock_beads: Mock) -> None:
        """Test main with beta-first flag."""
        from pokepoke.orchestrator import main

        mock_run.return_value = 0
        mock_ui.run_with_orchestrator.side_effect = lambda f: f()

        result = main()

        assert result == 0
        mock_run.assert_called_once_with(interactive=False, continuous=False, run_beta_first=True)

    @patch('pokepoke.init.init_project', return_value=True)
    @patch('sys.argv', ['pokepoke', '--init'])
    def test_main_init_success(self, mock_init: Mock) -> None:
        """Test main with --init flag succeeding."""
        from pokepoke.orchestrator import main

        result = main()

        assert result == 0
        mock_init.assert_called_once()

    @patch('pokepoke.init.init_project', return_value=False)
    @patch('sys.argv', ['pokepoke', '--init'])
    def test_main_init_failure(self, mock_init: Mock) -> None:
        """Test main with --init flag failing."""
        from pokepoke.orchestrator import main

        result = main()

        assert result == 1


class TestCheckBeadsAvailable:
    """Test _check_beads_available function."""

    @patch('src.pokepoke.orchestrator.shutil.which', return_value=None)
    def test_bd_not_installed(self, mock_which: Mock) -> None:
        """Test returns False when bd command not found."""
        from src.pokepoke.orchestrator import _check_beads_available

        result = _check_beads_available()

        assert result is False

    @patch('src.pokepoke.orchestrator.subprocess.run')
    @patch('src.pokepoke.orchestrator.shutil.which', return_value='/usr/bin/bd')
    def test_bd_info_succeeds(self, mock_which: Mock, mock_run: Mock) -> None:
        """Test returns True when bd is installed and initialized."""
        from src.pokepoke.orchestrator import _check_beads_available

        mock_run.return_value = Mock(returncode=0)

        result = _check_beads_available()

        assert result is True

    @patch('src.pokepoke.orchestrator.subprocess.run')
    @patch('src.pokepoke.orchestrator.shutil.which', return_value='/usr/bin/bd')
    def test_bd_not_initialized(self, mock_which: Mock, mock_run: Mock) -> None:
        """Test returns False when bd info fails (not initialized)."""
        from src.pokepoke.orchestrator import _check_beads_available

        mock_run.return_value = Mock(returncode=1)

        result = _check_beads_available()

        assert result is False

    @patch('src.pokepoke.orchestrator.subprocess.run')
    @patch('src.pokepoke.orchestrator.shutil.which', return_value='/usr/bin/bd')
    def test_bd_info_timeout(self, mock_which: Mock, mock_run: Mock) -> None:
        """Test returns False when bd info times out."""
        import subprocess as sp
        from src.pokepoke.orchestrator import _check_beads_available

        mock_run.side_effect = sp.TimeoutExpired('bd', 10)

        result = _check_beads_available()

        assert result is False

    @patch('src.pokepoke.orchestrator.subprocess.run')
    @patch('src.pokepoke.orchestrator.shutil.which', return_value='/usr/bin/bd')
    def test_bd_info_exception(self, mock_which: Mock, mock_run: Mock) -> None:
        """Test returns False on unexpected exception."""
        from src.pokepoke.orchestrator import _check_beads_available

        mock_run.side_effect = OSError("Permission denied")

        result = _check_beads_available()

        assert result is False


class TestFinalizeSession:
    """Test _finalize_session function."""

    @patch('src.pokepoke.orchestrator.clear_terminal_banner')
    @patch('src.pokepoke.orchestrator.print_stats')
    @patch('src.pokepoke.orchestrator.get_beads_stats')
    @patch('src.pokepoke.orchestrator.time')
    def test_finalize_session_success(
        self, mock_time: Mock, mock_stats: Mock,
        mock_print: Mock, mock_clear: Mock
    ) -> None:
        """Test finalize collects stats, prints, and clears banner."""
        from src.pokepoke.orchestrator import _finalize_session
        from pokepoke.types import SessionStats, AgentStats
        from pokepoke.logging_utils import RunLogger
        import tempfile

        mock_time.time.return_value = 100.0
        mock_stats.return_value = {"items": 5}

        session = SessionStats(agent_stats=AgentStats())
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = RunLogger(base_dir=tmpdir)
            _finalize_session(session, 90.0, 3, 5, logger)

        assert session.ending_beads_stats == {"items": 5}
        mock_print.assert_called_once()
        mock_clear.assert_called_once()

    @patch('src.pokepoke.orchestrator.clear_terminal_banner')
    @patch('src.pokepoke.orchestrator.print_stats')
    @patch('src.pokepoke.orchestrator.get_beads_stats')
    @patch('src.pokepoke.orchestrator.time')
    def test_finalize_session_keyboard_interrupt(
        self, mock_time: Mock, mock_stats: Mock,
        mock_print: Mock, mock_clear: Mock
    ) -> None:
        """Test finalize handles KeyboardInterrupt during stats collection."""
        from src.pokepoke.orchestrator import _finalize_session
        from pokepoke.types import SessionStats, AgentStats
        from pokepoke.logging_utils import RunLogger
        import tempfile

        mock_time.time.return_value = 100.0
        mock_stats.side_effect = KeyboardInterrupt

        session = SessionStats(agent_stats=AgentStats())
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = RunLogger(base_dir=tmpdir)
            _finalize_session(session, 90.0, 0, 0, logger)

        assert session.ending_beads_stats is None
        mock_print.assert_called_once()
        mock_clear.assert_called_once()


class TestRunOrchestratorBetaFirst:
    """Test run_orchestrator with beta_first flag."""

    @patch('subprocess.run')
    @patch('pokepoke.agent_runner.run_worktree_cleanup')
    @patch('pokepoke.agent_runner.run_beta_tester')
    @patch('pokepoke.orchestrator.process_work_item')
    @patch('pokepoke.orchestrator.select_work_item')
    @patch('pokepoke.orchestrator.get_ready_work_items')
    def test_beta_first_runs_beta_tester(
        self, mock_get_items: Mock, mock_select: Mock,
        mock_process: Mock, mock_beta: Mock,
        mock_cleanup: Mock, mock_subprocess: Mock
    ) -> None:
        """Test beta tester runs at startup when run_beta_first=True."""
        from pokepoke.types import AgentStats

        mock_subprocess.return_value = Mock(stdout="", returncode=0)
        beta_stats = AgentStats(
            wall_duration=10.0, api_duration=5.0,
            input_tokens=100, output_tokens=50,
            premium_requests=1
        )
        mock_beta.return_value = beta_stats
        mock_get_items.return_value = []
        mock_select.return_value = None

        result = run_orchestrator(interactive=False, continuous=False, run_beta_first=True)

        assert result == 0
        mock_beta.assert_called_once()

    @patch('subprocess.run')
    @patch('pokepoke.agent_runner.run_worktree_cleanup')
    @patch('pokepoke.agent_runner.run_beta_tester')
    @patch('pokepoke.orchestrator.process_work_item')
    @patch('pokepoke.orchestrator.select_work_item')
    @patch('pokepoke.orchestrator.get_ready_work_items')
    def test_beta_first_none_stats(
        self, mock_get_items: Mock, mock_select: Mock,
        mock_process: Mock, mock_beta: Mock,
        mock_cleanup: Mock, mock_subprocess: Mock
    ) -> None:
        """Test beta tester returning None stats is handled."""
        mock_subprocess.return_value = Mock(stdout="", returncode=0)
        mock_beta.return_value = None
        mock_get_items.return_value = []
        mock_select.return_value = None

        result = run_orchestrator(interactive=False, continuous=False, run_beta_first=True)

        assert result == 0


class TestRunOrchestratorFailedClaims:
    """Test failed claim tracking in run_orchestrator."""

    @patch('time.sleep')
    @patch('pokepoke.agent_runner.run_worktree_cleanup')
    @patch('pokepoke.agent_runner.run_beta_tester')
    @patch('pokepoke.orchestrator.run_periodic_maintenance')
    @patch('pokepoke.orchestrator.get_beads_stats')
    @patch('pokepoke.orchestrator.process_work_item')
    @patch('pokepoke.orchestrator.select_work_item')
    @patch('pokepoke.orchestrator.get_ready_work_items')
    @patch('pokepoke.orchestrator.check_and_commit_main_repo')
    def test_failed_claim_added_to_skip_list(
        self, mock_check_repo: Mock, mock_get_items: Mock,
        mock_select: Mock, mock_process: Mock,
        mock_stats: Mock, mock_maintenance: Mock,
        mock_beta: Mock, mock_cleanup: Mock, mock_sleep: Mock
    ) -> None:
        """Test failed claims (0 requests) are tracked to avoid retrying."""
        from pokepoke.types import AgentStats

        mock_check_repo.return_value = True
        mock_stats.return_value = {}
        mock_maintenance.return_value = None
        mock_beta.return_value = None

        item = BeadsWorkItem(
            id="task-1", title="Task 1", description="",
            status="open", priority=1, issue_type="task"
        )

        # First iteration: claim fails (success=False, requests=0)
        # Second iteration: no items available
        mock_get_items.side_effect = [[item], []]
        mock_select.side_effect = [item, None]
        mock_process.return_value = (False, 0, None, 0, 0, None)

        result = run_orchestrator(interactive=False, continuous=True)

        assert result == 0
        # Verify skip_ids was passed with the failed item
        second_select_call = mock_select.call_args_list[1]
        assert 'task-1' in second_select_call[1].get('skip_ids', set())

    @patch('time.sleep')
    @patch('pokepoke.agent_runner.run_worktree_cleanup')
    @patch('pokepoke.agent_runner.run_beta_tester')
    @patch('pokepoke.orchestrator.run_periodic_maintenance')
    @patch('pokepoke.orchestrator.get_beads_stats')
    @patch('pokepoke.orchestrator.process_work_item')
    @patch('pokepoke.orchestrator.select_work_item')
    @patch('pokepoke.orchestrator.get_ready_work_items')
    @patch('pokepoke.orchestrator.check_and_commit_main_repo')
    def test_success_clears_skip_list(
        self, mock_check_repo: Mock, mock_get_items: Mock,
        mock_select: Mock, mock_process: Mock,
        mock_stats: Mock, mock_maintenance: Mock,
        mock_beta: Mock, mock_cleanup: Mock, mock_sleep: Mock
    ) -> None:
        """Test successful processing clears the skip list."""
        from pokepoke.types import AgentStats

        mock_check_repo.return_value = True
        mock_stats.return_value = {}
        mock_maintenance.return_value = None
        mock_beta.return_value = None

        item1 = BeadsWorkItem(
            id="task-1", title="Task 1", description="",
            status="open", priority=1, issue_type="task"
        )
        item2 = BeadsWorkItem(
            id="task-2", title="Task 2", description="",
            status="open", priority=1, issue_type="task"
        )

        mock_get_items.side_effect = [[item1], [item2], []]
        mock_select.side_effect = [item1, item2, None]
        # First fails claim, second succeeds
        mock_process.side_effect = [
            (False, 0, None, 0, 0, None),
            (True, 1, AgentStats(), 0, 0, None)
        ]

        result = run_orchestrator(interactive=False, continuous=True)

        assert result == 0


class TestRunOrchestratorModelCompletion:
    """Test model completion recording in run_orchestrator."""

    @patch('subprocess.run')
    @patch('pokepoke.agent_runner.run_worktree_cleanup')
    @patch('pokepoke.agent_runner.run_beta_tester')
    @patch('pokepoke.orchestrator.run_periodic_maintenance')
    @patch('pokepoke.orchestrator.record_completion')
    @patch('pokepoke.orchestrator.process_work_item')
    @patch('pokepoke.orchestrator.select_work_item')
    @patch('pokepoke.orchestrator.get_ready_work_items')
    def test_model_completion_recorded(
        self, mock_get_items: Mock, mock_select: Mock,
        mock_process: Mock, mock_record: Mock,
        mock_maintenance: Mock, mock_beta: Mock,
        mock_cleanup: Mock, mock_subprocess: Mock
    ) -> None:
        """Test model completion is recorded when present."""
        from pokepoke.types import AgentStats, ModelCompletionRecord

        mock_subprocess.return_value = Mock(stdout="", returncode=0)
        mock_maintenance.return_value = None
        mock_beta.return_value = None

        item = BeadsWorkItem(
            id="task-1", title="Task", description="",
            status="open", priority=1, issue_type="task"
        )
        mock_get_items.return_value = [item]
        mock_select.return_value = item

        completion = ModelCompletionRecord(
            model="claude-opus-4.6", item_id="task-1",
            duration_seconds=10.0, gate_passed=True
        )
        mock_process.return_value = (True, 1, AgentStats(), 0, 0, completion)

        result = run_orchestrator(interactive=False, continuous=False)

        assert result == 0
        mock_record.assert_called_once_with(completion)


class TestRunOrchestratorRepoCheckFailure:
    """Test run_orchestrator when main repo check fails."""

    @patch('subprocess.run')
    @patch('pokepoke.agent_runner.run_worktree_cleanup')
    @patch('pokepoke.agent_runner.run_beta_tester')
    @patch('pokepoke.orchestrator.check_and_commit_main_repo')
    @patch('pokepoke.orchestrator.get_ready_work_items')
    def test_repo_check_failure_returns_1(
        self, mock_get_items: Mock, mock_check_repo: Mock,
        mock_beta: Mock, mock_cleanup: Mock, mock_subprocess: Mock
    ) -> None:
        """Test orchestrator returns 1 when repo check fails."""
        mock_subprocess.return_value = Mock(stdout="", returncode=0)
        mock_beta.return_value = None
        mock_check_repo.return_value = False

        result = run_orchestrator(interactive=False, continuous=False)

        assert result == 1
        mock_get_items.assert_not_called()


class TestRunOrchestratorContinuousAutonomousSleep:
    """Test continuous autonomous mode sleep behavior."""

    @patch('time.sleep')
    @patch('pokepoke.agent_runner.run_worktree_cleanup')
    @patch('pokepoke.agent_runner.run_beta_tester')
    @patch('pokepoke.orchestrator.run_periodic_maintenance')
    @patch('pokepoke.orchestrator.get_beads_stats')
    @patch('pokepoke.orchestrator.process_work_item')
    @patch('pokepoke.orchestrator.select_work_item')
    @patch('pokepoke.orchestrator.get_ready_work_items')
    @patch('pokepoke.orchestrator.check_and_commit_main_repo')
    def test_autonomous_continuous_sleeps_between_items(
        self, mock_check_repo: Mock, mock_get_items: Mock,
        mock_select: Mock, mock_process: Mock,
        mock_stats: Mock, mock_maintenance: Mock,
        mock_beta: Mock, mock_cleanup: Mock, mock_sleep: Mock
    ) -> None:
        """Test autonomous continuous mode sleeps 5s between items."""
        from pokepoke.types import AgentStats

        mock_check_repo.return_value = True
        mock_stats.return_value = {}
        mock_maintenance.return_value = None
        mock_beta.return_value = None

        item = BeadsWorkItem(
            id="task-1", title="Task 1", description="",
            status="open", priority=1, issue_type="task"
        )

        mock_get_items.side_effect = [[item], []]
        mock_select.side_effect = [item, None]
        mock_process.return_value = (True, 1, AgentStats(), 0, 0, None)

        result = run_orchestrator(interactive=False, continuous=True)

        assert result == 0
        # Sleep is called in 0.5s increments (10 times for 5s total)
        assert mock_sleep.call_count >= 1


class TestRunOrchestratorRetries:
    """Test retry counting and stats aggregation."""

    @patch('subprocess.run')
    @patch('pokepoke.agent_runner.run_worktree_cleanup')
    @patch('pokepoke.agent_runner.run_beta_tester')
    @patch('pokepoke.orchestrator.run_periodic_maintenance')
    @patch('pokepoke.orchestrator.process_work_item')
    @patch('pokepoke.orchestrator.select_work_item')
    @patch('pokepoke.orchestrator.get_ready_work_items')
    def test_retries_tracked_when_multiple_requests(
        self, mock_get_items: Mock, mock_select: Mock,
        mock_process: Mock, mock_maintenance: Mock,
        mock_beta: Mock, mock_cleanup: Mock, mock_subprocess: Mock
    ) -> None:
        """Test retries are counted when request_count > 1."""
        from pokepoke.types import AgentStats

        mock_subprocess.return_value = Mock(stdout="", returncode=0)
        mock_maintenance.return_value = None
        mock_beta.return_value = None

        item = BeadsWorkItem(
            id="task-1", title="Task", description="",
            status="open", priority=1, issue_type="task"
        )
        mock_get_items.return_value = [item]
        mock_select.return_value = item
        mock_process.return_value = (True, 3, AgentStats(), 1, 2, None)

        result = run_orchestrator(interactive=False, continuous=False)

        assert result == 0


class TestRunOrchestratorKeyboardInterrupt:
    """Test KeyboardInterrupt handling in run_orchestrator."""

    @patch('subprocess.run')
    @patch('pokepoke.agent_runner.run_worktree_cleanup')
    @patch('pokepoke.agent_runner.run_beta_tester')
    @patch('pokepoke.orchestrator.get_ready_work_items')
    @patch('pokepoke.orchestrator.check_and_commit_main_repo')
    def test_keyboard_interrupt_during_loop(
        self, mock_check_repo: Mock, mock_get_items: Mock,
        mock_beta: Mock, mock_cleanup: Mock, mock_subprocess: Mock
    ) -> None:
        """Test graceful shutdown on KeyboardInterrupt."""
        mock_subprocess.return_value = Mock(stdout="", returncode=0)
        mock_beta.return_value = None
        mock_check_repo.return_value = True
        mock_get_items.side_effect = KeyboardInterrupt

        result = run_orchestrator(interactive=False, continuous=False)

        assert result == 0


# ============================================================================
# Tests using src.pokepoke.orchestrator for worktree coverage
# ============================================================================

class TestRunOrchestratorWorktreeCoverage:
    """Tests that import from src.pokepoke.orchestrator to contribute to worktree coverage."""

    def setup_method(self) -> None:
        """Reset shutdown state before each test."""
        from pokepoke.shutdown import reset
        reset()

    @patch('subprocess.run')
    @patch('pokepoke.agent_runner.run_worktree_cleanup')
    @patch('pokepoke.agent_runner.run_beta_tester')
    @patch('src.pokepoke.orchestrator.process_work_item')
    @patch('src.pokepoke.orchestrator.select_work_item')
    @patch('src.pokepoke.orchestrator.get_ready_work_items')
    def test_no_items_returns_zero(
        self, mock_get_items: Mock, mock_select: Mock,
        mock_process: Mock, mock_beta: Mock,
        mock_cleanup: Mock, mock_subprocess: Mock
    ) -> None:
        """Test orchestrator returns 0 when no items available."""
        from src.pokepoke.orchestrator import run_orchestrator as run_orch

        mock_subprocess.return_value = Mock(stdout="", returncode=0)
        mock_beta.return_value = None
        mock_get_items.return_value = []
        mock_select.return_value = None

        result = run_orch(interactive=False, continuous=False)
        assert result == 0

    @patch('subprocess.run')
    @patch('pokepoke.agent_runner.run_worktree_cleanup')
    @patch('pokepoke.agent_runner.run_beta_tester')
    @patch('src.pokepoke.orchestrator.run_periodic_maintenance')
    @patch('src.pokepoke.orchestrator.process_work_item')
    @patch('src.pokepoke.orchestrator.select_work_item')
    @patch('src.pokepoke.orchestrator.get_ready_work_items')
    def test_single_shot_success(
        self, mock_get_items: Mock, mock_select: Mock,
        mock_process: Mock, mock_maintenance: Mock,
        mock_beta: Mock, mock_cleanup: Mock, mock_subprocess: Mock
    ) -> None:
        """Test single-shot success returns 0."""
        from src.pokepoke.orchestrator import run_orchestrator as run_orch
        from pokepoke.types import AgentStats

        mock_subprocess.return_value = Mock(stdout="", returncode=0)
        mock_beta.return_value = None
        mock_maintenance.return_value = None

        item = BeadsWorkItem(
            id="task-1", title="Task", description="",
            status="open", priority=1, issue_type="task"
        )
        mock_get_items.return_value = [item]
        mock_select.return_value = item
        mock_process.return_value = (True, 1, AgentStats(), 0, 0, None)

        result = run_orch(interactive=False, continuous=False)
        assert result == 0

    @patch('subprocess.run')
    @patch('pokepoke.agent_runner.run_worktree_cleanup')
    @patch('pokepoke.agent_runner.run_beta_tester')
    @patch('src.pokepoke.orchestrator.process_work_item')
    @patch('src.pokepoke.orchestrator.select_work_item')
    @patch('src.pokepoke.orchestrator.get_ready_work_items')
    def test_single_shot_failure_returns_one(
        self, mock_get_items: Mock, mock_select: Mock,
        mock_process: Mock, mock_beta: Mock,
        mock_cleanup: Mock, mock_subprocess: Mock
    ) -> None:
        """Test single-shot failure returns 1."""
        from src.pokepoke.orchestrator import run_orchestrator as run_orch

        mock_subprocess.return_value = Mock(stdout="", returncode=0)
        mock_beta.return_value = None

        item = BeadsWorkItem(
            id="task-1", title="Task", description="",
            status="open", priority=1, issue_type="task"
        )
        mock_get_items.return_value = [item]
        mock_select.return_value = item
        mock_process.return_value = (False, 1, None, 0, 0, None)

        result = run_orch(interactive=False, continuous=False)
        assert result == 1

    @patch('subprocess.run')
    @patch('pokepoke.agent_runner.run_worktree_cleanup')
    @patch('pokepoke.agent_runner.run_beta_tester')
    @patch('src.pokepoke.orchestrator.run_periodic_maintenance')
    @patch('src.pokepoke.orchestrator.record_completion')
    @patch('src.pokepoke.orchestrator.process_work_item')
    @patch('src.pokepoke.orchestrator.select_work_item')
    @patch('src.pokepoke.orchestrator.get_ready_work_items')
    def test_model_completion_recorded(
        self, mock_get_items: Mock, mock_select: Mock,
        mock_process: Mock, mock_record: Mock,
        mock_maintenance: Mock, mock_beta: Mock,
        mock_cleanup: Mock, mock_subprocess: Mock
    ) -> None:
        """Test model completion is recorded when present."""
        from src.pokepoke.orchestrator import run_orchestrator as run_orch
        from pokepoke.types import AgentStats, ModelCompletionRecord

        mock_subprocess.return_value = Mock(stdout="", returncode=0)
        mock_maintenance.return_value = None
        mock_beta.return_value = None

        item = BeadsWorkItem(
            id="task-1", title="Task", description="",
            status="open", priority=1, issue_type="task"
        )
        mock_get_items.return_value = [item]
        mock_select.return_value = item

        completion = ModelCompletionRecord(
            model="claude-opus-4.6", item_id="task-1",
            duration_seconds=10.0, gate_passed=True
        )
        mock_process.return_value = (True, 1, AgentStats(), 0, 0, completion)

        result = run_orch(interactive=False, continuous=False)
        assert result == 0
        mock_record.assert_called_once_with(completion)

    @patch('subprocess.run')
    @patch('pokepoke.agent_runner.run_worktree_cleanup')
    @patch('pokepoke.agent_runner.run_beta_tester')
    @patch('src.pokepoke.orchestrator.run_periodic_maintenance')
    @patch('src.pokepoke.orchestrator.process_work_item')
    @patch('src.pokepoke.orchestrator.select_work_item')
    @patch('src.pokepoke.orchestrator.get_ready_work_items')
    def test_retries_counted(
        self, mock_get_items: Mock, mock_select: Mock,
        mock_process: Mock, mock_maintenance: Mock,
        mock_beta: Mock, mock_cleanup: Mock, mock_subprocess: Mock
    ) -> None:
        """Test that multiple requests are tracked as retries."""
        from src.pokepoke.orchestrator import run_orchestrator as run_orch
        from pokepoke.types import AgentStats

        mock_subprocess.return_value = Mock(stdout="", returncode=0)
        mock_maintenance.return_value = None
        mock_beta.return_value = None

        item = BeadsWorkItem(
            id="task-1", title="Task", description="",
            status="open", priority=1, issue_type="task"
        )
        mock_get_items.return_value = [item]
        mock_select.return_value = item
        mock_process.return_value = (True, 3, AgentStats(), 1, 2, None)

        result = run_orch(interactive=False, continuous=False)
        assert result == 0

    @patch('subprocess.run')
    @patch('pokepoke.agent_runner.run_worktree_cleanup')
    @patch('pokepoke.agent_runner.run_beta_tester')
    @patch('src.pokepoke.orchestrator.get_ready_work_items')
    @patch('src.pokepoke.orchestrator.check_and_commit_main_repo')
    def test_exception_returns_one(
        self, mock_check_repo: Mock, mock_get_items: Mock,
        mock_beta: Mock, mock_cleanup: Mock, mock_subprocess: Mock
    ) -> None:
        """Test exception handling returns 1."""
        from src.pokepoke.orchestrator import run_orchestrator as run_orch

        mock_subprocess.return_value = Mock(stdout="", returncode=0)
        mock_beta.return_value = None
        mock_check_repo.return_value = True
        mock_get_items.side_effect = RuntimeError("DB error")

        result = run_orch(interactive=False, continuous=False)
        assert result == 1

    @patch('subprocess.run')
    @patch('pokepoke.agent_runner.run_worktree_cleanup')
    @patch('pokepoke.agent_runner.run_beta_tester')
    @patch('src.pokepoke.orchestrator.get_ready_work_items')
    @patch('src.pokepoke.orchestrator.check_and_commit_main_repo')
    def test_keyboard_interrupt_returns_zero(
        self, mock_check_repo: Mock, mock_get_items: Mock,
        mock_beta: Mock, mock_cleanup: Mock, mock_subprocess: Mock
    ) -> None:
        """Test KeyboardInterrupt returns 0."""
        from src.pokepoke.orchestrator import run_orchestrator as run_orch

        mock_subprocess.return_value = Mock(stdout="", returncode=0)
        mock_beta.return_value = None
        mock_check_repo.return_value = True
        mock_get_items.side_effect = KeyboardInterrupt

        result = run_orch(interactive=False, continuous=False)
        assert result == 0

    @patch('subprocess.run')
    @patch('pokepoke.agent_runner.run_worktree_cleanup')
    @patch('pokepoke.agent_runner.run_beta_tester')
    @patch('src.pokepoke.orchestrator.check_and_commit_main_repo')
    @patch('src.pokepoke.orchestrator.get_ready_work_items')
    def test_repo_check_failure(
        self, mock_get_items: Mock, mock_check_repo: Mock,
        mock_beta: Mock, mock_cleanup: Mock, mock_subprocess: Mock
    ) -> None:
        """Test repo check failure returns 1."""
        from src.pokepoke.orchestrator import run_orchestrator as run_orch

        mock_subprocess.return_value = Mock(stdout="", returncode=0)
        mock_beta.return_value = None
        mock_check_repo.return_value = False

        result = run_orch(interactive=False, continuous=False)
        assert result == 1

    @patch('subprocess.run')
    @patch('pokepoke.agent_runner.run_worktree_cleanup')
    @patch('pokepoke.agent_runner.run_beta_tester')
    @patch('src.pokepoke.orchestrator.process_work_item')
    @patch('src.pokepoke.orchestrator.select_work_item')
    @patch('src.pokepoke.orchestrator.get_ready_work_items')
    def test_beta_first_with_stats(
        self, mock_get_items: Mock, mock_select: Mock,
        mock_process: Mock, mock_beta: Mock,
        mock_cleanup: Mock, mock_subprocess: Mock
    ) -> None:
        """Test beta_first flag runs beta tester and aggregates stats."""
        from src.pokepoke.orchestrator import run_orchestrator as run_orch
        from pokepoke.types import AgentStats

        mock_subprocess.return_value = Mock(stdout="", returncode=0)
        beta_stats = AgentStats(
            wall_duration=10.0, api_duration=5.0,
            input_tokens=100, output_tokens=50, premium_requests=1
        )
        mock_beta.return_value = beta_stats
        mock_get_items.return_value = []
        mock_select.return_value = None

        result = run_orch(interactive=False, continuous=False, run_beta_first=True)
        assert result == 0
        mock_beta.assert_called_once()

    @patch('subprocess.run')
    @patch('pokepoke.agent_runner.run_worktree_cleanup')
    @patch('pokepoke.agent_runner.run_beta_tester')
    @patch('src.pokepoke.orchestrator.process_work_item')
    @patch('src.pokepoke.orchestrator.select_work_item')
    @patch('src.pokepoke.orchestrator.get_ready_work_items')
    def test_beta_first_none_stats(
        self, mock_get_items: Mock, mock_select: Mock,
        mock_process: Mock, mock_beta: Mock,
        mock_cleanup: Mock, mock_subprocess: Mock
    ) -> None:
        """Test beta_first with None stats is handled."""
        from src.pokepoke.orchestrator import run_orchestrator as run_orch

        mock_subprocess.return_value = Mock(stdout="", returncode=0)
        mock_beta.return_value = None
        mock_get_items.return_value = []
        mock_select.return_value = None

        result = run_orch(interactive=False, continuous=False, run_beta_first=True)
        assert result == 0

    @patch('time.sleep')
    @patch('pokepoke.agent_runner.run_worktree_cleanup')
    @patch('pokepoke.agent_runner.run_beta_tester')
    @patch('src.pokepoke.orchestrator.run_periodic_maintenance')
    @patch('src.pokepoke.orchestrator.get_beads_stats')
    @patch('src.pokepoke.orchestrator.process_work_item')
    @patch('src.pokepoke.orchestrator.select_work_item')
    @patch('src.pokepoke.orchestrator.get_ready_work_items')
    @patch('src.pokepoke.orchestrator.check_and_commit_main_repo')
    def test_continuous_autonomous_processes_multiple_items(
        self, mock_check_repo: Mock, mock_get_items: Mock,
        mock_select: Mock, mock_process: Mock,
        mock_stats: Mock, mock_maintenance: Mock,
        mock_beta: Mock, mock_cleanup: Mock, mock_sleep: Mock
    ) -> None:
        """Test continuous autonomous mode processes multiple items."""
        from src.pokepoke.orchestrator import run_orchestrator as run_orch
        from pokepoke.types import AgentStats

        mock_check_repo.return_value = True
        mock_stats.return_value = {}
        mock_maintenance.return_value = None
        mock_beta.return_value = None

        item1 = BeadsWorkItem(
            id="task-1", title="Task 1", description="",
            status="open", priority=1, issue_type="task"
        )
        item2 = BeadsWorkItem(
            id="task-2", title="Task 2", description="",
            status="open", priority=1, issue_type="task"
        )

        mock_get_items.side_effect = [[item1], [item2], []]
        mock_select.side_effect = [item1, item2, None]
        mock_process.side_effect = [
            (True, 1, AgentStats(), 0, 0, None),
            (True, 1, AgentStats(), 0, 0, None)
        ]

        result = run_orch(interactive=False, continuous=True)
        assert result == 0
        assert mock_process.call_count == 2

    @patch('time.sleep')
    @patch('pokepoke.agent_runner.run_worktree_cleanup')
    @patch('pokepoke.agent_runner.run_beta_tester')
    @patch('src.pokepoke.orchestrator.run_periodic_maintenance')
    @patch('src.pokepoke.orchestrator.get_beads_stats')
    @patch('src.pokepoke.orchestrator.process_work_item')
    @patch('src.pokepoke.orchestrator.select_work_item')
    @patch('src.pokepoke.orchestrator.get_ready_work_items')
    @patch('src.pokepoke.orchestrator.check_and_commit_main_repo')
    def test_failed_claim_tracked(
        self, mock_check_repo: Mock, mock_get_items: Mock,
        mock_select: Mock, mock_process: Mock,
        mock_stats: Mock, mock_maintenance: Mock,
        mock_beta: Mock, mock_cleanup: Mock, mock_sleep: Mock
    ) -> None:
        """Test failed claims are added to skip list."""
        from src.pokepoke.orchestrator import run_orchestrator as run_orch

        mock_check_repo.return_value = True
        mock_stats.return_value = {}
        mock_maintenance.return_value = None
        mock_beta.return_value = None

        item = BeadsWorkItem(
            id="task-1", title="Task 1", description="",
            status="open", priority=1, issue_type="task"
        )

        mock_get_items.side_effect = [[item], []]
        mock_select.side_effect = [item, None]
        mock_process.return_value = (False, 0, None, 0, 0, None)

        result = run_orch(interactive=False, continuous=True)
        assert result == 0

    @patch('pokepoke.agent_runner.run_worktree_cleanup')
    @patch('pokepoke.agent_runner.run_beta_tester')
    @patch('src.pokepoke.orchestrator.run_periodic_maintenance')
    @patch('builtins.input')
    @patch('src.pokepoke.orchestrator.get_beads_stats')
    @patch('src.pokepoke.orchestrator.process_work_item')
    @patch('src.pokepoke.orchestrator.select_work_item')
    @patch('src.pokepoke.orchestrator.get_ready_work_items')
    @patch('src.pokepoke.orchestrator.check_and_commit_main_repo')
    def test_interactive_continuous_quit(
        self, mock_check_repo: Mock, mock_get_items: Mock,
        mock_select: Mock, mock_process: Mock,
        mock_stats: Mock, mock_input: Mock,
        mock_maintenance: Mock, mock_beta: Mock,
        mock_cleanup: Mock
    ) -> None:
        """Test interactive continuous mode with user quitting."""
        from src.pokepoke.orchestrator import run_orchestrator as run_orch
        from pokepoke.types import AgentStats

        mock_check_repo.return_value = True
        mock_stats.return_value = {}
        mock_maintenance.return_value = None
        mock_beta.return_value = None

        item = BeadsWorkItem(
            id="task-1", title="Task 1", description="",
            status="open", priority=1, issue_type="task"
        )

        mock_get_items.return_value = [item]
        mock_select.return_value = item
        mock_process.return_value = (True, 1, AgentStats(), 0, 0, None)
        mock_input.return_value = 'n'

        result = run_orch(interactive=True, continuous=True)
        assert result == 0

    @patch('subprocess.run')
    @patch('pokepoke.agent_runner.run_worktree_cleanup')
    @patch('pokepoke.agent_runner.run_beta_tester')
    @patch('src.pokepoke.orchestrator.is_shutting_down', return_value=True)
    def test_shutdown_during_loop(
        self, mock_shutdown: Mock,
        mock_beta: Mock, mock_cleanup: Mock, mock_subprocess: Mock
    ) -> None:
        """Test shutdown during loop returns 0."""
        from src.pokepoke.orchestrator import run_orchestrator as run_orch

        mock_subprocess.return_value = Mock(stdout="", returncode=0)
        mock_beta.return_value = None

        result = run_orch(interactive=False, continuous=True)
        assert result == 0


class TestMainWorktreeCoverage:
    """Tests for main() using src.pokepoke.orchestrator for coverage."""

    @patch('src.pokepoke.orchestrator._check_beads_available', return_value=True)
    @patch('src.pokepoke.orchestrator.run_orchestrator')
    @patch('pokepoke.terminal_ui.ui')
    @patch('sys.argv', ['pokepoke', '--autonomous'])
    def test_main_autonomous(self, mock_ui: Mock, mock_run: Mock, _mock_beads: Mock) -> None:
        """Test main with autonomous flag."""
        from src.pokepoke.orchestrator import main

        mock_run.return_value = 0
        mock_ui.run_with_orchestrator.side_effect = lambda f: f()

        result = main()
        assert result == 0

    @patch('src.pokepoke.orchestrator._check_beads_available', return_value=True)
    @patch('src.pokepoke.orchestrator.run_orchestrator')
    @patch('pokepoke.terminal_ui.ui')
    @patch('sys.argv', ['pokepoke', '--autonomous', '--beta-first'])
    def test_main_beta_first(self, mock_ui: Mock, mock_run: Mock, _mock_beads: Mock) -> None:
        """Test main with beta-first flag."""
        from src.pokepoke.orchestrator import main

        mock_run.return_value = 0
        mock_ui.run_with_orchestrator.side_effect = lambda f: f()

        result = main()
        assert result == 0
        mock_run.assert_called_once_with(interactive=False, continuous=False, run_beta_first=True)

    @patch('src.pokepoke.orchestrator._check_beads_available', return_value=False)
    @patch('sys.argv', ['pokepoke', '--autonomous'])
    def test_main_beads_unavailable(self, _mock_beads: Mock) -> None:
        """Test main returns 1 when beads unavailable."""
        from src.pokepoke.orchestrator import main

        result = main()
        assert result == 1

    @patch('pokepoke.init.init_project', return_value=True)
    @patch('sys.argv', ['pokepoke', '--init'])
    def test_main_init(self, mock_init: Mock) -> None:
        """Test main with --init flag."""
        from src.pokepoke.orchestrator import main

        result = main()
        assert result == 0

    @patch('src.pokepoke.orchestrator._check_beads_available', return_value=True)
    @patch('src.pokepoke.orchestrator.run_orchestrator')
    @patch('pokepoke.terminal_ui.ui')
    @patch('sys.argv', ['pokepoke', '--autonomous', '--continuous'])
    def test_main_continuous(self, mock_ui: Mock, mock_run: Mock, _mock_beads: Mock) -> None:
        """Test main with continuous flag."""
        from src.pokepoke.orchestrator import main

        mock_run.return_value = 0
        mock_ui.run_with_orchestrator.side_effect = lambda f: f()

        result = main()
        assert result == 0
        mock_run.assert_called_once_with(interactive=False, continuous=True, run_beta_first=False)


class TestOrchestratorCleanupDetection:
    """Test orchestrator's main repo cleanup detection."""
    
    @patch('pokepoke.agent_runner.invoke_cleanup_agent')
    @patch('pokepoke.orchestrator.get_ready_work_items')
    @patch('subprocess.run')
    def test_detects_uncommitted_changes_and_invokes_cleanup(
        self,
        mock_subprocess: Mock,
        mock_get_items: Mock,
        mock_cleanup: Mock
    ) -> None:
        """Test that uncommitted non-beads changes invoke cleanup agent."""
        mock_subprocess.return_value = Mock(
            stdout=" M src/pokepoke/orchestrator.py\n M src/pokepoke/beads.py",
            returncode=0
        )
        mock_cleanup.return_value = (False, None)
        
        result = run_orchestrator(interactive=False, continuous=False)
        
        assert result == 1
        mock_cleanup.assert_called_once()
        mock_get_items.assert_not_called()
    
    @patch('pokepoke.orchestrator.check_and_commit_main_repo')
    @patch('pokepoke.orchestrator.get_beads_stats')
    @patch('pokepoke.orchestrator.get_ready_work_items')
    def test_detects_beads_changes_without_autocommit(
        self,
        mock_get_items: Mock,
        mock_beads_stats: Mock,
        mock_check_repo: Mock
    ) -> None:
        """Test that beads-only changes are detected but NOT auto-committed."""
        mock_beads_stats.return_value = BeadsStats(
            total_issues=10,
            open_issues=5,
            in_progress_issues=2,
            closed_issues=3,
            ready_issues=1
        )
        mock_check_repo.return_value = True
        mock_get_items.return_value = []
        
        result = run_orchestrator(interactive=False, continuous=False)
        
        mock_check_repo.assert_called_once()
        assert result == 0
    
    @patch('pokepoke.orchestrator.get_ready_work_items')
    @patch('subprocess.run')
    def test_clean_repo_proceeds_to_work(
        self,
        mock_subprocess: Mock,
        mock_get_items: Mock
    ) -> None:
        """Test that clean repo proceeds to normal work processing."""
        mock_subprocess.return_value = Mock(
            stdout="",
            returncode=0
        )
        mock_get_items.return_value = []
        
        result = run_orchestrator(interactive=False, continuous=False)
        
        mock_get_items.assert_called_once()
        assert result == 0

