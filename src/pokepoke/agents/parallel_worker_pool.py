"""ParallelWorkerPool: encapsulates ThreadPoolExecutor, semaphore, and futures tracking.

Thread-safe: Shared mutable state protected by threading.Lock.

CRITICAL FIX (PokePoke-82v1j): The collect_done_futures() function previously used
concurrent.futures.wait() to check for completed futures. This could cause indefinite
hangs even with a timeout when futures were in a bad state (deadlocked threads, zombie
subprocesses, or hung system calls). The orchestrator would appear frozen with agents
showing 0% CPU but never completing.

Solution: Removed all blocking wait() calls and rely solely on non-blocking .done()
polling. This ensures the polling loop never hangs and can always detect and handle
stalled agents through the health check mechanism.
"""

from __future__ import annotations

import concurrent.futures
import logging
import threading
import time
from typing import Any

from pokepoke.beads.beads_hierarchy import is_high_conflict_risk
from pokepoke.types import WorkItemResult
from pokepoke.types_beads import BeadsWorkItem, RecordFn
from pokepoke.types_stats import SessionStats
from pokepoke.utils.logging_utils import RunLogger

logger = logging.getLogger(__name__)
_Future = concurrent.futures.Future[WorkItemResult]

# Agent health monitoring configuration
_AGENT_HEALTH_CHECK_INTERVAL = 60.0  # Check agent health every 60 seconds
_AGENT_STALL_THRESHOLD = 1800.0  # Consider agent stalled after 30 minutes without progress
_MAX_STALLED_AGENTS = 3  # Trigger circuit breaker if this many agents are stalled

# Thread-safe helper functions
def _locked_snapshot(lock: threading.Lock | None, futures: dict[_Future, BeadsWorkItem]) -> tuple[list[_Future], int]:
    """Snapshot futures dict keys under lock."""
    if lock is not None:
        with lock:
            return list(futures.keys()), len(futures)
    return list(futures), len(futures)
def _locked_pop(lock: threading.Lock | None, futures: dict[_Future, BeadsWorkItem], fut: _Future) -> BeadsWorkItem | None:
    """Pop a future from the dict under lock."""
    if lock:
        with lock:
            return futures.pop(fut, None)
    return futures.pop(fut, None)
def _locked_futures_len(lock: threading.Lock | None, futures: dict[_Future, BeadsWorkItem]) -> int:
    """Return len(futures) under lock."""
    if lock:
        with lock:
            return len(futures)
    return len(futures)
def _locked_has_futures(lock: threading.Lock | None, futures: dict[_Future, BeadsWorkItem]) -> bool:
    """Return bool(futures) under lock."""
    if lock:
        with lock:
            return bool(futures)
    return bool(futures)
def _locked_add_to_set(lock: threading.Lock | None, target: set[str], value: str) -> None:
    """Add value to set under lock."""
    if lock:
        with lock:
            target.add(value)
    else:
        target.add(value)

def _locked_get_skip_and_active(
    lock: threading.Lock | None, failed_claim_ids: set[str],
    attempted_this_cycle: set[str], current_active: set[str],
) -> tuple[set[str], set[str]]:
    """Get combined skip IDs and snapshot of active IDs under lock."""
    if lock:
        with lock:
            return failed_claim_ids | attempted_this_cycle, set(current_active)
    return failed_claim_ids | attempted_this_cycle, set(current_active)
def _locked_register_dispatch(
    lock: threading.Lock | None, futures: dict[_Future, BeadsWorkItem],
    current_active: set[str], fut: _Future, item: BeadsWorkItem,
    future_start_times: dict[_Future, float] | None = None,
) -> None:
    """Register a dispatched item in futures dict and active set under lock."""
    if lock:
        with lock:
            futures[fut] = item
            current_active.add(item.id)
            if future_start_times is not None:
                future_start_times[fut] = time.time()
    else:
        futures[fut] = item
        current_active.add(item.id)
        if future_start_times is not None:
            future_start_times[fut] = time.time()
def _check_high_conflict_active(lock: threading.Lock | None, futures: dict[_Future, BeadsWorkItem]) -> bool:
    """Check if any high-conflict item is currently active."""
    if lock:
        with lock:
            return any(is_high_conflict_risk(i) for i in futures.values())
    return any(is_high_conflict_risk(i) for i in futures.values())
def _safe_unassign(item_id: str, run_logger: RunLogger, reason: str) -> None:
    """Safely unassign an item, logging any errors."""
    try:
        from pokepoke.agents.parallel import unassign_with_retry
        unassign_with_retry(item_id)
    except Exception as e:
        run_logger.log_orchestrator(f"Failed to unassign {item_id} ({reason}): {e}", level="WARNING")
def _drain_orphaned_futures(
    futures: dict[_Future, BeadsWorkItem], run_logger: RunLogger, lock: threading.Lock | None = None,
) -> None:
    """Cancel and drain any remaining futures when shutting down."""
    snapshot, _ = _locked_snapshot(lock, futures)
    for fut in snapshot:
        if not fut.done():
            fut.cancel()
        item = _locked_pop(lock, futures, fut)
        if item:
            _safe_unassign(item.id, run_logger, "orphaned")
def _update_failed_ids(
    lock: threading.Lock | None, failed_claim_ids: set[str],
    item_id: str, success: bool, was_exception: bool, request_count: int,
) -> None:
    """Update failed_claim_ids under lock based on result."""
    if lock:
        with lock:
            if not success and request_count == 0 and not was_exception:
                failed_claim_ids.add(item_id)
            elif success:
                failed_claim_ids.discard(item_id)
    elif not success and request_count == 0 and not was_exception:
        failed_claim_ids.add(item_id)
    elif success:
        failed_claim_ids.discard(item_id)

def _check_agent_health(
    futures: dict[_Future, BeadsWorkItem], future_start_times: dict[_Future, float],
    run_logger: RunLogger, lock: threading.Lock | None = None,
) -> int:
    """Check for stalled agents and take corrective action. Returns number of stalled agents detected."""
    current_time = time.time()
    stalled_count = 0
    stalled_items: list[str] = []
    stalled_futures: list[_Future] = []
    snapshot, _ = _locked_snapshot(lock, futures)
    for fut in snapshot:
        if not fut.done():
            start_time = future_start_times.get(fut)
            if start_time is not None:
                elapsed = current_time - start_time
                if elapsed > _AGENT_STALL_THRESHOLD:
                    if lock:
                        with lock:
                            item = futures.get(fut)
                    else:
                        item = futures.get(fut)
                    if item:
                        stalled_count += 1
                        stalled_items.append(f"{item.id} ({elapsed/60:.1f}m)")
                        stalled_futures.append(fut)
    if stalled_count > 0:
        run_logger.log_orchestrator(
            f"⚠️  Agent health: {stalled_count} agent(s) appear stalled: {', '.join(stalled_items)}",
            level="WARNING"
        )

        if stalled_count >= _MAX_STALLED_AGENTS:
            run_logger.log_orchestrator(
                f"🚨 Agent health: {stalled_count}/{_MAX_STALLED_AGENTS} agents stalled — cancelling hung futures",
                level="ERROR"
            )
            cancelled = 0
            for fut in stalled_futures:
                if fut.cancel():
                    cancelled += 1
                    item = _locked_pop(lock, futures, fut)
                    if item:
                        run_logger.log_orchestrator(
                            f"Cancelled stalled agent for {item.id}",
                            level="WARNING"
                        )
                        _safe_unassign(item.id, run_logger, "stalled-cancelled")
                        future_start_times.pop(fut, None)
            if cancelled > 0:
                run_logger.log_orchestrator(
                    f"Cancelled {cancelled} stalled agent(s) to break deadlock",
                    level="WARNING"
                )
    return stalled_count

def collect_done_futures(
    futures: dict[_Future, BeadsWorkItem], failed_claim_ids: set[str],
    total_requests: int, session_stats: SessionStats, run_logger: RunLogger,
    record_fn: RecordFn, lock: threading.Lock | None = None,
    future_start_times: dict[_Future, float] | None = None,
) -> tuple[int, bool, int, int]:
    """Collect completed futures and record results. Returns (total_requests, any_success, success_count, failure_count)."""
    snapshot, futures_len = _locked_snapshot(lock, futures)
    done_futs: set[_Future] = set()
    for fut in snapshot:
        if fut.done():
            done_futs.add(fut)
    # CRITICAL FIX: Avoid concurrent.futures.wait() which can hang indefinitely
    # even with timeout when futures are in hung state (deadlocked threads, zombie subprocesses).
    # Instead, rely solely on non-blocking .done() polling which cannot hang.
    # If no futures are done on first pass, we simply return empty batch - the polling
    # loop will check again in the next iteration (every 0.5s).
    if done_futs:
        run_logger.log_orchestrator(
            f"Agent lifecycle: collected {len(done_futs)} agent(s); "
            f"{futures_len - len(done_futs)} remain active")
    if future_start_times is not None and futures_len > 0:
        _check_agent_health(futures, future_start_times, run_logger, lock)
    any_success, success_count, failure_count = False, 0, 0
    for fut in done_futs:
        item = _locked_pop(lock, futures, fut)
        if item is None:
            continue
        if future_start_times is not None:
            future_start_times.pop(fut, None)
        was_exception = False
        try:
            result = fut.result()
        except Exception as exc:
            logger.error(f"\n❌ Agent for {item.id} raised: {exc}")
            run_logger.log_orchestrator(f"Agent error for {item.id}: {exc}", level="ERROR")
            result = WorkItemResult(success=False, request_count=0)
            was_exception = True
        _update_failed_ids(lock, failed_claim_ids, item.id, result.success, was_exception, result.request_count)
        if result.success:
            any_success = True
            success_count += 1
        else:
            failure_count += 1
        total_requests += result.request_count
        try:
            record_fn(item, result, session_stats, run_logger)
        except Exception as exc:
            logger.warning(f"record_fn raised for {item.id}: {exc}", exc_info=True)
            run_logger.log_orchestrator(f"Error recording result for {item.id}: {exc}", level="ERROR")

    return total_requests, any_success, success_count, failure_count
# Pool class
class ParallelWorkerPool:
    """Manages ThreadPoolExecutor, Semaphore, and futures dict for parallel workers.
    All _futures access is protected by _lock for thread-safety."""

    def __init__(self, pool_size: int) -> None:
        self._lock = threading.Lock()
        self._semaphore = threading.Semaphore(pool_size)
        self._futures: dict[_Future, BeadsWorkItem] = {}
        self._future_start_times: dict[_Future, float] = {}  # Track when futures were dispatched
        self._executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=pool_size, thread_name_prefix="pokepoke-agent")
        self._last_health_check = time.time()

    @property
    def lock(self) -> threading.Lock:
        """The pool-wide lock that protects shared state."""
        return self._lock
    @property
    def futures(self) -> dict[_Future, BeadsWorkItem]:
        """Direct reference to futures dict. Access should be protected by lock."""
        return self._futures
    @property
    def semaphore(self) -> threading.Semaphore:
        """The pool-wide semaphore that caps concurrent workers."""
        return self._semaphore
    @property
    def executor(self) -> concurrent.futures.ThreadPoolExecutor:
        """The underlying ThreadPoolExecutor."""
        return self._executor
    @property
    def future_start_times(self) -> dict[_Future, float]:
        """Direct reference to future start times dict. Access should be protected by lock."""
        return self._future_start_times
    @property
    def active_count(self) -> int:
        """Number of futures currently tracked."""
        with self._lock:
            return len(self._futures)
    @property
    def active_ids(self) -> set[str]:
        """Set of work-item IDs with a tracked future."""
        with self._lock:
            return {item.id for item in self._futures.values()}

    def dispatch_item(self, item: BeadsWorkItem, run_logger: RunLogger,
                      process_item_fn: Any, worker_name: str) -> None:
        """Acquire semaphore and submit item to the pool."""
        self._semaphore.acquire()
        try:
            fut = self._executor.submit(process_item_fn, item, run_logger, self._semaphore, worker_name)
        except Exception:
            self._semaphore.release()
            raise
        with self._lock:
            self._futures[fut] = item
    def collect_done(self, failed_claim_ids: set[str], total_requests: int,
                     session_stats: SessionStats, run_logger: RunLogger,
                     record_fn: RecordFn) -> tuple[int, bool, int, int]:
        """Collect completed futures and record results."""
        # Always pass future_start_times for health monitoring
        # The collect_done_futures function will decide when to run checks
        # based on the _AGENT_HEALTH_CHECK_INTERVAL
        current_time = time.time()
        should_check_health = (current_time - self._last_health_check) >= _AGENT_HEALTH_CHECK_INTERVAL

        result = collect_done_futures(
            self._futures, failed_claim_ids, total_requests,
            session_stats, run_logger, record_fn, lock=self._lock,
            future_start_times=self._future_start_times if should_check_health else None)

        if should_check_health:
            self._last_health_check = current_time

        return result
    def has_active_workers(self) -> bool:
        """Return True if any futures are still pending or running."""
        with self._lock:
            return bool(self._futures)
    def shutdown(self, *, wait: bool = True, cancel_futures: bool = False) -> None:
        """Shut down the underlying ThreadPoolExecutor."""
        self._executor.shutdown(wait=wait, cancel_futures=cancel_futures)

def update_circuit_breaker(
    batch_successes: int, batch_failures: int, consecutive_failures: int,
    max_consecutive_failures: int, futures: dict[_Future, BeadsWorkItem],
    run_logger: RunLogger, lock: threading.Lock | None = None,
) -> tuple[int, bool]:
    """Update the circuit breaker counter. Returns (consecutive_failures, tripped)."""
    if batch_failures > 0 and batch_successes == 0:
        consecutive_failures += 1
    elif batch_successes > 0:
        consecutive_failures = 0
    tripped = consecutive_failures >= max_consecutive_failures
    if tripped:
        futures_len = _locked_futures_len(lock, futures)
        run_logger.log_orchestrator(
            f"Circuit breaker: {consecutive_failures} consecutive failures — "
            f"stopping dispatch, draining {futures_len} remaining agent(s)", level="ERROR")
    return consecutive_failures, tripped

def update_memory_circuit_breaker(
    available_mb: int,
    memory_floor_mb: int,
    threshold_polls: int,
    consecutive_low_polls: int,
    futures: dict[_Future, BeadsWorkItem],
    run_logger: RunLogger,
    lock: threading.Lock | None = None,
) -> tuple[int, bool]:
    """Track consecutive memory-floor violations. Returns (consecutive_low_polls, tripped)."""
    # avail_mb == 0 means memory monitoring is unavailable (non-Windows or error)
    # Preserve counter when monitoring fails - don't reset accumulated pressure evidence
    if available_mb > 0 and available_mb < memory_floor_mb:
        consecutive_low_polls += 1
    elif available_mb > 0:
        # Confirmed above floor -- safe to reset
        consecutive_low_polls = 0
    # else: available_mb == 0 -- unknown state, preserve counter as-is

    tripped = consecutive_low_polls >= threshold_polls
    if tripped:
        futures_len = _locked_futures_len(lock, futures)
        run_logger.log_orchestrator(
            f"Memory circuit breaker: {consecutive_low_polls} consecutive low-memory polls "
            f"({available_mb}MB < {memory_floor_mb}MB) — stopping dispatch, "
            f"draining {futures_len} remaining agent(s)", level="ERROR")
    return consecutive_low_polls, tripped

def compute_slots(
    futures: dict[_Future, BeadsWorkItem], run_logger: RunLogger, lock: threading.Lock | None = None,
) -> tuple[set[str], int, int]:
    """Compute available dispatch slots with memory backpressure."""
    from pokepoke.agents.parallel import get_effective_max_agents
    from pokepoke.utils.memory_utils import (
        apply_memory_backpressure,
        get_cpu_usage_percent,
        get_process_rss_mb,
    )
    if lock:
        with lock:
            current_active = {i.id for i in futures.values()}
            futures_len = len(futures)
    else:
        current_active = {i.id for i in futures.values()}
        futures_len = len(futures)
    current_max = get_effective_max_agents()
    slots = current_max - futures_len
    slots, avail_mb = apply_memory_backpressure(slots)
    if avail_mb > 0 and slots == 0 and current_max - futures_len > 0:
        run_logger.log_orchestrator(f"Memory low ({avail_mb}MB) — blocking agents", level="WARNING")
    elif avail_mb > 0 and slots < current_max - futures_len:
        run_logger.log_orchestrator(f"Memory pressure ({avail_mb}MB) — {slots} slot(s)", level="WARNING")
    rss_mb = get_process_rss_mb()
    cpu_percent = get_cpu_usage_percent()
    run_logger.log_polling(
        f"Lifecycle: active={futures_len} max={current_max} slots={slots} mem={avail_mb}MB rss={rss_mb}MB cpu={cpu_percent:.1f}%"
    )
    return current_active, slots, avail_mb
