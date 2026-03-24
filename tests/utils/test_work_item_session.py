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

            p = patch("pokepoke.beads.beads_management.unassign_item", return_value=True)
            mocks["unassign_item"] = p.start()
            patches["unassign_item"] = p

            yield mocks
        finally:
            for p in patches.values():
                p.stop()

    return _ctx()


# ---------------------------------------------------------------------------
# __exit__: success path (no-op)
# ---------------------------------------------------------------------------


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
        """Steps must run in order: journal → merge abort → worktree → branch → unassign."""
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

        # Verify ordering
        assert call_order[0] == f"journal:{SessionPhase.UNWINDING}"
        assert call_order.index("remove_worktree") < call_order.index("unassign")
        assert "delete_journal" in call_order


# ---------------------------------------------------------------------------
# cleanup_on_failure: partial failure → ABANDONED journal
# ---------------------------------------------------------------------------


class TestCleanupPartialFailure:
    """When any step fails, journal should be written as ABANDONED."""

    def test_worktree_removal_fails_writes_abandoned(self) -> None:
        with _patch_all_helpers() as m:
            m["cleanup_worktree"].return_value = False
            # _remove_worktree raises RuntimeError when cleanup_worktree returns False
            session = _make_session()
            session.cleanup_on_failure()

            # ABANDONED should be the last journal write
            last_write = m["write_journal"].call_args_list[-1]
            phase = last_write.kwargs.get("phase")
            assert phase == SessionPhase.ABANDONED

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

    def test_branch_delete_fails_writes_abandoned(self) -> None:
        with _patch_all_helpers() as m:
            m["branch_exists"].return_value = True
            m["subprocess_run"].side_effect = RuntimeError("branch -D failed")
            session = _make_session()
            session.cleanup_on_failure()

            last_write = m["write_journal"].call_args_list[-1]
            phase = last_write.kwargs.get("phase")
            assert phase == SessionPhase.ABANDONED

    def test_journal_write_fails_still_continues(self) -> None:
        """Even if writing the UNWINDING journal fails, remaining steps run."""
        with _patch_all_helpers() as m:
            m["write_journal"].side_effect = OSError("disk full")
            m["cleanup_worktree"].return_value = True
            m["unassign_item"].return_value = True

            session = _make_session()
            session.cleanup_on_failure()

            # Despite journal failure, cleanup and unassign should be attempted
            m["cleanup_worktree"].assert_called_once()
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

    def test_worktree_failure_logged_at_error(self, caplog: pytest.LogCaptureFixture) -> None:
        with _patch_all_helpers() as m:
            m["cleanup_worktree"].return_value = False
            session = _make_session()
            with caplog.at_level(logging.ERROR, logger="pokepoke.orchestration.work_item_session"):
                session.cleanup_on_failure()

            error_msgs = [r.message for r in caplog.records if r.levelno >= logging.ERROR]
            assert any("worktree" in msg.lower() for msg in error_msgs), (
                f"Expected ERROR log about worktree failure, got: {error_msgs}"
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

    def test_branch_delete_failure_logged_at_error(self, caplog: pytest.LogCaptureFixture) -> None:
        with _patch_all_helpers() as m:
            m["branch_exists"].return_value = True
            m["subprocess_run"].side_effect = RuntimeError("branch -D failed")
            session = _make_session()
            with caplog.at_level(logging.ERROR, logger="pokepoke.orchestration.work_item_session"):
                session.cleanup_on_failure()

            error_msgs = [r.message for r in caplog.records if r.levelno >= logging.ERROR]
            assert any("branch" in msg.lower() for msg in error_msgs), (
                f"Expected ERROR log about branch delete failure, got: {error_msgs}"
            )

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
            m["cleanup_worktree"].return_value = True
            m["unassign_item"].return_value = True
            session = _make_session()
            session.cleanup_on_failure()
            session.cleanup_on_failure()

            assert m["cleanup_worktree"].call_count == 2
            assert m["unassign_item"].call_count == 2


# ---------------------------------------------------------------------------
# __exit__ used as context manager
# ---------------------------------------------------------------------------


class TestContextManagerIntegration:
    """Test __exit__ behavior when used with 'with' statement."""

    def test_exception_triggers_cleanup(self) -> None:
        with _patch_all_helpers() as m:
            m["cleanup_worktree"].return_value = True
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

            m["cleanup_worktree"].assert_called_once()
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

            p = patch("pokepoke.beads.beads_management.unassign_item", return_value=True)
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
