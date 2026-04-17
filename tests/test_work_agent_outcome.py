"""Tests for pokepoke.work_agent_outcome module.

Covers WorkAgentOutcome dataclass validation, parse_work_agent_outcome()
JSON extraction from agent output, and the _str_list() coercion helper.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from pokepoke.work_agent_outcome import (
    WORK_AGENT_OUTCOME_STATUSES,
    WorkAgentOutcome,
    _str_list,
    parse_work_agent_outcome,
)

# ---------------------------------------------------------------------------
# WorkAgentOutcome dataclass tests
# ---------------------------------------------------------------------------

class TestWorkAgentOutcome:
    """Tests for the WorkAgentOutcome dataclass."""

    @pytest.mark.parametrize("status", sorted(WORK_AGENT_OUTCOME_STATUSES))
    def test_valid_statuses(self, status: str) -> None:
        outcome = WorkAgentOutcome(status=status)
        assert outcome.status == status

    def test_defaults(self) -> None:
        outcome = WorkAgentOutcome(status="completed")
        assert outcome.reason == ""
        assert outcome.files_modified == []
        assert outcome.tests_added == []
        assert outcome.suggested_split == []

    def test_custom_fields(self) -> None:
        outcome = WorkAgentOutcome(
            status="blocked",
            reason="dependency missing",
            files_modified=["src/a.py"],
            tests_added=["tests/test_a.py"],
            suggested_split=["part1", "part2"],
        )
        assert outcome.reason == "dependency missing"
        assert outcome.files_modified == ["src/a.py"]
        assert outcome.tests_added == ["tests/test_a.py"]
        assert outcome.suggested_split == ["part1", "part2"]

    def test_invalid_status_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="Invalid work agent outcome status"):
            WorkAgentOutcome(status="invalid")

    def test_empty_status_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="Invalid work agent outcome status"):
            WorkAgentOutcome(status="")

    def test_status_set_is_frozenset(self) -> None:
        assert isinstance(WORK_AGENT_OUTCOME_STATUSES, frozenset)

    def test_expected_statuses_present(self) -> None:
        expected = {"completed", "blocked", "needs_clarification", "too_large"}
        assert expected == WORK_AGENT_OUTCOME_STATUSES


# ---------------------------------------------------------------------------
# parse_work_agent_outcome() tests
# ---------------------------------------------------------------------------

class TestParseWorkAgentOutcome:
    """Tests for parsing structured outcomes from raw agent output."""

    def test_none_input(self) -> None:
        assert parse_work_agent_outcome(None) is None

    def test_empty_string(self) -> None:
        assert parse_work_agent_outcome("") is None

    def test_no_json_blocks(self) -> None:
        assert parse_work_agent_outcome("just some plain text") is None

    def test_valid_completed_block(self) -> None:
        output = (
            'Some agent log output\n'
            '```json\n'
            '{"status": "completed", "reason": "all done", '
            '"files_modified": ["src/a.py"], "tests_added": ["tests/test_a.py"]}\n'
            '```\n'
            'More log output'
        )
        result = parse_work_agent_outcome(output)
        assert result is not None
        assert result.status == "completed"
        assert result.reason == "all done"
        assert result.files_modified == ["src/a.py"]
        assert result.tests_added == ["tests/test_a.py"]

    def test_valid_blocked_block(self) -> None:
        output = '```json\n{"status": "blocked", "reason": "missing dep"}\n```'
        result = parse_work_agent_outcome(output)
        assert result is not None
        assert result.status == "blocked"
        assert result.reason == "missing dep"

    def test_valid_needs_clarification_block(self) -> None:
        output = '```json\n{"status": "needs_clarification", "reason": "ambiguous spec"}\n```'
        result = parse_work_agent_outcome(output)
        assert result is not None
        assert result.status == "needs_clarification"

    def test_valid_too_large_block(self) -> None:
        output = '```json\n{"status": "too_large", "suggested_split": ["a", "b"]}\n```'
        result = parse_work_agent_outcome(output)
        assert result is not None
        assert result.status == "too_large"
        assert result.suggested_split == ["a", "b"]

    def test_last_valid_block_wins(self) -> None:
        output = (
            '```json\n{"status": "blocked", "reason": "first"}\n```\n'
            'middle text\n'
            '```json\n{"status": "completed", "reason": "second"}\n```\n'
        )
        result = parse_work_agent_outcome(output)
        assert result is not None
        assert result.status == "completed"
        assert result.reason == "second"

    def test_skips_non_outcome_json_blocks(self) -> None:
        output = (
            '```json\n{"some_other": "data"}\n```\n'
            '```json\n{"status": "completed", "reason": "real"}\n```\n'
        )
        result = parse_work_agent_outcome(output)
        assert result is not None
        assert result.status == "completed"

    def test_skips_invalid_status_json(self) -> None:
        output = '```json\n{"status": "unknown_status"}\n```'
        assert parse_work_agent_outcome(output) is None

    def test_skips_malformed_json(self) -> None:
        output = '```json\n{not valid json}\n```'
        assert parse_work_agent_outcome(output) is None

    def test_malformed_json_then_valid(self) -> None:
        output = (
            '```json\n{bad json}\n```\n'
            '```json\n{"status": "completed"}\n```\n'
        )
        result = parse_work_agent_outcome(output)
        assert result is not None
        assert result.status == "completed"

    def test_case_insensitive_json_fence(self) -> None:
        output = '```JSON\n{"status": "completed"}\n```'
        result = parse_work_agent_outcome(output)
        assert result is not None
        assert result.status == "completed"

    def test_mixed_case_json_fence(self) -> None:
        output = '```Json\n{"status": "blocked"}\n```'
        result = parse_work_agent_outcome(output)
        assert result is not None
        assert result.status == "blocked"

    def test_missing_optional_fields_default(self) -> None:
        output = '```json\n{"status": "completed"}\n```'
        result = parse_work_agent_outcome(output)
        assert result is not None
        assert result.reason == ""
        assert result.files_modified == []
        assert result.tests_added == []
        assert result.suggested_split == []

    def test_multiline_json(self) -> None:
        output = (
            '```json\n'
            '{\n'
            '  "status": "completed",\n'
            '  "reason": "all tests pass",\n'
            '  "files_modified": [\n'
            '    "src/main.py",\n'
            '    "src/utils.py"\n'
            '  ]\n'
            '}\n'
            '```'
        )
        result = parse_work_agent_outcome(output)
        assert result is not None
        assert result.status == "completed"
        assert result.files_modified == ["src/main.py", "src/utils.py"]

    @patch("pokepoke.work_agent_outcome.strip_process_monitor_lines", side_effect=lambda x: x)
    def test_calls_strip_process_monitor(self, mock_strip) -> None:
        output = '```json\n{"status": "completed"}\n```'
        parse_work_agent_outcome(output)
        mock_strip.assert_called()

    def test_process_monitor_noise_stripped(self) -> None:
        output = (
            '```json\n'
            '{"status": "completed",\n'
            '[ProcessMonitor] PID 1234 active\n'
            '"reason": "done"}\n'
            '```'
        )
        result = parse_work_agent_outcome(output)
        assert result is not None
        assert result.status == "completed"


# ---------------------------------------------------------------------------
# _str_list() tests
# ---------------------------------------------------------------------------

class TestStrList:
    """Tests for the _str_list helper."""

    def test_list_of_strings(self) -> None:
        assert _str_list(["a", "b", "c"]) == ["a", "b", "c"]

    def test_list_of_ints(self) -> None:
        assert _str_list([1, 2, 3]) == ["1", "2", "3"]

    def test_mixed_list(self) -> None:
        assert _str_list(["a", 1, True]) == ["a", "1", "True"]

    def test_empty_list(self) -> None:
        assert _str_list([]) == []

    def test_none_returns_empty(self) -> None:
        assert _str_list(None) == []

    def test_string_returns_empty(self) -> None:
        assert _str_list("not a list") == []

    def test_int_returns_empty(self) -> None:
        assert _str_list(42) == []

    def test_dict_returns_empty(self) -> None:
        assert _str_list({"key": "val"}) == []

    def test_bool_returns_empty(self) -> None:
        assert _str_list(True) == []
