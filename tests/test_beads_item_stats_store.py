import json
import tempfile
from pathlib import Path

from pokepoke.beads_item_stats_store import (
    get_summary,
    load_beads_item_stats,
    record_item_completed,
    record_item_created,
)


def test_missing_file_loads_empty_store() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "missing.json"
        data = load_beads_item_stats(path)
        assert data["log"] == []
        assert data["summary"]["total_created"] == 0
        assert data["summary"]["total_completed"] == 0


def test_record_created_and_completed_updates_totals_and_by_agent() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "stats.json"

        s1 = record_item_created("PokePoke-0001", agent_type="janitor", path=path)
        assert s1["total_created"] == 1
        assert s1["total_completed"] == 0
        assert s1["net_delta"] == 1
        assert s1["by_agent_type"]["janitor"]["created"] == 1

        s2 = record_item_completed("PokePoke-0002", agent_type="work", path=path)
        assert s2["total_created"] == 1
        assert s2["total_completed"] == 1
        assert s2["net_delta"] == 0
        assert s2["by_agent_type"]["work"]["completed"] == 1

        s3 = record_item_created("PokePoke-0003", agent_type="work", path=path)
        assert s3["total_created"] == 2
        assert s3["total_completed"] == 1
        assert s3["net_delta"] == 1
        assert s3["by_agent_type"]["work"]["created"] == 1
        assert s3["by_agent_type"]["work"]["net_delta"] == 0

        summary = get_summary(path)
        assert summary["total_created"] == 2
        assert summary["total_completed"] == 1
        assert summary["net_delta"] == 1


def test_corrupt_file_returns_empty_store() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "stats.json"
        path.write_text("{not-json", encoding="utf-8")

        data = load_beads_item_stats(path)
        assert data["log"] == []
        assert data["summary"]["total_created"] == 0


def test_persists_json_to_disk() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "stats.json"
        _ = record_item_created("PokePoke-0001", agent_type="janitor", path=path)
        assert path.exists()

        loaded = json.loads(path.read_text(encoding="utf-8"))
        assert isinstance(loaded.get("log"), list)
        assert loaded["log"][0]["event"] == "created"
        assert loaded["summary"]["total_created"] == 1
