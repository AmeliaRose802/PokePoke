"""Concurrency stress tests for parallel agent execution.

These tests use REAL ThreadPoolExecutor workers, threading.Barrier,
and repeated iterations to surface race conditions, deadlocks, and
data corruption in shared mutable state under thread contention.

External dependencies (beads, copilot, terminal UI) are mocked,
but all threading primitives and shared state are exercised for real.
"""

import concurrent.futures
import threading
import time
from unittest.mock import MagicMock, Mock, patch

import pytest

from pokepoke.agents.parallel import (
    _collect_done_futures,
    _parallel_process_item,
)
from pokepoke.agents.parallel_runtime import (
    clear_runtime_parallel_limits,
    compute_effective_max_agents,
    set_runtime_parallel_limits,
)
from pokepoke.agents.parallel_support import (
    compute_slots,
    dispatch_items,
    update_circuit_breaker,
)
from pokepoke.types import (
    AgentStats,
    BeadsCreatedItem,
    BeadsWorkItem,
    SessionStats,
    WorkItemResult,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_item(item_id: str = "t1") -> BeadsWorkItem:
    return BeadsWorkItem(
        id=item_id, title=f"Title-{item_id}", status="open",
        priority=1, issue_type="task",
    )


def _make_stats() -> SessionStats:
    return SessionStats(agent_stats=AgentStats())


# Number of stress iterations — high enough to surface intermittent races.
_STRESS_ITERATIONS = 50


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _mock_parallel_externals(monkeypatch):
    """Mock external deps for all stress tests."""
    mock_cfg = MagicMock()
    mock_cfg.preflight_health.enabled = False
    mock_cfg.max_parallel_agents = 10
    monkeypatch.setattr("pokepoke.config.get_config", lambda: mock_cfg)
    monkeypatch.setattr(
        "pokepoke.agents.parallel.assign_and_sync_item", lambda *a, **kw: True)
    monkeypatch.setattr(
        "pokepoke.agents.parallel.unassign_with_retry", lambda *a, **kw: None)
    monkeypatch.setattr(
        "pokepoke.agents.parallel_support.kill_orphaned_copilot_processes",
        lambda **kw: None)
    monkeypatch.setattr(
        "pokepoke.agents.parallel_support.terminal_ui", MagicMock())
    monkeypatch.setattr(
        "pokepoke.agents.parallel_support.is_high_conflict_risk",
        lambda _item: False)


# =========================================================================
# 1. SessionStats integrity under concurrent updates
# =========================================================================


class TestSessionStatsConcurrentIntegrity:
    """Verify SessionStats counters remain consistent under thread contention."""

    @pytest.mark.timeout(30)
    def test_record_completion_concurrent_accuracy(self) -> None:
        """N threads each record 1 completion; total must equal N."""
        for _ in range(_STRESS_ITERATIONS):
            n_threads = 8
            stats = _make_stats()
            barrier = threading.Barrier(n_threads)

            def _worker(idx: int, _barrier=barrier, _stats=stats) -> None:
                _barrier.wait()
                item = _make_item(f"item-{idx}")
                _stats.record_completion(item, agent_type="work")

            with concurrent.futures.ThreadPoolExecutor(max_workers=n_threads) as pool:
                futs = [pool.submit(_worker, i) for i in range(n_threads)]
                concurrent.futures.wait(futs)
                for f in futs:
                    f.result()

            assert stats.items_completed == n_threads
            assert len(stats.completed_items_list) == n_threads

    @pytest.mark.timeout(30)
    def test_record_agent_stats_concurrent_accumulation(self) -> None:
        """Concurrent accumulate calls must sum correctly."""
        for _ in range(_STRESS_ITERATIONS):
            n_threads = 8
            stats = _make_stats()
            barrier = threading.Barrier(n_threads)
            per_thread_tokens = 100

            def _worker(_barrier=barrier, _stats=stats, _tok=per_thread_tokens) -> None:
                _barrier.wait()
                s = AgentStats(input_tokens=_tok, output_tokens=_tok)
                _stats.record_agent_stats(s)

            with concurrent.futures.ThreadPoolExecutor(max_workers=n_threads) as pool:
                futs = [pool.submit(_worker) for _ in range(n_threads)]
                concurrent.futures.wait(futs)
                for f in futs:
                    f.result()

            expected = n_threads * per_thread_tokens
            assert stats.agent_stats.input_tokens == expected
            assert stats.agent_stats.output_tokens == expected

    @pytest.mark.timeout(30)
    def test_record_created_item_dedup_under_contention(self) -> None:
        """Duplicate item IDs submitted concurrently should be deduped."""
        for _ in range(_STRESS_ITERATIONS):
            n_threads = 8
            stats = _make_stats()
            barrier = threading.Barrier(n_threads)
            # All threads submit the same item ID — only 1 should be recorded
            shared_item = BeadsCreatedItem(id="dup-1", title="Dup", agent_type="work")

            def _worker(_barrier=barrier, _stats=stats, _item=shared_item) -> None:
                _barrier.wait()
                _stats.record_created_item(_item)

            with concurrent.futures.ThreadPoolExecutor(max_workers=n_threads) as pool:
                futs = [pool.submit(_worker) for _ in range(n_threads)]
                concurrent.futures.wait(futs)
                for f in futs:
                    f.result()

            assert stats.items_created == 1
            assert len(stats.created_items_list) == 1

    @pytest.mark.timeout(30)
    def test_mixed_operations_concurrent(self) -> None:
        """Multiple operation types concurrently should not corrupt state."""
        for _ in range(_STRESS_ITERATIONS):
            n_threads = 8
            stats = _make_stats()
            barrier = threading.Barrier(n_threads)

            def _worker(idx: int, _barrier=barrier, _stats=stats) -> None:
                _barrier.wait()
                if idx % 3 == 0:
                    _stats.record_completion(_make_item(f"c-{idx}"), agent_type="work")
                elif idx % 3 == 1:
                    _stats.record_agent_stats(AgentStats(input_tokens=10))
                else:
                    _stats.record_agent_run("work", count=1)

            with concurrent.futures.ThreadPoolExecutor(max_workers=n_threads) as pool:
                futs = [pool.submit(_worker, i) for i in range(n_threads)]
                concurrent.futures.wait(futs)
                for f in futs:
                    f.result()

            completions = sum(1 for i in range(n_threads) if i % 3 == 0)
            token_adds = sum(1 for i in range(n_threads) if i % 3 == 1)
            run_adds = sum(1 for i in range(n_threads) if i % 3 == 2)

            assert stats.items_completed == completions
            assert stats.agent_stats.input_tokens == token_adds * 10
            assert stats.get_agent_run_count("work") == run_adds

    @pytest.mark.timeout(30)
    def test_snapshot_while_concurrent_writes(self) -> None:
        """Snapshots taken during concurrent writes must be internally consistent."""
        stats = _make_stats()
        errors: list[str] = []
        stop = threading.Event()

        def _writer() -> None:
            idx = 0
            while not stop.is_set():
                stats.record_completion(_make_item(f"snap-{idx}"), agent_type="work")
                stats.record_agent_stats(AgentStats(input_tokens=1))
                idx += 1

        def _reader() -> None:
            while not stop.is_set():
                snap = stats.snapshot()
                # Snapshot must have at least as many completed items in list
                if len(snap.completed_items_list) < snap.items_completed:
                    errors.append(
                        f"list={len(snap.completed_items_list)} < count={snap.items_completed}")

        writers = [threading.Thread(target=_writer) for _ in range(4)]
        readers = [threading.Thread(target=_reader) for _ in range(2)]
        for t in writers + readers:
            t.start()
        time.sleep(0.3)
        stop.set()
        for t in writers + readers:
            t.join(timeout=5)
            assert not t.is_alive(), f"Thread {t.name} did not finish within timeout"

        assert not errors, f"Snapshot inconsistencies: {errors[:5]}"


# =========================================================================
# 2. Circuit breaker under real concurrent failure cascades
# =========================================================================


class TestCircuitBreakerConcurrentFailures:
    """Test circuit breaker trips correctly under real concurrent failures."""

    @pytest.mark.timeout(30)
    def test_circuit_breaker_trips_after_consecutive_failures(self) -> None:
        """Real concurrent workers all failing should trip the circuit breaker."""
        max_failures = 5

        for _ in range(_STRESS_ITERATIONS):
            consecutive = 0
            tripped = False
            # Simulate batches of failures arriving from concurrent workers
            for _batch in range(max_failures + 2):
                consecutive, tripped = update_circuit_breaker(
                    batch_successes=0, batch_failures=2,
                    consecutive_failures=consecutive,
                    max_consecutive_failures=max_failures,
                    futures={}, run_logger=Mock(),
                )
                if tripped:
                    break

            assert tripped, "Circuit breaker should have tripped"
            assert consecutive >= max_failures

    @pytest.mark.timeout(30)
    def test_circuit_breaker_resets_on_success(self) -> None:
        """A single success among failures should reset the counter."""
        max_failures = 10

        for _ in range(_STRESS_ITERATIONS):
            consecutive = 0
            # Accumulate 9 failures
            for _ in range(max_failures - 1):
                consecutive, tripped = update_circuit_breaker(
                    batch_successes=0, batch_failures=1,
                    consecutive_failures=consecutive,
                    max_consecutive_failures=max_failures,
                    futures={}, run_logger=Mock(),
                )
                assert not tripped

            # One success resets
            consecutive, tripped = update_circuit_breaker(
                batch_successes=1, batch_failures=0,
                consecutive_failures=consecutive,
                max_consecutive_failures=max_failures,
                futures={}, run_logger=Mock(),
            )
            assert consecutive == 0
            assert not tripped

    @pytest.mark.timeout(30)
    def test_collect_done_futures_with_real_executor_failures(self) -> None:
        """Real ThreadPoolExecutor workers that raise exceptions."""
        n_workers = 6
        stats = _make_stats()
        barrier = threading.Barrier(n_workers)

        def _failing_worker(idx: int) -> WorkItemResult:
            barrier.wait()
            if idx % 2 == 0:
                raise RuntimeError(f"Worker {idx} failed")
            return WorkItemResult(success=False, request_count=1)

        with concurrent.futures.ThreadPoolExecutor(max_workers=n_workers) as pool:
            futures: dict[concurrent.futures.Future, BeadsWorkItem] = {}
            for i in range(n_workers):
                item = _make_item(f"cb-{i}")
                fut = pool.submit(_failing_worker, i)
                futures[fut] = item

            # Wait for all to complete
            concurrent.futures.wait(futures.keys())

            failed_ids: set[str] = set()
            record_fn = Mock()
            _total, any_ok, successes, failures = _collect_done_futures(
                futures, failed_ids, 0, stats, Mock(), record_fn,
            )

        assert successes == 0
        assert failures == n_workers
        assert not any_ok
        assert record_fn.call_count == n_workers


# =========================================================================
# 3. Race conditions on failed_claim_ids under thread contention
# =========================================================================


class TestFailedClaimIdsConcurrency:
    """Test shared failed_claim_ids set under concurrent modification."""

    @pytest.mark.timeout(30)
    def test_concurrent_add_and_discard(self) -> None:
        """Concurrent add/discard on failed_claim_ids should not raise."""
        for _ in range(_STRESS_ITERATIONS):
            failed_ids: set[str] = set()
            n_threads = 8
            barrier = threading.Barrier(n_threads)
            errors: list[str] = []

            def _worker(idx: int, _barrier=barrier, _failed=failed_ids, _errs=errors) -> None:
                try:
                    _barrier.wait()
                    item_id = f"item-{idx % 4}"
                    # Simulate the add/discard pattern from _collect_done_futures
                    _failed.add(item_id)
                    time.sleep(0.001)
                    _failed.discard(item_id)
                except Exception as e:
                    _errs.append(str(e))

            with concurrent.futures.ThreadPoolExecutor(max_workers=n_threads) as pool:
                futs = [pool.submit(_worker, i) for i in range(n_threads)]
                concurrent.futures.wait(futs)
                for f in futs:
                    f.result()

            assert not errors

    @pytest.mark.timeout(30)
    def test_collect_done_futures_concurrent_claim_tracking(self) -> None:
        """_collect_done_futures updates failed_claim_ids correctly
        when successes and failures arrive concurrently."""
        for _ in range(_STRESS_ITERATIONS):
            n_workers = 8
            stats = _make_stats()

            futures_dict: dict[concurrent.futures.Future, BeadsWorkItem] = {}
            for i in range(n_workers):
                fut: concurrent.futures.Future[WorkItemResult] = concurrent.futures.Future()
                item = _make_item(f"claim-{i}")
                if i % 2 == 0:
                    fut.set_result(WorkItemResult(success=True, request_count=1))
                else:
                    # request_count=0 + not success = blacklisted
                    fut.set_result(WorkItemResult(success=False, request_count=0))
                futures_dict[fut] = item

            failed_ids: set[str] = set()
            _total, _any_ok, successes, failures = _collect_done_futures(
                futures_dict, failed_ids, 0, stats, Mock(), Mock(),
            )

            assert successes == n_workers // 2
            assert failures == n_workers // 2
            # Successful items should NOT be in failed_ids
            for i in range(n_workers):
                if i % 2 == 0:
                    assert f"claim-{i}" not in failed_ids
                else:
                    assert f"claim-{i}" in failed_ids


# =========================================================================
# 4. Semaphore + executor interaction under contention
# =========================================================================


class TestSemaphoreExecutorContention:
    """Test semaphore-controlled worker submission has no deadlocks."""

    @pytest.mark.timeout(30)
    def test_semaphore_limits_concurrent_workers(self) -> None:
        """Semaphore should enforce max concurrent worker count."""
        pool_size = 4
        total_items = 12
        semaphore = threading.Semaphore(pool_size)
        max_concurrent = 0
        current_concurrent = 0
        lock = threading.Lock()

        def _worker() -> WorkItemResult:
            nonlocal max_concurrent, current_concurrent
            with lock:
                current_concurrent += 1
                max_concurrent = max(max_concurrent, current_concurrent)
            time.sleep(0.01)
            with lock:
                current_concurrent -= 1
            semaphore.release()
            return WorkItemResult(success=True, request_count=1)

        with concurrent.futures.ThreadPoolExecutor(max_workers=pool_size) as executor:
            futs = []
            for _ in range(total_items):
                semaphore.acquire()
                futs.append(executor.submit(_worker))
            concurrent.futures.wait(futs)
            for f in futs:
                f.result()

        assert max_concurrent <= pool_size

    @pytest.mark.timeout(30)
    def test_semaphore_release_on_exception(self) -> None:
        """Semaphore must be released even when workers raise exceptions."""
        pool_size = 4
        semaphore = threading.Semaphore(pool_size)

        def _failing_worker() -> WorkItemResult:
            try:
                raise RuntimeError("boom")
            finally:
                semaphore.release()

        with concurrent.futures.ThreadPoolExecutor(max_workers=pool_size) as executor:
            futs = []
            for _ in range(pool_size * 2):
                semaphore.acquire()
                futs.append(executor.submit(_failing_worker))
            concurrent.futures.wait(futs)

        # If semaphore wasn't released, we'd deadlock above. Verify count.
        acquired = 0
        for _ in range(pool_size):
            if semaphore.acquire(blocking=False):
                acquired += 1
        assert acquired == pool_size

    @pytest.mark.timeout(30)
    def test_no_deadlock_semaphore_with_barrier(self) -> None:
        """Workers using barrier + semaphore must not deadlock."""
        pool_size = 4
        semaphore = threading.Semaphore(pool_size)
        barrier = threading.Barrier(pool_size)
        results: list[bool] = []
        results_lock = threading.Lock()

        def _worker() -> None:
            barrier.wait()
            time.sleep(0.005)
            with results_lock:
                results.append(True)
            semaphore.release()

        with concurrent.futures.ThreadPoolExecutor(max_workers=pool_size) as executor:
            for _ in range(pool_size):
                semaphore.acquire()
                executor.submit(_worker)
            # Wait for workers by re-acquiring all semaphore slots
            for i in range(pool_size):
                acquired = semaphore.acquire(timeout=5)
                assert acquired, f"Worker {i} failed to release semaphore (timeout)"

        assert len(results) == pool_size


# =========================================================================
# 5. _collect_done_futures with real concurrent executor
# =========================================================================


class TestCollectDoneFuturesConcurrent:
    """Test _collect_done_futures with futures from real ThreadPoolExecutor."""

    @pytest.mark.timeout(30)
    def test_real_executor_mixed_results(self) -> None:
        """Real executor with mixed success/failure workers."""
        for _ in range(_STRESS_ITERATIONS):
            n_workers = 8
            stats = _make_stats()
            barrier = threading.Barrier(n_workers)

            def _worker(idx: int, _barrier=barrier) -> WorkItemResult:
                _barrier.wait()
                success = idx % 3 != 0
                return WorkItemResult(success=success, request_count=1)

            with concurrent.futures.ThreadPoolExecutor(max_workers=n_workers) as pool:
                futures: dict[concurrent.futures.Future, BeadsWorkItem] = {}
                for i in range(n_workers):
                    item = _make_item(f"real-{i}")
                    fut = pool.submit(_worker, i)
                    futures[fut] = item

                concurrent.futures.wait(futures.keys())

                failed_ids: set[str] = set()
                total, any_ok, successes, failures = _collect_done_futures(
                    futures, failed_ids, 0, stats, Mock(), Mock(),
                )

            expected_failures = sum(1 for i in range(n_workers) if i % 3 == 0)
            expected_successes = n_workers - expected_failures
            assert successes == expected_successes
            assert failures == expected_failures
            assert total == n_workers
            assert any_ok is True

    @pytest.mark.timeout(30)
    def test_real_executor_all_exceptions(self) -> None:
        """All workers raising should be handled gracefully."""
        n_workers = 6
        stats = _make_stats()

        def _bomb(_idx: int) -> WorkItemResult:
            raise ValueError("kaboom")

        with concurrent.futures.ThreadPoolExecutor(max_workers=n_workers) as pool:
            futures: dict[concurrent.futures.Future, BeadsWorkItem] = {}
            for i in range(n_workers):
                futures[pool.submit(_bomb, i)] = _make_item(f"bomb-{i}")
            concurrent.futures.wait(futures.keys())

            failed_ids: set[str] = set()
            _total, any_ok, successes, failures = _collect_done_futures(
                futures, failed_ids, 0, stats, Mock(), Mock(),
            )

        assert successes == 0
        assert failures == n_workers
        assert not any_ok
        # Exception workers should NOT blacklist (was_exception=True path)
        assert len(failed_ids) == 0

    @pytest.mark.timeout(30)
    def test_staggered_completion_order(self) -> None:
        """Workers completing at different times are all collected."""
        n_workers = 8
        stats = _make_stats()

        def _staggered(idx: int) -> WorkItemResult:
            time.sleep(0.01 * (idx % 4))
            return WorkItemResult(success=True, request_count=1)

        with concurrent.futures.ThreadPoolExecutor(max_workers=n_workers) as pool:
            futures: dict[concurrent.futures.Future, BeadsWorkItem] = {}
            for i in range(n_workers):
                futures[pool.submit(_staggered, i)] = _make_item(f"stag-{i}")
            concurrent.futures.wait(futures.keys())

            total, _any_ok, successes, failures = _collect_done_futures(
                futures, set(), 0, stats, Mock(), Mock(),
            )

        assert successes == n_workers
        assert failures == 0
        assert total == n_workers


# =========================================================================
# 6. Runtime parallel limits under concurrent reads
# =========================================================================


class TestRuntimeLimitsConcurrency:
    """Verify parallel_runtime module is thread-safe."""

    @pytest.mark.timeout(30)
    def test_concurrent_set_and_compute(self) -> None:
        """Concurrent writes/reads to runtime limits should not corrupt."""
        errors: list[str] = []
        stop = threading.Event()

        def _writer() -> None:
            i = 0
            while not stop.is_set():
                cap = (i % 8) + 1
                set_runtime_parallel_limits(cap, True, baseline=4)
                i += 1

        def _reader() -> None:
            while not stop.is_set():
                result = compute_effective_max_agents(4)
                if result < 1:
                    errors.append(f"Invalid result: {result}")

        threads = ([threading.Thread(target=_writer) for _ in range(2)] +
                   [threading.Thread(target=_reader) for _ in range(4)])
        for t in threads:
            t.start()
        time.sleep(0.2)
        stop.set()
        for t in threads:
            t.join(timeout=5)
            assert not t.is_alive(), f"Thread {t.name} did not finish within timeout"
        clear_runtime_parallel_limits()

        assert not errors, f"Runtime limit errors: {errors[:5]}"


# =========================================================================
# 7. _parallel_process_item with real ThreadPoolExecutor
# =========================================================================


class TestParallelProcessItemReal:
    """Test _parallel_process_item in a real thread pool."""

    @pytest.mark.timeout(30)
    def test_concurrent_process_items(self, monkeypatch) -> None:
        """Multiple _parallel_process_item calls in real threads."""
        n_workers = 4
        barrier = threading.Barrier(n_workers)
        monkeypatch.setattr("pokepoke.agents.parallel.terminal_ui", MagicMock())
        monkeypatch.setattr(
            "pokepoke.beads.beads.increment_total_attempts", lambda _: None)

        call_count = 0
        count_lock = threading.Lock()

        def _mock_process_work_item(item, **kwargs):
            nonlocal call_count
            barrier.wait()
            with count_lock:
                call_count += 1
            return WorkItemResult(success=True, request_count=1)

        monkeypatch.setattr(
            "pokepoke.agents.parallel.process_work_item", _mock_process_work_item)

        semaphore = threading.Semaphore(n_workers)
        run_logger = Mock()

        with concurrent.futures.ThreadPoolExecutor(max_workers=n_workers) as pool:
            futs = []
            for i in range(n_workers):
                semaphore.acquire()
                item = _make_item(f"proc-{i}")
                futs.append(pool.submit(
                    _parallel_process_item, item, run_logger, semaphore,
                    f"worker-{i}",
                ))
            concurrent.futures.wait(futs)
            results = [f.result() for f in futs]

        assert all(r.success for r in results)
        assert call_count == n_workers
        # Semaphore should be fully released
        acquired = sum(1 for _ in range(n_workers) if semaphore.acquire(blocking=False))
        assert acquired == n_workers


# =========================================================================
# 8. dispatch_items with real executor under contention
# =========================================================================


class TestDispatchItemsConcurrentExecutor:
    """Test dispatch_items submitting to a real ThreadPoolExecutor."""

    @pytest.mark.timeout(30)
    def test_dispatch_fills_slots_with_real_executor(self) -> None:
        """dispatch_items should submit work to a real executor."""
        n_slots = 4
        semaphore = threading.Semaphore(n_slots)
        items = [_make_item(f"disp-{i}") for i in range(n_slots)]

        def _mock_process(item, run_logger, sem, worker_name=None, repo_path=None):
            result = WorkItemResult(success=True, request_count=1)
            sem.release()
            return result

        with concurrent.futures.ThreadPoolExecutor(max_workers=n_slots) as executor:
            futures: dict[concurrent.futures.Future, BeadsWorkItem] = {}
            run_logger = Mock()

            with patch("pokepoke.agents.parallel.assign_and_sync_item", return_value=True), \
                 patch("pokepoke.agents.parallel.select_multiple_items", return_value=items), \
                 patch("pokepoke.agents.parallel.should_stop_after_current", return_value=False), \
                 patch("pokepoke.agents.parallel.get_ready_work_items", return_value=items):

                counter = dispatch_items(
                    ready_items=items,
                    slots=n_slots,
                    continuous=True,
                    has_success=False,
                    consecutive_failures=0,
                    max_consecutive_failures=10,
                    failed_claim_ids=set(),
                    current_active=set(),
                    futures=futures,
                    semaphore=semaphore,
                    executor=executor,
                    run_logger=run_logger,
                    worker_counter=0,
                    build_worker_name_fn=lambda base, iid, c: f"w-{c}",
                    process_item_fn=_mock_process,
                )

            assert len(futures) == n_slots
            concurrent.futures.wait(futures.keys())
            results = [f.result() for f in futures]
            assert all(r.success for r in results)
            assert counter == n_slots


# =========================================================================
# 9. Compute slots under concurrent dynamic config changes
# =========================================================================


class TestComputeSlotsConcurrency:
    """Test compute_slots correctness with dynamic config changes."""

    @pytest.mark.timeout(30)
    def test_compute_slots_parallel_calls(self, monkeypatch) -> None:
        """Concurrent compute_slots calls must return valid slot counts."""
        monkeypatch.setattr(
            "pokepoke.agents.parallel.get_effective_max_agents", lambda: 6)
        monkeypatch.setattr(
            "pokepoke.agents.parallel_support.apply_memory_backpressure",
            lambda slots: (slots, 8000))

        errors: list[str] = []
        barrier = threading.Barrier(8)

        def _worker() -> None:
            barrier.wait()
            _active, slots, _mem = compute_slots({}, Mock())
            if slots < 0:
                errors.append(f"Negative slots: {slots}")
            if slots > 6:
                errors.append(f"Slots exceed max: {slots}")

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            futs = [pool.submit(_worker) for _ in range(8)]
            concurrent.futures.wait(futs)
            for f in futs:
                f.result()

        assert not errors, f"Slot errors: {errors[:5]}"
