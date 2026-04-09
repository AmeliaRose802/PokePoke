"""Support functions extracted from parallel.py for file length compliance."""

from __future__ import annotations

import concurrent.futures
import logging
import threading
import time
from typing import Any

from pokepoke.agents.parallel_worker_pool import (
    _check_high_conflict_active,
    _locked_add_to_set,
    _locked_futures_len,
    _locked_get_skip_and_active,
    _locked_has_futures,
    _locked_register_dispatch,
    _safe_unassign,
)
from pokepoke.agents.parallel_worker_pool import (
    compute_slots as compute_slots,
)
from pokepoke.agents.parallel_worker_pool import (
    update_circuit_breaker as update_circuit_breaker,
)
from pokepoke.beads.beads_hierarchy import is_high_conflict_risk
from pokepoke.desktop import terminal_ui
from pokepoke.types import BeadsWorkItem, RecordFn, SessionStats, WorkItemResult
from pokepoke.utils.logging_utils import RunLogger
from pokepoke.utils.preflight_log_utils import handle_preflight_checks
from pokepoke.utils.shutdown import is_shutting_down

logger = logging.getLogger(__name__)
_Future = concurrent.futures.Future[WorkItemResult]


def finalize_workers(
    futures: dict[_Future, BeadsWorkItem], session_stats: SessionStats,
    start_time: float, total_requests: int, run_logger: RunLogger,
    record_fn: RecordFn, lock: threading.Lock | None = None,
) -> tuple[int, bool]:
    """Wait for remaining workers and collect results."""
    timeout_occurred = False
    if lock:
        with lock:
            if not futures:
                return total_requests, timeout_occurred
            run_logger.log_orchestrator(f"Waiting for {len(futures)} active workers")
            snapshot = list(futures.keys())
    else:
        if not futures:
            return total_requests, timeout_occurred
        run_logger.log_orchestrator(f"Waiting for {len(futures)} active workers")
        snapshot = list(futures.keys())
    _dummy = BeadsWorkItem(id="?", title="?", status="?", priority=0, issue_type="?")
    try:
        for fut in concurrent.futures.as_completed(snapshot, timeout=300):
            if lock:
                with lock:
                    item = futures.pop(fut, _dummy)
            else:
                item = futures.pop(fut, _dummy)
            try:
                result = fut.result()
                run_logger.log_orchestrator(f"Worker completed {item.id}")
            except Exception as e:
                run_logger.log_orchestrator(f"Worker failed {item.id}: {e}", level="ERROR")
                result = WorkItemResult(success=False, request_count=0)
            total_requests += result.request_count
            try:
                record_fn(item, result, session_stats, run_logger)
            except Exception as exc:
                logger.warning(f"record_fn failed {item.id}: {exc}", exc_info=True)
            terminal_ui.ui.update_stats(session_stats, time.time() - start_time)
    except concurrent.futures.TimeoutError:
        if lock:
            with lock:
                cancelled = sum(1 for f in list(futures.keys()) if f.cancel())
        else:
            cancelled = sum(1 for f in list(futures.keys()) if f.cancel())
        run_logger.log_orchestrator(f"Cancelled {cancelled} workers; timeout", level="WARNING")
        timeout_occurred = True
        _drain_orphaned_futures(futures, session_stats, start_time, run_logger, record_fn, lock)
    run_logger.log_orchestrator("Workers completed")
    terminal_ui.ui.update_stats(session_stats, time.time() - start_time)
    return total_requests, timeout_occurred


def _drain_orphaned_futures(
    futures: dict[_Future, BeadsWorkItem], session_stats: SessionStats,
    start_time: float, run_logger: RunLogger, record_fn: RecordFn, lock: threading.Lock | None = None,
) -> None:
    """Drain futures remaining after a timeout."""
    if lock:
        with lock:
            orphaned = list(futures.items())
            futures.clear()
    else:
        orphaned = list(futures.items())
        futures.clear()
    if not orphaned:
        return
    run_logger.log_orchestrator(f"Draining {len(orphaned)} orphan(s)", level="WARNING")
    for fut, item in orphaned:
        result = WorkItemResult(success=False, request_count=0)
        if fut.done():
            try:
                result = fut.result(timeout=0)
            except Exception as e:
                run_logger.log_orchestrator(
                    f"Failed to retrieve result for {item.id}: {e}", level="WARNING"
                )
        try:
            record_fn(item, result, session_stats, run_logger)
        except Exception as e:
            run_logger.log_orchestrator(
                f"Failed to record result for {item.id}: {e}", level="WARNING"
            )
        _safe_unassign(item.id, run_logger, "orphan")
        terminal_ui.ui.update_stats(session_stats, time.time() - start_time)

def drain_circuit_breaker(
    futures: dict[_Future, BeadsWorkItem],
    failed_claim_ids: set[str],
    total_requests: int,
    session_stats: SessionStats,
    run_logger: RunLogger,
    record_fn: RecordFn,
    collect_fn: Any,
    mode_name: str,
    lock: threading.Lock | None = None,
) -> int:
    """Drain remaining futures after circuit breaker trips. Returns updated total_requests.

    Parameters
    ----------
    lock:
        Optional lock protecting *futures*. When provided, the lock is held
        during reads/mutations to ensure thread-safety.
    """
    from pokepoke.config import get_config
    total_requests, _any, _succ, _fail = collect_fn(
        futures, failed_claim_ids, total_requests, session_stats, run_logger, record_fn, lock)
    if not _locked_has_futures(lock, futures):
        return total_requests
    drain_timeout = get_config().circuit_breaker_drain_timeout
    futures_len = _locked_futures_len(lock, futures)
    run_logger.log_orchestrator(f"Circuit breaker: draining {futures_len} remaining agent(s)")
    if drain_timeout > 0:
        run_logger.log_orchestrator(f"Circuit breaker: drain timeout set to {drain_timeout}s")
    terminal_ui.ui.update_header(
        "PokePoke", f"{mode_name} Mode", f"Draining {futures_len} agents (circuit breaker)")
    start_time = time.time()
    while _locked_has_futures(lock, futures):
        if is_shutting_down():
            run_logger.log_orchestrator("Circuit breaker: shutdown signal received during drain")
            break
        if drain_timeout > 0 and (time.time() - start_time) >= drain_timeout:
            futures_len = _locked_futures_len(lock, futures)
            run_logger.log_orchestrator(
                f"Circuit breaker: drain timeout ({drain_timeout}s) exceeded with "
                f"{futures_len} agent(s) still running — forcibly terminating",
                level="WARNING")
            _drain_orphaned_futures(futures, session_stats, start_time, run_logger, record_fn, lock)
            break
        total_requests, _any, _succ, _fail = collect_fn(
            futures, failed_claim_ids, total_requests, session_stats, run_logger, record_fn, lock)
        if not _locked_has_futures(lock, futures):
            run_logger.log_orchestrator("Circuit breaker: all remaining agents finished")
            break
        sleep_remaining = 7.0
        while sleep_remaining > 0 and not is_shutting_down() and _locked_has_futures(lock, futures):
            time.sleep(min(0.5, sleep_remaining))
            sleep_remaining -= 0.5
    return total_requests

def _should_skip_item(
    item: BeadsWorkItem,
    futures: dict[_Future, BeadsWorkItem],
    dispatched: int,
    failed_claim_ids: set[str],
    run_logger: RunLogger,
    lock: threading.Lock | None = None,
) -> bool:
    """Return True if this item should be skipped during dispatch."""
    futures_len = _locked_futures_len(lock, futures)
    if is_high_conflict_risk(item) and (futures_len > 0 or dispatched > 0):
        run_logger.log_orchestrator(
            f"Deferring high-conflict {item.id} — other items active")
        return True
    return False


def dispatch_items(
    ready_items: list[BeadsWorkItem],
    slots: int,
    continuous: bool,
    has_success: bool,
    consecutive_failures: int,
    max_consecutive_failures: int,
    failed_claim_ids: set[str],
    current_active: set[str],
    futures: dict[_Future, BeadsWorkItem],
    semaphore: threading.Semaphore,
    executor: concurrent.futures.ThreadPoolExecutor,
    run_logger: RunLogger,
    worker_counter: int,
    build_worker_name_fn: Any,
    process_item_fn: Any,
    lock: threading.Lock | None = None,
) -> int:
    """Select, claim, and submit work items. Returns updated worker_counter.

    Parameters
    ----------
    lock:
        Optional lock protecting *futures*, *failed_claim_ids*, and *current_active*.
        When provided, the lock is held during mutations to ensure thread-safety.
    """
    from pokepoke.agents.agent_context import get_agent_name
    from pokepoke.agents.parallel import assign_and_sync_item, select_multiple_items, should_stop_after_current
    if slots <= 0 or should_stop_after_current():
        return worker_counter
    if (not continuous and has_success) or consecutive_failures >= max_consecutive_failures:
        return worker_counter
    if _check_high_conflict_active(lock, futures):
        run_logger.log_orchestrator("High-conflict item active — deferring new dispatches")
        return worker_counter

    attempted_this_cycle: set[str] = set()
    dispatched = logged_replenish = submit_failed = 0

    while dispatched < slots and not submit_failed:
        cycle_skip, active_snapshot = _locked_get_skip_and_active(
            lock, failed_claim_ids, attempted_this_cycle, current_active)

        selected_items = select_multiple_items(
            ready_items, count=slots - dispatched,
            skip_ids=cycle_skip, claimed_ids=active_snapshot,
        )

        if not selected_items:
            break

        if not logged_replenish:
            run_logger.log_orchestrator(f"Replenishing up to {slots} open slot(s)")
            logged_replenish = True

        pre_attempt_size = len(attempted_this_cycle)
        made_progress, high_conflict_dispatched = False, False

        for item in selected_items:
            if high_conflict_dispatched:
                break
            attempted_this_cycle.add(item.id)

            if _should_skip_item(item, futures, dispatched, failed_claim_ids, run_logger, lock):
                continue

            worker_counter += 1
            base_name = get_agent_name(default="pokepoke")
            worker_name = build_worker_name_fn(base_name, item.id, worker_counter)

            if not assign_and_sync_item(item.id, agent_name=worker_name):
                run_logger.log_orchestrator(f"Claim failed {item.id} (worker: {worker_name})", level="WARNING")
                _locked_add_to_set(lock, failed_claim_ids, item.id)
                continue

            run_logger.log_orchestrator(f"Submitting item: {item.id} - {item.title} (worker: {worker_name})")
            semaphore.acquire()
            try:
                fut = executor.submit(process_item_fn, item, run_logger, semaphore, worker_name)
            except Exception as e:
                logger.warning(f"Failed to submit work item {item.id} to executor: {e}")
                run_logger.log_orchestrator(f"Executor submit failed for {item.id}: {e}", level="ERROR")
                semaphore.release()
                _safe_unassign(item.id, run_logger, "submit-failed")
                submit_failed = True
                break

            _locked_register_dispatch(lock, futures, current_active, fut, item)
            dispatched += 1
            made_progress = True
            if is_high_conflict_risk(item):
                high_conflict_dispatched = True

        if not made_progress and len(attempted_this_cycle) <= pre_attempt_size:
            break
        if high_conflict_dispatched:
            break

    return worker_counter

def run_preflight_and_repo_checks(
    main_repo_path: Any, run_logger: RunLogger, consecutive_preflight_failures: int,
    max_preflight_failures: int, check_and_commit_main_repo_fn: Any = None,
    get_ready_work_items_fn: Any = None,
) -> tuple[bool, int, list[BeadsWorkItem]]:
    """Run pre-flight health checks, repo status check, and fetch ready items."""
    if check_and_commit_main_repo_fn is None:
        from pokepoke.git.repo_check import check_and_commit_main_repo as check_and_commit_main_repo_fn
    if get_ready_work_items_fn is None:
        from pokepoke.beads.beads import get_ready_work_items as get_ready_work_items_fn
    run_logger.log_polling("Running pre-flight health checks")
    should_continue, is_critical = handle_preflight_checks(main_repo_path, run_logger)
    if not should_continue:
        if is_critical:
            consecutive_preflight_failures += 1
            if consecutive_preflight_failures >= max_preflight_failures:
                run_logger.log_orchestrator(
                    f"Shutting down after {consecutive_preflight_failures} preflight failures", level="ERROR")
        return False, consecutive_preflight_failures, []
    consecutive_preflight_failures = 0
    run_logger.log_polling("Checking main repository status")
    if not check_and_commit_main_repo_fn(main_repo_path, run_logger):
        run_logger.log_orchestrator("Main repo check failed", level="ERROR")
        return False, consecutive_preflight_failures, []
    run_logger.log_polling("Fetching ready work from beads")
    try:
        ready_items = get_ready_work_items_fn()
    except Exception as e:
        run_logger.log_orchestrator(f"Failed to fetch ready items: {e}", level="ERROR")
        ready_items = None
    if ready_items is None:
        run_logger.log_orchestrator("Failed to query beads for work items - system error", level="ERROR")
        return False, consecutive_preflight_failures, []
    try:
        from pokepoke.beads.beads_query import get_in_progress_items
        in_progress = get_in_progress_items()
        if in_progress:
            ready_ids = {item.id for item in ready_items}
            resumed = [it for it in in_progress if it.id not in ready_ids]
            if resumed:
                run_logger.log_polling(f"Resuming {len(resumed)} in-progress item(s)")
                ready_items = resumed + ready_items
    except Exception as e:
        run_logger.log_orchestrator(f"Failed to fetch in-progress items: {e}", level="WARNING")
    return True, consecutive_preflight_failures, ready_items


def check_loop_exit(
    futures: dict[_Future, BeadsWorkItem],
    ready_items: list[BeadsWorkItem],
    continuous: bool,
    has_success: bool,
    total_requests: int,
    items_completed: int,
    session_stats: SessionStats,
    start_time: float,
    idle_sleep: float,
    mode_name: str,
    run_logger: RunLogger,
    finalize_fn: Any,
    get_ready_work_items_fn: Any = None,
    lock: threading.Lock | None = None,
) -> str | None:
    """Decide whether the main loop should exit, continue idling, or keep running.

    Parameters
    ----------
    lock:
        Optional lock protecting *futures*. When provided, the lock is held
        during reads to ensure thread-safety.
    """
    from pokepoke.agents.parallel import cancel_stop_after_current, should_stop_after_current
    if get_ready_work_items_fn is None:
        from pokepoke.agents.parallel import get_ready_work_items as get_ready_work_items_fn
    has_futures = _locked_has_futures(lock, futures)
    if should_stop_after_current() and not has_futures:
        cancel_stop_after_current()
        terminal_ui.ui.stop_and_capture()
        run_logger.log_orchestrator("Stop after current item requested - exiting")
        finalize_fn(session_stats, start_time, items_completed, total_requests, run_logger)
        return "break-success"
    if not continuous and not has_futures and total_requests > 0:
        terminal_ui.ui.update_stats(session_stats, time.time() - start_time)
        terminal_ui.ui.stop_and_capture()
        finalize_fn(session_stats, start_time, items_completed, total_requests, run_logger)
        return "break-done"
    if not has_futures and not ready_items:
        run_logger.log_polling("No ready items - double-checking beads")
        try:
            final_check = get_ready_work_items_fn()
            if final_check:
                run_logger.log_orchestrator(f"Found {len(final_check)} items on re-check")
                return "recheck"
        except Exception as e:
            run_logger.log_orchestrator(f"Final beads check failed: {e}", level="WARNING")

        if continuous:
            run_logger.enter_idle()
            run_logger.log_polling(f"Continuous: sleeping {idle_sleep:.1f}s (no items)")
            terminal_ui.ui.update_header("PokePoke", f"{mode_name} Mode", "Waiting for work...")
            time.sleep(idle_sleep)
            return "idle-continue"

        terminal_ui.ui.stop_and_capture()
        run_logger.log_orchestrator("No work items available - exiting")
        finalize_fn(session_stats, start_time, items_completed, total_requests, run_logger)
        return "break-empty"

    run_logger.exit_idle()
    return None
