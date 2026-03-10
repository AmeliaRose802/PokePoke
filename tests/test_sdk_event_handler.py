"""Tests for streaming tool output handling."""

import asyncio
import json
from types import SimpleNamespace

from pokepoke.sdk_event_handler import create_event_handler
from pokepoke.sdk_beads_tracker import extract_command as _extract_command, parse_created_items as _parse_created_items, record_items_created as _record_items_created


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
    monkeypatch.setattr("pokepoke.sdk_event_handler.record_items_created", lambda items: created.extend(items))

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


def test_turn_end_with_no_pending_tools_does_not_set_done() -> None:
    """assistant.turn_end should NOT set done — only session.idle (after
    confirmation timeout) or session.end do."""
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        done = asyncio.Event()
        output_lines: list[str] = []
        errors: list[str] = []

        handler, stats = create_event_handler(done, output_lines, errors, idle_timeout=0.1)
        handler(_make_event("assistant.turn_end"))

        assert stats['turn_count'] == 1
        loop.run_until_complete(asyncio.sleep(0.3))
        assert not done.is_set(), "turn_end should not set done — wait for session.end"
    finally:
        asyncio.set_event_loop(None)
        loop.close()


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

    # Rate-limit error should set done and flag rate_limit_detected, without appending to errors
    assert done.is_set()
    assert errors == []
    assert handler.rate_limit_detected is True

    # A second session.error after reset should still work normally
    done.clear()
    handler.reset_for_retry(done, output_lines, errors)
    handler(_make_event("session.error", message="another error"))
    assert done.is_set()
    assert len(errors) == 1
    assert handler.rate_limit_detected is False


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


def test_on_token_usage_callback_invoked_on_usage_event() -> None:
    """on_token_usage callback should be called with cumulative totals."""
    done = asyncio.Event()
    output_lines: list[str] = []
    errors: list[str] = []
    usage_calls: list[tuple[int, int]] = []

    def on_usage(input_tokens: int, output_tokens: int) -> None:
        usage_calls.append((input_tokens, output_tokens))

    handler, stats = create_event_handler(
        done, output_lines, errors, on_token_usage=on_usage,
    )

    handler(_make_event("assistant.usage", input_tokens=100, output_tokens=50,
                        cache_read_tokens=0, cache_write_tokens=0))
    handler(_make_event("assistant.usage", input_tokens=200, output_tokens=100,
                        cache_read_tokens=0, cache_write_tokens=0))

    assert usage_calls == [(100, 50), (300, 150)]
    assert stats['total_input_tokens'] == 300
    assert stats['total_output_tokens'] == 150


def test_stale_idle_forces_completion_after_threshold(capsys) -> None:
    """When session.idle fires repeatedly with unchanged pending_tool_calls,
    the handler should force-set done after _MAX_STALE_IDLES (2) consecutive
    stale idles — preventing a 2-hour hang when Copilot exits mid-tool."""
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        done = asyncio.Event()
        output_lines: list[str] = []
        errors: list[str] = []

        handler, stats = create_event_handler(
            done, output_lines, errors, idle_timeout=0.1,
        )

        # Simulate a tool that started but never completed (Copilot exited)
        handler(_make_event("tool.execution_start", tool_name="powershell",
                            arguments={"command": "bd close"}, tool_call_id="t1"))
        assert stats['pending_tool_calls'] == 1
        assert not done.is_set()

        # First stale idle: should NOT force completion yet
        handler(_make_event("session.idle"))
        assert not done.is_set()

        # Second stale idle: should force completion
        handler(_make_event("session.idle"))
        assert done.is_set()
        assert stats['pending_tool_calls'] == 0

        captured = capsys.readouterr()
        assert "stale pending tool" in captured.out
        assert "forcing completion" in captured.out
    finally:
        asyncio.set_event_loop(None)
        loop.close()


def test_tool_activity_resets_stale_idle_counter(capsys) -> None:
    """A tool.execution_start or tool.execution_complete between idle events
    should reset the stale idle counter, preventing false-positive force
    completion."""
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        done = asyncio.Event()
        output_lines: list[str] = []
        errors: list[str] = []

        handler, stats = create_event_handler(
            done, output_lines, errors, idle_timeout=0.1,
        )

        # Start two tools
        handler(_make_event("tool.execution_start", tool_name="powershell",
                            arguments={}, tool_call_id="t1"))
        handler(_make_event("tool.execution_start", tool_name="view",
                            arguments={}, tool_call_id="t2"))
        assert stats['pending_tool_calls'] == 2

        # First stale idle (pending=2)
        handler(_make_event("session.idle"))
        assert not done.is_set()

        # One tool completes — resets stale counter
        handler(_make_event("tool.execution_complete", tool_name="powershell",
                            arguments={}, result=SimpleNamespace(content="ok"),
                            success=True, tool_call_id="t1"))
        assert stats['pending_tool_calls'] == 1

        # This idle is NOT stale (pending changed from 2→1), counter resets
        handler(_make_event("session.idle"))
        assert not done.is_set()

        # Second idle with pending=1 unchanged → stale counter=2, force complete
        handler(_make_event("session.idle"))
        assert done.is_set()
    finally:
        asyncio.set_event_loop(None)
        loop.close()


def test_idle_with_zero_pending_sets_done_after_confirm() -> None:
    """When pending_tool_calls is 0, session.idle should spawn a confirmation
    task that sets done after idle_timeout elapses (Feb 24 pattern)."""
    async def _run() -> None:
        done = asyncio.Event()
        output_lines: list[str] = []
        errors: list[str] = []

        handler, stats = create_event_handler(
            done, output_lines, errors, idle_timeout=0.05,
        )

        # Idle with no pending tools — spawns confirmation task, not done yet
        handler(_make_event("session.idle"))
        assert not done.is_set()

        # After idle_timeout elapses, confirmation task should set done
        await asyncio.sleep(0.15)
        assert done.is_set(), "session.idle should set done after idle_timeout confirmation"

    asyncio.run(_run())


def test_tool_start_cancels_idle_confirmation() -> None:
    """New tool activity should cancel the pending idle confirmation task,
    preventing premature completion when the agent resumes work."""
    async def _run() -> None:
        done = asyncio.Event()
        output_lines: list[str] = []
        errors: list[str] = []

        handler, stats = create_event_handler(
            done, output_lines, errors, idle_timeout=0.1,
        )

        # Trigger idle — spawns confirmation task
        handler(_make_event("session.idle"))
        assert not done.is_set()
        assert stats['idle_task'] is not None

        # New tool activity should cancel that task
        handler(_make_event("tool.execution_start", tool_name="powershell",
                            arguments={"command": "echo hi"}, tool_call_id="t1"))

        # Let the event loop process the cancellation
        await asyncio.sleep(0)
        assert stats['idle_task'].cancelled()

        # Wait past idle_timeout — done should NOT be set (task was cancelled)
        await asyncio.sleep(0.2)
        assert not done.is_set(), "tool activity should have cancelled idle confirmation"

    asyncio.run(_run())


def test_session_end_sets_done_immediately() -> None:
    """A session.end event should set done immediately — this is the
    primary signal that the agent has finished its work."""
    done = asyncio.Event()
    output_lines: list[str] = []
    errors: list[str] = []

    handler, stats = create_event_handler(done, output_lines, errors)
    assert not done.is_set()

    handler(_make_event("session.end"))
    assert done.is_set()


def test_session_end_after_tool_activity_sets_done(capsys) -> None:
    """session.end should set done even after recent tool activity."""
    done = asyncio.Event()
    output_lines: list[str] = []
    errors: list[str] = []

    handler, stats = create_event_handler(done, output_lines, errors)

    # Simulate tool activity
    handler(_make_event("tool.execution_start", tool_name="powershell",
                        arguments={"command": "echo hi"}, tool_call_id="t1"))
    handler(_make_event("tool.execution_complete", tool_name="powershell",
                        arguments={"command": "echo hi"},
                        result=SimpleNamespace(content="hi"), success=True,
                        tool_call_id="t1"))

    assert not done.is_set()
    handler(_make_event("session.end"))
    assert done.is_set()

    captured = capsys.readouterr()
    assert "session complete" in captured.out.lower()


def test_tool_activity_time_tracked_on_start_and_complete() -> None:
    """last_tool_activity_time in stats should update on both
    tool.execution_start and tool.execution_complete events."""
    done = asyncio.Event()
    output_lines: list[str] = []
    errors: list[str] = []

    handler, stats = create_event_handler(done, output_lines, errors)

    assert stats['last_tool_activity_time'] == 0.0

    handler(_make_event("tool.execution_start", tool_name="run_cmd",
                        arguments={}, tool_call_id="t1"))
    start_time = stats['last_tool_activity_time']
    assert start_time > 0

    handler(_make_event("tool.execution_complete", tool_name="run_cmd",
                        arguments={}, result=SimpleNamespace(content="ok"),
                        success=True, tool_call_id="t1"))
    assert stats['last_tool_activity_time'] >= start_time
