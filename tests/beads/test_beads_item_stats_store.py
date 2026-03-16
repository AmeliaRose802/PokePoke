import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from pokepoke.beads.beads_item_stats_store import (
    get_summary,
    get_summary_by_repo,
    load_beads_item_stats,
    record_item_completed,
    record_item_created,
)
from pokepoke.utils.file_utils import replace_with_retry


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
        replace_with_retry(src, dst)
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

        with patch("pokepoke.utils.file_utils.os.replace", side_effect=fake_replace), \
             patch("pokepoke.utils.file_utils.time.sleep") as mock_sleep:
            replace_with_retry(src, dst, retries=5, delay=0.01)

        assert fail_count[0] == 3
        assert mock_sleep.call_count == 2


def test_replace_with_retry_raises_after_all_retries_exhausted() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        src = Path(tmpdir) / "src.tmp"
        dst = Path(tmpdir) / "dst.json"
        src.write_text("data", encoding="utf-8")

        with patch("pokepoke.utils.file_utils.os.replace", side_effect=PermissionError("locked")), \
             patch("pokepoke.utils.file_utils.time.sleep"), pytest.raises(PermissionError):
            replace_with_retry(src, dst, retries=3, delay=0.001)


def test_summary_deduplicates_events_by_item_id() -> None:
    """Test that recording the same item multiple times only counts once."""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "stats.json"

        # Record same item completed multiple times (simulating retries/duplicates)
        s1 = record_item_completed("PokePoke-0001", agent_type="work", path=path)
        assert s1["total_completed"] == 1

        s2 = record_item_completed("PokePoke-0001", agent_type="work", path=path)
        assert s2["total_completed"] == 1  # Still 1, not 2

        s3 = record_item_completed("PokePoke-0001", agent_type="work", path=path)
        assert s3["total_completed"] == 1  # Still 1, not 3

        # Record a different item
        s4 = record_item_completed("PokePoke-0002", agent_type="work", path=path)
        assert s4["total_completed"] == 2  # Now 2 unique items

        # Same for created events
        s5 = record_item_created("PokePoke-0003", agent_type="janitor", path=path)
        assert s5["total_created"] == 1

        s6 = record_item_created("PokePoke-0003", agent_type="janitor", path=path)
        assert s6["total_created"] == 1  # Still 1, not 2

        s7 = record_item_created("PokePoke-0004", agent_type="janitor", path=path)
        assert s7["total_created"] == 2  # Now 2 unique items

        # Verify final state
        summary = get_summary(path)
        assert summary["total_created"] == 2
        assert summary["total_completed"] == 2
        assert summary["net_delta"] == 0


# ── Repo-level isolation tests ──────────────────────────────────────


def test_record_event_includes_repo_name_from_context() -> None:
    """Events should capture repo_name from thread-local context."""
    from pokepoke.stats.metrics_context import set_current_repo_name

    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "stats.json"
        set_current_repo_name("MyRepo")
        try:
            record_item_created("PP-1", agent_type="work", path=path)
        finally:
            set_current_repo_name(None)

        data = load_beads_item_stats(path)
        assert data["log"][0]["repo_name"] == "MyRepo"


def test_record_event_explicit_repo_name_overrides_context() -> None:
    """Explicit repo_name parameter should override thread-local context."""
    from pokepoke.stats.metrics_context import set_current_repo_name

    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "stats.json"
        set_current_repo_name("ContextRepo")
        try:
            record_item_created("PP-1", agent_type="work", path=path, repo_name="ExplicitRepo")
        finally:
            set_current_repo_name(None)

        data = load_beads_item_stats(path)
        assert data["log"][0]["repo_name"] == "ExplicitRepo"


def test_get_summary_by_repo() -> None:
    """get_summary_by_repo should segment created/completed counts per repo."""
    from pokepoke.stats.metrics_context import set_current_repo_name

    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "stats.json"

        set_current_repo_name("RepoA")
        record_item_created("PP-1", agent_type="janitor", path=path)
        record_item_created("PP-2", agent_type="janitor", path=path)
        record_item_completed("PP-3", agent_type="work", path=path)

        set_current_repo_name("RepoB")
        record_item_created("PP-4", agent_type="work", path=path)
        set_current_repo_name(None)

        by_repo = get_summary_by_repo(path)
        assert "RepoA" in by_repo
        assert by_repo["RepoA"]["total_created"] == 2
        assert by_repo["RepoA"]["total_completed"] == 1
        assert by_repo["RepoA"]["net_delta"] == 1

        assert "RepoB" in by_repo
        assert by_repo["RepoB"]["total_created"] == 1
        assert by_repo["RepoB"]["total_completed"] == 0
        assert by_repo["RepoB"]["net_delta"] == 1


def test_get_summary_by_repo_empty() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "stats.json"
        assert get_summary_by_repo(path) == {}

