"""Unit tests for workflow finalization operations.

This module tests work item finalization including:
- Work item finalization orchestration
- Merging worktree to development branch
- Closing work items and parent hierarchy
- Parent hierarchy traversal and completion
"""

import subprocess
from pathlib import Path
from unittest.mock import Mock, patch

from pokepoke.types_beads import BeadsWorkItem
from pokepoke.worktrees.worktree_finalization import (
    check_parent_hierarchy,
    close_work_item_and_parents,
    finalize_work_item,
    merge_worktree_to_dev,
)


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


class TestMergeWorktreeToDev:
    """Test merge_worktree_to_dev function (delegates to handle_worktree_merge)."""

    @patch('pokepoke.worktrees.worktree_merge_handler.handle_worktree_merge')
    def test_successful_merge(self, mock_handle: Mock) -> None:
        """Test successful worktree merge."""
        item = BeadsWorkItem(
            id="task-1",
            title="Task 1",
            description="",
            status="open",
            priority=1,
            issue_type="task"
        )

        mock_handle.return_value = (True, True)

        result = merge_worktree_to_dev(item)

        assert result is True
        mock_handle.assert_called_once()

    @patch('pokepoke.worktrees.worktree_merge_handler.handle_worktree_merge')
    def test_merge_fails_autofix_succeeds(self, mock_handle: Mock) -> None:
        """Test merge returns True when handle_worktree_merge succeeds."""
        item = BeadsWorkItem(id="task-1", title="T", description="", status="open", priority=1, issue_type="task")
        mock_handle.return_value = (True, True)

        result = merge_worktree_to_dev(item)
        assert result is True

    @patch('pokepoke.worktrees.worktree_merge_handler.handle_worktree_merge')
    def test_repo_not_ready_autofix_fails(self, mock_handle: Mock) -> None:
        """Test when merge fails."""
        item = BeadsWorkItem(id="task-1", title="Task 1", description="", status="open", priority=1, issue_type="task")
        mock_handle.return_value = (False, False)

        result = merge_worktree_to_dev(item)
        assert result is False

    @patch('pokepoke.worktrees.worktree_merge_handler.handle_worktree_merge')
    def test_repo_not_ready_autofix_succeeds(self, mock_handle: Mock) -> None:
        """Test merge returns True after successful recovery."""
        item = BeadsWorkItem(id="task-1", title="T", description="", status="open", priority=1, issue_type="task")
        mock_handle.return_value = (True, True)

        result = merge_worktree_to_dev(item)
        assert result is True

    @patch('pokepoke.worktrees.worktree_merge_handler.handle_worktree_merge')
    def test_merge_fails_autofix_fails(self, mock_handle: Mock) -> None:
        """Test when merge fails and recovery fails."""
        item = BeadsWorkItem(id="task-1", title="T", description="", status="open", priority=1, issue_type="task")
        mock_handle.return_value = (False, False)

        result = merge_worktree_to_dev(item)
        assert result is False


class TestCloseWorkItemAndParents:
    """Test close_work_item_and_parents function."""

    @patch('pokepoke.worktrees.worktree_finalization.check_parent_hierarchy')
    @patch('pokepoke.worktrees.worktree_finalization.close_item')
    @patch('pokepoke.worktrees.worktree_finalization._run_bd_with_retry')
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
        mock_check_parents.assert_called_once_with(item, item_logger=None)

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
        mock_check_parents.assert_called_once_with(item, item_logger=None)

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
        mock_check_parents.assert_called_once_with(item, item_logger=None)


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
