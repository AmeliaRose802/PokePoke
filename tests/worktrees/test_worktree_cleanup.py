"""Tests for pokepoke.worktrees.worktree_cleanup module.

This file specifically tests the manifest operations with file locking.
Additional worktree cleanup tests exist in test_worktrees.py.
"""

import json
import threading
from pathlib import Path
from unittest.mock import patch

import pytest

from pokepoke.worktrees.worktree_cleanup import (
    add_uncleaned_worktree,
    get_worktree_manifest_path,
    load_worktree_manifest,
    remove_from_manifest,
    save_worktree_manifest,
)


class TestManifestPath:
    """Tests for get_worktree_manifest_path."""

    def test_returns_path_in_pokepoke_dir(self) -> None:
        path = get_worktree_manifest_path()
        assert path.name == "uncleaned_worktrees.json"
        assert path.parent.name == ".pokepoke"


class TestLoadWorktreeManifest:
    """Tests for load_worktree_manifest."""

    def test_returns_empty_for_missing_file(self, tmp_path: Path) -> None:
        manifest_path = tmp_path / "missing.json"
        with patch(
            "pokepoke.worktrees.worktree_cleanup.get_worktree_manifest_path",
            return_value=manifest_path,
        ):
            assert load_worktree_manifest() == {}

    def test_returns_empty_for_corrupt_json(self, tmp_path: Path) -> None:
        manifest_path = tmp_path / "corrupt.json"
        manifest_path.write_text("not valid json{{{", encoding="utf-8")
        with patch(
            "pokepoke.worktrees.worktree_cleanup.get_worktree_manifest_path",
            return_value=manifest_path,
        ):
            assert load_worktree_manifest() == {}

    def test_returns_empty_for_non_dict(self, tmp_path: Path) -> None:
        manifest_path = tmp_path / "array.json"
        manifest_path.write_text("[1, 2, 3]", encoding="utf-8")
        with patch(
            "pokepoke.worktrees.worktree_cleanup.get_worktree_manifest_path",
            return_value=manifest_path,
        ):
            assert load_worktree_manifest() == {}

    def test_returns_dict_content(self, tmp_path: Path) -> None:
        manifest_path = tmp_path / "manifest.json"
        data = {"task-1": {"path": "/path", "reason": "test", "timestamp": "2026-01-01"}}
        manifest_path.write_text(json.dumps(data), encoding="utf-8")
        with patch(
            "pokepoke.worktrees.worktree_cleanup.get_worktree_manifest_path",
            return_value=manifest_path,
        ):
            assert load_worktree_manifest() == data


class TestSaveWorktreeManifest:
    """Tests for save_worktree_manifest."""

    def test_creates_parent_directory(self, tmp_path: Path) -> None:
        manifest_path = tmp_path / "subdir" / "manifest.json"
        with patch(
            "pokepoke.worktrees.worktree_cleanup.get_worktree_manifest_path",
            return_value=manifest_path,
        ):
            save_worktree_manifest({"test": {"path": "/p", "reason": "r", "timestamp": "t"}})
            assert manifest_path.exists()

    def test_writes_json_content(self, tmp_path: Path) -> None:
        manifest_path = tmp_path / "manifest.json"
        data = {"task-1": {"path": "/path", "reason": "test", "timestamp": "2026-01-01"}}
        with patch(
            "pokepoke.worktrees.worktree_cleanup.get_worktree_manifest_path",
            return_value=manifest_path,
        ):
            save_worktree_manifest(data)
            loaded = json.loads(manifest_path.read_text(encoding="utf-8"))
            assert loaded == data

    def test_logs_oserror(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        import logging

        manifest_path = tmp_path / "blocked" / "manifest.json"
        # Create the directory and make it unwritable
        manifest_path.parent.mkdir(parents=True, exist_ok=True)

        data = {"task-1": {"path": "/path/to/worktree", "reason": "test", "timestamp": "t"}}

        with (
            patch(
                "pokepoke.worktrees.worktree_cleanup.get_worktree_manifest_path",
                return_value=manifest_path,
            ),
            patch("pathlib.Path.mkdir", side_effect=OSError("Permission denied")),
            caplog.at_level(logging.WARNING),
        ):
            save_worktree_manifest(data)
            assert "Failed to save manifest" in caplog.text


class TestAddUncleanedWorktree:
    """Tests for add_uncleaned_worktree with file locking."""

    def test_adds_entry_to_manifest(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".pokepoke").mkdir(exist_ok=True)

        add_uncleaned_worktree("task-123", "/path/to/worktree", "cleanup failed")

        manifest = load_worktree_manifest()
        assert "task-123" in manifest
        assert manifest["task-123"]["path"] == "/path/to/worktree"
        assert manifest["task-123"]["reason"] == "cleanup failed"
        assert "timestamp" in manifest["task-123"]

    def test_overwrites_existing_entry(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".pokepoke").mkdir(exist_ok=True)

        add_uncleaned_worktree("task-123", "/old/path", "old reason")
        add_uncleaned_worktree("task-123", "/new/path", "new reason")

        manifest = load_worktree_manifest()
        assert manifest["task-123"]["path"] == "/new/path"
        assert manifest["task-123"]["reason"] == "new reason"


class TestRemoveFromManifest:
    """Tests for remove_from_manifest with file locking."""

    def test_removes_existing_entry(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".pokepoke").mkdir(exist_ok=True)

        add_uncleaned_worktree("task-123", "/path", "reason")
        assert "task-123" in load_worktree_manifest()

        remove_from_manifest("task-123")
        assert "task-123" not in load_worktree_manifest()

    def test_noop_for_missing_entry(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".pokepoke").mkdir(exist_ok=True)

        # Should not raise, just no-op
        remove_from_manifest("nonexistent")
        assert load_worktree_manifest() == {}

    def test_preserves_other_entries(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".pokepoke").mkdir(exist_ok=True)

        add_uncleaned_worktree("task-1", "/path1", "reason1")
        add_uncleaned_worktree("task-2", "/path2", "reason2")

        remove_from_manifest("task-1")

        manifest = load_worktree_manifest()
        assert "task-1" not in manifest
        assert "task-2" in manifest


class TestManifestLockingBehavior:
    """Tests verifying manifest operations use file locking."""

    def test_concurrent_adds_do_not_lose_entries(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Concurrent add_uncleaned_worktree calls should not lose entries."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".pokepoke").mkdir(exist_ok=True)

        errors: list[str] = []
        num_entries = 10

        def add_entry(entry_id: str) -> None:
            try:
                add_uncleaned_worktree(entry_id, f"/path/{entry_id}", f"reason for {entry_id}")
            except Exception as e:
                errors.append(str(e))

        threads = [
            threading.Thread(target=add_entry, args=(f"entry-{i}",))
            for i in range(num_entries)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=60)

        assert not errors, f"Errors during concurrent adds: {errors}"

        manifest = load_worktree_manifest()
        for i in range(num_entries):
            assert f"entry-{i}" in manifest, f"Entry entry-{i} was lost in race condition"

    def test_concurrent_removes_do_not_corrupt_manifest(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Concurrent remove_from_manifest calls should not corrupt the manifest."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".pokepoke").mkdir(exist_ok=True)

        # Add entries first
        for i in range(10):
            add_uncleaned_worktree(f"entry-{i}", f"/path/{i}", f"reason {i}")

        errors: list[str] = []

        def remove_entry(entry_id: str) -> None:
            try:
                remove_from_manifest(entry_id)
            except Exception as e:
                errors.append(str(e))

        threads = [
            threading.Thread(target=remove_entry, args=(f"entry-{i}",))
            for i in range(10)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=60)

        assert not errors, f"Errors during concurrent removes: {errors}"

        # All entries should be removed
        manifest = load_worktree_manifest()
        assert len(manifest) == 0, f"Expected empty manifest, got {list(manifest.keys())}"

    def test_mixed_concurrent_operations(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Mixed concurrent add/remove operations should maintain consistency."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".pokepoke").mkdir(exist_ok=True)

        # Pre-add some entries that will be removed
        for i in range(5):
            add_uncleaned_worktree(f"remove-{i}", f"/path/remove/{i}", "to remove")

        errors: list[str] = []

        def add_entry(entry_id: str) -> None:
            try:
                add_uncleaned_worktree(entry_id, f"/path/{entry_id}", f"reason for {entry_id}")
            except Exception as e:
                errors.append(f"add {entry_id}: {e}")

        def remove_entry(entry_id: str) -> None:
            try:
                remove_from_manifest(entry_id)
            except Exception as e:
                errors.append(f"remove {entry_id}: {e}")

        threads = []
        # Add new entries
        for i in range(5):
            threads.append(threading.Thread(target=add_entry, args=(f"add-{i}",)))
        # Remove existing entries
        for i in range(5):
            threads.append(threading.Thread(target=remove_entry, args=(f"remove-{i}",)))

        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=60)

        assert not errors, f"Errors during mixed operations: {errors}"

        manifest = load_worktree_manifest()
        # All added entries should be present
        for i in range(5):
            assert f"add-{i}" in manifest, f"Added entry add-{i} missing"
        # All removed entries should be gone
        for i in range(5):
            assert f"remove-{i}" not in manifest, f"Removed entry remove-{i} still present"
