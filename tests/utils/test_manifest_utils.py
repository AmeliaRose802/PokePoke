"""Tests for pokepoke.manifest_utils module."""

import json
import logging
from pathlib import Path

import pytest

from pokepoke.manifest_utils import (
    get_manifest_path,
    load_manifest_from_path,
    save_manifest_to_path,
)


class TestGetManifestPath:
    def test_returns_path_under_pokepoke_dir(self) -> None:
        result = get_manifest_path("test.json")
        assert result == Path(".pokepoke") / "test.json"

    def test_different_filenames(self) -> None:
        assert get_manifest_path("a.json") != get_manifest_path("b.json")


class TestLoadManifestFromPath:
    def test_returns_empty_dict_for_missing_file(self, tmp_path: Path) -> None:
        assert load_manifest_from_path(tmp_path / "nonexistent.json") == {}

    def test_loads_valid_manifest(self, tmp_path: Path) -> None:
        manifest_path = tmp_path / "test.json"
        data = {"item-1": {"key": "value"}}
        manifest_path.write_text(json.dumps(data), encoding="utf-8")
        assert load_manifest_from_path(manifest_path) == data

    def test_returns_empty_dict_for_non_dict(self, tmp_path: Path) -> None:
        manifest_path = tmp_path / "test.json"
        manifest_path.write_text(json.dumps(["a", "b"]), encoding="utf-8")
        assert load_manifest_from_path(manifest_path) == {}

    def test_returns_empty_dict_for_invalid_json(self, tmp_path: Path) -> None:
        manifest_path = tmp_path / "test.json"
        manifest_path.write_text("not json!", encoding="utf-8")
        assert load_manifest_from_path(manifest_path) == {}


class TestSaveManifestToPath:
    def test_saves_valid_manifest(self, tmp_path: Path) -> None:
        manifest_path = tmp_path / "test.json"
        data = {"item-1": {"key": "value", "other": "data"}}
        save_manifest_to_path(manifest_path, data)
        loaded = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert loaded == data

    def test_creates_parent_directory(self, tmp_path: Path) -> None:
        manifest_path = tmp_path / "subdir" / "test.json"
        save_manifest_to_path(manifest_path, {"a": {"b": "c"}})
        assert manifest_path.exists()

    def test_logs_warning_on_error(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        # Use an invalid path to trigger OSError
        manifest_path = tmp_path / "nonexistent_dir" / "test.json"
        from unittest.mock import patch

        with patch("pathlib.Path.mkdir", side_effect=OSError("denied")), \
             caplog.at_level(logging.WARNING):
            save_manifest_to_path(manifest_path, {"a": {"b": "c"}})
            assert "Failed to save manifest" in caplog.text

    def test_logs_warn_context(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        manifest_path = tmp_path / "nonexistent_dir" / "test.json"
        from unittest.mock import patch

        with patch("pathlib.Path.mkdir", side_effect=OSError("denied")), \
             caplog.at_level(logging.WARNING):
            save_manifest_to_path(
                manifest_path,
                {"a": {"b": "c"}},
                warn_context="some context info",
            )
            assert "some context info" in caplog.text

    def test_retries_rename_on_os_error(self, tmp_path: Path) -> None:
        """Rename retries should succeed after transient failures."""
        manifest_path = tmp_path / "test.json"
        data = {"item-1": {"key": "value"}}
        from unittest.mock import patch

        original_replace = Path.replace
        call_count = 0

        def flaky_replace(self: Path, target: Path) -> Path:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise OSError("Access is denied")
            return original_replace(self, target)

        with patch.object(Path, "replace", flaky_replace):
            save_manifest_to_path(manifest_path, data)

        loaded = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert loaded == data
        assert call_count == 3

    def test_write_text_failure_logs_warning(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """OSError during write_text should log a warning and return."""
        manifest_path = tmp_path / "test.json"
        from unittest.mock import patch

        with patch.object(Path, "write_text", side_effect=OSError("disk full")), \
             caplog.at_level(logging.WARNING):
            save_manifest_to_path(manifest_path, {"a": {"b": "c"}}, warn_context="extra info")

        assert "Failed to save manifest" in caplog.text
        assert "extra info" in caplog.text
        assert not manifest_path.exists()

    def test_all_retries_exhausted_logs_warning(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """When all rename retries fail, should log warning and clean up."""
        manifest_path = tmp_path / "test.json"
        from unittest.mock import patch

        with patch.object(Path, "replace", side_effect=OSError("Access denied")), \
             caplog.at_level(logging.WARNING):
            save_manifest_to_path(
                manifest_path, {"a": {"b": "c"}}, warn_context="orphan paths"
            )

        assert "after 5 retries" in caplog.text
        assert "orphan paths" in caplog.text
        # Temp file should have been cleaned up
        assert not (tmp_path / "test.tmp").exists()
