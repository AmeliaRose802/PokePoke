"""Comprehensive tests for workflow.py targeting 80%+ line coverage.

Exercises process_work_item and setup_worktree through multiple scenarios,
mocking ALL external dependencies to isolate workflow logic.
"""

from contextlib import nullcontext
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from pokepoke.orchestration.workflow import process_work_item
from pokepoke.orchestration.workflow_helpers import setup_worktree
from pokepoke.types import (
    AgentStats,
    BeadsWorkItem,
    CopilotResult,
    GateAgentResult,
    WorkItemResult,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _item(id: str = "wf-cov-1", desc: str = "test desc") -> BeadsWorkItem:
    return BeadsWorkItem(
        id=id, title=f"Item {id}", status="ready",
        priority=1, issue_type="task", description=desc,
    )


def _ok_copilot(item_id: str = "wf-cov-1", **kw) -> CopilotResult:
    defaults = dict(work_item_id=item_id, success=True, attempt_count=1)
    defaults.update(kw)
    return CopilotResult(**defaults)


def _fail_copilot(item_id: str = "wf-cov-1", **kw) -> CopilotResult:
    defaults = dict(work_item_id=item_id, success=False, error="copilot failed", attempt_count=1)
    defaults.update(kw)
    return CopilotResult(**defaults)


def _timeout_copilot(item_id: str = "wf-cov-1", **kw) -> CopilotResult:
    defaults = dict(
        work_item_id=item_id, success=False,
        error="timeout exceeded", attempt_count=1,
        session_id="sess-timeout-1", last_output_summary="partial output",
    )
    defaults.update(kw)
    return CopilotResult(**defaults)


# ---------------------------------------------------------------------------
# Autouse fixture – mock every external dependency of workflow.py
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _mock_workflow_deps(monkeypatch):
    """Mock all external dependencies for workflow tests."""
    mock_cfg = MagicMock()
    mock_cfg.max_parallel_agents = 1
    mock_cfg.gate_agent_enabled = False
    mock_cfg.command_timeout = 120
    mock_cfg.max_copilot_failure_retries = 0
    mock_cfg.max_gate_rejections_per_item = 3
    mock_cfg.ai_backend.provider = "copilot-cli"

    monkeypatch.setattr("pokepoke.orchestration.workflow.get_config", lambda: mock_cfg)
    monkeypatch.setattr("pokepoke.orchestration.workflow.terminal_ui", MagicMock())
    monkeypatch.setattr("pokepoke.orchestration.workflow.register_agent", lambda: None)
    monkeypatch.setattr("pokepoke.orchestration.workflow.unregister_agent", lambda: None)
    monkeypatch.setattr("pokepoke.orchestration.workflow.is_shutting_down", lambda: False)
    monkeypatch.setattr("pokepoke.orchestration.workflow.set_current_work_item_id", lambda x: None)
    monkeypatch.setattr("pokepoke.orchestration.workflow.set_current_repo_name", lambda x: None)
    monkeypatch.setattr("pokepoke.orchestration.workflow.get_agent_name", lambda default="agent": "test-agent")
    monkeypatch.setattr("pokepoke.orchestration.workflow.select_model_for_item", lambda item: "test-model")
    monkeypatch.setattr("pokepoke.orchestration.workflow.get_assignment_for_item", lambda item: ("test-model", "beads-item"))
    monkeypatch.setattr("pokepoke.orchestration.workflow.build_prompt_from_work_item", lambda *a, **kw: "test prompt")
    monkeypatch.setattr("pokepoke.orchestration.workflow.build_resume_prompt", lambda *a, **kw: "resume prompt")
    monkeypatch.setattr("pokepoke.orchestration.workflow.assign_and_sync_item", lambda *a, **kw: True)
    monkeypatch.setattr("pokepoke.orchestration.workflow.add_comment", lambda *a, **kw: True)
    monkeypatch.setattr("pokepoke.orchestration.workflow.cleanup_worktree", lambda *a, **kw: None)

    # Lazy imports mocked at source module
    monkeypatch.setattr("pokepoke.beads.beads.increment_total_attempts", lambda *a: True)
    monkeypatch.setattr("pokepoke.beads.reconciliation.is_beads_item_closed", lambda *a: False)
    monkeypatch.setattr("pokepoke.git.git_operations.build_handoff_context", lambda **kw: "handoff ctx")
    monkeypatch.setattr("pokepoke.stats.metrics_context.agent_type_context", lambda *a: nullcontext())

    # Mock WorkItemSession to avoid real file operations
    mock_session = MagicMock()
    monkeypatch.setattr("pokepoke.orchestration.workflow.WorkItemSession", lambda **kw: mock_session)

    return mock_cfg


# ---------------------------------------------------------------------------
# setup_worktree tests
# ---------------------------------------------------------------------------

class TestSetupWorktree:
    def test_success_returns_path(self):
        wt = Path("/tmp/worktree")
        with patch("pokepoke.orchestration.workflow_helpers.create_worktree", return_value=wt):
            result = setup_worktree(_item())
        assert result == wt

    def test_failure_returns_none(self):
        with patch("pokepoke.orchestration.workflow_helpers.create_worktree", side_effect=Exception("git error")):
            result = setup_worktree(_item())
        assert result is None

    def test_failure_logs_to_run_logger(self):
        rl = MagicMock()
        il = MagicMock()
        with patch("pokepoke.orchestration.workflow_helpers.create_worktree", side_effect=RuntimeError("lock")):
            result = setup_worktree(_item(), run_logger=rl, item_logger=il)
        assert result is None
        rl.log_orchestrator.assert_called_once()
        il.log_error.assert_called_once()

    def test_custom_lock_timeout_forwarded(self):
        with patch("pokepoke.orchestration.workflow_helpers.create_worktree", return_value=Path("/w")) as mock_cw:
            setup_worktree(_item(), lock_timeout=999.0)
        mock_cw.assert_called_once_with(_item().id, lock_timeout=999.0, repo_path=None)

    def test_repo_path_forwarded(self):
        with patch("pokepoke.orchestration.workflow_helpers.create_worktree", return_value=Path("/w")) as mock_cw:
            setup_worktree(_item(), repo_path="/custom/repo")
        mock_cw.assert_called_once_with(_item().id, lock_timeout=300.0, repo_path="/custom/repo")


# ---------------------------------------------------------------------------
# process_work_item tests
# ---------------------------------------------------------------------------

class TestProcessWorkItemClaimFailure:
    """assign_and_sync_item returns False → immediate fail."""

    def test_claim_failure_returns_failed_result(self, monkeypatch):
        monkeypatch.setattr("pokepoke.orchestration.workflow.assign_and_sync_item", lambda *a, **kw: False)
        result = process_work_item(_item(), interactive=False)
        assert result.success is False

    def test_claim_failure_skips_worktree(self, monkeypatch):
        monkeypatch.setattr("pokepoke.orchestration.workflow.assign_and_sync_item", lambda *a, **kw: False)
        with patch("pokepoke.orchestration.workflow.setup_worktree") as mock_sw:
            result = process_work_item(_item(), interactive=False)
        mock_sw.assert_not_called()
        assert result.success is False


class TestProcessWorkItemWorktreeFailure:
    """setup_worktree returns None → immediate fail."""

    def test_worktree_failure(self, monkeypatch):
        def _fail(*a, **kw):
            raise Exception("git fail")
        monkeypatch.setattr("pokepoke.orchestration.workflow_helpers.create_worktree", _fail)
        result = process_work_item(_item(), interactive=False)
        assert result.success is False


class TestProcessWorkItemInteractiveSkip:
    """User enters 'n' in interactive mode → skip."""

    def test_user_skips(self, monkeypatch):
        monkeypatch.setattr("builtins.input", lambda _: "n")
        result = process_work_item(_item(), interactive=True)
        assert result.success is False


class TestProcessWorkItemCopilotSuccessGateDisabled:
    """Copilot succeeds, gate agent disabled → success path."""

    def test_success_gate_disabled(self, monkeypatch):
        monkeypatch.setattr("pokepoke.orchestration.workflow_helpers.create_worktree", lambda *a, **kw: Path("/tmp/wt"))
        monkeypatch.setattr("pokepoke.orchestration.workflow.invoke_copilot", lambda *a, **kw: _ok_copilot())
        monkeypatch.setattr("pokepoke.orchestration.workflow._log_commit_status", lambda *a: None)
        monkeypatch.setattr("pokepoke.orchestration.workflow.run_cleanup_with_timeout", lambda *a, **kw: (True, 1))
        monkeypatch.setattr(
            "pokepoke.orchestration.workflow._finalize_item_result",
            lambda *a, **kw: (WorkItemResult(success=True, request_count=1), True),
        )
        monkeypatch.setattr("pokepoke.orchestration.workflow._extract_agent_stats", lambda r: None)

        result = process_work_item(_item(), interactive=False)
        assert result.success is True

    def test_success_with_stats_accumulation(self, monkeypatch):
        """Verify stats from copilot result are accumulated."""
        stats = AgentStats(input_tokens=50, output_tokens=25)
        monkeypatch.setattr("pokepoke.orchestration.workflow_helpers.create_worktree", lambda *a, **kw: Path("/tmp/wt"))
        monkeypatch.setattr("pokepoke.orchestration.workflow.invoke_copilot", lambda *a, **kw: _ok_copilot(stats=stats))
        monkeypatch.setattr("pokepoke.orchestration.workflow._log_commit_status", lambda *a: None)
        monkeypatch.setattr("pokepoke.orchestration.workflow.run_cleanup_with_timeout", lambda *a, **kw: (True, 0))
        monkeypatch.setattr("pokepoke.orchestration.workflow._extract_agent_stats", lambda *a, **kw: stats)
        monkeypatch.setattr(
            "pokepoke.orchestration.workflow._finalize_item_result",
            lambda *a, **kw: (WorkItemResult(success=True, request_count=1, stats=stats), True),
        )
        result = process_work_item(_item(), interactive=False)
        assert result.success is True


class TestProcessWorkItemCopilotFailureNoRetry:
    """Copilot fails, max_copilot_failure_retries=0 → break immediately."""

    def test_copilot_fail_no_retry(self, monkeypatch):
        monkeypatch.setattr("pokepoke.orchestration.workflow_helpers.create_worktree", lambda *a, **kw: Path("/tmp/wt"))
        monkeypatch.setattr("pokepoke.orchestration.workflow.invoke_copilot", lambda *a, **kw: _fail_copilot())
        monkeypatch.setattr("pokepoke.orchestration.workflow._extract_agent_stats", lambda r: None)
        monkeypatch.setattr("pokepoke.orchestration.workflow._maybe_retry_copilot", lambda *a, **kw: (False, ""))
        monkeypatch.setattr(
            "pokepoke.orchestration.workflow._finalize_item_result",
            lambda *a, **kw: (WorkItemResult(success=False, request_count=1), True),
        )
        result = process_work_item(_item(), interactive=False)
        assert result.success is False


class TestProcessWorkItemShutdownDuringLoop:
    """is_shutting_down returns True on first iteration → loop exits."""

    def test_shutdown_exits_loop(self, monkeypatch):
        monkeypatch.setattr("pokepoke.orchestration.workflow_helpers.create_worktree", lambda *a, **kw: Path("/tmp/wt"))
        monkeypatch.setattr("pokepoke.orchestration.workflow.is_shutting_down", lambda: True)
        monkeypatch.setattr(
            "pokepoke.orchestration.workflow._finalize_item_result",
            lambda *a, **kw: (WorkItemResult(success=False, request_count=0), True),
        )
        result = process_work_item(_item(), interactive=False)
        assert result.success is False


class TestProcessWorkItemTimeoutRestart:
    """Elapsed exceeds timeout; restart count hits limit → fail."""

    def test_timeout_max_restarts_exceeded(self, monkeypatch, _mock_workflow_deps):
        _mock_workflow_deps.max_copilot_failure_retries = 0
        monkeypatch.setattr("pokepoke.orchestration.workflow_helpers.create_worktree", lambda *a, **kw: Path("/tmp/wt"))
        # Make time.time() return values so elapsed always exceeds timeout
        call_count = {"n": 0}
        def fake_time():
            call_count["n"] += 1
            # start_time = 0 (first call), then always return a large number
            if call_count["n"] == 1:
                return 0.0
            return 100000.0  # way past any timeout
        monkeypatch.setattr("pokepoke.orchestration.workflow.time.time", fake_time)
        # timeout_hours=0.001 → timeout_seconds≈3.6, max_timeout_restarts=0
        result = process_work_item(_item(), interactive=False, timeout_hours=0.001, max_timeout_restarts=0)
        assert result.success is False

    def test_timeout_restarts_then_succeeds(self, monkeypatch, _mock_workflow_deps):
        """Timeout fires once, restart resets timer, then copilot succeeds."""
        _mock_workflow_deps.max_copilot_failure_retries = 0
        monkeypatch.setattr("pokepoke.orchestration.workflow_helpers.create_worktree", lambda *a, **kw: Path("/tmp/wt"))

        # First time.time() is start_time (0), second causes timeout,
        # third is reset start_time, fourth is within budget
        times = iter([0.0, 100000.0, 0.0, 1.0, 1.0, 1.0, 1.0, 1.0])
        monkeypatch.setattr("pokepoke.orchestration.workflow.time.time", lambda: next(times, 1.0))

        monkeypatch.setattr("pokepoke.orchestration.workflow.invoke_copilot", lambda *a, **kw: _ok_copilot())
        monkeypatch.setattr("pokepoke.orchestration.workflow._log_commit_status", lambda *a: None)
        monkeypatch.setattr("pokepoke.orchestration.workflow._extract_agent_stats", lambda r: None)
        monkeypatch.setattr("pokepoke.orchestration.workflow.run_cleanup_with_timeout", lambda *a, **kw: (True, 0))
        monkeypatch.setattr(
            "pokepoke.orchestration.workflow._finalize_item_result",
            lambda *a, **kw: (WorkItemResult(success=True, request_count=1), True),
        )
        result = process_work_item(_item(), interactive=False, timeout_hours=0.001, max_timeout_restarts=3)
        assert result.success is True


class TestProcessWorkItemCopilotTimeoutWithResume:
    """invoke_copilot fails with timeout+session_id → resume path exercised."""

    def test_timeout_then_resume_then_success(self, monkeypatch, _mock_workflow_deps):
        _mock_workflow_deps.max_copilot_failure_retries = 2
        monkeypatch.setattr("pokepoke.orchestration.workflow_helpers.create_worktree", lambda *a, **kw: Path("/tmp/wt"))

        call_count = {"n": 0}
        def fake_invoke(*a, **kw):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return _timeout_copilot()
            return _ok_copilot()

        monkeypatch.setattr("pokepoke.orchestration.workflow.invoke_copilot", fake_invoke)
        monkeypatch.setattr("pokepoke.orchestration.workflow._extract_agent_stats", lambda r: None)
        monkeypatch.setattr("pokepoke.orchestration.workflow._log_commit_status", lambda *a: None)
        monkeypatch.setattr("pokepoke.orchestration.workflow.run_cleanup_with_timeout", lambda *a, **kw: (True, 0))
        # _maybe_retry_copilot returns (True, feedback) on first call
        retry_calls = {"n": 0}
        def fake_maybe_retry(*a, **kw):
            retry_calls["n"] += 1
            if retry_calls["n"] == 1:
                return (True, "timeout feedback")
            return (False, "")
        monkeypatch.setattr("pokepoke.orchestration.workflow._maybe_retry_copilot", fake_maybe_retry)
        monkeypatch.setattr("pokepoke.orchestration.workflow._apply_gate_feedback", lambda fb, acc, it: ([*acc, fb], it + 1))
        monkeypatch.setattr(
            "pokepoke.orchestration.workflow._finalize_item_result",
            lambda *a, **kw: (WorkItemResult(success=True, request_count=2), True),
        )
        result = process_work_item(_item(), interactive=False)
        assert result.success is True


class TestProcessWorkItemCleanupFailure:
    """run_cleanup_with_timeout returns (False, n) → immediate fail."""

    def test_cleanup_failure(self, monkeypatch):
        monkeypatch.setattr("pokepoke.orchestration.workflow_helpers.create_worktree", lambda *a, **kw: Path("/tmp/wt"))
        monkeypatch.setattr("pokepoke.orchestration.workflow.invoke_copilot", lambda *a, **kw: _ok_copilot())
        monkeypatch.setattr("pokepoke.orchestration.workflow._extract_agent_stats", lambda r: None)
        monkeypatch.setattr("pokepoke.orchestration.workflow._log_commit_status", lambda *a: None)
        monkeypatch.setattr("pokepoke.orchestration.workflow.run_cleanup_with_timeout", lambda *a, **kw: (False, 1))
        monkeypatch.setattr("pokepoke.orchestration.workflow._log_failure", lambda *a, **kw: None)
        result = process_work_item(_item(), interactive=False)
        assert result.success is False


class TestProcessWorkItemBeadsItemAlreadyClosed:
    """is_beads_item_closed returns True → skip gate, succeed."""

    def test_already_closed(self, monkeypatch):
        monkeypatch.setattr("pokepoke.orchestration.workflow_helpers.create_worktree", lambda *a, **kw: Path("/tmp/wt"))
        monkeypatch.setattr("pokepoke.orchestration.workflow.invoke_copilot", lambda *a, **kw: _ok_copilot())
        monkeypatch.setattr("pokepoke.orchestration.workflow._extract_agent_stats", lambda r: None)
        monkeypatch.setattr("pokepoke.orchestration.workflow._log_commit_status", lambda *a: None)
        monkeypatch.setattr("pokepoke.beads.reconciliation.is_beads_item_closed", lambda *a: True)
        monkeypatch.setattr(
            "pokepoke.orchestration.workflow._finalize_item_result",
            lambda *a, **kw: (WorkItemResult(success=True, request_count=1), True),
        )
        result = process_work_item(_item(), interactive=False)
        assert result.success is True


class TestProcessWorkItemGateAgentEnabled:
    """Gate agent enabled → exercises the gate agent retry loop."""

    def test_gate_passes(self, monkeypatch, _mock_workflow_deps):
        _mock_workflow_deps.gate_agent_enabled = True
        monkeypatch.setattr("pokepoke.orchestration.workflow_helpers.create_worktree", lambda *a, **kw: Path("/tmp/wt"))
        monkeypatch.setattr("pokepoke.orchestration.workflow.invoke_copilot", lambda *a, **kw: _ok_copilot())
        monkeypatch.setattr("pokepoke.orchestration.workflow._extract_agent_stats", lambda r: None)
        monkeypatch.setattr("pokepoke.orchestration.workflow._log_commit_status", lambda *a: None)
        monkeypatch.setattr("pokepoke.orchestration.workflow.run_cleanup_with_timeout", lambda *a, **kw: (True, 1))
        gate_ok = GateAgentResult(success=True, reason="looks good", crashed=False, is_timeout=False)
        monkeypatch.setattr("pokepoke.orchestration.workflow.run_gate_agent", lambda *a, **kw: gate_ok)
        monkeypatch.setattr(
            "pokepoke.orchestration.workflow._finalize_item_result",
            lambda *a, **kw: (WorkItemResult(success=True, request_count=1), True),
        )
        result = process_work_item(_item(), interactive=False)
        assert result.success is True

    def test_gate_rejects_then_work_agent_retries(self, monkeypatch, _mock_workflow_deps):
        """Gate rejects → feedback loop, then shutdown stops the loop."""
        _mock_workflow_deps.gate_agent_enabled = True
        monkeypatch.setattr("pokepoke.orchestration.workflow_helpers.create_worktree", lambda *a, **kw: Path("/tmp/wt"))

        invoke_count = {"n": 0}
        def fake_invoke(*a, **kw):
            invoke_count["n"] += 1
            return _ok_copilot()
        monkeypatch.setattr("pokepoke.orchestration.workflow.invoke_copilot", fake_invoke)
        monkeypatch.setattr("pokepoke.orchestration.workflow._extract_agent_stats", lambda r: None)
        monkeypatch.setattr("pokepoke.orchestration.workflow._log_commit_status", lambda *a: None)
        monkeypatch.setattr("pokepoke.orchestration.workflow.run_cleanup_with_timeout", lambda *a, **kw: (True, 0))
        monkeypatch.setattr("pokepoke.orchestration.workflow._apply_gate_feedback", lambda fb, acc, it: ([*acc, fb], it + 1))

        gate_call = {"n": 0}
        def fake_gate(*a, **kw):
            gate_call["n"] += 1
            if gate_call["n"] == 1:
                return GateAgentResult(success=False, reason="tests fail", crashed=False, is_timeout=False)
            return GateAgentResult(success=True, reason="ok", crashed=False, is_timeout=False)
        monkeypatch.setattr("pokepoke.orchestration.workflow.run_gate_agent", fake_gate)
        monkeypatch.setattr(
            "pokepoke.orchestration.workflow._finalize_item_result",
            lambda *a, **kw: (WorkItemResult(success=True, request_count=2), True),
        )
        result = process_work_item(_item(), interactive=False)
        assert result.success is True
        assert invoke_count["n"] == 2  # work agent ran twice

    def test_gate_crashes_retries_then_raises(self, monkeypatch, _mock_workflow_deps):
        """Gate crashes 3 times → exception propagates."""
        _mock_workflow_deps.gate_agent_enabled = True
        monkeypatch.setattr("pokepoke.orchestration.workflow_helpers.create_worktree", lambda *a, **kw: Path("/tmp/wt"))
        monkeypatch.setattr("pokepoke.orchestration.workflow.invoke_copilot", lambda *a, **kw: _ok_copilot())
        monkeypatch.setattr("pokepoke.orchestration.workflow._extract_agent_stats", lambda r: None)
        monkeypatch.setattr("pokepoke.orchestration.workflow._log_commit_status", lambda *a: None)
        monkeypatch.setattr("pokepoke.orchestration.workflow.run_cleanup_with_timeout", lambda *a, **kw: (True, 0))
        def _raise(*a, **kw): raise RuntimeError("infra crash")
        monkeypatch.setattr("pokepoke.orchestration.workflow.run_gate_agent", _raise)

        with pytest.raises(RuntimeError, match="infra crash"):
            process_work_item(_item(), interactive=False)

    def test_gate_timeout_retries_then_gives_up(self, monkeypatch, _mock_workflow_deps):
        """Gate times out 3 times → breaks out of gate loop."""
        _mock_workflow_deps.gate_agent_enabled = True
        monkeypatch.setattr("pokepoke.orchestration.workflow_helpers.create_worktree", lambda *a, **kw: Path("/tmp/wt"))
        monkeypatch.setattr("pokepoke.orchestration.workflow.invoke_copilot", lambda *a, **kw: _ok_copilot())
        monkeypatch.setattr("pokepoke.orchestration.workflow._extract_agent_stats", lambda r: None)
        monkeypatch.setattr("pokepoke.orchestration.workflow._log_commit_status", lambda *a: None)
        monkeypatch.setattr("pokepoke.orchestration.workflow.run_cleanup_with_timeout", lambda *a, **kw: (True, 0))
        gate_timeout = GateAgentResult(
            success=False, reason="timed out", crashed=False, is_timeout=True,
            session_id="gate-sess-1", last_output_summary="partial",
        )
        monkeypatch.setattr("pokepoke.orchestration.workflow.run_gate_agent", lambda *a, **kw: gate_timeout)
        monkeypatch.setattr(
            "pokepoke.orchestration.workflow._finalize_item_result",
            lambda *a, **kw: (WorkItemResult(success=False, request_count=1), True),
        )
        result = process_work_item(_item(), interactive=False)
        assert result.success is False

    def test_gate_crashed_flag_retries(self, monkeypatch, _mock_workflow_deps):
        """Gate returns crashed=True via result flag → retries then gives up."""
        _mock_workflow_deps.gate_agent_enabled = True
        monkeypatch.setattr("pokepoke.orchestration.workflow_helpers.create_worktree", lambda *a, **kw: Path("/tmp/wt"))
        monkeypatch.setattr("pokepoke.orchestration.workflow.invoke_copilot", lambda *a, **kw: _ok_copilot())
        monkeypatch.setattr("pokepoke.orchestration.workflow._extract_agent_stats", lambda r: None)
        monkeypatch.setattr("pokepoke.orchestration.workflow._log_commit_status", lambda *a: None)
        monkeypatch.setattr("pokepoke.orchestration.workflow.run_cleanup_with_timeout", lambda *a, **kw: (True, 0))
        gate_crash = GateAgentResult(
            success=False, reason="segfault", crashed=True, is_timeout=False,
        )
        monkeypatch.setattr("pokepoke.orchestration.workflow.run_gate_agent", lambda *a, **kw: gate_crash)
        monkeypatch.setattr(
            "pokepoke.orchestration.workflow._finalize_item_result",
            lambda *a, **kw: (WorkItemResult(success=False, request_count=1), True),
        )
        result = process_work_item(_item(), interactive=False)
        assert result.success is False


class TestProcessWorkItemFinalizationNotComplete:
    """_finalize_item_result returns finalized=False → session cleanup runs."""

    def test_session_cleanup_on_failed_finalize(self, monkeypatch):
        monkeypatch.setattr("pokepoke.orchestration.workflow_helpers.create_worktree", lambda *a, **kw: Path("/tmp/wt"))
        monkeypatch.setattr("pokepoke.orchestration.workflow.invoke_copilot", lambda *a, **kw: _ok_copilot())
        monkeypatch.setattr("pokepoke.orchestration.workflow._extract_agent_stats", lambda r: None)
        monkeypatch.setattr("pokepoke.orchestration.workflow._log_commit_status", lambda *a: None)
        monkeypatch.setattr("pokepoke.orchestration.workflow.run_cleanup_with_timeout", lambda *a, **kw: (True, 0))
        monkeypatch.setattr(
            "pokepoke.orchestration.workflow._finalize_item_result",
            lambda *a, **kw: (WorkItemResult(success=False, request_count=1), False),
        )
        mock_session = MagicMock()
        monkeypatch.setattr("pokepoke.orchestration.workflow.WorkItemSession", lambda **kw: mock_session)
        result = process_work_item(_item(), interactive=False)
        assert result.success is False
        mock_session.cleanup_on_failure.assert_called_once()


class TestProcessWorkItemCopilotRetryOnFailure:
    """Copilot fails, _maybe_retry_copilot returns True → loop continues."""

    def test_copilot_retries_then_succeeds(self, monkeypatch, _mock_workflow_deps):
        _mock_workflow_deps.max_copilot_failure_retries = 2
        monkeypatch.setattr("pokepoke.orchestration.workflow_helpers.create_worktree", lambda *a, **kw: Path("/tmp/wt"))

        call_count = {"n": 0}
        def fake_invoke(*a, **kw):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return _fail_copilot()
            return _ok_copilot()
        monkeypatch.setattr("pokepoke.orchestration.workflow.invoke_copilot", fake_invoke)
        monkeypatch.setattr("pokepoke.orchestration.workflow._extract_agent_stats", lambda r: None)
        monkeypatch.setattr("pokepoke.orchestration.workflow._log_commit_status", lambda *a: None)
        monkeypatch.setattr("pokepoke.orchestration.workflow.run_cleanup_with_timeout", lambda *a, **kw: (True, 0))

        retry_count = {"n": 0}
        def fake_maybe_retry(*a, **kw):
            retry_count["n"] += 1
            if retry_count["n"] == 1:
                return (True, "retry feedback")
            return (False, "")
        monkeypatch.setattr("pokepoke.orchestration.workflow._maybe_retry_copilot", fake_maybe_retry)
        monkeypatch.setattr("pokepoke.orchestration.workflow._apply_gate_feedback", lambda fb, acc, it: ([*acc, fb], it + 1))
        monkeypatch.setattr(
            "pokepoke.orchestration.workflow._finalize_item_result",
            lambda *a, **kw: (WorkItemResult(success=True, request_count=2), True),
        )
        result = process_work_item(_item(), interactive=False)
        assert result.success is True
        assert call_count["n"] == 2

    def test_non_timeout_failure_clears_resume_state(self, monkeypatch, _mock_workflow_deps):
        """Non-timeout failure clears resume_session_id."""
        _mock_workflow_deps.max_copilot_failure_retries = 1
        monkeypatch.setattr("pokepoke.orchestration.workflow_helpers.create_worktree", lambda *a, **kw: Path("/tmp/wt"))
        # First: timeout failure with session, second: non-timeout failure
        call_n = {"n": 0}
        def fake_invoke(*a, **kw):
            call_n["n"] += 1
            if call_n["n"] == 1:
                return _timeout_copilot()
            return _fail_copilot(error="syntax error")  # no timeout keyword
        monkeypatch.setattr("pokepoke.orchestration.workflow.invoke_copilot", fake_invoke)
        monkeypatch.setattr("pokepoke.orchestration.workflow._extract_agent_stats", lambda r: None)

        retry_n = {"n": 0}
        def fake_retry(*a, **kw):
            retry_n["n"] += 1
            if retry_n["n"] == 1:
                return (True, "try again")
            return (False, "")
        monkeypatch.setattr("pokepoke.orchestration.workflow._maybe_retry_copilot", fake_retry)
        monkeypatch.setattr("pokepoke.orchestration.workflow._apply_gate_feedback", lambda fb, acc, it: ([*acc, fb], it + 1))
        monkeypatch.setattr(
            "pokepoke.orchestration.workflow._finalize_item_result",
            lambda *a, **kw: (WorkItemResult(success=False, request_count=2), True),
        )
        result = process_work_item(_item(), interactive=False)
        assert result.success is False


class TestProcessWorkItemRepoPath:
    """Verify repo_path argument flows through correctly."""

    def test_repo_path_used(self, monkeypatch):
        monkeypatch.setattr("pokepoke.orchestration.workflow_helpers.create_worktree", lambda *a, **kw: Path("/tmp/wt"))
        monkeypatch.setattr("pokepoke.orchestration.workflow.invoke_copilot", lambda *a, **kw: _ok_copilot())
        monkeypatch.setattr("pokepoke.orchestration.workflow._extract_agent_stats", lambda r: None)
        monkeypatch.setattr("pokepoke.orchestration.workflow._log_commit_status", lambda *a: None)
        monkeypatch.setattr("pokepoke.orchestration.workflow.run_cleanup_with_timeout", lambda *a, **kw: (True, 0))
        monkeypatch.setattr(
            "pokepoke.orchestration.workflow._finalize_item_result",
            lambda *a, **kw: (WorkItemResult(success=True, request_count=1), True),
        )
        result = process_work_item(_item(), interactive=False, repo_path="/custom/path")
        assert result.success is True


class TestProcessWorkItemRunLogger:
    """Verify run_logger integration points."""

    def test_run_logger_starts_item_log(self, monkeypatch):
        run_logger = MagicMock()
        item_logger = MagicMock()
        run_logger.start_item_log.return_value = item_logger

        monkeypatch.setattr("pokepoke.orchestration.workflow_helpers.create_worktree", lambda *a, **kw: Path("/tmp/wt"))
        monkeypatch.setattr("pokepoke.orchestration.workflow.invoke_copilot", lambda *a, **kw: _ok_copilot())
        monkeypatch.setattr("pokepoke.orchestration.workflow._extract_agent_stats", lambda r: None)
        monkeypatch.setattr("pokepoke.orchestration.workflow._log_commit_status", lambda *a: None)
        monkeypatch.setattr("pokepoke.orchestration.workflow.run_cleanup_with_timeout", lambda *a, **kw: (True, 0))
        monkeypatch.setattr(
            "pokepoke.orchestration.workflow._finalize_item_result",
            lambda *a, **kw: (WorkItemResult(success=True, request_count=1), True),
        )
        result = process_work_item(_item(), interactive=False, run_logger=run_logger)
        assert result.success is True
        run_logger.start_item_log.assert_called_once()


class TestProcessWorkItemInteractiveConfirm:
    """User enters 'y' or empty → proceed normally."""

    def test_user_confirms_with_y(self, monkeypatch):
        monkeypatch.setattr("builtins.input", lambda _: "y")
        monkeypatch.setattr("pokepoke.orchestration.workflow_helpers.create_worktree", lambda *a, **kw: Path("/tmp/wt"))
        monkeypatch.setattr("pokepoke.orchestration.workflow.invoke_copilot", lambda *a, **kw: _ok_copilot())
        monkeypatch.setattr("pokepoke.orchestration.workflow._extract_agent_stats", lambda r: None)
        monkeypatch.setattr("pokepoke.orchestration.workflow._log_commit_status", lambda *a: None)
        monkeypatch.setattr("pokepoke.orchestration.workflow.run_cleanup_with_timeout", lambda *a, **kw: (True, 0))
        monkeypatch.setattr(
            "pokepoke.orchestration.workflow._finalize_item_result",
            lambda *a, **kw: (WorkItemResult(success=True, request_count=1), True),
        )
        result = process_work_item(_item(), interactive=True)
        assert result.success is True

    def test_user_confirms_with_empty(self, monkeypatch):
        monkeypatch.setattr("builtins.input", lambda _: "")
        monkeypatch.setattr("pokepoke.orchestration.workflow_helpers.create_worktree", lambda *a, **kw: Path("/tmp/wt"))
        monkeypatch.setattr("pokepoke.orchestration.workflow.invoke_copilot", lambda *a, **kw: _ok_copilot())
        monkeypatch.setattr("pokepoke.orchestration.workflow._extract_agent_stats", lambda r: None)
        monkeypatch.setattr("pokepoke.orchestration.workflow._log_commit_status", lambda *a: None)
        monkeypatch.setattr("pokepoke.orchestration.workflow.run_cleanup_with_timeout", lambda *a, **kw: (True, 0))
        monkeypatch.setattr(
            "pokepoke.orchestration.workflow._finalize_item_result",
            lambda *a, **kw: (WorkItemResult(success=True, request_count=1), True),
        )
        result = process_work_item(_item(), interactive=True)
        assert result.success is True


class TestProcessWorkItemFeedbackPaths:
    """Cover the feedback printing branches (gate vs timeout retry)."""

    def test_gate_feedback_prints_restart(self, monkeypatch, _mock_workflow_deps):
        """After gate rejection, last_retry_was_gate_feedback=True → 'Restarting' path."""
        _mock_workflow_deps.gate_agent_enabled = True
        monkeypatch.setattr("pokepoke.orchestration.workflow_helpers.create_worktree", lambda *a, **kw: Path("/tmp/wt"))

        invoke_n = {"n": 0}
        def fake_invoke(*a, **kw):
            invoke_n["n"] += 1
            return _ok_copilot()
        monkeypatch.setattr("pokepoke.orchestration.workflow.invoke_copilot", fake_invoke)
        monkeypatch.setattr("pokepoke.orchestration.workflow._extract_agent_stats", lambda r: None)
        monkeypatch.setattr("pokepoke.orchestration.workflow._log_commit_status", lambda *a: None)
        monkeypatch.setattr("pokepoke.orchestration.workflow.run_cleanup_with_timeout", lambda *a, **kw: (True, 0))
        monkeypatch.setattr("pokepoke.orchestration.workflow._apply_gate_feedback", lambda fb, acc, it: ([*acc, fb], it + 1))

        gate_n = {"n": 0}
        def fake_gate(*a, **kw):
            gate_n["n"] += 1
            if gate_n["n"] <= 1:
                return GateAgentResult(success=False, reason="needs fixes", crashed=False, is_timeout=False)
            return GateAgentResult(success=True, reason="ok", crashed=False, is_timeout=False)
        monkeypatch.setattr("pokepoke.orchestration.workflow.run_gate_agent", fake_gate)
        monkeypatch.setattr(
            "pokepoke.orchestration.workflow._finalize_item_result",
            lambda *a, **kw: (WorkItemResult(success=True, request_count=2), True),
        )
        result = process_work_item(_item(), interactive=False)
        assert result.success is True

    def test_timeout_feedback_prints_resuming(self, monkeypatch, _mock_workflow_deps):
        """After timeout retry, last_retry_was_gate_feedback=False → 'Resuming' path."""
        _mock_workflow_deps.max_copilot_failure_retries = 1
        monkeypatch.setattr("pokepoke.orchestration.workflow_helpers.create_worktree", lambda *a, **kw: Path("/tmp/wt"))

        n = {"n": 0}
        def fake_invoke(*a, **kw):
            n["n"] += 1
            if n["n"] == 1:
                return _timeout_copilot()
            return _ok_copilot()
        monkeypatch.setattr("pokepoke.orchestration.workflow.invoke_copilot", fake_invoke)
        monkeypatch.setattr("pokepoke.orchestration.workflow._extract_agent_stats", lambda r: None)
        monkeypatch.setattr("pokepoke.orchestration.workflow._log_commit_status", lambda *a: None)
        monkeypatch.setattr("pokepoke.orchestration.workflow.run_cleanup_with_timeout", lambda *a, **kw: (True, 0))
        monkeypatch.setattr("pokepoke.orchestration.workflow._maybe_retry_copilot", lambda *a, **kw: (True, "timeout fb"))
        monkeypatch.setattr("pokepoke.orchestration.workflow._apply_gate_feedback", lambda fb, acc, it: ([*acc, fb], it + 1))

        # After retry succeeds, mock finalize
        def fake_finalize(*a, **kw):
            return (WorkItemResult(success=True, request_count=2), True)
        monkeypatch.setattr("pokepoke.orchestration.workflow._finalize_item_result", fake_finalize)
        # Need _maybe_retry_copilot to return False on second failure to avoid infinite loop
        retry_n = {"n": 0}
        def retry_once(*a, **kw):
            retry_n["n"] += 1
            if retry_n["n"] == 1:
                return (True, "timeout feedback")
            return (False, "")
        monkeypatch.setattr("pokepoke.orchestration.workflow._maybe_retry_copilot", retry_once)

        result = process_work_item(_item(), interactive=False)
        assert result.success is True


class TestProcessWorkItemGateResumeInPlace:
    """Cover the gate resume_in_place=True branch (gate timeout with session_id)."""

    def test_gate_timeout_with_session_id_resumes(self, monkeypatch, _mock_workflow_deps):
        _mock_workflow_deps.gate_agent_enabled = True
        monkeypatch.setattr("pokepoke.orchestration.workflow_helpers.create_worktree", lambda *a, **kw: Path("/tmp/wt"))
        monkeypatch.setattr("pokepoke.orchestration.workflow.invoke_copilot", lambda *a, **kw: _ok_copilot())
        monkeypatch.setattr("pokepoke.orchestration.workflow._extract_agent_stats", lambda r: None)
        monkeypatch.setattr("pokepoke.orchestration.workflow._log_commit_status", lambda *a: None)
        monkeypatch.setattr("pokepoke.orchestration.workflow.run_cleanup_with_timeout", lambda *a, **kw: (True, 0))

        gate_n = {"n": 0}
        def fake_gate(*a, **kw):
            gate_n["n"] += 1
            if gate_n["n"] <= 2:
                return GateAgentResult(
                    success=False, reason="timed out", crashed=False, is_timeout=True,
                    session_id="gate-sess-resume", last_output_summary="partial gate output",
                )
            # Third time also times out to hit max
            return GateAgentResult(
                success=False, reason="timed out again", crashed=False, is_timeout=True,
            )
        monkeypatch.setattr("pokepoke.orchestration.workflow.run_gate_agent", fake_gate)
        monkeypatch.setattr(
            "pokepoke.orchestration.workflow._finalize_item_result",
            lambda *a, **kw: (WorkItemResult(success=False, request_count=1), True),
        )
        result = process_work_item(_item(), interactive=False)
        assert result.success is False
