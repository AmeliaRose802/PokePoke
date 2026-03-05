"""Support functions extracted from parallel.py for file length compliance."""

import concurrent.futures
import contextlib
import logging
import threading
import time
from typing import Any

from pokepoke.process_utils import apply_memory_backpressure, kill_orphaned_copilot_processes
from pokepoke.types import BeadsWorkItem, SessionStats, WorkItemResult
from pokepoke.logging_utils import RunLogger
from pokepoke import terminal_ui
from pokepoke.shutdown import is_shutting_down

logger = logging.getLogger(__name__)

_Future = concurrent.futures.Future[WorkItemResult]


def handle_preflight_checks(
    main_repo_path: Any, run_logger: RunLogger,
) -> tuple[bool, bool]:
    """Run preflight health checks. Returns (should_continue, is_critical_failure)."""
    from pokepoke.config import get_config
    from pokepoke.preflight_health import run_preflight_checks

    cfg = get_config()
    if not cfg.preflight_health.enabled:
        print("⏭️  Pre-flight health checks disabled via config")
        run_logger.log_orchestrator("Pre-flight health checks disabled via config")
        return True, False

    health_config = {k: getattr(cfg.preflight_health, k) for k in (
        'min_disk_space_gb', 'lock_timeout_seconds', 'worktree_test_timeout',
        'max_orphan_worktrees', 'git_operation_timeout', 'enable_self_repair',
        'max_repair_attempts',
    )}
    health_result = run_preflight_checks(repo_path=main_repo_path, config=health_config)

    if health_result.passed:
        print("✅ Pre-flight health checks passed")
        run_logger.log_orchestrator("Pre-flight health checks passed")
        for w in health_result.warnings:
            print(f"   ℹ️  {w}")
        return True, False

    print(f"\n❌ Pre-flight health checks failed ({len(health_result.errors)} error(s))")
    for e in health_result.errors:
        print(f"   • {e.check_name}: {e.message}")

    if health_result.self_repair_attempted:
        status = "completed successfully" if health_result.self_repair_successful else "failed"
        emoji = "✅" if health_result.self_repair_successful else "❌"
        print(f"{emoji} Self-repair {status}")

    if health_result.has_critical_errors() and cfg.preflight_health.fail_on_critical_errors:
        print("\n🚨 Critical health check failures detected - shutting down gracefully")
        run_logger.log_orchestrator("Critical health check failures - shutting down", level="ERROR")
        return False, True

    if health_result.has_environmental_errors() and cfg.preflight_health.fail_on_environmental_errors:
        print("\n⚠️  Environmental health check failures detected - shutting down gracefully")
        run_logger.log_orchestrator("Environmental health check failures - shutting down", level="ERROR")
        if cfg.preflight_health.graceful_shutdown_on_failure:
            return False, True

    for w in health_result.warnings:
        print(f"   ⚠️  Warning: {w}")
    run_logger.log_orchestrator(
        f"Pre-flight checks failed but continuing (errors: {len(health_result.errors)})", level="WARNING")
    return True, False


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
    run_logger.log_orchestrator("Workers completed")
    kill_orphaned_copilot_processes(expected_count=0)
    terminal_ui.ui.update_stats(session_stats, time.time() - start_time)
    return total_requests, timeout_occurred


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
    total_requests, _any, _succ, _fail = collect_fn(
        futures, failed_claim_ids, total_requests,
        session_stats, run_logger, record_fn,
    )
    run_logger.log_orchestrator(
        f"Circuit breaker: draining {len(futures)} remaining agent(s)")
    terminal_ui.ui.update_header(
        "PokePoke", f"{mode_name} Mode",
        f"Draining {len(futures)} agents (circuit breaker)",
    )
    for _ in range(10):
        if is_shutting_down() or not futures:
            break
        time.sleep(0.5)
    return total_requests


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
    # Late import from pokepoke.parallel so test monkey-patches work correctly
    from pokepoke.parallel import is_item_claimable, assign_and_sync_item, unassign_with_retry
    from pokepoke.parallel import select_multiple_items, should_stop_after_current
    from pokepoke.agent_context import get_agent_name

    if (
        slots <= 0
        or should_stop_after_current()
        or (not continuous and has_success)
        or consecutive_failures >= max_consecutive_failures
    ):
        return worker_counter

    selected_items = select_multiple_items(
        ready_items, count=slots,
        skip_ids=failed_claim_ids, claimed_ids=current_active,
    )
    if selected_items:
        run_logger.log_orchestrator(f"Replenishing {len(selected_items)} of {slots} open slot(s)")

    for item in selected_items:
        if not is_item_claimable(item.id):
            run_logger.log_orchestrator(f"Skipping {item.id} - already claimed by another agent")
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
            semaphore.release()
            with contextlib.suppress(Exception):
                unassign_with_retry(item.id)
            raise
        futures[fut] = item

    return worker_counter


def run_preflight_and_repo_checks(
    main_repo_path: Any,
    run_logger: RunLogger,
    consecutive_preflight_failures: int,
    max_preflight_failures: int,
    check_and_commit_main_repo_fn: Any = None,
    get_ready_work_items_fn: Any = None,
) -> tuple[bool, int, list[BeadsWorkItem]]:
    """Run pre-flight health checks, repo status check, and fetch ready items.

    Returns (should_continue, updated_preflight_failures, ready_items).
    """
    if check_and_commit_main_repo_fn is None:
        from pokepoke.repo_check import check_and_commit_main_repo as check_and_commit_main_repo_fn
    if get_ready_work_items_fn is None:
        from pokepoke.beads import get_ready_work_items as get_ready_work_items_fn

    run_logger.log_orchestrator("Running pre-flight health checks")
    should_continue, is_critical = handle_preflight_checks(main_repo_path, run_logger)
    if not should_continue:
        if is_critical:
            consecutive_preflight_failures += 1
            if consecutive_preflight_failures >= max_preflight_failures:
                run_logger.log_orchestrator(
                    f"Shutting down after {consecutive_preflight_failures} preflight failures",
                    level="ERROR",
                )
        return False, consecutive_preflight_failures, []
    consecutive_preflight_failures = 0

    run_logger.log_orchestrator("Checking main repository status")
    if not check_and_commit_main_repo_fn(main_repo_path, run_logger):
        run_logger.log_orchestrator("Main repo check failed", level="ERROR")
        return False, consecutive_preflight_failures, []

    run_logger.log_orchestrator("Fetching ready work from beads")
    try:
        ready_items = get_ready_work_items_fn()
    except Exception as e:
        run_logger.log_orchestrator(f"Failed to fetch ready items: {e}", level="ERROR")
        ready_items = []

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
    # Late import from pokepoke.parallel so test monkey-patches work correctly
    from pokepoke.parallel import should_stop_after_current, cancel_stop_after_current
    if get_ready_work_items_fn is None:
        from pokepoke.parallel import get_ready_work_items as get_ready_work_items_fn

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
        run_logger.log_orchestrator("No ready items - double-checking beads")
        try:
            final_check = get_ready_work_items_fn()
            if final_check:
                run_logger.log_orchestrator(f"Found {len(final_check)} items on re-check")
                return "recheck"
        except Exception as e:
            run_logger.log_orchestrator(f"Final beads check failed: {e}", level="WARNING")

        if continuous:
            run_logger.log_orchestrator(f"Continuous: sleeping {idle_sleep:.1f}s (no items)")
            terminal_ui.ui.update_header("PokePoke", f"{mode_name} Mode", "Waiting for work...")
            time.sleep(idle_sleep)
            return "idle-continue"

        terminal_ui.ui.stop_and_capture()
        run_logger.log_orchestrator("No work items available - exiting")
        finalize_fn(session_stats, start_time, items_completed, total_requests, run_logger)
        return "break-empty"

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

    tripped = False
    if consecutive_failures >= max_consecutive_failures:
        run_logger.log_orchestrator(
            f"Circuit breaker: {consecutive_failures} consecutive failures — "
            f"stopping dispatch, draining {len(futures)} remaining agent(s)",
            level="ERROR",
        )
        tripped = True
    return consecutive_failures, tripped


def compute_slots(
    futures: dict[_Future, BeadsWorkItem],
    run_logger: RunLogger,
) -> tuple[set[str], int, int]:
    """Compute available dispatch slots with memory backpressure."""
    from pokepoke.parallel import get_effective_max_agents

    current_active = {i.id for i in futures.values()}
    current_max = get_effective_max_agents()
    slots = current_max - len(futures)

    slots, avail_mb = apply_memory_backpressure(slots)
    if avail_mb > 0 and slots == 0 and current_max - len(futures) > 0:
        run_logger.log_orchestrator(f"Memory low ({avail_mb}MB) — blocking agents", level="WARNING")
    elif avail_mb > 0 and slots < current_max - len(futures):
        run_logger.log_orchestrator(f"Memory pressure ({avail_mb}MB) — {slots} slot(s)", level="WARNING")
    run_logger.log_orchestrator(f"Lifecycle: active={len(futures)} max={current_max} slots={slots} mem={avail_mb}MB")
    return current_active, slots, avail_mb
