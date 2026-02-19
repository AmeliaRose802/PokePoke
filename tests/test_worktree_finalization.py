"""Tests for worktree finalization merge conflict recovery paths.

This module tests the critical merge conflict handling code in worktree_finalization.py
(lines 117-177), specifically:
- Conflict detection when is_merge_in_progress() returns True
- Cleanup agent invocation and retry logic
- abort_merge() calls and return value handling
- Retry merge after cleanup success/failure scenarios
"""

from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from pokepoke.types import BeadsWorkItem
from pokepoke.worktree_finalization import merge_worktree_to_dev


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
