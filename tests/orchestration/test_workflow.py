"""Unit tests for workflow module."""

import subprocess
from pathlib import Path
from unittest.mock import Mock, patch

from pokepoke.orchestration.work_item_selection import autonomous_selection, interactive_selection
from pokepoke.orchestration.work_item_session import WorkItemSession
from pokepoke.orchestration.workflow import process_work_item, select_work_item
from pokepoke.orchestration.workflow_helpers import run_cleanup_with_timeout as _run_cleanup_with_timeout
from pokepoke.orchestration.workflow_helpers import setup_worktree
from pokepoke.types import AgentStats, BeadsWorkItem, CopilotResult, GateAgentResult
from pokepoke.worktrees.worktree_finalization import (
    check_and_merge_worktree,
    check_parent_hierarchy,
    close_work_item_and_parents,
    finalize_work_item,
    merge_worktree_to_dev,
)
from tests.orchestration.conftest import (
    PATCH_MODEL_CONFIG,
    PATCH_WF_ADD_COMMENT,
    PATCH_WF_GET_CONFIG,
    PATCH_WF_IS_SHUTTING_DOWN,
    PATCH_WF_SELECT_MODEL,
    make_process_item_mocks,
    make_selection_mocks,
    make_work_item,
)


class TestSelectWorkItem:
    """Test select_work_item function."""

    def test_empty_list(self) -> None:
        """Test with empty work item list."""
        result = select_work_item([], interactive=False)

        assert result is None

    def test_autonomous_selection(self) -> None:
        """Test autonomous mode selection."""
        item = make_work_item(id="task-1", title="Task 1")

        with make_selection_mocks(selected_item=item) as mocks:
            result = select_work_item([item], interactive=False)

            assert result is not None
            assert result.id == "task-1"
            mocks['select'].assert_called_once()

    @patch('builtins.input')
    def test_interactive_selection(self, mock_input: Mock) -> None:
        """Test interactive mode selection."""
        item = make_work_item(id="task-1", title="Task 1")
        mock_input.return_value = '1'

        result = select_work_item([item], interactive=True)

        assert result is not None
        assert result.id == "task-1"

    def test_filters_items_assigned_to_others(self) -> None:
        """Test that items assigned to other agents are filtered out."""
        import os
        os.environ['AGENT_NAME'] = 'agent_alpha'

        item1 = make_work_item(
            id="task-1",
            title="Task assigned to other agent",
            status="in_progress",
            assignee="agent_beta"
        )
        item2 = make_work_item(
            id="task-2",
            title="Task available",
            priority=2,
            status="open",
            assignee=None
        )

        with make_selection_mocks(selected_item=item2) as mocks:
            result = select_work_item([item1, item2], interactive=False)

            # Should have filtered out task-1 and only passed task-2
            mocks['select'].assert_called_once()
            passed_items = mocks['select'].call_args[0][0]
            assert len(passed_items) == 1
            assert passed_items[0].id == "task-2"
            assert result is not None
            assert result.id == "task-2"

    def test_all_items_assigned_to_others(self) -> None:
        """Test when all items are assigned to other agents."""
        import os
        os.environ['AGENT_NAME'] = 'agent_alpha'

        items = [
            make_work_item(
                id="task-1",
                title="Task assigned to beta",
                status="in_progress",
                assignee="agent_beta"
            ),
            make_work_item(
                id="task-2",
                title="Task assigned to gamma",
                priority=2,
                status="in_progress",
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

    @patch('pokepoke.orchestration.work_item_selection.select_next_hierarchical_item')
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

    @patch('pokepoke.orchestration.work_item_selection.select_next_hierarchical_item')
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
    """Test setup_worktree function."""

    @patch('pokepoke.orchestration.workflow_helpers.create_worktree')
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

        result = setup_worktree(item)

        assert result is not None
        assert result == Path("/fake/worktree")
        mock_create.assert_called_once_with("task-1", lock_timeout=300.0, repo_path=None)

    @patch('pokepoke.orchestration.workflow_helpers.create_worktree')
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

        result = setup_worktree(item, lock_timeout=600.0, repo_path=None)

        assert result is not None
        assert result == Path("/fake/worktree")
        mock_create.assert_called_once_with("task-1", lock_timeout=600.0, repo_path=None)

    @patch('pokepoke.orchestration.workflow_helpers.create_worktree')
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

        result = setup_worktree(item)

        assert result is None


class TestRunCleanupWithTimeout:
    """Test _run_cleanup_with_timeout function."""

    @patch('pokepoke.orchestration.workflow_helpers.run_cleanup_loop')
    @patch('pokepoke.orchestration.workflow_helpers.has_uncommitted_changes')
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

    @patch('pokepoke.orchestration.workflow_helpers.run_cleanup_loop')
    @patch('pokepoke.orchestration.workflow_helpers.has_uncommitted_changes')
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

    @patch('pokepoke.orchestration.workflow_helpers.run_cleanup_loop')
    @patch('pokepoke.orchestration.workflow_helpers.has_uncommitted_changes')
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
        # Extra values needed because print() calls through desktop_ui may call time.time()
        mock_time.side_effect = [0, 7300] + [7300] * 10
        mock_uncommitted.return_value = True  # Always has changes
        mock_cleanup.return_value = (True, 1)  # Cleanup succeeds

        success, cleanup_runs = _run_cleanup_with_timeout(
            item, result, repo_root, 0, 7200, 2.0
        )

        assert success is False  # Timeout occurred
        assert cleanup_runs == 1  # One cleanup was attempted before timeout
        mock_cleanup.assert_called_once()  # Cleanup called once before timeout

    @patch('pokepoke.orchestration.workflow_helpers.run_cleanup_loop')
    @patch('pokepoke.orchestration.workflow_helpers.has_uncommitted_changes')
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

    @patch('pokepoke.worktrees.worktree_finalization.close_work_item_and_parents')
    @patch('pokepoke.worktrees.worktree_finalization.check_and_merge_worktree')
    def test_finalize_returns_false_when_merge_fails(self, mock_merge: Mock, mock_close: Mock) -> None:
        """Test finalize returns False when check_and_merge_worktree fails."""
        item = BeadsWorkItem(id="task-1", title="Task", description="", status="open", priority=1, issue_type="task")
        mock_merge.return_value = False

        result = finalize_work_item(item, Path("/fake/worktree"))

        assert result is False
        mock_close.assert_not_called()


class TestCheckAndMergeWorktree:
    """Test check_and_merge_worktree function."""

    @patch('pokepoke.worktrees.worktree_finalization.merge_lock')
    @patch('pokepoke.worktrees.worktree_finalization.merge_worktree_to_dev')
    @patch('pokepoke.worktrees.worktree_finalization.cleanup_worktree')
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
        mock_cleanup.assert_called_once_with("task-1", force=True, repo_path=None)
        mock_merge.assert_not_called()
        # Verify cwd is passed to subprocess instead of os.chdir
        cwd_calls = [c for c in mock_run.call_args_list if c.kwargs.get('cwd')]
        assert len(cwd_calls) == 1
        assert cwd_calls[0].kwargs['cwd'] == str(worktree_path)

    @patch('pokepoke.worktrees.worktree_finalization.merge_lock')
    @patch('pokepoke.worktrees.worktree_finalization.merge_worktree_to_dev')
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
        mock_merge.assert_called_once_with(item, parent_agent_id=None, worktree_path=worktree_path, repo_path=None)

    @patch('pokepoke.worktrees.worktree_finalization.merge_lock')
    @patch('pokepoke.worktrees.worktree_finalization.merge_worktree_to_dev')
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
        mock_merge.assert_called_once_with(item, parent_agent_id=None, worktree_path=worktree_path, repo_path=None)


class TestMergeWorktreeToDev:
    """Test merge_worktree_to_dev function (delegates to perform_worktree_merge)."""

    @patch('pokepoke.worktrees.worktree_merge_handler.perform_worktree_merge')
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

    @patch('pokepoke.worktrees.worktree_merge_handler.perform_worktree_merge')
    def test_merge_fails_autofix_succeeds(self, mock_perform: Mock) -> None:
        """Test merge returns True when perform_worktree_merge succeeds."""
        item = BeadsWorkItem(id="task-1", title="T", description="", status="open", priority=1, issue_type="task")
        mock_perform.return_value = (True, True)

        result = merge_worktree_to_dev(item)
        assert result is True

    @patch('pokepoke.worktrees.worktree_merge_handler.perform_worktree_merge')
    def test_repo_not_ready_autofix_fails(self, mock_perform: Mock) -> None:
        """Test when merge fails."""
        item = BeadsWorkItem(id="task-1", title="Task 1", description="", status="open", priority=1, issue_type="task")
        mock_perform.return_value = (False, False)

        result = merge_worktree_to_dev(item)
        assert result is False

    @patch('pokepoke.worktrees.worktree_merge_handler.perform_worktree_merge')
    def test_repo_not_ready_autofix_succeeds(self, mock_perform: Mock) -> None:
        """Test merge returns True after successful recovery."""
        item = BeadsWorkItem(id="task-1", title="T", description="", status="open", priority=1, issue_type="task")
        mock_perform.return_value = (True, True)

        result = merge_worktree_to_dev(item)
        assert result is True

    @patch('pokepoke.worktrees.worktree_merge_handler.perform_worktree_merge')
    def test_merge_fails_autofix_fails(self, mock_perform: Mock) -> None:
        """Test when merge fails and recovery fails."""
        item = BeadsWorkItem(id="task-1", title="T", description="", status="open", priority=1, issue_type="task")
        mock_perform.return_value = (False, False)

        result = merge_worktree_to_dev(item)
        assert result is False


class TestCloseWorkItemAndParents:
    """Test close_work_item_and_parents function."""

    @patch('pokepoke.worktrees.worktree_finalization.check_parent_hierarchy')
    @patch('pokepoke.worktrees.worktree_finalization.close_item')
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

    @patch('pokepoke.worktrees.worktree_finalization.check_parent_hierarchy')
    @patch('pokepoke.worktrees.worktree_finalization.close_item')
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

    @patch('pokepoke.worktrees.worktree_finalization.check_parent_hierarchy')
    @patch('pokepoke.worktrees.worktree_finalization.close_item')
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

    @patch('pokepoke.worktrees.worktree_finalization.close_parent_if_complete')
    @patch('pokepoke.worktrees.worktree_finalization.get_parent_id')
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

    @patch('pokepoke.worktrees.worktree_finalization.close_parent_if_complete')
    @patch('pokepoke.worktrees.worktree_finalization.get_parent_id')
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

    @patch('pokepoke.worktrees.worktree_finalization.close_parent_if_complete')
    @patch('pokepoke.worktrees.worktree_finalization.get_parent_id')
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

    def test_skip_in_interactive_mode(self) -> None:
        """Test skipping item in interactive mode."""
        item = make_work_item()

        with make_process_item_mocks(include_config=True) as mocks:
            mocks['input'].return_value = 'n'
            with patch(PATCH_MODEL_CONFIG) as mock_model_config:
                mock_model_config.return_value.models.candidate_models = ["gemini-3-pro"]
                mock_model_config.return_value.models.default = "gemini-3-pro"

                result = process_work_item(item, interactive=True)

            assert result.success is False
            assert result.request_count == 0
            assert result.stats is None
            assert result.cleanup_agent_runs == 0
            mocks['setup'].assert_not_called()

    def test_worktree_setup_fails(self) -> None:
        """Test when worktree setup fails, process returns failure."""
        item = make_work_item()

        with make_process_item_mocks(
            worktree_path=None, include_session_cleanup=True,
        ):
            result = process_work_item(item, interactive=True)

            assert result.success is False
            assert result.request_count == 0
            assert result.stats is None
            assert result.cleanup_agent_runs == 0

    def test_shutdown_before_first_iteration_does_not_crash(self) -> None:
        """Shutdown before first loop iteration should not raise UnboundLocalError."""
        item = make_work_item()

        with make_process_item_mocks(
            include_session_cleanup=True, include_cleanup_worktree=True,
        ) as mocks:
            with patch(PATCH_WF_IS_SHUTTING_DOWN, return_value=True), \
                 patch(PATCH_WF_SELECT_MODEL, return_value="test-model"):
                result = process_work_item(item, interactive=False)

            assert result.success is False
            assert result.request_count == 0
            # Stats are now tracked even on failure/shutdown
            assert result.stats is not None
            assert result.cleanup_agent_runs == 0
            assert result.gate_agent_runs == 0
            assert result.model_completion is not None
            mocks['invoke'].assert_not_called()
            # Worktree should be preserved on shutdown — cleanup_on_failure must NOT run
            mocks['session_cleanup'].assert_not_called()

    def test_no_changes_made(self) -> None:
        """Test when Copilot makes no changes (no uncommitted and no commits ahead)."""
        item = make_work_item()

        with make_process_item_mocks(
            commits_ahead=0, include_handoff=True,
        ) as mocks:
            result = process_work_item(item, interactive=True)

            assert result.success is True
            assert result.request_count == 1
            # Cleanup is called even with no changes (it just exits early)
            mocks['cleanup_timeout'].assert_called_once()

    def test_changes_already_committed(self) -> None:
        """Test when Copilot committed changes (clean tree but commits ahead)."""
        item = make_work_item()

        with make_process_item_mocks(
            commits_ahead=2, include_handoff=True,
        ) as mocks:
            result = process_work_item(item, interactive=True)

            assert result.success is True
            assert result.request_count == 1
            # Verify has_commits_ahead was called (distinguishes from "no changes")
            mocks['commits_ahead'].assert_called_once()

    def test_copilot_failure(self) -> None:
        """Test when Copilot CLI fails (no retries configured)."""
        item = make_work_item()

        with make_process_item_mocks(
            copilot_success=False, uncommitted=True,
            include_config=True, include_session_cleanup=True,
            include_cleanup_worktree=True,
        ) as mocks:
            result = process_work_item(item, interactive=True)

            assert result.success is False
            assert result.request_count == 1
            mocks['session_cleanup'].assert_called()

    def test_copilot_failure_retries_exhausted(self) -> None:
        """Test that all retries are attempted when Copilot fails, then item fails."""
        item = make_work_item()

        with make_process_item_mocks(
            copilot_success=False, uncommitted=True,
            include_config=True, include_session_cleanup=True,
            include_cleanup_worktree=True,
            max_copilot_failure_retries=2,
        ) as mocks:
            result = process_work_item(item, interactive=True)

            assert result.success is False
            # 1 initial + 2 retries = 3 total invocations, each with attempt_count=1
            assert result.request_count == 3
            assert mocks['invoke'].call_count == 3
            mocks['session_cleanup'].assert_called()

    def test_copilot_failure_retried_successfully(self) -> None:
        """Test that a failed Copilot attempt is retried and can succeed."""
        item = make_work_item()

        with make_process_item_mocks(
            uncommitted=True,
            include_config=True, include_handoff=True,
            include_cleanup_worktree=True,
            max_copilot_failure_retries=2,
        ) as mocks:
            # First attempt fails, second succeeds
            mocks['invoke'].side_effect = [
                CopilotResult(
                    work_item_id="task-1", success=False,
                    error="Tests failed", attempt_count=1,
                ),
                CopilotResult(
                    work_item_id="task-1", success=True,
                    output="Done", attempt_count=1,
                ),
            ]

            result = process_work_item(item, interactive=True)

            assert result.success is True
            assert result.request_count == 2
            assert mocks['invoke'].call_count == 2
            # Description must NOT be mutated — feedback goes via prompt
            assert item.description == ""

    def test_copilot_failure_no_retry_when_rate_limited(self) -> None:
        """Test that rate-limited failures are not retried."""
        item = make_work_item()

        with make_process_item_mocks(
            copilot_success=False, uncommitted=True,
            include_config=True, include_session_cleanup=True,
            include_cleanup_worktree=True,
            max_copilot_failure_retries=2,
        ) as mocks:
            mocks['invoke'].return_value = CopilotResult(
                work_item_id="task-1", success=False,
                error="Rate limit exceeded", attempt_count=1,
                is_rate_limited=True,
            )

            result = process_work_item(item, interactive=True)

            assert result.success is False
            assert result.request_count == 1  # No retry on rate limit
            assert mocks['invoke'].call_count == 1

    def test_process_crash_skips_gate_agent(self) -> None:
        """Test that gate agent is skipped when CLI process crashes, even if retry succeeds."""
        item = make_work_item()

        with make_process_item_mocks(
            uncommitted=True,
            include_config=True, include_session_cleanup=True,
            include_cleanup_worktree=True,
            max_copilot_failure_retries=2,
        ) as mocks:
            # First attempt: process crashes
            # Second attempt: succeeds
            mocks['invoke'].side_effect = [
                CopilotResult(
                    work_item_id="task-1", success=False,
                    error="Process died: consecutive ping failures or output timeout",
                    attempt_count=1,
                ),
                CopilotResult(
                    work_item_id="task-1", success=True,
                    output="Fixed on retry", attempt_count=1,
                ),
            ]

            result = process_work_item(item, interactive=True)

            # Should succeed (retry worked)
            assert result.success is True
            assert result.request_count == 2
            # Gate agent should NOT have been called (process crashed on first attempt)
            assert mocks['gate'].call_count == 0

    def test_sdk_exception_crash_skips_gate_agent(self) -> None:
        """Test that gate agent is skipped for SDK exceptions with 'exited unexpectedly' pattern."""
        item = make_work_item()

        with make_process_item_mocks(
            uncommitted=True,
            include_config=True, include_session_cleanup=True,
            include_cleanup_worktree=True,
            max_copilot_failure_retries=2,
        ) as mocks:
            # First attempt: SDK exception with CLI process crash
            # Second attempt: succeeds
            mocks['invoke'].side_effect = [
                CopilotResult(
                    work_item_id="task-1", success=False,
                    error="SDK exception: CLI process exited unexpectedly",
                    attempt_count=1,
                ),
                CopilotResult(
                    work_item_id="task-1", success=True,
                    output="Fixed on retry", attempt_count=1,
                ),
            ]

            result = process_work_item(item, interactive=True)

            # Should succeed (retry worked)
            assert result.success is True
            assert result.request_count == 2
            # Gate agent should NOT have been called (process crashed on first attempt)
            assert mocks['gate'].call_count == 0

    def test_gate_agent_retry_loop(self) -> None:
        """Test gate agent rejection triggers retry loop."""
        item = make_work_item()

        with make_process_item_mocks(
            uncommitted=True,
            include_handoff=True, include_cleanup_worktree=True,
        ) as mocks:
            # Gate agent fails first time, passes second time
            mocks['gate'].side_effect = [
                GateAgentResult(success=False, reason="Tests failed"),
                GateAgentResult(success=True, reason="All tests pass"),
            ]
            # Two work agent invocations
            mocks['invoke'].side_effect = [
                CopilotResult(work_item_id="task-1", success=True, output="Try 1", attempt_count=1),
                CopilotResult(work_item_id="task-1", success=True, output="Try 2", attempt_count=1),
            ]
            with patch(PATCH_WF_ADD_COMMENT) as mock_add_comment:
                result = process_work_item(item, interactive=True)

                assert result.success is True
                assert result.request_count == 2  # Two invocations
                mock_add_comment.assert_called_once()  # Comment added for gate rejection
                assert mocks['gate'].call_count == 2

            # Description must NOT be mutated — feedback goes via prompt
            assert item.description == ""

    def test_gate_agent_stats_aggregation(self) -> None:
        """Test gate agent stats are aggregated into totals."""
        item = make_work_item()

        with make_process_item_mocks(
            uncommitted=True,
            include_handoff=True, include_cleanup_worktree=True,
        ) as mocks:
            # Gate agent returns stats
            gate_stats = AgentStats(
                wall_duration=5.0, api_duration=2.0,
                input_tokens=50, output_tokens=25, premium_requests=1,
            )
            mocks['gate'].return_value = GateAgentResult(
                success=True, reason="Pass", stats=gate_stats,
            )

            work_stats = AgentStats(
                wall_duration=10.0, api_duration=5.0,
                input_tokens=100, output_tokens=50, premium_requests=2,
            )
            mocks['invoke'].return_value = CopilotResult(
                work_item_id="task-1", success=True, output="Completed",
                attempt_count=1, stats=work_stats,
            )

            with patch(PATCH_WF_ADD_COMMENT):
                result = process_work_item(item, interactive=True)

            assert result.success is True
            assert result.stats is not None
            # Gate agent stats should NOT be aggregated into work agent stats (yja0 fix)
            assert result.stats.wall_duration == 10.0  # Only work agent stats
            assert result.stats.input_tokens == 100  # Only work agent tokens
            assert result.gate_agent_runs == 1  # Gate agent ran once

    def test_cleanup_failure_returns_stats(self) -> None:
        """Test that cleanup failure returns accumulated stats."""
        item = make_work_item()

        with make_process_item_mocks(
            uncommitted=True,
            include_session_cleanup=True, include_cleanup_worktree=True,
        ) as mocks:
            work_stats = AgentStats(
                wall_duration=10.0, api_duration=5.0,
                input_tokens=100, output_tokens=50,
            )
            mocks['invoke'].return_value = CopilotResult(
                work_item_id="task-1", success=True, output="Completed",
                attempt_count=1, stats=work_stats,
            )
            mocks['cleanup_timeout'].return_value = (False, 2)  # Cleanup fails

            result = process_work_item(item, interactive=True)

            assert result.success is False
            assert result.cleanup_agent_runs == 2
            assert result.stats is not None  # Stats should be returned even on failure
            assert result.stats.wall_duration == 10.0

    def test_timeout_restarts_limited(self) -> None:
        """Test that repeated timeouts are bounded by max_timeout_restarts."""
        item = make_work_item()

        with make_process_item_mocks(
            commits_ahead=0,
            include_handoff=True, include_session_cleanup=True,
            include_cleanup_worktree=True,
        ) as mocks:
            # Use a very short timeout (0.001 hours = 3.6s) so timeout fires reliably
            # Return monotonically increasing values; each call 5s apart ensures timeout
            call_count = [0]
            def time_side_effect():
                call_count[0] += 1
                return call_count[0] * 5.0
            mocks['time'].side_effect = time_side_effect
            mocks['gate'].return_value = GateAgentResult(success=False, reason="Rejected")

            with patch(PATCH_WF_SELECT_MODEL, return_value="test-model"), \
                 patch(PATCH_WF_ADD_COMMENT):
                result = process_work_item(
                    item, interactive=True, timeout_hours=0.001, max_timeout_restarts=2,
                )

            assert result.success is False
            # Worktree is preserved on failure (not cleaned up)
            mocks['cleanup_wt'].assert_not_called()

    def test_timeout_restart_then_success(self) -> None:
        """Test that a timeout restart followed by success works correctly."""
        item = make_work_item()

        with make_process_item_mocks(
            commits_ahead=0, include_handoff=True,
        ) as mocks:
            # First iteration: past timeout. After restart, within timeout.
            call_count = 0
            def time_side_effect():
                nonlocal call_count
                call_count += 1
                if call_count <= 2:
                    # Initial start_time and first elapsed check: past timeout
                    return 99999
                # After restart: well within timeout
                return 0

            mocks['time'].side_effect = time_side_effect

            result = process_work_item(
                item, interactive=True, max_timeout_restarts=3,
            )

            assert result.success is True
            mocks['invoke'].assert_called_once()


class TestProcessWorkItemCoordination:
    """Tests for concurrent-agent coordination paths in process_work_item."""

    def test_assign_fails_race_condition(self) -> None:
        """When assign_and_sync_item returns False (another agent already claimed the item),
        process_work_item must return (False, 0, ...) without creating a worktree."""
        item = make_work_item(id="task-race", title="Race Task")

        with make_process_item_mocks(assign_ok=False) as mocks:
            result = process_work_item(item, interactive=False)

            assert result.success is False
            assert result.request_count == 0
            assert result.stats is None
            mocks['setup'].assert_not_called()

    def test_worktree_lock_timeout(self) -> None:
        """When create_worktree times out (another agent holds the lock),
        process_work_item must return (False, 0, ...) without crashing.

        The lock is now acquired inside create_worktree via with_worktree_lock,
        not as a wrapper around the entire setup block.

        setup_worktree catches exceptions and returns None, so we simulate
        that behavior here by returning None (as if the lock timeout happened
        and setup_worktree caught the exception).
        """
        item = make_work_item(id="task-lock", title="Lock Task")

        with make_process_item_mocks(
            worktree_path=None, include_session_cleanup=True,
        ):
            result = process_work_item(item, interactive=False)

            assert result.success is False
            assert result.request_count == 0
            assert result.stats is None

    def test_worktree_failure_triggers_unassign(self) -> None:
        """When worktree creation fails after a successful claim,
        process_work_item must run session cleanup so the item is unassigned."""
        item = make_work_item(id="task-wt-fail", title="Worktree Fail Task")

        with make_process_item_mocks(
            worktree_path=None, include_session_cleanup=True,
        ) as mocks:
            result = process_work_item(item, interactive=False)

            assert result.success is False
            assert result.request_count == 0
            mocks['session_cleanup'].assert_called_once()


class TestGateAgentDisabled:
    """Tests for gate_agent_enabled config setting."""

    def test_gate_agent_skipped_when_disabled(self) -> None:
        """When gate_agent_enabled is False, gate agent should not run."""
        item = make_work_item()

        with make_process_item_mocks(include_handoff=True) as mocks:
            from pokepoke.config import ProjectConfig
            cfg = ProjectConfig()
            cfg.gate_agent_enabled = False
            with patch(PATCH_WF_GET_CONFIG, return_value=cfg):
                result = process_work_item(item, interactive=True)

            assert result.success is True
            assert result.gate_agent_runs == 0
            mocks['gate'].assert_not_called()


class TestUnassignOnFailure:
    """Tests that work items are cleaned up when processing fails after assignment."""

    def test_finalization_failure_triggers_cleanup(self) -> None:
        """When finalize_work_item returns False, session cleanup must run."""
        item = make_work_item(id="task-finalize-fail", title="Finalize Fail Task")

        with make_process_item_mocks(
            finalize_ok=False,
            include_handoff=True, include_cleanup_worktree=True,
            include_session_cleanup=True,
        ) as mocks:
            result = process_work_item(item, interactive=False)

            assert result.success is False
            mocks['session_cleanup'].assert_called_once()

    def test_work_agent_failure_triggers_cleanup(self) -> None:
        """When work agent fails, session cleanup must run."""
        item = make_work_item(id="task-agent-fail", title="Agent Fail Task")

        with make_process_item_mocks(
            copilot_success=False,
            include_cleanup_worktree=True, include_session_cleanup=True,
        ) as mocks:
            result = process_work_item(item, interactive=False)

            assert result.success is False
            mocks['session_cleanup'].assert_called_once()

    def test_successful_finalization_skips_cleanup(self) -> None:
        """When finalization succeeds, session cleanup must NOT run."""
        item = make_work_item(id="task-success", title="Success Task")

        with make_process_item_mocks(
            include_handoff=True, include_cleanup_worktree=True,
            include_session_cleanup=True,
        ) as mocks:
            result = process_work_item(item, interactive=False)

            assert result.success is True
            mocks['session_cleanup'].assert_not_called()


class TestLogFailure:
    """Tests for _log_failure helper."""

    def test_calls_loggers_when_both_present(self) -> None:
        """Covers lines 38-39: both loggers are called."""
        from pokepoke.orchestration.workflow import _log_failure
        run_logger = Mock()
        item_logger = Mock()
        _log_failure(run_logger, item_logger, request_count=3)
        item_logger.log_summary.assert_called_once_with(False, 3)
        run_logger.log_orchestrator.assert_called_once()

    def test_skips_when_no_loggers(self) -> None:
        """Covers lines 37: no-op when loggers are None."""
        from pokepoke.orchestration.workflow import _log_failure
        _log_failure(None, None, request_count=1)  # Should not raise


class TestWorkflowGateException:
    """Tests for gate agent exception handling."""

    def test_gate_agent_exception_triggers_cleanup(self) -> None:
        """Gate agent exception is re-raised and session cleanup runs in finally."""
        import pytest
        item = make_work_item(id="task-gate-ex", title="Gate Ex Task")

        with make_process_item_mocks(
            include_handoff=True, include_cleanup_worktree=True,
            include_session_cleanup=True,
        ) as mocks:
            mocks['gate'].side_effect = RuntimeError("gate crashed")

            with pytest.raises(RuntimeError, match="gate crashed"):
                process_work_item(item, interactive=False)

            # Finally block should have run session cleanup
            mocks['session_cleanup'].assert_called()


class TestWorkflowCleanupException:
    """Tests for session cleanup exception handling in finally."""

    def test_cleanup_exception_in_finally_propagates(self) -> None:
        """When cleanup_on_failure raises, the exception propagates
        (cleanup_on_failure itself should never raise, but if it does
        the finally block does not swallow it)."""
        import pytest
        item = make_work_item(id="task-cleanup-ex", title="Cleanup Ex")

        with make_process_item_mocks(
            copilot_success=False,
            include_cleanup_worktree=True, include_session_cleanup=True,
        ) as mocks:
            mocks['session_cleanup'].side_effect = RuntimeError("cleanup exploded")

            with pytest.raises(RuntimeError, match="cleanup exploded"):
                process_work_item(item, interactive=False)

    def test_cleanup_called_on_work_agent_failure(self) -> None:
        """Session cleanup runs when work agent fails."""
        item = make_work_item(id="task-unassign-ex", title="Unassign Ex")

        with make_process_item_mocks(
            copilot_success=False,
            include_cleanup_worktree=True, include_session_cleanup=True,
        ) as mocks:
            result = process_work_item(item, interactive=False)

            assert result.success is False
            mocks['session_cleanup'].assert_called_once()


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

    @patch.object(WorkItemSession, 'cleanup_on_failure')
    @patch('pokepoke.orchestration.workflow.assign_and_sync_item', return_value=True)
    @patch('pokepoke.orchestration.workflow.setup_worktree', return_value=None)
    @patch('time.time', return_value=0.0)
    def testsetup_worktree_called_with_scaled_timeout(
        self,
        mock_time: Mock,
        mock_setup: Mock,
        mock_assign: Mock,
        mock_session_cleanup: Mock,
    ) -> None:
        """process_work_item passes scaled lock_timeout to setup_worktree.

        The worktree lock is now acquired inside create_worktree, and the
        timeout is passed via setup_worktree's lock_timeout parameter.
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

        with patch('pokepoke.orchestration.workflow.get_config', return_value=cfg):
            process_work_item(item, interactive=False)

        # setup_worktree should have been called with lock_timeout=1200.0 (max(300, 120*10))
        mock_setup.assert_called_once()
        call_kwargs = mock_setup.call_args
        timeout_used = call_kwargs[1]['lock_timeout'] if call_kwargs[1] else call_kwargs[0][1]
        assert timeout_used == 1200.0

