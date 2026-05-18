"""Tests for finalization paths: gate-rejection, success, failure, reconciliation.

Verifies that when CopilotResult has success=True AND gate_rejected=True,
_finalize_item_result routes to _handle_gate_rejection (no merge, no reconcile,
no fail_task — item left open).

Also covers _handle_success, _handle_failure, _reconcile_as_success, and
_store_discoveries for coverage of the major finalization branches.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

from pokepoke.orchestration.finalization import (
    ResultContext,
    _finalize_item_result,
    _store_discoveries,
)
from pokepoke.types_agent import CopilotResult
from pokepoke.types_beads import BeadsWorkItem
from pokepoke.types_stats import AgentStats


def _item(**overrides: object) -> BeadsWorkItem:
    defaults: dict = dict(
        id="task-gr-1", title="Gate rejected test", description="",
        status="open", priority=1, issue_type="task",
    )
    defaults.update(overrides)
    return BeadsWorkItem(**defaults)


def _mock_loggers() -> tuple[MagicMock, MagicMock]:
    """Return (run_logger, item_logger) mocks with expected methods."""
    run_logger = MagicMock()
    item_logger = MagicMock()
    return run_logger, item_logger


def _ctx(
    *,
    gate_rejected: bool,
    success: bool,
    tmp_path: Path,
    run_logger: "MagicMock | None" = None,
    item_logger: "MagicMock | None" = None,
    run_beta_test: bool = False,
    gate_success: bool = False,
    gate_agent_runs: int = 2,
    error: str | None = None,
) -> ResultContext:
    result = CopilotResult(
        work_item_id="task-gr-1", success=success,
        gate_rejected=gate_rejected, attempt_count=3,
        error=error,
    )
    return ResultContext(
        result=result, item=_item(), worktree_path=tmp_path,
        selected_model="gpt-4", start_time=0.0, request_count=3,
        accumulated_stats=AgentStats(), cleanup_agent_runs=0,
        gate_agent_runs=gate_agent_runs, gate_success=gate_success,
        run_logger=run_logger, item_logger=item_logger,
        base_agent_id="agent-1", run_beta_test=run_beta_test,
    )


class TestGateRejectedDoesNotMerge:
    """gate_rejected=True must NOT call _handle_success or _handle_failure."""

    @patch("pokepoke.orchestration.finalization.terminal_ui")
    @patch("pokepoke.orchestration.finalization._handle_failure")
    @patch("pokepoke.orchestration.finalization._handle_success")
    @patch("pokepoke.orchestration.finalization.set_terminal_banner")
    @patch("pokepoke.orchestration.finalization.format_work_item_banner", return_value="b")
    def test_gate_rejected_skips_success_and_failure(
        self, _banner, _set, mock_success, mock_failure, _tui, tmp_path,
    ) -> None:
        ctx = _ctx(gate_rejected=True, success=True, tmp_path=tmp_path)
        _finalize_item_result(ctx)
        mock_success.assert_not_called()
        mock_failure.assert_not_called()


class TestGateRejectedDoesNotCallFailTask:
    """gate_rejected=True must NOT call fail_task or reconcile."""

    @patch("pokepoke.orchestration.finalization.terminal_ui")
    @patch("pokepoke.orchestration.finalization.reconcile_completed_item")
    @patch("pokepoke.beads.beads_management.fail_task")
    @patch("pokepoke.orchestration.finalization.set_terminal_banner")
    @patch("pokepoke.orchestration.finalization.format_work_item_banner", return_value="b")
    def test_gate_rejected_no_fail_task_or_reconcile(
        self, _banner, _set, mock_fail_task, mock_reconcile, _tui, tmp_path,
    ) -> None:
        ctx = _ctx(gate_rejected=True, success=True, tmp_path=tmp_path)
        _finalize_item_result(ctx)
        mock_fail_task.assert_not_called()
        mock_reconcile.assert_not_called()


class TestGateRejectedReturnsFailure:
    """gate_rejected path returns (WorkItemResult(success=False), False)."""

    @patch("pokepoke.orchestration.finalization.terminal_ui")
    @patch("pokepoke.orchestration.finalization.set_terminal_banner")
    @patch("pokepoke.orchestration.finalization.format_work_item_banner", return_value="b")
    def test_gate_rejected_result_values(
        self, _banner, _set, _tui, tmp_path,
    ) -> None:
        ctx = _ctx(gate_rejected=True, success=True, tmp_path=tmp_path)
        wi_result, finalized = _finalize_item_result(ctx)
        assert wi_result.success is False
        assert finalized is False
        assert wi_result.failure_reason is not None
        assert "gate" in wi_result.failure_reason.lower()


class TestNormalPathsUnchanged:
    """Verify success=False and success=True (no gate_rejected) still route correctly."""

    @patch("pokepoke.orchestration.finalization.terminal_ui")
    @patch("pokepoke.orchestration.finalization.finalize_work_item", return_value=True)
    @patch("pokepoke.orchestration.finalization._store_discoveries")
    @patch("pokepoke.orchestration.finalization.set_terminal_banner")
    @patch("pokepoke.orchestration.finalization.format_work_item_banner", return_value="b")
    def test_success_true_no_gate_rejected_calls_handle_success(
        self, _banner, _set, _disc, _finalize, _tui, tmp_path,
    ) -> None:
        ctx = _ctx(gate_rejected=False, success=True, tmp_path=tmp_path)
        wi_result, finalized = _finalize_item_result(ctx)
        assert wi_result.success is True
        assert finalized is True

    @patch("pokepoke.orchestration.finalization.terminal_ui")
    @patch("pokepoke.orchestration.finalization.reconcile_completed_item", return_value=(False, {}))
    @patch("pokepoke.beads.beads_management.fail_task")
    @patch("pokepoke.orchestration.finalization._log_failure")
    @patch("pokepoke.orchestration.finalization.set_terminal_banner")
    @patch("pokepoke.orchestration.finalization.format_work_item_banner", return_value="b")
    def test_success_false_calls_handle_failure(
        self, _banner, _set, _log, mock_fail_task, _reconcile, _tui, tmp_path,
    ) -> None:
        ctx = _ctx(gate_rejected=False, success=False, tmp_path=tmp_path)
        wi_result, finalized = _finalize_item_result(ctx)
        assert wi_result.success is False
        assert finalized is False
        mock_fail_task.assert_called_once()


# ---------- gate_rejected with item_logger (line 84) ----------


class TestGateRejectedWithItemLogger:
    """Cover the item_logger.log branch inside _handle_gate_rejection."""

    @patch("pokepoke.orchestration.finalization.terminal_ui")
    @patch("pokepoke.orchestration.finalization.set_terminal_banner")
    @patch("pokepoke.orchestration.finalization.format_work_item_banner", return_value="b")
    def test_gate_rejected_logs_to_item_logger(
        self, _banner, _set, _tui, tmp_path,
    ) -> None:
        _, item_logger = _mock_loggers()
        ctx = _ctx(gate_rejected=True, success=True, tmp_path=tmp_path, item_logger=item_logger)
        _finalize_item_result(ctx)
        item_logger.log.assert_called_once()
        assert "gate" in item_logger.log.call_args[0][0].lower()


# ---------- _handle_success paths (lines 103, 116, 118-122, 124-125) ----------


class TestHandleSuccessWithLoggers:
    """Cover _handle_success with loggers, beta test, and finalize failure."""

    @patch("pokepoke.orchestration.finalization.terminal_ui")
    @patch("pokepoke.orchestration.finalization.finalize_work_item", return_value=True)
    @patch("pokepoke.orchestration.finalization._store_discoveries")
    @patch("pokepoke.orchestration.finalization.set_terminal_banner")
    @patch("pokepoke.orchestration.finalization.format_work_item_banner", return_value="b")
    def test_success_with_both_loggers(
        self, _banner, _set, _disc, _finalize, _tui, tmp_path,
    ) -> None:
        """Covers lines 103, 124-125 (item_logger.log + log_summary + run_logger)."""
        run_logger, item_logger = _mock_loggers()
        ctx = _ctx(
            gate_rejected=False, success=True, tmp_path=tmp_path,
            run_logger=run_logger, item_logger=item_logger,
        )
        wi_result, finalized = _finalize_item_result(ctx)
        assert wi_result.success is True
        assert finalized is True
        item_logger.log.assert_called()
        item_logger.log_summary.assert_called_once_with(True, 3)
        run_logger.log_orchestrator.assert_called_once()

    @patch("pokepoke.orchestration.finalization.terminal_ui")
    @patch("pokepoke.orchestration.finalization.finalize_work_item", return_value=False)
    @patch("pokepoke.orchestration.finalization.set_terminal_banner")
    @patch("pokepoke.orchestration.finalization.format_work_item_banner", return_value="b")
    def test_success_finalize_fails_with_item_logger(
        self, _banner, _set, _finalize, _tui, tmp_path,
    ) -> None:
        """Covers line 116 (item_logger.log_error on finalize failure)."""
        _, item_logger = _mock_loggers()
        ctx = _ctx(
            gate_rejected=False, success=True, tmp_path=tmp_path,
            item_logger=item_logger, gate_success=True,
        )
        wi_result, finalized = _finalize_item_result(ctx)
        assert wi_result.success is False
        assert finalized is False
        item_logger.log_error.assert_called_once()
        assert wi_result.failure_stage == "merge"
        assert wi_result.failure_reason is not None

    @patch("pokepoke.orchestration.finalization.terminal_ui")
    @patch("pokepoke.orchestration.finalization.finalize_work_item", return_value=True)
    @patch("pokepoke.orchestration.finalization._store_discoveries")
    @patch("pokepoke.orchestration.finalization.run_beta_tester", return_value=AgentStats(input_tokens=10))
    @patch("pokepoke.orchestration.finalization.set_terminal_banner")
    @patch("pokepoke.orchestration.finalization.format_work_item_banner", return_value="b")
    def test_success_with_beta_test(
        self, _banner, _set, _beta, _disc, _finalize, _tui, tmp_path,
    ) -> None:
        """Covers lines 118-122 (beta test execution and stats accumulation)."""
        ctx = _ctx(
            gate_rejected=False, success=True, tmp_path=tmp_path,
            run_beta_test=True,
        )
        wi_result, finalized = _finalize_item_result(ctx)
        assert wi_result.success is True
        assert finalized is True
        _beta.assert_called_once()


# ---------- _handle_failure paths (lines 151, 161, 167, 174, 193-212) ----------


class TestHandleFailureWithItemLogger:
    """Cover _handle_failure with item_logger set."""

    @patch("pokepoke.orchestration.finalization.terminal_ui")
    @patch("pokepoke.orchestration.finalization.reconcile_completed_item", return_value=(False, {}))
    @patch("pokepoke.beads.beads_management.fail_task")
    @patch("pokepoke.orchestration.finalization._log_failure")
    @patch("pokepoke.orchestration.finalization.set_terminal_banner")
    @patch("pokepoke.orchestration.finalization.format_work_item_banner", return_value="b")
    def test_failure_with_item_logger_logs_all_phases(
        self, _banner, _set, _log, _fail_task, _reconcile, _tui, tmp_path,
    ) -> None:
        """Covers lines 151, 167, 174 (item_logger calls in failure path)."""
        _, item_logger = _mock_loggers()
        ctx = _ctx(
            gate_rejected=False, success=False, tmp_path=tmp_path,
            item_logger=item_logger, error="agent crashed",
        )
        wi_result, finalized = _finalize_item_result(ctx)
        assert wi_result.success is False
        assert finalized is False
        # Line 151: reconciliation announcement
        # Line 167: failure error log
        # Line 174: preserving worktree log
        assert item_logger.log.call_count >= 2
        item_logger.log_error.assert_called_once()
        _fail_task.assert_called_once_with("task-gr-1", "agent crashed")


class TestHandleFailureReconciled:
    """Cover reconcile=True → _reconcile_as_success (lines 161, 193-212)."""

    @patch("pokepoke.orchestration.finalization.terminal_ui")
    @patch(
        "pokepoke.orchestration.finalization.reconcile_completed_item",
        return_value=(True, {"beads_closed": True, "commits_on_default": True,
                             "commits_on_worktree_branch": False, "worktree_cleaned": False}),
    )
    @patch("pokepoke.orchestration.finalization.set_terminal_banner")
    @patch("pokepoke.orchestration.finalization.format_work_item_banner", return_value="b")
    def test_failure_reconciled_returns_success(
        self, _banner, _set, _reconcile, _tui, tmp_path,
    ) -> None:
        """Covers lines 161, 193-212 (_reconcile_as_success body)."""
        ctx = _ctx(gate_rejected=False, success=False, tmp_path=tmp_path)
        wi_result, finalized = _finalize_item_result(ctx)
        assert wi_result.success is True
        assert finalized is True
        assert wi_result.model_completion is not None
        assert wi_result.model_completion.item_id == "task-gr-1"

    @patch("pokepoke.orchestration.finalization.terminal_ui")
    @patch(
        "pokepoke.orchestration.finalization.reconcile_completed_item",
        return_value=(True, {"beads_closed": True, "commits_on_default": False,
                             "commits_on_worktree_branch": True, "worktree_cleaned": False}),
    )
    @patch("pokepoke.orchestration.finalization.set_terminal_banner")
    @patch("pokepoke.orchestration.finalization.format_work_item_banner", return_value="b")
    def test_failure_reconciled_with_loggers(
        self, _banner, _set, _reconcile, _tui, tmp_path,
    ) -> None:
        """Covers _reconcile_as_success logger branches."""
        run_logger, item_logger = _mock_loggers()
        ctx = _ctx(
            gate_rejected=False, success=False, tmp_path=tmp_path,
            run_logger=run_logger, item_logger=item_logger,
        )
        wi_result, finalized = _finalize_item_result(ctx)
        assert wi_result.success is True
        assert finalized is True
        item_logger.log.assert_called()
        item_logger.log_summary.assert_called_once_with(True, 3)
        run_logger.log_orchestrator.assert_called_once()


# ---------- _store_discoveries (lines 225-240) ----------


class TestStoreDiscoveries:
    """Cover _store_discoveries function."""

    @patch("pokepoke.config.get_config")
    def test_store_discoveries_disabled(self, mock_config, tmp_path) -> None:
        """When memory_enabled=False, returns early."""
        mock_config.return_value.mcp_server.memory_enabled = False
        _store_discoveries(_item(), tmp_path)
        # No exception; early return before imports

    @patch("pokepoke.config.get_config")
    @patch("pokepoke.models.memory_helpers.store_agent_discoveries")
    @patch("pokepoke.models.memory_helpers.auto_discover_from_prompt", return_value=["disc1"])
    @patch("pokepoke.models.sdk_helpers.build_prompt_from_work_item", return_value="prompt")
    def test_store_discoveries_enabled_with_results(
        self, _build, _discover, _store, mock_config, tmp_path,
    ) -> None:
        """Covers lines 225-240 (full discovery storage path)."""
        mock_config.return_value.mcp_server.memory_enabled = True
        _store_discoveries(_item(), tmp_path)
        _build.assert_called_once()
        _discover.assert_called_once()
        _store.assert_called_once()

    @patch("pokepoke.config.get_config")
    @patch("pokepoke.models.memory_helpers.store_agent_discoveries")
    @patch("pokepoke.models.memory_helpers.auto_discover_from_prompt", return_value=[])
    @patch("pokepoke.models.sdk_helpers.build_prompt_from_work_item", return_value="prompt")
    def test_store_discoveries_no_results_skips_store(
        self, _build, _discover, _store, mock_config, tmp_path,
    ) -> None:
        """When no discoveries found, store is not called."""
        mock_config.return_value.mcp_server.memory_enabled = True
        _store_discoveries(_item(), tmp_path)
        _store.assert_not_called()

    @patch("pokepoke.config.get_config")
    @patch("pokepoke.models.memory_helpers.auto_discover_from_prompt", side_effect=RuntimeError("boom"))
    @patch("pokepoke.models.sdk_helpers.build_prompt_from_work_item", return_value="prompt")
    def test_store_discoveries_exception_is_swallowed(
        self, _build, _discover, mock_config, tmp_path,
    ) -> None:
        """Exceptions in discovery don't propagate."""
        mock_config.return_value.mcp_server.memory_enabled = True
        _store_discoveries(_item(), tmp_path)  # no exception raised
