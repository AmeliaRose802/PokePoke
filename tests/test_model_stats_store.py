import json
from contextlib import contextmanager
from pathlib import Path

import pytest

from pokepoke.model_stats_store import (
    get_model_history,
    get_model_summary,
    get_model_weights,
    load_model_stats,
    record_completion,
    save_model_stats,
)
from pokepoke.types import ModelCompletionRecord


@contextmanager
def _fake_lock(*_args: object, **_kwargs: object):
    yield


def test_missing_or_corrupt_files_return_empty(tmp_path: Path) -> None:
    missing_path = tmp_path / "missing.json"
    assert load_model_stats(missing_path)["log"] == []

    corrupt_path = tmp_path / "corrupt.json"
    corrupt_path.write_text("{not-json", encoding="utf-8")
    assert load_model_stats(corrupt_path)["log"] == []


def test_record_completion_updates_summary_and_history(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    stats_path = tmp_path / "stats.json"
    monkeypatch.setattr("pokepoke.model_stats_store.acquire_lock", _fake_lock)

    record_completion(
        ModelCompletionRecord(
            item_id="A",
            model="model-a",
            duration_seconds=2.0,
            gate_passed=True,
            input_tokens=10,
            output_tokens=5,
            agent_turns=1,
            cost=0.5,
        ),
        path=stats_path,
    )
    record_completion(
        ModelCompletionRecord(
            item_id="B",
            model="model-a",
            duration_seconds=4.0,
            gate_passed=False,
            input_tokens=20,
            output_tokens=10,
            agent_turns=2,
            cost=1.0,
        ),
        path=stats_path,
    )
    record_completion(
        ModelCompletionRecord(
            item_id="C",
            model="model-b",
            duration_seconds=1.0,
            gate_passed=True,
        ),
        path=stats_path,
    )

    summary = get_model_summary(stats_path)
    assert summary["model-a"]["total_items_attempted"] == 2
    assert summary["model-a"]["total_items_succeeded"] == 1
    assert summary["model-a"]["total_items_failed"] == 1
    assert summary["model-a"]["median_duration"] == 3.0
    assert summary["model-b"]["total_items_attempted"] == 1
    assert summary["model-b"]["success_rate"] == 1.0

    history = get_model_history(stats_path, limit=2)
    assert len(history) == 2
    assert {entry["item_id"] for entry in history} == {"B", "C"}


def test_get_model_weights_uses_min_attempts(tmp_path: Path) -> None:
    data = {
        "log": [],
        "summary": {
            "cold-model": {"total_items_attempted": 1, "success_rate": 0.0},
            "hot-model": {"total_items_attempted": 5, "success_rate": 0.8},
            "failing-model": {"total_items_attempted": 5, "success_rate": 0.05},
        },
    }
    save_model_stats(data, path=tmp_path / "stats.json")

    weights = get_model_weights(tmp_path / "stats.json", min_attempts=3)

    assert weights["cold-model"] == 1.0
    assert weights["hot-model"] == 0.8
    assert weights["failing-model"] == 0.1  # floor applied


def test_save_model_stats_uses_atomic_replace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    stats_path = tmp_path / "stats.json"
    called = []

    def fake_replace(src: Path, dst: Path) -> None:
        dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
        src.unlink(missing_ok=True)
        called.append((src, dst))

    monkeypatch.setattr("pokepoke.model_stats_store.replace_with_retry", fake_replace)

    save_model_stats({"log": [], "summary": {}}, path=stats_path)

    assert called, "replace_with_retry should be used for atomic save"
    assert stats_path.exists()
    loaded = json.loads(stats_path.read_text(encoding="utf-8"))
    assert loaded["log"] == []


def test_save_model_stats_surfaces_os_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    stats_path = tmp_path / "stats.json"

    def boom(*_args: object, **_kwargs: object) -> None:
        raise PermissionError("disk full")

    monkeypatch.setattr("pokepoke.model_stats_store.replace_with_retry", boom)

    with pytest.raises(PermissionError):
        save_model_stats({"log": [], "summary": {}}, path=stats_path)
