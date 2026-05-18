"""Tests for pokepoke.worktrees.lock_cleanup."""

import json
from pathlib import Path
from unittest.mock import patch

from pokepoke.worktrees.lock_cleanup import (
    cleanup_all_lock_files_for_pid,
    cleanup_owned_lock_files,
)


class TestCleanupOwnedLockFiles:
    """Tests for cleanup_owned_lock_files()."""

    @patch("pokepoke.worktrees.lock_cleanup._get_related_files")
    @patch("pokepoke.worktrees.lock_cleanup.get_owned_lock_paths")
    def test_removes_tracked_files(
        self, mock_get_owned, mock_get_related, tmp_path: Path,
    ):
        lock_file = tmp_path / "test.lock"
        meta_file = tmp_path / "test.lock.meta"
        break_file = tmp_path / "test.lock.break"

        lock_file.touch()
        meta_file.touch()
        break_file.touch()

        mock_get_owned.return_value = [lock_file]
        mock_get_related.return_value = [lock_file, meta_file, break_file]

        count = cleanup_owned_lock_files()

        assert count == 3
        assert not lock_file.exists()
        assert not meta_file.exists()
        assert not break_file.exists()

    @patch("pokepoke.worktrees.lock_cleanup._get_related_files")
    @patch("pokepoke.worktrees.lock_cleanup.get_owned_lock_paths")
    def test_missing_files_dont_raise_errors(
        self, mock_get_owned, mock_get_related, tmp_path: Path,
    ):
        lock_file = tmp_path / "ghost.lock"
        meta_file = tmp_path / "ghost.lock.meta"
        break_file = tmp_path / "ghost.lock.break"

        mock_get_owned.return_value = [lock_file]
        mock_get_related.return_value = [lock_file, meta_file, break_file]

        # None of the files exist — should not raise
        count = cleanup_owned_lock_files()
        assert count == 3  # unlink(missing_ok=True) succeeds; files already absent


class TestCleanupAllLockFilesForPid:
    """Tests for cleanup_all_lock_files_for_pid()."""

    def _setup_lock(
        self, locks_dir: Path, name: str, pid: int,
    ) -> tuple[Path, Path, Path]:
        lock = locks_dir / f"{name}.lock"
        meta = locks_dir / f"{name}.lock.meta"
        brk = locks_dir / f"{name}.lock.break"
        lock.touch()
        meta.write_text(json.dumps({"pid": pid, "timestamp": 1234567890}))
        brk.touch()
        return lock, meta, brk

    @patch("pokepoke.worktrees.lock_cleanup.Path")
    def test_removes_matching_pid(self, mock_path_cls, tmp_path: Path):
        locks_dir = tmp_path / ".pokepoke" / "locks"
        locks_dir.mkdir(parents=True)

        lock, meta, brk = self._setup_lock(locks_dir, "worktree-setup", 9999)

        # Make Path(".pokepoke") / "locks" resolve to our tmp_path directory
        mock_path_cls.side_effect = lambda *a: Path(*a)
        with patch(
            "pokepoke.worktrees.lock_cleanup.Path",
            side_effect=lambda *a: tmp_path / Path(*a) if a else tmp_path,
        ):
            count = cleanup_all_lock_files_for_pid(pid=9999)

        assert count == 3
        assert not lock.exists()
        assert not meta.exists()
        assert not brk.exists()

    @patch("pokepoke.worktrees.lock_cleanup.Path")
    def test_skips_different_pid(self, mock_path_cls, tmp_path: Path):
        locks_dir = tmp_path / ".pokepoke" / "locks"
        locks_dir.mkdir(parents=True)

        lock, meta, brk = self._setup_lock(locks_dir, "other", 1111)

        with patch(
            "pokepoke.worktrees.lock_cleanup.Path",
            side_effect=lambda *a: tmp_path / Path(*a) if a else tmp_path,
        ):
            count = cleanup_all_lock_files_for_pid(pid=9999)

        assert count == 0
        assert lock.exists()
        assert meta.exists()
        assert brk.exists()

    def test_handles_empty_locks_directory(self, tmp_path: Path):
        locks_dir = tmp_path / ".pokepoke" / "locks"
        locks_dir.mkdir(parents=True)

        with patch(
            "pokepoke.worktrees.lock_cleanup.Path",
            side_effect=lambda *a: tmp_path / Path(*a) if a else tmp_path,
        ):
            count = cleanup_all_lock_files_for_pid(pid=9999)

        assert count == 0

    def test_nonexistent_locks_directory_returns_zero(self, tmp_path: Path):
        # Point to a directory that doesn't exist
        with patch(
            "pokepoke.worktrees.lock_cleanup.Path",
            side_effect=lambda *a: tmp_path / Path(*a) if a else tmp_path,
        ):
            count = cleanup_all_lock_files_for_pid(pid=9999)

        assert count == 0
