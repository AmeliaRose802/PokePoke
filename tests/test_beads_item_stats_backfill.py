import subprocess
from pathlib import Path

import pytest

from pokepoke import beads_item_stats_backfill as backfill
from pokepoke.beads_item_stats_store import load_beads_item_stats, save_beads_item_stats


def test_backfill_adds_missing_created_events(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    stats_path = tmp_path / "stats.json"
    initial_log = [
        {"event": "created", "item_id": "existing-created", "agent_type": "work", "timestamp": "2026-01-01T00:00:00Z"},
        {"event": "completed", "item_id": "completed-only", "agent_type": "work", "timestamp": "2026-01-02T00:00:00Z"},
    ]
    save_beads_item_stats({"log": initial_log, "summary": {}}, stats_path)

    monkeypatch.setattr(
        backfill,
        "_get_all_beads_items",
        lambda: [{"id": "from-db-1", "created_at": "2026-01-03T00:00:00Z", "created_by": "Amelia"}],
    )

    result = backfill.backfill_from_beads_db(stats_path=stats_path, silent=True)

    assert result["backfilled"] == 2
    stats = load_beads_item_stats(stats_path)
    created_events = [e for e in stats["log"] if e["event"] == "created"]
    assert {e["item_id"] for e in created_events} == {"existing-created", "from-db-1", "completed-only"}
    by_agent = stats["summary"]["by_agent_type"]
    assert by_agent["human"]["created"] == 1  # derived from created_by
    assert by_agent["work"]["created"] == 2
    assert stats["summary"]["total_created"] == 3
    assert stats["summary"]["total_completed"] == 1


def test_backfill_is_idempotent_when_all_items_covered(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    stats_path = tmp_path / "stats.json"
    initial_log = [
        {"event": "created", "item_id": "covered", "agent_type": "janitor", "timestamp": "2026-01-01T00:00:00Z"},
        {"event": "completed", "item_id": "covered", "agent_type": "janitor", "timestamp": "2026-01-02T00:00:00Z"},
    ]
    save_beads_item_stats({"log": initial_log, "summary": {}}, stats_path)

    monkeypatch.setattr(backfill, "_get_all_beads_items", lambda: [{"id": "covered"}])

    result = backfill.backfill_from_beads_db(stats_path=stats_path, silent=True)

    assert result["already_complete"] is True
    assert result["backfilled"] == 0


def test_get_all_beads_items_handles_subprocess_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_args: object, **_kwargs: object) -> None:
        raise subprocess.CalledProcessError(1, "bd")

    monkeypatch.setattr(backfill.subprocess, "run", boom)

    assert backfill._get_all_beads_items() == []
