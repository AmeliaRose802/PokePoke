import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from pokepoke.beads_item_stats_store import (
    _replace_with_retry,
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


def test_replace_with_retry_succeeds_on_first_attempt() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        src = Path(tmpdir) / "src.tmp"
        dst = Path(tmpdir) / "dst.json"
        src.write_text("data", encoding="utf-8")
        _replace_with_retry(src, dst)
        assert dst.exists()
        assert dst.read_text(encoding="utf-8") == "data"
        assert not src.exists()


def test_replace_with_retry_retries_on_permission_error() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        src = Path(tmpdir) / "src.tmp"
        dst = Path(tmpdir) / "dst.json"
        src.write_text("data", encoding="utf-8")

        fail_count = [0]

        def fake_replace(s: str, d: str) -> None:
            fail_count[0] += 1
            if fail_count[0] < 3:
                raise PermissionError("locked")
            # Success on third attempt — nothing to do, just return

        with patch("pokepoke.beads_item_stats_store.os.replace", side_effect=fake_replace), \
             patch("pokepoke.beads_item_stats_store.time.sleep") as mock_sleep:
            _replace_with_retry(src, dst, retries=5, delay=0.01)

        assert fail_count[0] == 3
        assert mock_sleep.call_count == 2


def test_replace_with_retry_raises_after_all_retries_exhausted() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        src = Path(tmpdir) / "src.tmp"
        dst = Path(tmpdir) / "dst.json"
        src.write_text("data", encoding="utf-8")

        with patch("pokepoke.beads_item_stats_store.os.replace", side_effect=PermissionError("locked")), \
             patch("pokepoke.beads_item_stats_store.time.sleep"):
            with pytest.raises(PermissionError):
                _replace_with_retry(src, dst, retries=3, delay=0.001)
