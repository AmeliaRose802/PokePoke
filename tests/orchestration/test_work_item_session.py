"""Tests for WorkItemSession RAII context manager."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from pokepoke.orchestration.work_item_session import WorkItemSession
from pokepoke.stats.session_journal import SessionPhase

# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

ITEM_ID = "PokePoke-abc123"
AGENT = "test-agent"
SANITIZED_ID = "PokePoke-abc123"  # no special chars → unchanged
EXPECTED_BRANCH = f"task/{SANITIZED_ID}"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_session(**overrides) -> WorkItemSession:
    """Build a WorkItemSession with sensible test defaults."""
    kwargs = {"item_id": ITEM_ID, "agent_name": AGENT}
    kwargs.update(overrides)
    return WorkItemSession(**kwargs)


def _enter_session(session: WorkItemSession) -> WorkItemSession:
    """Manually set the flags that __enter__ would set on success."""
    session._assigned = True
    session._branch_created = True
    session._worktree_created = True
    session.worktree_path = r"C:\worktrees\task-abc"
    return session


# ===================================================================
# 1. __init__
# ===================================================================

class TestInit:
    """WorkItemSession.__init__ attribute derivation."""

    def test_default_branch_derivation(self):
        s = _make_session()
        assert s.branch == EXPECTED_BRANCH

    def test_custom_branch(self):
        s = _make_session(branch="custom/branch")
        assert s.branch == "custom/branch"

    def test_default_worktree_path_is_empty(self):
        s = _make_session()
        assert s.worktree_path == ""

    def test_custom_worktree_path(self):
        s = _make_session(worktree_path="/some/path")
        assert s.worktree_path == "/some/path"

    def test_sessions_dir_stored(self):
        d = Path("/sessions")
        s = _make_session(sessions_dir=d)
        assert s._sessions_dir is d

    def test_lock_timeout_default(self):
        s = _make_session()
        assert s._lock_timeout == 300.0

    def test_lock_timeout_custom(self):
        s = _make_session(lock_timeout=60.0)
        assert s._lock_timeout == 60.0

    def test_initial_flags_are_false(self):
        s = _make_session()
        assert s._assigned is False
        assert s._branch_created is False
        assert s._worktree_created is False


# ===================================================================
# 2–4. __enter__
# ===================================================================

class TestEnter:
    """WorkItemSession.__enter__ — success and failure paths."""

    @patch("pokepoke.orchestration.work_item_session.write_journal", return_value=Path("/j"))
    @patch("pokepoke.worktrees.worktrees.create_worktree", return_value=Path("/wt/task-x"))
    @patch("pokepoke.beads.beads_management.assign_and_sync_item", return_value=True)
    def test_success_path(self, mock_assign, mock_wt, mock_journal):
        s = _make_session()
        result = s.__enter__()

        assert result is s
        assert s._assigned is True
        assert s._worktree_created is True
        assert s._branch_created is True
        assert s.worktree_path == str(Path("/wt/task-x"))
        mock_assign.assert_called_once_with(ITEM_ID)
        mock_wt.assert_called_once_with(ITEM_ID, lock_timeout=300.0)
        # Journal should be written for ASSIGNING, CREATING_WT, ACTIVE
        assert mock_journal.call_count == 3

    @patch("pokepoke.orchestration.work_item_session.write_journal", return_value=Path("/j"))
    @patch("pokepoke.orchestration.work_item_session.delete_journal")
    @patch("pokepoke.beads.beads_management.assign_and_sync_item", return_value=False)
    def test_assign_failure_raises_and_rolls_back(self, mock_assign, mock_del_j, mock_journal):
        s = _make_session()
        with pytest.raises(RuntimeError, match="Failed to assign"):
            s.__enter__()
        # Nothing was acquired so rollback is minimal (just journal delete)
        mock_del_j.assert_called_once()

    @patch("pokepoke.orchestration.work_item_session.write_journal", return_value=Path("/j"))
    @patch("pokepoke.orchestration.work_item_session.delete_journal")
    @patch("pokepoke.beads.beads_manifest_utils.unassign_with_retry", return_value=True)
    @patch("pokepoke.worktrees.worktrees.create_worktree", side_effect=RuntimeError("boom"))
    @patch("pokepoke.beads.beads_management.assign_and_sync_item", return_value=True)
    def test_worktree_failure_rolls_back_assign(
        self, mock_assign, mock_wt, mock_unassign, mock_del_j, mock_journal
    ):
        s = _make_session()
        with pytest.raises(RuntimeError, match="boom"):
            s.__enter__()
        # Assign succeeded, worktree failed → unassign + journal delete
        mock_unassign.assert_called_once_with(ITEM_ID)
        mock_del_j.assert_called_once()
        assert s._assigned is False


# ===================================================================
# 5–9. _rollback_enter
# ===================================================================

class TestRollbackEnter:
    """_rollback_enter — resource cleanup in reverse order."""

    @patch("pokepoke.orchestration.work_item_session.delete_journal")
    @patch("pokepoke.beads.beads_manifest_utils.unassign_with_retry", return_value=True)
    @patch("pokepoke.git.git_operations.branch_exists", return_value=True)
    @patch("pokepoke.orchestration.work_item_session.run_git")
    @patch("pokepoke.worktrees.worktrees.cleanup_worktree", return_value=True)
    def test_all_rollback_succeed(
        self, mock_cleanup_wt, mock_run_git, mock_branch_exists, mock_unassign, mock_del_j
    ):
        s = _enter_session(_make_session())
        s._rollback_enter()

        mock_cleanup_wt.assert_called_once_with(ITEM_ID, force=True)
        mock_run_git.assert_called_once()
        mock_unassign.assert_called_once_with(ITEM_ID)
        mock_del_j.assert_called_once()
        assert s._worktree_created is False
        assert s._branch_created is False
        assert s._assigned is False

    @patch("pokepoke.orchestration.work_item_session.delete_journal")
    @patch("pokepoke.beads.beads_manifest_utils.unassign_with_retry", return_value=True)
    @patch("pokepoke.git.git_operations.branch_exists", return_value=True)
    @patch("pokepoke.orchestration.work_item_session.run_git")
    @patch(
        "pokepoke.worktrees.worktrees.cleanup_worktree",
        side_effect=RuntimeError("wt fail"),
    )
    def test_worktree_removal_fails_continues(
        self, mock_cleanup_wt, mock_run_git, mock_branch_exists, mock_unassign, mock_del_j
    ):
        s = _enter_session(_make_session())
        s._rollback_enter()
        # Should continue despite worktree failure
        mock_run_git.assert_called_once()  # branch delete still attempted
        mock_unassign.assert_called_once()
        mock_del_j.assert_called_once()
        assert s._worktree_created is False

    @patch("pokepoke.orchestration.work_item_session.delete_journal")
    @patch("pokepoke.beads.beads_manifest_utils.unassign_with_retry", return_value=True)
    @patch(
        "pokepoke.git.git_operations.branch_exists",
        side_effect=RuntimeError("branch fail"),
    )
    @patch("pokepoke.worktrees.worktrees.cleanup_worktree", return_value=True)
    def test_branch_deletion_fails_continues(
        self, mock_cleanup_wt, mock_branch_exists, mock_unassign, mock_del_j
    ):
        s = _enter_session(_make_session())
        s._rollback_enter()
        mock_unassign.assert_called_once()
        mock_del_j.assert_called_once()
        assert s._branch_created is False

    @patch("pokepoke.orchestration.work_item_session.delete_journal")
    @patch(
        "pokepoke.beads.beads_manifest_utils.unassign_with_retry",
        side_effect=RuntimeError("unassign fail"),
    )
    @patch("pokepoke.git.git_operations.branch_exists", return_value=False)
    @patch("pokepoke.worktrees.worktrees.cleanup_worktree", return_value=True)
    def test_unassign_fails_continues(
        self, mock_cleanup_wt, mock_branch_exists, mock_unassign, mock_del_j
    ):
        s = _enter_session(_make_session())
        s._rollback_enter()
        mock_del_j.assert_called_once()
        assert s._assigned is False

    @patch(
        "pokepoke.orchestration.work_item_session.delete_journal",
        side_effect=OSError("journal fail"),
    )
    @patch("pokepoke.beads.beads_manifest_utils.unassign_with_retry", return_value=True)
    @patch("pokepoke.git.git_operations.branch_exists", return_value=False)
    @patch("pokepoke.worktrees.worktrees.cleanup_worktree", return_value=True)
    def test_journal_deletion_fails_logged(
        self, mock_cleanup_wt, mock_branch_exists, mock_unassign, mock_del_j
    ):
        s = _enter_session(_make_session())
        # Should not raise
        s._rollback_enter()
        mock_del_j.assert_called_once()


# ===================================================================
# 10–12. __exit__
# ===================================================================

class TestExit:
    """WorkItemSession.__exit__ — dispatch logic."""

    def test_success_path_is_noop(self):
        s = _make_session()
        s._assigned = True
        result = s.__exit__(None, None, None)
        assert result is False
        # _assigned unchanged because cleanup was NOT called
        assert s._assigned is True

    @patch.object(WorkItemSession, "cleanup_on_failure")
    def test_failure_path_calls_cleanup(self, mock_cleanup):
        s = _make_session()
        result = s.__exit__(RuntimeError, RuntimeError("x"), None)
        mock_cleanup.assert_called_once()
        assert result is False

    def test_always_returns_false_on_success(self):
        s = _make_session()
        assert s.__exit__(None, None, None) is False

    @patch.object(WorkItemSession, "cleanup_on_failure")
    def test_always_returns_false_on_failure(self, mock_cleanup):
        s = _make_session()
        assert s.__exit__(ValueError, ValueError(), None) is False


# ===================================================================
# 13–18. cleanup_on_failure
# ===================================================================

class TestCleanupOnFailure:
    """cleanup_on_failure — deterministic unwind sequence."""

    @patch("pokepoke.orchestration.work_item_session.delete_journal")
    @patch("pokepoke.beads.beads_manifest_utils.unassign_with_retry", return_value=True)
    @patch("pokepoke.orchestration.work_item_session.is_merge_in_progress", return_value=False)
    @patch("pokepoke.orchestration.work_item_session.write_journal", return_value=Path("/j"))
    def test_all_succeed_journal_deleted(
        self, mock_journal, mock_merge, mock_unassign, mock_del_j
    ):
        s = _enter_session(_make_session())
        # Make worktree path point to an "existing" dir
        with patch.object(Path, "exists", return_value=True):
            s.cleanup_on_failure()
        mock_del_j.assert_called_once()
        # UNWINDING journal written
        mock_journal.assert_called()

    @patch("pokepoke.orchestration.work_item_session.write_journal", side_effect=OSError("j fail"))
    def test_journal_write_fails_marks_abandoned(self, mock_journal):
        s = _make_session()
        s._assigned = False
        s.worktree_path = ""
        s.cleanup_on_failure()
        # write_journal called twice: UNWINDING (fails) then ABANDONED (also fails)
        assert mock_journal.call_count == 2

    @patch("pokepoke.orchestration.work_item_session.write_journal", return_value=Path("/j"))
    @patch(
        "pokepoke.orchestration.work_item_session.is_merge_in_progress",
        side_effect=subprocess.CalledProcessError(1, "git"),
    )
    def test_merge_abort_fails_abandoned(self, mock_merge, mock_journal):
        s = _make_session()
        s._assigned = False
        s.worktree_path = "/some/path"
        with patch.object(Path, "exists", return_value=True):
            s.cleanup_on_failure()
        # Should write ABANDONED (not delete journal)
        phases = [c.kwargs.get("phase") for c in mock_journal.call_args_list]
        assert SessionPhase.ABANDONED in phases

    @patch("pokepoke.orchestration.work_item_session.write_journal", return_value=Path("/j"))
    @patch(
        "pokepoke.beads.beads_manifest_utils.unassign_with_retry",
        side_effect=RuntimeError("fail"),
    )
    def test_unassign_fails_abandoned(self, mock_unassign, mock_journal):
        s = _make_session()
        s._assigned = True
        s.worktree_path = ""
        s.cleanup_on_failure()
        phases = [c.kwargs.get("phase") for c in mock_journal.call_args_list]
        assert SessionPhase.ABANDONED in phases

    @patch("pokepoke.orchestration.work_item_session.delete_journal")
    @patch("pokepoke.orchestration.work_item_session.write_journal", return_value=Path("/j"))
    def test_no_worktree_path_skips_merge_abort(self, mock_journal, mock_del_j):
        s = _make_session()
        s._assigned = False
        s.worktree_path = ""
        s.cleanup_on_failure()
        # No merge abort attempted — only UNWINDING journal and delete
        mock_del_j.assert_called_once()

    @patch("pokepoke.orchestration.work_item_session.delete_journal")
    @patch("pokepoke.orchestration.work_item_session.is_merge_in_progress", return_value=False)
    @patch("pokepoke.orchestration.work_item_session.write_journal", return_value=Path("/j"))
    def test_not_assigned_skips_unassign(self, mock_journal, mock_merge, mock_del_j):
        s = _make_session()
        s._assigned = False
        s.worktree_path = "/wt"
        with patch.object(Path, "exists", return_value=True):
            s.cleanup_on_failure()
        mock_del_j.assert_called_once()


# ===================================================================
# 19–22. _abort_any_in_progress_merge
# ===================================================================

class TestAbortMerge:
    """_abort_any_in_progress_merge edge cases."""

    def test_no_worktree_path_returns_early(self):
        s = _make_session()
        s.worktree_path = ""
        # Should not raise or call anything
        s._abort_any_in_progress_merge()

    @patch("pokepoke.orchestration.work_item_session.is_merge_in_progress")
    def test_worktree_does_not_exist_returns_early(self, mock_merge):
        s = _make_session()
        s.worktree_path = "/nonexistent"
        with patch.object(Path, "exists", return_value=False):
            s._abort_any_in_progress_merge()
        mock_merge.assert_not_called()

    @patch("pokepoke.orchestration.work_item_session.run_git")
    @patch("pokepoke.orchestration.work_item_session.is_merge_in_progress", return_value=False)
    def test_no_merge_in_progress_no_abort(self, mock_merge, mock_run_git):
        s = _make_session()
        s.worktree_path = "/wt"
        with patch.object(Path, "exists", return_value=True):
            s._abort_any_in_progress_merge()
        mock_run_git.assert_not_called()

    @patch("pokepoke.orchestration.work_item_session.run_git")
    @patch("pokepoke.orchestration.work_item_session.is_merge_in_progress", return_value=True)
    def test_merge_in_progress_aborts(self, mock_merge, mock_run_git):
        s = _make_session()
        s.worktree_path = "/wt"
        with patch.object(Path, "exists", return_value=True):
            s._abort_any_in_progress_merge()
        mock_run_git.assert_called_once()
        args = mock_run_git.call_args[0][0]
        assert "merge" in args
        assert "--abort" in args


# ===================================================================
# 23–24. _remove_worktree
# ===================================================================

class TestRemoveWorktree:
    """_remove_worktree edge cases."""

    def test_no_path_returns_early(self):
        s = _make_session()
        s.worktree_path = ""
        # Should not raise
        s._remove_worktree()

    @patch("pokepoke.worktrees.worktrees.cleanup_worktree", return_value=False)
    def test_cleanup_returns_false_raises(self, mock_cleanup):
        s = _make_session()
        s.worktree_path = "/wt"
        with pytest.raises(RuntimeError, match="cleanup_worktree returned False"):
            s._remove_worktree()

    @patch("pokepoke.worktrees.worktrees.cleanup_worktree", return_value=True)
    def test_cleanup_returns_true_succeeds(self, mock_cleanup):
        s = _make_session()
        s.worktree_path = "/wt"
        s._remove_worktree()
        mock_cleanup.assert_called_once_with(ITEM_ID, force=True)


# ===================================================================
# 25–26. _delete_branch
# ===================================================================

class TestDeleteBranch:
    """_delete_branch — conditional branch deletion."""

    @patch("pokepoke.orchestration.work_item_session.run_git")
    @patch("pokepoke.git.git_operations.branch_exists", return_value=False)
    def test_branch_does_not_exist_noop(self, mock_exists, mock_run_git):
        s = _make_session()
        s._delete_branch()
        mock_run_git.assert_not_called()

    @patch("pokepoke.orchestration.work_item_session.run_git")
    @patch("pokepoke.git.git_operations.branch_exists", return_value=True)
    def test_branch_exists_deletes(self, mock_exists, mock_run_git):
        s = _make_session()
        s._delete_branch()
        mock_run_git.assert_called_once()
        args = mock_run_git.call_args[0][0]
        assert args == ["git", "branch", "-D", EXPECTED_BRANCH]


# ===================================================================
# 27–28. _unassign_beads_item
# ===================================================================

class TestUnassignBeadsItem:
    """_unassign_beads_item — retry wrapper."""

    @patch("pokepoke.beads.beads_manifest_utils.unassign_with_retry", return_value=True)
    def test_success(self, mock_unassign):
        s = _make_session()
        s._unassign_beads_item()
        mock_unassign.assert_called_once_with(ITEM_ID)

    @patch("pokepoke.beads.beads_manifest_utils.unassign_with_retry", return_value=False)
    def test_retry_exhausted_raises(self, mock_unassign):
        s = _make_session()
        with pytest.raises(RuntimeError, match="unassign_with_retry exhausted"):
            s._unassign_beads_item()


# ===================================================================
# Context-manager integration
# ===================================================================

class TestContextManagerIntegration:
    """End-to-end with-statement usage."""

    @patch("pokepoke.orchestration.work_item_session.delete_journal")
    @patch("pokepoke.orchestration.work_item_session.write_journal", return_value=Path("/j"))
    @patch("pokepoke.worktrees.worktrees.create_worktree", return_value=Path("/wt/x"))
    @patch("pokepoke.beads.beads_management.assign_and_sync_item", return_value=True)
    def test_with_success_no_cleanup(self, mock_assign, mock_wt, mock_journal, mock_del_j):
        s = _make_session()
        with s:
            assert s.worktree_path == str(Path("/wt/x"))
        # On success, cleanup_on_failure is NOT called → journal NOT deleted by __exit__
        mock_del_j.assert_not_called()

    @patch("pokepoke.orchestration.work_item_session.delete_journal")
    @patch("pokepoke.orchestration.work_item_session.write_journal", return_value=Path("/j"))
    @patch("pokepoke.orchestration.work_item_session.is_merge_in_progress", return_value=False)
    @patch("pokepoke.beads.beads_manifest_utils.unassign_with_retry", return_value=True)
    @patch("pokepoke.worktrees.worktrees.create_worktree", return_value=Path("/wt/x"))
    @patch("pokepoke.beads.beads_management.assign_and_sync_item", return_value=True)
    def test_with_exception_triggers_cleanup(  # noqa: PLR0913
        self, mock_assign, mock_wt, mock_unassign, mock_merge, mock_journal, mock_del_j
    ):
        s = _make_session()
        with pytest.raises(ValueError, match="test error"), s:
                raise ValueError("test error")
        # cleanup_on_failure should have run: unassign called, journal deleted
        mock_unassign.assert_called_once()
        mock_del_j.assert_called_once()
