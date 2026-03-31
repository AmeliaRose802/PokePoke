"""Tests for sdk_event_handler_utils helpers."""

from types import SimpleNamespace
from unittest.mock import patch

from pokepoke.models.sdk_event_handler_utils import (
    iter_streaming_chunks,
    record_tool_output,
)


def test_iter_streaming_chunks_empty():
    assert iter_streaming_chunks(SimpleNamespace()) == []


def test_iter_streaming_chunks_collects_text():
    data = SimpleNamespace(stdout="ok", delta_content="delta", other="x")
    event = SimpleNamespace(data=data)
    chunks = iter_streaming_chunks(event)
    assert ("stdout", "ok") in chunks
    assert ("delta_content", "delta") in chunks


def test_record_tool_output_updates_stats():
    stats = {"last_tool_output_time": 0.0, "last_tool_output": None, "last_tool_activity_time": 0.0}
    with patch("pokepoke.models.sdk_event_handler_utils.time.monotonic", return_value=123.0):
        record_tool_output(stats, "hello")
    assert stats["last_tool_output_time"] == 123.0
    assert stats["last_tool_activity_time"] == 123.0
    assert stats["last_tool_output"] == "hello"


def test_record_tool_output_trims_long_text():
    stats = {"last_tool_output_time": 0.0, "last_tool_output": None, "last_tool_activity_time": 0.0}
    long_text = "x" * 500
    with patch("pokepoke.models.sdk_event_handler_utils.time.monotonic", return_value=5.0):
        record_tool_output(stats, long_text)
    assert stats["last_tool_output_time"] == 5.0
    assert stats["last_tool_output"].startswith("...")
    assert len(stats["last_tool_output"]) <= 403


def test_record_tool_output_ignores_empty():
    stats = {"last_tool_output_time": 1.0, "last_tool_output": "prev", "last_tool_activity_time": 1.0}
    record_tool_output(stats, "   ")
    assert stats["last_tool_output"] == "prev"
