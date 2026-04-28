"""Tests for gate agent executor - JSON parsing, timeout detection, result building."""

import json
from unittest.mock import Mock, patch

from pokepoke.agents.agent_config import GateAgentConfig
from pokepoke.agents.gate_agent_executor import run_gate_agent
from pokepoke.types import BeadsWorkItem


def _make_item(**kwargs):
    defaults = dict(id="item-1", title="Test", status="in_progress", priority=1, issue_type="task")
    defaults.update(kwargs)
    return BeadsWorkItem(**defaults)


def _mock_invoke_result(success=True, output="", error=None, session_id=None, last_output_summary=None):
    r = Mock()
    r.success = success
    r.output = output
    r.error = error
    r.session_id = session_id
    r.last_output_summary = last_output_summary
    return r


# ---------------------------------------------------------------------------
# Gate JSON parsing
# ---------------------------------------------------------------------------

class TestGateAgentJsonParsing:
    """Tests for JSON verdict extraction from gate agent output."""

    @patch("pokepoke.agents.gate_agent_executor.invoke_copilot")
    @patch("pokepoke.agents.gate_agent_executor.select_gate_model", return_value=None)
    @patch("pokepoke.agents.gate_agent_executor.get_default_branch", return_value="main")
    @patch("pokepoke.agents.gate_agent_executor.terminal_ui")
    def test_success_json_verdict(self, mock_ui, mock_branch, mock_model, mock_invoke):
        verdict = json.dumps({"status": "success", "message": "All tests pass"})
        output = f"Some preamble\n```json\n{verdict}\n```\nMore text"
        mock_invoke.return_value = _mock_invoke_result(success=True, output=output)

        result = run_gate_agent(_make_item())

        assert result.success is True
        assert "All tests pass" in result.reason

    @patch("pokepoke.agents.gate_agent_executor.invoke_copilot")
    @patch("pokepoke.agents.gate_agent_executor.select_gate_model", return_value=None)
    @patch("pokepoke.agents.gate_agent_executor.get_default_branch", return_value="main")
    @patch("pokepoke.agents.gate_agent_executor.terminal_ui")
    def test_failure_json_verdict(self, mock_ui, mock_branch, mock_model, mock_invoke):
        verdict = json.dumps({"status": "failure", "reason": "Tests fail", "details": "3 errors"})
        output = f"```json\n{verdict}\n```"
        mock_invoke.return_value = _mock_invoke_result(success=True, output=output)

        result = run_gate_agent(_make_item())

        assert result.success is False
        assert "Tests fail" in result.reason
        assert "3 errors" in result.reason

    @patch("pokepoke.agents.gate_agent_executor.invoke_copilot")
    @patch("pokepoke.agents.gate_agent_executor.select_gate_model", return_value=None)
    @patch("pokepoke.agents.gate_agent_executor.get_default_branch", return_value="main")
    @patch("pokepoke.agents.gate_agent_executor.terminal_ui")
    def test_success_with_reason_and_recommendation(self, mock_ui, mock_branch, mock_model, mock_invoke):
        verdict = json.dumps({
            "status": "success", "message": "Verified",
            "reason": "All checks passed", "recommendation": "Ship it",
        })
        output = f"```json\n{verdict}\n```"
        mock_invoke.return_value = _mock_invoke_result(success=True, output=output)

        result = run_gate_agent(_make_item())

        assert result.success is True
        assert "All checks passed" in result.reason
        assert "Ship it" in result.reason

    @patch("pokepoke.agents.gate_agent_executor.invoke_copilot")
    @patch("pokepoke.agents.gate_agent_executor.select_gate_model", return_value=None)
    @patch("pokepoke.agents.gate_agent_executor.get_default_branch", return_value="main")
    @patch("pokepoke.agents.gate_agent_executor.terminal_ui")
    def test_multiple_json_blocks_uses_last(self, mock_ui, mock_branch, mock_model, mock_invoke):
        """When multiple JSON blocks exist, the last one with a status key is used."""
        block1 = json.dumps({"status": "failure", "reason": "Early check"})
        block2 = json.dumps({"status": "success", "message": "Final verdict"})
        output = f"```json\n{block1}\n```\nMore text\n```json\n{block2}\n```"
        mock_invoke.return_value = _mock_invoke_result(success=True, output=output)

        result = run_gate_agent(_make_item())

        assert result.success is True
        assert "Final verdict" in result.reason

    @patch("pokepoke.agents.gate_agent_executor.invoke_copilot")
    @patch("pokepoke.agents.gate_agent_executor.select_gate_model", return_value=None)
    @patch("pokepoke.agents.gate_agent_executor.get_default_branch", return_value="main")
    @patch("pokepoke.agents.gate_agent_executor.terminal_ui")
    def test_case_insensitive_json_fence(self, mock_ui, mock_branch, mock_model, mock_invoke):
        """JSON fence with mixed case (```JSON) should still be parsed."""
        verdict = json.dumps({"status": "success", "message": "ok"})
        output = f"```JSON\n{verdict}\n```"
        mock_invoke.return_value = _mock_invoke_result(success=True, output=output)

        result = run_gate_agent(_make_item())

        assert result.success is True


# ---------------------------------------------------------------------------
# Text-match fallback
# ---------------------------------------------------------------------------

class TestGateAgentTextFallback:
    """Tests for text-based success detection when no JSON verdict present."""

    @patch("pokepoke.agents.gate_agent_executor.invoke_copilot")
    @patch("pokepoke.agents.gate_agent_executor.select_gate_model", return_value=None)
    @patch("pokepoke.agents.gate_agent_executor.get_default_branch", return_value="main")
    @patch("pokepoke.agents.gate_agent_executor.terminal_ui")
    def test_verification_successful_text_match(self, mock_ui, mock_branch, mock_model, mock_invoke):
        output = "The fix looks good. VERIFICATION SUCCESSFUL."
        mock_invoke.return_value = _mock_invoke_result(success=True, output=output)

        result = run_gate_agent(_make_item())

        assert result.success is True
        assert "text match" in result.reason

    @patch("pokepoke.agents.gate_agent_executor.invoke_copilot")
    @patch("pokepoke.agents.gate_agent_executor.select_gate_model", return_value=None)
    @patch("pokepoke.agents.gate_agent_executor.get_default_branch", return_value="main")
    @patch("pokepoke.agents.gate_agent_executor.terminal_ui")
    def test_new_work_verified_text_match(self, mock_ui, mock_branch, mock_model, mock_invoke):
        output = "Changes look correct. NEW_WORK_VERIFIED"
        mock_invoke.return_value = _mock_invoke_result(success=True, output=output)

        result = run_gate_agent(_make_item())

        assert result.success is True

    @patch("pokepoke.agents.gate_agent_executor.invoke_copilot")
    @patch("pokepoke.agents.gate_agent_executor.select_gate_model", return_value=None)
    @patch("pokepoke.agents.gate_agent_executor.get_default_branch", return_value="main")
    @patch("pokepoke.agents.gate_agent_executor.terminal_ui")
    def test_no_approval_gives_failure(self, mock_ui, mock_branch, mock_model, mock_invoke):
        output = "I looked at the code but I'm not sure it's correct."
        mock_invoke.return_value = _mock_invoke_result(success=True, output=output)

        result = run_gate_agent(_make_item())

        assert result.success is False
        assert result.crashed is False
        assert "did not explicitly approve" in result.reason


# ---------------------------------------------------------------------------
# ProcessMonitor output corruption handling
# ---------------------------------------------------------------------------

class TestGateAgentProcessMonitorCorruption:
    """Tests for handling ProcessMonitor lines interleaved in JSON verdict."""

    @patch("pokepoke.agents.gate_agent_executor.invoke_copilot")
    @patch("pokepoke.agents.gate_agent_executor.select_gate_model", return_value=None)
    @patch("pokepoke.agents.gate_agent_executor.get_default_branch", return_value="main")
    @patch("pokepoke.agents.gate_agent_executor.terminal_ui")
    def test_success_verdict_with_process_monitor_interleaved(self, mock_ui, mock_branch, mock_model, mock_invoke):
        """ProcessMonitor lines inside JSON block should be stripped, allowing parse to succeed."""
        output = (
            "Analysis complete.\n"
            "```json\n"
            "{\n"
            '  "status": "success",\n'
            "[ProcessMonitor] PID 12345 (pytest.exe) active - wrote 2048 bytes\n"
            '  "message": "All tests pass"\n'
            "}\n"
            "```"
        )
        mock_invoke.return_value = _mock_invoke_result(success=True, output=output)

        result = run_gate_agent(_make_item())

        assert result.success is True
        assert "All tests pass" in result.reason

    @patch("pokepoke.agents.gate_agent_executor.invoke_copilot")
    @patch("pokepoke.agents.gate_agent_executor.select_gate_model", return_value=None)
    @patch("pokepoke.agents.gate_agent_executor.get_default_branch", return_value="main")
    @patch("pokepoke.agents.gate_agent_executor.terminal_ui")
    def test_failure_verdict_with_process_monitor_interleaved(self, mock_ui, mock_branch, mock_model, mock_invoke):
        """ProcessMonitor lines in a failure verdict should still parse correctly."""
        output = (
            "```json\n"
            "{\n"
            '  "status": "failure",\n'
            "[ProcessMonitor] Started monitoring PID 999 (python.exe)\n"
            '  "reason": "Tests failing",\n'
            '  "details": "2 errors"\n'
            "}\n"
            "```"
        )
        mock_invoke.return_value = _mock_invoke_result(success=True, output=output)

        result = run_gate_agent(_make_item())

        assert result.success is False
        assert result.crashed is False
        assert "Tests failing" in result.reason

    @patch("pokepoke.agents.gate_agent_executor.invoke_copilot")
    @patch("pokepoke.agents.gate_agent_executor.select_gate_model", return_value=None)
    @patch("pokepoke.agents.gate_agent_executor.get_default_branch", return_value="main")
    @patch("pokepoke.agents.gate_agent_executor.terminal_ui")
    def test_unparseable_json_blocks_marked_as_crash(self, mock_ui, mock_branch, mock_model, mock_invoke):
        """When JSON blocks exist but none can be parsed, treat as crash not rejection."""
        output = (
            "```json\n"
            "{ this is not valid json at all }\n"
            "```"
        )
        mock_invoke.return_value = _mock_invoke_result(success=True, output=output)

        result = run_gate_agent(_make_item())

        assert result.success is False
        assert result.crashed is True
        assert "corrupted" in result.reason.lower()

    @patch("pokepoke.agents.gate_agent_executor.invoke_copilot")
    @patch("pokepoke.agents.gate_agent_executor.select_gate_model", return_value=None)
    @patch("pokepoke.agents.gate_agent_executor.get_default_branch", return_value="main")
    @patch("pokepoke.agents.gate_agent_executor.terminal_ui")
    def test_multiple_monitor_lines_stripped_from_json(self, mock_ui, mock_branch, mock_model, mock_invoke):
        """Multiple ProcessMonitor lines in one JSON block should all be stripped."""
        output = (
            "```json\n"
            "{\n"
            "[ProcessMonitor] Started monitoring PID 1 (a.exe)\n"
            '  "status": "success",\n'
            "[ProcessMonitor] PID 1 (a.exe) active - wrote 100 bytes\n"
            '  "message": "Verified"\n'
            "[ProcessMonitor] PID 1 (a.exe) completed\n"
            "}\n"
            "```"
        )
        mock_invoke.return_value = _mock_invoke_result(success=True, output=output)

        result = run_gate_agent(_make_item())

        assert result.success is True
        assert "Verified" in result.reason

    @patch("pokepoke.agents.gate_agent_executor.invoke_copilot")
    @patch("pokepoke.agents.gate_agent_executor.select_gate_model", return_value=None)
    @patch("pokepoke.agents.gate_agent_executor.get_default_branch", return_value="main")
    @patch("pokepoke.agents.gate_agent_executor.terminal_ui")
    def test_process_monitor_breaks_code_fence_uses_unfenced_fallback(
        self, mock_ui, mock_branch, mock_model, mock_invoke,
    ):
        """When ProcessMonitor breaks the code fence, unfenced JSON extraction recovers the verdict."""
        output = (
            "Analysis complete.\n"
            "``[ProcessMonitor] PID 1234 (python.exe) active`json\n"
            '{"status": "success", "message": "All tests pass"}\n'
            "```\n"
            "Done."
        )
        mock_invoke.return_value = _mock_invoke_result(success=True, output=output)

        result = run_gate_agent(_make_item())

        assert result.success is True
        assert "All tests pass" in result.reason

    @patch("pokepoke.agents.gate_agent_executor.invoke_copilot")
    @patch("pokepoke.agents.gate_agent_executor.select_gate_model", return_value=None)
    @patch("pokepoke.agents.gate_agent_executor.get_default_branch", return_value="main")
    @patch("pokepoke.agents.gate_agent_executor.terminal_ui")
    def test_process_monitor_noise_no_json_treated_as_crash(
        self, mock_ui, mock_branch, mock_model, mock_invoke,
    ):
        """When output has ProcessMonitor noise but no parseable verdict, treat as crash not rejection."""
        output = (
            "[ProcessMonitor] Started monitoring PID 5678 (node.exe)\n"
            "I analyzed the code and it looks good.\n"
            "[ProcessMonitor] PID 5678 (node.exe) completed\n"
        )
        mock_invoke.return_value = _mock_invoke_result(success=True, output=output)

        result = run_gate_agent(_make_item())

        assert result.success is False
        assert result.crashed is True
        assert "processmonitor" in result.reason.lower()

    @patch("pokepoke.agents.gate_agent_executor.invoke_copilot")
    @patch("pokepoke.agents.gate_agent_executor.select_gate_model", return_value=None)
    @patch("pokepoke.agents.gate_agent_executor.get_default_branch", return_value="main")
    @patch("pokepoke.agents.gate_agent_executor.terminal_ui")
    def test_unfenced_failure_verdict_extracted(
        self, mock_ui, mock_branch, mock_model, mock_invoke,
    ):
        """Unfenced JSON failure verdict is extracted when no fenced blocks exist."""
        output = (
            'Here is my verdict:\n'
            '{"status": "failure", "reason": "Missing tests", "details": "No coverage"}\n'
            "That's my analysis."
        )
        mock_invoke.return_value = _mock_invoke_result(success=True, output=output)

        result = run_gate_agent(_make_item())

        assert result.success is False
        assert result.crashed is False
        assert "Missing tests" in result.reason


# ---------------------------------------------------------------------------
# Execution failures and timeouts
# ---------------------------------------------------------------------------

class TestGateAgentFailures:
    """Tests for gate agent execution failures and timeouts."""

    @patch("pokepoke.agents.gate_agent_executor.invoke_copilot")
    @patch("pokepoke.agents.gate_agent_executor.select_gate_model", return_value=None)
    @patch("pokepoke.agents.gate_agent_executor.get_default_branch", return_value="main")
    @patch("pokepoke.agents.gate_agent_executor.terminal_ui")
    def test_execution_failure_marked_as_crash(self, mock_ui, mock_branch, mock_model, mock_invoke):
        mock_invoke.return_value = _mock_invoke_result(success=False, error="Process exited with code 1")

        result = run_gate_agent(_make_item())

        assert result.success is False
        assert result.crashed is True
        assert result.is_timeout is False

    @patch("pokepoke.agents.gate_agent_executor.invoke_copilot")
    @patch("pokepoke.agents.gate_agent_executor.select_gate_model", return_value=None)
    @patch("pokepoke.agents.gate_agent_executor.get_default_branch", return_value="main")
    @patch("pokepoke.agents.gate_agent_executor.terminal_ui")
    def test_timeout_error_detected(self, mock_ui, mock_branch, mock_model, mock_invoke):
        mock_invoke.return_value = _mock_invoke_result(success=False, error="Session timeout reached")

        result = run_gate_agent(_make_item())

        assert result.success is False
        assert result.is_timeout is True
        assert result.crashed is False

    @patch("pokepoke.agents.gate_agent_executor.invoke_copilot")
    @patch("pokepoke.agents.gate_agent_executor.select_gate_model", return_value=None)
    @patch("pokepoke.agents.gate_agent_executor.get_default_branch", return_value="main")
    @patch("pokepoke.agents.gate_agent_executor.terminal_ui")
    def test_inactivity_timeout_detected(self, mock_ui, mock_branch, mock_model, mock_invoke):
        mock_invoke.return_value = _mock_invoke_result(success=False, error="Terminated due to inactivity")

        result = run_gate_agent(_make_item())

        assert result.success is False
        assert result.is_timeout is True
        assert result.crashed is False

    @patch("pokepoke.agents.gate_agent_executor.PromptService")
    @patch("pokepoke.agents.gate_agent_executor.select_gate_model", return_value=None)
    @patch("pokepoke.agents.gate_agent_executor.get_default_branch", return_value="main")
    @patch("pokepoke.agents.gate_agent_executor.terminal_ui")
    def test_prompt_render_failure(self, mock_ui, mock_branch, mock_model, mock_prompt_svc):
        mock_prompt_svc.return_value.load_and_render.side_effect = RuntimeError("Template not found")

        result = run_gate_agent(_make_item())

        assert result.success is False
        assert result.crashed is True
        assert "Failed to render prompt" in result.reason


# ---------------------------------------------------------------------------
# Stats and session_id propagation
# ---------------------------------------------------------------------------

class TestGateAgentResultMetadata:
    """Tests for stats parsing and session_id in gate results."""

    @patch("pokepoke.agents.gate_agent_executor.invoke_copilot")
    @patch("pokepoke.agents.gate_agent_executor.select_gate_model", return_value=None)
    @patch("pokepoke.agents.gate_agent_executor.get_default_branch", return_value="main")
    @patch("pokepoke.agents.gate_agent_executor.terminal_ui")
    def test_stats_parsed_from_output(self, mock_ui, mock_branch, mock_model, mock_invoke):
        output = (
            "Total duration (wall): 20.5s\n"
            "Total code changes: 10 lines added, 3 lines removed\n"
            '```json\n{"status":"success","message":"ok"}\n```'
        )
        mock_invoke.return_value = _mock_invoke_result(success=True, output=output)

        result = run_gate_agent(_make_item())

        assert result.stats is not None
        assert result.stats.wall_duration == 20.5
        assert result.stats.lines_added == 10

    @patch("pokepoke.agents.gate_agent_executor.invoke_copilot")
    @patch("pokepoke.agents.gate_agent_executor.select_gate_model", return_value=None)
    @patch("pokepoke.agents.gate_agent_executor.get_default_branch", return_value="main")
    @patch("pokepoke.agents.gate_agent_executor.terminal_ui")
    def test_session_id_propagated(self, mock_ui, mock_branch, mock_model, mock_invoke):
        verdict = json.dumps({"status": "success", "message": "ok"})
        output = f"```json\n{verdict}\n```"
        mock_invoke.return_value = _mock_invoke_result(
            success=True, output=output,
            session_id="sess-abc", last_output_summary="summary text",
        )

        result = run_gate_agent(_make_item())

        assert result.session_id == "sess-abc"
        assert result.last_output_summary == "summary text"

    @patch("pokepoke.agents.gate_agent_executor.invoke_copilot")
    @patch("pokepoke.agents.gate_agent_executor.select_gate_model", return_value=None)
    @patch("pokepoke.agents.gate_agent_executor.get_default_branch", return_value="main")
    @patch("pokepoke.agents.gate_agent_executor.terminal_ui")
    def test_no_stats_when_no_output(self, mock_ui, mock_branch, mock_model, mock_invoke):
        mock_invoke.return_value = _mock_invoke_result(success=True, output="")

        result = run_gate_agent(_make_item())

        assert result.stats is None


# ---------------------------------------------------------------------------
# Gate model selection and recording
# ---------------------------------------------------------------------------

class TestGateModelRecording:
    """Tests for gate model recording via record_gate_check."""

    @patch("pokepoke.agents.gate_agent_executor.record_gate_check")
    @patch("pokepoke.agents.gate_agent_executor.invoke_copilot")
    @patch("pokepoke.agents.gate_agent_executor.select_gate_model", return_value="claude-3")
    @patch("pokepoke.agents.gate_agent_executor.get_default_branch", return_value="main")
    @patch("pokepoke.agents.gate_agent_executor.terminal_ui")
    def test_records_gate_check_on_success(self, mock_ui, mock_branch, mock_model, mock_invoke, mock_record):
        verdict = json.dumps({"status": "success", "message": "ok"})
        output = f"```json\n{verdict}\n```"
        mock_invoke.return_value = _mock_invoke_result(success=True, output=output)

        run_gate_agent(_make_item(), config=GateAgentConfig(work_model="gpt-4"))

        mock_record.assert_called_once_with("claude-3", "item-1", True, reason='')

    @patch("pokepoke.agents.gate_agent_executor.record_gate_check")
    @patch("pokepoke.agents.gate_agent_executor.invoke_copilot")
    @patch("pokepoke.agents.gate_agent_executor.select_gate_model", return_value="claude-3")
    @patch("pokepoke.agents.gate_agent_executor.get_default_branch", return_value="main")
    @patch("pokepoke.agents.gate_agent_executor.terminal_ui")
    def test_records_gate_check_on_failure(self, mock_ui, mock_branch, mock_model, mock_invoke, mock_record):
        verdict = json.dumps({"status": "failure", "reason": "Bad code"})
        output = f"```json\n{verdict}\n```"
        mock_invoke.return_value = _mock_invoke_result(success=True, output=output)

        run_gate_agent(_make_item(), config=GateAgentConfig(work_model="gpt-4"))

        mock_record.assert_called_once_with("claude-3", "item-1", False, reason="Bad code\nDetails: ")

    @patch("pokepoke.agents.gate_agent_executor.record_gate_check")
    @patch("pokepoke.agents.gate_agent_executor.invoke_copilot")
    @patch("pokepoke.agents.gate_agent_executor.select_gate_model", return_value="claude-3")
    @patch("pokepoke.agents.gate_agent_executor.get_default_branch", return_value="main")
    @patch("pokepoke.agents.gate_agent_executor.terminal_ui")
    def test_no_recording_on_crash(self, mock_ui, mock_branch, mock_model, mock_invoke, mock_record):
        mock_invoke.return_value = _mock_invoke_result(success=False, error="Process killed")

        run_gate_agent(_make_item(), config=GateAgentConfig(work_model="gpt-4"))

        mock_record.assert_not_called()


class TestGateAgentAddParentDir:
    """Tests that gate agent passes add_parent_dir=True for parent repo visibility."""

    @patch("pokepoke.agents.gate_agent_executor.invoke_copilot")
    @patch("pokepoke.agents.gate_agent_executor.select_gate_model", return_value=None)
    @patch("pokepoke.agents.gate_agent_executor.get_default_branch", return_value="main")
    @patch("pokepoke.agents.gate_agent_executor.terminal_ui")
    def test_gate_agent_passes_add_parent_dir_true(self, mock_ui, mock_branch, mock_model, mock_invoke):
        """Gate agent invocations should include add_parent_dir=True."""
        verdict = json.dumps({"status": "success", "message": "ok"})
        output = f"```json\n{verdict}\n```"
        mock_invoke.return_value = _mock_invoke_result(success=True, output=output)

        run_gate_agent(_make_item())

        _, kwargs = mock_invoke.call_args
        assert kwargs.get("add_parent_dir") is True


class TestGateAgentProcessMonitorCorruptionRegression:
    """Regression tests for PokePoke-urg3h: ProcessMonitor output corrupting JSON verdicts."""

    @patch("pokepoke.agents.gate_agent_executor.invoke_copilot")
    @patch("pokepoke.agents.gate_agent_executor.select_gate_model", return_value=None)
    @patch("pokepoke.agents.gate_agent_executor.get_default_branch", return_value="main")
    @patch("pokepoke.agents.gate_agent_executor.terminal_ui")
    def test_corrupted_json_block_falls_through_to_text_match(
        self, mock_ui, mock_branch, mock_model, mock_invoke
    ):
        """JSON corrupted by ProcessMonitor lines should be skipped; text fallback should work."""
        # Simulate the exact corruption pattern from the bug report
        corrupted_output = (
            'Looks good.\n'
            '```json\n'
            '{\n'
            '  "status": "success",\n'
            '  "reason[ProcessMonitor] PID 167828 ...\n'
            '": "new_work_verified"\n'
            '}\n'
            '```\n'
            'VERIFICATION SUCCESSFUL'
        )
        mock_invoke.return_value = _mock_invoke_result(success=True, output=corrupted_output)

        result = run_gate_agent(_make_item())

        # The corrupted JSON should fail to parse, but text fallback should succeed
        assert result.success is True
        assert "text match" in result.reason

    @patch("pokepoke.agents.gate_agent_executor.invoke_copilot")
    @patch("pokepoke.agents.gate_agent_executor.select_gate_model", return_value=None)
    @patch("pokepoke.agents.gate_agent_executor.get_default_branch", return_value="main")
    @patch("pokepoke.agents.gate_agent_executor.terminal_ui")
    def test_corrupted_json_without_text_fallback_rejects(
        self, mock_ui, mock_branch, mock_model, mock_invoke
    ):
        """Corrupted JSON with no text fallback keywords should reject."""
        corrupted_output = (
            '```json\n'
            '{\n'
            '  "status": "success",\n'
            '  "reason[ProcessMonitor] PID 167828 (copilot.exe) active - wrote 13121 bytes\n'
            '": "new_work_verified"\n'
            '}\n'
            '```'
        )
        mock_invoke.return_value = _mock_invoke_result(success=True, output=corrupted_output)

        result = run_gate_agent(_make_item())

        assert result.success is False
        assert result.crashed is True
        assert "could not be parsed" in result.reason.lower()
