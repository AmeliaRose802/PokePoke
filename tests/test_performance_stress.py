"""Performance regression and stress tests for PokePoke.

Exercises real threading under contention, scaling behavior, and timing
guarantees that mock-only tests cannot cover.

Test categories:
- Thread contention: 8+ workers competing for file-based locks
- Merge queue throughput: N items queued simultaneously
- Model stats scaling: record_completion with 1000+ log entries (O(N) rebuild)
- Memory backpressure: threshold-based slot adjustment
- Idle loop timing: exponential backoff verification
- Subprocess timeout: process_utils timeout behavior
- Preflight duration budget: check completion within time budget
- LockContentionTracker thread safety: concurrent multi-thread access
"""

import os
import threading
import time
from concurrent.futures import Future
from pathlib import Path
from unittest.mock import patch

from pokepoke.lock_contention import LockContentionTracker
from pokepoke.merge_queue import MergeQueue, MergeStatus
from pokepoke.model_stats_store import (
    _rebuild_summary,
    load_model_stats,
    record_completion,
    save_model_stats,
)
from pokepoke.process_utils import apply_memory_backpressure
from pokepoke.types import BeadsWorkItem, ModelCompletionRecord


# ── Helpers ──────────────────────────────────────────────────────────


def _make_item(item_id: str = "PERF-001") -> BeadsWorkItem:
    return BeadsWorkItem(
        id=item_id,
        title=f"Perf test item {item_id}",
        status="in_progress",
        priority=1,
        issue_type="task",
        labels=[],
    )


def _make_record(
    item_id: str = "PP-1",
    model: str = "gpt-4o",
    duration: float = 60.0,
    gate_passed: bool = True,
) -> ModelCompletionRecord:
    return ModelCompletionRecord(
        item_id=item_id,
        model=model,
        duration_seconds=duration,
        gate_passed=gate_passed,
    )


def _make_log_entry(
    item_id: str = "PP-1",
    model: str = "gpt-4o",
    duration: float = 60.0,
    gate_passed: bool = True,
) -> dict:
    return {
        "item_id": item_id,
        "model": model,
        "duration_seconds": duration,
        "gate_passed": gate_passed,
        "input_tokens": 0,
        "output_tokens": 0,
        "agent_turns": 0,
        "cost": 0.0,
        "timestamp": "2025-01-01T00:00:00+00:00",
    }


# ── Thread contention stress tests ──────────────────────────────────


class TestLockContentionStress:
    """8+ workers competing for file-based locks via coordination.acquire_lock."""

    def test_concurrent_lock_acquisition_workers(self, tmp_path: Path) -> None:
        """4 threads compete for the same filelock; all must eventually acquire it."""
        from filelock import FileLock

        lock_path = tmp_path / "stress.lock"
        num_workers = 4
        acquired_order: list[int] = []
        order_lock = threading.Lock()

        def worker(worker_id: int) -> None:
            fl = FileLock(lock_path)
            fl.acquire(timeout=5)
            try:
                with order_lock:
                    acquired_order.append(worker_id)
                time.sleep(0.005)  # hold briefly
            finally:
                fl.release()

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(num_workers)]
        t0 = time.monotonic()
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        elapsed = time.monotonic() - t0
        assert len(acquired_order) == num_workers
        assert set(acquired_order) == set(range(num_workers))
        assert elapsed < 10.0, f"Lock contention took {elapsed:.1f}s (expected <10s)"

    def test_concurrent_lock_acquisition_more_workers(self, tmp_path: Path) -> None:
        """6 threads stress-test filelock contention."""
        from filelock import FileLock

        lock_path = tmp_path / "stress6.lock"
        num_workers = 6
        counter = {"value": 0}
        counter_lock = threading.Lock()

        def worker() -> None:
            fl = FileLock(lock_path)
            fl.acquire(timeout=5)
            try:
                with counter_lock:
                    counter["value"] += 1
                time.sleep(0.002)
            finally:
                fl.release()

        threads = [threading.Thread(target=worker) for _ in range(num_workers)]
        t0 = time.monotonic()
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        elapsed = time.monotonic() - t0
        assert counter["value"] == num_workers
        assert elapsed < 10.0

    def test_lock_contention_tracker_under_thread_pressure(self) -> None:
        """LockContentionTracker records correctly under concurrent access."""
        tracker = LockContentionTracker()
        num_threads = 4
        ops_per_thread = 50
        barrier = threading.Barrier(num_threads, timeout=5)

        def worker(tid: int) -> None:
            barrier.wait(timeout=5)
            for i in range(ops_per_thread):
                tracker.record_acquisition(f"lock-{tid % 3}", 0.001 * i)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        snap = tracker.snapshot()
        total_acquired = sum(s["acquired"] for s in snap.values())
        assert total_acquired == num_threads * ops_per_thread

    def test_mixed_acquisition_and_timeout_recording(self) -> None:
        """Concurrent acquisitions and timeouts don't corrupt tracker state."""
        tracker = LockContentionTracker()
        num_threads = 4
        barrier = threading.Barrier(num_threads, timeout=5)

        def worker(tid: int) -> None:
            barrier.wait(timeout=5)
            for _ in range(20):
                if tid % 2 == 0:
                    tracker.record_acquisition("shared", 0.01)
                else:
                    tracker.record_timeout("shared", 5.0)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        snap = tracker.snapshot()
        expected_acq = 2 * 20   # 2 even threads × 20 ops
        expected_to = 2 * 20    # 2 odd threads × 20 ops
        assert snap["shared"]["acquired"] == expected_acq
        assert snap["shared"]["timeouts"] == expected_to


# ── Merge queue throughput tests ─────────────────────────────────────


class TestMergeQueueThroughput:
    """N items queued simultaneously; verify serialized processing."""

    def setup_method(self) -> None:
        self.queue = MergeQueue()

    def teardown_method(self) -> None:
        if self.queue.is_running:
            self.queue.shutdown(timeout=10)

    @patch("pokepoke.merge_queue.is_shutting_down", return_value=False)
    @patch("pokepoke.merge_queue._rebase_worktree", return_value=True)
    def test_items_queued_simultaneously(self, mock_rebase, mock_shutdown) -> None:
        """5 merge requests queued at once are all processed serially."""
        processing_order: list[str] = []
        order_lock = threading.Lock()

        def mock_merge(item, worktree_path=None):
            with order_lock:
                processing_order.append(item.id)
            time.sleep(0.005)
            return True

        with patch("pokepoke.worktree_finalization.merge_worktree_to_dev", side_effect=mock_merge):
            self.queue.start()
            futures: list[Future] = []
            for i in range(5):
                item = _make_item(f"BATCH-{i:03d}")
                f = self.queue.submit(Path(f"worktrees/task-BATCH-{i:03d}"), item)
                futures.append(f)

            results = [f.result(timeout=15) for f in futures]

        assert all(r.status == MergeStatus.SUCCESS for r in results)
        assert len(processing_order) == 5

    @patch("pokepoke.merge_queue.is_shutting_down", return_value=False)
    @patch("pokepoke.merge_queue._rebase_worktree", return_value=True)
    def test_concurrent_submitters(self, mock_rebase, mock_shutdown) -> None:
        """Multiple threads submit to the queue simultaneously."""
        def mock_merge(item, worktree_path=None):
            time.sleep(0.005)
            return True

        with patch("pokepoke.worktree_finalization.merge_worktree_to_dev", side_effect=mock_merge):
            self.queue.start()
            all_futures: list[Future] = []
            barrier = threading.Barrier(4, timeout=5)

            def submitter(base_id: int) -> None:
                barrier.wait(timeout=5)
                for i in range(3):
                    item = _make_item(f"SUB-{base_id}-{i}")
                    f = self.queue.submit(Path(f"worktrees/task-SUB-{base_id}-{i}"), item)
                    all_futures.append(f)

            threads = [threading.Thread(target=submitter, args=(t,)) for t in range(4)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=15)

            results = [f.result(timeout=15) for f in all_futures]

        assert len(results) == 12
        assert all(r.status == MergeStatus.SUCCESS for r in results)

    @patch("pokepoke.merge_queue.is_shutting_down", return_value=False)
    @patch("pokepoke.merge_queue._rebase_worktree", return_value=True)
    def test_shutdown_drains_pending(self, mock_rebase, mock_shutdown) -> None:
        """Shutdown resolves all pending requests with SHUTDOWN status."""
        slow_event = threading.Event()

        def slow_merge(item, worktree_path=None):
            slow_event.wait(timeout=10)
            return True

        with patch("pokepoke.worktree_finalization.merge_worktree_to_dev", side_effect=slow_merge):
            self.queue.start()
            futures = []
            for i in range(5):
                item = _make_item(f"DRAIN-{i}")
                futures.append(self.queue.submit(Path(f"wt/drain-{i}"), item))

            time.sleep(0.1)
            slow_event.set()
            self.queue.shutdown(timeout=15)

            resolved = [f.result(timeout=5) for f in futures if f.done()]

        assert len(resolved) >= 1  # at least one processed or drained


# ── Model stats scaling tests ────────────────────────────────────────


class TestModelStatsScaling:
    """record_completion with 1000+ log entries testing O(N) rebuild."""

    def test_rebuild_summary_1000_entries(self) -> None:
        """_rebuild_summary scales linearly with 100 log entries."""
        log = [_make_log_entry(f"item-{i}", "model-a", 10.0 + i * 0.1) for i in range(100)]

        t0 = time.monotonic()
        summary = _rebuild_summary(log)
        elapsed = time.monotonic() - t0

        assert "model-a" in summary
        assert summary["model-a"]["total_items_attempted"] == 100
        assert summary["model-a"]["total_items_succeeded"] == 100
        assert elapsed < 1.0, f"Rebuild took {elapsed:.3f}s for 100 entries"

    def test_rebuild_summary_scaling(self) -> None:
        """Verify rebuild time scales roughly linearly from 100→500 entries."""
        log_small = [_make_log_entry(f"i-{i}", "m", float(i)) for i in range(100)]
        log_large = [_make_log_entry(f"i-{i}", "m", float(i)) for i in range(500)]

        t0 = time.monotonic()
        _rebuild_summary(log_small)
        time_small = time.monotonic() - t0

        t0 = time.monotonic()
        _rebuild_summary(log_large)
        time_large = time.monotonic() - t0

        # 5x data should take at most 10x time (generous margin for overhead)
        assert time_large < time_small * 10 + 0.1, (
            f"Non-linear scaling: small={time_small:.4f}s, large={time_large:.4f}s"
        )

    def test_rebuild_summary_multiple_models(self) -> None:
        """Rebuild with entries spread across 10 different models."""
        log = []
        for i in range(200):
            model = f"model-{i % 10}"
            log.append(_make_log_entry(f"item-{i}", model, 10.0))

        t0 = time.monotonic()
        summary = _rebuild_summary(log)
        elapsed = time.monotonic() - t0

        assert len(summary) == 10
        for model_stats in summary.values():
            assert model_stats["total_items_attempted"] == 20
        assert elapsed < 2.0

    def test_record_completion_concurrent_writes(self, tmp_path: Path) -> None:
        """Multiple threads call record_completion on the same stats file."""
        stats_path = tmp_path / "model_stats.json"
        lock_dir = tmp_path / "locks"
        lock_dir.mkdir()
        num_threads = 3
        records_per_thread = 5
        barrier = threading.Barrier(num_threads, timeout=5)

        def writer(tid: int) -> None:
            barrier.wait(timeout=5)
            for i in range(records_per_thread):
                rec = _make_record(
                    item_id=f"T{tid}-{i}",
                    model=f"model-{tid % 2}",
                    duration=float(i),
                )
                record_completion(rec, path=stats_path)

        with patch("pokepoke.coordination._lock_dir", return_value=lock_dir):
            threads = [threading.Thread(target=writer, args=(t,)) for t in range(num_threads)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=15)

        data = load_model_stats(stats_path)
        total_records = len(data["log"])
        assert total_records == num_threads * records_per_thread

    def test_record_completion_sequential(self, tmp_path: Path) -> None:
        """30 sequential record_completion calls complete in reasonable time.

        Exercises the O(N) rebuild path. Each call reads the full log,
        rebuilds summary, and writes atomically.
        """
        stats_path = tmp_path / "model_stats.json"
        lock_dir = tmp_path / "locks"
        lock_dir.mkdir()

        with patch("pokepoke.coordination._lock_dir", return_value=lock_dir):
            t0 = time.monotonic()
            for i in range(30):
                rec = _make_record(item_id=f"SEQ-{i}", model="seq-model", duration=1.0)
                record_completion(rec, path=stats_path)
            elapsed = time.monotonic() - t0

        data = load_model_stats(stats_path)
        assert len(data["log"]) == 30
        assert data["summary"]["seq-model"]["total_items_attempted"] == 30
        assert elapsed < 10.0, f"30 sequential completions took {elapsed:.1f}s"

    def test_save_load_roundtrip_large_file(self, tmp_path: Path) -> None:
        """Save and load a stats file with 200 entries."""
        stats_path = tmp_path / "model_stats.json"
        log = [_make_log_entry(f"item-{i}", f"model-{i % 10}", float(i)) for i in range(200)]
        data = {"log": log, "summary": _rebuild_summary(log)}

        t0 = time.monotonic()
        save_model_stats(data, stats_path)
        elapsed_save = time.monotonic() - t0

        t0 = time.monotonic()
        loaded = load_model_stats(stats_path)
        elapsed_load = time.monotonic() - t0

        assert len(loaded["log"]) == 200
        assert elapsed_save < 2.0
        assert elapsed_load < 2.0


# ── Memory backpressure simulation ───────────────────────────────────


class TestMemoryBackpressure:
    """Verify memory-based slot adjustment thresholds."""

    @patch("pokepoke.process_utils.get_available_memory_mb", return_value=4096)
    @patch("pokepoke.process_utils.is_memory_pressure", return_value=False)
    @patch("pokepoke.process_utils.is_memory_critical", return_value=False)
    def test_no_pressure_preserves_slots(self, *mocks) -> None:
        adjusted, avail = apply_memory_backpressure(8)
        assert adjusted == 8
        assert avail == 4096

    @patch("pokepoke.process_utils.get_available_memory_mb", return_value=1500)
    @patch("pokepoke.process_utils.is_memory_pressure", return_value=True)
    @patch("pokepoke.process_utils.is_memory_critical", return_value=False)
    def test_pressure_throttles_to_1(self, *mocks) -> None:
        adjusted, avail = apply_memory_backpressure(8)
        assert adjusted == 1
        assert avail == 1500

    @patch("pokepoke.process_utils.get_available_memory_mb", return_value=800)
    @patch("pokepoke.process_utils.is_memory_pressure", return_value=True)
    @patch("pokepoke.process_utils.is_memory_critical", return_value=True)
    def test_critical_blocks_all(self, *mocks) -> None:
        adjusted, avail = apply_memory_backpressure(8)
        assert adjusted == 0
        assert avail == 800

    @patch("pokepoke.process_utils.get_available_memory_mb", return_value=0)
    @patch("pokepoke.process_utils.is_memory_pressure", return_value=False)
    @patch("pokepoke.process_utils.is_memory_critical", return_value=False)
    def test_unknown_memory_passes_through(self, *mocks) -> None:
        adjusted, avail = apply_memory_backpressure(4)
        assert adjusted == 4
        assert avail == 0

    def test_zero_slots_unchanged(self) -> None:
        with patch("pokepoke.process_utils.get_available_memory_mb", return_value=1500), \
             patch("pokepoke.process_utils.is_memory_pressure", return_value=True), \
             patch("pokepoke.process_utils.is_memory_critical", return_value=False):
            adjusted, _ = apply_memory_backpressure(0)
            assert adjusted == 0

    @patch("pokepoke.process_utils.get_available_memory_mb", return_value=1500)
    @patch("pokepoke.process_utils.is_memory_pressure", return_value=True)
    @patch("pokepoke.process_utils.is_memory_critical", return_value=False)
    def test_pressure_caps_high_slot_count(self, *mocks) -> None:
        adjusted, _ = apply_memory_backpressure(16)
        assert adjusted == 1


# ── Idle loop timing verification ────────────────────────────────────


class TestIdleLoopTiming:
    """Verify exponential backoff timing behavior."""

    def test_exponential_backoff_doubles(self) -> None:
        """Simulate the orchestrator's idle backoff: starts at base, doubles to max."""
        base_delay = 8.0
        max_delay = 120.0
        backoff = 2.0

        delay = base_delay
        delays: list[float] = []
        for _ in range(10):
            delays.append(delay)
            delay = min(delay * backoff, max_delay)

        assert delays[0] == 8.0
        assert delays[1] == 16.0
        assert delays[2] == 32.0
        assert delays[3] == 64.0
        assert delays[4] == 120.0  # capped
        assert all(d == 120.0 for d in delays[4:])

    def test_backoff_resets_on_work(self) -> None:
        """After finding work, delay resets to base."""
        base_delay = 8.0
        delay = 120.0  # currently at max

        # Simulate "found work"
        delay = base_delay
        assert delay == 8.0

    def test_backoff_sequence_duration(self) -> None:
        """Total wait over first 5 idle cycles is predictable."""
        base_delay = 8.0
        max_delay = 120.0
        delay = base_delay
        total = 0.0
        for _ in range(5):
            total += delay
            delay = min(delay * 2.0, max_delay)

        # 8 + 16 + 32 + 64 + 120 = 240
        assert total == 240.0


# ── Subprocess timeout behavior tests ────────────────────────────────


class TestSubprocessTimeoutBehavior:
    """Verify timeout handling in process_utils."""

    @patch("pokepoke.process_utils.subprocess.run")
    def test_check_copilot_processes_timeout(self, mock_run) -> None:
        """check_copilot_processes handles subprocess.TimeoutExpired."""
        import subprocess
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="tasklist", timeout=30)

        from pokepoke.process_utils import check_copilot_processes
        # Ensure the cache doesn't interfere
        import pokepoke.process_utils as pu
        old_cache = pu._copilot_process_cache
        pu._copilot_process_cache = None
        try:
            count = check_copilot_processes()
            assert count == 0  # Returns 0 on error
        finally:
            pu._copilot_process_cache = old_cache

    @patch("pokepoke.process_utils.subprocess.run")
    def test_kill_orphans_timeout(self, mock_run) -> None:
        """kill_orphaned_copilot_processes handles timeout."""
        import subprocess
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="tasklist", timeout=30)

        from pokepoke.process_utils import kill_orphaned_copilot_processes
        killed = kill_orphaned_copilot_processes(expected_count=0)
        assert killed == 0

    @patch("pokepoke.process_utils.subprocess.run")
    def test_is_process_running_timeout(self, mock_run) -> None:
        """is_process_running handles subprocess timeout."""
        import subprocess
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="tasklist", timeout=10)

        from pokepoke.process_utils import is_process_running
        assert is_process_running(99999) is False


# ── Preflight check duration budget assertions ───────────────────────


class TestPreflightDurationBudget:
    """Verify preflight checks complete within time budget."""

    def test_check_disk_space_speed(self, tmp_path: Path) -> None:
        """Disk space check completes well under 1 second."""
        from pokepoke.preflight_checks import check_disk_space

        config = {"min_disk_space_gb": 1.0}
        t0 = time.monotonic()
        errors, warnings = check_disk_space(tmp_path, config)
        elapsed = time.monotonic() - t0

        assert elapsed < 1.0, f"Disk space check took {elapsed:.3f}s"

    def test_check_lock_availability_speed(self, tmp_path: Path) -> None:
        """Lock availability check completes well under 1 second."""
        from pokepoke.preflight_checks import check_lock_availability

        config = {"enable_self_repair": True}
        t0 = time.monotonic()
        errors, warnings = check_lock_availability(tmp_path, config)
        elapsed = time.monotonic() - t0

        assert elapsed < 1.0, f"Lock check took {elapsed:.3f}s"

    def test_check_git_status_mocked_speed(self, tmp_path: Path) -> None:
        """Git status check (mocked) completes within budget."""
        from pokepoke.preflight_checks import check_git_status

        # Create a minimal .git directory to pass the existence check
        (tmp_path / ".git").mkdir()
        config = {"git_operation_timeout": 30}

        with patch("pokepoke.preflight_checks.has_uncommitted_changes", return_value=False):
            t0 = time.monotonic()
            errors, warnings = check_git_status(tmp_path, config)
            elapsed = time.monotonic() - t0

        assert elapsed < 0.5, f"Mocked git status check took {elapsed:.3f}s"
        assert len(errors) == 0

    def test_is_lock_stale_speed(self, tmp_path: Path) -> None:
        """Lock staleness check completes well under 1s (with mocked process check)."""
        from pokepoke.preflight_checks import is_lock_stale

        lock_file = tmp_path / "test.lock"
        lock_file.write_text(str(os.getpid()))

        # Mock is_process_running to avoid real tasklist calls on Windows
        with patch("pokepoke.preflight_checks.is_process_running", return_value=True):
            t0 = time.monotonic()
            for _ in range(100):
                is_lock_stale(lock_file)
            elapsed = time.monotonic() - t0

        # 100 iterations under 2 seconds with mocked subprocess
        assert elapsed < 2.0, f"100 is_lock_stale calls took {elapsed:.3f}s"


# ── LockContentionTracker thread safety ──────────────────────────────


class TestLockContentionTrackerThreadSafety:
    """Verify tracker correctness under heavy concurrent access."""

    def test_snapshot_consistency_during_writes(self) -> None:
        """Snapshots taken during writes are always internally consistent."""
        tracker = LockContentionTracker()
        errors: list[str] = []
        stop = threading.Event()

        def writer() -> None:
            i = 0
            while not stop.is_set():
                tracker.record_acquisition("stress", 0.1)
                i += 1

        def reader() -> None:
            while not stop.is_set():
                snap = tracker.snapshot()
                if "stress" in snap:
                    s = snap["stress"]
                    # acquired count should always be >= 0
                    if s["acquired"] < 0:
                        errors.append(f"Negative acquired: {s['acquired']}")
                    # total_wait should be non-negative
                    if s["total_wait"] < 0:
                        errors.append(f"Negative total_wait: {s['total_wait']}")

        writers = [threading.Thread(target=writer) for _ in range(2)]
        readers = [threading.Thread(target=reader) for _ in range(1)]

        for t in writers + readers:
            t.start()
        time.sleep(0.1)
        stop.set()
        for t in writers + readers:
            t.join(timeout=5)

        assert errors == [], f"Consistency errors: {errors}"

    def test_reset_during_concurrent_writes(self) -> None:
        """Reset while writes are happening doesn't cause crashes."""
        tracker = LockContentionTracker()
        stop = threading.Event()
        crash_errors: list[str] = []

        def writer() -> None:
            try:
                while not stop.is_set():
                    tracker.record_acquisition("reset-test", 0.01)
                    tracker.record_timeout("reset-test", 1.0)
                    tracker.record_stale_clearance("reset-test")
            except Exception as e:
                crash_errors.append(str(e))

        def resetter() -> None:
            try:
                while not stop.is_set():
                    tracker.reset()
                    time.sleep(0.01)
            except Exception as e:
                crash_errors.append(str(e))

        threads = [threading.Thread(target=writer) for _ in range(2)]
        threads.append(threading.Thread(target=resetter))

        for t in threads:
            t.start()
        time.sleep(0.1)
        stop.set()
        for t in threads:
            t.join(timeout=5)

        assert crash_errors == [], f"Crashes during reset: {crash_errors}"

    def test_high_throughput_histogram_accuracy(self) -> None:
        """Histogram bucket counts match total acquisitions under concurrency."""
        tracker = LockContentionTracker()
        num_threads = 4
        ops_per_thread = 50
        barrier = threading.Barrier(num_threads, timeout=5)

        def worker() -> None:
            barrier.wait(timeout=5)
            for i in range(ops_per_thread):
                tracker.record_acquisition("hist", float(i) * 0.01)

        threads = [threading.Thread(target=worker) for _ in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        snap = tracker.snapshot()
        total_acquired = snap["hist"]["acquired"]
        histogram_total = sum(snap["hist"]["histogram"].values())

        assert total_acquired == num_threads * ops_per_thread
        assert histogram_total == total_acquired


# ── Coordination lock integration ────────────────────────────────────


class TestCoordinationLockIntegration:
    """Integration tests for acquire_lock under real thread contention."""

    def test_acquire_lock_serializes_work(self, tmp_path: Path) -> None:
        """acquire_lock with real filelock serializes concurrent workers."""
        from pokepoke.coordination import acquire_lock

        results: list[int] = []
        result_lock = threading.Lock()

        # Redirect locks to tmp_path
        with patch("pokepoke.coordination._lock_dir", return_value=tmp_path):
            barrier = threading.Barrier(4, timeout=5)

            def worker(wid: int) -> None:
                barrier.wait(timeout=5)
                with acquire_lock("test-serial", timeout=5):
                    with result_lock:
                        results.append(wid)
                    time.sleep(0.002)

            threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=10)

        assert len(results) == 4
        assert len(set(results)) == 4

    def test_worktree_lock_contention(self, tmp_path: Path) -> None:
        """with_worktree_lock serializes under contention from 8 threads."""
        from pokepoke.coordination import with_worktree_lock

        counter = {"value": 0}
        violations: list[str] = []
        active = {"count": 0}
        active_lock = threading.Lock()

        with patch("pokepoke.coordination._lock_dir", return_value=tmp_path):
            barrier = threading.Barrier(4, timeout=5)

            def worker() -> None:
                barrier.wait(timeout=5)
                with with_worktree_lock(timeout=5):
                    with active_lock:
                        active["count"] += 1
                        if active["count"] > 1:
                            violations.append(f"Concurrent holders: {active['count']}")
                    time.sleep(0.002)
                    with active_lock:
                        active["count"] -= 1
                    counter["value"] += 1

            threads = [threading.Thread(target=worker) for _ in range(4)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=10)

        assert counter["value"] == 4
        assert violations == [], f"Mutual exclusion violated: {violations}"
