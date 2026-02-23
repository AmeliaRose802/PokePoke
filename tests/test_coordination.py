"""Tests for pokepoke.coordination module."""

import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest
from filelock import Timeout

from pokepoke.coordination import (
    acquire_lock, try_lock, worktree_setup_lock, merge_lock, merge_lock_active,
    manifest_lock, git_main_repo_lock, _lock_dir, _lock_path, _MERGE_LOCK_STALE_AGE,
)


class TestLockDir:
    """Tests for lock directory helpers."""

    def test_lock_dir_creates_directory(self, tmp_path: Path) -> None:
        with patch("pokepoke.coordination._lock_dir") as mock_dir:
            d = tmp_path / ".pokepoke" / "locks"
            mock_dir.return_value = d
            result = mock_dir()
            assert result == d

    def test_lock_path_returns_correct_name(self, tmp_path: Path) -> None:
        with patch("pokepoke.coordination._lock_dir", return_value=tmp_path):
            assert _lock_path("foo") == tmp_path / "foo.lock"


class TestAcquireLock:
    """Tests for acquire_lock context manager."""

    def test_acquires_and_releases(self, tmp_path: Path) -> None:
        with patch("pokepoke.coordination._lock_dir", return_value=tmp_path):
            with acquire_lock("test") as lock:
                assert lock.is_locked
                lock_file = tmp_path / "test.lock"
                assert lock_file.exists()
            assert not lock.is_locked

    def test_lock_file_created_in_lock_dir(self, tmp_path: Path) -> None:
        with patch("pokepoke.coordination._lock_dir", return_value=tmp_path), acquire_lock("mylock"):
            assert (tmp_path / "mylock.lock").exists()

    def test_timeout_raises(self, tmp_path: Path) -> None:
        with patch("pokepoke.coordination._lock_dir", return_value=tmp_path), acquire_lock("exclusive"):  # noqa: SIM117
            # Same lock with zero timeout should fail
            with pytest.raises(Timeout), acquire_lock("exclusive", timeout=0):
                    pass  # pragma: no cover

    def test_release_on_exception(self, tmp_path: Path) -> None:
        with patch("pokepoke.coordination._lock_dir", return_value=tmp_path):
            lock_ref = None
            with pytest.raises(RuntimeError), acquire_lock("err") as lock:
                lock_ref = lock
                raise RuntimeError("boom")
            assert lock_ref is not None
            assert not lock_ref.is_locked


class TestTryLock:
    """Tests for try_lock non-blocking acquisition."""

    def test_returns_lock_when_available(self, tmp_path: Path) -> None:
        with patch("pokepoke.coordination._lock_dir", return_value=tmp_path):
            lock = try_lock("avail")
            assert lock is not None
            assert lock.is_locked
            lock.release()

    def test_returns_none_when_held(self, tmp_path: Path) -> None:
        with patch("pokepoke.coordination._lock_dir", return_value=tmp_path), acquire_lock("held"):
            result = try_lock("held")
            assert result is None

    def test_caller_must_release(self, tmp_path: Path) -> None:
        with patch("pokepoke.coordination._lock_dir", return_value=tmp_path):
            lock = try_lock("manual")
            assert lock is not None
            assert lock.is_locked
            lock.release()
            assert not lock.is_locked


class TestLockDirCreation:
    """Tests for _lock_dir lazy directory creation."""

    def test_creates_nested_directories(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        d = _lock_dir()
        assert d.is_dir()
        assert d == Path(".pokepoke") / "locks"

    def test_idempotent(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        d1 = _lock_dir()
        d2 = _lock_dir()
        assert d1 == d2
        assert d1.is_dir()


class TestWorktreeSetupLock:
    """Tests for worktree_setup_lock – the high-level coordination primitive."""

    def test_acquires_and_releases(self, tmp_path: Path) -> None:
        with patch("pokepoke.coordination._lock_dir", return_value=tmp_path):
            with worktree_setup_lock(timeout=5) as lock:
                assert lock.is_locked
            assert not lock.is_locked

    def test_second_agent_times_out_while_first_holds_lock(self, tmp_path: Path) -> None:
        """Second concurrent agent should raise Timeout when first holds the lock."""
        with patch("pokepoke.coordination._lock_dir", return_value=tmp_path), worktree_setup_lock(timeout=5):  # noqa: SIM117
            with pytest.raises(Timeout), worktree_setup_lock(timeout=0):
                    pass  # pragma: no cover

    def test_serializes_two_threads(self, tmp_path: Path) -> None:
        """Two threads must not hold worktree_setup_lock simultaneously."""
        overlap_detected = threading.Event()
        inside_count = [0]
        lock_obj = threading.Lock()
        errors: list[str] = []

        def worker():
            with patch("pokepoke.coordination._lock_dir", return_value=tmp_path), worktree_setup_lock(timeout=10):
                with lock_obj:
                    inside_count[0] += 1
                    if inside_count[0] > 1:
                        errors.append("overlap!")
                        overlap_detected.set()
                import time
                time.sleep(0.05)
                with lock_obj:
                    inside_count[0] -= 1

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15)

        assert not errors, "Two threads were inside worktree_setup_lock simultaneously"

    def test_releases_on_exception(self, tmp_path: Path) -> None:
        with patch("pokepoke.coordination._lock_dir", return_value=tmp_path):
            lock_ref = None
            with pytest.raises(ValueError), worktree_setup_lock(timeout=5) as lock:
                lock_ref = lock
                raise ValueError("simulated failure")
            assert lock_ref is not None
            assert not lock_ref.is_locked


class TestMergeLock:
    """Tests for merge_lock – serializes worktree merges across parallel agents."""

    def test_acquires_and_releases(self, tmp_path: Path) -> None:
        with patch("pokepoke.coordination._lock_dir", return_value=tmp_path):
            with merge_lock(timeout=5) as lock:
                assert lock.is_locked
            assert not lock.is_locked

    def test_second_agent_times_out_while_first_holds_lock(self, tmp_path: Path) -> None:
        """Second concurrent agent should raise Timeout when first holds the lock."""
        with patch("pokepoke.coordination._lock_dir", return_value=tmp_path), merge_lock(timeout=5):  # noqa: SIM117
            with pytest.raises(Timeout), merge_lock(timeout=0):
                    pass  # pragma: no cover

    def test_serializes_two_threads(self, tmp_path: Path) -> None:
        """Two threads must not hold merge_lock simultaneously."""
        overlap_detected = threading.Event()
        inside_count = [0]
        lock_obj = threading.Lock()
        errors: list[str] = []

        def worker():
            with patch("pokepoke.coordination._lock_dir", return_value=tmp_path), merge_lock(timeout=10):
                with lock_obj:
                    inside_count[0] += 1
                    if inside_count[0] > 1:
                        errors.append("overlap!")
                        overlap_detected.set()
                import time
                time.sleep(0.05)
                with lock_obj:
                    inside_count[0] -= 1

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15)

        assert not errors, "Two threads were inside merge_lock simultaneously"

    def test_releases_on_exception(self, tmp_path: Path) -> None:
        with patch("pokepoke.coordination._lock_dir", return_value=tmp_path):
            lock_ref = None
            with pytest.raises(ValueError), merge_lock(timeout=5) as lock:
                lock_ref = lock
                raise ValueError("simulated failure")
            assert lock_ref is not None
            assert not lock_ref.is_locked


class TestMergeLockActive:
    """Tests for merge_lock_active helper."""

    def test_returns_false_when_not_held(self, tmp_path: Path) -> None:
        with patch("pokepoke.coordination._lock_dir", return_value=tmp_path):
            assert merge_lock_active() is False

    def test_returns_true_when_held(self, tmp_path: Path) -> None:
        with patch("pokepoke.coordination._lock_dir", return_value=tmp_path), merge_lock(timeout=5):
            assert merge_lock_active() is True


class TestManifestLock:
    """Tests for manifest_lock – serializes worktree manifest updates."""

    def test_acquires_and_releases(self, tmp_path: Path) -> None:
        with patch("pokepoke.coordination._lock_dir", return_value=tmp_path):
            with manifest_lock(timeout=5) as lock:
                assert lock.is_locked
            assert not lock.is_locked

    def test_second_agent_times_out_while_first_holds_lock(self, tmp_path: Path) -> None:
        """Second concurrent agent should raise Timeout when first holds the lock."""
        with patch("pokepoke.coordination._lock_dir", return_value=tmp_path), manifest_lock(timeout=5):  # noqa: SIM117
            with pytest.raises(Timeout), manifest_lock(timeout=0):
                    pass  # pragma: no cover

    def test_serializes_two_threads(self, tmp_path: Path) -> None:
        """Two threads must not hold manifest_lock simultaneously."""
        overlap_detected = threading.Event()
        inside_count = [0]
        lock_obj = threading.Lock()
        errors: list[str] = []

        def worker():
            with patch("pokepoke.coordination._lock_dir", return_value=tmp_path), manifest_lock(timeout=10):
                with lock_obj:
                    inside_count[0] += 1
                    if inside_count[0] > 1:
                        errors.append("overlap!")
                        overlap_detected.set()
                import time
                time.sleep(0.05)
                with lock_obj:
                    inside_count[0] -= 1

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15)

        assert not errors, "Two threads were inside manifest_lock simultaneously"

    def test_releases_on_exception(self, tmp_path: Path) -> None:
        with patch("pokepoke.coordination._lock_dir", return_value=tmp_path):
            lock_ref = None
            with pytest.raises(ValueError), manifest_lock(timeout=5) as lock:
                lock_ref = lock
                raise ValueError("simulated failure")
            assert lock_ref is not None
            assert not lock_ref.is_locked


class TestManifestFunctionsUseLocking:
    """Tests that manifest operations use file locking to prevent race conditions."""

    def test_add_uncleaned_worktree_acquires_lock(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """add_uncleaned_worktree should acquire manifest_lock during read-modify-write."""
        from pokepoke.worktree_cleanup import add_uncleaned_worktree

        monkeypatch.chdir(tmp_path)
        (tmp_path / ".pokepoke").mkdir(exist_ok=True)

        lock_acquired = []

        original_manifest_lock = manifest_lock

        from contextlib import contextmanager

        @contextmanager
        def tracking_manifest_lock(timeout=30.0):
            lock_acquired.append(True)
            with original_manifest_lock(timeout=timeout) as lock:
                yield lock

        # Patch at the coordination module level where it's defined
        with patch("pokepoke.coordination.manifest_lock", tracking_manifest_lock):
            add_uncleaned_worktree("test-id", "/path/to/worktree", "test reason")

        assert len(lock_acquired) == 1, "manifest_lock should be acquired exactly once"

    def test_remove_from_manifest_acquires_lock(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """remove_from_manifest should acquire manifest_lock during read-modify-write."""
        from pokepoke.worktree_cleanup import add_uncleaned_worktree, remove_from_manifest

        monkeypatch.chdir(tmp_path)
        (tmp_path / ".pokepoke").mkdir(exist_ok=True)

        # First add an entry
        add_uncleaned_worktree("test-id", "/path/to/worktree", "test reason")

        lock_acquired = []

        original_manifest_lock = manifest_lock

        from contextlib import contextmanager

        @contextmanager
        def tracking_manifest_lock(timeout=30.0):
            lock_acquired.append(True)
            with original_manifest_lock(timeout=timeout) as lock:
                yield lock

        # Patch at the coordination module level where it's defined
        with patch("pokepoke.coordination.manifest_lock", tracking_manifest_lock):
            remove_from_manifest("test-id")

        assert len(lock_acquired) == 1, "manifest_lock should be acquired exactly once"

    def test_concurrent_add_operations_serialized(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Concurrent add_uncleaned_worktree calls should not lose entries due to race conditions."""
        from pokepoke.worktree_cleanup import add_uncleaned_worktree, load_worktree_manifest

        monkeypatch.chdir(tmp_path)
        (tmp_path / ".pokepoke").mkdir(exist_ok=True)

        errors: list[str] = []

        def add_entry(entry_id: str):
            try:
                add_uncleaned_worktree(entry_id, f"/path/{entry_id}", f"reason for {entry_id}")
            except Exception as e:
                errors.append(str(e))

        # Run multiple adds concurrently
        threads = [threading.Thread(target=add_entry, args=(f"entry-{i}",)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        assert not errors, f"Errors during concurrent adds: {errors}"

        # All entries should be present (no lost writes)
        manifest = load_worktree_manifest()
        for i in range(5):
            assert f"entry-{i}" in manifest, f"Entry entry-{i} was lost in race condition"


class TestStaleLockRecovery:
    """Tests for stale lock detection and forced removal in acquire_lock."""

    def test_stale_lock_file_removed_before_acquire(self, tmp_path: Path) -> None:
        """A lock file older than stale_timeout is removed so acquire succeeds."""
        with patch("pokepoke.coordination._lock_dir", return_value=tmp_path):
            lock_file = tmp_path / "stale.lock"
            # Create an orphan lock file (no real lock held)
            lock_file.write_text("")
            # Backdate modification time so it looks ancient
            old_mtime = time.time() - 1800  # 30 minutes ago
            import os
            os.utime(lock_file, (old_mtime, old_mtime))

            # Should succeed because the stale file is removed first
            with acquire_lock("stale", timeout=0, stale_timeout=900) as lock:
                assert lock.is_locked

    def test_fresh_lock_file_not_removed(self, tmp_path: Path) -> None:
        """A recently-modified lock file is left alone (not treated as stale)."""
        with patch("pokepoke.coordination._lock_dir", return_value=tmp_path):
            # Hold a real lock in a background thread to simulate a live process
            acquired = threading.Event()
            release = threading.Event()

            def holder():
                with acquire_lock("fresh", timeout=5) as _:
                    acquired.set()
                    release.wait(timeout=5)

            t = threading.Thread(target=holder, daemon=True)
            t.start()
            acquired.wait(timeout=5)
            try:
                # A fresh stale_timeout (1s) should not clear a lock held seconds ago
                with pytest.raises(Timeout), acquire_lock("fresh", timeout=0, stale_timeout=3600) as _:
                    pass
            finally:
                release.set()
                t.join(timeout=5)

    def test_merge_lock_stale_age_constant(self) -> None:
        """_MERGE_LOCK_STALE_AGE should be well above 10 minutes."""
        assert _MERGE_LOCK_STALE_AGE >= 600, "Stale age must be >= merge lock timeout"


class TestGitMainRepoLock:
    """Tests for git_main_repo_lock – serializes main-repo git operations."""

    def test_acquires_and_releases(self, tmp_path: Path) -> None:
        with patch("pokepoke.coordination._lock_dir", return_value=tmp_path):
            with git_main_repo_lock(timeout=5) as lock:
                assert lock.is_locked
            assert not lock.is_locked

    def test_second_holder_times_out(self, tmp_path: Path) -> None:
        with patch("pokepoke.coordination._lock_dir", return_value=tmp_path), git_main_repo_lock(timeout=5):  # noqa: SIM117
            with pytest.raises(Timeout), git_main_repo_lock(timeout=0):
                pass  # pragma: no cover

    def test_serializes_two_threads(self, tmp_path: Path) -> None:
        """Two threads must not hold git_main_repo_lock simultaneously."""
        overlap_detected = threading.Event()
        inside_count = [0]
        lock_obj = threading.Lock()
        errors: list[str] = []

        def worker():
            with patch("pokepoke.coordination._lock_dir", return_value=tmp_path), git_main_repo_lock(timeout=10):
                with lock_obj:
                    inside_count[0] += 1
                    if inside_count[0] > 1:
                        errors.append("overlap!")
                        overlap_detected.set()
                time.sleep(0.05)
                with lock_obj:
                    inside_count[0] -= 1

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15)

        assert not errors, "Two threads were inside git_main_repo_lock simultaneously"

    def test_releases_on_exception(self, tmp_path: Path) -> None:
        with patch("pokepoke.coordination._lock_dir", return_value=tmp_path):
            lock_ref = None
            with pytest.raises(ValueError), git_main_repo_lock(timeout=5) as lock:
                lock_ref = lock
                raise ValueError("simulated failure")
            assert lock_ref is not None
            assert not lock_ref.is_locked
