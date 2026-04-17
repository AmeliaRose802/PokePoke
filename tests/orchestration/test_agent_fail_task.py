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
from pokepoke.orchestration.finalization import ResultContext, _finalize_item_result
from pokepoke.orchestration.work_item_session import WorkItemSession
from pokepoke.orchestration.workflow import WorkItemConfig, process_work_item
from pokepoke.orchestration.workflow_helpers import (
    _fail_result,
    _log_failure,
    _maybe_decompose,
    _maybe_retry_copilot,
    run_cleanup_with_timeout,
)
from pokepoke.stats.session_journal import SessionPhase
from pokepoke.types_agent import CopilotResult, GateAgentResult
from pokepoke.types_stats import AgentStats
from tests.orchestration.conftest import (
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
    """Gate rejection cap is now enforced at the scheduling layer (work_item_selection),
    not inside process_work_item.  These tests verify that process_work_item
    still correctly increments the counter and defers when the gate actually rejects."""

    def test_gate_rejection_increments_and_defers_at_cap(self) -> None:
        """When gate rejects and count hits cap, item is deferred."""
        item = make_work_item(id="task-capped", title="Capped Task",
                              metadata={'gate_rejection_count': '2'})
        with make_process_item_mocks(
            include_session_cleanup=True,
            include_handoff=True,
            gate_result=GateAgentResult(success=False, reason="Quality issues"),
        ):
            with (
                patch(f"{_WF}.defer_item") as mock_defer,
                patch(f"{_WF}._maybe_decompose"),
            ):
                result = process_work_item(item, interactive=False)

            assert result.success is False
            # Gate rejected → should have deferred
            mock_defer.assert_called_once()

    def test_item_at_cap_still_processes_if_gate_passes(self) -> None:
        """Items with high prior rejections still run if scheduling lets them through."""
        item = make_work_item(id="task-capped-pass", title="Capped Pass",
                              metadata={'gate_rejection_count': '5'})
        with make_process_item_mocks(
            include_session_cleanup=True,
            include_handoff=True,
            gate_success=True,
        ):
            result = process_work_item(item, interactive=False)

            assert result.success is True


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
        from pokepoke.types_stats import ModelCompletionRecord
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
                OSError("journal write failed"),  # UNWINDING fails
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
                OSError("journal fail"),  # UNWINDING
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
                "pokepoke.orchestration.finalization.reconcile_completed_item",
                return_value=(True, {"beads_closed": True, "commits_on_default": 2}),
            ),
            patch("pokepoke.orchestration.finalization.terminal_ui"),
        ):
            wi_result, finalized = _finalize_item_result(ResultContext(
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
            ))

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
                "pokepoke.orchestration.finalization.reconcile_completed_item",
                return_value=(False, {}),
            ),
            patch("pokepoke.orchestration.finalization.terminal_ui"),
        ):
            wi_result, finalized = _finalize_item_result(ResultContext(
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
            ))

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
                "pokepoke.orchestration.finalization.reconcile_completed_item",
                side_effect=RuntimeError("db error"),
            ),
            patch("pokepoke.orchestration.finalization.terminal_ui"),
        ):
            wi_result, finalized = _finalize_item_result(ResultContext(
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
            ))

        assert wi_result.success is False
        assert finalized is False


# ═══════════════════════════════════════════════════════════════════════════
# Process crash detection
# ═══════════════════════════════════════════════════════════════════════════


class TestProcessCrashDetection:
    """Tests for process crash detection behavior."""

    def test_process_died_still_runs_gate_on_success(self) -> None:
        """'Process died' error with success=True still runs gate agent."""
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

            # Gate IS called since result.success is True
            mocks['gate'].assert_called_once()

    def test_exited_unexpectedly_still_runs_gate_on_success(self) -> None:
        """'Exited unexpectedly' error with success=True still runs gate agent."""
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

            mocks['gate'].assert_called_once()


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
                config=WorkItemConfig(
                    timeout_hours=0.001,  # Very short timeout
                    max_timeout_restarts=0,  # No restarts allowed
                ),
            )

            assert result.success is False
            mocks['session_cleanup'].assert_called()


# ═══════════════════════════════════════════════════════════════════════════
# _log_failure with loggers
# ═══════════════════════════════════════════════════════════════════════════


class TestLogFailure:
    """Tests for _log_failure helper."""

    def test_logs_when_both_loggers_present(self) -> None:
        """Both loggers receive calls when provided."""
        from unittest.mock import Mock
        run_logger = Mock()
        item_logger = Mock()
        _log_failure(run_logger, item_logger, request_count=5)
        item_logger.log_summary.assert_called_once_with(False, 5)
        run_logger.log_orchestrator.assert_called_once()
        assert "5 agent requests" in run_logger.log_orchestrator.call_args[0][0]
        assert "FAILURE" in run_logger.log_orchestrator.call_args[0][0]

    def test_noop_when_run_logger_is_none(self) -> None:
        """No error when run_logger is None."""
        from unittest.mock import Mock
        item_logger = Mock()
        _log_failure(None, item_logger, request_count=1)
        item_logger.log_summary.assert_not_called()

    def test_noop_when_item_logger_is_none(self) -> None:
        """No error when item_logger is None."""
        from unittest.mock import Mock
        run_logger = Mock()
        _log_failure(run_logger, None, request_count=1)
        run_logger.log_orchestrator.assert_not_called()

    def test_noop_when_both_loggers_none(self) -> None:
        """No error when both loggers are None."""
        _log_failure(None, None, request_count=0)

    def test_default_request_count_is_zero(self) -> None:
        """Default request_count is 0."""
        from unittest.mock import Mock
        run_logger = Mock()
        item_logger = Mock()
        _log_failure(run_logger, item_logger)
        item_logger.log_summary.assert_called_once_with(False, 0)


# ═══════════════════════════════════════════════════════════════════════════
# _build_completion_record validation
# ═══════════════════════════════════════════════════════════════════════════


class TestBuildCompletionRecord:
    """Tests for _build_completion_record in finalization.py."""

    def test_basic_completion_record(self) -> None:
        """Build a record with full stats."""
        from pokepoke.orchestration.finalization import _build_completion_record
        stats = AgentStats()
        stats.input_tokens = 500
        stats.output_tokens = 200
        stats.api_duration = 1.5
        stats.lines_added = 10
        stats.lines_removed = 3
        record = _build_completion_record(
            "item-1", "model-x", 120.0, True, True, stats, 4,
        )
        assert record.item_id == "item-1"
        assert record.model == "model-x"
        assert record.duration_seconds == 120.0
        assert record.gate_passed is True
        assert record.input_tokens == 500
        assert record.output_tokens == 200
        assert record.agent_turns == 4
        assert record.retry_attempts == 3
        assert record.api_duration == 1.5
        assert record.lines_added == 10
        assert record.lines_removed == 3

    def test_completion_record_with_none_stats(self) -> None:
        """Stats default to 0 when stats is None."""
        from pokepoke.orchestration.finalization import _build_completion_record
        record = _build_completion_record(
            "item-2", "model-y", 60.0, False, None, None, 1,
        )
        assert record.input_tokens == 0
        assert record.output_tokens == 0
        assert record.agent_turns == 1
        assert record.retry_attempts == 0
        assert record.api_duration is None
        assert record.lines_added is None
        assert record.lines_removed is None

    def test_single_request_has_zero_retries(self) -> None:
        """retry_attempts = max(0, request_count - 1)."""
        from pokepoke.orchestration.finalization import _build_completion_record
        record = _build_completion_record("i", "m", 1.0, True, None, None, 1)
        assert record.retry_attempts == 0

    def test_zero_requests_has_zero_retries(self) -> None:
        """retry_attempts never goes negative."""
        from pokepoke.orchestration.finalization import _build_completion_record
        record = _build_completion_record("i", "m", 1.0, False, None, None, 0)
        assert record.retry_attempts == 0


# ═══════════════════════════════════════════════════════════════════════════
# _extract_agent_stats
# ═══════════════════════════════════════════════════════════════════════════


class TestExtractAgentStats:
    """Tests for _extract_agent_stats helper."""

    def test_returns_stats_from_result_directly(self) -> None:
        """When result.stats is set, return it directly."""
        from pokepoke.orchestration.workflow_helpers import _extract_agent_stats
        stats = AgentStats()
        stats.input_tokens = 42
        result = CopilotResult(
            work_item_id="t1", success=True, output="x", attempt_count=1,
            stats=stats,
        )
        extracted = _extract_agent_stats(result)
        assert extracted is stats

    def test_parses_stats_from_output(self) -> None:
        """When result.stats is None, parse from output."""
        from pokepoke.orchestration.workflow_helpers import _extract_agent_stats
        result = CopilotResult(
            work_item_id="t1", success=True, output="some output text",
            attempt_count=1,
        )
        with patch("pokepoke.stats.stats.parse_agent_stats") as mock_parse:
            mock_parse.return_value = AgentStats()
            extracted = _extract_agent_stats(result)
            mock_parse.assert_called_once_with("some output text")
            assert extracted is not None

    def test_returns_none_for_no_stats_no_output(self) -> None:
        """When both stats and output are empty/None, return None."""
        from pokepoke.orchestration.workflow_helpers import _extract_agent_stats
        result = CopilotResult(
            work_item_id="t1", success=True, output="", attempt_count=1,
        )
        extracted = _extract_agent_stats(result)
        assert extracted is None


# ═══════════════════════════════════════════════════════════════════════════
# _apply_gate_feedback
# ═══════════════════════════════════════════════════════════════════════════


class TestApplyGateFeedback:
    """Tests for _apply_gate_feedback helper."""

    def test_appends_feedback_and_bumps_iteration(self) -> None:
        """New feedback is appended, iteration incremented."""
        from pokepoke.orchestration.workflow_helpers import _apply_gate_feedback
        updated, next_iter = _apply_gate_feedback("fix tests", [], 0)
        assert updated == ["fix tests"]
        assert next_iter == 1

    def test_trims_to_last_three(self) -> None:
        """Only the last 3 feedback entries are kept."""
        from pokepoke.orchestration.workflow_helpers import _apply_gate_feedback
        existing = ["a", "b", "c"]
        updated, next_iter = _apply_gate_feedback("d", existing, 3)
        assert updated == ["b", "c", "d"]
        assert next_iter == 4

    def test_does_not_mutate_original_list(self) -> None:
        """Original feedback list is not modified."""
        from pokepoke.orchestration.workflow_helpers import _apply_gate_feedback
        original = ["x", "y"]
        _apply_gate_feedback("z", original, 1)
        assert original == ["x", "y"]


# ═══════════════════════════════════════════════════════════════════════════
# _log_commit_status
# ═══════════════════════════════════════════════════════════════════════════


class TestLogCommitStatus:
    """Tests for _log_commit_status helper."""

    def test_returns_early_when_uncommitted_changes(self) -> None:
        """When uncommitted changes exist, just return."""
        from pokepoke.orchestration.workflow_helpers import _log_commit_status
        with (
            patch(f"{_WFH}.has_uncommitted_changes", return_value=True),
            patch("pokepoke.git.git_operations.has_commits_ahead") as mock_ahead,
        ):
            _log_commit_status("/some/path")
            mock_ahead.assert_not_called()

    def test_logs_commits_ahead(self) -> None:
        """When no uncommitted changes and commits ahead, logs skip message."""
        from pokepoke.orchestration.workflow_helpers import _log_commit_status
        with (
            patch(f"{_WFH}.has_uncommitted_changes", return_value=False),
            patch("pokepoke.git.git_operations.has_commits_ahead", return_value=3),
        ):
            _log_commit_status("/some/path")

    def test_logs_no_changes_when_zero_ahead(self) -> None:
        """When no uncommitted and zero commits ahead, logs no-changes message."""
        from pokepoke.orchestration.workflow_helpers import _log_commit_status
        with (
            patch(f"{_WFH}.has_uncommitted_changes", return_value=False),
            patch("pokepoke.git.git_operations.has_commits_ahead", return_value=0),
        ):
            _log_commit_status("/some/path")


# ═══════════════════════════════════════════════════════════════════════════
# _maybe_retry_copilot with run_logger
# ═══════════════════════════════════════════════════════════════════════════


class TestMaybeRetryCopilotWithLogger:
    """Tests for _maybe_retry_copilot when run_logger is provided."""

    def test_logs_retry_with_run_logger(self) -> None:
        """Run logger receives retry information."""
        from unittest.mock import Mock
        run_logger = Mock()
        result = CopilotResult(
            work_item_id="task-1", success=False,
            error="timeout", attempt_count=1,
        )
        should_retry, _feedback = _maybe_retry_copilot(
            result, failure_count=1, max_retries=3, run_logger=run_logger,
            item_id="task-1",
        )
        assert should_retry is True
        run_logger.log_orchestrator.assert_called_once()
        assert "task-1" in run_logger.log_orchestrator.call_args[0][0]

    def test_rate_limited_result_does_not_retry(self) -> None:
        """Rate-limited results should not retry regardless of count."""
        result = CopilotResult(
            work_item_id="task-1", success=False,
            error="rate limited", attempt_count=1,
            is_rate_limited=True,
        )
        should_retry, _ = _maybe_retry_copilot(
            result, failure_count=1, max_retries=10, run_logger=None,
            item_id="task-1",
        )
        assert should_retry is False


# ═══════════════════════════════════════════════════════════════════════════
# run_cleanup_with_timeout – timeout path
# ═══════════════════════════════════════════════════════════════════════════


class TestCleanupTimeoutPath:
    """Tests for the timeout branch in run_cleanup_with_timeout."""

    def test_returns_false_when_timeout_exceeded(self) -> None:
        """When elapsed >= timeout_seconds during cleanup, returns (False, runs)."""
        item = make_work_item()
        result = CopilotResult(
            work_item_id="task-1", success=True, output="done", attempt_count=1,
        )
        time_call = 0

        def time_side(*_a, **_kw):
            nonlocal time_call
            time_call += 1
            return time_call * 5000.0

        with (
            patch(f"{_WFH}.has_uncommitted_changes", return_value=True),
            patch(f"{_WFH}.run_cleanup_loop", return_value=(True, 1)),
            patch("time.time", side_effect=time_side),
        ):
            success, runs = run_cleanup_with_timeout(
                item, result, Path("/repo"), start_time=0.0,
                timeout_seconds=100, timeout_hours=0.03,
            )
            assert success is False
            assert runs == 0

    def test_cleanup_loop_failure_breaks_loop(self) -> None:
        """When run_cleanup_loop returns success=False, loop breaks."""
        item = make_work_item()
        result = CopilotResult(
            work_item_id="task-1", success=True, output="done", attempt_count=1,
        )
        call_count = 0

        def uncommitted_side_effect(cwd=None):
            nonlocal call_count
            call_count += 1
            return True  # always uncommitted

        with (
            patch(f"{_WFH}.has_uncommitted_changes", side_effect=uncommitted_side_effect),
            patch(f"{_WFH}.run_cleanup_loop", return_value=(False, 1)),
            patch("time.time", return_value=0.0),
        ):
            _success, runs = run_cleanup_with_timeout(
                item, result, Path("/repo"), start_time=0.0,
                timeout_seconds=3600, timeout_hours=1.0,
            )
            # Loop broke due to cleanup failure, not timeout
            assert runs == 1


# ═══════════════════════════════════════════════════════════════════════════
# _fail_result with failure_reason
# ═══════════════════════════════════════════════════════════════════════════


class TestFailResultWithReason:
    """Tests for _fail_result carrying failure_reason."""

    def test_fail_result_carries_failure_reason(self) -> None:
        """failure_reason is passed through to WorkItemResult."""
        result = _fail_result(failure_reason="agent timed out")
        assert result.failure_reason == "agent timed out"
        assert result.success is False

    def test_fail_result_none_reason(self) -> None:
        """Default failure_reason is None."""
        result = _fail_result()
        assert result.failure_reason is None


# ═══════════════════════════════════════════════════════════════════════════
# Reconciliation with loggers
# ═══════════════════════════════════════════════════════════════════════════


class TestReconcileWithLoggers:
    """Tests for _reconcile_as_success when loggers are provided."""

    def test_reconcile_logs_to_both_loggers(self) -> None:
        """When loggers are present, reconciliation logs to both."""
        from unittest.mock import Mock
        result = CopilotResult(
            work_item_id="task-log", success=False,
            error="died", attempt_count=1,
        )
        item = make_work_item(id="task-log", title="Log Task")
        run_logger = Mock()
        item_logger = Mock()

        with (
            patch(
                "pokepoke.orchestration.finalization.reconcile_completed_item",
                return_value=(True, {"beads_closed": True}),
            ),
            patch("pokepoke.orchestration.finalization.terminal_ui"),
        ):
            wi_result, _finalized = _finalize_item_result(ResultContext(
                result=result,
                item=item,
                worktree_path=Path("/fake/wt"),
                selected_model="test-model",
                start_time=0.0,
                request_count=2,
                accumulated_stats=AgentStats(),
                cleanup_agent_runs=0,
                gate_agent_runs=0,
                gate_success=False,
                run_logger=run_logger,
                item_logger=item_logger,
                base_agent_id="test-agent",
                run_beta_test=False,
            ))

        assert wi_result.success is True
        item_logger.log_summary.assert_called_once_with(True, 2)
        run_logger.log_orchestrator.assert_called_once()
        assert "reconciled" in run_logger.log_orchestrator.call_args[0][0].lower()


# ═══════════════════════════════════════════════════════════════════════════
# _handle_failure with loggers
# ═══════════════════════════════════════════════════════════════════════════


class TestHandleFailureWithLoggers:
    """Tests for _handle_failure logging behavior."""

    def test_failure_logs_to_both_loggers(self) -> None:
        """When loggers are present, failure logs to both."""
        from unittest.mock import Mock
        result = CopilotResult(
            work_item_id="task-fail-log", success=False,
            error="agent crashed hard", attempt_count=1,
        )
        item = make_work_item(id="task-fail-log", title="Fail Log Task")
        run_logger = Mock()
        item_logger = Mock()

        with (
            patch(
                "pokepoke.orchestration.finalization.reconcile_completed_item",
                return_value=(False, {}),
            ),
            patch("pokepoke.orchestration.finalization.terminal_ui"),
            patch("pokepoke.beads.beads_management.fail_task") as mock_fail,
        ):
            wi_result, finalized = _finalize_item_result(ResultContext(
                result=result,
                item=item,
                worktree_path=Path("/fake/wt"),
                selected_model="test-model",
                start_time=0.0,
                request_count=3,
                accumulated_stats=AgentStats(),
                cleanup_agent_runs=1,
                gate_agent_runs=2,
                gate_success=False,
                run_logger=run_logger,
                item_logger=item_logger,
                base_agent_id="test-agent",
                run_beta_test=False,
            ))

        assert wi_result.success is False
        assert finalized is False
        mock_fail.assert_called_once_with("task-fail-log", "agent crashed hard")
        # _log_failure is called internally
        item_logger.log_summary.assert_called_once_with(False, 3)
        run_logger.log_orchestrator.assert_called_once()

    def test_failure_result_carries_failure_reason(self) -> None:
        """The WorkItemResult from _handle_failure carries failure_reason."""
        result = CopilotResult(
            work_item_id="task-reason", success=False,
            error="memory exhausted", attempt_count=1,
        )
        item = make_work_item(id="task-reason", title="Reason Task")

        with (
            patch(
                "pokepoke.orchestration.finalization.reconcile_completed_item",
                return_value=(False, {}),
            ),
            patch("pokepoke.orchestration.finalization.terminal_ui"),
            patch("pokepoke.beads.beads_management.fail_task"),
        ):
            wi_result, _ = _finalize_item_result(ResultContext(
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
            ))

        assert wi_result.failure_reason == "memory exhausted"

    def test_failure_with_unknown_error(self) -> None:
        """When error is None, failure_reason defaults to 'Unknown failure'."""
        result = CopilotResult(
            work_item_id="task-unknown", success=False,
            error=None, attempt_count=1,
        )
        item = make_work_item(id="task-unknown", title="Unknown Task")

        with (
            patch(
                "pokepoke.orchestration.finalization.reconcile_completed_item",
                return_value=(False, {}),
            ),
            patch("pokepoke.orchestration.finalization.terminal_ui"),
            patch("pokepoke.beads.beads_management.fail_task"),
        ):
            wi_result, _ = _finalize_item_result(ResultContext(
                result=result,
                item=item,
                worktree_path=Path("/fake/wt"),
                selected_model="test-model",
                start_time=0.0,
                request_count=0,
                accumulated_stats=AgentStats(),
                cleanup_agent_runs=0,
                gate_agent_runs=0,
                gate_success=False,
                run_logger=None,
                item_logger=None,
                base_agent_id="test-agent",
                run_beta_test=False,
            ))

        assert wi_result.failure_reason == "Unknown failure"


# ═══════════════════════════════════════════════════════════════════════════
# _store_discoveries
# ═══════════════════════════════════════════════════════════════════════════


class TestStoreDiscoveries:
    """Tests for _store_discoveries in finalization.py."""

    def test_skipped_when_memory_disabled(self) -> None:
        """No discovery logic runs when memory is disabled."""
        from pokepoke.orchestration.finalization import _store_discoveries
        item = make_work_item(id="task-disc", title="Disc Task")
        with patch("pokepoke.config.get_config") as mock_cfg:
            mock_cfg.return_value.mcp_server.memory_enabled = False
            _store_discoveries(item, Path("/wt"))

    def test_stores_discoveries_when_found(self) -> None:
        """Discoveries are stored when auto_discover finds them."""
        from pokepoke.orchestration.finalization import _store_discoveries
        item = make_work_item(id="task-disc2", title="Disc Task 2")
        with (
            patch("pokepoke.config.get_config") as mock_cfg,
            patch("pokepoke.models.memory_helpers.auto_discover_from_prompt", return_value=["d1"]),
            patch("pokepoke.models.memory_helpers.store_agent_discoveries") as mock_store,
            patch("pokepoke.models.sdk_helpers.build_prompt_from_work_item", return_value="prompt"),
        ):
            mock_cfg.return_value.mcp_server.memory_enabled = True
            _store_discoveries(item, Path("/wt"))
            mock_store.assert_called_once()

    def test_exception_in_discovery_is_swallowed(self) -> None:
        """Exceptions during discovery are caught and logged."""
        from pokepoke.orchestration.finalization import _store_discoveries
        item = make_work_item(id="task-disc3", title="Disc Task 3")
        with (
            patch("pokepoke.config.get_config") as mock_cfg,
            patch("pokepoke.models.memory_helpers.auto_discover_from_prompt", side_effect=ImportError("no module")),
            patch("pokepoke.models.sdk_helpers.build_prompt_from_work_item", return_value="prompt"),
        ):
            mock_cfg.return_value.mcp_server.memory_enabled = True
            # Should not raise
            _store_discoveries(item, Path("/wt"))


# ═══════════════════════════════════════════════════════════════════════════
# DefaultBeadsClient.fail_task protocol contract
# ═══════════════════════════════════════════════════════════════════════════


class TestDefaultBeadsClientFailTask:
    """Tests for DefaultBeadsClient.fail_task protocol method."""

    def test_delegates_to_beads_management(self) -> None:
        """DefaultBeadsClient.fail_task delegates to beads_management.fail_task."""
        from pokepoke.protocols import DefaultBeadsClient
        with (
            patch("pokepoke.beads.beads_management.add_comment", return_value=True),
            patch("pokepoke.beads.beads_item_stats_store.record_event"),
        ):
            client = DefaultBeadsClient()
            result = client.fail_task("PP-1", "test reason", agent_type="gate")
            assert result is True

    def test_passes_agent_type_through(self) -> None:
        """agent_type parameter is forwarded correctly."""
        from pokepoke.protocols import DefaultBeadsClient
        with (
            patch("pokepoke.beads.beads_management.add_comment", return_value=True),
            patch("pokepoke.beads.beads_item_stats_store.record_event") as mock_record,
        ):
            client = DefaultBeadsClient()
            client.fail_task("PP-2", "gate rejected", agent_type="gate")
            mock_record.assert_called_once_with("failed", "PP-2", "gate", path=None, repo_name="")
