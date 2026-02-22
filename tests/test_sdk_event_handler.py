"""Tests for streaming tool output handling."""

import asyncio
import json
from types import SimpleNamespace

from pokepoke.sdk_event_handler import create_event_handler, _extract_command, _parse_created_items, _record_items_created


class DummyLogger:
    def __init__(self) -> None:
        self.chunks: list[str] = []

    def log_copilot_output(self, text: str) -> None:
        self.chunks.append(text)


def _make_event(event_type: str, **data_fields: object) -> SimpleNamespace:
    return SimpleNamespace(
        type=SimpleNamespace(value=event_type),
        data=SimpleNamespace(**data_fields) if data_fields else None,
    )


def test_tool_output_streams_are_logged_incrementally(capsys) -> None:
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        done = asyncio.Event()
        output_lines: list[str] = []
        errors: list[str] = []
        logger = DummyLogger()

        handler, _ = create_event_handler(
            done,
            output_lines,
            errors,
            item_logger=logger,
            idle_timeout=0.1,
        )

        handler(_make_event("tool.output", stdout="line one\n"))
        handler(_make_event("tool.output", stderr="line two"))

        captured = capsys.readouterr()
        assert "line one" in captured.out
        assert "line two" in captured.out
        assert output_lines == ["line one\n", "line two"]
        assert logger.chunks == ["line one\n", "line two"]
        assert errors == []
    finally:
        asyncio.set_event_loop(None)
        loop.close()


def test_extract_command_prefers_command_key() -> None:
    assert _extract_command({"command": "bd create"}) == "bd create"
    assert _extract_command({"other": 123}).startswith("{")


def test_parse_created_items_from_json_dict() -> None:
    content = json.dumps({"id": "PokePoke-123", "title": "Hello"})
    assert _parse_created_items(content) == [("PokePoke-123", "Hello")]


def test_parse_created_items_from_json_list() -> None:
    content = json.dumps([
        {"id": "PokePoke-1", "title": "One"},
        {"id": "PokePoke-2", "title": "Two"},
    ])
    assert _parse_created_items(content) == [("PokePoke-1", "One"), ("PokePoke-2", "Two")]


def test_parse_created_items_falls_back_to_regex() -> None:
    assert _parse_created_items("created PokePoke-9f06 and PokePoke-aaaa") == [("PokePoke-9f06", ""), ("PokePoke-aaaa", "")]


def test_record_items_created_updates_session_stats_and_store(monkeypatch) -> None:
    class DummyStats:
        def __init__(self) -> None:
            self.created: list[object] = []
            self.lifetime: tuple[int, int] | None = None

        def record_created_item(self, item: object) -> None:
            self.created.append(item)

        def set_lifetime_beads_item_totals(self, created: int, completed: int) -> None:
            self.lifetime = (created, completed)

    dummy = DummyStats()
    recorded: list[tuple[str, str]] = []

    def fake_record_item_created(*, item_id: str, agent_type: str) -> dict[str, int]:
        recorded.append((item_id, agent_type))
        return {"total_created": len(recorded), "total_completed": 0}

    monkeypatch.setattr("pokepoke.session_stats_registry.get_current_session_stats", lambda: dummy)
    monkeypatch.setattr("pokepoke.metrics_context.get_current_agent_type", lambda default="unknown": "janitor")
    monkeypatch.setattr("pokepoke.beads_item_stats_store.record_item_created", fake_record_item_created)

    _record_items_created([("PokePoke-1", ""), ("PokePoke-2", "Two")])

    assert recorded == [("PokePoke-1", "janitor"), ("PokePoke-2", "janitor")]
    assert len(dummy.created) == 2
    assert dummy.lifetime == (2, 0)


def test_beads_create_detected_from_powershell_tool(monkeypatch) -> None:
    done = asyncio.Event()
    output_lines: list[str] = []
    errors: list[str] = []

    created: list[tuple[str, str]] = []
    monkeypatch.setattr("pokepoke.sdk_event_handler._record_items_created", lambda items: created.extend(items))

    handler, _ = create_event_handler(done, output_lines, errors)
    handler(_make_event(
        "tool.execution_complete",
        tool_name="powershell",
        arguments={"command": "bd create something --json"},
        result=SimpleNamespace(content=json.dumps({"id": "PokePoke-99", "title": "T"})),
        success=True,
    ))

    assert created == [("PokePoke-99", "T")]


def test_streamed_deltas_not_duplicated_by_message(capsys) -> None:
    """Content already streamed via message_delta must not be re-logged by
    the subsequent assistant.message event."""
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        done = asyncio.Event()
        output_lines: list[str] = []
        errors: list[str] = []
        logger = DummyLogger()

        handler, _ = create_event_handler(
            done, output_lines, errors, item_logger=logger, idle_timeout=0.1,
        )

        # Simulate streaming: two delta chunks followed by the full message
        handler(_make_event("assistant.message_delta", delta_content="Hello "))
        handler(_make_event("assistant.message_delta", delta_content="world"))
        handler(_make_event("assistant.message", content="Hello world"))

        # Deltas should have been logged, but the full message should NOT
        assert logger.chunks == ["Hello ", "world"]
        assert output_lines == ["Hello ", "world"]
    finally:
        asyncio.set_event_loop(None)
        loop.close()


def test_non_streamed_message_still_logged(capsys) -> None:
    """When no message_delta events precede assistant.message, it must still
    be logged (non-streaming path)."""
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        done = asyncio.Event()
        output_lines: list[str] = []
        errors: list[str] = []
        logger = DummyLogger()

        handler, _ = create_event_handler(
            done, output_lines, errors, item_logger=logger, idle_timeout=0.1,
        )

        handler(_make_event("assistant.message", content="No streaming"))

        assert logger.chunks == ["No streaming"]
        assert output_lines == ["No streaming"]
    finally:
        asyncio.set_event_loop(None)
        loop.close()


def test_extract_command_non_dict() -> None:
    assert _extract_command("raw string") == "raw string"
    assert _extract_command({"no_command": 1}) == str({"no_command": 1})


def test_parse_created_items_empty() -> None:
    assert _parse_created_items("") == []
    assert _parse_created_items(None) == []  # type: ignore[arg-type]


def test_parse_created_items_list_with_non_dict_entries() -> None:
    content = json.dumps([None, {"id": "PokePoke-ok", "title": "T"}, "skip"])
    assert _parse_created_items(content) == [("PokePoke-ok", "T")]


def test_parse_created_items_json_list_no_valid_ids() -> None:
    content = json.dumps([{"title": "no id here"}])
    # Falls through to regex scan when JSON list has no valid ids
    result = _parse_created_items(content)
    assert result == []


def test_parse_created_items_fallback_regex() -> None:
    # Non-JSON content → fallback regex
    result = _parse_created_items("not json but PokePoke-abc123 was created")
    assert result == [("PokePoke-abc123", "")]


def test_assistant_usage_updates_stats() -> None:
    done = asyncio.Event()
    output_lines: list[str] = []
    errors: list[str] = []

    handler, stats = create_event_handler(done, output_lines, errors)
    handler(_make_event("assistant.usage", input_tokens=100, output_tokens=50,
                        cache_read_tokens=10, cache_write_tokens=5))

    assert stats['total_input_tokens'] == 100
    assert stats['total_output_tokens'] == 50
    assert stats['total_cache_read_tokens'] == 10
    assert stats['total_cache_write_tokens'] == 5


def test_assistant_turn_end_increments_count() -> None:
    done = asyncio.Event()
    output_lines: list[str] = []
    errors: list[str] = []

    handler, stats = create_event_handler(done, output_lines, errors)
    handler(_make_event("assistant.turn_end"))
    handler(_make_event("assistant.turn_end"))

    assert stats['turn_count'] == 2


def test_session_error_sets_done_and_records_error() -> None:
    done = asyncio.Event()
    output_lines: list[str] = []
    errors: list[str] = []

    handler, _ = create_event_handler(done, output_lines, errors)
    handler(_make_event("session.error", message="Something went wrong"))

    assert done.is_set()
    assert "Something went wrong" in errors


def test_session_error_rate_limit_triggers_fallback(capsys) -> None:
    done = asyncio.Event()
    output_lines: list[str] = []
    errors: list[str] = []

    handler, stats = create_event_handler(done, output_lines, errors)
    handler(_make_event("session.error", message="rate limit exceeded"))

    # First rate-limit error should set fallback flag and NOT set done
    assert not done.is_set()
    assert errors == []
    assert stats['tried_fallback'] is True

    # A second session.error should now set done
    handler(_make_event("session.error", message="another error"))
    assert done.is_set()
    assert len(errors) == 1


def test_tool_execution_start_tracks_stats() -> None:
    done = asyncio.Event()
    output_lines: list[str] = []
    errors: list[str] = []

    handler, stats = create_event_handler(done, output_lines, errors)
    handler(_make_event("tool.execution_start", tool_name="run_cmd", arguments={"command": "ls"}, tool_call_id="1"))

    assert stats['total_tool_calls'] == 1
    assert stats['pending_tool_calls'] == 1


def test_tool_execution_complete_decrements_pending() -> None:
    done = asyncio.Event()
    output_lines: list[str] = []
    errors: list[str] = []

    handler, stats = create_event_handler(done, output_lines, errors)
    handler(_make_event("tool.execution_start", tool_name="run_cmd", arguments={}, tool_call_id="t1"))
    handler(_make_event("tool.execution_complete", tool_name="run_cmd", arguments={},
                        result=SimpleNamespace(content="ok"), success=True, tool_call_id="t1"))

    assert stats['pending_tool_calls'] == 0


def test_delta_tracking_resets_between_turns() -> None:
    """After an assistant.message, received_deltas resets so the next
    turn can still log non-streamed content."""
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        done = asyncio.Event()
        output_lines: list[str] = []
        errors: list[str] = []
        logger = DummyLogger()

        handler, _ = create_event_handler(
            done, output_lines, errors, item_logger=logger, idle_timeout=0.1,
        )

        # Turn 1: streamed, so message should be suppressed
        handler(_make_event("assistant.message_delta", delta_content="streamed"))
        handler(_make_event("assistant.message", content="streamed"))

        # Turn 2: NOT streamed, so message should be logged
        handler(_make_event("assistant.message", content="second turn"))

        assert "second turn" in output_lines
        assert logger.chunks.count("second turn") == 1
    finally:
        asyncio.set_event_loop(None)
        loop.close()
