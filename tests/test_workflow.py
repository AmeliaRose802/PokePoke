"""Unit tests for workflow module."""

import subprocess
from pathlib import Path
from unittest.mock import Mock, patch

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

    @patch('pokepoke.work_item_selection.has_unmet_blocking_dependencies', return_value=False)
    @patch('pokepoke.work_item_selection.select_next_hierarchical_item')
    def test_autonomous_selection(self, mock_select: Mock, mock_deps: Mock) -> None:
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

    @patch('pokepoke.work_item_selection.has_unmet_blocking_dependencies', return_value=False)
    @patch('builtins.input')
    def test_interactive_selection(self, mock_input: Mock, mock_deps: Mock) -> None:
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

    @patch('pokepoke.work_item_selection.has_unmet_blocking_dependencies', return_value=False)
    @patch('pokepoke.work_item_selection.select_next_hierarchical_item')
    def test_filters_items_assigned_to_others(self, mock_select: Mock, mock_deps: Mock) -> None:
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

    @patch('pokepoke.work_item_selection.has_unmet_blocking_dependencies', return_value=False)
    def test_all_items_assigned_to_others(self, mock_deps: Mock) -> None:
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
        mock_create.assert_called_once_with("task-1", lock_timeout=300.0)

    @patch('pokepoke.workflow.create_worktree')
    def test_successful_setup_with_custom_timeout(self, mock_create: Mock) -> None:
        """Test successful worktree creation with custom lock timeout."""
        item = BeadsWorkItem(
            id="task-1",
            title="Task 1",
            description="",
            status="open",
            priority=1,
            issue_type="task"
        )
        mock_create.return_value = Path("/fake/worktree")

        result = _setup_worktree(item, lock_timeout=600.0)

        assert result is not None
        assert result == Path("/fake/worktree")
        mock_create.assert_called_once_with("task-1", lock_timeout=600.0)

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

    @patch('pokepoke.worktree_finalization.merge_lock')
    @patch('pokepoke.worktree_finalization.merge_worktree_to_dev')
    @patch('pokepoke.worktree_finalization.cleanup_worktree')
    @patch('subprocess.run')
    def test_no_commits_to_merge(
        self,
        mock_run: Mock,
        mock_cleanup: Mock,
        mock_merge: Mock,
        mock_lock: Mock
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

    @patch('pokepoke.worktree_finalization.merge_lock')
    @patch('pokepoke.worktree_finalization.merge_worktree_to_dev')
    @patch('subprocess.run')
    def test_has_commits_to_merge(
        self,
        mock_run: Mock,
        mock_merge: Mock,
        mock_lock: Mock
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
        mock_merge.assert_called_once_with(item, parent_agent_id=None, worktree_path=worktree_path)

    @patch('pokepoke.worktree_finalization.merge_lock')
    @patch('pokepoke.worktree_finalization.merge_worktree_to_dev')
    @patch('subprocess.run')
    def test_commit_count_check_fails(
        self,
        mock_run: Mock,
        mock_merge: Mock,
        mock_lock: Mock
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
        mock_merge.assert_called_once_with(item, parent_agent_id=None, worktree_path=worktree_path)


class TestMergeWorktreeToDev:
    """Test merge_worktree_to_dev function (delegates to perform_worktree_merge)."""

    @patch('pokepoke.worktree_merge_handler.perform_worktree_merge')
    def test_successful_merge(self, mock_perform: Mock) -> None:
        """Test successful worktree merge."""
        item = BeadsWorkItem(
            id="task-1",
            title="Task 1",
            description="",
            status="open",
            priority=1,
            issue_type="task"
        )

        mock_perform.return_value = (True, True)

        result = merge_worktree_to_dev(item)

        assert result is True
        mock_perform.assert_called_once()

    @patch('pokepoke.worktree_merge_handler.perform_worktree_merge')
    def test_merge_fails_autofix_succeeds(self, mock_perform: Mock) -> None:
        """Test merge returns True when perform_worktree_merge succeeds."""
        item = BeadsWorkItem(id="task-1", title="T", description="", status="open", priority=1, issue_type="task")
        mock_perform.return_value = (True, True)

        result = merge_worktree_to_dev(item)
        assert result is True

    @patch('pokepoke.worktree_merge_handler.perform_worktree_merge')
    def test_repo_not_ready_autofix_fails(self, mock_perform: Mock) -> None:
        """Test when merge fails."""
        item = BeadsWorkItem(id="task-1", title="Task 1", description="", status="open", priority=1, issue_type="task")
        mock_perform.return_value = (False, False)

        result = merge_worktree_to_dev(item)
        assert result is False

    @patch('pokepoke.worktree_merge_handler.perform_worktree_merge')
    def test_repo_not_ready_autofix_succeeds(self, mock_perform: Mock) -> None:
        """Test merge returns True after successful recovery."""
        item = BeadsWorkItem(id="task-1", title="T", description="", status="open", priority=1, issue_type="task")
        mock_perform.return_value = (True, True)

        result = merge_worktree_to_dev(item)
        assert result is True

    @patch('pokepoke.worktree_merge_handler.perform_worktree_merge')
    def test_merge_fails_autofix_fails(self, mock_perform: Mock) -> None:
        """Test when merge fails and recovery fails."""
        item = BeadsWorkItem(id="task-1", title="T", description="", status="open", priority=1, issue_type="task")
        mock_perform.return_value = (False, False)

        result = merge_worktree_to_dev(item)
        assert result is False


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

    @patch('pokepoke.model_selection.get_config')
    @patch('pokepoke.workflow.get_config')
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
        mock_beta: Mock,
        mock_config: Mock,
        mock_model_config: Mock,
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
        # Mock get_config to avoid needing proper path resolution
        mock_config.return_value.ai_backend.provider = "copilot"
        mock_config.return_value.command_timeout = "300"
        # Mock model selection config
        mock_model_config.return_value.models.candidate_models = ["gemini-3-pro"]
        mock_model_config.return_value.models.default = "gemini-3-pro"

        result = process_work_item(
            item, interactive=True
        )

        assert result.success is False
        assert result.request_count == 0
        assert result.stats is None
        assert result.cleanup_agent_runs == 0
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
        mock_setup: Mock,
    ) -> None:
        """Test when worktree setup fails, process returns failure."""
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

        result = process_work_item(
            item, interactive=True
        )

        assert result.success is False
        assert result.request_count == 0
        assert result.stats is None
        assert result.cleanup_agent_runs == 0

    @patch('pokepoke.workflow.cleanup_worktree')
    @patch('pokepoke.workflow.invoke_copilot')
    @patch('pokepoke.workflow._setup_worktree')
    @patch('pokepoke.workflow.assign_and_sync_item')
    @patch('pokepoke.workflow.is_shutting_down')
    @patch('pokepoke.workflow.select_model_for_item')
    @patch('time.time')
    def test_shutdown_before_first_iteration_does_not_crash(
        self,
        mock_time: Mock,
        mock_select_model: Mock,
        mock_is_shutting_down: Mock,
        mock_assign: Mock,
        mock_setup: Mock,
        mock_invoke: Mock,
        mock_cleanup_worktree: Mock,
    ) -> None:
        """Shutdown before first loop iteration should not raise UnboundLocalError."""
        item = BeadsWorkItem(
            id="task-1",
            title="Task 1",
            description="",
            status="open",
            priority=1,
            issue_type="task",
        )

        mock_time.return_value = 0.0
        mock_select_model.return_value = "test-model"
        mock_is_shutting_down.return_value = True
        mock_assign.return_value = True
        mock_setup.return_value = Path("/fake/worktree")

        result = process_work_item(
            item, interactive=False
        )

        assert result.success is False
        assert result.request_count == 0
        # Stats are now tracked even on failure/shutdown
        assert result.stats is not None
        assert result.cleanup_agent_runs == 0
        assert result.gate_agent_runs == 0
        assert result.model_completion is not None
        mock_invoke.assert_not_called()
        mock_cleanup_worktree.assert_any_call(item.id, force=True)

    @patch('pokepoke.git_operations.build_handoff_context', return_value='')
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
        mock_gate_agent: Mock,
        mock_handoff: Mock
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

        result = process_work_item(
            item, interactive=True
        )

        assert result.success is True
        assert result.request_count == 1
        # Cleanup is called even with no changes (it just exits early)
        mock_cleanup_timeout.assert_called_once()

    @patch('pokepoke.git_operations.build_handoff_context', return_value='')
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
        mock_gate_agent: Mock,
        mock_handoff: Mock
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

        result = process_work_item(
            item, interactive=True
        )

        assert result.success is True
        assert result.request_count == 1
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

        result = process_work_item(
            item, interactive=True
        )

        assert result.success is False
        assert result.request_count == 1
        mock_cleanup.assert_called_with("task-1", force=True)

    @patch('pokepoke.git_operations.build_handoff_context', return_value='')
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
        mock_add_comment: Mock,
        mock_handoff: Mock
    ) -> None:
        """Test gate agent rejection triggers retry loop."""
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

        result = process_work_item(
            item, interactive=True
        )

        assert result.success is True
        assert result.request_count == 2  # Two invocations
        mock_add_comment.assert_called_once()  # Comment added for gate rejection
        assert mock_gate_agent.call_count == 2

        assert item.description.startswith("**PREVIOUS GATE AGENT FEEDBACK:**\n")
        assert not item.description.startswith("\n\n")

    @patch('pokepoke.git_operations.build_handoff_context', return_value='')
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
        mock_add_comment: Mock,
        mock_handoff: Mock
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

        result = process_work_item(
            item, interactive=True
        )

        assert result.success is True
        assert result.stats is not None
        # Gate agent stats should NOT be aggregated into work agent stats (yja0 fix)
        assert result.stats.wall_duration == 10.0  # Only work agent stats
        assert result.stats.input_tokens == 100  # Only work agent tokens
        assert result.gate_agent_runs == 1  # Gate agent ran once

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

        result = process_work_item(
            item, interactive=True
        )

        assert result.success is False
        assert result.cleanup_agent_runs == 2
        assert result.stats is not None  # Stats should be returned even on failure
        assert result.stats.wall_duration == 10.0

    @patch('pokepoke.git_operations.build_handoff_context', return_value='')
    @patch('pokepoke.workflow.add_comment')
    @patch('pokepoke.workflow.run_gate_agent')
    @patch('pokepoke.workflow.select_model_for_item')
    @patch('pokepoke.workflow.cleanup_worktree')
    @patch('pokepoke.workflow._run_cleanup_with_timeout')
    @patch('pokepoke.workflow.invoke_copilot')
    @patch('pokepoke.workflow.has_commits_ahead')
    @patch('pokepoke.workflow.has_uncommitted_changes')
    @patch('pokepoke.workflow._setup_worktree')
    @patch('pokepoke.workflow.assign_and_sync_item')
    @patch('builtins.input')
    @patch('time.time')
    def test_timeout_restarts_limited(
        self,
        mock_time: Mock,
        mock_input: Mock,
        mock_assign: Mock,
        mock_setup: Mock,
        mock_uncommitted: Mock,
        mock_commits_ahead: Mock,
        mock_invoke: Mock,
        mock_cleanup_timeout: Mock,
        mock_cleanup_worktree: Mock,
        mock_select_model: Mock,
        mock_gate_agent: Mock,
        mock_add_comment: Mock,
        mock_handoff: Mock
    ) -> None:
        """Test that repeated timeouts are bounded by max_timeout_restarts."""
        item = BeadsWorkItem(
            id="task-1",
            title="Task 1",
            description="",
            status="open",
            priority=1,
            issue_type="task"
        )

        mock_select_model.return_value = "test-model"
        # Use a very short timeout (0.001 hours = 3.6s) so timeout fires reliably
        # Return monotonically increasing values; each call 5s apart ensures timeout
        call_count = [0]
        def time_side_effect():
            call_count[0] += 1
            return call_count[0] * 5.0
        mock_time.side_effect = time_side_effect
        mock_input.return_value = 'y'
        mock_assign.return_value = True
        mock_setup.return_value = Path("/fake/worktree")
        mock_uncommitted.return_value = False
        mock_commits_ahead.return_value = 0
        mock_invoke.return_value = CopilotResult(
            work_item_id="task-1",
            success=True,
            output="Completed",
            attempt_count=1
        )
        mock_cleanup_timeout.return_value = (True, 0)
        # Gate rejects, forcing loop to continue to next timeout check
        mock_gate_agent.return_value = (False, "Rejected", None)

        result = process_work_item(
            item, interactive=True, timeout_hours=0.001, max_timeout_restarts=2
        )

        assert result.success is False
        mock_cleanup_worktree.assert_called_with(item.id, force=True)

    @patch('pokepoke.git_operations.build_handoff_context', return_value='')
    @patch('pokepoke.workflow.run_gate_agent')
    @patch('pokepoke.workflow.run_beta_tester')
    @patch('pokepoke.workflow.finalize_work_item')
    @patch('pokepoke.workflow._run_cleanup_with_timeout')
    @patch('pokepoke.workflow.invoke_copilot')
    @patch('pokepoke.workflow.has_commits_ahead')
    @patch('pokepoke.workflow.has_uncommitted_changes')
    @patch('pokepoke.workflow._setup_worktree')
    @patch('pokepoke.workflow.assign_and_sync_item')
    @patch('builtins.input')
    @patch('time.time')
    def test_timeout_restart_then_success(
        self,
        mock_time: Mock,
        mock_input: Mock,
        mock_assign: Mock,
        mock_setup: Mock,
        mock_uncommitted: Mock,
        mock_commits_ahead: Mock,
        mock_invoke: Mock,
        mock_cleanup_timeout: Mock,
        mock_finalize: Mock,
        mock_beta: Mock,
        mock_gate_agent: Mock,
        mock_handoff: Mock
    ) -> None:
        """Test that a timeout restart followed by success works correctly."""
        item = BeadsWorkItem(
            id="task-1",
            title="Task 1",
            description="",
            status="open",
            priority=1,
            issue_type="task"
        )

        # First iteration: past timeout. After restart, within timeout.
        # time.time() calls: start_time init, elapsed check (past), restart reset,
        # elapsed check (within), remaining calc, duration calc...
        call_count = 0
        def time_side_effect():
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                # Initial start_time and first elapsed check: past timeout
                return 99999
            # After restart: well within timeout
            return 0

        mock_time.side_effect = time_side_effect
        mock_input.return_value = 'y'
        mock_assign.return_value = True
        mock_setup.return_value = Path("/fake/worktree")
        mock_uncommitted.return_value = False
        mock_commits_ahead.return_value = 0
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

        result = process_work_item(
            item, interactive=True, max_timeout_restarts=3
        )

        assert result.success is True
        mock_invoke.assert_called_once()


class TestProcessWorkItemCoordination:
    """Tests for concurrent-agent coordination paths in process_work_item."""

    @patch('pokepoke.workflow._setup_worktree')
    @patch('pokepoke.workflow.assign_and_sync_item')
    @patch('time.time')
    def test_assign_fails_race_condition(
        self,
        mock_time: Mock,
        mock_assign: Mock,
        mock_setup: Mock,
    ) -> None:
        """When assign_and_sync_item returns False (another agent already claimed the item),
        process_work_item must return (False, 0, ...) without creating a worktree."""
        item = BeadsWorkItem(
            id="task-race",
            title="Race Task",
            description="",
            status="open",
            priority=1,
            issue_type="task",
        )
        mock_time.return_value = 0.0
        mock_assign.return_value = False  # Simulate another agent grabbed the item first

        result = process_work_item(
            item, interactive=False
        )

        assert result.success is False
        assert result.request_count == 0
        assert result.stats is None
        mock_setup.assert_not_called()

    @patch('pokepoke.workflow._setup_worktree')
    @patch('pokepoke.workflow.assign_and_sync_item')
    @patch('time.time')
    def test_worktree_lock_timeout(
        self,
        mock_time: Mock,
        mock_assign: Mock,
        mock_setup: Mock,
    ) -> None:
        """When create_worktree times out (another agent holds the lock),
        process_work_item must return (False, 0, ...) without crashing.

        The lock is now acquired inside create_worktree via with_worktree_lock,
        not as a wrapper around the entire setup block.

        _setup_worktree catches exceptions and returns None, so we simulate
        that behavior here by returning None (as if the lock timeout happened
        and _setup_worktree caught the exception).
        """
        item = BeadsWorkItem(
            id="task-lock",
            title="Lock Task",
            description="",
            status="open",
            priority=1,
            issue_type="task",
        )
        mock_time.return_value = 0.0
        mock_assign.return_value = True
        # Simulate lock timeout: _setup_worktree catches the RuntimeError and returns None
        mock_setup.return_value = None

        result = process_work_item(
            item, interactive=False
        )

        assert result.success is False
        assert result.request_count == 0
        assert result.stats is None

    @patch('pokepoke.workflow.unassign_with_retry')
    @patch('pokepoke.workflow._setup_worktree')
    @patch('pokepoke.workflow.assign_and_sync_item')
    @patch('time.time')
    def test_worktree_failure_triggers_unassign(
        self,
        mock_time: Mock,
        mock_assign: Mock,
        mock_setup: Mock,
        mock_unassign: Mock,
    ) -> None:
        """When worktree creation fails after a successful claim,
        process_work_item must unassign the item so other agents can pick it up."""
        item = BeadsWorkItem(
            id="task-wt-fail",
            title="Worktree Fail Task",
            description="",
            status="open",
            priority=1,
            issue_type="task",
        )
        mock_time.return_value = 0.0
        mock_assign.return_value = True
        mock_setup.return_value = None  # Worktree creation failed
        mock_unassign.return_value = True

        result = process_work_item(
            item, interactive=False
        )

        assert result.success is False
        assert result.request_count == 0
        mock_unassign.assert_called_once_with(item.id)


class TestGateAgentDisabled:
    """Tests for gate_agent_enabled config setting."""

    @patch('pokepoke.git_operations.build_handoff_context', return_value='')
    @patch('pokepoke.workflow.run_gate_agent')
    @patch('pokepoke.workflow.run_beta_tester')
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
    def test_gate_agent_skipped_when_disabled(
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
        mock_gate_agent: Mock,
        mock_handoff: Mock,
    ) -> None:
        """When gate_agent_enabled is False, gate agent should not run."""
        item = BeadsWorkItem(
            id="task-1",
            title="Task 1",
            description="",
            status="open",
            priority=1,
            issue_type="task",
        )

        mock_time.return_value = 0
        mock_input.return_value = 'y'
        mock_assign.return_value = True
        mock_setup.return_value = Path("/fake/worktree")
        mock_getcwd.return_value = "/original"
        mock_uncommitted.return_value = False
        mock_commits_ahead.return_value = 1
        mock_invoke.return_value = CopilotResult(
            work_item_id="task-1", success=True, output="Done", attempt_count=1,
        )
        mock_cleanup_timeout.return_value = (True, 0)
        mock_finalize.return_value = True
        mock_beta.return_value = None

        # Patch get_config to disable gate agent
        from pokepoke.config import ProjectConfig
        cfg = ProjectConfig()
        cfg.gate_agent_enabled = False
        with patch('pokepoke.workflow.get_config', return_value=cfg):
            result = process_work_item(
                item, interactive=True,
            )

        assert result.success is True
        assert result.gate_agent_runs == 0
        mock_gate_agent.assert_not_called()


class TestUnassignOnFailure:
    """Tests that work items are unassigned when processing fails after assignment."""

    @patch('pokepoke.workflow.unassign_with_retry')
    @patch('pokepoke.workflow.cleanup_worktree')
    @patch('pokepoke.git_operations.build_handoff_context', return_value='')
    @patch('pokepoke.workflow.run_gate_agent')
    @patch('pokepoke.workflow.run_beta_tester')
    @patch('pokepoke.workflow.finalize_work_item')
    @patch('pokepoke.workflow._run_cleanup_with_timeout')
    @patch('pokepoke.workflow.invoke_copilot')
    @patch('pokepoke.workflow.has_commits_ahead')
    @patch('pokepoke.workflow.has_uncommitted_changes')
    @patch('pokepoke.workflow._setup_worktree')
    @patch('pokepoke.workflow.assign_and_sync_item')
    @patch('time.time')
    def test_finalization_failure_triggers_unassign(
        self,
        mock_time: Mock,
        mock_assign: Mock,
        mock_setup: Mock,
        mock_uncommitted: Mock,
        mock_commits_ahead: Mock,
        mock_invoke: Mock,
        mock_cleanup_timeout: Mock,
        mock_finalize: Mock,
        mock_beta: Mock,
        mock_gate_agent: Mock,
        mock_handoff: Mock,
        mock_cleanup_wt: Mock,
        mock_unassign: Mock,
    ) -> None:
        """When finalize_work_item returns False, item must be unassigned."""
        item = BeadsWorkItem(
            id="task-finalize-fail",
            title="Finalize Fail Task",
            description="",
            status="open",
            priority=1,
            issue_type="task",
        )
        mock_time.return_value = 0.0
        mock_assign.return_value = True
        mock_setup.return_value = Path("/fake/worktree")
        mock_uncommitted.return_value = False
        mock_commits_ahead.return_value = 1
        mock_invoke.return_value = CopilotResult(
            work_item_id="task-finalize-fail", success=True, output="Done", attempt_count=1
        )
        mock_cleanup_timeout.return_value = (True, 0)
        mock_gate_agent.return_value = (True, "OK", None)
        mock_finalize.return_value = False  # Finalization fails

        result = process_work_item(item, interactive=False)

        assert result.success is False
        mock_unassign.assert_called_once_with(item.id)

    @patch('pokepoke.workflow.unassign_with_retry')
    @patch('pokepoke.workflow.cleanup_worktree')
    @patch('pokepoke.workflow.invoke_copilot')
    @patch('pokepoke.workflow._setup_worktree')
    @patch('pokepoke.workflow.assign_and_sync_item')
    @patch('time.time')
    def test_work_agent_failure_triggers_unassign(
        self,
        mock_time: Mock,
        mock_assign: Mock,
        mock_setup: Mock,
        mock_invoke: Mock,
        mock_cleanup_wt: Mock,
        mock_unassign: Mock,
    ) -> None:
        """When work agent fails, item must be unassigned."""
        item = BeadsWorkItem(
            id="task-agent-fail",
            title="Agent Fail Task",
            description="",
            status="open",
            priority=1,
            issue_type="task",
        )
        mock_time.return_value = 0.0
        mock_assign.return_value = True
        mock_setup.return_value = Path("/fake/worktree")
        mock_invoke.return_value = CopilotResult(
            work_item_id="task-agent-fail", success=False, error="Agent crashed", attempt_count=1
        )

        result = process_work_item(item, interactive=False)

        assert result.success is False
        mock_unassign.assert_called_once_with(item.id)

    @patch('pokepoke.workflow.unassign_with_retry')
    @patch('pokepoke.workflow.cleanup_worktree')
    @patch('pokepoke.git_operations.build_handoff_context', return_value='')
    @patch('pokepoke.workflow.run_gate_agent')
    @patch('pokepoke.workflow.run_beta_tester')
    @patch('pokepoke.workflow.finalize_work_item')
    @patch('pokepoke.workflow._run_cleanup_with_timeout')
    @patch('pokepoke.workflow.invoke_copilot')
    @patch('pokepoke.workflow.has_commits_ahead')
    @patch('pokepoke.workflow.has_uncommitted_changes')
    @patch('pokepoke.workflow._setup_worktree')
    @patch('pokepoke.workflow.assign_and_sync_item')
    @patch('time.time')
    def test_successful_finalization_does_not_unassign(
        self,
        mock_time: Mock,
        mock_assign: Mock,
        mock_setup: Mock,
        mock_uncommitted: Mock,
        mock_commits_ahead: Mock,
        mock_invoke: Mock,
        mock_cleanup_timeout: Mock,
        mock_finalize: Mock,
        mock_beta: Mock,
        mock_gate_agent: Mock,
        mock_handoff: Mock,
        mock_cleanup_wt: Mock,
        mock_unassign: Mock,
    ) -> None:
        """When finalization succeeds, item must NOT be unassigned."""
        item = BeadsWorkItem(
            id="task-success",
            title="Success Task",
            description="",
            status="open",
            priority=1,
            issue_type="task",
        )
        mock_time.return_value = 0.0
        mock_assign.return_value = True
        mock_setup.return_value = Path("/fake/worktree")
        mock_uncommitted.return_value = False
        mock_commits_ahead.return_value = 1
        mock_invoke.return_value = CopilotResult(
            work_item_id="task-success", success=True, output="Done", attempt_count=1
        )
        mock_cleanup_timeout.return_value = (True, 0)
        mock_gate_agent.return_value = (True, "OK", None)
        mock_finalize.return_value = True  # Finalization succeeds

        result = process_work_item(item, interactive=False)

        assert result.success is True
        mock_unassign.assert_not_called()


class TestLogFailure:
    """Tests for _log_failure helper."""

    def test_calls_loggers_when_both_present(self) -> None:
        """Covers lines 38-39: both loggers are called."""
        from pokepoke.workflow import _log_failure
        run_logger = Mock()
        item_logger = Mock()
        _log_failure(run_logger, item_logger, request_count=3)
        item_logger.log_summary.assert_called_once_with(False, 3)
        run_logger.log_orchestrator.assert_called_once()

    def test_skips_when_no_loggers(self) -> None:
        """Covers lines 37: no-op when loggers are None."""
        from pokepoke.workflow import _log_failure
        _log_failure(None, None, request_count=1)  # Should not raise


class TestWorkflowGateException:
    """Tests for gate agent exception handling."""

    @patch('pokepoke.workflow.unassign_with_retry')
    @patch('pokepoke.workflow.cleanup_worktree')
    @patch('pokepoke.git_operations.build_handoff_context', return_value='')
    @patch('pokepoke.workflow.run_gate_agent', side_effect=RuntimeError("gate crashed"))
    @patch('pokepoke.workflow._run_cleanup_with_timeout')
    @patch('pokepoke.workflow.invoke_copilot')
    @patch('pokepoke.workflow.has_commits_ahead')
    @patch('pokepoke.workflow.has_uncommitted_changes')
    @patch('pokepoke.workflow._setup_worktree')
    @patch('pokepoke.workflow.assign_and_sync_item')
    @patch('time.time')
    def test_gate_agent_exception_triggers_cleanup(
        self,
        mock_time: Mock,
        mock_assign: Mock,
        mock_setup: Mock,
        mock_uncommitted: Mock,
        mock_commits_ahead: Mock,
        mock_invoke: Mock,
        mock_cleanup_timeout: Mock,
        mock_gate_agent: Mock,
        mock_handoff: Mock,
        mock_cleanup_wt: Mock,
        mock_unassign: Mock,
    ) -> None:
        """Covers lines 237-244: gate agent exception is logged, re-raised,
        and finally block handles cleanup."""
        import pytest
        item = BeadsWorkItem(
            id="task-gate-ex", title="Gate Ex Task", description="",
            status="open", priority=1, issue_type="task",
        )
        mock_time.return_value = 0.0
        mock_assign.return_value = True
        mock_setup.return_value = Path("/fake/worktree")
        mock_uncommitted.return_value = False
        mock_commits_ahead.return_value = 1
        mock_invoke.return_value = CopilotResult(
            work_item_id="task-gate-ex", success=True, output="Done", attempt_count=1
        )
        mock_cleanup_timeout.return_value = (True, 0)

        with pytest.raises(RuntimeError, match="gate crashed"):
            process_work_item(item, interactive=False)

        # Finally block should have run cleanup and unassign
        mock_cleanup_wt.assert_called()
        mock_unassign.assert_called()


class TestWorkflowCleanupException:
    """Tests for worktree cleanup and unassign exception in finally."""

    @patch('pokepoke.workflow.unassign_with_retry')
    @patch('pokepoke.workflow.cleanup_worktree')
    @patch('pokepoke.workflow.invoke_copilot')
    @patch('pokepoke.workflow._setup_worktree')
    @patch('pokepoke.workflow.assign_and_sync_item')
    @patch('time.time')
    def test_cleanup_worktree_exception_in_finally_handled(
        self,
        mock_time: Mock,
        mock_assign: Mock,
        mock_setup: Mock,
        mock_invoke: Mock,
        mock_cleanup_wt: Mock,
        mock_unassign: Mock,
    ) -> None:
        """Covers lines 348-349: cleanup_worktree exception in finally is caught."""
        item = BeadsWorkItem(
            id="task-cleanup-ex", title="Cleanup Ex", description="",
            status="open", priority=1, issue_type="task",
        )
        mock_time.return_value = 0.0
        mock_assign.return_value = True
        mock_setup.return_value = Path("/fake/worktree")
        mock_invoke.return_value = CopilotResult(
            work_item_id="task-cleanup-ex", success=False, error="Failed", attempt_count=1
        )
        # First call at line 315 succeeds, second call in finally raises
        mock_cleanup_wt.side_effect = [None, RuntimeError("cleanup exploded")]

        result = process_work_item(item, interactive=False)
        assert result.success is False

    @patch('pokepoke.workflow.unassign_with_retry', side_effect=RuntimeError("unassign failed"))
    @patch('pokepoke.workflow.cleanup_worktree')
    @patch('pokepoke.workflow.invoke_copilot')
    @patch('pokepoke.workflow._setup_worktree')
    @patch('pokepoke.workflow.assign_and_sync_item')
    @patch('time.time')
    def test_unassign_exception_handled(
        self,
        mock_time: Mock,
        mock_assign: Mock,
        mock_setup: Mock,
        mock_invoke: Mock,
        mock_cleanup_wt: Mock,
        mock_unassign: Mock,
    ) -> None:
        """Covers lines 354-355: unassign exception in finally."""
        item = BeadsWorkItem(
            id="task-unassign-ex", title="Unassign Ex", description="",
            status="open", priority=1, issue_type="task",
        )
        mock_time.return_value = 0.0
        mock_assign.return_value = True
        mock_setup.return_value = Path("/fake/worktree")
        mock_invoke.return_value = CopilotResult(
            work_item_id="task-unassign-ex", success=False, error="Failed", attempt_count=1
        )

        result = process_work_item(item, interactive=False)
        assert result.success is False


class TestWorktreeLockTimeout:
    """Tests that worktree_lock_timeout scales with max_parallel_agents."""

    def test_single_agent_uses_command_timeout(self) -> None:
        """With 1 agent, the lock timeout equals command_timeout (300s default)."""
        from pokepoke.config import ProjectConfig
        cfg = ProjectConfig()
        cfg.command_timeout = 300
        cfg.max_parallel_agents = 1

        # 120.0 * 1 = 120.0 < 300.0, so max returns 300.0
        expected = max(float(cfg.command_timeout), 120.0 * max(1, int(cfg.max_parallel_agents)))
        assert expected == 300.0

    def test_many_agents_scales_timeout(self) -> None:
        """With 10 agents, the lock timeout exceeds command_timeout to accommodate queuing."""
        from pokepoke.config import ProjectConfig
        cfg = ProjectConfig()
        cfg.command_timeout = 300
        cfg.max_parallel_agents = 10

        # 120.0 * 10 = 1200.0 > 300.0, so max returns 1200.0
        expected = max(float(cfg.command_timeout), 120.0 * max(1, int(cfg.max_parallel_agents)))
        assert expected == 1200.0

    @patch('pokepoke.workflow.assign_and_sync_item', return_value=True)
    @patch('pokepoke.workflow._setup_worktree', return_value=None)
    @patch('time.time', return_value=0.0)
    def test_setup_worktree_called_with_scaled_timeout(
        self,
        mock_time: Mock,
        mock_setup: Mock,
        mock_assign: Mock,
    ) -> None:
        """process_work_item passes scaled lock_timeout to _setup_worktree.

        The worktree lock is now acquired inside create_worktree, and the
        timeout is passed via _setup_worktree's lock_timeout parameter.
        """
        from pokepoke.config import ProjectConfig

        item = BeadsWorkItem(
            id="task-scale",
            title="Scale Test",
            description="",
            status="open",
            priority=1,
            issue_type="task",
        )

        cfg = ProjectConfig()
        cfg.command_timeout = 300
        cfg.max_parallel_agents = 10

        with patch('pokepoke.workflow.get_config', return_value=cfg):
            process_work_item(item, interactive=False)

        # _setup_worktree should have been called with lock_timeout=1200.0 (max(300, 120*10))
        mock_setup.assert_called_once()
        call_kwargs = mock_setup.call_args
        timeout_used = call_kwargs[1]['lock_timeout'] if call_kwargs[1] else call_kwargs[0][1]
        assert timeout_used == 1200.0

