"""Tests for pokepoke.orchestration.work_item_session — __enter__, __exit__, and cleanup_on_failure."""

import logging
from pathlib import Path
from unittest.mock import patch

import pytest

from pokepoke.orchestration.work_item_session import WorkItemSession
from pokepoke.stats.session_journal import SessionPhase

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_session(
    item_id: str = "test-item",
    agent_name: str = "test-agent",
    worktree_path: str = "/tmp/wt/task-test-item",
    sessions_dir: Path | None = None,
) -> WorkItemSession:
    """Create a WorkItemSession with defaults suitable for testing."""
    session = WorkItemSession(
        item_id=item_id,
        agent_name=agent_name,
        worktree_path=worktree_path,
        sessions_dir=sessions_dir,
    )
    # Mark resources as acquired so cleanup attempts all steps.
    session._assigned = True
    session._branch_created = True
    session._worktree_created = True
    return session


# Shared patch targets — all internal helpers are patched so no real
# git/beads/filesystem operations run during tests.


def _patch_all_helpers():
    """Return a context manager yielding a dict of mocks for all helpers.

    Patches are applied to the correct module for each import style:
    - Module-level imports → patched on ``pokepoke.orchestration.work_item_session``
    - Lazy (in-function) imports → patched on their source module
    """
    import contextlib

    @contextlib.contextmanager
    def _ctx():
        patches = {}
        mocks = {}
        try:
            # Module-level imports in work_item_session.py
            p = patch("pokepoke.orchestration.work_item_session.write_journal", return_value=Path("/j.json"))
            mocks["write_journal"] = p.start()
            patches["write_journal"] = p

            p = patch("pokepoke.orchestration.work_item_session.delete_journal", return_value=True)
            mocks["delete_journal"] = p.start()
            patches["delete_journal"] = p

            p = patch("pokepoke.orchestration.work_item_session.is_merge_in_progress", return_value=False)
            mocks["is_merge"] = p.start()
            patches["is_merge"] = p

            p = patch("pokepoke.orchestration.work_item_session.run_git")
            mocks["subprocess_run"] = p.start()
            patches["subprocess_run"] = p

            # Lazy imports — must be patched at their source modules
            p = patch("pokepoke.worktrees.worktrees.cleanup_worktree", return_value=True)
            mocks["cleanup_worktree"] = p.start()
            patches["cleanup_worktree"] = p

            p = patch("pokepoke.git.git_operations.branch_exists", return_value=False)
            mocks["branch_exists"] = p.start()
            patches["branch_exists"] = p

            p = patch("pokepoke.beads.beads_recovery.unassign_with_retry", return_value=True)
            mocks["unassign_item"] = p.start()
            patches["unassign_item"] = p

            yield mocks
        finally:
            for p in patches.values():
                p.stop()

    return _ctx()


class TestExitSuccessPath:
    """__exit__ with exc_type=None should be a no-op."""

    def test_returns_false_on_success(self) -> None:
        session = _make_session()
        result = session.__exit__(None, None, None)
        assert result is False

    def test_does_not_call_cleanup(self) -> None:
        session = _make_session()
        with patch.object(session, "cleanup_on_failure") as mock_cleanup:
            session.__exit__(None, None, None)
            mock_cleanup.assert_not_called()


# ---------------------------------------------------------------------------
# __exit__: failure path
# ---------------------------------------------------------------------------


class TestExitFailurePath:
    """__exit__ with exc_type set should delegate to cleanup_on_failure."""

    def test_returns_false_on_failure(self) -> None:
        """__exit__ must never suppress the original exception."""
        session = _make_session()
        with patch.object(session, "cleanup_on_failure"):
            result = session.__exit__(RuntimeError, RuntimeError("boom"), None)
        assert result is False

    def test_calls_cleanup_on_failure(self) -> None:
        session = _make_session()
        with patch.object(session, "cleanup_on_failure") as mock_cleanup:
            session.__exit__(ValueError, ValueError("x"), None)
            mock_cleanup.assert_called_once()


# ---------------------------------------------------------------------------
# cleanup_on_failure: full unwind — all steps succeed
# ---------------------------------------------------------------------------


class TestCleanupAllSucceed:
    """When every unwind step succeeds the journal should be deleted."""

    def test_writes_unwinding_journal(self) -> None:
        with _patch_all_helpers() as m:
            session = _make_session()
            session.cleanup_on_failure()

            # First call should be UNWINDING
            calls = m["write_journal"].call_args_list
            assert any(
                c.kwargs.get("phase") == SessionPhase.UNWINDING
                or (c.args and SessionPhase.UNWINDING in c.args)
                for c in calls
            ), f"Expected UNWINDING journal write, got: {calls}"

    def test_deletes_journal_on_full_success(self) -> None:
        with _patch_all_helpers() as m:
            m["cleanup_worktree"].return_value = True
            m["unassign_item"].return_value = True
            session = _make_session()
            session.cleanup_on_failure()

            m["delete_journal"].assert_called_once()

    def test_no_abandoned_journal_on_full_success(self) -> None:
        with _patch_all_helpers() as m:
            m["cleanup_worktree"].return_value = True
            m["unassign_item"].return_value = True
            session = _make_session()
            session.cleanup_on_failure()

            # ABANDONED should NOT be written
            for call in m["write_journal"].call_args_list:
                phase_arg = call.kwargs.get("phase")
                if phase_arg is None and len(call.args) >= 5:
                    phase_arg = call.args[4]
                assert phase_arg != SessionPhase.ABANDONED

    def test_unwind_order(self) -> None:
        """Steps must run in order: journal → merge abort → unassign (worktree/branch preserved)."""
        call_order: list[str] = []

        with _patch_all_helpers() as m:
            m["write_journal"].side_effect = lambda **kw: (
                call_order.append(f"journal:{kw.get('phase', 'unknown')}"),
                Path("/j.json"),
            )[-1]
            m["is_merge"].side_effect = lambda *a: (call_order.append("merge_check"), False)[-1]
            m["cleanup_worktree"].side_effect = lambda *a, **kw: (
                call_order.append("remove_worktree"), True
            )[-1]
            m["branch_exists"].side_effect = lambda *a: (call_order.append("branch_check"), False)[-1]
            m["unassign_item"].side_effect = lambda *a: (call_order.append("unassign"), True)[-1]
            m["delete_journal"].side_effect = lambda *a, **kw: (
                call_order.append("delete_journal"), True
            )[-1]

            session = _make_session()
            session.cleanup_on_failure()

        # Verify ordering — worktree and branch are preserved for retry reuse
        assert call_order[0] == f"journal:{SessionPhase.UNWINDING}"
        assert "remove_worktree" not in call_order  # worktree preserved
        assert "branch_check" not in call_order     # branch preserved
        assert "unassign" in call_order
        assert "delete_journal" in call_order


# ---------------------------------------------------------------------------
# cleanup_on_failure: partial failure → ABANDONED journal
# ---------------------------------------------------------------------------


class TestCleanupPartialFailure:
    """When any step fails, journal should be written as ABANDONED."""

    def test_worktree_preserved_on_failure(self) -> None:
        """Worktree is never removed on failure — preserved for retry reuse."""
        with _patch_all_helpers() as m:
            session = _make_session()
            session.cleanup_on_failure()

            # Worktree should NOT be cleaned up
            m["cleanup_worktree"].assert_not_called()

    def test_unassign_fails_writes_abandoned(self) -> None:
        with _patch_all_helpers() as m:
            m["unassign_item"].return_value = False
            session = _make_session()
            session.cleanup_on_failure()

            last_write = m["write_journal"].call_args_list[-1]
            phase = last_write.kwargs.get("phase")
            assert phase == SessionPhase.ABANDONED

    def test_merge_abort_fails_writes_abandoned(self) -> None:
        with _patch_all_helpers() as m:
            m["is_merge"].return_value = True
            m["subprocess_run"].side_effect = RuntimeError("merge --abort failed")
            session = _make_session(worktree_path="/tmp/wt/task-test-item")
            # Need to make the worktree path exist for the merge abort check
            with patch("pokepoke.orchestration.work_item_session.Path.exists", return_value=True):
                session.cleanup_on_failure()

            last_write = m["write_journal"].call_args_list[-1]
            phase = last_write.kwargs.get("phase")
            assert phase == SessionPhase.ABANDONED

    def test_branch_preserved_on_failure(self) -> None:
        """Branch is never deleted on failure — preserved for retry reuse."""
        with _patch_all_helpers() as m:
            m["branch_exists"].return_value = True
            session = _make_session()
            session.cleanup_on_failure()

            # Branch delete should NOT be called
            m["subprocess_run"].assert_not_called()

    def test_journal_write_fails_still_continues(self) -> None:
        """Even if writing the UNWINDING journal fails, remaining steps run."""
        with _patch_all_helpers() as m:
            m["write_journal"].side_effect = OSError("disk full")
            m["unassign_item"].return_value = True

            session = _make_session()
            session.cleanup_on_failure()

            # Despite journal failure, unassign should be attempted
            # (worktree/branch are preserved, not cleaned up)
            m["cleanup_worktree"].assert_not_called()
            m["unassign_item"].assert_called_once()

    def test_all_steps_fail_writes_abandoned(self) -> None:
        with _patch_all_helpers() as m:
            # All steps fail
            m["write_journal"].side_effect = [
                OSError("disk full"),  # UNWINDING
                Path("/j.json"),       # ABANDONED
            ]
            m["cleanup_worktree"].return_value = False
            m["unassign_item"].return_value = False
            m["branch_exists"].return_value = True
            m["subprocess_run"].side_effect = RuntimeError("branch -D failed")

            session = _make_session()
            session.cleanup_on_failure()

            # ABANDONED write should have been attempted (second call)
            assert m["write_journal"].call_count == 2

    def test_journal_not_deleted_on_partial_failure(self) -> None:
        with _patch_all_helpers() as m:
            m["unassign_item"].return_value = False
            session = _make_session()
            session.cleanup_on_failure()

            m["delete_journal"].assert_not_called()


# ---------------------------------------------------------------------------
# cleanup_on_failure: ERROR-level logging
# ---------------------------------------------------------------------------


class TestCleanupErrorLogging:
    """All step failures must be logged at ERROR level."""

    def test_worktree_preserved_logged_at_info(self, caplog: pytest.LogCaptureFixture) -> None:
        """Worktree preservation should be logged at INFO level."""
        with _patch_all_helpers():
            session = _make_session()
            with caplog.at_level(logging.INFO, logger="pokepoke.orchestration.work_item_session"):
                session.cleanup_on_failure()

            info_msgs = [r.message for r in caplog.records if r.levelno == logging.INFO]
            assert any("preserving worktree" in msg.lower() for msg in info_msgs), (
                f"Expected INFO log about preserving worktree, got: {info_msgs}"
            )

    def test_unassign_failure_logged_at_error(self, caplog: pytest.LogCaptureFixture) -> None:
        with _patch_all_helpers() as m:
            m["unassign_item"].return_value = False
            session = _make_session()
            with caplog.at_level(logging.ERROR, logger="pokepoke.orchestration.work_item_session"):
                session.cleanup_on_failure()

            error_msgs = [r.message for r in caplog.records if r.levelno >= logging.ERROR]
            assert any("unassign" in msg.lower() for msg in error_msgs), (
                f"Expected ERROR log about unassign failure, got: {error_msgs}"
            )

    def test_branch_preserved_not_deleted(self, caplog: pytest.LogCaptureFixture) -> None:
        """Branch should not be deleted — preserved for retry reuse."""
        with _patch_all_helpers() as m:
            m["branch_exists"].return_value = True
            session = _make_session()
            with caplog.at_level(logging.INFO, logger="pokepoke.orchestration.work_item_session"):
                session.cleanup_on_failure()

            # No branch deletion should be attempted
            m["subprocess_run"].assert_not_called()

    def test_journal_write_failure_logged_at_error(self, caplog: pytest.LogCaptureFixture) -> None:
        with _patch_all_helpers() as m:
            m["write_journal"].side_effect = OSError("disk full")
            session = _make_session()
            with caplog.at_level(logging.ERROR, logger="pokepoke.orchestration.work_item_session"):
                session.cleanup_on_failure()

            error_msgs = [r.message for r in caplog.records if r.levelno >= logging.ERROR]
            assert any("unwinding" in msg.lower() or "journal" in msg.lower() for msg in error_msgs), (
                f"Expected ERROR log about journal failure, got: {error_msgs}"
            )


# ---------------------------------------------------------------------------
# cleanup_on_failure: edge cases
# ---------------------------------------------------------------------------


class TestCleanupEdgeCases:
    """Edge cases and idempotency."""

    def test_empty_worktree_path_skips_removal(self) -> None:
        """When worktree_path is empty, _remove_worktree should be a no-op."""
        with _patch_all_helpers() as m:
            session = _make_session(worktree_path="")
            session.cleanup_on_failure()

            # cleanup_worktree should not be called since worktree_path is empty
            m["cleanup_worktree"].assert_not_called()

    def test_branch_does_not_exist_skips_delete(self) -> None:
        with _patch_all_helpers() as m:
            m["branch_exists"].return_value = False
            session = _make_session()
            session.cleanup_on_failure()

            # run_git should not be called for branch deletion
            # (no merge abort either since is_merge returns False)
            m["subprocess_run"].assert_not_called()

    def test_worktree_path_not_existing_skips_merge_abort(self) -> None:
        """If the worktree directory doesn't exist, merge abort is skipped."""
        with _patch_all_helpers() as m:
            session = _make_session(worktree_path="/nonexistent/path")
            session.cleanup_on_failure()

            # is_merge_in_progress should not be checked if path doesn't exist
            # The _abort_any_in_progress_merge method checks Path.exists() first
            m["is_merge"].assert_not_called()

    def test_cleanup_on_failure_can_be_called_multiple_times(self) -> None:
        """Cleanup should be idempotent — calling it twice should not crash."""
        with _patch_all_helpers() as m:
            m["unassign_item"].return_value = True
            session = _make_session()
            session.cleanup_on_failure()
            session.cleanup_on_failure()

            # Worktree preserved, not cleaned up
            m["cleanup_worktree"].assert_not_called()
            assert m["unassign_item"].call_count == 2

    def test_empty_worktree_path_skips_merge_abort(self) -> None:
        """When worktree_path is empty, merge abort should not target cwd."""
        with _patch_all_helpers() as m:
            session = _make_session(worktree_path="")
            session._worktree_created = True
            session.cleanup_on_failure()

            # is_merge_in_progress should NOT be called — empty path must be skipped
            m["is_merge"].assert_not_called()
            m["subprocess_run"].assert_not_called()

    def test_not_assigned_skips_unassign(self) -> None:
        """When _assigned is False, cleanup should skip unassignment."""
        with _patch_all_helpers() as m:
            session = _make_session()
            session._assigned = False
            session.cleanup_on_failure()

            m["unassign_item"].assert_not_called()

    def test_no_worktree_created_skips_merge_abort(self) -> None:
        """When _worktree_created is False, cleanup should skip merge abort."""
        with _patch_all_helpers() as m:
            m["is_merge"].return_value = True
            session = _make_session(worktree_path="/tmp/wt/task-test-item")
            session._worktree_created = False
            session.cleanup_on_failure()

            # Merge abort should be skipped since worktree was never created
            m["is_merge"].assert_not_called()
            m["subprocess_run"].assert_not_called()

    def test_partial_init_cleanup_only_unassigns(self) -> None:
        """Session with only _assigned=True should only unassign, not touch worktree."""
        with _patch_all_helpers() as m:
            session = _make_session(worktree_path="")
            session._assigned = True
            session._worktree_created = False
            session._branch_created = False
            session.cleanup_on_failure()

            # Should unassign but not try to abort merge
            m["unassign_item"].assert_called_once()
            m["is_merge"].assert_not_called()


# ---------------------------------------------------------------------------
# __exit__ used as context manager
# ---------------------------------------------------------------------------


class TestContextManagerIntegration:
    """Test __exit__ behavior when used with 'with' statement."""

    def test_exception_triggers_cleanup(self) -> None:
        with _patch_all_helpers() as m:
            m["unassign_item"].return_value = True

            session = _make_session()
            # Simulate context manager usage without __enter__
            with pytest.raises(ValueError, match="test error"):
                session.__enter__ = lambda: session  # type: ignore[assignment]
                try:
                    raise ValueError("test error")
                except ValueError:
                    import sys
                    session.__exit__(*sys.exc_info())
                    raise

            # Worktree preserved, not cleaned up
            m["cleanup_worktree"].assert_not_called()
            m["unassign_item"].assert_called_once()

    def test_no_exception_skips_cleanup(self) -> None:
        with _patch_all_helpers() as m:
            session = _make_session()
            session.__exit__(None, None, None)

            m["cleanup_worktree"].assert_not_called()
            m["unassign_item"].assert_not_called()
            m["write_journal"].assert_not_called()


# ---------------------------------------------------------------------------
# __enter__: ordered resource acquisition
# ---------------------------------------------------------------------------


def _patch_enter_helpers():
    """Patch dependencies used by __enter__."""
    import contextlib

    @contextlib.contextmanager
    def _ctx():
        patches = {}
        mocks = {}
        try:
            p = patch("pokepoke.orchestration.work_item_session.write_journal", return_value=Path("/j.json"))
            mocks["write_journal"] = p.start()
            patches["write_journal"] = p

            p = patch("pokepoke.orchestration.work_item_session.delete_journal", return_value=True)
            mocks["delete_journal"] = p.start()
            patches["delete_journal"] = p

            p = patch("pokepoke.beads.beads_management.assign_and_sync_item", return_value=True)
            mocks["assign"] = p.start()
            patches["assign"] = p

            p = patch("pokepoke.worktrees.worktrees.create_worktree", return_value=Path("/tmp/wt/task-test"))
            mocks["create_worktree"] = p.start()
            patches["create_worktree"] = p

            # Needed for rollback
            p = patch("pokepoke.worktrees.worktrees.cleanup_worktree", return_value=True)
            mocks["cleanup_worktree"] = p.start()
            patches["cleanup_worktree"] = p

            p = patch("pokepoke.git.git_operations.branch_exists", return_value=False)
            mocks["branch_exists"] = p.start()
            patches["branch_exists"] = p

            p = patch("pokepoke.beads.beads_recovery.unassign_with_retry", return_value=True)
            mocks["unassign_item"] = p.start()
            patches["unassign_item"] = p

            yield mocks
        finally:
            for p in patches.values():
                p.stop()

    return _ctx()


class TestEnterSuccess:
    """__enter__ should acquire resources in order and return self."""

    def test_returns_self(self) -> None:
        with _patch_enter_helpers():
            session = WorkItemSession(item_id="test-1", agent_name="agent")
            result = session.__enter__()
            assert result is session

    def test_sets_worktree_path(self) -> None:
        with _patch_enter_helpers():
            session = WorkItemSession(item_id="test-1", agent_name="agent")
            session.__enter__()
            assert session.worktree_path == str(Path("/tmp/wt/task-test"))

    def test_marks_resources_acquired(self) -> None:
        with _patch_enter_helpers():
            session = WorkItemSession(item_id="test-1", agent_name="agent")
            session.__enter__()
            assert session._assigned is True
            assert session._branch_created is True
            assert session._worktree_created is True

    def test_writes_journals_in_order(self) -> None:
        with _patch_enter_helpers() as m:
            session = WorkItemSession(item_id="test-1", agent_name="agent")
            session.__enter__()

            phases = [c.kwargs.get("phase") for c in m["write_journal"].call_args_list]
            assert phases == [SessionPhase.ASSIGNING, SessionPhase.CREATING_WT, SessionPhase.ACTIVE]

    def test_calls_assign_then_create_worktree(self) -> None:
        with _patch_enter_helpers() as m:
            session = WorkItemSession(item_id="test-1", agent_name="agent")
            session.__enter__()
            m["assign"].assert_called_once_with("test-1")
            m["create_worktree"].assert_called_once()


class TestEnterFailureAndRollback:
    """__enter__ failures should trigger reverse-order rollback."""

    def test_assign_failure_raises(self) -> None:
        with _patch_enter_helpers() as m:
            m["assign"].return_value = False
            session = WorkItemSession(item_id="test-1", agent_name="agent")
            with pytest.raises(RuntimeError, match="Failed to assign"):
                session.__enter__()

    def test_assign_failure_deletes_journal(self) -> None:
        with _patch_enter_helpers() as m:
            m["assign"].return_value = False
            session = WorkItemSession(item_id="test-1", agent_name="agent")
            with pytest.raises(RuntimeError):
                session.__enter__()
            m["delete_journal"].assert_called_once()

    def test_worktree_failure_rolls_back_assignment(self) -> None:
        with _patch_enter_helpers() as m:
            m["create_worktree"].side_effect = RuntimeError("worktree failed")
            session = WorkItemSession(item_id="test-1", agent_name="agent")
            with pytest.raises(RuntimeError, match="worktree failed"):
                session.__enter__()
            # Assignment should be rolled back
            m["unassign_item"].assert_called_once()

    def test_worktree_failure_deletes_journal(self) -> None:
        with _patch_enter_helpers() as m:
            m["create_worktree"].side_effect = RuntimeError("worktree failed")
            session = WorkItemSession(item_id="test-1", agent_name="agent")
            with pytest.raises(RuntimeError):
                session.__enter__()
            m["delete_journal"].assert_called_once()

    def test_rollback_logs_errors_at_error_level(self, caplog: pytest.LogCaptureFixture) -> None:
        with _patch_enter_helpers() as m:
            m["create_worktree"].side_effect = RuntimeError("worktree failed")
            m["unassign_item"].side_effect = RuntimeError("unassign failed")
            session = WorkItemSession(item_id="test-1", agent_name="agent")
            with caplog.at_level(logging.ERROR, logger="pokepoke.orchestration.work_item_session"), \
                    pytest.raises(RuntimeError, match="worktree failed"):
                    session.__enter__()

            error_msgs = [r.message for r in caplog.records if r.levelno >= logging.ERROR]
            assert any("rollback" in msg.lower() for msg in error_msgs)

    def test_rollback_worktree_removal_failure_logs_error(self, caplog: pytest.LogCaptureFixture) -> None:
        """Covers lines 112-116: worktree removal fails during rollback."""
        with _patch_enter_helpers() as m:
            # Step 2 fails, triggering rollback that includes worktree removal
            m["create_worktree"].return_value = Path("/tmp/wt/test")
            # We need __enter__ to succeed through assign+create_worktree, then fail later
            # Instead, simulate: assign succeeds, create_worktree succeeds, but then
            # write_journal for ACTIVE phase fails
            call_count = [0]
            original_return = m["write_journal"].return_value

            def write_journal_side_effect(**kwargs):
                call_count[0] += 1
                # Fail on the 3rd call (ACTIVE phase)
                if call_count[0] == 3:
                    raise RuntimeError("journal write failed")
                return original_return

            m["write_journal"].side_effect = write_journal_side_effect
            m["cleanup_worktree"].side_effect = RuntimeError("worktree cleanup failed")

            session = WorkItemSession(item_id="test-1", agent_name="agent")
            with caplog.at_level(logging.ERROR, logger="pokepoke.orchestration.work_item_session"), \
                    pytest.raises(RuntimeError, match="journal write failed"):
                session.__enter__()

            error_msgs = [r.message for r in caplog.records if r.levelno >= logging.ERROR]
            assert any("worktree" in msg.lower() for msg in error_msgs)

    def test_rollback_branch_deletion_failure_logs_error(self, caplog: pytest.LogCaptureFixture) -> None:
        """Covers lines 119-123: branch deletion fails during rollback."""
        with _patch_enter_helpers() as m:
            call_count = [0]
            original_return = m["write_journal"].return_value

            def write_journal_side_effect(**kwargs):
                call_count[0] += 1
                if call_count[0] == 3:
                    raise RuntimeError("journal write failed")
                return original_return

            m["write_journal"].side_effect = write_journal_side_effect
            m["branch_exists"].return_value = True
            m["cleanup_worktree"].return_value = True
            # Patch run_git to fail for branch deletion in rollback
            with patch("pokepoke.orchestration.work_item_session.run_git",
                       side_effect=RuntimeError("branch delete failed")):
                session = WorkItemSession(item_id="test-1", agent_name="agent")
                with caplog.at_level(logging.ERROR, logger="pokepoke.orchestration.work_item_session"), \
                        pytest.raises(RuntimeError, match="journal write failed"):
                    session.__enter__()

            error_msgs = [r.message for r in caplog.records if r.levelno >= logging.ERROR]
            assert any("branch" in msg.lower() for msg in error_msgs)

    def test_rollback_journal_deletion_failure_logs_error(self, caplog: pytest.LogCaptureFixture) -> None:
        """Covers lines 134-135: journal deletion fails during rollback."""
        with _patch_enter_helpers() as m:
            m["assign"].return_value = False  # Fails at step 1
            m["delete_journal"].side_effect = RuntimeError("journal delete failed")

            session = WorkItemSession(item_id="test-1", agent_name="agent")
            with caplog.at_level(logging.ERROR, logger="pokepoke.orchestration.work_item_session"), \
                    pytest.raises(RuntimeError, match="Failed to assign"):
                session.__enter__()

            error_msgs = [r.message for r in caplog.records if r.levelno >= logging.ERROR]
            assert any("journal" in msg.lower() for msg in error_msgs)


class TestCleanupDeleteJournalFailure:
    """Test cleanup_on_failure when delete_journal fails on success path."""

    def test_delete_journal_failure_on_success_path(self, caplog: pytest.LogCaptureFixture) -> None:
        """Covers lines 220-221: delete_journal raises during successful cleanup."""
        with _patch_all_helpers() as m:
            m["unassign_item"].return_value = True
            m["delete_journal"].side_effect = RuntimeError("journal delete failed")

            session = _make_session()
            with caplog.at_level(logging.ERROR, logger="pokepoke.orchestration.work_item_session"):
                session.cleanup_on_failure()

            error_msgs = [r.message for r in caplog.records if r.levelno >= logging.ERROR]
            assert any("journal" in msg.lower() for msg in error_msgs)


class TestAbortMergeInProgress:
    """Tests for _abort_any_in_progress_merge."""

    def test_aborts_merge_when_in_progress(self, tmp_path: Path) -> None:
        """Covers line 253: runs git merge --abort when merge is in progress."""
        with _patch_all_helpers() as m:
            m["is_merge"].return_value = True
            session = _make_session(worktree_path=str(tmp_path))
            session.cleanup_on_failure()

            m["subprocess_run"].assert_called_once()
            call_args = m["subprocess_run"].call_args
            assert "merge" in call_args[0][0]
            assert "--abort" in call_args[0][0]


class TestRemoveWorktreeHelper:
    """Tests for _remove_worktree internal helper."""

    def test_remove_worktree_calls_cleanup(self) -> None:
        """Covers lines 257-262: _remove_worktree delegates to cleanup_worktree."""
        with _patch_all_helpers() as m:
            m["cleanup_worktree"].return_value = True
            session = _make_session()
            session._remove_worktree()
            m["cleanup_worktree"].assert_called_once_with(session.item_id, force=True)

    def test_remove_worktree_empty_path_noop(self) -> None:
        """_remove_worktree is a no-op when worktree_path is empty."""
        with _patch_all_helpers() as m:
            session = _make_session(worktree_path="")
            session._remove_worktree()
            m["cleanup_worktree"].assert_not_called()

    def test_remove_worktree_raises_on_failure(self) -> None:
        """_remove_worktree raises when cleanup_worktree returns False."""
        with _patch_all_helpers() as m:
            m["cleanup_worktree"].return_value = False
            session = _make_session()
            with pytest.raises(RuntimeError, match="cleanup_worktree returned False"):
                session._remove_worktree()


class TestDeleteBranchHelper:
    """Tests for _delete_branch internal helper."""

    def test_delete_branch_when_exists(self) -> None:
        """Covers lines 266-272: branch exists and gets deleted."""
        with _patch_all_helpers() as m:
            m["branch_exists"].return_value = True
            session = _make_session()
            session._delete_branch()
            m["subprocess_run"].assert_called_once()
            call_args = m["subprocess_run"].call_args
            assert "branch" in call_args[0][0]
            assert "-D" in call_args[0][0]

    def test_delete_branch_skips_when_not_exists(self) -> None:
        """Branch that doesn't exist is silently skipped."""
        with _patch_all_helpers() as m:
            m["branch_exists"].return_value = False
            session = _make_session()
            session._delete_branch()
            m["subprocess_run"].assert_not_called()


class TestUnassignBeadsItemHelper:
    """Tests for _unassign_beads_item internal helper (Unassign Ex validation)."""

    def test_unassign_success(self) -> None:
        """_unassign_beads_item succeeds when unassign_with_retry returns True."""
        with _patch_all_helpers() as m:
            m["unassign_item"].return_value = True
            session = _make_session(item_id="task-unassign-ex")
            # Should not raise
            session._unassign_beads_item()
            m["unassign_item"].assert_called_once_with("task-unassign-ex")

    def test_unassign_failure_raises_runtime_error(self) -> None:
        """_unassign_beads_item raises RuntimeError when unassign_with_retry returns False."""
        with _patch_all_helpers() as m:
            m["unassign_item"].return_value = False
            session = _make_session(item_id="task-unassign-ex")
            with pytest.raises(RuntimeError, match="unassign_with_retry exhausted for task-unassign-ex"):
                session._unassign_beads_item()

    def test_unassign_exception_propagates(self) -> None:
        """Exceptions from unassign_with_retry propagate to caller."""
        with _patch_all_helpers() as m:
            m["unassign_item"].side_effect = ConnectionError("beads service unavailable")
            session = _make_session(item_id="task-unassign-ex")
            with pytest.raises(ConnectionError, match="beads service unavailable"):
                session._unassign_beads_item()

    def test_unassign_called_with_correct_item_id(self) -> None:
        """Validates that unassign_with_retry is called with the correct item_id."""
        with _patch_all_helpers() as m:
            m["unassign_item"].return_value = True
            session = _make_session(item_id="my-special-task")
            session._unassign_beads_item()
            m["unassign_item"].assert_called_once_with("my-special-task")

    def test_unassign_integrates_with_cleanup_on_failure(self) -> None:
        """Verifies _unassign_beads_item is called during cleanup_on_failure."""
        with _patch_all_helpers() as m:
            m["unassign_item"].return_value = True
            session = _make_session(item_id="task-cleanup-test")
            session.cleanup_on_failure()
            # Verify unassign was called as part of cleanup
            m["unassign_item"].assert_called_once_with("task-cleanup-test")
