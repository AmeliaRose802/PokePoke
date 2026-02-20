from __future__ import annotations

import threading

from pokepoke.metrics_context import agent_type_context, get_current_agent_type, set_current_agent_type


def test_agent_type_context_sets_and_restores() -> None:
    set_current_agent_type(None)
    assert get_current_agent_type() == "unknown"
    with agent_type_context("work"):
        assert get_current_agent_type() == "work"
    assert get_current_agent_type() == "unknown"


def test_agent_type_context_restores_previous_value() -> None:
    set_current_agent_type("maintenance")
    with agent_type_context("work"):
        assert get_current_agent_type() == "work"
    assert get_current_agent_type() == "maintenance"


def test_get_current_agent_type_empty_string_uses_default() -> None:
    set_current_agent_type("")
    assert get_current_agent_type(default="fallback") == "fallback"


def test_thread_local_isolated_between_threads() -> None:
    set_current_agent_type(None)
    results: list[str] = []

    def worker() -> None:
        with agent_type_context("janitor"):
            results.append(get_current_agent_type())

    t = threading.Thread(target=worker)
    t.start(); t.join()
    assert results == ["janitor"]
    assert get_current_agent_type() == "unknown"
