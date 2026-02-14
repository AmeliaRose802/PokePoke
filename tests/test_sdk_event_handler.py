"""Tests for sdk_event_handler module."""

import asyncio
import types
from typing import List

import pytest

from src.pokepoke import sdk_event_handler


class DummyLogger:
    def __init__(self) -> None:
        self.lines: List[str] = []

    def log_copilot_output(self, text: str) -> None:
        self.lines.append(text)


class DummyEventFlag:
    def __init__(self) -> None:
        self.is_set = False

    def set(self) -> None:
        self.is_set = True


@pytest.fixture(autouse=True)
def stub_terminal_ui(monkeypatch: pytest.MonkeyPatch) -> None:
    """Prevent real terminal styling during tests."""
    monkeypatch.setattr(
        sdk_event_handler.terminal_ui,
        "ui",
        types.SimpleNamespace(set_style=lambda *_: None)
    )


def make_event(event_type: str, **payload) -> object:
    event = types.SimpleNamespace()
    event.type = types.SimpleNamespace(value=event_type)
    for key, value in payload.items():
        setattr(event, key, value)
    return event


def make_data(**values) -> object:
    return types.SimpleNamespace(**values)


def test_message_delta_logs_output(monkeypatch: pytest.MonkeyPatch) -> None:
    done = DummyEventFlag()
    output: List[str] = []
    errors: List[str] = []
    logger = DummyLogger()
    handler, stats = sdk_event_handler.create_event_handler(done, output, errors, logger)
    event = make_event("assistant.message_delta", data=make_data(delta_content="hello "))

    needs_retry = handler(event)

    assert needs_retry is False
    assert output == ["hello "]
    assert logger.lines == ["hello "]
    assert stats['turn_count'] == 0


def test_message_event_logs_full_content() -> None:
    done = DummyEventFlag()
    output: List[str] = []
    errors: List[str] = []
    logger = DummyLogger()
    handler, _ = sdk_event_handler.create_event_handler(done, output, errors, logger)
    event = make_event("assistant.message", data=make_data(content="final chunk"))

    handler(event)

    assert output == ["final chunk"]
    assert logger.lines == ["final chunk"]


def test_message_complete_reschedules_idle_task(monkeypatch: pytest.MonkeyPatch) -> None:
    done = DummyEventFlag()
    output: List[str] = []
    errors: List[str] = []
    handler, stats = sdk_event_handler.create_event_handler(done, output, errors)

    class DummyTask:
        def __init__(self) -> None:
            self.cancel_called = False

        def cancel(self) -> None:
            self.cancel_called = True

    created_tasks: List[DummyTask] = []

    def fake_create_task(coro):
        task = DummyTask()
        created_tasks.append(task)
        coro.close()
        return task

    monkeypatch.setattr(sdk_event_handler.asyncio, "create_task", fake_create_task)

    handler(make_event("assistant.message_complete"))
    assert stats['idle_task'] is created_tasks[0]

    handler(make_event("assistant.message_complete"))
    assert created_tasks[0].cancel_called is True
    assert stats['idle_task'] is created_tasks[1]


def test_idle_task_completes_without_pending_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    done = DummyEventFlag()
    handler, stats = sdk_event_handler.create_event_handler(done, [], [])

    class ImmediateTask:
        def __init__(self, coro):
            self.cancel_called = False
            asyncio.run(coro)

        def cancel(self) -> None:
            self.cancel_called = True

    async def immediate_sleep(_: float) -> None:
        return None

    monkeypatch.setattr(sdk_event_handler.asyncio, "sleep", immediate_sleep)
    monkeypatch.setattr(sdk_event_handler.asyncio, "create_task", lambda coro: ImmediateTask(coro))

    handler(make_event("assistant.message_complete"))

    assert done.is_set is True
    assert isinstance(stats['idle_task'], ImmediateTask)


def test_rate_limit_error_requests_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    done = DummyEventFlag()
    handler, stats = sdk_event_handler.create_event_handler(done, [], [], None)

    retry = handler(make_event("assistant.error", data=make_data(error="Rate limit exceeded")))
    assert retry is True

    # Second error completes the session
    retry_second = handler(make_event("assistant.error", data=make_data(error="Other failure")))
    assert retry_second is False
    assert done.is_set is True
    assert stats['tried_fallback'] is False  # Not flipped inside handler


def test_tool_call_tracking_and_usage_updates(monkeypatch: pytest.MonkeyPatch) -> None:
    done = DummyEventFlag()
    handler, stats = sdk_event_handler.create_event_handler(done, [], [])

    handler(make_event("assistant.tool_calls"))
    handler(make_event("assistant.tool_calls"))
    assert stats['pending_tool_calls'] == 2
    assert stats['total_tool_calls'] == 2

    handler(make_event("assistant.tool_execution_complete"))
    assert stats['pending_tool_calls'] == 1

    usage_event = make_event(
        "assistant.usage",
        data=make_data(
            input_tokens=5,
            output_tokens=3,
            cache_read_tokens=2,
            cache_write_tokens=1
        )
    )
    handler(usage_event)
    assert stats['total_input_tokens'] == 5
    assert stats['total_output_tokens'] == 3
    assert stats['total_cache_read_tokens'] == 2
    assert stats['total_cache_write_tokens'] == 1
    assert stats['turn_count'] == 1
