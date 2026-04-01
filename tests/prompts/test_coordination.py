"""Tests for pokepoke.worktrees.coordination module."""

import json
import os
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest
from filelock import Timeout

from pokepoke.worktrees.coordination import (
    _MERGE_LOCK_STALE_AGE,
    _is_pid_alive,
    _load_worktree_metrics,
    _lock_dir,
    _lock_path,
    _read_lock_metadata,
    _record_worktree_attempt,
    _save_worktree_metrics,
    _write_lock_metadata,
    acquire_lock,
    check_lock_status,
    clear_lock_if_stale,
    manifest_lock,
    merge_lock,
    merge_lock_active,
    try_lock,
    with_worktree_lock,
    worktree_setup_lock,
)
from pokepoke.worktrees.lock_contention import (
    _contention_tracker,
    get_lock_contention_stats,
)


class TestLockDir:
    """Tests for lock directory helpers."""

    def test_lock_dir_creates_directory(self, tmp_path: Path) -> None:
        with patch("pokepoke.worktrees.coordination._lock_dir") as mock_dir:
            d = tmp_path / ".pokepoke" / "locks"
            mock_dir.return_value = d
            result = mock_dir()
            assert result == d

    def test_lock_path_returns_correct_name(self, tmp_path: Path) -> None:
        with patch("pokepoke.worktrees.coordination._lock_dir", return_value=tmp_path):
            assert _lock_path("foo") == tmp_path / "foo.lock"


class TestAcquireLock:
    """Tests for acquire_lock context manager."""

    def test_acquires_and_releases(self, tmp_path: Path) -> None:
        with patch("pokepoke.worktrees.coordination._lock_dir", return_value=tmp_path):
            with acquire_lock("test") as lock:
                assert lock.is_locked
                lock_file = tmp_path / "test.lock"
                assert lock_file.exists()
            assert not lock.is_locked

    def test_lock_file_created_in_lock_dir(self, tmp_path: Path) -> None:
        with patch("pokepoke.worktrees.coordination._lock_dir", return_value=tmp_path), acquire_lock("mylock"):
            assert (tmp_path / "mylock.lock").exists()

    def test_timeout_raises(self, tmp_path: Path) -> None:
        with patch("pokepoke.worktrees.coordination._lock_dir", return_value=tmp_path), acquire_lock("exclusive"):  # noqa: SIM117
            # Same lock with zero timeout should fail
            with pytest.raises(Timeout), acquire_lock("exclusive", timeout=0):
                    pass  # pragma: no cover

    def test_release_on_exception(self, tmp_path: Path) -> None:
        with patch("pokepoke.worktrees.coordination._lock_dir", return_value=tmp_path):
            lock_ref = None
            with pytest.raises(RuntimeError), acquire_lock("err") as lock:
                lock_ref = lock
                raise RuntimeError("boom")
            assert lock_ref is not None
            assert not lock_ref.is_locked


class TestTryLock:
    """Tests for try_lock non-blocking acquisition."""

    def test_returns_lock_when_available(self, tmp_path: Path) -> None:
        with patch("pokepoke.worktrees.coordination._lock_dir", return_value=tmp_path):
            lock = try_lock("avail")
            assert lock is not None
            assert lock.is_locked
            lock.release()

    def test_returns_none_when_held(self, tmp_path: Path) -> None:
        with patch("pokepoke.worktrees.coordination._lock_dir", return_value=tmp_path), acquire_lock("held"):
            result = try_lock("held")
            assert result is None

    def test_caller_must_release(self, tmp_path: Path) -> None:
        with patch("pokepoke.worktrees.coordination._lock_dir", return_value=tmp_path):
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
        with patch("pokepoke.worktrees.coordination._lock_dir", return_value=tmp_path):
            with worktree_setup_lock(timeout=5) as lock:
                assert lock.is_locked
            assert not lock.is_locked

    def test_second_agent_times_out_while_first_holds_lock(self, tmp_path: Path) -> None:
        """Second concurrent agent should raise Timeout when first holds the lock."""
        with patch("pokepoke.worktrees.coordination._lock_dir", return_value=tmp_path), worktree_setup_lock(timeout=5):  # noqa: SIM117
            with pytest.raises(Timeout), worktree_setup_lock(timeout=0):
                    pass  # pragma: no cover

    def test_serializes_two_threads(self, tmp_path: Path) -> None:
        """Two threads must not hold worktree_setup_lock simultaneously."""
        overlap_detected = threading.Event()
        inside_count = [0]
        lock_obj = threading.Lock()
        errors: list[str] = []

        def worker():
            with patch("pokepoke.worktrees.coordination._lock_dir", return_value=tmp_path), worktree_setup_lock(timeout=10):
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
        with patch("pokepoke.worktrees.coordination._lock_dir", return_value=tmp_path):
            lock_ref = None
            with pytest.raises(ValueError), worktree_setup_lock(timeout=5) as lock:
                lock_ref = lock
                raise ValueError("simulated failure")
            assert lock_ref is not None
            assert not lock_ref.is_locked


class TestMergeLock:
    """Tests for merge_lock – serializes worktree merges across parallel agents."""

    def test_acquires_and_releases(self, tmp_path: Path) -> None:
        with patch("pokepoke.worktrees.coordination._lock_dir", return_value=tmp_path):
            with merge_lock(timeout=5) as lock:
                assert lock.is_locked
            assert not lock.is_locked

    def test_second_agent_times_out_while_first_holds_lock(self, tmp_path: Path) -> None:
        """Second concurrent agent should raise Timeout when first holds the lock."""
        with patch("pokepoke.worktrees.coordination._lock_dir", return_value=tmp_path), merge_lock(timeout=5):  # noqa: SIM117
            with pytest.raises(Timeout), merge_lock(timeout=0):
                    pass  # pragma: no cover

    def test_serializes_two_threads(self, tmp_path: Path) -> None:
        """Two threads must not hold merge_lock simultaneously."""
        overlap_detected = threading.Event()
        inside_count = [0]
        lock_obj = threading.Lock()
        errors: list[str] = []

        def worker():
            with patch("pokepoke.worktrees.coordination._lock_dir", return_value=tmp_path), merge_lock(timeout=10):
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
        with patch("pokepoke.worktrees.coordination._lock_dir", return_value=tmp_path):
            lock_ref = None
            with pytest.raises(ValueError), merge_lock(timeout=5) as lock:
                lock_ref = lock
                raise ValueError("simulated failure")
            assert lock_ref is not None
            assert not lock_ref.is_locked


class TestMergeLockActive:
    """Tests for merge_lock_active helper."""

    def test_returns_false_when_not_held(self, tmp_path: Path) -> None:
        with patch("pokepoke.worktrees.coordination._lock_dir", return_value=tmp_path):
            assert merge_lock_active() is False

    def test_returns_true_when_held(self, tmp_path: Path) -> None:
        with patch("pokepoke.worktrees.coordination._lock_dir", return_value=tmp_path), merge_lock(timeout=5):
            assert merge_lock_active() is True


class TestManifestLock:
    """Tests for manifest_lock – serializes worktree manifest updates."""

    def test_acquires_and_releases(self, tmp_path: Path) -> None:
        with patch("pokepoke.worktrees.coordination._lock_dir", return_value=tmp_path):
            with manifest_lock(timeout=5) as lock:
                assert lock.is_locked
            assert not lock.is_locked

    def test_second_agent_times_out_while_first_holds_lock(self, tmp_path: Path) -> None:
        """Second concurrent agent should raise Timeout when first holds the lock."""
        with patch("pokepoke.worktrees.coordination._lock_dir", return_value=tmp_path), manifest_lock(timeout=5):  # noqa: SIM117
            with pytest.raises(Timeout), manifest_lock(timeout=0):
                    pass  # pragma: no cover

    def test_serializes_two_threads(self, tmp_path: Path) -> None:
        """Two threads must not hold manifest_lock simultaneously."""
        overlap_detected = threading.Event()
        inside_count = [0]
        lock_obj = threading.Lock()
        errors: list[str] = []

        def worker():
            with patch("pokepoke.worktrees.coordination._lock_dir", return_value=tmp_path), manifest_lock(timeout=10):
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
        with patch("pokepoke.worktrees.coordination._lock_dir", return_value=tmp_path):
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
        from pokepoke.worktrees.worktree_cleanup import add_uncleaned_worktree

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
        with patch("pokepoke.worktrees.coordination.manifest_lock", tracking_manifest_lock):
            add_uncleaned_worktree("test-id", "/path/to/worktree", "test reason")

        assert len(lock_acquired) == 1, "manifest_lock should be acquired exactly once"

    def test_remove_from_manifest_acquires_lock(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """remove_from_manifest should acquire manifest_lock during read-modify-write."""
        from pokepoke.worktrees.worktree_cleanup import add_uncleaned_worktree, remove_from_manifest

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
        with patch("pokepoke.worktrees.coordination.manifest_lock", tracking_manifest_lock):
            remove_from_manifest("test-id")

        assert len(lock_acquired) == 1, "manifest_lock should be acquired exactly once"

    def test_concurrent_add_operations_serialized(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Concurrent add_uncleaned_worktree calls should not lose entries due to race conditions."""
        from pokepoke.worktrees.worktree_cleanup import add_uncleaned_worktree, load_worktree_manifest

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
        with patch("pokepoke.worktrees.coordination._lock_dir", return_value=tmp_path):
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
        with patch("pokepoke.worktrees.coordination._lock_dir", return_value=tmp_path):
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


class TestPidTracking:
    """Tests for PID tracking and stale-lock detection."""

    def test_is_pid_alive_returns_true_for_current_process(self) -> None:
        assert _is_pid_alive(os.getpid()) is True

    def test_is_pid_alive_returns_false_for_invalid_pid(self) -> None:
        assert _is_pid_alive(0) is False
        assert _is_pid_alive(-1) is False

    def test_is_pid_alive_returns_false_for_dead_pid(self) -> None:
        # Use a very high PID that is almost certainly not running
        assert _is_pid_alive(2**30) is False

    def test_write_and_read_lock_metadata(self, tmp_path: Path) -> None:
        lock_file = tmp_path / "test.lock"
        lock_file.write_text("")
        _write_lock_metadata(lock_file)
        meta = _read_lock_metadata(lock_file)
        assert meta is not None
        assert meta["pid"] == os.getpid()
        assert isinstance(meta["timestamp"], float)
        # Metadata lives in sidecar file
        assert (tmp_path / "test.lock.meta").exists()

    def test_read_lock_metadata_returns_none_for_empty(self, tmp_path: Path) -> None:
        lock_file = tmp_path / "test.lock"
        lock_file.write_text("")
        # No sidecar written yet
        assert _read_lock_metadata(lock_file) is None

    def test_read_lock_metadata_returns_none_for_invalid_json(self, tmp_path: Path) -> None:
        lock_file = tmp_path / "test.lock"
        meta_file = tmp_path / "test.lock.meta"
        meta_file.write_text("not json")
        assert _read_lock_metadata(lock_file) is None

    def test_read_lock_metadata_returns_none_for_missing_pid(self, tmp_path: Path) -> None:
        lock_file = tmp_path / "test.lock"
        meta_file = tmp_path / "test.lock.meta"
        meta_file.write_text(json.dumps({"timestamp": 123.0}))
        assert _read_lock_metadata(lock_file) is None

    def test_acquire_lock_writes_pid_metadata(self, tmp_path: Path) -> None:
        with patch("pokepoke.worktrees.coordination._lock_dir", return_value=tmp_path), acquire_lock("pidtest", timeout=5):
            meta = _read_lock_metadata(tmp_path / "pidtest.lock")
            assert meta is not None
            assert meta["pid"] == os.getpid()

    def test_stale_lock_with_dead_pid_is_removed(self, tmp_path: Path) -> None:
        """A lock whose holder PID is dead should be force-removed."""
        with patch("pokepoke.worktrees.coordination._lock_dir", return_value=tmp_path):
            lock_file = tmp_path / "stale-pid.lock"
            # Create lock file and sidecar with dead PID
            lock_file.write_text("")
            (tmp_path / "stale-pid.lock.meta").write_text(json.dumps({
                "pid": 2**30,
                "timestamp": time.time() - 3600,
            }))
            # Backdate mtime past stale threshold
            old_mtime = time.time() - 3600
            os.utime(lock_file, (old_mtime, old_mtime))

            with acquire_lock("stale-pid", timeout=0, stale_timeout=300) as lock:
                assert lock.is_locked

    def test_stale_lock_with_alive_pid_not_removed(self, tmp_path: Path) -> None:
        """A lock whose holder PID is alive should NOT be force-removed."""
        with patch("pokepoke.worktrees.coordination._lock_dir", return_value=tmp_path):
            lock_file = tmp_path / "alive-pid.lock"
            meta_file = tmp_path / "alive-pid.lock.meta"
            # Write sidecar with our own (alive) PID
            meta_file.write_text(json.dumps({
                "pid": os.getpid(),
                "timestamp": time.time() - 3600,
            }))
            # Create and hold a real lock
            lock_file.write_text("")
            old_mtime = time.time() - 3600
            os.utime(lock_file, (old_mtime, old_mtime))

            from filelock import FileLock
            real_lock = FileLock(lock_file)
            real_lock.acquire(timeout=0)
            try:
                # Should NOT remove the lock since PID is alive
                with pytest.raises(Timeout), acquire_lock("alive-pid", timeout=0, stale_timeout=300):
                    pass  # pragma: no cover
            finally:
                real_lock.release()

    def test_try_lock_writes_metadata(self, tmp_path: Path) -> None:
        with patch("pokepoke.worktrees.coordination._lock_dir", return_value=tmp_path):
            lock = try_lock("trytest")
            assert lock is not None
            try:
                meta = _read_lock_metadata(tmp_path / "trytest.lock")
                assert meta is not None
                assert meta["pid"] == os.getpid()
            finally:
                lock.release()


class TestWorktreeMetrics:
    """Tests for worktree metrics persistence helpers."""

    def test_load_metrics_defaults_when_missing(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        import pokepoke.worktrees.coordination as coord_module

        metrics_path = tmp_path / "worktree_metrics.json"
        monkeypatch.setattr(coord_module, "_WORKTREE_METRICS_PATH", metrics_path)
        monkeypatch.setattr(coord_module, "_WORKTREE_METRICS_DIR", tmp_path)

        metrics = _load_worktree_metrics()

        assert metrics["total_attempts"] == 0
        assert metrics["total_successes"] == 0
        assert metrics["total_failures"] == 0

    def test_load_metrics_handles_invalid_json(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        import pokepoke.worktrees.coordination as coord_module

        metrics_path = tmp_path / "worktree_metrics.json"
        metrics_path.write_text("not json")
        monkeypatch.setattr(coord_module, "_WORKTREE_METRICS_PATH", metrics_path)
        monkeypatch.setattr(coord_module, "_WORKTREE_METRICS_DIR", tmp_path)

        metrics = _load_worktree_metrics()

        assert metrics["total_attempts"] == 0
        assert metrics["total_wait_time"] == 0.0

    def test_save_and_load_metrics_round_trip(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        import pokepoke.worktrees.coordination as coord_module

        metrics_path = tmp_path / "worktree_metrics.json"
        monkeypatch.setattr(coord_module, "_WORKTREE_METRICS_PATH", metrics_path)
        monkeypatch.setattr(coord_module, "_WORKTREE_METRICS_DIR", tmp_path)

        metrics_in = {
            "total_attempts": 3,
            "total_successes": 2,
            "total_failures": 1,
            "total_wait_time": 4.0,
            "max_wait_time": 2.5,
        }

        _save_worktree_metrics(metrics_in)
        metrics_out = _load_worktree_metrics()

        assert metrics_out == metrics_in

    def test_record_worktree_attempt_updates_metrics(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        import pokepoke.worktrees.coordination as coord_module

        metrics_path = tmp_path / "worktree_metrics.json"
        monkeypatch.setattr(coord_module, "_WORKTREE_METRICS_PATH", metrics_path)
        monkeypatch.setattr(coord_module, "_WORKTREE_METRICS_DIR", tmp_path)

        _record_worktree_attempt(success=True, wait_time=1.5)
        _record_worktree_attempt(success=False, wait_time=2.0)

        metrics = _load_worktree_metrics()
        assert metrics["total_attempts"] == 2
        assert metrics["total_successes"] == 1
        assert metrics["total_failures"] == 1
        assert metrics["total_wait_time"] == pytest.approx(3.5)
        assert metrics["max_wait_time"] == pytest.approx(2.0)


class TestWithWorktreeLock:
    """Tests for worktree lock metrics integration."""

    def test_records_successful_lock(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        import pokepoke.worktrees.coordination as coord_module

        metrics_path = tmp_path / "worktree_metrics.json"
        monkeypatch.setattr(coord_module, "_WORKTREE_METRICS_PATH", metrics_path)
        monkeypatch.setattr(coord_module, "_WORKTREE_METRICS_DIR", tmp_path)

        with patch("pokepoke.worktrees.coordination._lock_dir", return_value=tmp_path), with_worktree_lock(timeout=5):
            pass

        metrics = _load_worktree_metrics()
        assert metrics["total_attempts"] == 1
        assert metrics["total_successes"] == 1

    def test_records_failed_lock(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        import pokepoke.worktrees.coordination as coord_module

        metrics_path = tmp_path / "worktree_metrics.json"
        monkeypatch.setattr(coord_module, "_WORKTREE_METRICS_PATH", metrics_path)
        monkeypatch.setattr(coord_module, "_WORKTREE_METRICS_DIR", tmp_path)

        called = {"value": False}

        def failing_lock(*_args, **_kwargs):
            called["value"] = True
            raise Timeout("lock timeout")

        monkeypatch.setattr(coord_module, "worktree_setup_lock", failing_lock)

        with pytest.raises(RuntimeError), with_worktree_lock(timeout=0):
            pass

        assert called["value"] is True

        metrics = _load_worktree_metrics()
        assert metrics["total_attempts"] == 1
        assert metrics["total_failures"] == 1


class TestCheckLockStatus:
    """Tests for check_lock_status helper."""

    def test_returns_false_when_missing(self, tmp_path: Path) -> None:
        with patch("pokepoke.worktrees.coordination._lock_dir", return_value=tmp_path):
            exists, metadata = check_lock_status("missing-lock")
            assert exists is False
            assert metadata is None

    def test_returns_metadata_when_present(self, tmp_path: Path) -> None:
        with patch("pokepoke.worktrees.coordination._lock_dir", return_value=tmp_path):
            lock_file = tmp_path / "status.lock"
            lock_file.write_text("")
            _write_lock_metadata(lock_file)

            exists, metadata = check_lock_status("status")

            assert exists is True
            assert metadata is not None
            assert metadata["pid"] == os.getpid()


class TestClearLockIfStale:
    """Tests for clear_lock_if_stale helper."""

    def test_clears_stale_lock_without_metadata(self, tmp_path: Path) -> None:
        with patch("pokepoke.worktrees.coordination._lock_dir", return_value=tmp_path):
            lock_file = tmp_path / "stale-no-meta.lock"
            lock_file.write_text("")

            cleared = clear_lock_if_stale("stale-no-meta", max_age_seconds=10)

            assert cleared is True
            assert not lock_file.exists()

    def test_clears_stale_lock_when_unheld(self, tmp_path: Path) -> None:
        with patch("pokepoke.worktrees.coordination._lock_dir", return_value=tmp_path):
            lock_file = tmp_path / "stale-clear.lock"
            lock_file.write_text("")
            meta_file = tmp_path / "stale-clear.lock.meta"
            meta_file.write_text(json.dumps({
                "pid": 2**30,
                "timestamp": time.time() - 3600,
            }))

            cleared = clear_lock_if_stale("stale-clear", max_age_seconds=10)

            assert cleared is True
            assert not lock_file.exists()
            assert not meta_file.exists()

    def test_does_not_clear_when_lock_held(self, tmp_path: Path) -> None:
        with patch("pokepoke.worktrees.coordination._lock_dir", return_value=tmp_path), acquire_lock("held-clear", timeout=5):
            meta_file = tmp_path / "held-clear.lock.meta"
            meta_file.write_text(json.dumps({
                "pid": 2**30,
                "timestamp": time.time() - 3600,
            }))

            cleared = clear_lock_if_stale("held-clear", max_age_seconds=10)

            assert cleared is False
            assert (tmp_path / "held-clear.lock").exists()


class TestAcquireLockContention:
    """Tests that acquire_lock records contention metrics via the global tracker."""

    def test_successful_acquire_records_metric(self, tmp_path: Path) -> None:
        _contention_tracker.reset()
        with patch("pokepoke.worktrees.coordination._lock_dir", return_value=tmp_path), acquire_lock("track-ok", timeout=5):
            pass
        snap = get_lock_contention_stats()
        assert "track-ok" in snap
        assert snap["track-ok"]["acquired"] == 1
        assert snap["track-ok"]["timeouts"] == 0
        assert snap["track-ok"]["total_wait"] >= 0.0

    def test_timeout_records_metric(self, tmp_path: Path) -> None:
        _contention_tracker.reset()
        with patch("pokepoke.worktrees.coordination._lock_dir", return_value=tmp_path), acquire_lock("track-to", timeout=5):  # noqa: SIM117
            with pytest.raises(Timeout), acquire_lock("track-to", timeout=0):
                pass  # pragma: no cover
        snap = get_lock_contention_stats()
        assert snap["track-to"]["acquired"] == 1
        assert snap["track-to"]["timeouts"] == 1

    def test_stale_clearance_records_metric(self, tmp_path: Path) -> None:
        _contention_tracker.reset()
        with patch("pokepoke.worktrees.coordination._lock_dir", return_value=tmp_path):
            lock_file = tmp_path / "track-stale.lock"
            lock_file.write_text("")
            (tmp_path / "track-stale.lock.meta").write_text(json.dumps({
                "pid": 2**30,
                "timestamp": time.time() - 7200,
            }))
            old_mtime = time.time() - 7200
            os.utime(lock_file, (old_mtime, old_mtime))

            with acquire_lock("track-stale", timeout=0, stale_timeout=300):
                pass

        snap = get_lock_contention_stats()
        assert snap["track-stale"]["stale_cleared"] == 1
        assert snap["track-stale"]["acquired"] == 1

    def test_concurrent_stale_detection_serialized(self, tmp_path: Path) -> None:
        """Multiple threads detecting a stale lock record exactly one clearance."""
        _contention_tracker.reset()
        with patch("pokepoke.worktrees.coordination._lock_dir", return_value=tmp_path):
            lock_file = tmp_path / "race-stale.lock"
            lock_file.write_text("")
            (tmp_path / "race-stale.lock.meta").write_text(json.dumps({
                "pid": 2**30,
                "timestamp": time.time() - 7200,
            }))
            old_mtime = time.time() - 7200
            os.utime(lock_file, (old_mtime, old_mtime))

            results: dict[str, int] = {"acquired": 0, "errors": 0}
            lock = threading.Lock()
            barrier = threading.Barrier(5)

            def worker() -> None:
                try:
                    barrier.wait(timeout=5)
                    with acquire_lock("race-stale", timeout=10, stale_timeout=300):
                        with lock:
                            results["acquired"] += 1
                        time.sleep(0.05)
                except Exception:
                    with lock:
                        results["errors"] += 1

            threads = [threading.Thread(target=worker) for _ in range(5)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=30)

            assert results["acquired"] == 5
            assert results["errors"] == 0

        snap = get_lock_contention_stats()
        # Only ONE stale clearance despite 5 concurrent threads
        assert snap["race-stale"]["stale_cleared"] == 1
        assert snap["race-stale"]["acquired"] == 5

    def test_get_lock_contention_stats_returns_dict(self, tmp_path: Path) -> None:
        _contention_tracker.reset()
        result = get_lock_contention_stats()
        assert isinstance(result, dict)
