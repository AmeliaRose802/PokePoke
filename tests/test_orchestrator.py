"""Unit tests for orchestrator module."""

import sys
from unittest.mock import Mock, patch, call
import pytest

from src.pokepoke.orchestrator import run_orchestrator
from src.pokepoke.workflow import select_work_item, process_work_item
from src.pokepoke.types import BeadsWorkItem, CopilotResult


class TestSelectWorkItem:
    """Test work item selection logic."""
    
    def test_select_work_item_empty_list(self) -> None:
        """Test selecting from empty list returns None."""
        result = select_work_item([], interactive=False)
        
        assert result is None
    
    @patch('src.pokepoke.workflow.select_next_hierarchical_item')
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
    
    @pytest.mark.xfail(sys.platform == "win32", reason="Windows Unicode encoding issue - tracked in PokePoke-oel")
    @patch('src.pokepoke.beads.close_parent_if_complete')
    @patch('src.pokepoke.beads.get_parent_id')
    @patch('src.pokepoke.workflow.close_item')  # Patch where it's used
    @patch('subprocess.run')
    @patch('src.pokepoke.worktrees.cleanup_worktree')
    @patch('src.pokepoke.workflow.merge_worktree')
    @patch('src.pokepoke.workflow.check_main_repo_ready_for_merge')
    @patch('src.pokepoke.agent_runner.has_uncommitted_changes')
    @patch('os.chdir')
    @patch('os.getcwd')
    @patch('src.pokepoke.workflow.create_worktree')
    @patch('src.pokepoke.workflow.invoke_copilot_cli')
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
                    # Return open status so close_item will be called
                    return Mock(stdout='{"status": "open"}', returncode=0)
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
        mock_close.assert_called_once_with("task-1", "Completed by PokePoke orchestrator")
    
    @pytest.mark.xfail(sys.platform == "win32", reason="Windows Unicode encoding issue - tracked in PokePoke-oel")
    @patch('src.pokepoke.beads.close_parent_if_complete')
    @patch('src.pokepoke.beads.get_parent_id')
    @patch('src.pokepoke.workflow.close_item')  # Patch where it's used
    @patch('subprocess.run')
    @patch('src.pokepoke.worktrees.cleanup_worktree')
    @patch('src.pokepoke.workflow.merge_worktree')
    @patch('src.pokepoke.workflow.check_main_repo_ready_for_merge')
    @patch('src.pokepoke.agent_runner.has_uncommitted_changes')
    @patch('os.chdir')
    @patch('os.getcwd')
    @patch('src.pokepoke.workflow.create_worktree')
    @patch('src.pokepoke.workflow.invoke_copilot_cli')
    def test_process_work_item_success_with_parent(
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
        mock_uncommitted.return_value = False
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
                    # Return open status so close_item will be called
                    return Mock(stdout='{"status": "open"}', returncode=0)
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
    
    @pytest.mark.xfail(sys.platform == "win32", reason="Windows Unicode encoding issue - tracked in PokePoke-oel")
    @patch('src.pokepoke.worktrees.cleanup_worktree')
    @patch('os.chdir')
    @patch('os.getcwd')
    @patch('src.pokepoke.workflow.create_worktree')
    @patch('src.pokepoke.workflow.invoke_copilot_cli')
    def test_process_work_item_failure(
        self,
        mock_invoke: Mock,
        mock_create_wt: Mock,
        mock_getcwd: Mock,
        mock_chdir: Mock,
        mock_cleanup: Mock
    ) -> None:
        """Test processing failure."""
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
        mock_invoke.return_value = CopilotResult(
            work_item_id="task-1",
            success=False,
            error="Something went wrong",
            attempt_count=1
        )
        
        result = process_work_item(item, interactive=False)
        
        success, request_count, stats, cleanup_runs = result
        assert success == False
        assert request_count == 1
        assert stats is None
        assert cleanup_runs == 0
    
    @patch('src.pokepoke.workflow.invoke_copilot_cli')
    @patch('builtins.input')
    def test_process_work_item_interactive_skip(
        self,
        mock_input: Mock,
        mock_invoke: Mock
    ) -> None:
        """Test skipping item in interactive mode."""
        item = BeadsWorkItem(
            id="task-1",
            title="Task",
            description="",
            status="open",
            priority=1,
            issue_type="task"
        )
        mock_input.return_value = 'n'
        
        result = process_work_item(item, interactive=True)
        
        success, request_count, stats, cleanup_runs = result
        assert success == False
        assert request_count == 0
        assert stats is None
        assert cleanup_runs == 0
        mock_invoke.assert_not_called()


class TestRunOrchestrator:
    """Test orchestrator main loop."""
    
    @patch('subprocess.run')  # Mock git status check
    @patch('src.pokepoke.orchestrator.process_work_item')
    @patch('src.pokepoke.orchestrator.select_work_item')
    @patch('src.pokepoke.orchestrator.get_ready_work_items')
    def test_run_orchestrator_no_items(
        self,
        mock_get_items: Mock,
        mock_select: Mock,
        mock_process: Mock,
        mock_subprocess_run: Mock
    ) -> None:
        """Test orchestrator with no ready items."""
        # Mock git status to return clean repo
        mock_subprocess_run.return_value = Mock(stdout="", returncode=0)
        
        mock_get_items.return_value = []
        mock_select.return_value = None
        
        result = run_orchestrator(interactive=False, continuous=False)
        
        assert result == 0
        mock_process.assert_not_called()
    
    @patch('subprocess.run')  # Mock git status check
    @patch('src.pokepoke.orchestrator.process_work_item')
    @patch('src.pokepoke.orchestrator.select_work_item')
    @patch('src.pokepoke.orchestrator.get_ready_work_items')
    def test_run_orchestrator_single_shot_success(
        self,
        mock_get_items: Mock,
        mock_select: Mock,
        mock_process: Mock,
        mock_subprocess_run: Mock
    ) -> None:
        """Test single-shot mode with successful processing."""
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
        mock_process.return_value = (True, 1, None, 0)  # 4-tuple: success, request_count, stats, cleanup_runs
        
        result = run_orchestrator(interactive=False, continuous=False)
        
        assert result == 0
        mock_process.assert_called_once()
    
    @patch('subprocess.run')  # Mock git status check
    @patch('src.pokepoke.orchestrator.process_work_item')
    @patch('src.pokepoke.orchestrator.select_work_item')
    @patch('src.pokepoke.orchestrator.get_ready_work_items')
    def test_run_orchestrator_single_shot_failure(
        self,
        mock_get_items: Mock,
        mock_select: Mock,
        mock_process: Mock,
        mock_subprocess_run: Mock
    ) -> None:
        """Test single-shot mode with processing failure."""
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
    @patch('src.pokepoke.orchestrator.process_work_item')
    @patch('src.pokepoke.orchestrator.select_work_item')
    @patch('src.pokepoke.orchestrator.get_ready_work_items')
    def test_run_orchestrator_continuous_quit(
        self,
        mock_get_items: Mock,
        mock_select: Mock,
        mock_process: Mock,
        mock_input: Mock,
        mock_subprocess_run: Mock
    ) -> None:
        """Test continuous interactive mode with user quit."""
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
        mock_process.return_value = (True, 1, None, 0)  # 4-tuple: success, request_count, stats, cleanup_runs
        mock_input.return_value = 'n'  # Don't continue
        
        result = run_orchestrator(interactive=True, continuous=True)
        
        assert result == 0
        mock_process.assert_called_once()
    
    @patch('subprocess.run')  # Mock git status check
    @patch('src.pokepoke.orchestrator.process_work_item')
    @patch('src.pokepoke.orchestrator.select_work_item')
    @patch('src.pokepoke.orchestrator.get_ready_work_items')
    def test_run_orchestrator_exception_handling(
        self,
        mock_get_items: Mock,
        mock_select: Mock,
        mock_process: Mock,
        mock_subprocess_run: Mock
    ) -> None:
        """Test orchestrator handles exceptions."""
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
        from src.pokepoke.git_operations import check_main_repo_ready_for_merge
        
        mock_subprocess.return_value = Mock(stdout="")
        is_ready, error = check_main_repo_ready_for_merge()
        
        assert is_ready == True
        assert error == ""
    
    @patch('subprocess.run')
    def test_beads_only_changes(self, mock_subprocess: Mock) -> None:
        """Test beads-only changes are auto-committed."""
        from src.pokepoke.git_operations import check_main_repo_ready_for_merge
        
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
        from src.pokepoke.git_operations import check_main_repo_ready_for_merge
        
        mock_subprocess.return_value = Mock(stdout="M src/file.py\nM .beads/issues.jsonl\n")
        is_ready, error = check_main_repo_ready_for_merge()
        
        assert is_ready == False
        assert "src/file.py" in error
        # Should only call git status once, not attempt to commit
        assert mock_subprocess.call_count == 1
    
    @patch('subprocess.run')
    def test_subprocess_error(self, mock_subprocess: Mock) -> None:
        """Test subprocess error is handled."""
        from src.pokepoke.git_operations import check_main_repo_ready_for_merge
        
        mock_subprocess.side_effect = Exception("git command failed")
        is_ready, error = check_main_repo_ready_for_merge()
        
        assert is_ready == False
        assert "git command failed" in error
