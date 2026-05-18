"""Tests for worktree coordination and locking mechanisms."""

import contextlib
import threading
import time
from pathlib import Path

import pytest

from pokepoke.worktrees.coordination import (
    _load_worktree_metrics as _load_metrics,
)
from pokepoke.worktrees.coordination import (
    _lock_dir,
    with_worktree_lock,
)
from pokepoke.worktrees.coordination import (
    _record_worktree_attempt as _record_attempt,
)


def _worktree_lock_path() -> Path:
    """Return the lock file path dynamically (CWD-relative)."""
    return _lock_dir() / "worktree-setup.lock"


@pytest.fixture
def isolated_metrics(tmp_path, monkeypatch):
    """Provide an isolated metrics file for each test."""
    import pokepoke.worktrees.coordination as coord_module

    # Create isolated paths for this test
    test_stats_dir = tmp_path / "stats"
    test_metrics_path = test_stats_dir / "worktree_metrics.json"

    # Patch the canonical module constants
    original_stats_dir = coord_module._WORKTREE_METRICS_DIR
    original_metrics_path = coord_module._WORKTREE_METRICS_PATH

    coord_module._WORKTREE_METRICS_DIR = test_stats_dir
    coord_module._WORKTREE_METRICS_PATH = test_metrics_path

    yield test_metrics_path

    # Restore original constants
    coord_module._WORKTREE_METRICS_DIR = original_stats_dir
    coord_module._WORKTREE_METRICS_PATH = original_metrics_path


@pytest.fixture
def cleanup_lock_files():
    """Clean up lock and metrics files after each test."""
    yield
    # Clean up lock file
    if _worktree_lock_path().exists():
        with contextlib.suppress(Exception):
            _worktree_lock_path().unlink()


def test_with_worktree_lock_basic(cleanup_lock_files, tmp_path, monkeypatch):
    """Test basic lock acquisition and release."""
    import os
    lock_dir = tmp_path / ".pokepoke" / "locks"

    def _isolated_lock_dir():
        os.makedirs(lock_dir, exist_ok=True)
        return lock_dir

    monkeypatch.setattr("pokepoke.worktrees.coordination._lock_dir", _isolated_lock_dir)
    lock_path = lock_dir / "worktree-setup.lock"
    # Lock should be acquired and released without error
    with with_worktree_lock(timeout=5):
        # Verify lock file exists while locked
        assert lock_path.exists()

    # Lock file may or may not exist after release depending on platform


def test_with_worktree_lock_serializes_operations(cleanup_lock_files):
    """Test that lock properly serializes concurrent operations."""
    results = []
    lock_acquired_count = [0]
    lock = threading.Lock()

    def worker(worker_id: int):
        """Worker thread that acquires worktree lock."""
        with with_worktree_lock(timeout=10):
            # Increment counter under thread lock
            with lock:
                lock_acquired_count[0] += 1
                current_count = lock_acquired_count[0]

            # Simulate worktree creation work
            time.sleep(0.1)

            # Record result - only one worker should hold lock at a time
            results.append({
                "worker_id": worker_id,
                "lock_count": current_count,
            })

    # Launch 5 workers concurrently
    threads = []
    for i in range(5):
        t = threading.Thread(target=worker, args=(i,))
        threads.append(t)
        t.start()

    # Wait for all workers to complete
    for t in threads:
        t.join(timeout=15)

    # All workers should have completed
    assert len(results) == 5

    # Lock counter should reach 5
    assert lock_acquired_count[0] == 5

    # Verify serialization - each worker should see a unique count
    counts = [r["lock_count"] for r in results]
    assert sorted(counts) == [1, 2, 3, 4, 5]


def test_with_worktree_lock_timeout(cleanup_lock_files):
    """Test that lock times out appropriately."""
    lock_holder_started = threading.Event()

    def long_holder():
        """Hold lock for longer than timeout."""
        with with_worktree_lock(timeout=10):
            lock_holder_started.set()
            time.sleep(1)  # Hold for 1 second

    # Start thread that holds lock
    holder_thread = threading.Thread(target=long_holder)
    holder_thread.start()

    # Wait for holder to acquire lock
    assert lock_holder_started.wait(timeout=5), "Lock holder didn't start"

    # Try to acquire with short timeout - should fail
    with pytest.raises(RuntimeError, match="Timed out waiting for worktree lock"), with_worktree_lock(timeout=0.5):
        pass

    # Wait for holder to finish
    holder_thread.join(timeout=10)


def test_metrics_recording(isolated_metrics):
    """Test that metrics are properly recorded."""
    # Record some attempts
    _record_attempt(success=True, wait_time=0.5)
    _record_attempt(success=True, wait_time=1.2)
    _record_attempt(success=False, wait_time=5.0)

    # Load and verify metrics
    metrics = _load_metrics()
    assert metrics.total_attempts == 3
    assert metrics.total_successes == 2
    assert metrics.total_failures == 1
    assert metrics.total_wait_time == 6.7  # 0.5 + 1.2 + 5.0
    assert metrics.max_wait_time == 5.0


def test_metrics_persistence(isolated_metrics):
    """Test that metrics persist across multiple loads."""
    # Record first attempt
    _record_attempt(success=True, wait_time=1.0)

    # Record second attempt (should add to first)
    _record_attempt(success=True, wait_time=2.0)

    # Load metrics
    metrics = _load_metrics()
    assert metrics.total_attempts == 2
    assert metrics.total_successes == 2
    assert metrics.total_wait_time == 3.0
    assert metrics.max_wait_time == 2.0


def test_lock_creates_directories(cleanup_lock_files, tmp_path, monkeypatch):
    """Test that lock creation ensures required directories exist."""
    from unittest.mock import patch

    # Use a temporary lock directory so the test is isolated
    with patch("pokepoke.worktrees.coordination._lock_dir", return_value=tmp_path), with_worktree_lock(timeout=5):
            # Lock file should exist in the patched directory
            assert (tmp_path / "worktree-setup.lock").exists()


def test_concurrent_lock_acquisition_stress(cleanup_lock_files):
    """Stress test with many concurrent workers."""
    num_workers = 20
    results = {"success": 0, "failed": 0}
    lock = threading.Lock()

    def worker(worker_id: int):
        """Worker that tries to acquire lock."""
        try:
            with with_worktree_lock(timeout=30):
                # Simulate brief work
                time.sleep(0.05)
            with lock:
                results["success"] += 1
        except Exception:
            with lock:
                results["failed"] += 1

    # Launch all workers
    threads = []
    for i in range(num_workers):
        t = threading.Thread(target=worker, args=(i,))
        threads.append(t)
        t.start()

    # Wait for completion
    for t in threads:
        t.join(timeout=60)

    # All workers should succeed
    assert results["success"] == num_workers
    assert results["failed"] == 0


class TestMainRepoGitLock:
    """Tests for the main_repo_git_lock threading primitive."""

    def test_mutual_exclusion(self):
        """Two threads cannot hold main_repo_git_lock simultaneously."""
        from pokepoke.worktrees.coordination import main_repo_git_lock

        overlap_detected = threading.Event()
        inside = threading.Event()
        done = threading.Event()

        def holder():
            with main_repo_git_lock():
                inside.set()
                # Hold the lock until the other thread has tried to acquire
                done.wait(timeout=5)

        def contender():
            inside.wait(timeout=5)
            # At this point, holder has the lock. We should block.
            with main_repo_git_lock():
                # If we reach here while holder still hasn't released, bad.
                if not done.is_set():
                    overlap_detected.set()
            done.set()

        t1 = threading.Thread(target=holder)
        t2 = threading.Thread(target=contender)
        t1.start()
        t2.start()

        # Let contender block briefly, then release holder
        time.sleep(0.1)
        done.set()

        t1.join(timeout=5)
        t2.join(timeout=5)

        assert not overlap_detected.is_set(), "Both threads held main_repo_git_lock at the same time"

    def test_reentrant(self):
        """The same thread can acquire main_repo_git_lock multiple times."""
        from pokepoke.worktrees.coordination import main_repo_git_lock

        with main_repo_git_lock(), main_repo_git_lock():
            pass  # Should not deadlock

    def test_context_manager_releases_on_exception(self):
        """Lock is released even if the body raises."""
        from pokepoke.worktrees.coordination import main_repo_git_lock

        with contextlib.suppress(RuntimeError), main_repo_git_lock():
            raise RuntimeError("boom")

        # Should be acquirable again
        with main_repo_git_lock():
            pass


class TestOwnedLockPaths:
    """Tests for the PID-based lock file registry."""

    def test_acquire_lock_tracks_path(self, tmp_path, monkeypatch):
        """Lock paths are added to _owned_lock_paths after acquire_lock."""
        import pokepoke.worktrees.coordination as coord

        lock_dir = tmp_path / "locks"
        lock_dir.mkdir()
        monkeypatch.setattr(coord, "_lock_dir", lambda: lock_dir)

        with coord.acquire_lock("test-track", timeout=5):
            owned = coord.get_owned_lock_paths()
            expected = lock_dir / "test-track.lock"
            assert expected in owned

    def test_acquire_lock_removes_path_on_exit(self, tmp_path, monkeypatch):
        """Lock paths are removed from _owned_lock_paths after context exit."""
        import pokepoke.worktrees.coordination as coord

        lock_dir = tmp_path / "locks"
        lock_dir.mkdir()
        monkeypatch.setattr(coord, "_lock_dir", lambda: lock_dir)

        expected = lock_dir / "test-remove.lock"
        with coord.acquire_lock("test-remove", timeout=5):
            assert expected in coord.get_owned_lock_paths()

        assert expected not in coord.get_owned_lock_paths()

    def test_try_lock_tracks_path(self, tmp_path, monkeypatch):
        """try_lock adds to _owned_lock_paths on success."""
        import pokepoke.worktrees.coordination as coord

        lock_dir = tmp_path / "locks"
        lock_dir.mkdir()
        monkeypatch.setattr(coord, "_lock_dir", lambda: lock_dir)

        lock = coord.try_lock("test-try")
        assert lock is not None
        try:
            expected = lock_dir / "test-try.lock"
            assert expected in coord.get_owned_lock_paths()
        finally:
            lock.release()
            with coord._owned_lock_paths_lock:
                coord._owned_lock_paths.discard(lock_dir / "test-try.lock")

    def test_get_owned_lock_paths_returns_snapshot(self, tmp_path, monkeypatch):
        """get_owned_lock_paths returns a list copy, not a live reference."""
        import pokepoke.worktrees.coordination as coord

        lock_dir = tmp_path / "locks"
        lock_dir.mkdir()
        monkeypatch.setattr(coord, "_lock_dir", lambda: lock_dir)

        with coord.acquire_lock("test-snap", timeout=5):
            snapshot = coord.get_owned_lock_paths()
            assert isinstance(snapshot, list)
            # Mutating snapshot must not affect internal set
            snapshot.clear()
            assert len(coord.get_owned_lock_paths()) > 0

    def test_get_related_files_returns_three_paths(self):
        """_get_related_files returns .lock, .lock.meta, .lock.break."""
        from pokepoke.worktrees.coordination import _get_related_files

        base = Path("/tmp/locks/test.lock")
        related = _get_related_files(base)

        assert len(related) == 3
        assert base in related
        assert base.with_suffix(".lock.meta") in related
        assert base.with_suffix(".lock.break") in related
