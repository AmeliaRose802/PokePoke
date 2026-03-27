"""Tests for pokepoke.orchestration.workflow_helpers module."""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from pokepoke.orchestration.workflow_helpers import (
    _apply_gate_feedback,
    _build_completion_record,
    _extract_agent_stats,
    _fail_result,
    _finalize_item_result,
    _log_commit_status,
    _log_failure,
    _maybe_retry_copilot,
    _pre_loop_validate,
    _run_gate_check,
    run_cleanup_with_timeout,
    setup_worktree,
)
from pokepoke.types import (
    AgentStats,
    BeadsWorkItem,
    CopilotResult,
    ModelCompletionRecord,
)

# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def sample_item() -> BeadsWorkItem:
    return BeadsWorkItem(
        id="item-42",
        title="Fix the widget",
        status="in_progress",
        priority=1,
        issue_type="task",
        description="Something needs fixing",
    )


@pytest.fixture
def sample_stats() -> AgentStats:
    return AgentStats(
        input_tokens=100,
        output_tokens=50,
        api_duration=1.5,
        lines_added=10,
        lines_removed=3,
    )


@pytest.fixture
def sample_result() -> CopilotResult:
    return CopilotResult(
        work_item_id="item-42",
        success=True,
        output="some output",
    )


@pytest.fixture
def mock_run_logger() -> MagicMock:
    return MagicMock()


@pytest.fixture
def mock_item_logger() -> MagicMock:
    return MagicMock()


# ── _log_failure ────────────────────────────────────────────────────────────


class TestLogFailure:
    def test_logs_when_both_loggers_present(self, mock_run_logger, mock_item_logger):
        _log_failure(mock_run_logger, mock_item_logger, request_count=5)
        mock_item_logger.log_summary.assert_called_once_with(False, 5)
        mock_run_logger.log_orchestrator.assert_called_once()

    def test_no_op_when_loggers_are_none(self):
        _log_failure(None, None, request_count=0)

    def test_no_op_when_run_logger_is_none(self, mock_item_logger):
        _log_failure(None, mock_item_logger, request_count=1)
        mock_item_logger.log_summary.assert_not_called()

    def test_no_op_when_item_logger_is_none(self, mock_run_logger):
        _log_failure(mock_run_logger, None, request_count=1)
        mock_run_logger.log_orchestrator.assert_not_called()


# ── _fail_result ────────────────────────────────────────────────────────────


class TestFailResult:
    def test_defaults(self):
        result = _fail_result()
        assert result.success is False
        assert result.request_count == 0
        assert result.stats is None
        assert result.cleanup_agent_runs == 0
        assert result.gate_agent_runs == 0
        assert result.model_completion is None

    def test_custom_values(self, sample_stats):
        mc = ModelCompletionRecord(item_id="x", model="m", duration_seconds=1.0)
        result = _fail_result(
            request_count=3,
            stats=sample_stats,
            cleanup_agent_runs=2,
            gate_agent_runs=1,
            model_completion=mc,
        )
        assert result.success is False
        assert result.request_count == 3
        assert result.stats is sample_stats
        assert result.cleanup_agent_runs == 2
        assert result.gate_agent_runs == 1
        assert result.model_completion is mc


# ── _build_completion_record ────────────────────────────────────────────────


class TestBuildCompletionRecord:
    def test_with_stats(self, sample_stats):
        rec = _build_completion_record(
            item_id="item-1",
            model="test-model",
            duration=120.0,
            success=True,
            gate_passed=True,
            stats=sample_stats,
            request_count=5,
        )
        assert rec.item_id == "item-1"
        assert rec.model == "test-model"
        assert rec.duration_seconds == 120.0
        assert rec.gate_passed is True
        assert rec.input_tokens == 100
        assert rec.output_tokens == 50
        assert rec.agent_turns == 5
        assert rec.retry_attempts == 4
        assert rec.api_duration == 1.5
        assert rec.lines_added == 10
        assert rec.lines_removed == 3

    def test_without_stats(self):
        rec = _build_completion_record(
            item_id="item-2",
            model="m",
            duration=60.0,
            success=False,
            gate_passed=None,
            stats=None,
            request_count=1,
        )
        assert rec.input_tokens == 0
        assert rec.output_tokens == 0
        assert rec.retry_attempts == 0
        assert rec.api_duration is None
        assert rec.lines_added is None
        assert rec.lines_removed is None


# ── _extract_agent_stats ────────────────────────────────────────────────────


class TestExtractAgentStats:
    def test_returns_stats_from_result_directly(self, sample_stats):
        result = CopilotResult(work_item_id="x", success=True, stats=sample_stats)
        assert _extract_agent_stats(result) is sample_stats

    @patch("pokepoke.stats.stats.parse_agent_stats")
    def test_parses_from_output(self, mock_parse, sample_stats):
        mock_parse.return_value = sample_stats
        result = CopilotResult(work_item_id="x", success=True, output="raw output")
        assert _extract_agent_stats(result) is sample_stats
        mock_parse.assert_called_once_with("raw output")

    def test_returns_none_when_no_stats_or_output(self):
        result = CopilotResult(work_item_id="x", success=True)
        assert _extract_agent_stats(result) is None


# ── _apply_gate_feedback ────────────────────────────────────────────────────


class TestApplyGateFeedback:
    def test_appends_feedback(self):
        fb, iteration = _apply_gate_feedback("new feedback", ["old"], 1)
        assert fb == ["old", "new feedback"]
        assert iteration == 2

    def test_caps_at_three_entries(self):
        fb, iteration = _apply_gate_feedback("d", ["a", "b", "c"], 5)
        assert fb == ["b", "c", "d"]
        assert iteration == 6

    def test_does_not_mutate_input(self):
        original = ["a"]
        fb, _ = _apply_gate_feedback("b", original, 0)
        assert original == ["a"]
        assert fb == ["a", "b"]

    def test_empty_list(self):
        fb, iteration = _apply_gate_feedback("first", [], 0)
        assert fb == ["first"]
        assert iteration == 1


# ── _log_commit_status ──────────────────────────────────────────────────────


class TestLogCommitStatus:
    @patch("pokepoke.orchestration.workflow_helpers.has_uncommitted_changes", return_value=True)
    def test_returns_early_when_uncommitted(self, mock_has, capsys):
        _log_commit_status("/some/path")
        mock_has.assert_called_once_with(cwd="/some/path")
        assert capsys.readouterr().out == ""

    @patch("builtins.print")
    @patch("pokepoke.git.git_operations.has_commits_ahead", return_value=3)
    @patch("pokepoke.orchestration.workflow_helpers.has_uncommitted_changes", return_value=False)
    def test_prints_commits_ahead(self, mock_has, mock_ahead, mock_print):
        _log_commit_status("/wt")
        output = " ".join(str(a) for c in mock_print.call_args_list for a in c.args)
        assert "3 commits ahead" in output

    @patch("builtins.print")
    @patch("pokepoke.git.git_operations.has_commits_ahead", return_value=1)
    @patch("pokepoke.orchestration.workflow_helpers.has_uncommitted_changes", return_value=False)
    def test_singular_commit(self, mock_has, mock_ahead, mock_print):
        _log_commit_status("/wt")
        output = " ".join(str(a) for c in mock_print.call_args_list for a in c.args)
        assert "1 commit ahead" in output

    @patch("builtins.print")
    @patch("pokepoke.git.git_operations.has_commits_ahead", return_value=0)
    @patch("pokepoke.orchestration.workflow_helpers.has_uncommitted_changes", return_value=False)
    def test_no_changes(self, mock_has, mock_ahead, mock_print):
        _log_commit_status("/wt")
        output = " ".join(str(a) for c in mock_print.call_args_list for a in c.args)
        assert "No changes made" in output


# ── _maybe_retry_copilot ───────────────────────────────────────────────────


class TestMaybeRetryCopilot:
    def test_no_retry_when_over_max(self):
        result = CopilotResult(work_item_id="x", success=False, error="fail")
        should, feedback = _maybe_retry_copilot(result, failure_count=4, max_retries=3, run_logger=None, item_id="x")
        assert should is False
        assert feedback == ""

    def test_no_retry_when_rate_limited(self):
        result = CopilotResult(work_item_id="x", success=False, is_rate_limited=True)
        should, _feedback = _maybe_retry_copilot(result, failure_count=1, max_retries=3, run_logger=None, item_id="x")
        assert should is False

    @patch("builtins.print")
    def test_retries_with_error_feedback(self, mock_print):
        result = CopilotResult(work_item_id="x", success=False, error="some error")
        should, feedback = _maybe_retry_copilot(result, failure_count=1, max_retries=3, run_logger=None, item_id="x")
        assert should is True
        assert "some error" in feedback
        output = " ".join(str(a) for c in mock_print.call_args_list for a in c.args).lower()
        assert "retrying" in output

    def test_retries_with_default_feedback(self):
        result = CopilotResult(work_item_id="x", success=False)
        should, feedback = _maybe_retry_copilot(result, failure_count=2, max_retries=3, run_logger=None, item_id="x")
        assert should is True
        assert "did not complete" in feedback

    def test_logs_to_run_logger(self, mock_run_logger):
        result = CopilotResult(work_item_id="x", success=False, error="err")
        _maybe_retry_copilot(result, failure_count=1, max_retries=3, run_logger=mock_run_logger, item_id="item-1")
        mock_run_logger.log_orchestrator.assert_called_once()


# ── setup_worktree ─────────────────────────────────────────────────────────


class TestSetupWorktree:
    @patch("builtins.print")
    @patch("pokepoke.orchestration.workflow_helpers.create_worktree")
    def test_success(self, mock_create, mock_print, sample_item):
        mock_create.return_value = Path("/worktrees/item-42")
        result = setup_worktree(sample_item)
        assert result == Path("/worktrees/item-42")
        mock_create.assert_called_once_with("item-42", lock_timeout=300.0, repo_path=None)
        output = " ".join(str(a) for c in mock_print.call_args_list for a in c.args)
        assert "Creating worktree" in output

    @patch("builtins.print")
    @patch("pokepoke.orchestration.workflow_helpers.create_worktree", side_effect=RuntimeError("lock failed"))
    def test_failure_returns_none(self, mock_create, mock_print, sample_item):
        result = setup_worktree(sample_item)
        assert result is None
        output = " ".join(str(a) for c in mock_print.call_args_list for a in c.args)
        assert "Failed to create worktree" in output

    @patch("pokepoke.orchestration.workflow_helpers.create_worktree", side_effect=RuntimeError("boom"))
    def test_failure_logs_to_loggers(self, mock_create, sample_item, mock_run_logger, mock_item_logger):
        result = setup_worktree(
            sample_item, run_logger=mock_run_logger, item_logger=mock_item_logger,
        )
        assert result is None
        mock_run_logger.log_orchestrator.assert_called_once()
        mock_item_logger.log_error.assert_called_once()


# ── _pre_loop_validate ──────────────────────────────────────────────────────


class TestPreLoopValidate:
    @patch("pokepoke.orchestration.workflow_helpers.setup_worktree")
    @patch("pokepoke.orchestration.workflow_helpers.assign_and_sync_item", return_value=True)
    def test_non_interactive_success(self, mock_assign, mock_setup, sample_item):
        mock_setup.return_value = Path("/wt/item-42")
        early, assigned, wt_path, _root, wt_cwd = _pre_loop_validate(
            sample_item, interactive=False, worktree_lock_timeout=60.0,
            run_logger=None, item_logger=None,
        )
        assert early is None
        assert assigned is True
        assert wt_path == Path("/wt/item-42")
        assert wt_cwd == str(Path("/wt/item-42"))

    @patch("pokepoke.orchestration.workflow_helpers.assign_and_sync_item", return_value=False)
    def test_assignment_failure(self, mock_assign, sample_item, capsys):
        early, assigned, _wt_path, _, _ = _pre_loop_validate(
            sample_item, interactive=False, worktree_lock_timeout=60.0,
            run_logger=None, item_logger=None,
        )
        assert early is not None
        assert early.success is False
        assert assigned is False

    @patch("pokepoke.orchestration.workflow_helpers.setup_worktree", return_value=None)
    @patch("pokepoke.orchestration.workflow_helpers.assign_and_sync_item", return_value=True)
    def test_worktree_failure(self, mock_assign, mock_setup, sample_item, capsys):
        early, assigned, wt_path, _, _ = _pre_loop_validate(
            sample_item, interactive=False, worktree_lock_timeout=60.0,
            run_logger=None, item_logger=None,
        )
        assert early is not None
        assert early.success is False
        assert assigned is True
        assert wt_path is None

    @patch("pokepoke.orchestration.workflow_helpers.terminal_ui")
    @patch("pokepoke.orchestration.workflow_helpers.assign_and_sync_item", return_value=True)
    @patch("pokepoke.orchestration.workflow_helpers.setup_worktree")
    @patch("builtins.input", return_value="n")
    def test_interactive_decline(self, mock_input, mock_setup, mock_assign, mock_tui, sample_item):
        early, assigned, _, _, _ = _pre_loop_validate(
            sample_item, interactive=True, worktree_lock_timeout=60.0,
            run_logger=None, item_logger=None,
        )
        assert early is not None
        assert early.success is False
        assert assigned is False

    @patch("pokepoke.orchestration.workflow_helpers.terminal_ui")
    @patch("pokepoke.orchestration.workflow_helpers.assign_and_sync_item", return_value=True)
    @patch("pokepoke.orchestration.workflow_helpers.setup_worktree")
    @patch("builtins.input", return_value="")
    def test_interactive_accept_empty(self, mock_input, mock_setup, mock_assign, mock_tui, sample_item):
        mock_setup.return_value = Path("/wt/item-42")
        early, assigned, _wt_path, _, _ = _pre_loop_validate(
            sample_item, interactive=True, worktree_lock_timeout=60.0,
            run_logger=None, item_logger=None,
        )
        assert early is None
        assert assigned is True


# ── run_cleanup_with_timeout ─────────────────────────────────────────────────


class TestRunCleanupWithTimeout:
    @patch("pokepoke.orchestration.workflow_helpers.has_uncommitted_changes", return_value=False)
    def test_no_uncommitted_changes(self, mock_has, sample_item, sample_result):
        success, runs = run_cleanup_with_timeout(
            sample_item, sample_result, Path("/repo"), time.time(),
            timeout_seconds=3600, timeout_hours=1.0,
        )
        assert success is True
        assert runs == 0

    @patch("pokepoke.orchestration.workflow_helpers.run_cleanup_loop", return_value=(True, 1))
    @patch("pokepoke.orchestration.workflow_helpers.set_terminal_banner")
    @patch("pokepoke.orchestration.workflow_helpers.format_work_item_banner", return_value="banner")
    @patch("pokepoke.orchestration.workflow_helpers.has_uncommitted_changes", side_effect=[True, False])
    def test_cleanup_succeeds(self, mock_has, mock_fmt, mock_banner, mock_loop, sample_item, sample_result):
        success, runs = run_cleanup_with_timeout(
            sample_item, sample_result, Path("/repo"), time.time(),
            timeout_seconds=3600, timeout_hours=1.0,
        )
        assert success is True
        assert runs == 1

    @patch("pokepoke.orchestration.workflow_helpers.run_cleanup_loop", return_value=(False, 1))
    @patch("pokepoke.orchestration.workflow_helpers.set_terminal_banner")
    @patch("pokepoke.orchestration.workflow_helpers.format_work_item_banner", return_value="banner")
    @patch("pokepoke.orchestration.workflow_helpers.has_uncommitted_changes", return_value=True)
    def test_cleanup_fails_breaks_loop(self, mock_has, mock_fmt, mock_banner, mock_loop, sample_item, sample_result):
        success, runs = run_cleanup_with_timeout(
            sample_item, sample_result, Path("/repo"), time.time(),
            timeout_seconds=3600, timeout_hours=1.0,
        )
        assert success is True  # result.success is still True
        assert runs == 1

    @patch("builtins.print")
    @patch("pokepoke.orchestration.workflow_helpers.has_uncommitted_changes", return_value=True)
    def test_timeout(self, mock_has, mock_print, sample_item, sample_result):
        start = time.time() - 7200  # 2 hours ago
        success, runs = run_cleanup_with_timeout(
            sample_item, sample_result, Path("/repo"), start,
            timeout_seconds=3600, timeout_hours=1.0,
        )
        assert success is False
        assert runs == 0
        output = " ".join(str(a) for c in mock_print.call_args_list for a in c.args)
        assert "TIMEOUT" in output

    @patch("pokepoke.orchestration.workflow_helpers.has_uncommitted_changes", return_value=False)
    def test_failed_result_skips_loop(self, mock_has, sample_item):
        failed = CopilotResult(work_item_id="x", success=False)
        success, runs = run_cleanup_with_timeout(
            sample_item, failed, Path("/repo"), time.time(),
            timeout_seconds=3600, timeout_hours=1.0,
        )
        assert success is False
        assert runs == 0


# ── _run_gate_check ──────────────────────────────────────────────────────────


class TestRunGateCheck:
    @patch("pokepoke.orchestration.workflow_helpers.terminal_ui")
    @patch("pokepoke.orchestration.workflow_helpers.run_gate_agent")
    @patch("pokepoke.git.git_operations.build_handoff_context", return_value="ctx")
    def test_gate_success(self, mock_ctx, mock_gate, mock_tui, sample_item):
        mock_gate.return_value = (True, None, None, False)
        mock_tui.ui.agent_output_for.return_value.__enter__ = MagicMock()
        mock_tui.ui.agent_output_for.return_value.__exit__ = MagicMock(return_value=False)
        success, reason, runs, crashed = _run_gate_check(
            sample_item, "/wt", "model-a", gate_agent_runs=0, base_agent_id="agent-1",
        )
        assert success is True
        assert reason is None
        assert runs == 1
        assert crashed is False

    @patch("pokepoke.orchestration.workflow_helpers.terminal_ui")
    @patch("pokepoke.orchestration.workflow_helpers.run_gate_agent")
    @patch("pokepoke.git.git_operations.build_handoff_context", return_value="ctx")
    def test_gate_failure(self, mock_ctx, mock_gate, mock_tui, sample_item):
        mock_gate.return_value = (False, "tests failed", None, False)
        mock_tui.ui.agent_output_for.return_value.__enter__ = MagicMock()
        mock_tui.ui.agent_output_for.return_value.__exit__ = MagicMock(return_value=False)
        success, reason, runs, crashed = _run_gate_check(
            sample_item, "/wt", "model-a", gate_agent_runs=1, base_agent_id="agent-1",
        )
        assert success is False
        assert reason == "tests failed"
        assert runs == 2
        assert crashed is False

    @patch("pokepoke.orchestration.workflow_helpers.terminal_ui")
    @patch("pokepoke.orchestration.workflow_helpers.run_gate_agent")
    @patch("pokepoke.git.git_operations.build_handoff_context", return_value="ctx")
    def test_gate_infra_crash(self, mock_ctx, mock_gate, mock_tui, sample_item):
        """SDK crash returns crashed=True so callers can retry the gate."""
        mock_gate.return_value = (False, "Gate Agent execution failed: SDK exception", None, True)
        mock_tui.ui.agent_output_for.return_value.__enter__ = MagicMock()
        mock_tui.ui.agent_output_for.return_value.__exit__ = MagicMock(return_value=False)
        success, reason, runs, crashed = _run_gate_check(
            sample_item, "/wt", "model-a", gate_agent_runs=0, base_agent_id="agent-1",
        )
        assert success is False
        assert "SDK exception" in reason
        assert runs == 1
        assert crashed is True

    @patch("pokepoke.orchestration.workflow_helpers.terminal_ui")
    @patch("pokepoke.orchestration.workflow_helpers.run_gate_agent", side_effect=RuntimeError("crash"))
    @patch("pokepoke.git.git_operations.build_handoff_context", return_value="ctx")
    def test_gate_exception(self, mock_ctx, mock_gate, mock_tui, sample_item):
        mock_tui.ui.agent_output_for.return_value.__enter__ = MagicMock()
        mock_tui.ui.agent_output_for.return_value.__exit__ = MagicMock(return_value=False)
        with pytest.raises(RuntimeError, match="crash"):
            _run_gate_check(
                sample_item, "/wt", "model-a", gate_agent_runs=0, base_agent_id="agent-1",
            )


# ── _finalize_item_result ───────────────────────────────────────────────────


class TestFinalizeItemResult:
    @patch("pokepoke.orchestration.workflow_helpers.terminal_ui")
    @patch("pokepoke.orchestration.workflow_helpers.set_terminal_banner")
    @patch("pokepoke.orchestration.workflow_helpers.format_work_item_banner", return_value="banner")
    @patch("pokepoke.orchestration.workflow_helpers.finalize_work_item", return_value=True)
    def test_success_path(self, mock_fin, mock_fmt, mock_banner, mock_tui, sample_item, sample_stats):
        wr, ok = _finalize_item_result(
            result=CopilotResult(work_item_id="item-42", success=True),
            item=sample_item,
            worktree_path=Path("/wt"),
            selected_model="m",
            start_time=time.time() - 10,
            request_count=3,
            accumulated_stats=sample_stats,
            cleanup_agent_runs=1,
            gate_agent_runs=0,
            gate_success=False,
            run_logger=None,
            item_logger=None,
            base_agent_id="agent-1",
            run_beta_test=False,
        )
        assert wr.success is True
        assert ok is True
        assert wr.model_completion is not None

    @patch("pokepoke.orchestration.workflow_helpers.terminal_ui")
    @patch("pokepoke.orchestration.workflow_helpers.set_terminal_banner")
    @patch("pokepoke.orchestration.workflow_helpers.format_work_item_banner", return_value="banner")
    @patch("pokepoke.orchestration.workflow_helpers.finalize_work_item", return_value=False)
    def test_success_but_finalize_fails(self, mock_fin, mock_fmt, mock_banner, mock_tui, sample_item, sample_stats):
        wr, ok = _finalize_item_result(
            result=CopilotResult(work_item_id="item-42", success=True),
            item=sample_item,
            worktree_path=Path("/wt"),
            selected_model="m",
            start_time=time.time() - 10,
            request_count=1,
            accumulated_stats=sample_stats,
            cleanup_agent_runs=0,
            gate_agent_runs=0,
            gate_success=False,
            run_logger=None,
            item_logger=None,
            base_agent_id="agent-1",
            run_beta_test=False,
        )
        assert wr.success is False
        assert ok is False

    @patch("pokepoke.orchestration.workflow_helpers.terminal_ui")
    @patch("pokepoke.orchestration.workflow_helpers.set_terminal_banner")
    @patch("pokepoke.orchestration.workflow_helpers.format_work_item_banner", return_value="banner")
    @patch("pokepoke.orchestration.workflow_helpers.reconcile_completed_item", return_value=(False, {}))
    def test_failure_path_cleanup(self, mock_recon, mock_fmt, mock_banner, mock_tui, sample_item, sample_stats, capsys):
        """On failure, worktree is preserved (not cleaned up)."""
        wr, ok = _finalize_item_result(
            result=CopilotResult(work_item_id="item-42", success=False, error="something broke"),
            item=sample_item,
            worktree_path=Path("/wt"),
            selected_model="m",
            start_time=time.time() - 10,
            request_count=2,
            accumulated_stats=sample_stats,
            cleanup_agent_runs=0,
            gate_agent_runs=1,
            gate_success=False,
            run_logger=None,
            item_logger=None,
            base_agent_id="agent-1",
            run_beta_test=False,
        )
        assert wr.success is False
        assert ok is False

    @patch("pokepoke.orchestration.workflow_helpers.terminal_ui")
    @patch("pokepoke.orchestration.workflow_helpers.set_terminal_banner")
    @patch("pokepoke.orchestration.workflow_helpers.format_work_item_banner", return_value="banner")
    @patch("pokepoke.orchestration.workflow_helpers.reconcile_completed_item")
    def test_failure_reconciled_as_success(self, mock_recon, mock_fmt, mock_banner, mock_tui, sample_item, sample_stats):
        mock_recon.return_value = (True, {"beads_closed": True, "commits_on_default": True, "worktree_cleaned": True})
        wr, ok = _finalize_item_result(
            result=CopilotResult(work_item_id="item-42", success=False, error="oops"),
            item=sample_item,
            worktree_path=Path("/wt"),
            selected_model="m",
            start_time=time.time() - 10,
            request_count=2,
            accumulated_stats=sample_stats,
            cleanup_agent_runs=0,
            gate_agent_runs=1,
            gate_success=True,
            run_logger=None,
            item_logger=None,
            base_agent_id="agent-1",
            run_beta_test=False,
        )
        assert wr.success is True
        assert ok is True

    @patch("pokepoke.orchestration.workflow_helpers.terminal_ui")
    @patch("pokepoke.orchestration.workflow_helpers.set_terminal_banner")
    @patch("pokepoke.orchestration.workflow_helpers.format_work_item_banner", return_value="banner")
    @patch("pokepoke.orchestration.workflow_helpers.run_beta_tester")
    @patch("pokepoke.orchestration.workflow_helpers.finalize_work_item", return_value=True)
    def test_success_with_beta_test(self, mock_fin, mock_beta, mock_fmt, mock_banner, mock_tui, sample_item, sample_stats):
        beta_stats = AgentStats(input_tokens=10, output_tokens=5)
        mock_beta.return_value = beta_stats
        wr, ok = _finalize_item_result(
            result=CopilotResult(work_item_id="item-42", success=True),
            item=sample_item,
            worktree_path=Path("/wt"),
            selected_model="m",
            start_time=time.time() - 10,
            request_count=1,
            accumulated_stats=sample_stats,
            cleanup_agent_runs=0,
            gate_agent_runs=0,
            gate_success=False,
            run_logger=None,
            item_logger=None,
            base_agent_id="agent-1",
            run_beta_test=True,
        )
        assert wr.success is True
        assert ok is True
        mock_beta.assert_called_once()

    @patch("pokepoke.orchestration.workflow_helpers.terminal_ui")
    @patch("pokepoke.orchestration.workflow_helpers.set_terminal_banner")
    @patch("pokepoke.orchestration.workflow_helpers.format_work_item_banner", return_value="banner")
    @patch("pokepoke.orchestration.workflow_helpers.finalize_work_item", return_value=True)
    def test_success_with_loggers(self, mock_fin, mock_fmt, mock_banner, mock_tui, sample_item, sample_stats, mock_run_logger, mock_item_logger):
        wr, _ok = _finalize_item_result(
            result=CopilotResult(work_item_id="item-42", success=True),
            item=sample_item,
            worktree_path=Path("/wt"),
            selected_model="m",
            start_time=time.time() - 10,
            request_count=3,
            accumulated_stats=sample_stats,
            cleanup_agent_runs=0,
            gate_agent_runs=2,
            gate_success=True,
            run_logger=mock_run_logger,
            item_logger=mock_item_logger,
            base_agent_id="agent-1",
            run_beta_test=False,
        )
        assert wr.success is True
        mock_item_logger.log_summary.assert_called_once_with(True, 3)
        mock_run_logger.log_orchestrator.assert_called_once()
        assert wr.model_completion.gate_passed is True

    @patch("pokepoke.orchestration.workflow_helpers.terminal_ui")
    @patch("pokepoke.orchestration.workflow_helpers.set_terminal_banner")
    @patch("pokepoke.orchestration.workflow_helpers.format_work_item_banner", return_value="banner")
    @patch("pokepoke.orchestration.workflow_helpers.reconcile_completed_item", return_value=(False, {}))
    def test_failure_path_skips_cleanup_during_shutdown(
        self, mock_recon, mock_fmt, mock_banner, mock_tui, sample_item, sample_stats,
    ):
        """Worktree should be preserved on failure (always, not just shutdown)."""
        wr, ok = _finalize_item_result(
            result=CopilotResult(work_item_id="item-42", success=False, error="shutdown abort"),
            item=sample_item,
            worktree_path=Path("/wt"),
            selected_model="m",
            start_time=time.time() - 10,
            request_count=2,
            accumulated_stats=sample_stats,
            cleanup_agent_runs=0,
            gate_agent_runs=0,
            gate_success=False,
            run_logger=None,
            item_logger=None,
            base_agent_id="agent-1",
            run_beta_test=False,
        )
        assert wr.success is False
        assert ok is False
