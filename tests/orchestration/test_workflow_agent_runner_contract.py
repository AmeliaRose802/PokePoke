"""Contract tests: workflow.py <-> agent_runner.py (gate_agent_executor.py).

Validates the boundary between the workflow orchestration layer and the
agent runner layer, ensuring:

1. ``run_gate_agent`` accepts the exact parameter types workflow passes.
2. ``GateAgentResult`` has all fields workflow expects.
3. ``CopilotResult`` round-trips correctly through the boundary.

All tests use fakes/mocks — no real subprocess calls.
"""

from __future__ import annotations

import inspect
from unittest.mock import MagicMock, patch

import pytest

from pokepoke.agents.gate_agent_executor import run_gate_agent
from pokepoke.types import AgentStats, BeadsWorkItem, CopilotResult, GateAgentResult
from pokepoke.work_agent_outcome import WorkAgentOutcome

# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def sample_item() -> BeadsWorkItem:
    return BeadsWorkItem(
        id="contract-1",
        title="Contract boundary test",
        status="in_progress",
        priority=1,
        issue_type="task",
        description="Validate the workflow/agent_runner contract",
    )


@pytest.fixture
def success_gate_result() -> GateAgentResult:
    return GateAgentResult(
        success=True,
        reason="Verification successful",
        stats=AgentStats(input_tokens=50, output_tokens=25),
        crashed=False,
        is_timeout=False,
        session_id="sess-abc",
        last_output_summary="All checks passed",
    )


@pytest.fixture
def failure_gate_result() -> GateAgentResult:
    return GateAgentResult(
        success=False,
        reason="Tests failing on line 42",
        stats=None,
        crashed=False,
        is_timeout=False,
        session_id=None,
        last_output_summary=None,
    )


@pytest.fixture
def crashed_gate_result() -> GateAgentResult:
    return GateAgentResult(
        success=False,
        reason="Gate Agent execution failed: process died",
        stats=None,
        crashed=True,
        is_timeout=False,
    )


@pytest.fixture
def timeout_gate_result() -> GateAgentResult:
    return GateAgentResult(
        success=False,
        reason="Gate Agent execution failed: inactivity timeout",
        stats=None,
        crashed=False,
        is_timeout=True,
        session_id="sess-timeout",
        last_output_summary="Partial output before timeout",
    )


# ── 1. run_gate_agent signature matches workflow call-site ──────────────────


class TestRunGateAgentSignature:
    """Verify run_gate_agent accepts the exact parameter types workflow passes."""

    def test_signature_accepts_all_workflow_kwargs(self) -> None:
        """The keyword arguments workflow.py passes must be valid parameters."""
        sig = inspect.signature(run_gate_agent)
        # These are the exact kwargs workflow.py passes at the call-site (line ~317)
        workflow_kwargs = {
            "item",
            "cwd",
            "work_model",
            "handoff_context",
            "agent_id",
            "agent_iteration",
            "parent_agent_id",
            "item_logger",
            "session_id",
            "is_resume",
        }
        accepted_params = set(sig.parameters.keys())
        missing = workflow_kwargs - accepted_params
        assert not missing, (
            f"run_gate_agent is missing parameters that workflow.py passes: {missing}"
        )

    def test_first_param_is_item(self) -> None:
        """The first positional parameter must accept a BeadsWorkItem."""
        sig = inspect.signature(run_gate_agent)
        params = list(sig.parameters.values())
        assert params[0].name == "item"
        # Annotation should reference BeadsWorkItem
        ann = params[0].annotation
        assert ann is BeadsWorkItem or (isinstance(ann, str) and "BeadsWorkItem" in ann)

    def test_return_type_is_gate_agent_result(self) -> None:
        """run_gate_agent must return GateAgentResult."""
        sig = inspect.signature(run_gate_agent)
        ret = sig.return_annotation
        assert ret is GateAgentResult or (
            isinstance(ret, str) and "GateAgentResult" in ret
        )

    def test_optional_params_have_defaults(self) -> None:
        """All optional workflow kwargs should have defaults in the signature."""
        sig = inspect.signature(run_gate_agent)
        optional_params = {
            "cwd", "work_model", "handoff_context", "agent_id",
            "agent_iteration", "parent_agent_id", "item_logger",
            "session_id", "is_resume",
        }
        for name in optional_params:
            param = sig.parameters[name]
            assert param.default is not inspect.Parameter.empty, (
                f"Parameter '{name}' should have a default value"
            )


# ── 2. GateAgentResult has all fields workflow expects ──────────────────────


class TestGateAgentResultFields:
    """Verify GateAgentResult exposes every attribute workflow.py reads."""

    # workflow.py accesses these attributes on gate_result (lines ~326-329, ~352-358)
    WORKFLOW_ACCESSED_FIELDS = {
        "success",       # gate_result.success
        "reason",        # gate_result.reason
        "crashed",       # gate_result.crashed
        "is_timeout",    # gate_result.is_timeout
        "session_id",    # gate_result.session_id (for timeout resume)
        "last_output_summary",  # gate_result.last_output_summary
    }

    def test_all_workflow_fields_exist(self, success_gate_result: GateAgentResult) -> None:
        for field_name in self.WORKFLOW_ACCESSED_FIELDS:
            assert hasattr(success_gate_result, field_name), (
                f"GateAgentResult missing field '{field_name}' used by workflow.py"
            )

    def test_success_is_bool(self, success_gate_result: GateAgentResult) -> None:
        assert isinstance(success_gate_result.success, bool)

    def test_reason_is_str(self, success_gate_result: GateAgentResult) -> None:
        assert isinstance(success_gate_result.reason, str)

    def test_crashed_is_bool(self, success_gate_result: GateAgentResult) -> None:
        assert isinstance(success_gate_result.crashed, bool)

    def test_is_timeout_is_bool(self, success_gate_result: GateAgentResult) -> None:
        assert isinstance(success_gate_result.is_timeout, bool)

    def test_session_id_is_optional_str(
        self, success_gate_result: GateAgentResult, failure_gate_result: GateAgentResult,
    ) -> None:
        assert isinstance(success_gate_result.session_id, str)
        assert failure_gate_result.session_id is None

    def test_last_output_summary_is_optional_str(
        self, success_gate_result: GateAgentResult, failure_gate_result: GateAgentResult,
    ) -> None:
        assert isinstance(success_gate_result.last_output_summary, str)
        assert failure_gate_result.last_output_summary is None

    def test_stats_is_optional_agent_stats(
        self, success_gate_result: GateAgentResult, failure_gate_result: GateAgentResult,
    ) -> None:
        assert isinstance(success_gate_result.stats, AgentStats)
        assert failure_gate_result.stats is None

    def test_iterable_unpacking_compat(self, success_gate_result: GateAgentResult) -> None:
        """workflow_helpers._run_gate_check unpacks via: success, reason, _, crashed = run_gate_agent(...)"""
        success, reason, stats, crashed = success_gate_result
        assert success is True
        assert isinstance(reason, str)
        assert isinstance(stats, AgentStats)
        assert crashed is False

    def test_iterable_unpacking_failure(self, failure_gate_result: GateAgentResult) -> None:
        success, reason, stats, crashed = failure_gate_result
        assert success is False
        assert "failing" in reason.lower()
        assert stats is None
        assert crashed is False

    def test_len_is_four(self, success_gate_result: GateAgentResult) -> None:
        """GateAgentResult must support len() == 4 for tuple-like unpacking."""
        assert len(success_gate_result) == 4


# ── 3. CopilotResult round-trips correctly ──────────────────────────────────


class TestCopilotResultRoundTrip:
    """CopilotResult is created in workflow.py, passed to agent_runner, and read back."""

    def test_minimal_copilot_result(self) -> None:
        """Minimal CopilotResult (as created by workflow.py fallback) has required fields."""
        result = CopilotResult(
            work_item_id="item-1", success=False,
            output="", error="some error", attempt_count=1,
        )
        assert result.work_item_id == "item-1"
        assert result.success is False
        assert result.output == ""
        assert result.error == "some error"
        assert result.attempt_count == 1

    def test_full_copilot_result(self) -> None:
        """Full CopilotResult with all optional fields workflow.py might set/read."""
        outcome = WorkAgentOutcome(status="completed", reason="All done")
        stats = AgentStats(input_tokens=200, output_tokens=100)
        result = CopilotResult(
            work_item_id="item-2",
            success=True,
            output="Agent output here",
            error=None,
            validation_errors=["warn1"],
            attempt_count=3,
            is_rate_limited=False,
            stats=stats,
            model="claude-sonnet-4",
            session_id="sess-123",
            last_output_summary="summary text",
            work_agent_outcome=outcome,
        )
        # Verify all fields workflow.py reads
        assert result.success is True
        assert result.attempt_count == 3
        assert result.error is None
        assert result.is_rate_limited is False
        assert result.session_id == "sess-123"
        assert result.last_output_summary == "summary text"
        assert result.work_agent_outcome is outcome
        assert result.work_agent_outcome.status == "completed"
        assert result.stats is stats
        assert result.model == "claude-sonnet-4"

    def test_copilot_result_success_is_mutable(self) -> None:
        """workflow.py mutates result.success = False after cleanup failure."""
        result = CopilotResult(
            work_item_id="item-3", success=True, output="ok", attempt_count=1,
        )
        assert result.success is True
        result.success = False
        assert result.success is False

    def test_copilot_result_fields_match_agent_runner_usage(self) -> None:
        """agent_runner.py creates CopilotResult on exception — verify the kwargs match."""
        # This mirrors agent_runner.py line ~300-302
        result = CopilotResult(
            work_item_id="agent-item",
            success=False,
            output="",
            error="subprocess error",
            attempt_count=1,
        )
        assert result.work_item_id == "agent-item"
        assert result.output == ""
        assert result.error == "subprocess error"

    def test_copilot_result_default_session_fields(self) -> None:
        """Session fields default to None for non-SDK invocations."""
        result = CopilotResult(
            work_item_id="item-4", success=True, output="done", attempt_count=1,
        )
        assert result.session_id is None
        assert result.last_output_summary is None
        assert result.work_agent_outcome is None

    def test_copilot_result_timeout_round_trip(self) -> None:
        """Timeout scenario: workflow reads session_id/last_output_summary for resume."""
        result = CopilotResult(
            work_item_id="item-5",
            success=False,
            output="partial output",
            error="inactivity timeout",
            attempt_count=1,
            session_id="sess-timeout",
            last_output_summary="last 500 chars",
        )
        # workflow.py checks these for resume logic
        assert result.session_id is not None
        assert result.last_output_summary is not None
        assert "timeout" in result.error.lower()


# ── 4. End-to-end: run_gate_agent returns valid GateAgentResult ─────────────


class TestRunGateAgentReturnsValidResult:
    """Invoke run_gate_agent with mocked dependencies and verify the contract."""

    @patch("pokepoke.agents.gate_agent_executor.terminal_ui")
    @patch("pokepoke.agents.gate_agent_executor.invoke_copilot")
    @patch("pokepoke.agents.gate_agent_executor.get_default_branch", return_value="main")
    @patch("pokepoke.agents.gate_agent_executor.get_config")
    @patch("pokepoke.agents.gate_agent_executor.record_gate_check")
    @patch("pokepoke.agents.gate_agent_executor.select_gate_model", return_value="test-model")
    def test_gate_success_result(
        self, mock_select_gate: MagicMock, mock_record: MagicMock,
        mock_config: MagicMock, mock_branch: MagicMock,
        mock_invoke: MagicMock, mock_ui: MagicMock,
        sample_item: BeadsWorkItem,
    ) -> None:
        """Gate agent returns success when output contains success verdict."""
        mock_config.return_value = MagicMock(command_timeout=60)
        mock_invoke.return_value = CopilotResult(
            work_item_id=sample_item.id,
            success=True,
            output='```json\n{"status": "success", "message": "All good"}\n```',
            attempt_count=1,
        )
        mock_ui.ui = MagicMock()

        result = run_gate_agent(
            sample_item,
            cwd="/fake/worktree",
            work_model="test-model",
            handoff_context="diff context here",
            agent_id="contract-1-gate-1",
            agent_iteration=1,
            parent_agent_id="contract-1",
            item_logger=None,
            session_id=None,
            is_resume=False,
        )

        assert isinstance(result, GateAgentResult)
        assert result.success is True
        assert isinstance(result.reason, str)
        assert result.crashed is False
        assert result.is_timeout is False

    @patch("pokepoke.agents.gate_agent_executor.terminal_ui")
    @patch("pokepoke.agents.gate_agent_executor.invoke_copilot")
    @patch("pokepoke.agents.gate_agent_executor.get_default_branch", return_value="main")
    @patch("pokepoke.agents.gate_agent_executor.get_config")
    @patch("pokepoke.agents.gate_agent_executor.record_gate_check")
    @patch("pokepoke.agents.gate_agent_executor.select_gate_model", return_value="test-model")
    def test_gate_failure_result(
        self, mock_select_gate: MagicMock, mock_record: MagicMock,
        mock_config: MagicMock, mock_branch: MagicMock,
        mock_invoke: MagicMock, mock_ui: MagicMock,
        sample_item: BeadsWorkItem,
    ) -> None:
        """Gate agent returns failure with reason when verdict is not success."""
        mock_config.return_value = MagicMock(command_timeout=60)
        mock_invoke.return_value = CopilotResult(
            work_item_id=sample_item.id,
            success=True,
            output='```json\n{"status": "failure", "reason": "Tests broken", "details": "line 42"}\n```',
            attempt_count=1,
        )
        mock_ui.ui = MagicMock()

        result = run_gate_agent(sample_item, cwd="/fake")

        assert isinstance(result, GateAgentResult)
        assert result.success is False
        assert "Tests broken" in result.reason
        assert result.crashed is False

    @patch("pokepoke.agents.gate_agent_executor.terminal_ui")
    @patch("pokepoke.agents.gate_agent_executor.invoke_copilot")
    @patch("pokepoke.agents.gate_agent_executor.get_default_branch", return_value="main")
    @patch("pokepoke.agents.gate_agent_executor.get_config")
    @patch("pokepoke.agents.gate_agent_executor.select_gate_model", return_value=None)
    def test_gate_copilot_timeout_result(
        self, mock_select_gate: MagicMock,
        mock_config: MagicMock, mock_branch: MagicMock,
        mock_invoke: MagicMock, mock_ui: MagicMock,
        sample_item: BeadsWorkItem,
    ) -> None:
        """Timeout from invoke_copilot sets is_timeout=True, crashed=False."""
        mock_config.return_value = MagicMock(command_timeout=60)
        mock_invoke.return_value = CopilotResult(
            work_item_id=sample_item.id,
            success=False,
            output="",
            error="inactivity timeout after 600s",
            attempt_count=1,
            session_id="sess-resume",
            last_output_summary="partial work",
        )
        mock_ui.ui = MagicMock()

        result = run_gate_agent(sample_item)

        assert isinstance(result, GateAgentResult)
        assert result.success is False
        assert result.is_timeout is True
        assert result.crashed is False
        assert result.session_id == "sess-resume"
        assert result.last_output_summary == "partial work"

    @patch("pokepoke.agents.gate_agent_executor.terminal_ui")
    @patch("pokepoke.agents.gate_agent_executor.invoke_copilot")
    @patch("pokepoke.agents.gate_agent_executor.get_default_branch", return_value="main")
    @patch("pokepoke.agents.gate_agent_executor.get_config")
    @patch("pokepoke.agents.gate_agent_executor.select_gate_model", return_value=None)
    def test_gate_crash_result(
        self, mock_select_gate: MagicMock,
        mock_config: MagicMock, mock_branch: MagicMock,
        mock_invoke: MagicMock, mock_ui: MagicMock,
        sample_item: BeadsWorkItem,
    ) -> None:
        """Non-timeout failure sets crashed=True."""
        mock_config.return_value = MagicMock(command_timeout=60)
        mock_invoke.return_value = CopilotResult(
            work_item_id=sample_item.id,
            success=False,
            output="",
            error="process died unexpectedly",
            attempt_count=1,
        )
        mock_ui.ui = MagicMock()

        result = run_gate_agent(sample_item)

        assert isinstance(result, GateAgentResult)
        assert result.success is False
        assert result.crashed is True
        assert result.is_timeout is False

    @patch("pokepoke.agents.gate_agent_executor.terminal_ui")
    @patch("pokepoke.agents.gate_agent_executor.PromptService")
    def test_gate_prompt_render_failure(
        self, mock_prompt_svc: MagicMock, mock_ui: MagicMock,
        sample_item: BeadsWorkItem,
    ) -> None:
        """Prompt rendering failure returns crashed=True GateAgentResult."""
        mock_ui.ui = MagicMock()
        svc_instance = MagicMock()
        svc_instance.load_and_render.side_effect = RuntimeError("Template not found")
        mock_prompt_svc.return_value = svc_instance

        result = run_gate_agent(sample_item)

        assert isinstance(result, GateAgentResult)
        assert result.success is False
        assert result.crashed is True
        assert "Failed to render prompt" in result.reason


# ── 5. Workflow-specific field access patterns ──────────────────────────────


class TestWorkflowFieldAccessPatterns:
    """Verify field access patterns used in workflow.py work with real instances."""

    def test_gate_result_timeout_resume_fields(self, timeout_gate_result: GateAgentResult) -> None:
        """workflow.py reads session_id and last_output_summary for timeout resume."""
        # Mirrors workflow.py lines ~355-357
        gate_resume_session_id = timeout_gate_result.session_id
        _gate_resume_output = timeout_gate_result.last_output_summary

        assert gate_resume_session_id == "sess-timeout"
        assert _gate_resume_output == "Partial output before timeout"

    def test_copilot_result_workflow_init_pattern(self) -> None:
        """workflow.py creates a default CopilotResult before the loop (line ~136)."""
        result = CopilotResult(
            work_item_id="item-1",
            success=False,
            error="Session aborted due to application shutdown",
            attempt_count=0,
        )
        # workflow.py later reads these:
        assert result.success is False
        assert result.attempt_count == 0
        assert result.error is not None
        assert result.output is None
        assert result.work_agent_outcome is None

    def test_copilot_result_work_agent_outcome_access(self) -> None:
        """workflow.py reads result.work_agent_outcome and checks .status (line ~257)."""
        outcome = WorkAgentOutcome(status="blocked", reason="Missing dependency")
        result = CopilotResult(
            work_item_id="item-1", success=True, output="done",
            attempt_count=1, work_agent_outcome=outcome,
        )
        assert result.work_agent_outcome is not None
        assert result.work_agent_outcome.status == "blocked"
        assert result.work_agent_outcome.reason == "Missing dependency"

    def test_copilot_result_rate_limit_check(self) -> None:
        """workflow.py checks result.is_rate_limited before retry (line ~239)."""
        result = CopilotResult(
            work_item_id="item-1", success=False,
            error="rate limited", attempt_count=1,
            is_rate_limited=True,
        )
        assert result.is_rate_limited is True

    def test_gate_result_crash_vs_timeout_distinction(
        self, crashed_gate_result: GateAgentResult, timeout_gate_result: GateAgentResult,
    ) -> None:
        """workflow.py uses crashed and is_timeout to select different retry paths."""
        # Crash path: retry with fresh session (line ~363-369)
        assert crashed_gate_result.crashed is True
        assert crashed_gate_result.is_timeout is False

        # Timeout path: retry with resume session_id (line ~352-361)
        assert timeout_gate_result.crashed is False
        assert timeout_gate_result.is_timeout is True
        assert timeout_gate_result.session_id is not None
