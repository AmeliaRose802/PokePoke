"""Integration-style tests for workflow.py.

Exercises real code paths in workflow.py, mocking only external I/O
boundaries (copilot invocation, beads CLI, git operations, filesystem).
"""

import subprocess
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

from pokepoke.orchestration.finalization import ResultContext, _build_completion_record, _finalize_item_result
from pokepoke.orchestration.work_item_session import WorkItemSession
from pokepoke.orchestration.workflow import process_work_item
from pokepoke.orchestration.workflow_helpers import (
    _fail_result,
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
    GateAgentResult,
    ModelCompletionRecord,
)


def _item(id: str = "wf-1", desc: str | None = "desc") -> BeadsWorkItem:
    return BeadsWorkItem(id=id, title=f"Item {id}", status="ready",
                         priority=1, issue_type="task", description=desc)


def _branch_ok(branch: str = "task/wf-1") -> subprocess.CompletedProcess[str]:
    """Fake result for the pre-invocation branch guard."""
    return subprocess.CompletedProcess(
        args=["git", "branch", "--show-current"],
        returncode=0,
        stdout=branch,
        stderr="",
    )


# ── _fail_result ───────────────────────────────────────────────────

class TestFailResult:
    def test_defaults(self):
        r = _fail_result()
        assert r.success is False
        assert r.request_count == 0
        assert r.stats is None
        assert r.cleanup_agent_runs == 0
        assert r.gate_agent_runs == 0
        assert r.model_completion is None

    def test_with_all_params(self):
        stats = AgentStats(input_tokens=100)
        mc = ModelCompletionRecord(item_id="x", model="m", duration_seconds=1.0)
        r = _fail_result(request_count=3, stats=stats,
                         cleanup_agent_runs=2, gate_agent_runs=1,
                         model_completion=mc)
        assert r.request_count == 3
        assert r.stats.input_tokens == 100
        assert r.cleanup_agent_runs == 2
        assert r.gate_agent_runs == 1
        assert r.model_completion is mc


# ── _build_completion_record ───────────────────────────────────────

class TestBuildCompletionRecord:
    def test_basic(self):
        stats = AgentStats(input_tokens=500, output_tokens=200,
                           api_duration=1.5, lines_added=10, lines_removed=3)
        rec = _build_completion_record(
            item_id="x", model="gpt-4", duration=60.0, success=True,
            gate_passed=True, stats=stats, request_count=2,
        )
        assert rec.item_id == "x"
        assert rec.model == "gpt-4"
        assert rec.duration_seconds == 60.0
        assert rec.gate_passed is True
        assert rec.input_tokens == 500
        assert rec.output_tokens == 200
        assert rec.agent_turns == 2
        assert rec.retry_attempts == 1  # request_count - 1
        assert rec.api_duration == 1.5
        assert rec.lines_added == 10
        assert rec.lines_removed == 3

    def test_no_stats(self):
        rec = _build_completion_record(
            item_id="x", model="m", duration=1.0, success=False,
            gate_passed=None, stats=None, request_count=1,
        )
        assert rec.input_tokens == 0
        assert rec.output_tokens == 0
        assert rec.retry_attempts == 0
        assert rec.api_duration is None


# ── _log_failure ───────────────────────────────────────────────────

class TestLogFailure:
    def test_with_loggers(self):
        run_logger = MagicMock()
        item_logger = MagicMock()
        _log_failure(run_logger, item_logger, request_count=5)
        item_logger.log_summary.assert_called_once_with(False, 5)
        run_logger.log_orchestrator.assert_called_once()

    def test_without_loggers(self):
        _log_failure(None, None, 0)  # Should not raise


# ── setup_worktree ────────────────────────────────────────────────

class TestSetupWorktree:
    @patch("pokepoke.orchestration.workflow_helpers.create_worktree")
    def test_success(self, mock_create, tmp_path):
        mock_create.return_value = tmp_path / "worktree"
        result = setup_worktree(_item())
        assert result == tmp_path / "worktree"

    @patch("pokepoke.orchestration.workflow_helpers.create_worktree", side_effect=RuntimeError("git failed"))
    def test_failure_returns_none(self, mock_create):
        result = setup_worktree(_item())
        assert result is None

    @patch("pokepoke.orchestration.workflow_helpers.create_worktree", side_effect=RuntimeError("git failed"))
    def test_failure_logs_error(self, mock_create):
        run_logger = MagicMock()
        item_logger = MagicMock()
        result = setup_worktree(_item(), run_logger=run_logger, item_logger=item_logger)
        assert result is None
        run_logger.log_orchestrator.assert_called_once()
        item_logger.log_error.assert_called_once()


# ── run_cleanup_with_timeout ──────────────────────────────────────

class TestRunCleanupWithTimeout:
    @patch("pokepoke.orchestration.workflow_helpers.run_cleanup_loop", return_value=(True, 1))
    @patch("pokepoke.orchestration.workflow_helpers.has_uncommitted_changes")
    def test_cleanup_runs_once(self, mock_uncommitted, mock_cleanup):
        # First call: has changes; after cleanup: no changes
        mock_uncommitted.side_effect = [True, False]
        item = _item()
        result_obj = CopilotResult(work_item_id="wf-1", success=True, attempt_count=1)

        success, runs = run_cleanup_with_timeout(
            item, result_obj, Path("."), time.time(), 7200, 2.0, cwd="/fake",
        )
        assert success is True
        assert runs == 1

    @patch("pokepoke.orchestration.workflow_helpers.run_cleanup_loop", return_value=(True, 1))
    @patch("pokepoke.orchestration.workflow_helpers.has_uncommitted_changes", return_value=True)
    @patch("time.time")
    def test_cleanup_timeout(self, mock_time, mock_uncommitted, mock_cleanup):
        # Simulate timeout: time.time() returns value past timeout
        # Extra values needed because print() may trigger desktop_ui push_log
        # which also calls time.time() internally.
        mock_time.side_effect = [8000.0] + [8000.0] * 20  # past timeout_seconds (7200)
        item = _item()
        result_obj = CopilotResult(work_item_id="wf-1", success=True, attempt_count=1)

        success, runs = run_cleanup_with_timeout(
            item, result_obj, Path("."), 0.0, 7200, 2.0, cwd="/fake",
        )
        assert success is False
        assert runs == 0

    @patch("pokepoke.orchestration.workflow_helpers.has_uncommitted_changes", return_value=False)
    def test_no_changes_skips_cleanup(self, mock_uncommitted):
        item = _item()
        result_obj = CopilotResult(work_item_id="wf-1", success=True, attempt_count=1)

        success, runs = run_cleanup_with_timeout(
            item, result_obj, Path("."), time.time(), 7200, 2.0,
        )
        assert success is True
        assert runs == 0

    @patch("pokepoke.orchestration.workflow_helpers.run_cleanup_loop", return_value=(False, 1))
    @patch("pokepoke.orchestration.workflow_helpers.has_uncommitted_changes", return_value=True)
    def test_cleanup_failure(self, mock_uncommitted, mock_cleanup):
        item = _item()
        result_obj = CopilotResult(work_item_id="wf-1", success=True, attempt_count=1)

        _success, runs = run_cleanup_with_timeout(
            item, result_obj, Path("."), time.time(), 7200, 2.0,
        )
        # When cleanup fails, result.success is still True (the CopilotResult),
        # but cleanup_success returns True because result.success hasn't changed
        assert runs == 1


# ── process_work_item (integration) ────────────────────────────────

class TestProcessWorkItem:
    """Test process_work_item exercising real control flow."""

    @patch("pokepoke.orchestration.workflow.unregister_agent")
    @patch("pokepoke.orchestration.workflow.register_agent")
    @patch("pokepoke.orchestration.workflow.get_config")
    @patch("pokepoke.orchestration.workflow.select_model_for_item", return_value="gpt-4")
    @patch("pokepoke.orchestration.workflow.get_assignment_for_item", return_value=("assignment", "beads-item"))
    @patch("pokepoke.orchestration.workflow.terminal_ui")
    @patch("pokepoke.orchestration.workflow.terminal_ui.set_terminal_banner")
    @patch("pokepoke.orchestration.workflow.terminal_ui.format_work_item_banner", return_value="banner")
    @patch("pokepoke.orchestration.workflow.get_agent_name", return_value="test-agent")
    @patch("pokepoke.orchestration.workflow.assign_and_sync_item", return_value=False)
    def test_assign_failure(self, mock_assign, mock_agent_name,
                            mock_banner_fmt, mock_set_banner, mock_ui,
                            mock_assignment, mock_model, mock_config,
                            mock_register, mock_unregister):
        mock_config.return_value = MagicMock(
            command_timeout=300, max_parallel_agents=1,
            gate_agent_enabled=True, max_copilot_failure_retries=0, max_gate_rejections_per_item=3,
            ai_backend=MagicMock(provider="copilot"),
        )
        result = process_work_item(_item(), interactive=False)
        assert result.success is False
        assert result.request_count == 0

    @patch("pokepoke.orchestration.workflow.unregister_agent")
    @patch("pokepoke.orchestration.workflow.register_agent")
    @patch.object(WorkItemSession, "cleanup_on_failure")
    @patch("pokepoke.orchestration.workflow.cleanup_worktree")
    @patch("pokepoke.orchestration.workflow.get_config")
    @patch("pokepoke.orchestration.workflow.select_model_for_item", return_value="gpt-4")
    @patch("pokepoke.orchestration.workflow.get_assignment_for_item", return_value=("assignment", "beads-item"))
    @patch("pokepoke.orchestration.workflow.terminal_ui")
    @patch("pokepoke.orchestration.workflow.terminal_ui.set_terminal_banner")
    @patch("pokepoke.orchestration.workflow.terminal_ui.format_work_item_banner", return_value="banner")
    @patch("pokepoke.orchestration.workflow.get_agent_name", return_value="test-agent")
    @patch("pokepoke.orchestration.workflow.assign_and_sync_item", return_value=True)
    @patch("pokepoke.orchestration.workflow.setup_worktree", return_value=None)
    def test_worktree_failure(self, mock_setup, mock_assign, mock_agent_name,
                              mock_banner_fmt, mock_set_banner, mock_ui,
                              mock_assignment, mock_model, mock_config,
                              mock_cleanup, mock_session_cleanup,
                              mock_register, mock_unregister):
        mock_config.return_value = MagicMock(
            command_timeout=300, max_parallel_agents=1,
            gate_agent_enabled=True, max_copilot_failure_retries=0, max_gate_rejections_per_item=3,
            ai_backend=MagicMock(provider="copilot"),
        )
        # setup_worktree returns None -> signals worktree creation failed
        result = process_work_item(_item(), interactive=False)
        assert result.success is False

    @patch("pokepoke.git.git_helpers.run_git", return_value=_branch_ok())
    @patch("pokepoke.orchestration.workflow.unregister_agent")
    @patch("pokepoke.orchestration.workflow.register_agent")
    @patch("pokepoke.orchestration.workflow.cleanup_worktree")
    @patch("pokepoke.orchestration.workflow_helpers.finalize_work_item", return_value=True)
    @patch("pokepoke.orchestration.workflow_helpers.has_uncommitted_changes", return_value=False)
    @patch("pokepoke.git.git_operations.has_commits_ahead", return_value=1)
    @patch("pokepoke.orchestration.workflow.invoke_copilot")
    @patch("pokepoke.orchestration.workflow.build_prompt_from_work_item", return_value="prompt")
    @patch("pokepoke.orchestration.workflow.get_config")
    @patch("pokepoke.orchestration.workflow.select_model_for_item", return_value="gpt-4")
    @patch("pokepoke.orchestration.workflow.get_assignment_for_item", return_value=("assignment", "beads-item"))
    @patch("pokepoke.orchestration.workflow.terminal_ui")
    @patch("pokepoke.orchestration.workflow.terminal_ui.set_terminal_banner")
    @patch("pokepoke.orchestration.workflow.terminal_ui.format_work_item_banner", return_value="banner")
    @patch("pokepoke.orchestration.workflow.get_agent_name", return_value="test-agent")
    @patch("pokepoke.orchestration.workflow.assign_and_sync_item", return_value=True)
    @patch("pokepoke.orchestration.workflow.setup_worktree")
    @patch("pokepoke.orchestration.workflow.is_shutting_down", return_value=False)
    def test_successful_processing_no_gate(
        self, mock_shutdown, mock_setup, mock_assign, mock_agent_name,
        mock_banner_fmt, mock_set_banner, mock_ui, mock_assignment,
        mock_model, mock_config, mock_prompt, mock_copilot,
        mock_ahead, mock_uncommitted, mock_finalize, mock_cleanup,
        mock_register, mock_unregister, mock_run_git, tmp_path,
    ):
        mock_setup.return_value = tmp_path / "worktree"
        (tmp_path / "worktree").mkdir()
        mock_config.return_value = MagicMock(
            command_timeout=300, max_parallel_agents=1,
            gate_agent_enabled=False, max_copilot_failure_retries=0, max_gate_rejections_per_item=3,
            ai_backend=MagicMock(provider="copilot"),
        )
        mock_copilot.return_value = CopilotResult(
            work_item_id="wf-1", success=True, attempt_count=1,
            output="done", stats=AgentStats(input_tokens=100),
        )
        result = process_work_item(_item(), interactive=False)
        assert result.success is True
        assert result.request_count == 1
        mock_finalize.assert_called_once()

    @patch("pokepoke.git.git_helpers.run_git", return_value=_branch_ok())
    @patch("pokepoke.orchestration.workflow.unregister_agent")
    @patch("pokepoke.orchestration.workflow.register_agent")
    @patch.object(WorkItemSession, "cleanup_on_failure")
    @patch("pokepoke.orchestration.workflow.cleanup_worktree")
    @patch("pokepoke.orchestration.workflow_helpers.has_uncommitted_changes", return_value=False)
    @patch("pokepoke.git.git_operations.has_commits_ahead", return_value=0)
    @patch("pokepoke.orchestration.workflow.invoke_copilot")
    @patch("pokepoke.orchestration.workflow.build_prompt_from_work_item", return_value="prompt")
    @patch("pokepoke.orchestration.workflow.get_config")
    @patch("pokepoke.orchestration.workflow.select_model_for_item", return_value="gpt-4")
    @patch("pokepoke.orchestration.workflow.get_assignment_for_item", return_value=("assignment", "beads-item"))
    @patch("pokepoke.orchestration.workflow.terminal_ui")
    @patch("pokepoke.orchestration.workflow.terminal_ui.set_terminal_banner")
    @patch("pokepoke.orchestration.workflow.terminal_ui.format_work_item_banner", return_value="banner")
    @patch("pokepoke.orchestration.workflow.get_agent_name", return_value="test-agent")
    @patch("pokepoke.orchestration.workflow.assign_and_sync_item", return_value=True)
    @patch("pokepoke.orchestration.workflow.setup_worktree")
    @patch("pokepoke.orchestration.workflow.is_shutting_down", return_value=False)
    @patch("pokepoke.orchestration.workflow._maybe_decompose")
    def test_copilot_failure(
        self, mock_decompose, mock_shutdown, mock_setup, mock_assign, mock_agent_name,
        mock_banner_fmt, mock_set_banner, mock_ui, mock_assignment,
        mock_model, mock_config, mock_prompt, mock_copilot,
        mock_ahead, mock_uncommitted, mock_cleanup, mock_session_cleanup,
        mock_register, mock_unregister, mock_run_git, tmp_path,
    ):
        mock_setup.return_value = tmp_path / "worktree"
        (tmp_path / "worktree").mkdir()
        mock_config.return_value = MagicMock(
            command_timeout=300, max_parallel_agents=1,
            gate_agent_enabled=False, max_copilot_failure_retries=0, max_gate_rejections_per_item=3,
            ai_backend=MagicMock(provider="copilot"),
        )
        mock_copilot.return_value = CopilotResult(
            work_item_id="wf-1", success=False, attempt_count=1,
            error="timeout",
        )
        result = process_work_item(_item(), interactive=False)
        assert result.success is False
        assert result.request_count == 1
        mock_session_cleanup.assert_called()

    @patch("pokepoke.git.git_helpers.run_git", return_value=_branch_ok())
    @patch("pokepoke.orchestration.workflow.unregister_agent")
    @patch("pokepoke.orchestration.workflow.register_agent")
    @patch("pokepoke.orchestration.workflow.cleanup_worktree")
    @patch("pokepoke.orchestration.workflow_helpers.finalize_work_item", return_value=True)
    @patch("pokepoke.orchestration.workflow.add_comment")
    @patch("pokepoke.orchestration.workflow.run_gate_agent")
    @patch("pokepoke.orchestration.workflow_helpers.has_uncommitted_changes", return_value=False)
    @patch("pokepoke.git.git_operations.has_commits_ahead", return_value=1)
    @patch("pokepoke.orchestration.workflow.invoke_copilot")
    @patch("pokepoke.orchestration.workflow.build_prompt_from_work_item", return_value="prompt")
    @patch("pokepoke.orchestration.workflow.get_config")
    @patch("pokepoke.orchestration.workflow.select_model_for_item", return_value="gpt-4")
    @patch("pokepoke.orchestration.workflow.get_assignment_for_item", return_value=("assignment", "beads-item"))
    @patch("pokepoke.orchestration.workflow.terminal_ui")
    @patch("pokepoke.orchestration.workflow.terminal_ui.set_terminal_banner")
    @patch("pokepoke.orchestration.workflow.terminal_ui.format_work_item_banner", return_value="banner")
    @patch("pokepoke.orchestration.workflow.get_agent_name", return_value="test-agent")
    @patch("pokepoke.orchestration.workflow.assign_and_sync_item", return_value=True)
    @patch("pokepoke.orchestration.workflow.setup_worktree")
    @patch("pokepoke.orchestration.workflow.is_shutting_down", return_value=False)
    def test_gate_agent_pass(
        self, mock_shutdown, mock_setup, mock_assign, mock_agent_name,
        mock_banner_fmt, mock_set_banner, mock_ui, mock_assignment,
        mock_model, mock_config, mock_prompt, mock_copilot,
        mock_ahead, mock_uncommitted, mock_gate, mock_comment,
        mock_finalize, mock_cleanup,
        mock_register, mock_unregister, mock_run_git, tmp_path,
    ):
        mock_setup.return_value = tmp_path / "worktree"
        (tmp_path / "worktree").mkdir()
        mock_config.return_value = MagicMock(
            command_timeout=300, max_parallel_agents=1,
            gate_agent_enabled=True, max_copilot_failure_retries=0, max_gate_rejections_per_item=3,
            ai_backend=MagicMock(provider="copilot"),
        )
        mock_copilot.return_value = CopilotResult(
            work_item_id="wf-1", success=True, attempt_count=1,
        )
        mock_gate.return_value = GateAgentResult(success=True, reason="looks good")
        with patch("pokepoke.git.git_operations.build_handoff_context", return_value="ctx"):
            result = process_work_item(_item(), interactive=False)
        assert result.success is True
        assert result.gate_agent_runs == 1

    @patch("pokepoke.git.git_helpers.run_git", return_value=_branch_ok())
    @patch("pokepoke.orchestration.workflow.unregister_agent")
    @patch("pokepoke.orchestration.workflow.register_agent")
    @patch("pokepoke.orchestration.workflow.cleanup_worktree")
    @patch("pokepoke.orchestration.workflow_helpers.finalize_work_item", return_value=True)
    @patch("pokepoke.orchestration.workflow.add_comment")
    @patch("pokepoke.orchestration.workflow.run_gate_agent")
    @patch("pokepoke.orchestration.workflow_helpers.has_uncommitted_changes", return_value=False)
    @patch("pokepoke.git.git_operations.has_commits_ahead", return_value=1)
    @patch("pokepoke.orchestration.workflow.invoke_copilot")
    @patch("pokepoke.orchestration.workflow.build_prompt_from_work_item", return_value="prompt")
    @patch("pokepoke.orchestration.workflow.get_config")
    @patch("pokepoke.orchestration.workflow.select_model_for_item", return_value="gpt-4")
    @patch("pokepoke.orchestration.workflow.get_assignment_for_item", return_value=("assignment", "beads-item"))
    @patch("pokepoke.orchestration.workflow.terminal_ui")
    @patch("pokepoke.orchestration.workflow.terminal_ui.set_terminal_banner")
    @patch("pokepoke.orchestration.workflow.terminal_ui.format_work_item_banner", return_value="banner")
    @patch("pokepoke.orchestration.workflow.get_agent_name", return_value="test-agent")
    @patch("pokepoke.orchestration.workflow.assign_and_sync_item", return_value=True)
    @patch("pokepoke.orchestration.workflow.setup_worktree")
    @patch("pokepoke.orchestration.workflow.is_shutting_down")
    def test_gate_reject_then_pass(
        self, mock_shutdown, mock_setup, mock_assign, mock_agent_name,
        mock_banner_fmt, mock_set_banner, mock_ui, mock_assignment,
        mock_model, mock_config, mock_prompt, mock_copilot,
        mock_ahead, mock_uncommitted, mock_gate, mock_comment,
        mock_finalize, mock_cleanup,
        mock_register, mock_unregister, mock_run_git, tmp_path,
    ):
        mock_shutdown.return_value = False
        mock_setup.return_value = tmp_path / "worktree"
        (tmp_path / "worktree").mkdir()
        mock_config.return_value = MagicMock(
            command_timeout=300, max_parallel_agents=1,
            gate_agent_enabled=True, max_copilot_failure_retries=0, max_gate_rejections_per_item=3,
            ai_backend=MagicMock(provider="copilot"),
        )
        # First copilot call -> gate rejects; second copilot call -> gate passes
        mock_copilot.side_effect = [
            CopilotResult(work_item_id="wf-1", success=True, attempt_count=1),
            CopilotResult(work_item_id="wf-1", success=True, attempt_count=1),
        ]
        mock_gate.side_effect = [
            GateAgentResult(success=False, reason="needs fix"),
            GateAgentResult(success=True, reason="ok"),
        ]
        with patch("pokepoke.git.git_operations.build_handoff_context", return_value="ctx"):
            result = process_work_item(_item(), interactive=False)
        assert result.success is True
        assert result.gate_agent_runs == 2
        assert result.request_count == 2

    @patch("pokepoke.orchestration.workflow.unregister_agent")
    @patch("pokepoke.orchestration.workflow.register_agent")
    @patch("pokepoke.orchestration.workflow.cleanup_worktree")
    @patch("pokepoke.orchestration.workflow.get_config")
    @patch("pokepoke.orchestration.workflow.select_model_for_item", return_value="gpt-4")
    @patch("pokepoke.orchestration.workflow.get_assignment_for_item", return_value=("assignment", "beads-item"))
    @patch("pokepoke.orchestration.workflow.terminal_ui")
    @patch("pokepoke.orchestration.workflow.terminal_ui.set_terminal_banner")
    @patch("pokepoke.orchestration.workflow.terminal_ui.format_work_item_banner", return_value="banner")
    @patch("pokepoke.orchestration.workflow.get_agent_name", return_value="test-agent")
    @patch("pokepoke.orchestration.workflow.assign_and_sync_item", return_value=True)
    @patch("pokepoke.orchestration.workflow.setup_worktree")
    @patch("pokepoke.orchestration.workflow.is_shutting_down", return_value=True)
    def test_shutdown_before_copilot(
        self, mock_shutdown, mock_setup, mock_assign, mock_agent_name,
        mock_banner_fmt, mock_set_banner, mock_ui, mock_assignment,
        mock_model, mock_config, mock_cleanup,
        mock_register, mock_unregister, tmp_path,
    ):
        mock_setup.return_value = tmp_path / "worktree"
        (tmp_path / "worktree").mkdir()
        mock_config.return_value = MagicMock(
            command_timeout=300, max_parallel_agents=1,
            gate_agent_enabled=True, max_copilot_failure_retries=0, max_gate_rejections_per_item=3,
            ai_backend=MagicMock(provider="copilot"),
        )
        result = process_work_item(_item(), interactive=False)
        # Shutdown exits loop before copilot invocation -> failure
        assert result.success is False

    @patch("pokepoke.orchestration.workflow.unregister_agent")
    @patch("pokepoke.orchestration.workflow.register_agent")
    @patch("pokepoke.orchestration.workflow.cleanup_worktree")
    @patch("pokepoke.orchestration.workflow.get_config")
    @patch("pokepoke.orchestration.workflow.select_model_for_item", return_value="gpt-4")
    @patch("pokepoke.orchestration.workflow.get_assignment_for_item", return_value=("assignment", "beads-item"))
    @patch("pokepoke.orchestration.workflow.terminal_ui")
    @patch("pokepoke.orchestration.workflow.terminal_ui.set_terminal_banner")
    @patch("pokepoke.orchestration.workflow.terminal_ui.format_work_item_banner", return_value="banner")
    @patch("pokepoke.orchestration.workflow.get_agent_name", return_value="test-agent")
    @patch("pokepoke.orchestration.workflow.assign_and_sync_item", return_value=True)
    @patch("pokepoke.orchestration.workflow.create_worktree")
    @patch("builtins.input", return_value="n")
    def test_interactive_user_skips(
        self, mock_input, mock_create, mock_assign, mock_agent_name,
        mock_banner_fmt, mock_set_banner, mock_ui, mock_assignment,
        mock_model, mock_config, mock_cleanup,
        mock_register, mock_unregister, tmp_path,
    ):
        mock_create.return_value = tmp_path / "worktree"
        (tmp_path / "worktree").mkdir()
        mock_config.return_value = MagicMock(
            command_timeout=300, max_parallel_agents=1,
            gate_agent_enabled=True, max_copilot_failure_retries=0, max_gate_rejections_per_item=3,
            ai_backend=MagicMock(provider="copilot"),
        )
        result = process_work_item(_item(), interactive=True)
        assert result.success is False
        assert result.request_count == 0

    @patch("pokepoke.git.git_helpers.run_git", return_value=_branch_ok())
    @patch("pokepoke.orchestration.workflow.unregister_agent")
    @patch("pokepoke.orchestration.workflow.register_agent")
    @patch("pokepoke.orchestration.workflow.cleanup_worktree")
    @patch("pokepoke.orchestration.workflow_helpers.finalize_work_item", return_value=True)
    @patch("pokepoke.orchestration.workflow.add_comment")
    @patch("pokepoke.orchestration.workflow.run_gate_agent")
    @patch("pokepoke.orchestration.workflow_helpers.has_uncommitted_changes", return_value=False)
    @patch("pokepoke.git.git_operations.has_commits_ahead", return_value=1)
    @patch("pokepoke.orchestration.workflow.invoke_copilot")
    @patch("pokepoke.orchestration.workflow.build_prompt_from_work_item", return_value="prompt")
    @patch("pokepoke.orchestration.workflow.get_config")
    @patch("pokepoke.orchestration.workflow.select_model_for_item", return_value="gpt-4")
    @patch("pokepoke.orchestration.workflow.get_assignment_for_item", return_value=("assignment", "beads-item"))
    @patch("pokepoke.orchestration.workflow.terminal_ui")
    @patch("pokepoke.orchestration.workflow.terminal_ui.set_terminal_banner")
    @patch("pokepoke.orchestration.workflow.terminal_ui.format_work_item_banner", return_value="banner")
    @patch("pokepoke.orchestration.workflow.get_agent_name", return_value="test-agent")
    @patch("pokepoke.orchestration.workflow.assign_and_sync_item", return_value=True)
    @patch("pokepoke.orchestration.workflow.setup_worktree")
    @patch("pokepoke.orchestration.workflow.is_shutting_down")
    def test_retry_routes_output_to_retry_card(
        self, mock_shutdown, mock_setup, mock_assign, mock_agent_name,
        mock_banner_fmt, mock_set_banner, mock_ui, mock_assignment,
        mock_model, mock_config, mock_prompt, mock_copilot,
        mock_ahead, mock_uncommitted, mock_gate, mock_comment,
        mock_finalize, mock_cleanup,
        mock_register, mock_unregister, mock_run_git, tmp_path,
    ):
        """Retry iterations must wrap invoke_copilot in agent_output_for with the retry agent_id."""
        mock_shutdown.return_value = False
        mock_setup.return_value = tmp_path / "worktree"
        (tmp_path / "worktree").mkdir()
        mock_config.return_value = MagicMock(
            command_timeout=300, max_parallel_agents=1,
            gate_agent_enabled=True, max_copilot_failure_retries=0, max_gate_rejections_per_item=3,
            ai_backend=MagicMock(provider="copilot"),
        )
        mock_copilot.side_effect = [
            CopilotResult(work_item_id="wf-1", success=True, attempt_count=1),
            CopilotResult(work_item_id="wf-1", success=True, attempt_count=1),
        ]
        mock_gate.side_effect = [
            GateAgentResult(success=False, reason="needs fix"),
            GateAgentResult(success=True, reason="ok"),
        ]
        with patch("pokepoke.git.git_operations.build_handoff_context", return_value="ctx"):
            result = process_work_item(_item(), interactive=False)
        assert result.success is True

        # agent_output_for must be called for both v1 (base id) and v2 (retry id)
        output_for_calls = mock_ui.ui.agent_output_for.call_args_list
        agent_ids_routed = [c.args[0] for c in output_for_calls]
        # v1 uses base agent_id, v2 uses retry agent_id
        assert "wf-1" in agent_ids_routed, f"Expected base agent_id 'wf-1' in {agent_ids_routed}"
        assert any("retry" in aid for aid in agent_ids_routed), (
            f"Expected retry agent_id in {agent_ids_routed}"
        )


# ── _pre_loop_validate (unit) ──────────────────────────────────────

class TestPreLoopValidate:
    """Direct unit tests for _pre_loop_validate."""

    @patch("pokepoke.orchestration.workflow_helpers.terminal_ui")
    @patch("builtins.input", return_value="n")
    def test_interactive_user_declines(self, mock_input, mock_tui):
        result, was_assigned, _wt, _root, _cwd = _pre_loop_validate(
            _item(), interactive=True, worktree_lock_timeout=10,
            run_logger=None, item_logger=None,
        )
        assert result is not None
        assert result.success is False
        assert was_assigned is False
        mock_tui.ui.stop.assert_called_once()
        mock_tui.ui.start.assert_called_once()

    @patch("pokepoke.orchestration.workflow_helpers.setup_worktree")
    @patch("pokepoke.orchestration.workflow_helpers.assign_and_sync_item", return_value=False)
    @patch("pokepoke.orchestration.workflow_helpers.terminal_ui")
    def test_assign_failure(self, mock_tui, mock_assign, mock_setup):
        result, was_assigned, _wt, _root, _cwd = _pre_loop_validate(
            _item(), interactive=False, worktree_lock_timeout=10,
            run_logger=None, item_logger=None,
        )
        assert result is not None
        assert result.success is False
        assert was_assigned is False
        mock_setup.assert_not_called()

    @patch("pokepoke.orchestration.workflow_helpers.setup_worktree", return_value=None)
    @patch("pokepoke.orchestration.workflow_helpers.assign_and_sync_item", return_value=True)
    @patch("pokepoke.orchestration.workflow_helpers.terminal_ui")
    def test_worktree_setup_failure(self, mock_tui, mock_assign, mock_setup):
        result, was_assigned, _wt, _root, _cwd = _pre_loop_validate(
            _item(), interactive=False, worktree_lock_timeout=10,
            run_logger=None, item_logger=None,
        )
        assert result is not None
        assert result.success is False
        assert was_assigned is True


# ── _run_gate_check (unit) ─────────────────────────────────────────

class TestRunGateCheck:
    """Direct unit tests for _run_gate_check."""

    @patch("pokepoke.orchestration.workflow_helpers.terminal_ui")
    @patch("pokepoke.orchestration.workflow_helpers.run_gate_agent", return_value=GateAgentResult(success=True, reason="all good"))
    @patch("pokepoke.git.git_operations.build_handoff_context", return_value="ctx")
    def test_success_path(self, mock_ctx, mock_gate, mock_tui):
        success, reason, runs, crashed = _run_gate_check(
            _item(), worktree_cwd="/tmp/wt", selected_model="gpt-4",
            gate_agent_runs=0, base_agent_id="agent-1",
        )
        assert success is True
        assert reason == "all good"
        assert runs == 1
        assert crashed is False
        mock_tui.ui.push_agent_status.assert_called_once()
        call_kwargs = mock_tui.ui.push_agent_status.call_args
        assert call_kwargs[1]["status"] == "success"

    @patch("pokepoke.orchestration.workflow_helpers.terminal_ui")
    @patch("pokepoke.orchestration.workflow_helpers.run_gate_agent", side_effect=RuntimeError("boom"))
    @patch("pokepoke.git.git_operations.build_handoff_context", return_value="ctx")
    def test_exception_path(self, mock_ctx, mock_gate, mock_tui):
        import pytest
        with pytest.raises(RuntimeError, match="boom"):
            _run_gate_check(
                _item(), worktree_cwd="/tmp/wt", selected_model="gpt-4",
                gate_agent_runs=0, base_agent_id="agent-1",
            )
        mock_tui.ui.push_agent_status.assert_called_once()
        call_kwargs = mock_tui.ui.push_agent_status.call_args
        assert call_kwargs[1]["status"] == "failed"


# ── _maybe_retry_copilot (unit) ────────────────────────────────────

class TestMaybeRetryCopilot:
    """Direct unit tests for _maybe_retry_copilot."""

    def test_failure_count_exceeds_max_retries(self):
        result = CopilotResult(work_item_id="x", success=False, attempt_count=1)
        should_retry, feedback = _maybe_retry_copilot(
            result, failure_count=4, max_retries=3,
            run_logger=None, item_id="x",
        )
        assert should_retry is False
        assert feedback == ""

    def test_rate_limited(self):
        result = CopilotResult(
            work_item_id="x", success=False, attempt_count=1,
            is_rate_limited=True,
        )
        should_retry, feedback = _maybe_retry_copilot(
            result, failure_count=1, max_retries=5,
            run_logger=None, item_id="x",
        )
        assert should_retry is False
        assert feedback == ""


# ── run_cleanup_with_timeout (timeout path) ────────────────────────

class TestRunCleanupTimeout:
    """Test the timeout branch in run_cleanup_with_timeout."""

    @patch("pokepoke.orchestration.workflow_helpers.has_uncommitted_changes", return_value=True)
    @patch("pokepoke.orchestration.workflow_helpers.set_terminal_banner")
    @patch("pokepoke.orchestration.workflow_helpers.format_work_item_banner", return_value="banner")
    def test_timeout_during_cleanup(self, mock_banner, mock_set, mock_uncommitted):
        item = _item()
        result = CopilotResult(work_item_id="wf-1", success=True, attempt_count=1)
        # start_time far in the past so elapsed > timeout_seconds immediately
        start_time = time.time() - 9999
        success, runs = run_cleanup_with_timeout(
            item, result, repo_root=Path("."), start_time=start_time,
            timeout_seconds=1.0, timeout_hours=0.001, cwd="/tmp",
        )
        assert success is False
        assert runs == 0


# ── _finalize_item_result (unit) ───────────────────────────────────

class TestFinalizeItemResult:
    """Direct unit tests for _finalize_item_result."""

    @patch("pokepoke.orchestration.finalization.terminal_ui")
    @patch("pokepoke.orchestration.finalization.run_beta_tester")
    @patch("pokepoke.orchestration.finalization.finalize_work_item", return_value=True)
    @patch("pokepoke.orchestration.finalization.set_terminal_banner")
    @patch("pokepoke.orchestration.finalization.format_work_item_banner", return_value="banner")
    def test_beta_test_enabled(self, mock_banner, mock_set, mock_finalize,
                               mock_beta, mock_tui, tmp_path):
        beta_stats = AgentStats(input_tokens=50)
        mock_beta.return_value = beta_stats
        result = CopilotResult(work_item_id="wf-1", success=True, attempt_count=1)
        wir, success = _finalize_item_result(ResultContext(
            result=result,
            item=_item(),
            worktree_path=tmp_path,
            selected_model="gpt-4",
            start_time=time.time() - 10,
            request_count=1,
            accumulated_stats=AgentStats(input_tokens=100),
            cleanup_agent_runs=0,
            gate_agent_runs=0,
            gate_success=False,
            run_logger=None,
            item_logger=None,
            base_agent_id="agent-1",
            run_beta_test=True,
        ))
        assert success is True
        assert wir.success is True
        mock_beta.assert_called_once()
        # Beta stats should be accumulated
        assert wir.stats.input_tokens == 150

    @patch("pokepoke.orchestration.finalization.terminal_ui")
    @patch("pokepoke.orchestration.finalization.finalize_work_item", return_value=True)
    @patch("pokepoke.orchestration.finalization.set_terminal_banner")
    @patch("pokepoke.orchestration.finalization.format_work_item_banner", return_value="banner")
    def test_with_loggers(self, mock_banner, mock_set, mock_finalize,
                          mock_tui, tmp_path):
        run_logger = MagicMock()
        item_logger = MagicMock()
        result = CopilotResult(work_item_id="wf-1", success=True, attempt_count=1)
        _wir, success = _finalize_item_result(ResultContext(
            result=result,
            item=_item(),
            worktree_path=tmp_path,
            selected_model="gpt-4",
            start_time=time.time() - 10,
            request_count=2,
            accumulated_stats=AgentStats(),
            cleanup_agent_runs=0,
            gate_agent_runs=0,
            gate_success=False,
            run_logger=run_logger,
            item_logger=item_logger,
            base_agent_id="agent-1",
            run_beta_test=False,
        ))
        assert success is True
        item_logger.log_summary.assert_called_once_with(True, 2)
        run_logger.log_orchestrator.assert_called_once()

    # ── Failure path: reconciliation upgrades to SUCCESS ──────────

    @patch("pokepoke.orchestration.finalization.terminal_ui")
    @patch("pokepoke.orchestration.finalization.reconcile_completed_item")
    @patch("pokepoke.orchestration.finalization.set_terminal_banner")
    @patch("pokepoke.orchestration.finalization.format_work_item_banner", return_value="banner")
    def test_failure_reconciled_to_success(self, mock_banner, mock_set,
                                           mock_reconcile, mock_tui, tmp_path):
        """When session fails but reconciliation shows all evidence passed,
        _finalize_item_result should upgrade the outcome to SUCCESS."""
        mock_reconcile.return_value = (True, {
            "beads_closed": True,
            "commits_on_default": True,
            "worktree_cleaned": True,
        })
        result = CopilotResult(work_item_id="wf-1", success=False, attempt_count=1,
                               error="session failed")
        run_logger = MagicMock()
        item_logger = MagicMock()
        wir, success = _finalize_item_result(ResultContext(
            result=result,
            item=_item(),
            worktree_path=tmp_path,
            selected_model="gpt-4",
            start_time=time.time() - 10,
            request_count=1,
            accumulated_stats=AgentStats(input_tokens=100),
            cleanup_agent_runs=0,
            gate_agent_runs=0,
            gate_success=False,
            run_logger=run_logger,
            item_logger=item_logger,
            base_agent_id="agent-1",
            run_beta_test=False,
        ))
        assert success is True
        assert wir.success is True
        item_logger.log_summary.assert_called_once_with(True, 1)
        run_logger.log_orchestrator.assert_called_once()

    # ── Failure path: reconciliation says NOT reconciled ──────────

    @patch("pokepoke.orchestration.finalization.terminal_ui")
    @patch("pokepoke.orchestration.finalization.reconcile_completed_item")
    @patch("pokepoke.orchestration.finalization.set_terminal_banner")
    @patch("pokepoke.orchestration.finalization.format_work_item_banner", return_value="banner")
    def test_failure_not_reconciled(self, mock_banner, mock_set,
                                    mock_reconcile,
                                    mock_tui, tmp_path):
        """When session fails and reconciliation also says not reconciled,
        _finalize_item_result should return failure and preserve worktree."""
        mock_reconcile.return_value = (False, {
            "beads_closed": False,
            "commits_on_default": False,
            "worktree_cleaned": False,
        })
        result = CopilotResult(work_item_id="wf-1", success=False, attempt_count=1,
                               error="session failed")
        wir, success = _finalize_item_result(ResultContext(
            result=result,
            item=_item(),
            worktree_path=tmp_path,
            selected_model="gpt-4",
            start_time=time.time() - 10,
            request_count=1,
            accumulated_stats=AgentStats(),
            cleanup_agent_runs=0,
            gate_agent_runs=0,
            gate_success=False,
            run_logger=None,
            item_logger=None,
            base_agent_id="agent-1",
            run_beta_test=False,
        ))
        assert success is False
        assert wir.success is False

    # ── False-positive guard: partial evidence ≠ reconciled ──────

    @patch("pokepoke.orchestration.finalization.terminal_ui")
    @patch("pokepoke.orchestration.finalization.reconcile_completed_item")
    @patch("pokepoke.orchestration.finalization.set_terminal_banner")
    @patch("pokepoke.orchestration.finalization.format_work_item_banner", return_value="banner")
    def test_failure_partial_evidence_not_reconciled(self, mock_banner, mock_set,
                                                     mock_reconcile,
                                                     mock_tui, tmp_path):
        """Worktree cleaned + beads closed but NO merge commit should NOT reconcile.
        This guards against false positives."""
        mock_reconcile.return_value = (False, {
            "beads_closed": True,
            "commits_on_default": False,
            "worktree_cleaned": True,
        })
        result = CopilotResult(work_item_id="wf-1", success=False, attempt_count=1,
                               error="session failed")
        wir, success = _finalize_item_result(ResultContext(
            result=result,
            item=_item(),
            worktree_path=tmp_path,
            selected_model="gpt-4",
            start_time=time.time() - 10,
            request_count=1,
            accumulated_stats=AgentStats(),
            cleanup_agent_runs=0,
            gate_agent_runs=0,
            gate_success=False,
            run_logger=None,
            item_logger=None,
            base_agent_id="agent-1",
            run_beta_test=False,
        ))
        assert success is False
        assert wir.success is False
