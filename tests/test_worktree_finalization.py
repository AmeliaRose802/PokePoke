"""Tests for worktree finalization merge conflict recovery paths.

This module tests the critical merge conflict handling code in worktree_finalization.py
(lines 117-177), specifically:
- Conflict detection when is_merge_in_progress() returns True
- Cleanup agent invocation and retry logic
- abort_merge() calls and return value handling
- Retry merge after cleanup success/failure scenarios
"""

from contextlib import nullcontext
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

import json

from pokepoke.types import BeadsWorkItem
from pokepoke.worktree_finalization import (
    merge_worktree_to_dev,
    finalize_work_item,
    check_and_merge_worktree,
    close_work_item_and_parents,
    check_parent_hierarchy,
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


class TestMergeConflictDetection:
    """Test merge conflict detection branch (lines 119-126)."""

    @patch("pokepoke.git_operations.abort_merge")
    @patch("pokepoke.git_operations.is_merge_in_progress")
    @patch("pokepoke.git_operations.get_unmerged_files")
    @patch("pokepoke.cleanup_agents.invoke_merge_conflict_cleanup_agent")
    @patch("pokepoke.worktree_finalization.merge_worktree")
    @patch("pokepoke.worktree_finalization.check_main_repo_ready_for_merge")
    def test_conflict_detected_with_is_merge_in_progress_true(
        self,
        mock_check: Mock,
        mock_merge: Mock,
        mock_conflict_cleanup: Mock,
        mock_get_unmerged: Mock,
        mock_is_merging: Mock,
        mock_abort: Mock,
    ) -> None:
        """Test conflict branch when is_merge_in_progress returns True."""
        item = _make_test_item()
        mock_check.return_value = (True, "")
        # First merge fails, second succeeds (after cleanup)
        mock_merge.side_effect = [(False, ["file1.py", "file2.py"]), (True, [])]
        # First: conflict detection, second: check after cleanup (still in progress), third: after abort
        mock_is_merging.side_effect = [True, True, False]
        mock_get_unmerged.return_value = ["file1.py", "file2.py"]
        mock_conflict_cleanup.return_value = (True, None)
        mock_abort.return_value = (True, "")

        result = merge_worktree_to_dev(item)

        assert result is True
        # Verify is_merge_in_progress was checked during conflict handling
        assert mock_is_merging.call_count >= 1
        mock_conflict_cleanup.assert_called_once()

    @patch("pokepoke.git_operations.abort_merge")
    @patch("pokepoke.git_operations.is_merge_in_progress")
    @patch("pokepoke.git_operations.get_unmerged_files")
    @patch("pokepoke.cleanup_agents.invoke_merge_conflict_cleanup_agent")
    @patch("pokepoke.worktree_finalization.merge_worktree")
    @patch("pokepoke.worktree_finalization.check_main_repo_ready_for_merge")
    def test_conflict_displays_unmerged_files_when_is_merging(
        self,
        mock_check: Mock,
        mock_merge: Mock,
        mock_conflict_cleanup: Mock,
        mock_get_unmerged: Mock,
        mock_is_merging: Mock,
        mock_abort: Mock,
    ) -> None:
        """Test that unmerged files are passed to cleanup agent when detected."""
        item = _make_test_item()
        mock_check.return_value = (True, "")
        unmerged_files = ["src/conflict1.py", "src/conflict2.py", "tests/test_conflict.py"]
        mock_merge.side_effect = [(False, unmerged_files), (True, [])]
        # First: conflict detection, second: cleanup resolved merge
        mock_is_merging.side_effect = [True, False]
        mock_get_unmerged.return_value = unmerged_files
        mock_conflict_cleanup.return_value = (True, None)

        result = merge_worktree_to_dev(item)

        assert result is True
        # Verify cleanup was called with conflict details including unmerged files
        mock_conflict_cleanup.assert_called_once()
        call_kwargs = mock_conflict_cleanup.call_args
        assert "unmerged_files" in call_kwargs.kwargs
        assert call_kwargs.kwargs["unmerged_files"] == unmerged_files


class TestCleanupSucceededMergeStillInProgress:
    """Test cleanup-succeeded-but-merge-still-in-progress path (lines 152-159)."""

    @patch("pokepoke.git_operations.abort_merge")
    @patch("pokepoke.git_operations.is_merge_in_progress")
    @patch("pokepoke.git_operations.get_unmerged_files")
    @patch("pokepoke.cleanup_agents.invoke_merge_conflict_cleanup_agent")
    @patch("pokepoke.worktree_finalization.merge_worktree")
    @patch("pokepoke.worktree_finalization.check_main_repo_ready_for_merge")
    def test_abort_merge_called_when_merge_still_in_progress_after_cleanup(
        self,
        mock_check: Mock,
        mock_merge: Mock,
        mock_conflict_cleanup: Mock,
        mock_get_unmerged: Mock,
        mock_is_merging: Mock,
        mock_abort: Mock,
    ) -> None:
        """Test that abort_merge is called when cleanup succeeds but merge is still in progress."""
        item = _make_test_item()
        mock_check.return_value = (True, "")
        mock_merge.side_effect = [(False, ["file.py"]), (True, [])]
        # First call during conflict detection, second after cleanup (still merging)
        mock_is_merging.side_effect = [True, True, False]
        mock_get_unmerged.return_value = ["file.py"]
        mock_conflict_cleanup.return_value = (True, None)
        mock_abort.return_value = (True, "")

        result = merge_worktree_to_dev(item)

        assert result is True
        # abort_merge should be called because merge was still in progress after cleanup
        mock_abort.assert_called_once()
        assert mock_merge.call_count == 2

    @patch("pokepoke.git_operations.abort_merge")
    @patch("pokepoke.git_operations.is_merge_in_progress")
    @patch("pokepoke.git_operations.get_unmerged_files")
    @patch("pokepoke.cleanup_agents.invoke_merge_conflict_cleanup_agent")
    @patch("pokepoke.worktree_finalization.merge_worktree")
    @patch("pokepoke.worktree_finalization.check_main_repo_ready_for_merge")
    def test_abort_merge_failure_returns_false(
        self,
        mock_check: Mock,
        mock_merge: Mock,
        mock_conflict_cleanup: Mock,
        mock_get_unmerged: Mock,
        mock_is_merging: Mock,
        mock_abort: Mock,
    ) -> None:
        """Test that function returns False when abort_merge fails."""
        item = _make_test_item()
        mock_check.return_value = (True, "")
        mock_merge.return_value = (False, ["file.py"])
        mock_is_merging.return_value = True  # Always in merge state
        mock_get_unmerged.return_value = ["file.py"]
        mock_conflict_cleanup.return_value = (True, None)
        mock_abort.return_value = (False, "Cannot abort: index locked")

        result = merge_worktree_to_dev(item)

        assert result is False
        mock_abort.assert_called_once()
        # Should not attempt retry merge after failed abort
        assert mock_merge.call_count == 1


class TestRetryMergeAfterCleanup:
    """Test retry merge scenarios after cleanup (lines 161-170)."""

    @patch("pokepoke.git_operations.abort_merge")
    @patch("pokepoke.git_operations.is_merge_in_progress")
    @patch("pokepoke.git_operations.get_unmerged_files")
    @patch("pokepoke.cleanup_agents.invoke_merge_conflict_cleanup_agent")
    @patch("pokepoke.worktree_finalization.merge_worktree")
    @patch("pokepoke.worktree_finalization.check_main_repo_ready_for_merge")
    def test_retry_merge_succeeds_after_cleanup(
        self,
        mock_check: Mock,
        mock_merge: Mock,
        mock_conflict_cleanup: Mock,
        mock_get_unmerged: Mock,
        mock_is_merging: Mock,
        mock_abort: Mock,
    ) -> None:
        """Test successful retry merge after cleanup."""
        item = _make_test_item()
        mock_check.return_value = (True, "")
        # First merge fails, second succeeds
        mock_merge.side_effect = [(False, ["file.py"]), (True, [])]
        # First call: merge in progress, second call: not in progress (cleanup resolved it)
        mock_is_merging.side_effect = [True, False]
        mock_get_unmerged.return_value = ["file.py"]
        mock_conflict_cleanup.return_value = (True, None)

        result = merge_worktree_to_dev(item)

        assert result is True
        assert mock_merge.call_count == 2
        # abort_merge should NOT be called since merge was no longer in progress
        mock_abort.assert_not_called()

    @patch("pokepoke.git_operations.abort_merge")
    @patch("pokepoke.git_operations.is_merge_in_progress")
    @patch("pokepoke.git_operations.get_unmerged_files")
    @patch("pokepoke.cleanup_agents.invoke_merge_conflict_cleanup_agent")
    @patch("pokepoke.worktree_finalization.merge_worktree")
    @patch("pokepoke.worktree_finalization.check_main_repo_ready_for_merge")
    def test_retry_merge_fails_aborts_merge(
        self,
        mock_check: Mock,
        mock_merge: Mock,
        mock_conflict_cleanup: Mock,
        mock_get_unmerged: Mock,
        mock_is_merging: Mock,
        mock_abort: Mock,
    ) -> None:
        """Test that abort_merge is called when retry merge fails (line 169)."""
        item = _make_test_item()
        mock_check.return_value = (True, "")
        # Both merges fail
        mock_merge.side_effect = [(False, ["file.py"]), (False, ["file.py"])]
        # First: merging, second: cleanup cleared it, third: failed retry puts us back in merge
        mock_is_merging.side_effect = [True, False, True]
        mock_get_unmerged.return_value = ["file.py"]
        mock_conflict_cleanup.return_value = (True, None)
        mock_abort.return_value = (True, "")

        result = merge_worktree_to_dev(item)

        assert result is False
        assert mock_merge.call_count == 2
        # abort_merge called after retry fails and merge is still in progress
        mock_abort.assert_called_once()


class TestCleanupFailedAbortMerge:
    """Test cleanup failure abort path (lines 172-177)."""

    @patch("pokepoke.git_operations.abort_merge")
    @patch("pokepoke.git_operations.is_merge_in_progress")
    @patch("pokepoke.git_operations.get_unmerged_files")
    @patch("pokepoke.cleanup_agents.invoke_merge_conflict_cleanup_agent")
    @patch("pokepoke.worktree_finalization.merge_worktree")
    @patch("pokepoke.worktree_finalization.check_main_repo_ready_for_merge")
    def test_abort_merge_on_cleanup_failure(
        self,
        mock_check: Mock,
        mock_merge: Mock,
        mock_conflict_cleanup: Mock,
        mock_get_unmerged: Mock,
        mock_is_merging: Mock,
        mock_abort: Mock,
    ) -> None:
        """Test abort_merge is called when cleanup fails (line 176)."""
        item = _make_test_item()
        mock_check.return_value = (True, "")
        mock_merge.return_value = (False, ["file.py"])
        mock_is_merging.return_value = True
        mock_get_unmerged.return_value = ["file.py"]
        mock_conflict_cleanup.return_value = (False, None)  # Cleanup fails
        mock_abort.return_value = (True, "")

        result = merge_worktree_to_dev(item)

        assert result is False
        mock_conflict_cleanup.assert_called_once()
        mock_abort.assert_called_once()
        # No retry merge when cleanup fails
        assert mock_merge.call_count == 1

    @patch("pokepoke.git_operations.abort_merge")
    @patch("pokepoke.git_operations.is_merge_in_progress")
    @patch("pokepoke.git_operations.get_unmerged_files")
    @patch("pokepoke.cleanup_agents.invoke_merge_conflict_cleanup_agent")
    @patch("pokepoke.worktree_finalization.merge_worktree")
    @patch("pokepoke.worktree_finalization.check_main_repo_ready_for_merge")
    def test_cleanup_failure_no_abort_when_not_merging(
        self,
        mock_check: Mock,
        mock_merge: Mock,
        mock_conflict_cleanup: Mock,
        mock_get_unmerged: Mock,
        mock_is_merging: Mock,
        mock_abort: Mock,
    ) -> None:
        """Test abort_merge NOT called when cleanup fails but not in merge state."""
        item = _make_test_item()
        mock_check.return_value = (True, "")
        mock_merge.return_value = (False, ["file.py"])
        # First call: merging (triggers cleanup), second call: not merging
        mock_is_merging.side_effect = [True, False]
        mock_get_unmerged.return_value = ["file.py"]
        mock_conflict_cleanup.return_value = (False, None)

        result = merge_worktree_to_dev(item)

        assert result is False
        # abort_merge should NOT be called since not in merge state
        mock_abort.assert_not_called()


class TestAbortMergeReturnValueHandling:
    """Test handling of abort_merge return values."""

    @patch("pokepoke.git_operations.abort_merge")
    @patch("pokepoke.git_operations.is_merge_in_progress")
    @patch("pokepoke.git_operations.get_unmerged_files")
    @patch("pokepoke.cleanup_agents.invoke_merge_conflict_cleanup_agent")
    @patch("pokepoke.worktree_finalization.merge_worktree")
    @patch("pokepoke.worktree_finalization.check_main_repo_ready_for_merge")
    def test_abort_merge_returns_true_with_empty_error(
        self,
        mock_check: Mock,
        mock_merge: Mock,
        mock_conflict_cleanup: Mock,
        mock_get_unmerged: Mock,
        mock_is_merging: Mock,
        mock_abort: Mock,
    ) -> None:
        """Test handling when abort_merge returns (True, '')."""
        item = _make_test_item()
        mock_check.return_value = (True, "")
        mock_merge.side_effect = [(False, ["file.py"]), (True, [])]
        mock_is_merging.side_effect = [True, True, False]
        mock_get_unmerged.return_value = ["file.py"]
        mock_conflict_cleanup.return_value = (True, None)
        mock_abort.return_value = (True, "")  # Success

        result = merge_worktree_to_dev(item)

        assert result is True
        mock_abort.assert_called_once()

    @patch("pokepoke.git_operations.abort_merge")
    @patch("pokepoke.git_operations.is_merge_in_progress")
    @patch("pokepoke.git_operations.get_unmerged_files")
    @patch("pokepoke.cleanup_agents.invoke_merge_conflict_cleanup_agent")
    @patch("pokepoke.worktree_finalization.merge_worktree")
    @patch("pokepoke.worktree_finalization.check_main_repo_ready_for_merge")
    def test_abort_merge_returns_false_with_error_message(
        self,
        mock_check: Mock,
        mock_merge: Mock,
        mock_conflict_cleanup: Mock,
        mock_get_unmerged: Mock,
        mock_is_merging: Mock,
        mock_abort: Mock,
    ) -> None:
        """Test handling when abort_merge returns (False, 'error message')."""
        item = _make_test_item()
        mock_check.return_value = (True, "")
        mock_merge.return_value = (False, ["file.py"])
        mock_is_merging.return_value = True
        mock_get_unmerged.return_value = ["file.py"]
        mock_conflict_cleanup.return_value = (True, None)
        mock_abort.return_value = (False, "fatal: There is no merge to abort")

        result = merge_worktree_to_dev(item)

        assert result is False
        mock_abort.assert_called_once()


class TestNonConflictMergeFailure:
    """Test merge failure without conflict state (lines 127-132)."""

    @patch("pokepoke.git_operations.is_merge_in_progress")
    @patch("pokepoke.git_operations.get_unmerged_files")
    @patch("pokepoke.cleanup_agents.invoke_merge_conflict_cleanup_agent")
    @patch("pokepoke.worktree_finalization.merge_worktree")
    @patch("pokepoke.worktree_finalization.check_main_repo_ready_for_merge")
    def test_merge_failed_not_in_conflict_state(
        self,
        mock_check: Mock,
        mock_merge: Mock,
        mock_conflict_cleanup: Mock,
        mock_get_unmerged: Mock,
        mock_is_merging: Mock,
    ) -> None:
        """Test when merge fails but is_merge_in_progress returns False."""
        item = _make_test_item()
        mock_check.return_value = (True, "")
        mock_merge.side_effect = [(False, []), (True, [])]
        mock_is_merging.return_value = False  # Not in merge state
        mock_get_unmerged.return_value = []  # No unmerged files
        mock_conflict_cleanup.return_value = (True, None)

        result = merge_worktree_to_dev(item)

        assert result is True
        # get_unmerged_files should be called to fetch fresh list
        mock_get_unmerged.assert_called()
        mock_conflict_cleanup.assert_called_once()

    @patch("pokepoke.git_operations.is_merge_in_progress")
    @patch("pokepoke.git_operations.get_unmerged_files")
    @patch("pokepoke.cleanup_agents.invoke_merge_conflict_cleanup_agent")
    @patch("pokepoke.worktree_finalization.merge_worktree")
    @patch("pokepoke.worktree_finalization.check_main_repo_ready_for_merge")
    def test_fresh_unmerged_files_fetched_when_not_in_merge(
        self,
        mock_check: Mock,
        mock_merge: Mock,
        mock_conflict_cleanup: Mock,
        mock_get_unmerged: Mock,
        mock_is_merging: Mock,
    ) -> None:
        """Test that get_unmerged_files is called when merge fails but unmerged_files is empty."""
        item = _make_test_item()
        mock_check.return_value = (True, "")
        # merge_worktree returns empty unmerged list
        mock_merge.side_effect = [(False, []), (True, [])]
        mock_is_merging.return_value = False
        mock_get_unmerged.return_value = ["stale_conflict.py"]
        mock_conflict_cleanup.return_value = (True, None)

        result = merge_worktree_to_dev(item)

        assert result is True
        # get_unmerged_files should be called since unmerged_files was empty
        mock_get_unmerged.assert_called_once()


class TestMultipleConflictFiles:
    """Test handling of multiple conflicted files."""

    @patch("pokepoke.git_operations.abort_merge")
    @patch("pokepoke.git_operations.is_merge_in_progress")
    @patch("pokepoke.git_operations.get_unmerged_files")
    @patch("pokepoke.cleanup_agents.invoke_merge_conflict_cleanup_agent")
    @patch("pokepoke.worktree_finalization.merge_worktree")
    @patch("pokepoke.worktree_finalization.check_main_repo_ready_for_merge")
    def test_handles_many_conflict_files(
        self,
        mock_check: Mock,
        mock_merge: Mock,
        mock_conflict_cleanup: Mock,
        mock_get_unmerged: Mock,
        mock_is_merging: Mock,
        mock_abort: Mock,
    ) -> None:
        """Test handling of 15+ conflicted files (verifies truncation works)."""
        item = _make_test_item()
        mock_check.return_value = (True, "")
        # Create 15 conflicted files
        many_files = [f"src/module{i}.py" for i in range(15)]
        mock_merge.side_effect = [(False, many_files), (True, [])]
        mock_is_merging.side_effect = [True, False]
        mock_get_unmerged.return_value = many_files
        mock_conflict_cleanup.return_value = (True, None)

        result = merge_worktree_to_dev(item)

        assert result is True
        # Verify cleanup was called with all files
        call_kwargs = mock_conflict_cleanup.call_args
        assert len(call_kwargs.kwargs["unmerged_files"]) == 15
class TestFinalizeWorkItem:
    """Test finalize_work_item function (lines 21-29)."""

    @patch("pokepoke.worktree_finalization.close_work_item_and_parents")
    @patch("pokepoke.worktree_finalization.check_and_merge_worktree")
    def test_success(self, mock_merge: Mock, mock_close: Mock) -> None:
        mock_merge.return_value = True
        item = _make_test_item()
        assert finalize_work_item(item, Path("/wt")) is True
        mock_close.assert_called_once_with(item)

    @patch("pokepoke.worktree_finalization.close_work_item_and_parents")
    @patch("pokepoke.worktree_finalization.check_and_merge_worktree")
    def test_merge_fails(self, mock_merge: Mock, mock_close: Mock) -> None:
        mock_merge.return_value = False
        assert finalize_work_item(_make_test_item(), Path("/wt")) is False
        mock_close.assert_not_called()


class TestCheckAndMergeWorktree:
    """Test check_and_merge_worktree function (lines 34-58)."""

    @patch("pokepoke.worktree_finalization.merge_worktree_to_dev")
    @patch("pokepoke.worktree_finalization.get_default_branch", return_value="main")
    @patch("pokepoke.worktree_finalization.subprocess")
    def test_has_commits(self, mock_sub: Mock, mock_branch: Mock, mock_merge: Mock) -> None:
        mock_sub.run.return_value = Mock(stdout="3\n")
        mock_merge.return_value = True
        assert check_and_merge_worktree(_make_test_item(), Path("/wt")) is True
        mock_merge.assert_called_once()

    @patch("pokepoke.worktree_finalization.cleanup_worktree")
    @patch("pokepoke.worktree_finalization.get_default_branch", return_value="main")
    @patch("pokepoke.worktree_finalization.subprocess")
    def test_no_commits(self, mock_sub: Mock, mock_branch: Mock, mock_cleanup: Mock) -> None:
        mock_sub.run.return_value = Mock(stdout="0\n")
        assert check_and_merge_worktree(_make_test_item(), Path("/wt")) is True
        mock_cleanup.assert_called_once_with("task-1", force=True)

    @patch("pokepoke.worktree_finalization.merge_worktree_to_dev")
    @patch("pokepoke.worktree_finalization.get_default_branch")
    @patch("pokepoke.worktree_finalization.subprocess")
    def test_exception_merges_anyway(self, mock_sub: Mock, mock_branch: Mock, mock_merge: Mock) -> None:
        mock_sub.run.side_effect = Exception("git error")
        mock_merge.return_value = True
        assert check_and_merge_worktree(_make_test_item(), Path("/wt")) is True
        mock_merge.assert_called_once()


class TestPreMergeFailurePath:
    """Test the pre-merge failure + cleanup agent path (lines 68-114)."""

    @patch("pokepoke.cleanup_agents.invoke_cleanup_agent")
    @patch("pokepoke.worktree_finalization.merge_worktree")
    @patch("pokepoke.worktree_finalization.check_main_repo_ready_for_merge")
    def test_cleanup_success_retry_success(self, mock_check: Mock, mock_merge: Mock, mock_cleanup: Mock) -> None:
        mock_check.side_effect = [(False, "dirty"), (True, "")]
        mock_cleanup.return_value = (True, None)
        mock_merge.return_value = (True, [])
        assert merge_worktree_to_dev(_make_test_item()) is True

    @patch("pokepoke.cleanup_agents.invoke_cleanup_agent")
    @patch("pokepoke.worktree_finalization.check_main_repo_ready_for_merge")
    def test_cleanup_success_retry_still_fails(self, mock_check: Mock, mock_cleanup: Mock) -> None:
        mock_check.side_effect = [(False, "dirty"), (False, "still dirty")]
        mock_cleanup.return_value = (True, None)
        assert merge_worktree_to_dev(_make_test_item()) is False

    @patch("pokepoke.cleanup_agents.invoke_cleanup_agent")
    @patch("pokepoke.worktree_finalization.check_main_repo_ready_for_merge")
    def test_cleanup_fails(self, mock_check: Mock, mock_cleanup: Mock) -> None:
        mock_check.return_value = (False, "dirty")
        mock_cleanup.return_value = (False, None)
        assert merge_worktree_to_dev(_make_test_item()) is False


class TestMergeDirectSuccess:
    """Test first merge succeeding directly (lines 185-186)."""

    @patch("pokepoke.worktree_finalization.merge_worktree")
    @patch("pokepoke.worktree_finalization.check_main_repo_ready_for_merge")
    def test_first_merge_succeeds(self, mock_check: Mock, mock_merge: Mock) -> None:
        mock_check.return_value = (True, "")
        mock_merge.return_value = (True, [])
        assert merge_worktree_to_dev(_make_test_item()) is True


class TestAbortFailurePaths:
    """Test abort_merge failure paths (lines 174, 182)."""

    @patch("pokepoke.git_operations.abort_merge")
    @patch("pokepoke.git_operations.is_merge_in_progress")
    @patch("pokepoke.git_operations.get_unmerged_files")
    @patch("pokepoke.cleanup_agents.invoke_merge_conflict_cleanup_agent")
    @patch("pokepoke.worktree_finalization.merge_worktree")
    @patch("pokepoke.worktree_finalization.check_main_repo_ready_for_merge")
    def test_retry_merge_fails_abort_fails(
        self, mock_check: Mock, mock_merge: Mock, mock_cleanup: Mock,
        mock_unmerged: Mock, mock_is_merging: Mock, mock_abort: Mock,
    ) -> None:
        """Line 174: abort_merge fails after retry merge fails."""
        mock_check.return_value = (True, "")
        mock_merge.side_effect = [(False, ["f.py"]), (False, ["f.py"])]
        mock_is_merging.side_effect = [True, False, True]
        mock_unmerged.return_value = ["f.py"]
        mock_cleanup.return_value = (True, None)
        mock_abort.return_value = (False, "lock error")
        assert merge_worktree_to_dev(_make_test_item()) is False

    @patch("pokepoke.git_operations.abort_merge")
    @patch("pokepoke.git_operations.is_merge_in_progress")
    @patch("pokepoke.git_operations.get_unmerged_files")
    @patch("pokepoke.cleanup_agents.invoke_merge_conflict_cleanup_agent")
    @patch("pokepoke.worktree_finalization.merge_worktree")
    @patch("pokepoke.worktree_finalization.check_main_repo_ready_for_merge")
    def test_cleanup_fails_abort_fails(
        self, mock_check: Mock, mock_merge: Mock, mock_cleanup: Mock,
        mock_unmerged: Mock, mock_is_merging: Mock, mock_abort: Mock,
    ) -> None:
        """Line 182: abort_merge fails after cleanup fails."""
        mock_check.return_value = (True, "")
        mock_merge.return_value = (False, ["f.py"])
        mock_is_merging.return_value = True
        mock_unmerged.return_value = ["f.py"]
        mock_cleanup.return_value = (False, None)
        mock_abort.return_value = (False, "lock error")
        assert merge_worktree_to_dev(_make_test_item()) is False


class TestCloseWorkItemAndParents:
    """Test close_work_item_and_parents function (lines 189-217)."""

    @patch("pokepoke.worktree_finalization.check_parent_hierarchy")
    @patch("pokepoke.worktree_finalization.subprocess")
    def test_item_already_closed(self, mock_sub: Mock, mock_hierarchy: Mock) -> None:
        item = _make_test_item()
        mock_sub.run.return_value = Mock(stdout=json.dumps([{"status": "closed"}]))
        close_work_item_and_parents(item)
        mock_hierarchy.assert_called_once_with(item)

    @patch("pokepoke.worktree_finalization.check_parent_hierarchy")
    @patch("pokepoke.worktree_finalization.close_item")
    @patch("pokepoke.worktree_finalization.subprocess")
    def test_item_not_closed_falls_back(self, mock_sub: Mock, mock_close: Mock, mock_hierarchy: Mock) -> None:
        item = _make_test_item()
        mock_sub.run.return_value = Mock(stdout=json.dumps([{"status": "open"}]))
        close_work_item_and_parents(item)
        mock_close.assert_called_once()

    @patch("pokepoke.worktree_finalization.check_parent_hierarchy")
    @patch("pokepoke.worktree_finalization.close_item")
    @patch("pokepoke.worktree_finalization.subprocess")
    def test_exception_closes_item(self, mock_sub: Mock, mock_close: Mock, mock_hierarchy: Mock) -> None:
        item = _make_test_item()
        mock_sub.run.side_effect = Exception("bd not found")
        close_work_item_and_parents(item)
        mock_close.assert_called_once()

    @patch("pokepoke.worktree_finalization.check_parent_hierarchy")
    @patch("pokepoke.worktree_finalization.close_item")
    @patch("pokepoke.worktree_finalization.subprocess")
    def test_empty_data_closes_item(self, mock_sub: Mock, mock_close: Mock, mock_hierarchy: Mock) -> None:
        item = _make_test_item()
        mock_sub.run.return_value = Mock(stdout="[]")
        close_work_item_and_parents(item)
        mock_close.assert_called_once()


class TestCheckParentHierarchy:
    """Test check_parent_hierarchy function (lines 220-230)."""

    @patch("pokepoke.worktree_finalization.close_parent_if_complete")
    @patch("pokepoke.worktree_finalization.get_parent_id")
    def test_parent_and_grandparent(self, mock_get_parent: Mock, mock_close: Mock) -> None:
        mock_get_parent.side_effect = ["parent-1", "grandparent-1"]
        check_parent_hierarchy(_make_test_item())
        assert mock_close.call_count == 2

    @patch("pokepoke.worktree_finalization.close_parent_if_complete")
    @patch("pokepoke.worktree_finalization.get_parent_id")
    def test_parent_only(self, mock_get_parent: Mock, mock_close: Mock) -> None:
        mock_get_parent.side_effect = ["parent-1", None]
        check_parent_hierarchy(_make_test_item())
        mock_close.assert_called_once_with("parent-1")

    @patch("pokepoke.worktree_finalization.close_parent_if_complete")
    @patch("pokepoke.worktree_finalization.get_parent_id")
    def test_no_parent(self, mock_get_parent: Mock, mock_close: Mock) -> None:
        mock_get_parent.return_value = None
        check_parent_hierarchy(_make_test_item())
        mock_close.assert_not_called()


@pytest.fixture(autouse=True)
def _mock_cleanup_lock(monkeypatch):
    """Ensure cleanup lock does not hit filesystem during tests."""
    monkeypatch.setattr(
        "pokepoke.worktree_finalization.cleanup_lock",
        lambda: nullcontext(),
    )


@pytest.fixture(autouse=True)
def _mock_merge_lock(monkeypatch):
    """Ensure merge lock does not hit filesystem during tests."""
    monkeypatch.setattr(
        "pokepoke.worktree_finalization.merge_lock",
        lambda: nullcontext(),
    )
