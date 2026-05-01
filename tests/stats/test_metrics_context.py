from __future__ import annotations

import threading

from pokepoke.stats.metrics_context import (
    get_current_repo_name,
    get_current_work_item_id,
    set_current_repo_name,
    set_current_work_item_id,
    work_item_context,
)

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
