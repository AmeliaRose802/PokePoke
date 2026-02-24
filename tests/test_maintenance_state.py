"""Tests for pokepoke.maintenance_state — persistent maintenance counter."""

import json
from pathlib import Path
from unittest.mock import patch

from pokepoke.maintenance_state import (
    MaintenanceState,
    load_state,
    save_state,
    increment_items_completed,
)


class TestMaintenanceState:
    """Tests for MaintenanceState dataclass."""

    def test_defaults(self) -> None:
        state = MaintenanceState()
        assert state.total_items_completed == 0
        assert state.last_janitor_run == 0

    def test_custom_values(self) -> None:
        state = MaintenanceState(total_items_completed=5, last_janitor_run=3)
        assert state.total_items_completed == 5
        assert state.last_janitor_run == 3


class TestLoadState:
    """Tests for load_state function."""

    def test_returns_default_when_file_missing(self, tmp_path: Path) -> None:
        fake_path = tmp_path / "maintenance_state.json"
        with patch("pokepoke.maintenance_state.STATE_FILE", fake_path):
            state = load_state()
        assert state.total_items_completed == 0

    def test_loads_valid_json(self, tmp_path: Path) -> None:
        fake_path = tmp_path / "maintenance_state.json"
        fake_path.write_text(json.dumps({
            "total_items_completed": 10,
            "last_janitor_run": 5,
            "last_tech_debt_run": 3,
            "last_backlog_run": 0,
            "last_beta_run": 0,
            "last_code_review_run": 0,
        }), encoding="utf-8")
        with patch("pokepoke.maintenance_state.STATE_FILE", fake_path):
            state = load_state()
        assert state.total_items_completed == 10
        assert state.last_janitor_run == 5

    def test_returns_default_on_corrupt_json(self, tmp_path: Path) -> None:
        """Covers lines 29-32: exception handling in load_state."""
        fake_path = tmp_path / "maintenance_state.json"
        fake_path.write_text("not valid json!!!", encoding="utf-8")
        with patch("pokepoke.maintenance_state.STATE_FILE", fake_path):
            state = load_state()
        assert state.total_items_completed == 0

    def test_returns_default_on_invalid_fields(self, tmp_path: Path) -> None:
        """Covers lines 29-32: TypeError from unexpected fields."""
        fake_path = tmp_path / "maintenance_state.json"
        fake_path.write_text(json.dumps({"unexpected_field": 999}), encoding="utf-8")
        with patch("pokepoke.maintenance_state.STATE_FILE", fake_path):
            state = load_state()
        assert state.total_items_completed == 0


class TestSaveState:
    """Tests for save_state function."""

    def test_saves_to_disk(self, tmp_path: Path) -> None:
        fake_path = tmp_path / "maintenance_state.json"
        state = MaintenanceState(total_items_completed=7, last_janitor_run=3)
        with patch("pokepoke.maintenance_state.STATE_FILE", fake_path):
            save_state(state)
        data = json.loads(fake_path.read_text(encoding="utf-8"))
        assert data["total_items_completed"] == 7
        assert data["last_janitor_run"] == 3


class TestIncrementItemsCompleted:
    """Tests for increment_items_completed function."""

    def test_increments_from_zero(self, tmp_path: Path) -> None:
        fake_path = tmp_path / "maintenance_state.json"
        with patch("pokepoke.maintenance_state.STATE_FILE", fake_path):
            result = increment_items_completed()
        assert result == 1

    def test_increments_existing(self, tmp_path: Path) -> None:
        fake_path = tmp_path / "maintenance_state.json"
        fake_path.write_text(json.dumps({
            "total_items_completed": 5,
            "last_janitor_run": 0,
            "last_tech_debt_run": 0,
            "last_backlog_run": 0,
            "last_beta_run": 0,
            "last_code_review_run": 0,
        }), encoding="utf-8")
        with patch("pokepoke.maintenance_state.STATE_FILE", fake_path):
            result = increment_items_completed()
        assert result == 6
