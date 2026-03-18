"""Tests for pokepoke.models.sdk_helpers module.

Covers helper functions that are not exercised by name-matched test files
(e.g. _summarize_output, build_*_prompt, _check_abort_result).
"""

import time
from unittest.mock import AsyncMock, patch

import pytest

from pokepoke.models.sdk_helpers import (
    _build_token_usage_callback,
    _check_abort_result,
    _check_tool_watchdog,
    _summarize_output,
    build_gate_resume_prompt,
    build_resume_prompt,
)
from pokepoke.types import BeadsWorkItem


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def work_item() -> BeadsWorkItem:
    return BeadsWorkItem(
        id="helper-test-1",
        title="Helper test item",
        description="A test description",
        status="in_progress",
        priority=1,
        issue_type="feature",
        labels=["testing"],
    )


@pytest.fixture
def work_item_no_desc() -> BeadsWorkItem:
    return BeadsWorkItem(
        id="helper-test-2",
        title="No description item",
        description=None,
        status="in_progress",
        priority=2,
        issue_type="bug",
    )


@pytest.fixture
def session_stats() -> dict:
    return {
        "pending_tool_calls": 0,
        "idle_task": None,
        "total_input_tokens": 200,
        "total_output_tokens": 100,
        "total_cache_read_tokens": 0,
        "total_cache_write_tokens": 0,
        "turn_count": 3,
        "total_tool_calls": 5,
        "last_event_time": time.monotonic(),
        "event_count": 15,
        "last_tool_activity_time": 0.0,
    }


# ── _summarize_output ────────────────────────────────────────────────────────


class TestSummarizeOutput:
    def test_empty_list_returns_none(self):
        assert _summarize_output([]) is None

    def test_whitespace_returns_none(self):
        assert _summarize_output(["  ", "\n"]) is None

    def test_short_output_returned_intact(self):
        result = _summarize_output(["hello\n", "world\n"])
        assert result == "hello\nworld"

    def test_exact_max_length_not_truncated(self):
        text = "a" * 50
        result = _summarize_output([text], max_length=50)
        assert result == text
        assert "truncated" not in result

    def test_long_output_truncated(self):
        lines = ["x" * 80 + "\n" for _ in range(30)]
        result = _summarize_output(lines, max_length=100)
        assert result is not None
        assert result.startswith("...(earlier output truncated)...")

    def test_tail_content_preserved(self):
        lines = ["OLD\n", "MIDDLE\n", "END_MARKER\n"]
        result = _summarize_output(lines, max_length=20)
        assert result is not None
        assert "END_MARKER" in result


# ── _check_abort_result ──────────────────────────────────────────────────────


class TestCheckAbortResult:
    def test_returns_none_when_nothing_detected(self):
        assert _check_abort_result("item-1", False, 600.0, False, 600.0) is None

    def test_returns_failure_on_tool_timeout(self):
        result = _check_abort_result("item-1", False, 600.0, True, 300.0)
        assert result is not None
        assert result.success is False
        assert "300" in result.error
        assert "stuck" in result.error.lower()

    def test_includes_output_summary(self):
        result = _check_abort_result(
            "item-1", False, 600.0, True, 600.0, last_output_summary="some progress"
        )
        assert result is not None
        assert result.last_output_summary == "some progress"

    def test_returns_failure_on_inactivity(self):
        result = _check_abort_result("item-1", True, 600.0, False, 600.0)
        assert result is not None
        assert result.success is False
        assert "600" in result.error


# ── build_gate_resume_prompt ─────────────────────────────────────────────────


class TestBuildGateResumePrompt:
    def test_basic_prompt(self, work_item):
        result = build_gate_resume_prompt(work_item)
        assert "Gate Agent Session Resume" in result
        assert work_item.id in result
        assert work_item.title in result
        assert "timed out" in result

    def test_includes_description(self, work_item):
        result = build_gate_resume_prompt(work_item)
        assert work_item.description in result

    def test_no_description_omits_section(self, work_item_no_desc):
        result = build_gate_resume_prompt(work_item_no_desc)
        assert "Description" not in result

    def test_includes_handoff_context(self, work_item):
        result = build_gate_resume_prompt(work_item, handoff_context="diff output")
        assert "Handoff Context" in result
        assert "diff output" in result

    def test_no_handoff_omits_section(self, work_item):
        result = build_gate_resume_prompt(work_item, handoff_context=None)
        assert "Handoff Context" not in result

    def test_includes_previous_output(self, work_item):
        result = build_gate_resume_prompt(
            work_item, previous_output_summary="Running tests..."
        )
        assert "Previous Progress" in result
        assert "Running tests..." in result

    def test_no_previous_output_omits_section(self, work_item):
        result = build_gate_resume_prompt(work_item, previous_output_summary=None)
        assert "Previous Progress" not in result

    def test_custom_default_branch(self, work_item):
        result = build_gate_resume_prompt(work_item, default_branch="main")
        assert "`main`" in result

    def test_json_verdict_format_present(self, work_item):
        result = build_gate_resume_prompt(work_item)
        assert "status" in result
        assert "success" in result
        assert "failure" in result

    def test_full_prompt_with_all_options(self, work_item):
        result = build_gate_resume_prompt(
            work_item,
            handoff_context="context here",
            previous_output_summary="output here",
            default_branch="develop",
        )
        assert "Handoff Context" in result
        assert "Previous Progress" in result
        assert "`develop`" in result
        assert work_item.description in result


# ── build_resume_prompt ──────────────────────────────────────────────────────


class TestBuildResumePrompt:
    def test_basic_prompt(self, work_item):
        result = build_resume_prompt(work_item)
        assert "Session Resume" in result
        assert work_item.id in result
        assert work_item.title in result
        assert "timed out" in result

    def test_includes_description(self, work_item):
        result = build_resume_prompt(work_item)
        assert work_item.description in result

    def test_no_description_omits_section(self, work_item_no_desc):
        result = build_resume_prompt(work_item_no_desc)
        assert "**Description:**" not in result

    def test_includes_previous_output(self, work_item):
        result = build_resume_prompt(
            work_item, previous_output_summary="Edited files"
        )
        assert "Previous Progress" in result
        assert "Edited files" in result

    def test_no_output_omits_section(self, work_item):
        result = build_resume_prompt(work_item, previous_output_summary=None)
        assert "Previous Progress" not in result

    def test_includes_retry_feedback(self, work_item):
        feedback = ["Tests failed", "Missing coverage"]
        result = build_resume_prompt(work_item, retry_feedback=feedback)
        assert "Feedback from Previous Attempts" in result
        assert "Tests failed" in result
        assert "Missing coverage" in result

    def test_no_feedback_omits_section(self, work_item):
        result = build_resume_prompt(work_item, retry_feedback=None)
        assert "Feedback from Previous Attempts" not in result

    def test_success_criteria_present(self, work_item):
        result = build_resume_prompt(work_item)
        assert "Success Criteria" in result
        assert "fully implemented" in result

    def test_full_prompt_all_sections(self, work_item):
        result = build_resume_prompt(
            work_item,
            previous_output_summary="output summary",
            retry_feedback=["fix lint"],
        )
        assert work_item.description in result
        assert "output summary" in result
        assert "fix lint" in result
        assert "Success Criteria" in result


# ── _check_tool_watchdog ─────────────────────────────────────────────────────


class TestCheckToolWatchdog:
    @pytest.mark.asyncio
    async def test_returns_none_when_no_stats(self):
        session = AsyncMock()
        result = await _check_tool_watchdog(session, None, 600.0)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_timeout_zero(self):
        session = AsyncMock()
        stats = {"tool_start_times": {"t1": time.monotonic()}}
        result = await _check_tool_watchdog(session, stats, 0)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_no_tool_times(self):
        session = AsyncMock()
        stats = {"tool_start_times": {}}
        result = await _check_tool_watchdog(session, stats, 600.0)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_tools_within_limit(self):
        session = AsyncMock()
        stats = {"tool_start_times": {"t1": time.monotonic()}}
        result = await _check_tool_watchdog(session, stats, 600.0)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_tool_timeout_when_exceeded(self):
        session = AsyncMock()
        stats = {"tool_start_times": {"t1": time.monotonic() - 700}}
        result = await _check_tool_watchdog(session, stats, 600.0)
        assert result == "tool_timeout"
        session.abort.assert_called_once()

    @pytest.mark.asyncio
    async def test_abort_failure_still_returns_timeout(self):
        session = AsyncMock()
        session.abort.side_effect = Exception("abort failed")
        stats = {"tool_start_times": {"t1": time.monotonic() - 700}}
        result = await _check_tool_watchdog(session, stats, 600.0)
        assert result == "tool_timeout"


# ── _build_token_usage_callback ──────────────────────────────────────────────


class TestBuildTokenUsageCallback:
    @patch("pokepoke.models.sdk_helpers.terminal_ui")
    def test_callback_pushes_tokens_when_agent_id_set(self, mock_ui):
        cb = _build_token_usage_callback()
        with patch(
            "pokepoke.desktop.desktop_ui._thread_output"
        ) as mock_thread:
            mock_thread.agent_id = "agent-1"
            cb(100, 50)
            mock_ui.ui.push_agent_tokens.assert_called_once_with("agent-1", 100, 50)

    @patch("pokepoke.models.sdk_helpers.terminal_ui")
    def test_callback_noop_when_no_agent_id(self, mock_ui):
        cb = _build_token_usage_callback()
        with patch(
            "pokepoke.desktop.desktop_ui._thread_output"
        ) as mock_thread:
            mock_thread.agent_id = None
            cb(100, 50)
            mock_ui.ui.push_agent_tokens.assert_not_called()
