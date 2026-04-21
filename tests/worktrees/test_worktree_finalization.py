"""Tests for worktree finalization operations.

Tests cover:
- finalize_work_item orchestration
- check_and_merge_worktree commit counting
- merge_worktree_to_dev delegation to perform_worktree_merge
- close_work_item_and_parents
- check_parent_hierarchy
"""

import json
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from pokepoke.types import BeadsWorkItem
from pokepoke.worktrees.worktree_finalization import (
    check_and_merge_worktree,
    check_parent_hierarchy,
    close_work_item_and_parents,
    finalize_work_item,
    merge_worktree_to_dev,
)


def _make_test_item(item_id: str = "task-1") -> BeadsWorkItem:
    """Create a test work item."""
    return BeadsWorkItem(
        id=item_id,
        title="Test Task",
        description="Test description",
        status="open",
        priority=1,
        issue_type="task",
    )


class TestMergeWorktreeToDevDelegation:
    """Test that merge_worktree_to_dev delegates to handle_worktree_merge."""

    @patch("pokepoke.worktrees.worktree_merge_handler.handle_worktree_merge")
    def test_delegates_to_handle_worktree_merge(self, mock_handle: Mock) -> None:
        """Verify delegation and bool return."""
        mock_handle.return_value = (True, True)
        item = _make_test_item()
        result = merge_worktree_to_dev(item)
        assert result is True
        mock_handle.assert_called_once()
        call_args = mock_handle.call_args
        ctx = call_args[0][0]
        assert ctx.agent_id == item.id
        assert ctx.agent_item is item

    @patch("pokepoke.worktrees.worktree_merge_handler.handle_worktree_merge")
    def test_returns_false_on_merge_failure(self, mock_handle: Mock) -> None:
        mock_handle.return_value = (False, False)
        assert merge_worktree_to_dev(_make_test_item()) is False

    @patch("pokepoke.worktrees.worktree_merge_handler.handle_worktree_merge")
    def test_passes_parent_agent_id(self, mock_handle: Mock) -> None:
        mock_handle.return_value = (True, True)
        merge_worktree_to_dev(_make_test_item(), parent_agent_id="parent-1")
        ctx = mock_handle.call_args[0][0]
        assert ctx.parent_agent_id == "parent-1"

    @patch("pokepoke.worktrees.worktree_merge_handler.handle_worktree_merge")
    def test_uses_explicit_repo_root(self, mock_handle: Mock) -> None:
        mock_handle.return_value = (True, True)
        repo = Path("C:/my-repo")
        merge_worktree_to_dev(_make_test_item(), repo_root=repo)
        ctx = mock_handle.call_args[0][0]
        assert ctx.repo_root == repo

    @patch("pokepoke.worktrees.worktree_merge_handler.handle_worktree_merge")
    def test_uses_explicit_worktree_path(self, mock_handle: Mock) -> None:
        mock_handle.return_value = (True, True)
        wt = Path("C:/worktrees/task-task-1")
        merge_worktree_to_dev(_make_test_item(), worktree_path=wt)
        ctx = mock_handle.call_args[0][0]
        assert ctx.worktree_path == wt

    @patch("pokepoke.worktrees.worktree_merge_handler.handle_worktree_merge")
    def test_defaults_worktree_path_from_repo_root(self, mock_handle: Mock) -> None:
        mock_handle.return_value = (True, True)
        repo = Path("C:/my-repo")
        merge_worktree_to_dev(_make_test_item("abc"), repo_root=repo)
        ctx = mock_handle.call_args[0][0]
        assert ctx.worktree_path == repo / "worktrees" / "task-abc"
class TestFinalizeWorkItem:
    """Test finalize_work_item function (lines 21-29)."""

    @patch("pokepoke.worktrees.worktree_finalization.close_work_item_and_parents")
    @patch("pokepoke.worktrees.worktree_finalization.check_and_merge_worktree")
    def test_success(self, mock_merge: Mock, mock_close: Mock) -> None:
        mock_merge.return_value = True
        item = _make_test_item()
        assert finalize_work_item(item, Path("/wt")) is True
        mock_close.assert_called_once_with(item)

    @patch("pokepoke.worktrees.worktree_finalization.close_work_item_and_parents")
    @patch("pokepoke.worktrees.worktree_finalization.check_and_merge_worktree")
    def test_merge_fails(self, mock_merge: Mock, mock_close: Mock) -> None:
        mock_merge.return_value = False
        assert finalize_work_item(_make_test_item(), Path("/wt")) is False
        mock_close.assert_not_called()
class TestCheckAndMergeWorktree:
    """Test check_and_merge_worktree function."""

    @patch("pokepoke.worktrees.worktree_finalization.merge_worktree_to_dev")
    @patch("pokepoke.worktrees.worktree_finalization.get_default_branch", return_value="main")
    @patch("pokepoke.worktrees.worktree_finalization.run_git")
    def test_has_commits(self, mock_run_git: Mock, mock_branch: Mock, mock_merge: Mock) -> None:
        mock_run_git.return_value = Mock(stdout="3\n")
        mock_merge.return_value = True
        assert check_and_merge_worktree(_make_test_item(), Path("/wt")) is True
        mock_merge.assert_called_once()

    @patch("pokepoke.worktrees.worktree_finalization.merge_worktree_to_dev")
    @patch("pokepoke.worktrees.worktree_finalization.get_default_branch", return_value="main")
    @patch("pokepoke.worktrees.worktree_finalization.run_git")
    def test_has_commits_passes_worktree_path(self, mock_run_git: Mock, mock_branch: Mock, mock_merge: Mock) -> None:
        """Verify worktree_path is forwarded to merge_worktree_to_dev."""
        mock_run_git.return_value = Mock(stdout="3\n")
        mock_merge.return_value = True
        wt = Path("/my/worktree")
        check_and_merge_worktree(_make_test_item(), wt)
        assert mock_merge.call_args.kwargs["worktree_path"] == wt

    @patch("pokepoke.worktrees.worktree_finalization.cleanup_worktree")
    @patch("pokepoke.worktrees.worktree_finalization.get_default_branch", return_value="main")
    @patch("pokepoke.worktrees.worktree_finalization.run_git")
    def test_no_commits(self, mock_run_git: Mock, mock_branch: Mock, mock_cleanup: Mock) -> None:
        mock_run_git.return_value = Mock(stdout="0\n")
        assert check_and_merge_worktree(_make_test_item(), Path("/wt")) is True
        mock_cleanup.assert_called_once_with("task-1", force=True, repo_path=None)

    @patch("pokepoke.worktrees.worktree_finalization.merge_worktree_to_dev")
    @patch("pokepoke.worktrees.worktree_finalization.get_default_branch")
    @patch("pokepoke.worktrees.worktree_finalization.run_git")
    def test_called_process_error_merges_anyway(self, mock_run_git: Mock, mock_branch: Mock, mock_merge: Mock) -> None:
        """CalledProcessError (e.g., branch not found) is recoverable — proceed with merge."""
        import subprocess as real_subprocess
        mock_run_git.side_effect = real_subprocess.CalledProcessError(1, "git")
        mock_merge.return_value = True
        assert check_and_merge_worktree(_make_test_item(), Path("/wt")) is True
        mock_merge.assert_called_once()

    @patch("pokepoke.worktrees.worktree_finalization.merge_worktree_to_dev")
    @patch("pokepoke.worktrees.worktree_finalization.get_default_branch")
    @patch("pokepoke.worktrees.worktree_finalization.run_git")
    def test_timeout_aborts_merge(self, mock_run_git: Mock, mock_branch: Mock, mock_merge: Mock) -> None:
        """TimeoutExpired means git is unresponsive — abort merge."""
        import subprocess as real_subprocess
        mock_run_git.side_effect = real_subprocess.TimeoutExpired("git", 30)
        assert check_and_merge_worktree(_make_test_item(), Path("/wt")) is False
        mock_merge.assert_not_called()

    @patch("pokepoke.worktrees.worktree_finalization.merge_worktree_to_dev")
    @patch("pokepoke.worktrees.worktree_finalization.get_default_branch")
    @patch("pokepoke.worktrees.worktree_finalization.run_git")
    def test_unexpected_exception_aborts_merge(self, mock_run_git: Mock, mock_branch: Mock, mock_merge: Mock) -> None:
        """Unexpected exceptions (OS/resource) abort merge to prevent corruption."""
        mock_run_git.side_effect = OSError("disk full")
        assert check_and_merge_worktree(_make_test_item(), Path("/wt")) is False
        mock_merge.assert_not_called()


class TestCloseWorkItemAndParents:
    """Test close_work_item_and_parents function (lines 189-217)."""

    @patch("pokepoke.worktrees.worktree_finalization.check_parent_hierarchy")
    @patch("pokepoke.worktrees.worktree_finalization.subprocess")
    def test_item_already_closed(self, mock_sub: Mock, mock_hierarchy: Mock) -> None:
        item = _make_test_item()
        mock_sub.run.return_value = Mock(stdout=json.dumps([{"status": "closed"}]))
        close_work_item_and_parents(item)
        mock_hierarchy.assert_called_once_with(item)

    @patch("pokepoke.worktrees.worktree_finalization.check_parent_hierarchy")
    @patch("pokepoke.worktrees.worktree_finalization.close_item")
    @patch("pokepoke.worktrees.worktree_finalization.subprocess")
    def test_item_not_closed_falls_back(self, mock_sub: Mock, mock_close: Mock, mock_hierarchy: Mock) -> None:
        item = _make_test_item()
        mock_sub.run.return_value = Mock(stdout=json.dumps([{"status": "open"}]))
        close_work_item_and_parents(item)
        mock_close.assert_called_once()

    @patch("pokepoke.worktrees.worktree_finalization.check_parent_hierarchy")
    @patch("pokepoke.worktrees.worktree_finalization.close_item")
    @patch("pokepoke.worktrees.worktree_finalization.subprocess")
    def test_exception_closes_item(self, mock_sub: Mock, mock_close: Mock, mock_hierarchy: Mock) -> None:
        item = _make_test_item()
        mock_sub.run.side_effect = Exception("bd not found")
        close_work_item_and_parents(item)
        mock_close.assert_called_once()

    @patch("pokepoke.worktrees.worktree_finalization.check_parent_hierarchy")
    @patch("pokepoke.worktrees.worktree_finalization.close_item")
    @patch("pokepoke.worktrees.worktree_finalization.subprocess")
    def test_empty_data_closes_item(self, mock_sub: Mock, mock_close: Mock, mock_hierarchy: Mock) -> None:
        item = _make_test_item()
        mock_sub.run.return_value = Mock(stdout="[]")
        close_work_item_and_parents(item)
        mock_close.assert_called_once()

    def test_ephemeral_item_skips_beads_operations(self) -> None:
        """Ephemeral items should not trigger any beads operations."""
        item = BeadsWorkItem(
            id="maintenance-janitor-20260318-123456",
            title="Janitor Maintenance",
            description="Cleanup prompt",
            status="in_progress",
            priority=0,
            issue_type="task",
            is_ephemeral=True,
        )
        # Should return immediately without calling subprocess or close_item
        close_work_item_and_parents(item)


class TestCheckParentHierarchy:
    """Test check_parent_hierarchy function (lines 220-230)."""

    @patch("pokepoke.worktrees.worktree_finalization.close_parent_if_complete")
    @patch("pokepoke.worktrees.worktree_finalization.get_parent_id")
    def test_parent_and_grandparent(self, mock_get_parent: Mock, mock_close: Mock) -> None:
        mock_get_parent.side_effect = ["parent-1", "grandparent-1"]
        check_parent_hierarchy(_make_test_item())
        assert mock_close.call_count == 2

    @patch("pokepoke.worktrees.worktree_finalization.close_parent_if_complete")
    @patch("pokepoke.worktrees.worktree_finalization.get_parent_id")
    def test_parent_only(self, mock_get_parent: Mock, mock_close: Mock) -> None:
        mock_get_parent.side_effect = ["parent-1", None]
        check_parent_hierarchy(_make_test_item())
        mock_close.assert_called_once_with("parent-1")

    @patch("pokepoke.worktrees.worktree_finalization.close_parent_if_complete")
    @patch("pokepoke.worktrees.worktree_finalization.get_parent_id")
    def test_no_parent(self, mock_get_parent: Mock, mock_close: Mock) -> None:
        mock_get_parent.return_value = None
        check_parent_hierarchy(_make_test_item())
        mock_close.assert_not_called()
