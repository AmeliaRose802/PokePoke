"""Unit tests for agent_runner module."""

from unittest.mock import Mock, patch

import pytest

from pokepoke.agents.agent_config import GateAgentConfig
from pokepoke.agents.agent_runner import (
    run_gate_agent,
)
from pokepoke.types import AgentStats, BeadsWorkItem
from pokepoke.types_agent import CopilotResult, GateAgentResult


class TestRunGateAgent:
    """Test run_gate_agent function."""

    @pytest.fixture
    def work_item(self) -> BeadsWorkItem:
        """Create a test work item."""
        return BeadsWorkItem(
            id="test-123",
            title="Test Fix",
            description="Fix the bug",
            status="in_progress",
            priority=1,
            issue_type="bug",
            labels=["test"]
        )

    @patch('pokepoke.agents.gate_agent_executor.parse_agent_stats')
    @patch('pokepoke.agents.gate_agent_executor.invoke_copilot')
    @patch('pokepoke.agents.gate_agent_executor.PromptService')
    def test_successful_verification_json(
        self,
        mock_service_cls: Mock,
        mock_invoke: Mock,
        mock_parse: Mock,
        work_item: BeadsWorkItem
    ) -> None:
        """Test successful gate agent verification with JSON output."""
        mock_service = Mock()
        mock_service.load_and_render.return_value = "Gate prompt"
        mock_service_cls.return_value = mock_service

        mock_invoke.return_value = CopilotResult(
            work_item_id="test-123",
            success=True,
            output='```json\n{"status": "success", "message": "All tests pass"}\n```',
            attempt_count=1
        )
        mock_parse.return_value = AgentStats(
            wall_duration=10.0, api_duration=5.0, input_tokens=100,
            output_tokens=50, lines_added=0, lines_removed=0, premium_requests=1
        )

        success, reason, stats, crashed = run_gate_agent(work_item)

        assert success is True
        assert "All tests pass" in reason
        assert stats is not None
        assert crashed is False
        mock_invoke.assert_called_once_with(work_item, prompt="Gate prompt", deny_write=True, cwd=None, model=None, item_logger=None, session_id=None, is_resume=False, add_parent_dir=True)

    @patch('pokepoke.agents.gate_agent_executor.parse_agent_stats')
    @patch('pokepoke.agents.gate_agent_executor.invoke_copilot')
    @patch('pokepoke.agents.gate_agent_executor.PromptService')
    def test_failed_verification_json(
        self,
        mock_service_cls: Mock,
        mock_invoke: Mock,
        mock_parse: Mock,
        work_item: BeadsWorkItem
    ) -> None:
        """Test failed gate agent verification with JSON output."""
        mock_service = Mock()
        mock_service.load_and_render.return_value = "Gate prompt"
        mock_service_cls.return_value = mock_service

        mock_invoke.return_value = CopilotResult(
            work_item_id="test-123",
            success=True,
            output='```json\n{"status": "failed", "reason": "Tests failed", "details": "3 tests failed"}\n```',
            attempt_count=1
        )
        mock_parse.return_value = None

        success, reason, _stats, crashed = run_gate_agent(work_item)

        assert success is False
        assert "Tests failed" in reason
        assert "3 tests failed" in reason
        assert crashed is False

    @patch('pokepoke.agents.gate_agent_executor.parse_agent_stats')
    @patch('pokepoke.agents.gate_agent_executor.invoke_copilot')
    @patch('pokepoke.agents.gate_agent_executor.PromptService')
    def test_successful_verification_text_fallback(
        self,
        mock_service_cls: Mock,
        mock_invoke: Mock,
        mock_parse: Mock,
        work_item: BeadsWorkItem
    ) -> None:
        """Test successful verification using text fallback when JSON fails."""
        mock_service = Mock()
        mock_service.load_and_render.return_value = "Gate prompt"
        mock_service_cls.return_value = mock_service

        mock_invoke.return_value = CopilotResult(
            work_item_id="test-123",
            success=True,
            output="VERIFICATION SUCCESSFUL - all checks pass",
            attempt_count=1
        )
        mock_parse.return_value = None

        success, reason, _stats, _crashed = run_gate_agent(work_item)

        assert success is True
        assert "text match" in reason

    @patch('pokepoke.agents.gate_agent_executor.parse_agent_stats')
    @patch('pokepoke.agents.gate_agent_executor.invoke_copilot')
    @patch('pokepoke.agents.gate_agent_executor.PromptService')
    def test_new_work_verified_text_fallback(
        self,
        mock_service_cls: Mock,
        mock_invoke: Mock,
        mock_parse: Mock,
        work_item: BeadsWorkItem
    ) -> None:
        """Test successful verification using NEW_WORK_VERIFIED text fallback."""
        mock_service = Mock()
        mock_service.load_and_render.return_value = "Gate prompt"
        mock_service_cls.return_value = mock_service

        mock_invoke.return_value = CopilotResult(
            work_item_id="test-123",
            success=True,
            output="NEW_WORK_VERIFIED - All verification steps passed",
            attempt_count=1
        )
        mock_parse.return_value = None

        success, reason, _stats, _crashed = run_gate_agent(work_item)

        assert success is True
        assert "text match" in reason

    @patch('pokepoke.agents.gate_agent_executor.parse_agent_stats')
    @patch('pokepoke.agents.gate_agent_executor.invoke_copilot')
    @patch('pokepoke.agents.gate_agent_executor.PromptService')
    def test_multiline_json_with_nested_objects(
        self,
        mock_service_cls: Mock,
        mock_invoke: Mock,
        mock_parse: Mock,
        work_item: BeadsWorkItem
    ) -> None:
        """Test JSON parsing succeeds when output contains nested JSON objects.

        Regression test: the non-greedy regex {.*?} would stop at the first closing
        brace, incorrectly matching only an inner nested object. The greedy {.*} fix
        ensures the full outer object is captured.
        """
        mock_service = Mock()
        mock_service.load_and_render.return_value = "Gate prompt"
        mock_service_cls.return_value = mock_service

        mock_invoke.return_value = CopilotResult(
            work_item_id="test-123",
            success=True,
            output=(
                'Analysis complete.\n'
                '```json\n'
                '{\n'
                '  "status": "success",\n'
                '  "reason": "new_work_verified",\n'
                '  "message": "All verification steps passed",\n'
                '  "details": {"tests_run": 47, "tests_passed": 47}\n'
                '}\n'
                '```'
            ),
            attempt_count=1
        )
        mock_parse.return_value = None

        success, reason, _stats, _crashed = run_gate_agent(work_item)

        assert success is True
        assert "new_work_verified" in reason
        assert "All verification steps passed" in reason

    @patch('pokepoke.agents.gate_agent_executor.invoke_copilot')
    @patch('pokepoke.agents.gate_agent_executor.PromptService')
    def test_copilot_invocation_failure(
        self,
        mock_service_cls: Mock,
        mock_invoke: Mock,
        work_item: BeadsWorkItem
    ) -> None:
        """Test gate agent when Copilot invocation fails."""
        mock_service = Mock()
        mock_service.load_and_render.return_value = "Gate prompt"
        mock_service_cls.return_value = mock_service

        mock_invoke.return_value = CopilotResult(
            work_item_id="test-123",
            success=False,
            output="",
            error="Copilot CLI failed",
            attempt_count=1
        )

        success, reason, _stats, crashed = run_gate_agent(work_item)

        assert success is False
        assert "execution failed" in reason
        assert crashed is True

    @patch('pokepoke.agents.gate_agent_executor.invoke_copilot')
    @patch('pokepoke.agents.gate_agent_executor.PromptService')
    def test_timeout_detected_as_timeout_not_crash(
        self,
        mock_service_cls: Mock,
        mock_invoke: Mock,
        work_item: BeadsWorkItem
    ) -> None:
        """Timeout errors should set is_timeout=True and crashed=False."""
        mock_service = Mock()
        mock_service.load_and_render.return_value = "Gate prompt"
        mock_service_cls.return_value = mock_service

        mock_invoke.return_value = CopilotResult(
            work_item_id="test-123",
            success=False,
            output="",
            error="SESSION DEAD / inactivity timeout",
            attempt_count=1,
            session_id="sess-abc",
            last_output_summary="Running tests...",
        )

        result = run_gate_agent(work_item)

        assert isinstance(result, GateAgentResult)
        assert result.success is False
        assert result.is_timeout is True
        assert result.crashed is False
        assert result.session_id == "sess-abc"
        assert result.last_output_summary == "Running tests..."
        # Backward-compatible unpacking still works
        success, _reason, _stats, crashed = result
        assert success is False
        assert crashed is False

    @patch('pokepoke.agents.gate_agent_executor.invoke_copilot')
    @patch('pokepoke.agents.gate_agent_executor.PromptService')
    def test_non_timeout_failure_is_crash(
        self,
        mock_service_cls: Mock,
        mock_invoke: Mock,
        work_item: BeadsWorkItem
    ) -> None:
        """Non-timeout errors should set crashed=True and is_timeout=False."""
        mock_service = Mock()
        mock_service.load_and_render.return_value = "Gate prompt"
        mock_service_cls.return_value = mock_service

        mock_invoke.return_value = CopilotResult(
            work_item_id="test-123",
            success=False,
            output="",
            error="SDK process crashed unexpectedly",
            attempt_count=1,
        )

        result = run_gate_agent(work_item)

        assert isinstance(result, GateAgentResult)
        assert result.success is False
        assert result.is_timeout is False
        assert result.crashed is True

    @patch('pokepoke.agents.gate_agent_executor.invoke_copilot')
    @patch('pokepoke.agents.gate_agent_executor.PromptService')
    def test_resume_uses_gate_resume_prompt(
        self,
        mock_service_cls: Mock,
        mock_invoke: Mock,
        work_item: BeadsWorkItem
    ) -> None:
        """When session_id and is_resume are set, use gate resume prompt."""
        mock_invoke.return_value = CopilotResult(
            work_item_id="test-123",
            success=True,
            output='```json\n{"status": "success", "message": "All tests pass"}\n```',
            attempt_count=1,
        )

        result = run_gate_agent(
            work_item, config=GateAgentConfig(session_id="sess-abc", is_resume=True))

        assert result.success is True
        # Should NOT have called PromptService since we're resuming
        mock_service_cls.return_value.load_and_render.assert_not_called()
        # invoke_copilot should have been called with session_id and is_resume
        call_kwargs = mock_invoke.call_args
        assert call_kwargs[1].get('session_id') == "sess-abc"
        assert call_kwargs[1].get('is_resume') is True

    @patch('pokepoke.agents.gate_agent_executor.PromptService')
    def test_prompt_render_failure(
        self,
        mock_service_cls: Mock,
        work_item: BeadsWorkItem
    ) -> None:
        """Test gate agent when prompt rendering fails."""
        mock_service = Mock()
        mock_service.load_and_render.side_effect = Exception("Template not found")
        mock_service_cls.return_value = mock_service

        success, reason, stats, crashed = run_gate_agent(work_item)

        assert success is False
        assert "Failed to render prompt" in reason
        assert stats is None
        assert crashed is True

    @patch('pokepoke.agents.gate_agent_executor.invoke_copilot')
    @patch('pokepoke.agents.gate_agent_executor.PromptService')
    def test_no_explicit_approval(
        self,
        mock_service_cls: Mock,
        mock_invoke: Mock,
        work_item: BeadsWorkItem
    ) -> None:
        """Test when gate agent doesn't explicitly approve."""
        mock_service = Mock()
        mock_service.load_and_render.return_value = "Gate prompt"
        mock_service_cls.return_value = mock_service

        mock_invoke.return_value = CopilotResult(
            work_item_id="test-123",
            success=True,
            output="I looked at the code but I'm not sure...",
            attempt_count=1
        )

        success, reason, _stats, _crashed = run_gate_agent(work_item)

        assert success is False
        assert "did not explicitly approve" in reason

    @patch('pokepoke.agents.gate_agent_executor.parse_agent_stats')
    @patch('pokepoke.agents.gate_agent_executor.invoke_copilot')
    @patch('pokepoke.agents.gate_agent_executor.PromptService')
    def test_work_already_complete(
        self,
        mock_service_cls: Mock,
        mock_invoke: Mock,
        mock_parse: Mock,
        work_item: BeadsWorkItem
    ) -> None:
        """Test gate agent recognizing work already complete on main branch."""
        mock_service = Mock()
        mock_service.load_and_render.return_value = "Gate prompt"
        mock_service_cls.return_value = mock_service

        mock_invoke.return_value = CopilotResult(
            work_item_id="test-123",
            success=True,
            output='```json\n{"status": "success", "reason": "work_already_complete", '
                   '"message": "Fix already exists on main", '
                   '"recommendation": "Close as already-resolved"}\n```',
            attempt_count=1
        )
        mock_parse.return_value = None

        success, reason, _stats, _crashed = run_gate_agent(work_item)

        assert success is True
        assert "work_already_complete" in reason
        assert "Fix already exists on main" in reason
        assert "Close as already-resolved" in reason

    @patch('pokepoke.agents.gate_agent_executor.select_gate_model')
    @patch('pokepoke.agents.gate_agent_executor.parse_agent_stats')
    @patch('pokepoke.agents.gate_agent_executor.invoke_copilot')
    @patch('pokepoke.agents.gate_agent_executor.PromptService')
    def test_gate_agent_uses_different_model(
        self,
        mock_service_cls: Mock,
        mock_invoke: Mock,
        mock_parse: Mock,
        mock_select_gate: Mock,
        work_item: BeadsWorkItem
    ) -> None:
        """Test that gate agent uses a different model than work agent."""
        mock_service = Mock()
        mock_service.load_and_render.return_value = "Gate prompt"
        mock_service_cls.return_value = mock_service

        # Mock gate model selection to return a different model
        mock_select_gate.return_value = "gpt-5.1-codex"

        mock_invoke.return_value = CopilotResult(
            work_item_id="test-123",
            success=True,
            output='```json\n{"status": "success", "message": "All tests pass"}\n```',
            attempt_count=1
        )
        mock_parse.return_value = None

        # Call with work_model parameter
        success, _reason, _stats, _crashed = run_gate_agent(work_item, config=GateAgentConfig(work_model="claude-opus-4.6"))

        assert success is True
        # Verify select_gate_model was called with work model
        mock_select_gate.assert_called_once_with("claude-opus-4.6", "test-123")
        # Verify invoke_copilot was called with the gate model
        mock_invoke.assert_called_once_with(
            work_item,
            prompt="Gate prompt",
            deny_write=True,
            cwd=None,
            model="gpt-5.1-codex",
            item_logger=None,
            session_id=None,
            is_resume=False,
            add_parent_dir=True,
        )

    @patch('pokepoke.agents.gate_agent_executor.parse_agent_stats')
    @patch('pokepoke.agents.gate_agent_executor.invoke_copilot')
    @patch('pokepoke.agents.gate_agent_executor.PromptService')
    def test_handoff_context_passed_to_prompt(
        self,
        mock_service_cls: Mock,
        mock_invoke: Mock,
        mock_parse: Mock,
        work_item: BeadsWorkItem,
    ) -> None:
        """Test that handoff_context is passed to the prompt template."""
        mock_service = Mock()
        mock_service.load_and_render.return_value = "Gate prompt with handoff"
        mock_service_cls.return_value = mock_service

        mock_invoke.return_value = CopilotResult(
            work_item_id="test-123",
            success=True,
            output='```json\n{"status": "success", "message": "All tests pass"}\n```',
            attempt_count=1,
        )
        mock_parse.return_value = None

        handoff = "## Work Agent Handoff Context\n### Changed Files\nM\tsrc/foo.py"
        success, _reason, _stats, _crashed = run_gate_agent(work_item, config=GateAgentConfig(handoff_context=handoff))

        assert success is True
        # Verify handoff_context was included in template variables
        call_args = mock_service.load_and_render.call_args
        template_vars = call_args[0][1]
        assert template_vars["handoff_context"] == handoff

    @patch('pokepoke.agents.gate_agent_executor.parse_agent_stats')
    @patch('pokepoke.agents.gate_agent_executor.invoke_copilot')
    @patch('pokepoke.agents.gate_agent_executor.PromptService')
    def test_handoff_context_defaults_to_empty(
        self,
        mock_service_cls: Mock,
        mock_invoke: Mock,
        mock_parse: Mock,
        work_item: BeadsWorkItem,
    ) -> None:
        """Test that handoff_context defaults to empty string when not provided."""
        mock_service = Mock()
        mock_service.load_and_render.return_value = "Gate prompt"
        mock_service_cls.return_value = mock_service

        mock_invoke.return_value = CopilotResult(
            work_item_id="test-123",
            success=True,
            output='```json\n{"status": "success", "message": "OK"}\n```',
            attempt_count=1,
        )
        mock_parse.return_value = None

        run_gate_agent(work_item)

        call_args = mock_service.load_and_render.call_args
        template_vars = call_args[0][1]
        assert template_vars["handoff_context"] == ""

    @patch('pokepoke.agents.gate_agent_executor.get_default_branch', return_value='main')
    @patch('pokepoke.agents.gate_agent_executor.parse_agent_stats')
    @patch('pokepoke.agents.gate_agent_executor.invoke_copilot')
    @patch('pokepoke.agents.gate_agent_executor.PromptService')
    def test_default_branch_passed_to_template(
        self,
        mock_service_cls: Mock,
        mock_invoke: Mock,
        mock_parse: Mock,
        mock_get_branch: Mock,
        work_item: BeadsWorkItem,
    ) -> None:
        """Test that default_branch variable is passed to the gate-agent template."""
        mock_service = Mock()
        mock_service.load_and_render.return_value = "Gate prompt with default_branch"
        mock_service_cls.return_value = mock_service

        mock_invoke.return_value = CopilotResult(
            work_item_id="test-123",
            success=True,
            output='```json\n{"status": "success", "message": "OK"}\n```',
            attempt_count=1,
        )
        mock_parse.return_value = None

        run_gate_agent(work_item)

        # Verify get_default_branch was called
        mock_get_branch.assert_called_once()

        # Verify default_branch was included in template variables
        call_args = mock_service.load_and_render.call_args
        template_vars = call_args[0][1]
        assert template_vars["default_branch"] == "main"


class TestGateAgentJsonDecodeError:
    """Test gate agent JSONDecodeError fallback (lines 112-113)."""

    @pytest.fixture
    def work_item(self) -> BeadsWorkItem:
        return BeadsWorkItem(
            id="test-123", title="Test Fix", description="Fix the bug",
            status="in_progress", priority=1, issue_type="bug", labels=["test"]
        )

    @patch('pokepoke.agents.gate_agent_executor.parse_agent_stats')
    @patch('pokepoke.agents.gate_agent_executor.invoke_copilot')
    @patch('pokepoke.agents.gate_agent_executor.PromptService')
    def test_invalid_json_falls_back_to_text(
        self, mock_service_cls: Mock, mock_invoke: Mock, mock_parse: Mock,
        work_item: BeadsWorkItem
    ) -> None:
        """Invalid JSON in code block triggers JSONDecodeError handler."""
        mock_service = Mock()
        mock_service.load_and_render.return_value = "Gate prompt"
        mock_service_cls.return_value = mock_service
        mock_invoke.return_value = CopilotResult(
            work_item_id="test-123", success=True,
            output='```json\n{not valid json}\n```',
            attempt_count=1
        )
        mock_parse.return_value = None
        success, reason, _stats, crashed = run_gate_agent(work_item)
        assert success is False
        assert "could not be parsed" in reason
        assert crashed is True


class TestGateAgentWithAgentId:
    """Test gate agent pushes agent status when agent_id is provided (line 88)."""

    @patch('pokepoke.agents.gate_agent_executor.parse_agent_stats')
    @patch('pokepoke.agents.gate_agent_executor.invoke_copilot')
    @patch('pokepoke.agents.gate_agent_executor.PromptService')
    @patch('pokepoke.agents.gate_agent_executor.terminal_ui')
    def test_gate_agent_pushes_status_with_agent_id(
        self, mock_terminal_ui: Mock, mock_service_cls: Mock,
        mock_invoke: Mock, mock_parse: Mock,
    ) -> None:
        """Gate agent should push agent status when agent_id is provided."""
        work_item = BeadsWorkItem(
            id="test-123", title="Test Fix", description="Fix",
            status="in_progress", priority=1, issue_type="bug",
        )

        mock_service = Mock()
        mock_service.load_and_render.return_value = "Gate prompt"
        mock_service_cls.return_value = mock_service

        mock_invoke.return_value = CopilotResult(
            work_item_id="test-123", success=True,
            output='```json\n{"status": "success", "message": "OK"}\n```',
            attempt_count=1,
        )
        mock_parse.return_value = None

        success, _reason, _stats, _crashed = run_gate_agent(
            work_item, config=GateAgentConfig(agent_id="gate-123", parent_agent_id="parent-1"))

        assert success is True
        mock_terminal_ui.ui.push_agent_status.assert_called()
        call_kwargs = mock_terminal_ui.ui.push_agent_status.call_args
        assert call_kwargs[0][0] == "gate-123"
        assert call_kwargs[1]["parent_agent_id"] == "parent-1"
        assert call_kwargs[1]["agent_type"] == "gate"
