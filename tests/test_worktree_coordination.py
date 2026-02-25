"""Tests for worktree coordination and locking mechanisms."""

import json
import threading
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from pokepoke.worktree_coordination import (
    with_worktree_lock,
    _load_metrics,
    _save_metrics,
    _record_attempt,
    _LOCK_DIR,
    _WORKTREE_LOCK_PATH,
)


@pytest.fixture
def isolated_metrics(tmp_path, monkeypatch):
    """Provide an isolated metrics file for each test."""
    import pokepoke.worktree_coordination as coord_module
    
    # Create isolated paths for this test
    test_stats_dir = tmp_path / "stats"
    test_metrics_path = test_stats_dir / "worktree_metrics.json"
    
    # Patch module constants
    original_stats_dir = coord_module._STATS_DIR
    original_metrics_path = coord_module._METRICS_PATH
    
    coord_module._STATS_DIR = test_stats_dir
    coord_module._METRICS_PATH = test_metrics_path
    
    yield test_metrics_path
    
    # Restore original constants
    coord_module._STATS_DIR = original_stats_dir
    coord_module._METRICS_PATH = original_metrics_path


@pytest.fixture
def cleanup_lock_files():
    """Clean up lock and metrics files after each test."""
    yield
    # Clean up lock file
    if _WORKTREE_LOCK_PATH.exists():
        try:
            _WORKTREE_LOCK_PATH.unlink()
        except Exception:
            pass


def test_with_worktree_lock_basic(cleanup_lock_files):
    """Test basic lock acquisition and release."""
    # Lock should be acquired and released without error
    with with_worktree_lock(timeout=5):
        # Verify lock file exists while locked
        assert _WORKTREE_LOCK_PATH.exists()
    
    # Lock file should still exist but be unlocked
    # (filelock doesn't delete the lock file)
    assert _WORKTREE_LOCK_PATH.exists()


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
            time.sleep(3)  # Hold for 3 seconds
    
    # Start thread that holds lock
    holder_thread = threading.Thread(target=long_holder)
    holder_thread.start()
    
    # Wait for holder to acquire lock
    assert lock_holder_started.wait(timeout=5), "Lock holder didn't start"
    
    # Try to acquire with short timeout - should fail
    with pytest.raises(RuntimeError, match="Timed out waiting for worktree lock"):
        with with_worktree_lock(timeout=0.5):
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
    assert metrics["total_attempts"] == 3
    assert metrics["total_successes"] == 2
    assert metrics["total_failures"] == 1
    assert metrics["total_wait_time"] == 6.7  # 0.5 + 1.2 + 5.0
    assert metrics["max_wait_time"] == 5.0


def test_metrics_persistence(isolated_metrics):
    """Test that metrics persist across multiple loads."""
    # Record first attempt
    _record_attempt(success=True, wait_time=1.0)
    
    # Record second attempt (should add to first)
    _record_attempt(success=True, wait_time=2.0)
    
    # Load metrics
    metrics = _load_metrics()
    assert metrics["total_attempts"] == 2
    assert metrics["total_successes"] == 2
    assert metrics["total_wait_time"] == 3.0
    assert metrics["max_wait_time"] == 2.0


def test_lock_creates_directories(cleanup_lock_files, tmp_path, monkeypatch):
    """Test that lock creation ensures required directories exist."""
    # Use temporary directory for test
    test_lock_dir = tmp_path / "locks"
    test_lock_path = test_lock_dir / "test.lock"
    
    # Patch module constants
    import pokepoke.worktree_coordination as coord_module
    original_lock_dir = coord_module._LOCK_DIR
    original_lock_path = coord_module._WORKTREE_LOCK_PATH
    
    try:
        coord_module._LOCK_DIR = test_lock_dir
        coord_module._WORKTREE_LOCK_PATH = test_lock_path
        
        # Directory shouldn't exist yet
        assert not test_lock_dir.exists()
        
        # Acquire lock - should create directory
        with with_worktree_lock(timeout=5):
            assert test_lock_dir.exists()
            assert test_lock_path.exists()
    
    finally:
        # Restore original constants
        coord_module._LOCK_DIR = original_lock_dir
        coord_module._WORKTREE_LOCK_PATH = original_lock_path


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
