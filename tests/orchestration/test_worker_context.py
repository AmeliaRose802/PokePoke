"""Tests for pokepoke.orchestration.worker_context."""

import json
from typing import Any
from unittest.mock import patch

from pokepoke.orchestration.worker_context import (
    _MAX_CONTEXT_IN_PROMPT,
    WORKER_CONTEXT_TAG,
    format_worker_context_for_prompt,
    get_worker_contexts,
    save_worker_context,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_comment(text: str) -> dict[str, str]:
    return {"text": text, "author": "agent", "created_at": "2025-01-01T00:00:00Z"}


def _make_context_comment(ctx: dict[str, Any]) -> dict[str, str]:
    return _make_comment(f"{WORKER_CONTEXT_TAG} {json.dumps(ctx)}")


# ---------------------------------------------------------------------------
# save_worker_context
# ---------------------------------------------------------------------------

class TestSaveWorkerContext:
    def test_saves_basic_context(self) -> None:
        saved: list[tuple[str, str]] = []
        def fake_add(item_id: str, comment: str) -> bool:
            saved.append((item_id, comment))
            return True

        result = save_worker_context(
            "item-1",
            attempt_number=2,
            failure_reason="timeout after 300s",
            add_comment_fn=fake_add,
        )
        assert result is True
        assert len(saved) == 1
        item_id, comment = saved[0]
        assert item_id == "item-1"
        assert comment.startswith(WORKER_CONTEXT_TAG)
        payload = json.loads(comment[len(WORKER_CONTEXT_TAG):].strip())
        assert payload["attempt"] == 2
        assert payload["failure_reason"] == "timeout after 300s"

    def test_includes_gate_feedback(self) -> None:
        saved: list[tuple[str, str]] = []
        def fake_add(item_id: str, comment: str) -> bool:
            saved.append((item_id, comment))
            return True

        save_worker_context(
            "item-1",
            attempt_number=1,
            failure_reason="gate rejected",
            gate_feedback=["Missing tests", "Bad formatting"],
            add_comment_fn=fake_add,
        )
        payload = json.loads(saved[0][1][len(WORKER_CONTEXT_TAG):].strip())
        assert payload["gate_feedback"] == ["Missing tests", "Bad formatting"]

    def test_includes_files_modified(self) -> None:
        saved: list[tuple[str, str]] = []
        def fake_add(item_id: str, comment: str) -> bool:
            saved.append((item_id, comment))
            return True

        save_worker_context(
            "item-1",
            attempt_number=1,
            failure_reason="crash",
            files_modified=["src/foo.py", "tests/test_foo.py"],
            add_comment_fn=fake_add,
        )
        payload = json.loads(saved[0][1][len(WORKER_CONTEXT_TAG):].strip())
        assert payload["files_modified"] == ["src/foo.py", "tests/test_foo.py"]

    def test_includes_error_summary(self) -> None:
        saved: list[tuple[str, str]] = []
        def fake_add(item_id: str, comment: str) -> bool:
            saved.append((item_id, comment))
            return True

        save_worker_context(
            "item-1",
            attempt_number=3,
            failure_reason="timeout",
            error_summary="Process died with exit code 1",
            add_comment_fn=fake_add,
        )
        payload = json.loads(saved[0][1][len(WORKER_CONTEXT_TAG):].strip())
        assert payload["error_summary"] == "Process died with exit code 1"

    def test_truncates_long_fields(self) -> None:
        saved: list[tuple[str, str]] = []
        def fake_add(item_id: str, comment: str) -> bool:
            saved.append((item_id, comment))
            return True

        save_worker_context(
            "item-1",
            attempt_number=1,
            failure_reason="x" * 1000,
            gate_feedback=["y" * 1000],
            error_summary="z" * 1000,
            add_comment_fn=fake_add,
        )
        payload = json.loads(saved[0][1][len(WORKER_CONTEXT_TAG):].strip())
        assert len(payload["failure_reason"]) <= 500
        assert len(payload["gate_feedback"][0]) <= 300
        assert len(payload["error_summary"]) <= 500

    def test_returns_false_on_add_failure(self) -> None:
        def failing_add(_id: str, _msg: str) -> bool:
            return False

        result = save_worker_context(
            "item-1",
            attempt_number=1,
            failure_reason="fail",
            add_comment_fn=failing_add,
        )
        assert result is False

    def test_keeps_only_last_3_gate_feedback(self) -> None:
        saved: list[tuple[str, str]] = []
        def fake_add(item_id: str, comment: str) -> bool:
            saved.append((item_id, comment))
            return True

        save_worker_context(
            "item-1",
            attempt_number=1,
            failure_reason="test",
            gate_feedback=["fb1", "fb2", "fb3", "fb4", "fb5"],
            add_comment_fn=fake_add,
        )
        payload = json.loads(saved[0][1][len(WORKER_CONTEXT_TAG):].strip())
        assert len(payload["gate_feedback"]) == 3
        assert payload["gate_feedback"] == ["fb3", "fb4", "fb5"]

    def test_uses_default_add_comment(self) -> None:
        with patch("pokepoke.beads.beads_management.add_comment", return_value=True) as mock:
            result = save_worker_context(
                "item-1",
                attempt_number=1,
                failure_reason="test",
            )
        assert result is True
        mock.assert_called_once()


# ---------------------------------------------------------------------------
# get_worker_contexts
# ---------------------------------------------------------------------------

class TestGetWorkerContexts:
    def test_returns_empty_for_no_comments(self) -> None:
        result = get_worker_contexts("item-1", get_comments_fn=lambda _id: [])
        assert result == []

    def test_returns_empty_for_no_context_comments(self) -> None:
        comments = [
            _make_comment("Regular comment"),
            _make_comment("❌ Agent failure: timeout"),
        ]
        result = get_worker_contexts("item-1", get_comments_fn=lambda _id: comments)
        assert result == []

    def test_parses_valid_context_comments(self) -> None:
        ctx = {"attempt": 1, "failure_reason": "timeout"}
        comments = [_make_context_comment(ctx)]
        result = get_worker_contexts("item-1", get_comments_fn=lambda _id: comments)
        assert len(result) == 1
        assert result[0]["attempt"] == 1
        assert result[0]["failure_reason"] == "timeout"

    def test_skips_malformed_json(self) -> None:
        comments = [
            _make_comment(f"{WORKER_CONTEXT_TAG} {{not valid json"),
            _make_context_comment({"attempt": 2, "failure_reason": "crash"}),
        ]
        result = get_worker_contexts("item-1", get_comments_fn=lambda _id: comments)
        assert len(result) == 1
        assert result[0]["attempt"] == 2

    def test_skips_non_dict_json(self) -> None:
        comments = [
            _make_comment(f"{WORKER_CONTEXT_TAG} [1, 2, 3]"),
            _make_context_comment({"attempt": 1, "failure_reason": "ok"}),
        ]
        result = get_worker_contexts("item-1", get_comments_fn=lambda _id: comments)
        assert len(result) == 1

    def test_caps_at_max_contexts(self) -> None:
        comments = [
            _make_context_comment({"attempt": i, "failure_reason": f"fail-{i}"})
            for i in range(10)
        ]
        result = get_worker_contexts("item-1", get_comments_fn=lambda _id: comments)
        assert len(result) == _MAX_CONTEXT_IN_PROMPT
        assert result[0]["attempt"] == 7  # Last 3 of 0..9

    def test_mixed_comments_filters_correctly(self) -> None:
        comments = [
            _make_comment("Gate Agent Rejection: missing coverage"),
            _make_context_comment({"attempt": 1, "failure_reason": "timeout"}),
            _make_comment("❌ Agent failure: crash"),
            _make_context_comment({"attempt": 2, "failure_reason": "gate rejected"}),
        ]
        result = get_worker_contexts("item-1", get_comments_fn=lambda _id: comments)
        assert len(result) == 2
        assert result[0]["attempt"] == 1
        assert result[1]["attempt"] == 2

    def test_handles_body_key_fallback(self) -> None:
        """Some comment formats use 'body' instead of 'text'."""
        ctx = {"attempt": 1, "failure_reason": "timeout"}
        comments = [{"body": f"{WORKER_CONTEXT_TAG} {json.dumps(ctx)}"}]
        result = get_worker_contexts("item-1", get_comments_fn=lambda _id: comments)
        assert len(result) == 1

    def test_uses_default_get_comments(self) -> None:
        with patch("pokepoke.beads.beads_query.get_item_comments", return_value=[]) as mock:
            result = get_worker_contexts("item-1")
        assert result == []
        mock.assert_called_once_with("item-1")


# ---------------------------------------------------------------------------
# format_worker_context_for_prompt
# ---------------------------------------------------------------------------

class TestFormatWorkerContextForPrompt:
    def test_returns_none_for_empty(self) -> None:
        assert format_worker_context_for_prompt([]) is None

    def test_formats_single_context(self) -> None:
        ctx = [{"attempt": 1, "failure_reason": "timeout after 300s"}]
        result = format_worker_context_for_prompt(ctx)
        assert result is not None
        assert "Attempt 1" in result
        assert "timeout after 300s" in result

    def test_formats_gate_feedback(self) -> None:
        ctx = [{
            "attempt": 2,
            "failure_reason": "gate rejected",
            "gate_feedback": ["Missing test coverage", "Unused import"],
        }]
        result = format_worker_context_for_prompt(ctx)
        assert result is not None
        assert "Missing test coverage" in result
        assert "Unused import" in result
        assert "Gate feedback" in result

    def test_formats_files_modified(self) -> None:
        ctx = [{
            "attempt": 1,
            "failure_reason": "crash",
            "files_modified": ["src/a.py", "src/b.py"],
        }]
        result = format_worker_context_for_prompt(ctx)
        assert result is not None
        assert "src/a.py" in result
        assert "src/b.py" in result

    def test_formats_error_summary(self) -> None:
        ctx = [{"attempt": 1, "failure_reason": "crash", "error_summary": "exit code 1"}]
        result = format_worker_context_for_prompt(ctx)
        assert result is not None
        assert "exit code 1" in result

    def test_formats_multiple_contexts(self) -> None:
        contexts = [
            {"attempt": 1, "failure_reason": "timeout"},
            {"attempt": 2, "failure_reason": "gate rejected"},
        ]
        result = format_worker_context_for_prompt(contexts)
        assert result is not None
        assert "Attempt 1" in result
        assert "Attempt 2" in result
        assert "timeout" in result
        assert "gate rejected" in result

    def test_handles_missing_fields_gracefully(self) -> None:
        ctx = [{"attempt": 1}]
        result = format_worker_context_for_prompt(ctx)
        assert result is not None
        assert "Attempt 1" in result

    def test_handles_unknown_attempt_gracefully(self) -> None:
        ctx = [{"failure_reason": "unknown"}]
        result = format_worker_context_for_prompt(ctx)
        assert result is not None
        assert "Attempt ?" in result
