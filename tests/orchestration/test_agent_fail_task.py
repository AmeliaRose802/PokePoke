"""Tests for agent failure task handling.

This module provides comprehensive coverage of failure paths in the
workflow orchestration, focusing on:

- _maybe_decompose: decomposition of repeatedly failing items
- Branch verification failures within the work loop
- Gate rejection cap exceeded before processing begins
- Copilot failure → decomposition triggering
- Cleanup failure stats preservation
- Session cleanup in the finally block across failure modes
- WorkItemSession rollback and partial-failure cleanup
"""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from pokepoke.agents.decomposition_agent import DecompositionResult
from pokepoke.orchestration.work_item_session import WorkItemSession
from pokepoke.orchestration.workflow import process_work_item
from pokepoke.orchestration.workflow_helpers import (
    _fail_result,
    _finalize_item_result,
    _maybe_decompose,
    _maybe_retry_copilot,
    run_cleanup_with_timeout,
)
from pokepoke.stats.session_journal import SessionPhase
from pokepoke.types import AgentStats, CopilotResult
from tests.orchestration.conftest import (
    PATCH_WF_ADD_COMMENT,
    make_process_item_mocks,
    make_work_item,
)

# ---------------------------------------------------------------------------
# Patch targets
# ---------------------------------------------------------------------------

_WF = "pokepoke.orchestration.workflow"
_WFH = "pokepoke.orchestration.workflow_helpers"
_DECOMP = "pokepoke.agents.decomposition_agent"
PATCH_WF_VERIFY_BRANCH = f"{_WF}.verify_worktree_branch"
# should_decompose and run_decomposition are imported lazily inside _maybe_decompose,
# so they must be patched at their source module.
PATCH_SHOULD_DECOMPOSE = f"{_DECOMP}.should_decompose"
PATCH_RUN_DECOMPOSITION = f"{_DECOMP}.run_decomposition"


# ═══════════════════════════════════════════════════════════════════════════
# _maybe_decompose – the only completely untested helper
# ═══════════════════════════════════════════════════════════════════════════


class TestMaybeDecompose:
    """Tests for _maybe_decompose in workflow_helpers.py."""

    def _make_config(self, *, threshold: int = 3, enabled: bool = True) -> SimpleNamespace:
        return SimpleNamespace(
            decomposition_failure_threshold=threshold,
            decomposition_enabled=enabled,
        )

    def test_triggers_when_threshold_met(self) -> None:
        """Decomposition runs when total failures >= threshold and enabled."""
        item = make_work_item(id="task-decomp", title="Decomp Task")
        config = self._make_config(threshold=3, enabled=True)
        decomp_result = DecompositionResult(
            success=True, parent_id=item.id, child_ids=["child-1", "child-2"], reason="ok",
        )
        with (
            patch(PATCH_SHOULD_DECOMPOSE, return_value=True) as mock_should,
            patch(PATCH_RUN_DECOMPOSITION, return_value=decomp_result) as mock_run,
        ):
            _maybe_decompose(item, copilot_failure_count=2, gate_rejection_count=1, config=config)
            mock_should.assert_called_once_with(item, 3, 3, True)
            mock_run.assert_called_once_with(item, 3)

    def test_skipped_when_disabled(self) -> None:
        """When config disables decomposition, should_decompose returns False."""
        item = make_work_item(id="task-no-decomp")
        config = self._make_config(enabled=False)
        with (
            patch(PATCH_SHOULD_DECOMPOSE, return_value=False) as mock_should,
            patch(PATCH_RUN_DECOMPOSITION) as mock_run,
        ):
            _maybe_decompose(item, copilot_failure_count=5, gate_rejection_count=0, config=config)
            mock_should.assert_called_once()
            mock_run.assert_not_called()

    def test_skipped_when_below_threshold(self) -> None:
        """When failures < threshold, decomposition doesn't trigger."""
        item = make_work_item(id="task-low")
        config = self._make_config(threshold=10)
        with (
            patch(PATCH_SHOULD_DECOMPOSE, return_value=False) as mock_should,
            patch(PATCH_RUN_DECOMPOSITION) as mock_run,
        ):
            _maybe_decompose(item, copilot_failure_count=1, gate_rejection_count=1, config=config)
            mock_should.assert_called_once()
            mock_run.assert_not_called()

    def test_decomposition_failure_is_silent(self) -> None:
        """If run_decomposition returns success=False, no exception is raised."""
        item = make_work_item(id="task-fail-decomp")
        config = self._make_config(threshold=1)
        decomp_result = DecompositionResult(
            success=False, parent_id=item.id, child_ids=[], reason="no subtasks",
        )
        with (
            patch(PATCH_SHOULD_DECOMPOSE, return_value=True),
            patch(PATCH_RUN_DECOMPOSITION, return_value=decomp_result),
        ):
            # Should not raise
            _maybe_decompose(item, copilot_failure_count=5, gate_rejection_count=0, config=config)

    def test_uses_config_defaults_when_attrs_missing(self) -> None:
        """Gracefully handles config objects missing decomposition attributes."""
        item = make_work_item(id="task-defaults")
        config = SimpleNamespace()  # no decomposition_* attributes
        with (
            patch(PATCH_SHOULD_DECOMPOSE, return_value=False),
            patch(PATCH_RUN_DECOMPOSITION) as mock_run,
        ):
            _maybe_decompose(item, copilot_failure_count=2, gate_rejection_count=2, config=config)
            mock_run.assert_not_called()

    def test_copilot_and_gate_failures_summed(self) -> None:
        """Total failures = copilot_failure_count + gate_rejection_count."""
        item = make_work_item(id="task-sum")
        config = self._make_config(threshold=5)
        decomp_result = DecompositionResult(
            success=True, parent_id=item.id, child_ids=["c1"], reason="ok",
        )
        with (
            patch(PATCH_SHOULD_DECOMPOSE, return_value=True),
            patch(PATCH_RUN_DECOMPOSITION, return_value=decomp_result) as mock_run,
        ):
            _maybe_decompose(item, copilot_failure_count=3, gate_rejection_count=2, config=config)
            # total_failures = 3 + 2 = 5
            mock_run.assert_called_once_with(item, 5)


# ═══════════════════════════════════════════════════════════════════════════
# Branch verification failure
# ═══════════════════════════════════════════════════════════════════════════


class TestBranchVerificationFailure:
    """When verify_worktree_branch returns an error, the workflow must fail immediately."""

    def test_branch_error_returns_fail_result(self) -> None:
        """Branch verification error → immediate failure with cleanup."""
        item = make_work_item(id="task-bad-branch", title="Bad Branch")
        with make_process_item_mocks(
            include_session_cleanup=True,
            include_cleanup_worktree=True,
        ) as mocks:
            with patch(PATCH_WF_VERIFY_BRANCH, return_value="FATAL: wrong branch 'main'"):
                result = process_work_item(item, interactive=False)

            assert result.success is False
            mocks['session_cleanup'].assert_called_once()

    def test_branch_error_preserves_accumulated_stats(self) -> None:
        """Stats accumulated before branch error should be in the result."""
        item = make_work_item(id="task-branch-stats", title="Branch Stats")
        with make_process_item_mocks(
            include_session_cleanup=True,
            include_cleanup_worktree=True,
        ):
            with patch(PATCH_WF_VERIFY_BRANCH, return_value="FATAL: branch mismatch"):
                result = process_work_item(item, interactive=False)

            assert result.success is False
            assert result.request_count == 0  # No copilot invocation happened


# ═══════════════════════════════════════════════════════════════════════════
# Gate rejection cap exceeded before processing
# ═══════════════════════════════════════════════════════════════════════════


class TestGateRejectionCapExceeded:
    """Item that already hit the gate rejection cap should be refused."""

    def test_refuses_item_at_cap(self) -> None:
        """When existing rejection count >= max, processing is refused immediately."""
        item = make_work_item(id="task-capped", title="Capped Task")
        with make_process_item_mocks(
            include_session_cleanup=True,
        ) as mocks:
            with (
                patch(
                    "pokepoke.beads.beads_management.get_gate_rejection_count",
                    return_value=5,
                ),
                patch(PATCH_WF_ADD_COMMENT),
            ):
                result = process_work_item(item, interactive=False)

            assert result.success is False
            # Should not have tried to invoke copilot
            mocks['invoke'].assert_not_called()

    def test_adds_comment_when_cap_exceeded(self) -> None:
        """A comment should be posted explaining the cap."""
        item = make_work_item(id="task-capped-comment", title="Capped Comment")
        with make_process_item_mocks():
            with (
                patch(
                    "pokepoke.beads.beads_management.get_gate_rejection_count",
                    return_value=3,
                ),
                patch(PATCH_WF_ADD_COMMENT) as mock_comment,
            ):
                result = process_work_item(item, interactive=False)

            assert result.success is False
            mock_comment.assert_called_once()
            comment_text = mock_comment.call_args[0][1]
            assert "gate rejections" in comment_text.lower() or "Refusing" in comment_text


# ═══════════════════════════════════════════════════════════════════════════
# Copilot failure triggers decomposition
# ═══════════════════════════════════════════════════════════════════════════


class TestCopilotFailureDecomposition:
    """When copilot retries are exhausted, _maybe_decompose is invoked."""

    def test_decompose_called_after_retries_exhausted(self) -> None:
        """After max retries, decomposition should be attempted."""
        item = make_work_item(id="task-decompose-trigger", title="Decompose Trigger")
        with (
            make_process_item_mocks(
                copilot_success=False,
                include_config=True,
                include_session_cleanup=True,
                include_cleanup_worktree=True,
                max_copilot_failure_retries=0,
            ),
            patch(f"{_WF}._maybe_decompose") as mock_wf_decompose,
        ):
            result = process_work_item(item, interactive=False)
            assert result.success is False
            mock_wf_decompose.assert_called_once()


# ═══════════════════════════════════════════════════════════════════════════
# Cleanup failure preserves stats
# ═══════════════════════════════════════════════════════════════════════════


class TestCleanupFailureStats:
    """Stats must be preserved even when cleanup fails."""

    def test_cleanup_timeout_preserves_stats(self) -> None:
        """run_cleanup_with_timeout returning False should still return stats."""
        item = make_work_item(id="task-cleanup-stats", title="Cleanup Stats")
        with make_process_item_mocks(
            copilot_success=True,
            include_session_cleanup=True,
            include_cleanup_worktree=True,
            include_handoff=True,
        ) as mocks:
            # Make cleanup fail
            mocks['cleanup_timeout'].return_value = (False, 2)
            result = process_work_item(item, interactive=False)

            assert result.success is False
            assert result.cleanup_agent_runs == 2


# ═══════════════════════════════════════════════════════════════════════════
# Session cleanup in finally block
# ═══════════════════════════════════════════════════════════════════════════


class TestSessionCleanupFinally:
    """The finally block must call cleanup_on_failure when _session is set."""

    def test_cleanup_runs_on_assignment_failure(self) -> None:
        """Assignment failure → session not created → no cleanup needed."""
        item = make_work_item(id="task-no-assign", title="No Assign")
        with make_process_item_mocks(
            assign_ok=False,
            include_session_cleanup=True,
        ) as mocks:
            result = process_work_item(item, interactive=False)

            assert result.success is False
            # Session is not created yet at assignment failure, so no cleanup
            mocks['session_cleanup'].assert_not_called()

    def test_cleanup_runs_on_worktree_failure(self) -> None:
        """Worktree failure after assignment → session cleanup runs."""
        item = make_work_item(id="task-wt-fail", title="WT Fail")
        with make_process_item_mocks(
            worktree_path=None,
            include_session_cleanup=True,
        ) as mocks:
            mocks['setup'].return_value = None
            result = process_work_item(item, interactive=False)

            assert result.success is False
            # Session was created (after assignment) but worktree failed
            mocks['session_cleanup'].assert_called_once()

    def test_cleanup_skipped_on_success(self) -> None:
        """Successful finalization → _session set to None → no cleanup."""
        item = make_work_item(id="task-ok", title="OK Task")
        with make_process_item_mocks(
            include_handoff=True,
            include_session_cleanup=True,
            include_cleanup_worktree=True,
        ) as mocks:
            result = process_work_item(item, interactive=False)

            assert result.success is True
            mocks['session_cleanup'].assert_not_called()

    def test_cleanup_skipped_during_shutdown(self) -> None:
        """If is_shutting_down() is True, cleanup_on_failure should NOT run."""
        item = make_work_item(id="task-shutdown", title="Shutdown Task")
        with make_process_item_mocks(
            copilot_success=False,
            include_session_cleanup=True,
            include_cleanup_worktree=True,
        ) as mocks:
            with patch(f"{_WF}.is_shutting_down", return_value=True):
                process_work_item(item, interactive=False)
            # During shutdown, cleanup_on_failure should NOT be called
            mocks['session_cleanup'].assert_not_called()


# ═══════════════════════════════════════════════════════════════════════════
# _fail_result validation
# ═══════════════════════════════════════════════════════════════════════════


class TestFailResultValidation:
    """Ensure _fail_result produces correct WorkItemResult in all variants."""

    def test_default_fail_result(self) -> None:
        """Default _fail_result has success=False and zero counters."""
        result = _fail_result()
        assert result.success is False
        assert result.request_count == 0
        assert result.stats is None
        assert result.cleanup_agent_runs == 0
        assert result.gate_agent_runs == 0
        assert result.model_completion is None

    def test_fail_result_with_stats(self) -> None:
        """_fail_result preserves all provided parameters."""
        stats = AgentStats()
        stats.input_tokens = 100
        stats.output_tokens = 50
        from pokepoke.types import ModelCompletionRecord
        completion = ModelCompletionRecord(
            item_id="test", model="gpt-4", duration_seconds=10.0,
            gate_passed=False, input_tokens=100, output_tokens=50,
            agent_turns=3, retry_attempts=2,
        )
        result = _fail_result(
            request_count=3,
            stats=stats,
            cleanup_agent_runs=2,
            gate_agent_runs=1,
            model_completion=completion,
        )
        assert result.success is False
        assert result.request_count == 3
        assert result.stats.input_tokens == 100
        assert result.cleanup_agent_runs == 2
        assert result.gate_agent_runs == 1
        assert result.model_completion is not None
        assert result.model_completion.item_id == "test"


# ═══════════════════════════════════════════════════════════════════════════
# _maybe_retry_copilot edge cases
# ═══════════════════════════════════════════════════════════════════════════


class TestMaybeRetryCopilotEdgeCases:
    """Edge cases for _maybe_retry_copilot."""

    def test_retry_with_session_resume(self) -> None:
        """When result has session_id and output_summary, feedback includes resume note."""
        result = CopilotResult(
            work_item_id="task-1", success=False,
            error="timeout", attempt_count=1,
            session_id="sess-123",
            last_output_summary="did some work",
        )
        should_retry, feedback = _maybe_retry_copilot(
            result, failure_count=1, max_retries=3, run_logger=None, item_id="task-1",
        )
        assert should_retry is True
        assert "timeout" in feedback

    def test_no_retry_at_exact_boundary(self) -> None:
        """When failure_count == max_retries, should still retry (> is the cutoff)."""
        result = CopilotResult(
            work_item_id="task-1", success=False,
            error="some error", attempt_count=1,
        )
        should_retry, _ = _maybe_retry_copilot(
            result, failure_count=3, max_retries=3, run_logger=None, item_id="task-1",
        )
        assert should_retry is True

    def test_no_retry_past_boundary(self) -> None:
        """When failure_count > max_retries, should not retry."""
        result = CopilotResult(
            work_item_id="task-1", success=False,
            error="some error", attempt_count=1,
        )
        should_retry, _ = _maybe_retry_copilot(
            result, failure_count=4, max_retries=3, run_logger=None, item_id="task-1",
        )
        assert should_retry is False

    def test_no_error_provides_default_feedback(self) -> None:
        """When result.error is empty, default feedback is used."""
        result = CopilotResult(
            work_item_id="task-1", success=False,
            error="", attempt_count=1,
        )
        should_retry, feedback = _maybe_retry_copilot(
            result, failure_count=1, max_retries=3, run_logger=None, item_id="task-1",
        )
        assert should_retry is True
        assert "did not complete" in feedback


# ═══════════════════════════════════════════════════════════════════════════
# WorkItemSession: rollback_enter and cleanup partial failures
# ═══════════════════════════════════════════════════════════════════════════


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
    session._assigned = True
    session._branch_created = True
    session._worktree_created = True
    return session


def _patch_session_helpers():
    """Patch all WorkItemSession internal helpers for isolation."""
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

            p = patch("pokepoke.orchestration.work_item_session.is_merge_in_progress", return_value=False)
            mocks["is_merge"] = p.start()
            patches["is_merge"] = p

            p = patch("pokepoke.orchestration.work_item_session.run_git")
            mocks["run_git"] = p.start()
            patches["run_git"] = p

            p = patch("pokepoke.worktrees.worktrees.cleanup_worktree", return_value=True)
            mocks["cleanup_worktree"] = p.start()
            patches["cleanup_worktree"] = p

            p = patch("pokepoke.git.git_operations.branch_exists", return_value=False)
            mocks["branch_exists"] = p.start()
            patches["branch_exists"] = p

            p = patch("pokepoke.beads.beads_management.unassign_item", return_value=True)
            mocks["unassign_item"] = p.start()
            patches["unassign_item"] = p

            p = patch("pokepoke.beads.beads_management.assign_and_sync_item", return_value=True)
            mocks["assign"] = p.start()
            patches["assign"] = p

            p = patch("pokepoke.worktrees.worktrees.create_worktree", return_value=Path("/tmp/wt"))
            mocks["create_worktree"] = p.start()
            patches["create_worktree"] = p

            yield mocks
        finally:
            for p in patches.values():
                p.stop()

    return _ctx()


class TestSessionRollbackEnter:
    """Tests for WorkItemSession._rollback_enter when __enter__ fails partway."""

    def test_rollback_on_worktree_creation_failure(self) -> None:
        """If create_worktree raises, rollback should unassign the item."""
        with _patch_session_helpers() as m:
            m["create_worktree"].side_effect = RuntimeError("disk full")
            session = WorkItemSession(
                item_id="test-rollback",
                agent_name="test-agent",
            )
            with pytest.raises(RuntimeError, match="disk full"):
                session.__enter__()

            # Assignment happened, so unassign should be called during rollback
            m["unassign_item"].assert_called_once()

    def test_rollback_on_assignment_failure(self) -> None:
        """If assignment fails, rollback should delete the journal."""
        with _patch_session_helpers() as m:
            m["assign"].return_value = False
            session = WorkItemSession(
                item_id="test-assign-fail",
                agent_name="test-agent",
            )
            with pytest.raises(RuntimeError, match="Failed to assign"):
                session.__enter__()

            # Journal should be deleted in rollback
            m["delete_journal"].assert_called()


class TestSessionCleanupPartialFailure:
    """Tests for cleanup_on_failure when some steps fail."""

    def test_unassign_failure_writes_abandoned_journal(self) -> None:
        """When unassign fails, ABANDONED journal should be written."""
        with _patch_session_helpers() as m:
            m["unassign_item"].side_effect = RuntimeError("beads down")
            session = _make_session()
            session.cleanup_on_failure()

            # Should write ABANDONED since not all_ok
            abandoned_calls = [
                c for c in m["write_journal"].call_args_list
                if c.kwargs.get("phase") == SessionPhase.ABANDONED
            ]
            assert len(abandoned_calls) == 1

    def test_journal_write_failure_still_attempts_unassign(self) -> None:
        """Even if writing UNWINDING journal fails, unassign should still be attempted."""
        with _patch_session_helpers() as m:
            m["write_journal"].side_effect = [
                RuntimeError("journal write failed"),  # UNWINDING fails
                Path("/j.json"),  # ABANDONED succeeds
            ]
            session = _make_session()
            session.cleanup_on_failure()

            m["unassign_item"].assert_called_once()

    def test_merge_abort_attempted_when_merge_in_progress(self, tmp_path: Path) -> None:
        """When a merge is in progress, abort should be called during cleanup."""
        wt_dir = tmp_path / "wt" / "task-merge-test"
        wt_dir.mkdir(parents=True)
        with _patch_session_helpers() as m:
            m["is_merge"].return_value = True
            session = _make_session(worktree_path=str(wt_dir))
            session.cleanup_on_failure()

            m["run_git"].assert_called()
            # Verify merge --abort was called
            git_calls = m["run_git"].call_args_list
            merge_abort_calls = [
                c for c in git_calls
                if any("merge" in str(arg) and "--abort" in str(arg) for arg in c.args)
            ]
            assert len(merge_abort_calls) >= 1

    def test_worktree_preserved_on_failure(self) -> None:
        """Worktree and branch should NOT be removed during cleanup_on_failure."""
        with _patch_session_helpers() as m:
            session = _make_session()
            session.cleanup_on_failure()

            # cleanup_worktree should NOT be called — worktree is preserved
            m["cleanup_worktree"].assert_not_called()

    def test_all_steps_attempted_even_when_early_steps_fail(self) -> None:
        """Each cleanup step runs regardless of prior step failures."""
        with _patch_session_helpers() as m:
            # Journal write fails, merge abort fails, but unassign should still run
            m["write_journal"].side_effect = [
                RuntimeError("journal fail"),  # UNWINDING
                Path("/j.json"),  # ABANDONED
            ]
            m["is_merge"].return_value = True
            m["run_git"].side_effect = RuntimeError("git fail")

            session = _make_session()
            session.cleanup_on_failure()

            # Despite earlier failures, unassign should still be attempted
            m["unassign_item"].assert_called_once()


# ═══════════════════════════════════════════════════════════════════════════
# run_cleanup_with_timeout edge cases
# ═══════════════════════════════════════════════════════════════════════════


class TestRunCleanupWithTimeoutEdgeCases:
    """Edge cases for run_cleanup_with_timeout."""

    def test_no_cleanup_when_result_not_successful(self) -> None:
        """If result.success is False, cleanup loop should not execute."""
        item = make_work_item()
        result = CopilotResult(
            work_item_id="task-1", success=False, output="", attempt_count=1,
        )
        with (
            patch(f"{_WFH}.has_uncommitted_changes", return_value=True),
            patch(f"{_WFH}.run_cleanup_loop") as mock_cleanup,
        ):
            _, runs = run_cleanup_with_timeout(
                item, result, Path("/repo"), start_time=0.0,
                timeout_seconds=3600, timeout_hours=1.0,
            )
            assert runs == 0
            mock_cleanup.assert_not_called()

    def test_no_cleanup_when_no_uncommitted_changes(self) -> None:
        """If no uncommitted changes, cleanup loop should not run."""
        item = make_work_item()
        result = CopilotResult(
            work_item_id="task-1", success=True, output="done", attempt_count=1,
        )
        with (
            patch(f"{_WFH}.has_uncommitted_changes", return_value=False),
            patch(f"{_WFH}.run_cleanup_loop") as mock_cleanup,
        ):
            success, runs = run_cleanup_with_timeout(
                item, result, Path("/repo"), start_time=0.0,
                timeout_seconds=3600, timeout_hours=1.0,
            )
            assert success is True
            assert runs == 0
            mock_cleanup.assert_not_called()

    def test_multiple_cleanup_attempts_tracked(self) -> None:
        """Cleanup runs accumulate across multiple iterations."""
        item = make_work_item()
        result = CopilotResult(
            work_item_id="task-1", success=True, output="done", attempt_count=1,
        )
        call_count = 0

        def uncommitted_side_effect(cwd=None):
            nonlocal call_count
            call_count += 1
            return call_count <= 2  # uncommitted for first 2 calls, then clean

        with (
            patch(f"{_WFH}.has_uncommitted_changes", side_effect=uncommitted_side_effect),
            patch(f"{_WFH}.run_cleanup_loop", return_value=(True, 1)) as mock_cleanup,
            patch("time.time", return_value=0.0),
        ):
            success, runs = run_cleanup_with_timeout(
                item, result, Path("/repo"), start_time=0.0,
                timeout_seconds=3600, timeout_hours=1.0,
            )
            assert success is True
            assert runs == 2
            assert mock_cleanup.call_count == 2


# ═══════════════════════════════════════════════════════════════════════════
# Finalization reconciliation
# ═══════════════════════════════════════════════════════════════════════════


class TestFinalizeReconciliation:
    """Tests for the reconciliation path in _finalize_item_result."""

    def test_failure_reconciled_as_success(self) -> None:
        """When copilot reports failure but state shows work done, reconcile to success."""
        result = CopilotResult(
            work_item_id="task-reconcile", success=False,
            error="process died", attempt_count=1,
        )
        item = make_work_item(id="task-reconcile", title="Reconcile Task")

        with (
            patch(
                "pokepoke.orchestration.workflow_helpers.reconcile_completed_item",
                return_value=(True, {"beads_closed": True, "commits_on_default": 2}),
            ),
            patch("pokepoke.orchestration.workflow_helpers.terminal_ui"),
        ):
            wi_result, finalized = _finalize_item_result(
                result=result,
                item=item,
                worktree_path=Path("/fake/wt"),
                selected_model="test-model",
                start_time=0.0,
                request_count=1,
                accumulated_stats=AgentStats(),
                cleanup_agent_runs=0,
                gate_agent_runs=0,
                gate_success=False,
                run_logger=None,
                item_logger=None,
                base_agent_id="test-agent",
                run_beta_test=False,
            )

        assert wi_result.success is True
        assert finalized is True

    def test_failure_not_reconciled_returns_failure(self) -> None:
        """When reconciliation finds no evidence, result stays failure."""
        result = CopilotResult(
            work_item_id="task-no-reconcile", success=False,
            error="agent crashed", attempt_count=1,
        )
        item = make_work_item(id="task-no-reconcile", title="No Reconcile")

        with (
            patch(
                "pokepoke.orchestration.workflow_helpers.reconcile_completed_item",
                return_value=(False, {}),
            ),
            patch("pokepoke.orchestration.workflow_helpers.terminal_ui"),
        ):
            wi_result, finalized = _finalize_item_result(
                result=result,
                item=item,
                worktree_path=Path("/fake/wt"),
                selected_model="test-model",
                start_time=0.0,
                request_count=1,
                accumulated_stats=AgentStats(),
                cleanup_agent_runs=0,
                gate_agent_runs=0,
                gate_success=False,
                run_logger=None,
                item_logger=None,
                base_agent_id="test-agent",
                run_beta_test=False,
            )

        assert wi_result.success is False
        assert finalized is False

    def test_reconciliation_exception_treated_as_failure(self) -> None:
        """If reconciliation raises, result stays failure (best-effort)."""
        result = CopilotResult(
            work_item_id="task-reconcile-err", success=False,
            error="agent failed", attempt_count=1,
        )
        item = make_work_item(id="task-reconcile-err", title="Reconcile Error")

        with (
            patch(
                "pokepoke.orchestration.workflow_helpers.reconcile_completed_item",
                side_effect=RuntimeError("db error"),
            ),
            patch("pokepoke.orchestration.workflow_helpers.terminal_ui"),
        ):
            wi_result, finalized = _finalize_item_result(
                result=result,
                item=item,
                worktree_path=Path("/fake/wt"),
                selected_model="test-model",
                start_time=0.0,
                request_count=1,
                accumulated_stats=AgentStats(),
                cleanup_agent_runs=0,
                gate_agent_runs=0,
                gate_success=False,
                run_logger=None,
                item_logger=None,
                base_agent_id="test-agent",
                run_beta_test=False,
            )

        assert wi_result.success is False
        assert finalized is False


# ═══════════════════════════════════════════════════════════════════════════
# Process crash detection
# ═══════════════════════════════════════════════════════════════════════════


class TestProcessCrashDetection:
    """Tests for process crash detection and its effect on gate skipping."""

    def test_process_died_skips_gate(self) -> None:
        """'Process died' error should skip gate agent."""
        item = make_work_item(id="task-crash", title="Crash Task")
        result_obj = CopilotResult(
            work_item_id="task-crash",
            success=True,  # work completed despite crash
            output="some output",
            error="Process died: consecutive ping failures or output timeout",
            attempt_count=1,
        )
        with make_process_item_mocks(
            include_handoff=True,
            include_cleanup_worktree=True,
            include_session_cleanup=True,
        ) as mocks:
            mocks['invoke'].return_value = result_obj
            process_work_item(item, interactive=False)

            # Gate should not have been called
            mocks['gate'].assert_not_called()

    def test_exited_unexpectedly_skips_gate(self) -> None:
        """'Exited unexpectedly' error should skip gate agent."""
        item = make_work_item(id="task-exit", title="Exit Task")
        result_obj = CopilotResult(
            work_item_id="task-exit",
            success=True,
            output="partial work",
            error="SDK process exited unexpectedly",
            attempt_count=1,
        )
        with make_process_item_mocks(
            include_handoff=True,
            include_cleanup_worktree=True,
            include_session_cleanup=True,
        ) as mocks:
            mocks['invoke'].return_value = result_obj
            process_work_item(item, interactive=False)

            mocks['gate'].assert_not_called()


# ═══════════════════════════════════════════════════════════════════════════
# Timeout restart exhaustion
# ═══════════════════════════════════════════════════════════════════════════


class TestTimeoutRestartExhaustion:
    """Tests for timeout restart limits."""

    def test_max_restarts_exceeded_fails(self) -> None:
        """When max_timeout_restarts is exceeded, processing fails."""
        item = make_work_item(id="task-timeout", title="Timeout Task")
        call_count = 0

        def time_side_effect():
            nonlocal call_count
            call_count += 1
            # Return increasing time values so timeout is always exceeded
            return call_count * 10000.0

        with make_process_item_mocks(
            include_session_cleanup=True,
            include_cleanup_worktree=True,
        ) as mocks:
            mocks['time'].side_effect = time_side_effect
            result = process_work_item(
                item, interactive=False,
                timeout_hours=0.001,  # Very short timeout
                max_timeout_restarts=0,  # No restarts allowed
            )

            assert result.success is False
            mocks['session_cleanup'].assert_called()
