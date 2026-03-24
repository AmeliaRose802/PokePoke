"""Tests for pokepoke.maintenance.maintenance_state — persistent maintenance counter."""

import json
from pathlib import Path
from unittest.mock import patch

from pokepoke.maintenance.maintenance_state import (
    MaintenanceState,
    RepoMaintenanceState,
    get_items_completed_for_repo,
    get_repo_state,
    increment_items_completed,
    load_state,
    record_maintenance_run,
    save_state,
)


class TestMaintenanceState:
    """Tests for MaintenanceState dataclass."""

    def test_defaults(self) -> None:
        state = MaintenanceState()
        assert state.total_items_completed == 0
        assert state.repos == {}

    def test_custom_values(self) -> None:
        state = MaintenanceState(total_items_completed=5)
        assert state.total_items_completed == 5


class TestRepoMaintenanceState:
    """Tests for RepoMaintenanceState dataclass."""

    def test_defaults(self) -> None:
        repo_state = RepoMaintenanceState()
        assert repo_state.items_completed == 0
        assert repo_state.last_run_timestamp == 0.0


class TestLoadState:
    """Tests for load_state function."""

    def test_returns_default_when_file_missing(self, tmp_path: Path) -> None:
        fake_path = tmp_path / "maintenance_state.json"
        with patch("pokepoke.maintenance.maintenance_state.STATE_FILE", fake_path):
            state = load_state()
        assert state.total_items_completed == 0
        assert state.repos == {}

    def test_loads_valid_json(self, tmp_path: Path) -> None:
        fake_path = tmp_path / "maintenance_state.json"
        fake_path.write_text(json.dumps({
            "total_items_completed": 10,
            "repos": {
                "repo-a": {"items_completed": 5, "last_run_timestamp": 100.0},
            },
        }), encoding="utf-8")
        with patch("pokepoke.maintenance.maintenance_state.STATE_FILE", fake_path):
            state = load_state()
        assert state.total_items_completed == 10
        assert "repo-a" in state.repos
        assert state.repos["repo-a"].items_completed == 5
        assert state.repos["repo-a"].last_run_timestamp == 100.0

    def test_loads_legacy_format_without_repos(self, tmp_path: Path) -> None:
        """Backward compatible: old state files without 'repos' key."""
        fake_path = tmp_path / "maintenance_state.json"
        fake_path.write_text(json.dumps({
            "total_items_completed": 10,
        }), encoding="utf-8")
        with patch("pokepoke.maintenance.maintenance_state.STATE_FILE", fake_path):
            state = load_state()
        assert state.total_items_completed == 10
        assert state.repos == {}

    def test_returns_default_on_corrupt_json(self, tmp_path: Path) -> None:
        """Covers exception handling in load_state."""
        fake_path = tmp_path / "maintenance_state.json"
        fake_path.write_text("not valid json!!!", encoding="utf-8")
        with patch("pokepoke.maintenance.maintenance_state.STATE_FILE", fake_path):
            state = load_state()
        assert state.total_items_completed == 0

    def test_returns_default_on_invalid_fields(self, tmp_path: Path) -> None:
        """Covers TypeError from unexpected fields."""
        fake_path = tmp_path / "maintenance_state.json"
        fake_path.write_text(json.dumps({"unexpected_field": 999}), encoding="utf-8")
        with patch("pokepoke.maintenance.maintenance_state.STATE_FILE", fake_path):
            state = load_state()
        assert state.total_items_completed == 0


class TestSaveState:
    """Tests for save_state function."""

    def test_saves_to_disk(self, tmp_path: Path) -> None:
        fake_path = tmp_path / "maintenance_state.json"
        state = MaintenanceState(total_items_completed=7, repos={
            "repo-x": RepoMaintenanceState(items_completed=3, last_run_timestamp=50.0),
        })
        with patch("pokepoke.maintenance.maintenance_state.STATE_FILE", fake_path):
            save_state(state)
        data = json.loads(fake_path.read_text(encoding="utf-8"))
        assert data["total_items_completed"] == 7
        assert data["repos"]["repo-x"]["items_completed"] == 3
        assert data["repos"]["repo-x"]["last_run_timestamp"] == 50.0


class TestIncrementItemsCompleted:
    """Tests for increment_items_completed function."""

    def test_increments_from_zero_global(self, tmp_path: Path) -> None:
        """Legacy: no repo_id increments global counter."""
        fake_path = tmp_path / "maintenance_state.json"
        with patch("pokepoke.maintenance.maintenance_state.STATE_FILE", fake_path):
            result = increment_items_completed()
        assert result == 1

    def test_increments_existing_global(self, tmp_path: Path) -> None:
        fake_path = tmp_path / "maintenance_state.json"
        fake_path.write_text(json.dumps({
            "total_items_completed": 5,
            "repos": {},
        }), encoding="utf-8")
        with patch("pokepoke.maintenance.maintenance_state.STATE_FILE", fake_path):
            result = increment_items_completed()
        assert result == 6

    def test_increments_per_repo(self, tmp_path: Path) -> None:
        """Per-repo: increments both per-repo and global counters."""
        fake_path = tmp_path / "maintenance_state.json"
        with patch("pokepoke.maintenance.maintenance_state.STATE_FILE", fake_path):
            result = increment_items_completed(repo_id="repo-a")
        assert result == 1
        # Check the persisted state
        with patch("pokepoke.maintenance.maintenance_state.STATE_FILE", fake_path):
            state = load_state()
        assert state.total_items_completed == 1
        assert state.repos["repo-a"].items_completed == 1

    def test_independent_repo_counters(self, tmp_path: Path) -> None:
        """Each repo has its own independent counter."""
        fake_path = tmp_path / "maintenance_state.json"
        with patch("pokepoke.maintenance.maintenance_state.STATE_FILE", fake_path):
            r1 = increment_items_completed(repo_id="repo-a")
            r2 = increment_items_completed(repo_id="repo-b")
            r3 = increment_items_completed(repo_id="repo-a")
        assert r1 == 1
        assert r2 == 1
        assert r3 == 2
        # Global should be 3 total
        with patch("pokepoke.maintenance.maintenance_state.STATE_FILE", fake_path):
            state = load_state()
        assert state.total_items_completed == 3
        assert state.repos["repo-a"].items_completed == 2
        assert state.repos["repo-b"].items_completed == 1


class TestGetRepoState:
    """Tests for get_repo_state function."""

    def test_creates_new_repo_state(self) -> None:
        state = MaintenanceState()
        repo = get_repo_state(state, "new-repo")
        assert repo.items_completed == 0
        assert "new-repo" in state.repos

    def test_returns_existing_repo_state(self) -> None:
        state = MaintenanceState(repos={
            "existing": RepoMaintenanceState(items_completed=10),
        })
        repo = get_repo_state(state, "existing")
        assert repo.items_completed == 10


class TestRecordMaintenanceRun:
    """Tests for record_maintenance_run function."""

    def test_records_timestamp(self, tmp_path: Path) -> None:
        fake_path = tmp_path / "maintenance_state.json"
        with patch("pokepoke.maintenance.maintenance_state.STATE_FILE", fake_path):
            record_maintenance_run("repo-a")
            state = load_state()
        assert state.repos["repo-a"].last_run_timestamp > 0


class TestGetItemsCompletedForRepo:
    """Tests for get_items_completed_for_repo function."""

    def test_returns_zero_for_unknown(self, tmp_path: Path) -> None:
        fake_path = tmp_path / "maintenance_state.json"
        with patch("pokepoke.maintenance.maintenance_state.STATE_FILE", fake_path):
            assert get_items_completed_for_repo("unknown") == 0

    def test_returns_count_for_known(self, tmp_path: Path) -> None:
        fake_path = tmp_path / "maintenance_state.json"
        fake_path.write_text(json.dumps({
            "total_items_completed": 5,
            "repos": {"repo-a": {"items_completed": 3, "last_run_timestamp": 0.0}},
        }), encoding="utf-8")
        with patch("pokepoke.maintenance.maintenance_state.STATE_FILE", fake_path):
            assert get_items_completed_for_repo("repo-a") == 3
