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
