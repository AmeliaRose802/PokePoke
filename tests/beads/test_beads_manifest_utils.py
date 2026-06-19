"""Tests for beads_manifest_utils — manifest persistence functions.

Tests the shared manifest utility functions extracted to break the
circular dependency between beads_management and beads_recovery.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

from pokepoke.beads.beads_manifest_utils import (
    FailedUnassignEntry,
    _get_failed_unassign_manifest_path,
    _load_failed_unassign_manifest,
    _save_failed_unassign_manifest,
    add_failed_unassign,
    remove_failed_unassign,
)


class TestGetFailedUnassignManifestPath:
    def test_returns_pokepoke_path(self) -> None:
        path = _get_failed_unassign_manifest_path()
        assert path.name == "failed_unassigns.json"
        assert path.parent.name == ".pokepoke"


class TestLoadFailedUnassignManifest:
    def test_empty_when_file_missing(self) -> None:
        with patch(
            "pokepoke.beads.beads_manifest_utils._get_failed_unassign_manifest_path",
            return_value=Path("/nonexistent/path.json"),
        ):
            assert _load_failed_unassign_manifest() == {}

    def test_loads_valid_json(self, tmp_path: Path) -> None:
        import json
        manifest_path = tmp_path / "manifest.json"
        manifest_path.write_text(
            json.dumps({"item-1": {"reason": "test", "timestamp": "2024-01-01"}}),
            encoding="utf-8",
        )
        with patch(
            "pokepoke.beads.beads_manifest_utils._get_failed_unassign_manifest_path",
            return_value=manifest_path,
        ):
            result = _load_failed_unassign_manifest()
            assert "item-1" in result
            assert isinstance(result["item-1"], FailedUnassignEntry)
            assert result["item-1"].reason == "test"

    def test_returns_empty_on_invalid_json(self, tmp_path: Path) -> None:
        manifest_path = tmp_path / "bad.json"
        manifest_path.write_text("not valid json", encoding="utf-8")
        with patch(
            "pokepoke.beads.beads_manifest_utils._get_failed_unassign_manifest_path",
            return_value=manifest_path,
        ):
            assert _load_failed_unassign_manifest() == {}


class TestSaveFailedUnassignManifest:
    def test_creates_parent_directory(self, tmp_path: Path) -> None:
        manifest_path = tmp_path / "subdir" / "manifest.json"
        with patch(
            "pokepoke.beads.beads_manifest_utils._get_failed_unassign_manifest_path",
            return_value=manifest_path,
        ):
            _save_failed_unassign_manifest({"item-1": FailedUnassignEntry(reason="test", timestamp="t")})
            assert manifest_path.exists()
            assert manifest_path.parent.exists()

    def test_atomic_write_via_temp_file(self, tmp_path: Path) -> None:
        manifest_path = tmp_path / "manifest.json"
        with patch(
            "pokepoke.beads.beads_manifest_utils._get_failed_unassign_manifest_path",
            return_value=manifest_path,
        ):
            _save_failed_unassign_manifest({"item-1": FailedUnassignEntry(reason="test", timestamp="t")})
            # Verify temp file was used (no .tmp should remain)
            assert not (manifest_path.with_suffix('.tmp')).exists()
            assert manifest_path.exists()


class TestAddFailedUnassign:
    def test_adds_item_with_timestamp(self, tmp_path: Path) -> None:
        manifest_path = tmp_path / ".pokepoke" / "manifest.json"
        manifest_path.parent.mkdir(parents=True)
        manifest_path.write_text("{}", encoding="utf-8")
        with (
            patch(
                "pokepoke.beads.beads_manifest_utils._get_failed_unassign_manifest_path",
                return_value=manifest_path,
            ),
            patch("pokepoke.beads.beads_manifest_utils.manifest_lock", return_value=MagicMock()),
        ):
            add_failed_unassign("item-42", "connection refused")
            loaded = _load_failed_unassign_manifest()
            assert "item-42" in loaded
            assert loaded["item-42"].reason == "connection refused"
            assert loaded["item-42"].timestamp


class TestRemoveFailedUnassign:
    def test_removes_existing_item(self, tmp_path: Path) -> None:
        import json
        manifest_path = tmp_path / ".pokepoke" / "manifest.json"
        manifest_path.parent.mkdir(parents=True)
        manifest_path.write_text(
            json.dumps({"item-1": {"reason": "x", "timestamp": "t"}}),
            encoding="utf-8",
        )
        with (
            patch(
                "pokepoke.beads.beads_manifest_utils._get_failed_unassign_manifest_path",
                return_value=manifest_path,
            ),
            patch("pokepoke.beads.beads_manifest_utils.manifest_lock", return_value=MagicMock()),
        ):
            remove_failed_unassign("item-1")
            assert _load_failed_unassign_manifest() == {}

    def test_removes_nonexistent_is_noop(self, tmp_path: Path) -> None:
        import json
        manifest_path = tmp_path / ".pokepoke" / "manifest.json"
        manifest_path.parent.mkdir(parents=True)
        manifest_path.write_text(json.dumps({}), encoding="utf-8")
        with (
            patch(
                "pokepoke.beads.beads_manifest_utils._get_failed_unassign_manifest_path",
                return_value=manifest_path,
            ),
            patch("pokepoke.beads.beads_manifest_utils.manifest_lock", return_value=MagicMock()),
        ):
            remove_failed_unassign("ghost")
            assert _load_failed_unassign_manifest() == {}
