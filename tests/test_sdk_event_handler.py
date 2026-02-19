"""Tests for streaming tool output handling."""

import asyncio
from types import SimpleNamespace

from pokepoke.sdk_event_handler import create_event_handler


class DummyLogger:
    def __init__(self) -> None:
        self.chunks: list[str] = []

    def log_copilot_output(self, text: str) -> None:
        self.chunks.append(text)


def _make_event(event_type: str, **data_fields: str) -> SimpleNamespace:
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
