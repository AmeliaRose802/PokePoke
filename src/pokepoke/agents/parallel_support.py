"""Support functions extracted from parallel.py for file length compliance."""

import concurrent.futures
import logging
import threading
import time
from typing import Any

from pokepoke.beads.beads_hierarchy import is_high_conflict_risk
from pokepoke.desktop import terminal_ui
from pokepoke.types import BeadsWorkItem, SessionStats, WorkItemResult
from pokepoke.utils.logging_utils import RunLogger
from pokepoke.utils.preflight_log_utils import handle_preflight_checks
from pokepoke.utils.process_utils import apply_memory_backpressure
from pokepoke.utils.shutdown import is_shutting_down

logger = logging.getLogger(__name__)

_Future = concurrent.futures.Future[WorkItemResult]


def _safe_unassign(item_id: str, run_logger: RunLogger, context: str) -> None:
    """Attempt to unassign a work item, logging a warning on failure."""
    from pokepoke.agents.parallel import unassign_with_retry
    try:
        unassign_with_retry(item_id)
        run_logger.log_orchestrator(f"Unassigned {context} {item_id}")
    except Exception as exc:
        msg = f"Failed to unassign {context} {item_id} — item may remain stuck: {exc}"
        logger.warning(msg, exc_info=True)
        run_logger.log_orchestrator(f"STUCK ITEM: unassign failed for {context} {item_id}: {exc}",
                                    level="WARNING")


def finalize_workers(
    futures: dict[_Future, BeadsWorkItem],
    session_stats: SessionStats,
    start_time: float,
    total_requests: int,
    run_logger: RunLogger,
    record_fn: Any,
) -> tuple[int, bool]:
    """Wait for remaining workers and collect results."""
    timeout_occurred = False
    if not futures:
        return total_requests, timeout_occurred
    run_logger.log_orchestrator(f"Waiting for {len(futures)} active workers")
    try:
        for fut in concurrent.futures.as_completed(list(futures.keys()), timeout=300):
            item = futures.pop(fut, BeadsWorkItem(id="?", title="?", status="?", priority=0, issue_type="?"))
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
                run_logger.log_orchestrator(f"record_fn error {item.id}: {exc}", level="ERROR")
            terminal_ui.ui.update_stats(session_stats, time.time() - start_time)
    except concurrent.futures.TimeoutError:
        cancelled = sum(1 for fut in list(futures.keys()) if fut.cancel())
        run_logger.log_orchestrator(f"Cancelled {cancelled} workers; timeout waiting", level="WARNING")
        timeout_occurred = True
        _drain_orphaned_futures(futures, session_stats, start_time, run_logger, record_fn)
    run_logger.log_orchestrator("Workers completed")
    # DISABLED: kill_orphaned_copilot_processes caused death spiral (PokePoke-q3t16)
    terminal_ui.ui.update_stats(session_stats, time.time() - start_time)
    return total_requests, timeout_occurred
def _drain_orphaned_futures(
    futures: dict[_Future, BeadsWorkItem],
    session_stats: SessionStats,
    start_time: float,
    run_logger: RunLogger,
    record_fn: Any,
) -> None:
    """Drain futures remaining after a timeout, recording each as a failure and unassigning."""
    orphaned = list(futures.items())
    futures.clear()
    if not orphaned:
        return
    run_logger.log_orchestrator(
        f"Draining {len(orphaned)} orphaned future(s) after timeout", level="WARNING",
    )
    for fut, item in orphaned:
        result = WorkItemResult(success=False, request_count=0)
        if fut.done():
            try:
                result = fut.result(timeout=0)
                run_logger.log_orchestrator(f"Orphan {item.id} had completed result")
            except Exception as e:
                run_logger.log_orchestrator(f"Orphan {item.id} raised: {e}", level="ERROR")
        try:
            record_fn(item, result, session_stats, run_logger)
        except Exception as exc:
            logger.warning(f"record_fn failed for orphan {item.id}: {exc}", exc_info=True)
        _safe_unassign(item.id, run_logger, "orphan")
        terminal_ui.ui.update_stats(session_stats, time.time() - start_time)

def drain_circuit_breaker(
    futures: dict[_Future, BeadsWorkItem],
    failed_claim_ids: set[str],
    total_requests: int,
    session_stats: SessionStats,
    run_logger: RunLogger,
    record_fn: Any,
    collect_fn: Any,
    mode_name: str,
) -> int:
    """Drain remaining futures after circuit breaker trips. Returns updated total_requests."""
    from pokepoke.config import get_config
    total_requests, _any, _succ, _fail = collect_fn(
        futures, failed_claim_ids, total_requests, session_stats, run_logger, record_fn)
    if not futures:
        return total_requests
    drain_timeout = get_config().circuit_breaker_drain_timeout
    run_logger.log_orchestrator(f"Circuit breaker: draining {len(futures)} remaining agent(s)")
    if drain_timeout > 0:
        run_logger.log_orchestrator(f"Circuit breaker: drain timeout set to {drain_timeout}s")
    terminal_ui.ui.update_header(
        "PokePoke", f"{mode_name} Mode", f"Draining {len(futures)} agents (circuit breaker)")
    start_time = time.time()
    while futures:
        if is_shutting_down():
            run_logger.log_orchestrator("Circuit breaker: shutdown signal received during drain")
            break
        if drain_timeout > 0 and (time.time() - start_time) >= drain_timeout:
            run_logger.log_orchestrator(
                f"Circuit breaker: drain timeout ({drain_timeout}s) exceeded with "
                f"{len(futures)} agent(s) still running — forcibly terminating",
                level="WARNING")
            _drain_orphaned_futures(futures, session_stats, start_time, run_logger, record_fn)
            break
        total_requests, _any, _succ, _fail = collect_fn(
            futures, failed_claim_ids, total_requests, session_stats, run_logger, record_fn)
        if not futures:
            run_logger.log_orchestrator("Circuit breaker: all remaining agents finished")
            break
        sleep_remaining = 7.0
        while sleep_remaining > 0 and futures and not is_shutting_down():
            time.sleep(min(0.5, sleep_remaining))
            sleep_remaining -= 0.5
    return total_requests

def _should_skip_item(
    item: BeadsWorkItem,
    futures: dict[_Future, BeadsWorkItem],
    dispatched: int,
    failed_claim_ids: set[str],
    run_logger: RunLogger,
) -> bool:
    """Return True if this item should be skipped during dispatch."""
    if is_high_conflict_risk(item) and (len(futures) > 0 or dispatched > 0):
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
) -> int:
    """Select, claim, and submit work items. Returns updated worker_counter."""
    from pokepoke.agents.agent_context import get_agent_name
    from pokepoke.agents.parallel import assign_and_sync_item, select_multiple_items, should_stop_after_current
    if (
        slots <= 0
        or should_stop_after_current()
        or (not continuous and has_success)
        or consecutive_failures >= max_consecutive_failures
    ):
        return worker_counter
    if any(is_high_conflict_risk(item) for item in futures.values()):
        run_logger.log_orchestrator("High-conflict item active — deferring new dispatches")
        return worker_counter

    attempted_this_cycle: set[str] = set()
    dispatched = logged_replenish = submit_failed = 0

    while dispatched < slots and not submit_failed:
        needed = slots - dispatched
        cycle_skip = failed_claim_ids | attempted_this_cycle

        selected_items = select_multiple_items(
            ready_items, count=needed,
            skip_ids=cycle_skip, claimed_ids=current_active,
        )

        if not selected_items:
            break

        if not logged_replenish:
            run_logger.log_orchestrator(f"Replenishing up to {slots} open slot(s)")
            logged_replenish = True

        pre_attempt_size = len(attempted_this_cycle)
        made_progress = False
        high_conflict_dispatched = False
        for item in selected_items:
            if high_conflict_dispatched:
                break
            attempted_this_cycle.add(item.id)

            if _should_skip_item(item, futures, dispatched, failed_claim_ids, run_logger):
                continue

            worker_counter += 1
            base_name = get_agent_name(default="pokepoke")
            worker_name = build_worker_name_fn(base_name, item.id, worker_counter)

            if not assign_and_sync_item(item.id, agent_name=worker_name):
                run_logger.log_orchestrator(f"Claim failed {item.id} (worker: {worker_name})", level="WARNING")
                failed_claim_ids.add(item.id)
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
            futures[fut] = item
            current_active.add(item.id)
            dispatched += 1
            made_progress = True
            if is_high_conflict_risk(item):
                high_conflict_dispatched = True

        if not made_progress:
            if len(attempted_this_cycle) > pre_attempt_size:
                continue
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
) -> str | None:
    """Decide whether the main loop should exit, continue idling, or keep running."""
    from pokepoke.agents.parallel import cancel_stop_after_current, should_stop_after_current
    if get_ready_work_items_fn is None:
        from pokepoke.agents.parallel import get_ready_work_items as get_ready_work_items_fn
    if should_stop_after_current() and not futures:
        cancel_stop_after_current()
        terminal_ui.ui.stop_and_capture()
        run_logger.log_orchestrator("Stop after current item requested - exiting")
        finalize_fn(session_stats, start_time, items_completed, total_requests, run_logger)
        return "break-success"
    if not continuous and not futures and total_requests > 0:
        terminal_ui.ui.update_stats(session_stats, time.time() - start_time)
        terminal_ui.ui.stop_and_capture()
        finalize_fn(session_stats, start_time, items_completed, total_requests, run_logger)
        return "break-done"
    if not futures and not ready_items:
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

def update_circuit_breaker(
    batch_successes: int, batch_failures: int,
    consecutive_failures: int,
    max_consecutive_failures: int,
    futures: dict[_Future, BeadsWorkItem],
    run_logger: RunLogger,
) -> tuple[int, bool]:
    """Update the circuit breaker counter. Returns (consecutive_failures, tripped)."""
    if batch_failures > 0 and batch_successes == 0:
        consecutive_failures += 1
    elif batch_successes > 0:
        consecutive_failures = 0

    tripped = consecutive_failures >= max_consecutive_failures
    if tripped:
        run_logger.log_orchestrator(
            f"Circuit breaker: {consecutive_failures} consecutive failures — "
            f"stopping dispatch, draining {len(futures)} remaining agent(s)",
            level="ERROR",
        )
    return consecutive_failures, tripped

def compute_slots(
    futures: dict[_Future, BeadsWorkItem],
    run_logger: RunLogger,
) -> tuple[set[str], int, int]:
    """Compute available dispatch slots with memory backpressure."""
    from pokepoke.agents.parallel import get_effective_max_agents
    current_active = {i.id for i in futures.values()}
    current_max = get_effective_max_agents()
    slots = current_max - len(futures)
    slots, avail_mb = apply_memory_backpressure(slots)
    if avail_mb > 0 and slots == 0 and current_max - len(futures) > 0:
        run_logger.log_orchestrator(f"Memory low ({avail_mb}MB) — blocking agents", level="WARNING")
    elif avail_mb > 0 and slots < current_max - len(futures):
        run_logger.log_orchestrator(f"Memory pressure ({avail_mb}MB) — {slots} slot(s)", level="WARNING")
    run_logger.log_polling(f"Lifecycle: active={len(futures)} max={current_max} slots={slots} mem={avail_mb}MB")
    return current_active, slots, avail_mb
