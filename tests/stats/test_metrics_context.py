from __future__ import annotations

import threading

from pokepoke.stats.metrics_context import (
    agent_type_context,
    get_current_agent_type,
    get_current_repo_name,
    get_current_work_item_id,
    repo_context,
    set_current_agent_type,
    set_current_repo_name,
    set_current_work_item_id,
    work_item_context,
)


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
    t.start()
    t.join()
    assert results == ["janitor"]
    assert get_current_agent_type() == "unknown"


# ── Repo name context tests ─────────────────────────────────────────


def test_repo_name_default_empty() -> None:
    set_current_repo_name(None)
    assert get_current_repo_name() == ""


def test_repo_name_default_custom() -> None:
    set_current_repo_name(None)
    assert get_current_repo_name(default="fallback") == "fallback"


def test_set_and_get_repo_name() -> None:
    set_current_repo_name("PokePoke")
    assert get_current_repo_name() == "PokePoke"
    set_current_repo_name(None)


def test_repo_context_sets_and_restores() -> None:
    set_current_repo_name(None)
    assert get_current_repo_name() == ""
    with repo_context("MyRepo"):
        assert get_current_repo_name() == "MyRepo"
    assert get_current_repo_name() == ""


def test_repo_context_restores_previous_value() -> None:
    set_current_repo_name("RepoA")
    with repo_context("RepoB"):
        assert get_current_repo_name() == "RepoB"
    assert get_current_repo_name() == "RepoA"
    set_current_repo_name(None)


def test_repo_context_nested() -> None:
    set_current_repo_name(None)
    with repo_context("outer"):
        assert get_current_repo_name() == "outer"
        with repo_context("inner"):
            assert get_current_repo_name() == "inner"
        assert get_current_repo_name() == "outer"
    assert get_current_repo_name() == ""


def test_repo_name_thread_local_isolated() -> None:
    set_current_repo_name(None)
    results: list[str] = []

    def worker() -> None:
        with repo_context("WorkerRepo"):
            results.append(get_current_repo_name())

    t = threading.Thread(target=worker)
    t.start()
    t.join()
    assert results == ["WorkerRepo"]
    assert get_current_repo_name() == ""


def test_repo_name_empty_string_uses_default() -> None:
    set_current_repo_name("")
    assert get_current_repo_name(default="default-repo") == "default-repo"


# ── Work-item ID context tests ──────────────────────────────────────


def test_work_item_id_default_empty() -> None:
    set_current_work_item_id(None)
    assert get_current_work_item_id() == ""


def test_work_item_id_default_custom() -> None:
    set_current_work_item_id(None)
    assert get_current_work_item_id(default="fallback") == "fallback"


def test_set_and_get_work_item_id() -> None:
    set_current_work_item_id("PokePoke-abc1")
    assert get_current_work_item_id() == "PokePoke-abc1"
    set_current_work_item_id(None)


def test_work_item_context_sets_and_restores() -> None:
    set_current_work_item_id(None)
    assert get_current_work_item_id() == ""
    with work_item_context("item-42"):
        assert get_current_work_item_id() == "item-42"
    assert get_current_work_item_id() == ""


def test_work_item_context_restores_previous_value() -> None:
    set_current_work_item_id("item-A")
    with work_item_context("item-B"):
        assert get_current_work_item_id() == "item-B"
    assert get_current_work_item_id() == "item-A"
    set_current_work_item_id(None)


def test_work_item_context_nested() -> None:
    set_current_work_item_id(None)
    with work_item_context("outer"):
        assert get_current_work_item_id() == "outer"
        with work_item_context("inner"):
            assert get_current_work_item_id() == "inner"
        assert get_current_work_item_id() == "outer"
    assert get_current_work_item_id() == ""


def test_work_item_id_thread_local_isolated() -> None:
    set_current_work_item_id(None)
    results: list[str] = []

    def worker() -> None:
        with work_item_context("worker-item"):
            results.append(get_current_work_item_id())

    t = threading.Thread(target=worker)
    t.start()
    t.join()
    assert results == ["worker-item"]
    assert get_current_work_item_id() == ""


def test_work_item_id_empty_string_uses_default() -> None:
    set_current_work_item_id("")
    assert get_current_work_item_id(default="default-id") == "default-id"
