"""Unit tests for workflow module."""

import subprocess
import time
from pathlib import Path
from unittest.mock import Mock, patch, call
import pytest

from pokepoke.workflow import (
    select_work_item,
    process_work_item,
    _setup_worktree,
    _run_cleanup_with_timeout
)
from pokepoke.work_item_selection import (
    interactive_selection,
    autonomous_selection
)
from pokepoke.worktree_finalization import (
    finalize_work_item,
    check_and_merge_worktree,
    merge_worktree_to_dev,
    close_work_item_and_parents,
    check_parent_hierarchy
)
from pokepoke.types import BeadsWorkItem, CopilotResult, AgentStats


class TestSelectWorkItem:
    """Test select_work_item function."""
    
    def test_empty_list(self) -> None:
        """Test with empty work item list."""
        result = select_work_item([], interactive=False)
        
        assert result is None
    
    @patch('pokepoke.work_item_selection.select_next_hierarchical_item')
    def test_autonomous_selection(self, mock_select: Mock) -> None:
        """Test autonomous mode selection."""
        items = [
            BeadsWorkItem(
                id="task-1",
                title="Task 1",
                description="",
                status="open",
                priority=1,
                issue_type="task"
            )
        ]
        mock_select.return_value = items[0]
        
        result = select_work_item(items, interactive=False)
        
        assert result is not None
        assert result.id == "task-1"
        # Should have passed the full list (no filtering since no items assigned to others)
        mock_select.assert_called_once()
    
    @patch('builtins.input')
    def test_interactive_selection(self, mock_input: Mock) -> None:
        """Test interactive mode selection."""
        items = [
            BeadsWorkItem(
                id="task-1",
                title="Task 1",
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
    
    @patch('pokepoke.work_item_selection.select_next_hierarchical_item')
    def test_filters_items_assigned_to_others(self, mock_select: Mock) -> None:
        """Test that items assigned to other agents are filtered out."""
        import os
        os.environ['AGENT_NAME'] = 'agent_alpha'
        
        items = [
            BeadsWorkItem(
                id="task-1",
                title="Task assigned to other agent",
                description="",
                status="in_progress",
                priority=1,
                issue_type="task",
                assignee="agent_beta"  # Assigned to different agent
            ),
            BeadsWorkItem(
                id="task-2",
                title="Task available",
                description="",
                status="open",
                priority=2,
                issue_type="task",
                assignee=None  # Unassigned
            )
        ]
        mock_select.return_value = items[1]
        
        result = select_work_item(items, interactive=False)
        
        # Should have filtered out task-1 and only passed task-2
        mock_select.assert_called_once()
        passed_items = mock_select.call_args[0][0]
        assert len(passed_items) == 1
        assert passed_items[0].id == "task-2"
        assert result is not None
        assert result.id == "task-2"
    
    def test_all_items_assigned_to_others(self) -> None:
        """Test when all items are assigned to other agents."""
        import os
        os.environ['AGENT_NAME'] = 'agent_alpha'
        
        items = [
            BeadsWorkItem(
                id="task-1",
                title="Task assigned to beta",
                description="",
                status="in_progress",
                priority=1,
                issue_type="task",
                assignee="agent_beta"
            ),
            BeadsWorkItem(
                id="task-2",
                title="Task assigned to gamma",
                description="",
                status="in_progress",
                priority=2,
                issue_type="task",
                assignee="agent_gamma"
            )
        ]
        
        result = select_work_item(items, interactive=False)
        
        # Should return None since all items are assigned to others
        assert result is None


class TestInteractiveSelection:
    """Test interactive_selection function."""
    
    @patch('builtins.input')
    def test_valid_selection(self, mock_input: Mock) -> None:
        """Test valid item selection."""
        items = [
            BeadsWorkItem(
                id="task-1",
                title="Task 1",
                description="",
                status="open",
                priority=1,
                issue_type="task"
            ),
            BeadsWorkItem(
                id="task-2",
                title="Task 2",
                description="",
                status="open",
                priority=2,
                issue_type="task"
            )
        ]
        mock_input.return_value = '2'
        
        result = interactive_selection(items)
        
        assert result is not None
        assert result.id == "task-2"
    
    @patch('builtins.input')
    def test_quit_selection(self, mock_input: Mock) -> None:
        """Test quit option."""
        items = [
            BeadsWorkItem(
                id="task-1",
                title="Task 1",
                description="",
                status="open",
                priority=1,
                issue_type="task"
            )
        ]
        mock_input.return_value = 'q'
        
        result = interactive_selection(items)
        
        assert result is None
    
    @patch('builtins.input')
    def test_invalid_then_valid(self, mock_input: Mock) -> None:
        """Test invalid input followed by valid input."""
        items = [
            BeadsWorkItem(
                id="task-1",
                title="Task 1",
                description="",
                status="open",
                priority=1,
                issue_type="task"
            )
        ]
        mock_input.side_effect = ['invalid', '1']
        
        result = interactive_selection(items)
        
        assert result is not None
        assert result.id == "task-1"
    
    @patch('builtins.input')
    def test_out_of_range_then_valid(self, mock_input: Mock) -> None:
        """Test out of range input followed by valid input."""
        items = [
            BeadsWorkItem(
                id="task-1",
                title="Task 1",
                description="",
                status="open",
                priority=1,
                issue_type="task"
            )
        ]
        mock_input.side_effect = ['99', '1']
        
        result = interactive_selection(items)
        
        assert result is not None
        assert result.id == "task-1"
    
    @patch('builtins.input')
    def test_keyboard_interrupt(self, mock_input: Mock) -> None:
        """Test keyboard interrupt during selection."""
        items = [
            BeadsWorkItem(
                id="task-1",
                title="Task 1",
                description="",
                status="open",
                priority=1,
                issue_type="task"
            )
        ]
        mock_input.side_effect = KeyboardInterrupt()
        
        result = interactive_selection(items)
        
        assert result is None


class TestAutonomousSelection:
    """Test autonomous_selection function."""
    
    @patch('pokepoke.work_item_selection.select_next_hierarchical_item')
    def test_item_selected(self, mock_select: Mock) -> None:
        """Test successful hierarchical selection."""
        items = [
            BeadsWorkItem(
                id="task-1",
                title="Task 1",
                description="",
                status="open",
                priority=1,
                issue_type="task"
            )
        ]
        mock_select.return_value = items[0]
        
        result = autonomous_selection(items)
        
        assert result is not None
        assert result.id == "task-1"
    
    @patch('pokepoke.work_item_selection.select_next_hierarchical_item')
    def test_no_item_selected(self, mock_select: Mock) -> None:
        """Test when no item is selected."""
        items = [
            BeadsWorkItem(
                id="task-1",
                title="Task 1",
                description="",
                status="open",
                priority=1,
                issue_type="task"
            )
        ]
        mock_select.return_value = None
        
        result = autonomous_selection(items)
        
        assert result is None


class TestSetupWorktree:
    """Test _setup_worktree function."""
    
    @patch('pokepoke.workflow.create_worktree')
    def test_successful_setup(self, mock_create: Mock) -> None:
        """Test successful worktree creation."""
        item = BeadsWorkItem(
            id="task-1",
            title="Task 1",
            description="",
            status="open",
            priority=1,
            issue_type="task"
        )
        mock_create.return_value = Path("/fake/worktree")
        
        result = _setup_worktree(item)
        
        assert result is not None
        assert result == Path("/fake/worktree")
        mock_create.assert_called_once_with("task-1")
    
    @patch('pokepoke.workflow.create_worktree')
    def test_creation_failure(self, mock_create: Mock) -> None:
        """Test worktree creation failure."""
        item = BeadsWorkItem(
            id="task-1",
            title="Task 1",
            description="",
            status="open",
            priority=1,
            issue_type="task"
        )
        mock_create.side_effect = Exception("Failed to create worktree")
        
        result = _setup_worktree(item)
        
        assert result is None


class TestRunCleanupWithTimeout:
    """Test _run_cleanup_with_timeout function."""
    
    @patch('pokepoke.workflow.run_cleanup_loop')
    @patch('pokepoke.workflow.has_uncommitted_changes')
    @patch('time.time')
    def test_no_uncommitted_changes(
        self, 
        mock_time: Mock, 
        mock_uncommitted: Mock, 
        mock_cleanup: Mock
    ) -> None:
        """Test when no uncommitted changes exist."""
        item = BeadsWorkItem(
            id="task-1",
            title="Task 1",
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
        
        mock_time.return_value = 0
        mock_uncommitted.return_value = False
        
        success, cleanup_runs = _run_cleanup_with_timeout(
            item, result, repo_root, 0, 7200, 2.0
        )
        
        assert success is True
        assert cleanup_runs == 0
        mock_cleanup.assert_not_called()
    
    @patch('pokepoke.workflow.run_cleanup_loop')
    @patch('pokepoke.workflow.has_uncommitted_changes')
    @patch('time.time')
    def test_cleanup_success(
        self, 
        mock_time: Mock, 
        mock_uncommitted: Mock, 
        mock_cleanup: Mock
    ) -> None:
        """Test successful cleanup."""
        item = BeadsWorkItem(
            id="task-1",
            title="Task 1",
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
        
        mock_time.return_value = 0
        mock_uncommitted.side_effect = [True, False]
        mock_cleanup.return_value = (True, 1)
        
        success, cleanup_runs = _run_cleanup_with_timeout(
            item, result, repo_root, 0, 7200, 2.0
        )
        
        assert success is True
        assert cleanup_runs == 1
        mock_cleanup.assert_called_once()
    
    @patch('pokepoke.workflow.run_cleanup_loop')
    @patch('pokepoke.workflow.has_uncommitted_changes')
    @patch('time.time')
    def test_timeout_during_cleanup(
        self, 
        mock_time: Mock, 
        mock_uncommitted: Mock, 
        mock_cleanup: Mock
    ) -> None:
        """Test timeout during cleanup loop."""
        item = BeadsWorkItem(
            id="task-1",
            title="Task 1",
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
        
        # First check: has changes, second check: past timeout
        # The while loop enters, then checks timeout AFTER cleanup_attempt++
        # So cleanup_loop will be called once before timeout check
        mock_time.side_effect = [0, 7300]  # first check within timeout, second check past timeout
        mock_uncommitted.return_value = True  # Always has changes
        mock_cleanup.return_value = (True, 1)  # Cleanup succeeds
        
        success, cleanup_runs = _run_cleanup_with_timeout(
            item, result, repo_root, 0, 7200, 2.0
        )
        
        assert success is False  # Timeout occurred
        assert cleanup_runs == 1  # One cleanup was attempted before timeout
        mock_cleanup.assert_called_once()  # Cleanup called once before timeout
    
    @patch('pokepoke.workflow.run_cleanup_loop')
    @patch('pokepoke.workflow.has_uncommitted_changes')
    @patch('time.time')
    def test_cleanup_failure(
        self, 
        mock_time: Mock, 
        mock_uncommitted: Mock, 
        mock_cleanup: Mock
    ) -> None:
        """Test cleanup failure."""
        item = BeadsWorkItem(
            id="task-1",
            title="Task 1",
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
        
        mock_time.return_value = 0
        mock_uncommitted.side_effect = [True, False]  # Has changes, then no changes
        mock_cleanup.return_value = (False, 1)
        
        success, cleanup_runs = _run_cleanup_with_timeout(
            item, result, repo_root, 0, 7200, 2.0
        )
        
        # Cleanup failed, but loop exits when no more uncommitted changes
        # result.success is still True, so function returns True
        # The cleanup failure is only reflected in the break from loop
        assert success is True  # result.success wasn't modified
        assert cleanup_runs == 1


class TestFinalizeWorkItem:
    """Test finalize_work_item function."""
    
    @patch('pokepoke.worktree_finalization.close_work_item_and_parents')
    @patch('pokepoke.worktree_finalization.check_and_merge_worktree')
    def test_finalize_returns_false_when_merge_fails(self, mock_merge: Mock, mock_close: Mock) -> None:
        """Test finalize returns False when check_and_merge_worktree fails."""
        item = BeadsWorkItem(id="task-1", title="Task", description="", status="open", priority=1, issue_type="task")
        mock_merge.return_value = False
        
        result = finalize_work_item(item, Path("/fake/worktree"))
        
        assert result is False
        mock_close.assert_not_called()


class TestCheckAndMergeWorktree:
    """Test check_and_merge_worktree function."""
    
    @patch('pokepoke.worktree_finalization.merge_worktree_to_dev')
    @patch('pokepoke.worktree_finalization.cleanup_worktree')
    @patch('subprocess.run')
    def test_no_commits_to_merge(
        self, 
        mock_run: Mock, 
        mock_cleanup: Mock, 
        mock_merge: Mock
    ) -> None:
        """Test when worktree has no commits to merge."""
        item = BeadsWorkItem(
            id="task-1",
            title="Task 1",
            description="",
            status="open",
            priority=1,
            issue_type="task"
        )
        worktree_path = Path("/fake/worktree")
        
        mock_run.return_value = Mock(stdout="0\n", returncode=0)
        
        result = check_and_merge_worktree(item, worktree_path)
        
        assert result is True
        mock_cleanup.assert_called_once_with("task-1", force=True)
        mock_merge.assert_not_called()
        # Verify cwd is passed to subprocess instead of os.chdir
        cwd_calls = [c for c in mock_run.call_args_list if c.kwargs.get('cwd')]
        assert len(cwd_calls) == 1
        assert cwd_calls[0].kwargs['cwd'] == str(worktree_path)
    
    @patch('pokepoke.worktree_finalization.merge_worktree_to_dev')
    @patch('subprocess.run')
    def test_has_commits_to_merge(
        self, 
        mock_run: Mock, 
        mock_merge: Mock
    ) -> None:
        """Test when worktree has commits to merge."""
        item = BeadsWorkItem(
            id="task-1",
            title="Task 1",
            description="",
            status="open",
            priority=1,
            issue_type="task"
        )
        worktree_path = Path("/fake/worktree")
        
        mock_run.return_value = Mock(stdout="3\n", returncode=0)
        mock_merge.return_value = True  # merge_worktree_to_dev returns bool, not tuple
        
        result = check_and_merge_worktree(item, worktree_path)
        
        assert result is True
        mock_merge.assert_called_once_with(item)
    
    @patch('pokepoke.worktree_finalization.merge_worktree_to_dev')
    @patch('subprocess.run')
    def test_commit_count_check_fails(
        self, 
        mock_run: Mock, 
        mock_merge: Mock
    ) -> None:
        """Test when commit count check fails."""
        item = BeadsWorkItem(
            id="task-1",
            title="Task 1",
            description="",
            status="open",
            priority=1,
            issue_type="task"
        )
        worktree_path = Path("/fake/worktree")
        
        mock_run.side_effect = subprocess.CalledProcessError(1, "git rev-list")
        mock_merge.return_value = True  # merge_worktree_to_dev returns bool, not tuple
        
        result = check_and_merge_worktree(item, worktree_path)
        
        # Should attempt merge anyway
        assert result is True
        mock_merge.assert_called_once_with(item)


class TestMergeWorktreeToDev:
    """Test merge_worktree_to_dev function."""
    
    @patch('pokepoke.worktree_finalization.merge_worktree')
    @patch('pokepoke.worktree_finalization.check_main_repo_ready_for_merge')
    def test_successful_merge(
        self, 
        mock_check: Mock, 
        mock_merge: Mock
    ) -> None:
        """Test successful worktree merge."""
        item = BeadsWorkItem(
            id="task-1",
            title="Task 1",
            description="",
            status="open",
            priority=1,
            issue_type="task"
        )
        
        mock_check.return_value = (True, "")
        mock_merge.return_value = (True, [])  # Updated to return tuple
        
        result = merge_worktree_to_dev(item)
        
        assert result is True
        mock_merge.assert_called_once_with("task-1", cleanup=True)
    
    @patch('pokepoke.cleanup_agents.invoke_cleanup_agent')
    @patch('pokepoke.worktree_finalization.check_main_repo_ready_for_merge')
    def test_repo_not_ready_autofix_fails(self, mock_check: Mock, mock_cleanup: Mock) -> None:
        """Test when main repo is not ready and cleanup fails."""
        item = BeadsWorkItem(id="task-1", title="Task 1", description="", status="open", priority=1, issue_type="task")

        mock_check.return_value = (False, "Uncommitted changes")
        mock_cleanup.return_value = (False, "Reason")

        result = merge_worktree_to_dev(item)

        assert result is False
        mock_cleanup.assert_called_once()
    
    @patch('pokepoke.worktree_finalization.merge_worktree')
    @patch('pokepoke.cleanup_agents.invoke_cleanup_agent')
    @patch('pokepoke.worktree_finalization.check_main_repo_ready_for_merge')
    def test_repo_not_ready_autofix_succeeds(self, mock_check: Mock, mock_cleanup: Mock, mock_merge: Mock) -> None:
        """Test when main repo not ready, cleanup succeeds, merge proceeds."""
        item = BeadsWorkItem(id="task-1", title="T", description="", status="open", priority=1, issue_type="task")
        
        mock_check.side_effect = [(False, "Changes"), (True, "")]
        mock_cleanup.return_value = (True, "Fixed")
        mock_merge.return_value = (True, [])  # Updated to return tuple
        
        result = merge_worktree_to_dev(item)
        
        assert result is True
        mock_cleanup.assert_called_once()
        mock_merge.assert_called_once()

    @patch('pokepoke.cleanup_agents.invoke_merge_conflict_cleanup_agent')
    @patch('pokepoke.worktree_finalization.merge_worktree')
    @patch('pokepoke.worktree_finalization.check_main_repo_ready_for_merge')
    def test_merge_fails_autofix_fails(self, mock_check: Mock, mock_merge: Mock, mock_cleanup: Mock) -> None:
        """Test when merge fails and cleanup fails."""
        item = BeadsWorkItem(id="task-1", title="T", description="", status="open", priority=1, issue_type="task")

        mock_check.return_value = (True, "")
        mock_merge.return_value = (False, ["conflict.py"])  # Updated to return tuple
        mock_cleanup.return_value = (False, "Failed")

        result = merge_worktree_to_dev(item)

        assert result is False
        mock_cleanup.assert_called_once()

    @patch('pokepoke.cleanup_agents.invoke_merge_conflict_cleanup_agent')
    @patch('pokepoke.worktree_finalization.merge_worktree')
    @patch('pokepoke.worktree_finalization.check_main_repo_ready_for_merge')
    def test_merge_fails_autofix_succeeds(self, mock_check: Mock, mock_merge: Mock, mock_cleanup: Mock) -> None:
        """Test when merge fails, cleanup succeeds, retry works."""
        item = BeadsWorkItem(id="task-1", title="T", description="", status="open", priority=1, issue_type="task")

        mock_check.return_value = (True, "")
        mock_merge.side_effect = [(False, ["conflict.py"]), (True, [])]  # Updated to return tuples
        mock_cleanup.return_value = (True, "Fixed")

        result = merge_worktree_to_dev(item)

        assert result is True
        assert mock_merge.call_count == 2


class TestCloseWorkItemAndParents:
    """Test close_work_item_and_parents function."""
    
    @patch('pokepoke.worktree_finalization.check_parent_hierarchy')
    @patch('pokepoke.worktree_finalization.close_item')
    @patch('subprocess.run')
    def test_item_already_closed(
        self, 
        mock_run: Mock, 
        mock_close: Mock, 
        mock_check_parents: Mock
    ) -> None:
        """Test when item is already closed by agent."""
        item = BeadsWorkItem(
            id="task-1",
            title="Task 1",
            description="",
            status="in_progress",
            priority=1,
            issue_type="task"
        )
        
        mock_run.return_value = Mock(
            stdout='[{"id": "task-1", "title": "Test", "status": "closed", "priority": 1, "issue_type": "task"}]',
            returncode=0
        )
        
        close_work_item_and_parents(item)
        
        mock_close.assert_not_called()
        mock_check_parents.assert_called_once_with(item)
    
    @patch('pokepoke.worktree_finalization.check_parent_hierarchy')
    @patch('pokepoke.worktree_finalization.close_item')
    @patch('subprocess.run')
    def test_item_not_closed_fallback(
        self, 
        mock_run: Mock, 
        mock_close: Mock, 
        mock_check_parents: Mock
    ) -> None:
        """Test when item is not closed by agent."""
        item = BeadsWorkItem(
            id="task-1",
            title="Task 1",
            description="",
            status="in_progress",
            priority=1,
            issue_type="task"
        )
        
        mock_run.return_value = Mock(
            stdout='{"status": "in_progress"}',
            returncode=0
        )
        
        close_work_item_and_parents(item)
        
        mock_close.assert_called_once()
        mock_check_parents.assert_called_once_with(item)
    
    @patch('pokepoke.worktree_finalization.check_parent_hierarchy')
    @patch('pokepoke.worktree_finalization.close_item')
    @patch('subprocess.run')
    def test_check_status_fails(
        self, 
        mock_run: Mock, 
        mock_close: Mock, 
        mock_check_parents: Mock
    ) -> None:
        """Test when status check fails."""
        item = BeadsWorkItem(
            id="task-1",
            title="Task 1",
            description="",
            status="in_progress",
            priority=1,
            issue_type="task"
        )
        
        mock_run.side_effect = subprocess.CalledProcessError(1, "bd show")
        
        close_work_item_and_parents(item)
        
        mock_close.assert_called_once()
        mock_check_parents.assert_called_once_with(item)


class TestCheckParentHierarchy:
    """Test check_parent_hierarchy function."""
    
    @patch('pokepoke.worktree_finalization.close_parent_if_complete')
    @patch('pokepoke.worktree_finalization.get_parent_id')
    def test_no_parent(self, mock_get_parent: Mock, mock_close_parent: Mock) -> None:
        """Test when item has no parent."""
        item = BeadsWorkItem(
            id="task-1",
            title="Task 1",
            description="",
            status="open",
            priority=1,
            issue_type="task"
        )
        
        mock_get_parent.return_value = None
        
        check_parent_hierarchy(item)
        
        mock_close_parent.assert_not_called()
    
    @patch('pokepoke.worktree_finalization.close_parent_if_complete')
    @patch('pokepoke.worktree_finalization.get_parent_id')
    def test_with_parent_no_grandparent(
        self, 
        mock_get_parent: Mock, 
        mock_close_parent: Mock
    ) -> None:
        """Test when item has parent but no grandparent."""
        item = BeadsWorkItem(
            id="task-1",
            title="Task 1",
            description="",
            status="open",
            priority=1,
            issue_type="task"
        )
        
        mock_get_parent.side_effect = ["parent-1", None]
        
        check_parent_hierarchy(item)
        
        assert mock_close_parent.call_count == 1
        mock_close_parent.assert_called_with("parent-1")
    
    @patch('pokepoke.worktree_finalization.close_parent_if_complete')
    @patch('pokepoke.worktree_finalization.get_parent_id')
    def test_with_parent_and_grandparent(
        self, 
        mock_get_parent: Mock, 
        mock_close_parent: Mock
    ) -> None:
        """Test when item has parent and grandparent."""
        item = BeadsWorkItem(
            id="task-1",
            title="Task 1",
            description="",
            status="open",
            priority=1,
            issue_type="task"
        )
        
        mock_get_parent.side_effect = ["parent-1", "grandparent-1"]
        
        check_parent_hierarchy(item)
        
        assert mock_close_parent.call_count == 2
        mock_close_parent.assert_any_call("parent-1")
        mock_close_parent.assert_any_call("grandparent-1")


class TestProcessWorkItem:
    """Test process_work_item function."""
    
    @patch('pokepoke.workflow.run_beta_tester')  # Mock beta tester
    @patch('pokepoke.workflow.finalize_work_item')
    @patch('os.chdir')
    @patch('os.getcwd')
    @patch('pokepoke.workflow._run_cleanup_with_timeout')
    @patch('pokepoke.workflow.invoke_copilot')
    @patch('pokepoke.workflow.has_uncommitted_changes')
    @patch('pokepoke.workflow._setup_worktree')
    @patch('builtins.input')
    @patch('time.time')
    def test_skip_in_interactive_mode(
        self,
        mock_time: Mock,
        mock_input: Mock,
        mock_setup: Mock,
        mock_uncommitted: Mock,
        mock_invoke: Mock,
        mock_cleanup_timeout: Mock,
        mock_getcwd: Mock,
        mock_chdir: Mock,
        mock_finalize: Mock,
        mock_beta: Mock
    ) -> None:
        """Test skipping item in interactive mode."""
        item = BeadsWorkItem(
            id="task-1",
            title="Task 1",
            description="",
            status="open",
            priority=1,
            issue_type="task"
        )
        
        mock_input.return_value = 'n'
        mock_beta.return_value = None  # Beta tester returns None
        
        success, count, stats, cleanup_runs, gate_runs, model_completion = process_work_item(
            item, interactive=True
        )
        
        assert success is False
        assert count == 0
        assert stats is None
        assert cleanup_runs == 0
        mock_setup.assert_not_called()
    
    @patch('pokepoke.workflow._setup_worktree')
    @patch('pokepoke.workflow.assign_and_sync_item')
    @patch('builtins.input')
    @patch('time.time')
    def test_worktree_setup_fails(
        self,
        mock_time: Mock,
        mock_input: Mock,
        mock_assign: Mock,
        mock_setup: Mock
    ) -> None:
        """Test when worktree setup fails."""
        item = BeadsWorkItem(
            id="task-1",
            title="Task 1",
            description="",
            status="open",
            priority=1,
            issue_type="task"
        )
        
        mock_input.return_value = 'y'
        mock_assign.return_value = True
        mock_setup.return_value = None
        
        success, count, stats, cleanup_runs, gate_runs, model_completion = process_work_item(
            item, interactive=True
        )
        
        assert success is False
        assert count == 0
        assert stats is None
        assert cleanup_runs == 0
    
    @patch('pokepoke.workflow.run_gate_agent')  # Mock gate agent
    @patch('pokepoke.workflow.run_beta_tester')  # Mock beta tester
    @patch('pokepoke.workflow.finalize_work_item')
    @patch('os.chdir')
    @patch('os.getcwd')
    @patch('pokepoke.workflow._run_cleanup_with_timeout')
    @patch('pokepoke.workflow.invoke_copilot')
    @patch('pokepoke.workflow.has_commits_ahead')
    @patch('pokepoke.workflow.has_uncommitted_changes')
    @patch('pokepoke.workflow._setup_worktree')
    @patch('pokepoke.workflow.assign_and_sync_item')
    @patch('builtins.input')
    @patch('time.time')
    def test_no_changes_made(
        self,
        mock_time: Mock,
        mock_input: Mock,
        mock_assign: Mock,
        mock_setup: Mock,
        mock_uncommitted: Mock,
        mock_commits_ahead: Mock,
        mock_invoke: Mock,
        mock_cleanup_timeout: Mock,
        mock_getcwd: Mock,
        mock_chdir: Mock,
        mock_finalize: Mock,
        mock_beta: Mock,
        mock_gate_agent: Mock
    ) -> None:
        """Test when Copilot makes no changes (no uncommitted and no commits ahead)."""
        item = BeadsWorkItem(
            id="task-1",
            title="Task 1",
            description="",
            status="open",
            priority=1,
            issue_type="task"
        )
        
        mock_time.return_value = 0
        mock_input.return_value = 'y'
        mock_assign.return_value = True
        mock_setup.return_value = Path("/fake/worktree")
        mock_getcwd.return_value = "/original"
        mock_uncommitted.return_value = False
        mock_commits_ahead.return_value = 0
        mock_gate_agent.return_value = (True, "Gate passed", None)  # Gate agent passes
        mock_invoke.return_value = CopilotResult(
            work_item_id="task-1",
            success=True,
            output="Completed",
            attempt_count=1
        )
        mock_cleanup_timeout.return_value = (True, 0)  # Mock returns tuple
        mock_finalize.return_value = True
        mock_beta.return_value = None  # Beta tester returns None
        
        success, count, stats, cleanup_runs, gate_runs, model_completion = process_work_item(
            item, interactive=True
        )
        
        assert success is True
        assert count == 1
        # Cleanup is called even with no changes (it just exits early)
        mock_cleanup_timeout.assert_called_once()
    
    @patch('pokepoke.workflow.run_gate_agent')  # Mock gate agent
    @patch('pokepoke.workflow.run_beta_tester')  # Mock beta tester
    @patch('pokepoke.workflow.finalize_work_item')
    @patch('os.chdir')
    @patch('os.getcwd')
    @patch('pokepoke.workflow._run_cleanup_with_timeout')
    @patch('pokepoke.workflow.invoke_copilot')
    @patch('pokepoke.workflow.has_commits_ahead')
    @patch('pokepoke.workflow.has_uncommitted_changes')
    @patch('pokepoke.workflow._setup_worktree')
    @patch('pokepoke.workflow.assign_and_sync_item')
    @patch('builtins.input')
    @patch('time.time')
    def test_changes_already_committed(
        self,
        mock_time: Mock,
        mock_input: Mock,
        mock_assign: Mock,
        mock_setup: Mock,
        mock_uncommitted: Mock,
        mock_commits_ahead: Mock,
        mock_invoke: Mock,
        mock_cleanup_timeout: Mock,
        mock_getcwd: Mock,
        mock_chdir: Mock,
        mock_finalize: Mock,
        mock_beta: Mock,
        mock_gate_agent: Mock
    ) -> None:
        """Test when Copilot committed changes (clean tree but commits ahead)."""
        item = BeadsWorkItem(
            id="task-1",
            title="Task 1",
            description="",
            status="open",
            priority=1,
            issue_type="task"
        )
        
        mock_time.return_value = 0
        mock_input.return_value = 'y'
        mock_assign.return_value = True
        mock_setup.return_value = Path("/fake/worktree")
        mock_getcwd.return_value = "/original"
        mock_uncommitted.return_value = False
        mock_commits_ahead.return_value = 2  # 2 commits ahead
        mock_gate_agent.return_value = (True, "Gate passed", None)
        mock_invoke.return_value = CopilotResult(
            work_item_id="task-1",
            success=True,
            output="Completed",
            attempt_count=1
        )
        mock_cleanup_timeout.return_value = (True, 0)
        mock_finalize.return_value = True
        mock_beta.return_value = None
        
        success, count, stats, cleanup_runs, gate_runs, model_completion = process_work_item(
            item, interactive=True
        )
        
        assert success is True
        assert count == 1
        # Verify has_commits_ahead was called (distinguishes from "no changes")
        mock_commits_ahead.assert_called_once()
    
    @patch('pokepoke.workflow.run_gate_agent')  # Mock gate agent
    @patch('pokepoke.workflow.run_beta_tester')  # Mock beta tester
    @patch('pokepoke.workflow.cleanup_worktree')
    @patch('os.chdir')
    @patch('os.getcwd')
    @patch('pokepoke.workflow._run_cleanup_with_timeout')
    @patch('pokepoke.workflow.invoke_copilot')
    @patch('pokepoke.workflow.has_uncommitted_changes')
    @patch('pokepoke.workflow._setup_worktree')
    @patch('pokepoke.workflow.assign_and_sync_item')
    @patch('builtins.input')
    @patch('time.time')
    def test_copilot_failure(
        self,
        mock_time: Mock,
        mock_input: Mock,
        mock_assign: Mock,
        mock_setup: Mock,
        mock_uncommitted: Mock,
        mock_invoke: Mock,
        mock_cleanup_timeout: Mock,
        mock_getcwd: Mock,
        mock_chdir: Mock,
        mock_cleanup: Mock,
        mock_beta: Mock,
        mock_gate_agent: Mock
    ) -> None:
        """Test when Copilot CLI fails."""
        item = BeadsWorkItem(
            id="task-1",
            title="Task 1",
            description="",
            status="open",
            priority=1,
            issue_type="task"
        )
        
        mock_time.return_value = 0
        mock_input.return_value = 'y'
        mock_assign.return_value = True
        mock_setup.return_value = Path("/fake/worktree")
        mock_getcwd.return_value = "/original"
        mock_uncommitted.return_value = True
        mock_gate_agent.return_value = (True, "Gate passed", None)  # Gate agent passes
        mock_invoke.return_value = CopilotResult(
            work_item_id="task-1",
            success=False,
            output="",
            error="Failed",
            attempt_count=1
        )
        mock_cleanup_timeout.return_value = (True, 0)
        mock_beta.return_value = None  # Beta tester returns None
        
        success, count, stats, cleanup_runs, gate_runs, model_completion = process_work_item(
            item, interactive=True
        )
        
        assert success is False
        assert count == 1
        mock_cleanup.assert_called_once_with("task-1", force=True)
    
    @patch('pokepoke.workflow.add_comment')
    @patch('pokepoke.workflow.run_gate_agent')
    @patch('pokepoke.workflow.run_beta_tester')
    @patch('pokepoke.workflow.finalize_work_item')
    @patch('pokepoke.workflow.cleanup_worktree')
    @patch('os.chdir')
    @patch('os.getcwd')
    @patch('pokepoke.workflow._run_cleanup_with_timeout')
    @patch('pokepoke.workflow.invoke_copilot')
    @patch('pokepoke.workflow.has_uncommitted_changes')
    @patch('pokepoke.workflow._setup_worktree')
    @patch('pokepoke.workflow.assign_and_sync_item')
    @patch('builtins.input')
    @patch('time.time')
    def test_gate_agent_retry_loop(
        self,
        mock_time: Mock,
        mock_input: Mock,
        mock_assign: Mock,
        mock_setup: Mock,
        mock_uncommitted: Mock,
        mock_invoke: Mock,
        mock_cleanup_timeout: Mock,
        mock_getcwd: Mock,
        mock_chdir: Mock,
        mock_cleanup: Mock,
        mock_finalize: Mock,
        mock_beta: Mock,
        mock_gate_agent: Mock,
        mock_add_comment: Mock
    ) -> None:
        """Test gate agent rejection triggers retry loop."""
        item = BeadsWorkItem(
            id="task-1",
            title="Task 1",
            description="Original description",
            status="open",
            priority=1,
            issue_type="task"
        )
        
        mock_time.return_value = 0
        mock_input.return_value = 'y'
        mock_assign.return_value = True
        mock_setup.return_value = Path("/fake/worktree")
        mock_getcwd.return_value = "/original"
        mock_uncommitted.return_value = True
        mock_cleanup_timeout.return_value = (True, 0)
        mock_finalize.return_value = True
        mock_beta.return_value = None
        
        # First invoke: work agent succeeds
        # Gate agent fails first time, passes second time
        mock_gate_agent.side_effect = [
            (False, "Tests failed", None),
            (True, "All tests pass", None)
        ]
        # Two work agent invocations
        mock_invoke.side_effect = [
            CopilotResult(work_item_id="task-1", success=True, output="Try 1", attempt_count=1),
            CopilotResult(work_item_id="task-1", success=True, output="Try 2", attempt_count=1)
        ]
        
        success, count, stats, cleanup_runs, gate_runs, model_completion = process_work_item(
            item, interactive=True
        )
        
        assert success is True
        assert count == 2  # Two invocations
        mock_add_comment.assert_called_once()  # Comment added for gate rejection
        assert mock_gate_agent.call_count == 2
    
    @patch('pokepoke.workflow.add_comment')
    @patch('pokepoke.workflow.run_gate_agent')
    @patch('pokepoke.workflow.run_beta_tester')
    @patch('pokepoke.workflow.finalize_work_item')
    @patch('pokepoke.workflow.cleanup_worktree')
    @patch('os.chdir')
    @patch('os.getcwd')
    @patch('pokepoke.workflow._run_cleanup_with_timeout')
    @patch('pokepoke.workflow.invoke_copilot')
    @patch('pokepoke.workflow.has_uncommitted_changes')
    @patch('pokepoke.workflow._setup_worktree')
    @patch('pokepoke.workflow.assign_and_sync_item')
    @patch('builtins.input')
    @patch('time.time')
    def test_gate_agent_stats_aggregation(
        self,
        mock_time: Mock,
        mock_input: Mock,
        mock_assign: Mock,
        mock_setup: Mock,
        mock_uncommitted: Mock,
        mock_invoke: Mock,
        mock_cleanup_timeout: Mock,
        mock_getcwd: Mock,
        mock_chdir: Mock,
        mock_cleanup: Mock,
        mock_finalize: Mock,
        mock_beta: Mock,
        mock_gate_agent: Mock,
        mock_add_comment: Mock
    ) -> None:
        """Test gate agent stats are aggregated into totals."""
        item = BeadsWorkItem(
            id="task-1",
            title="Task 1",
            description="",
            status="open",
            priority=1,
            issue_type="task"
        )
        
        mock_time.return_value = 0
        mock_input.return_value = 'y'
        mock_assign.return_value = True
        mock_setup.return_value = Path("/fake/worktree")
        mock_getcwd.return_value = "/original"
        mock_uncommitted.return_value = True
        mock_cleanup_timeout.return_value = (True, 0)
        mock_finalize.return_value = True
        mock_beta.return_value = None
        
        # Gate agent returns stats
        gate_stats = AgentStats(
            wall_duration=5.0,
            api_duration=2.0,
            input_tokens=50,
            output_tokens=25,
            premium_requests=1
        )
        mock_gate_agent.return_value = (True, "Pass", gate_stats)
        
        work_stats = AgentStats(
            wall_duration=10.0,
            api_duration=5.0,
            input_tokens=100,
            output_tokens=50,
            premium_requests=2
        )
        mock_invoke.return_value = CopilotResult(
            work_item_id="task-1",
            success=True,
            output="Completed",
            attempt_count=1,
            stats=work_stats
        )
        
        success, count, stats, cleanup_runs, gate_runs, model_completion = process_work_item(
            item, interactive=True
        )
        
        assert success is True
        assert stats is not None
        # Gate agent stats should NOT be aggregated into work agent stats (yja0 fix)
        assert stats.wall_duration == 10.0  # Only work agent stats
        assert stats.input_tokens == 100  # Only work agent tokens
        assert gate_runs == 1  # Gate agent ran once
    
    @patch('pokepoke.workflow.run_gate_agent')
    @patch('pokepoke.workflow.run_beta_tester')
    @patch('pokepoke.workflow.cleanup_worktree')
    @patch('os.chdir')
    @patch('os.getcwd')
    @patch('pokepoke.workflow._run_cleanup_with_timeout')
    @patch('pokepoke.workflow.invoke_copilot')
    @patch('pokepoke.workflow.has_uncommitted_changes')
    @patch('pokepoke.workflow._setup_worktree')
    @patch('pokepoke.workflow.assign_and_sync_item')
    @patch('builtins.input')
    @patch('time.time')
    def test_cleanup_failure_returns_stats(
        self,
        mock_time: Mock,
        mock_input: Mock,
        mock_assign: Mock,
        mock_setup: Mock,
        mock_uncommitted: Mock,
        mock_invoke: Mock,
        mock_cleanup_timeout: Mock,
        mock_getcwd: Mock,
        mock_chdir: Mock,
        mock_cleanup: Mock,
        mock_beta: Mock,
        mock_gate_agent: Mock
    ) -> None:
        """Test that cleanup failure returns accumulated stats."""
        item = BeadsWorkItem(
            id="task-1",
            title="Task 1",
            description="",
            status="open",
            priority=1,
            issue_type="task"
        )
        
        mock_time.return_value = 0
        mock_input.return_value = 'y'
        mock_assign.return_value = True
        mock_setup.return_value = Path("/fake/worktree")
        mock_getcwd.return_value = "/original"
        mock_uncommitted.return_value = True
        mock_gate_agent.return_value = (True, "Pass", None)
        mock_beta.return_value = None
        
        work_stats = AgentStats(
            wall_duration=10.0,
            api_duration=5.0,
            input_tokens=100,
            output_tokens=50
        )
        mock_invoke.return_value = CopilotResult(
            work_item_id="task-1",
            success=True,
            output="Completed",
            attempt_count=1,
            stats=work_stats
        )
        mock_cleanup_timeout.return_value = (False, 2)  # Cleanup fails
        
        success, count, stats, cleanup_runs, gate_runs, model_completion = process_work_item(
            item, interactive=True
        )
        
        assert success is False
        assert cleanup_runs == 2
        assert stats is not None  # Stats should be returned even on failure
        assert stats.wall_duration == 10.0







