"""Boundary contract tests for the coordination <-> parallel_support module pair.

Verifies the implicit contract between ``pokepoke.worktrees.coordination``
and ``pokepoke.agents.parallel_support`` (plus ``parallel_worker_pool``),
covering:

* Lock acquisition patterns: threading.Lock passed through parallel_support helpers
* Worktree metrics shape: the dict persisted by coordination.py
* Lock metadata shape: PID/timestamp sidecar files
"""

from __future__ import annotations

import concurrent.futures
import json
import threading
import time
from unittest.mock import MagicMock, patch

from pokepoke.types import (
    AgentStats,
    BeadsWorkItem,
    SessionStats,
    WorkItemResult,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_item(item_id: str = "item-1", **kwargs) -> BeadsWorkItem:
    defaults = dict(
        id=item_id, title=f"Task {item_id}", status="in_progress",
        priority=1, issue_type="task",
    )
    defaults.update(kwargs)
    return BeadsWorkItem(**defaults)


def _make_session_stats() -> SessionStats:
    return SessionStats(agent_stats=AgentStats())


_Future = concurrent.futures.Future


# ===========================================================================
# 1. Lock acquisition patterns (threading.Lock through parallel_support)
# ===========================================================================


class TestLockAcquisitionPatterns:
    """parallel_support helpers accept an optional threading.Lock and use it
    consistently for all shared-state mutations."""

    def test_locked_has_futures_with_lock(self):
        """_locked_has_futures returns correct result under lock."""
        from pokepoke.agents.parallel_worker_pool import _locked_has_futures

        lock = threading.Lock()
        futures: dict[_Future[WorkItemResult], BeadsWorkItem] = {}

        assert _locked_has_futures(lock, futures) is False

        fut: _Future[WorkItemResult] = _Future()
        futures[fut] = _make_item()
        assert _locked_has_futures(lock, futures) is True

    def test_locked_has_futures_without_lock(self):
        """_locked_has_futures works in single-thread mode (lock=None)."""
        from pokepoke.agents.parallel_worker_pool import _locked_has_futures

        futures: dict[_Future[WorkItemResult], BeadsWorkItem] = {}
        assert _locked_has_futures(None, futures) is False

        fut: _Future[WorkItemResult] = _Future()
        futures[fut] = _make_item()
        assert _locked_has_futures(None, futures) is True

    def test_locked_futures_len_with_and_without_lock(self):
        """_locked_futures_len must return accurate count in both modes."""
        from pokepoke.agents.parallel_worker_pool import _locked_futures_len

        lock = threading.Lock()
        futures: dict[_Future[WorkItemResult], BeadsWorkItem] = {}

        assert _locked_futures_len(lock, futures) == 0
        assert _locked_futures_len(None, futures) == 0

        for i in range(3):
            fut: _Future[WorkItemResult] = _Future()
            futures[fut] = _make_item(f"item-{i}")

        assert _locked_futures_len(lock, futures) == 3
        assert _locked_futures_len(None, futures) == 3

    def test_locked_snapshot_returns_keys_and_len(self):
        """_locked_snapshot must return (list_of_futures, count)."""
        from pokepoke.agents.parallel_worker_pool import _locked_snapshot

        lock = threading.Lock()
        futures: dict[_Future[WorkItemResult], BeadsWorkItem] = {}

        keys, count = _locked_snapshot(lock, futures)
        assert keys == []
        assert count == 0

        fut: _Future[WorkItemResult] = _Future()
        futures[fut] = _make_item()
        keys, count = _locked_snapshot(lock, futures)
        assert len(keys) == 1
        assert count == 1
        assert keys[0] is fut

    def test_locked_add_to_set_with_lock(self):
        """_locked_add_to_set must add under lock protection."""
        from pokepoke.agents.parallel_worker_pool import _locked_add_to_set

        lock = threading.Lock()
        target: set[str] = set()
        _locked_add_to_set(lock, target, "id-1")
        assert "id-1" in target

    def test_locked_add_to_set_without_lock(self):
        """_locked_add_to_set must work when lock is None."""
        from pokepoke.agents.parallel_worker_pool import _locked_add_to_set

        target: set[str] = set()
        _locked_add_to_set(None, target, "id-2")
        assert "id-2" in target

    def test_locked_get_skip_and_active(self):
        """_locked_get_skip_and_active returns union of failed+attempted and active snapshot."""
        from pokepoke.agents.parallel_worker_pool import _locked_get_skip_and_active

        lock = threading.Lock()
        failed = {"f-1", "f-2"}
        attempted = {"a-1"}
        active = {"active-1", "active-2"}

        skip, active_snap = _locked_get_skip_and_active(lock, failed, attempted, active)
        assert skip == {"f-1", "f-2", "a-1"}
        assert active_snap == {"active-1", "active-2"}
        # Must be a copy, not the original reference
        assert active_snap is not active

    def test_update_failed_ids_adds_on_zero_request_failure(self):
        """_update_failed_ids adds item to failed set on non-exception failure with 0 requests."""
        from pokepoke.agents.parallel_worker_pool import _update_failed_ids

        lock = threading.Lock()
        failed: set[str] = set()

        _update_failed_ids(lock, failed, "item-1", success=False, was_exception=False, request_count=0)
        assert "item-1" in failed

    def test_update_failed_ids_removes_on_success(self):
        """_update_failed_ids removes item from failed set on success."""
        from pokepoke.agents.parallel_worker_pool import _update_failed_ids

        lock = threading.Lock()
        failed = {"item-1"}

        _update_failed_ids(lock, failed, "item-1", success=True, was_exception=False, request_count=1)
        assert "item-1" not in failed

    def test_update_failed_ids_no_add_on_exception(self):
        """_update_failed_ids should NOT add to failed set when was_exception=True."""
        from pokepoke.agents.parallel_worker_pool import _update_failed_ids

        lock = threading.Lock()
        failed: set[str] = set()

        _update_failed_ids(lock, failed, "item-1", success=False, was_exception=True, request_count=0)
        assert "item-1" not in failed

    def test_finalize_workers_empty_futures_returns_immediately(self):
        """finalize_workers with empty futures dict returns total_requests unchanged."""
        from pokepoke.agents.parallel_support import finalize_workers

        lock = threading.Lock()
        futures: dict[_Future[WorkItemResult], BeadsWorkItem] = {}
        stats = _make_session_stats()
        run_logger = MagicMock()
        record_fn = MagicMock()

        total, timeout_occurred = finalize_workers(
            futures, stats, time.time(), 5, run_logger, record_fn, lock,
        )
        assert total == 5
        assert timeout_occurred is False
        record_fn.assert_not_called()

    def test_finalize_workers_collects_completed_future(self):
        """finalize_workers must collect a completed future and call record_fn."""
        from pokepoke.agents.parallel_support import finalize_workers

        lock = threading.Lock()
        item = _make_item()
        fut: _Future[WorkItemResult] = _Future()
        fut.set_result(WorkItemResult(success=True, request_count=2))
        futures = {fut: item}
        stats = _make_session_stats()
        run_logger = MagicMock()
        record_fn = MagicMock()

        with patch("pokepoke.agents.parallel_support.terminal_ui") as mock_tui:
            mock_tui.ui = MagicMock()
            total, timeout_occurred = finalize_workers(
                futures, stats, time.time(), 0, run_logger, record_fn, lock,
            )

        assert total == 2
        assert timeout_occurred is False
        record_fn.assert_called_once()
        call_args = record_fn.call_args[0]
        assert call_args[0] is item  # first arg is the work item

    def test_lock_passed_through_drain_circuit_breaker(self):
        """drain_circuit_breaker passes lock to collect_fn and locked helpers."""
        from pokepoke.agents.parallel_support import drain_circuit_breaker

        lock = threading.Lock()
        futures: dict[_Future[WorkItemResult], BeadsWorkItem] = {}
        stats = _make_session_stats()
        run_logger = MagicMock()
        record_fn = MagicMock()

        # collect_fn returns (total_requests, any_success, successes, failures)
        collect_fn = MagicMock(return_value=(0, False, 0, 0))

        with patch("pokepoke.config.get_config") as mock_cfg:
            mock_cfg.return_value = MagicMock(circuit_breaker_drain_timeout=0)
            result = drain_circuit_breaker(
                futures, set(), 0, stats, run_logger, record_fn, collect_fn, "auto", lock,
            )

        assert isinstance(result, int)
        # collect_fn should have been called with lock as the last arg
        collect_fn.assert_called_once()
        assert collect_fn.call_args[0][-1] is lock

    def test_concurrent_lock_access_is_safe(self):
        """Multiple threads accessing futures dict through locked helpers must not corrupt state."""
        from pokepoke.agents.parallel_worker_pool import (
            _locked_has_futures,
            _locked_pop,
            _locked_register_dispatch,
        )

        lock = threading.Lock()
        futures: dict[_Future[WorkItemResult], BeadsWorkItem] = {}
        active: set[str] = set()
        errors: list[Exception] = []

        def _writer(idx: int) -> None:
            try:
                item = _make_item(f"concurrent-{idx}")
                fut: _Future[WorkItemResult] = _Future()
                _locked_register_dispatch(lock, futures, active, fut, item)
                assert _locked_has_futures(lock, futures)
                _locked_pop(lock, futures, fut)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=_writer, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors


# ===========================================================================
# 2. Worktree metrics shape
# ===========================================================================


class TestWorktreeMetricsShape:
    """coordination.py persists worktree metrics as a JSON dict with a fixed schema."""

    def test_default_metrics_has_required_keys(self):
        """The default metrics dataclass must have all required fields with zero values."""
        import dataclasses

        from pokepoke.worktrees.coordination import _DEFAULT_WORKTREE_METRICS

        required = {"total_attempts", "total_successes", "total_failures",
                     "total_wait_time", "max_wait_time"}
        fields = {f.name for f in dataclasses.fields(_DEFAULT_WORKTREE_METRICS)}
        assert fields == required
        for key in required:
            val = getattr(_DEFAULT_WORKTREE_METRICS, key)
            assert isinstance(val, (int, float))
            assert val == 0

    def test_load_worktree_metrics_returns_default_when_missing(self, tmp_path, monkeypatch):
        """_load_worktree_metrics returns default dict when the file doesn't exist."""
        from pokepoke.worktrees.coordination import _load_worktree_metrics

        monkeypatch.setattr(
            "pokepoke.worktrees.coordination._WORKTREE_METRICS_PATH",
            tmp_path / "nonexistent.json",
        )

        metrics = _load_worktree_metrics()
        from pokepoke.worktrees.coordination import WorktreeMetrics
        assert metrics == WorktreeMetrics()

    def test_save_and_load_worktree_metrics_roundtrip(self, tmp_path, monkeypatch):
        """Saved metrics can be loaded back with the same shape and values."""
        from pokepoke.worktrees.coordination import (
            _load_worktree_metrics,
            _save_worktree_metrics,
        )

        metrics_path = tmp_path / "stats" / "worktree_metrics.json"
        metrics_dir = tmp_path / "stats"
        monkeypatch.setattr("pokepoke.worktrees.coordination._WORKTREE_METRICS_PATH", metrics_path)
        monkeypatch.setattr("pokepoke.worktrees.coordination._WORKTREE_METRICS_DIR", metrics_dir)

        from pokepoke.worktrees.coordination import WorktreeMetrics

        original = WorktreeMetrics(
            total_attempts=10,
            total_successes=8,
            total_failures=2,
            total_wait_time=15.5,
            max_wait_time=4.2,
        )
        _save_worktree_metrics(original)
        loaded = _load_worktree_metrics()
        assert loaded == original

    def test_record_worktree_attempt_success(self, tmp_path, monkeypatch):
        """_record_worktree_attempt must update metrics correctly for a success."""
        from pokepoke.worktrees.coordination import _record_worktree_attempt

        metrics_path = tmp_path / "stats" / "worktree_metrics.json"
        metrics_dir = tmp_path / "stats"
        monkeypatch.setattr("pokepoke.worktrees.coordination._WORKTREE_METRICS_PATH", metrics_path)
        monkeypatch.setattr("pokepoke.worktrees.coordination._WORKTREE_METRICS_DIR", metrics_dir)

        _record_worktree_attempt(success=True, wait_time=1.5)

        with open(metrics_path) as f:
            data = json.load(f)
        assert data["total_attempts"] == 1
        assert data["total_successes"] == 1
        assert data["total_failures"] == 0
        assert data["total_wait_time"] == 1.5
        assert data["max_wait_time"] == 1.5

    def test_record_worktree_attempt_failure(self, tmp_path, monkeypatch):
        """_record_worktree_attempt must update metrics correctly for a failure."""
        from pokepoke.worktrees.coordination import _record_worktree_attempt

        metrics_path = tmp_path / "stats" / "worktree_metrics.json"
        metrics_dir = tmp_path / "stats"
        monkeypatch.setattr("pokepoke.worktrees.coordination._WORKTREE_METRICS_PATH", metrics_path)
        monkeypatch.setattr("pokepoke.worktrees.coordination._WORKTREE_METRICS_DIR", metrics_dir)

        _record_worktree_attempt(success=False, wait_time=3.0)

        with open(metrics_path) as f:
            data = json.load(f)
        assert data["total_attempts"] == 1
        assert data["total_successes"] == 0
        assert data["total_failures"] == 1
        assert data["total_wait_time"] == 3.0

    def test_record_worktree_attempt_max_wait_tracked(self, tmp_path, monkeypatch):
        """max_wait_time must track the maximum across multiple attempts."""
        from pokepoke.worktrees.coordination import _record_worktree_attempt

        metrics_path = tmp_path / "stats" / "worktree_metrics.json"
        metrics_dir = tmp_path / "stats"
        monkeypatch.setattr("pokepoke.worktrees.coordination._WORKTREE_METRICS_PATH", metrics_path)
        monkeypatch.setattr("pokepoke.worktrees.coordination._WORKTREE_METRICS_DIR", metrics_dir)

        _record_worktree_attempt(success=True, wait_time=1.0)
        _record_worktree_attempt(success=True, wait_time=5.0)
        _record_worktree_attempt(success=True, wait_time=2.0)

        with open(metrics_path) as f:
            data = json.load(f)
        assert data["max_wait_time"] == 5.0
        assert data["total_attempts"] == 3
        assert data["total_wait_time"] == 8.0

    def test_load_worktree_metrics_handles_corrupt_json(self, tmp_path, monkeypatch):
        """_load_worktree_metrics returns defaults on corrupt JSON."""
        from pokepoke.worktrees.coordination import _load_worktree_metrics

        metrics_path = tmp_path / "corrupt.json"
        metrics_path.write_text("not valid json{{{")
        monkeypatch.setattr("pokepoke.worktrees.coordination._WORKTREE_METRICS_PATH", metrics_path)

        metrics = _load_worktree_metrics()
        assert metrics.total_attempts == 0


# ===========================================================================
# 3. Lock metadata shape
# ===========================================================================


class TestLockMetadataShape:
    """coordination.py writes PID/timestamp metadata as JSON sidecar files."""

    def test_write_lock_metadata_creates_sidecar(self, tmp_path):
        """_write_lock_metadata must create a .lock.meta file with pid and timestamp."""
        from pokepoke.worktrees.coordination import _write_lock_metadata

        lock_path = tmp_path / "test.lock"
        lock_path.touch()
        _write_lock_metadata(lock_path)

        meta_path = lock_path.with_suffix(".lock.meta")
        assert meta_path.exists()

        data = json.loads(meta_path.read_text())
        assert "pid" in data
        assert "timestamp" in data
        assert isinstance(data["pid"], int)
        assert isinstance(data["timestamp"], float)
        assert data["pid"] > 0

    def test_read_lock_metadata_returns_correct_shape(self, tmp_path):
        """_read_lock_metadata must return dict with 'pid' and 'timestamp' keys."""
        from pokepoke.worktrees.coordination import _read_lock_metadata, _write_lock_metadata

        lock_path = tmp_path / "test.lock"
        lock_path.touch()
        _write_lock_metadata(lock_path)

        meta = _read_lock_metadata(lock_path)
        assert meta is not None
        assert "pid" in meta
        assert "timestamp" in meta
        import os
        assert meta["pid"] == os.getpid()

    def test_read_lock_metadata_returns_none_for_missing(self, tmp_path):
        """_read_lock_metadata returns None when no sidecar exists."""
        from pokepoke.worktrees.coordination import _read_lock_metadata

        lock_path = tmp_path / "nonexistent.lock"
        meta = _read_lock_metadata(lock_path)
        assert meta is None

    def test_read_lock_metadata_returns_none_for_corrupt_json(self, tmp_path):
        """_read_lock_metadata returns None on corrupt sidecar JSON."""
        from pokepoke.worktrees.coordination import _read_lock_metadata

        lock_path = tmp_path / "test.lock"
        lock_path.touch()
        meta_path = lock_path.with_suffix(".lock.meta")
        meta_path.write_text("not json")

        meta = _read_lock_metadata(lock_path)
        assert meta is None

    def test_check_lock_status_returns_tuple(self, tmp_path, monkeypatch):
        """check_lock_status must return (exists: bool, metadata: dict | None)."""
        from pokepoke.worktrees.coordination import check_lock_status

        # Redirect lock dir to tmp_path
        def _test_lock_dir():
            return tmp_path

        monkeypatch.setattr("pokepoke.worktrees.coordination._lock_dir", _test_lock_dir)

        # No lock file → (False, None)
        exists, meta = check_lock_status("nonexistent")
        assert exists is False
        assert meta is None

    def test_check_lock_status_with_existing_lock(self, tmp_path, monkeypatch):
        """check_lock_status returns (True, metadata) when lock exists."""
        from pokepoke.worktrees.coordination import (
            _write_lock_metadata,
            check_lock_status,
        )

        def _test_lock_dir():
            return tmp_path

        monkeypatch.setattr("pokepoke.worktrees.coordination._lock_dir", _test_lock_dir)

        # Create a lock file with metadata
        lock_path = tmp_path / "test-lock.lock"
        lock_path.touch()
        _write_lock_metadata(lock_path)

        exists, meta = check_lock_status("test-lock")
        assert exists is True
        assert meta is not None
        assert "pid" in meta
        assert "timestamp" in meta


# ===========================================================================
# 4. Cross-module lock flow: coordination lock pattern vs parallel threading.Lock
# ===========================================================================


class TestCrossModuleLockFlow:
    """Verify that the two locking mechanisms (file locks in coordination,
    threading.Lock in parallel_support) serve distinct purposes and don't conflict."""

    def test_threading_lock_is_used_for_futures_protection(self):
        """The parallel_worker_pool uses threading.Lock for in-memory futures dict."""
        from pokepoke.agents.parallel_worker_pool import ParallelWorkerPool

        pool = ParallelWorkerPool(2)
        assert isinstance(pool.lock, threading.Lock)
        pool.shutdown(wait=False)

    def test_file_lock_is_used_for_cross_process_coordination(self, tmp_path, monkeypatch):
        """coordination.acquire_lock uses file-based locking for cross-process safety."""
        import os

        from pokepoke.worktrees.coordination import acquire_lock

        # Redirect lock dir
        def _test_lock_dir():
            d = tmp_path / "locks"
            os.makedirs(d, exist_ok=True)
            return d

        monkeypatch.setattr("pokepoke.worktrees.coordination._lock_dir", _test_lock_dir)

        with acquire_lock("test-contract", timeout=5) as _lock:
            # Lock is acquired — file should exist
            lock_file = tmp_path / "locks" / "test-contract.lock"
            assert lock_file.exists()

    def test_compute_slots_return_shape(self):
        """compute_slots must return (active_ids: set[str], slots: int, avail_mb: int)."""
        from pokepoke.agents.parallel_worker_pool import compute_slots

        futures: dict[_Future[WorkItemResult], BeadsWorkItem] = {}
        run_logger = MagicMock()
        lock = threading.Lock()

        with (
            patch("pokepoke.agents.parallel.get_effective_max_agents", return_value=4),
            patch("pokepoke.utils.memory_utils.apply_memory_backpressure",
                  return_value=(4, 8192)),
            patch("pokepoke.utils.memory_utils.get_process_rss_mb", return_value=500),
            patch("pokepoke.utils.memory_utils.get_cpu_usage_percent", return_value=25.0),
        ):
            result = compute_slots(futures, run_logger, lock)

        assert isinstance(result, tuple)
        assert len(result) == 3
        active_ids, slots, avail_mb = result
        assert isinstance(active_ids, set)
        assert isinstance(slots, int)
        assert isinstance(avail_mb, int)
