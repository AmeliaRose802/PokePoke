"""Parallel orchestrator loop for running multiple work items concurrently."""

import concurrent.futures
import contextlib
import logging
import threading
import time
from typing import Any

from pokepoke.parallel_runtime import clear_runtime_parallel_limits, compute_effective_max_agents, set_runtime_parallel_limits
from pokepoke.process_utils import apply_memory_backpressure, kill_orphaned_copilot_processes

from pokepoke.agent_context import get_agent_name, set_agent_name, clear_agent_name
from pokepoke.beads import get_ready_work_items, is_item_claimable, assign_and_sync_item, unassign_with_retry
from pokepoke.types import BeadsWorkItem, SessionStats, WorkItemResult
from pokepoke.workflow import process_work_item
from pokepoke.work_item_selection import select_multiple_items
from pokepoke.logging_utils import RunLogger
from pokepoke import terminal_ui
from pokepoke.repo_check import check_and_commit_main_repo
from pokepoke.shutdown import is_shutting_down, set_executor, should_stop_after_current, cancel_stop_after_current
from pokepoke.parallel_support import (
    finalize_workers as _finalize_workers,
    handle_preflight_checks as _handle_preflight_checks,
)

logger = logging.getLogger(__name__)

# Default pool size; raised when effective_parallel exceeds this.
_DEFAULT_PARALLEL_CEILING = 8

_IDLE_BASE_DELAY = 8.0   # Idle backoff start for continuous mode (exponential to max)
_IDLE_MAX_DELAY = 120.0
_MAX_CONSECUTIVE_FAILURES = 10  # Circuit breaker: stop dispatching after N consecutive failures
_MAX_CONSECUTIVE_PREFLIGHT_FAILURES = 5  # Stop after N preflight failures

# Type alias to satisfy mypy strict generics
_Future = concurrent.futures.Future[WorkItemResult]

_spawn_wakeup = threading.Event()  # Wake up loop for spawn agent requests from desktop UI
_SNAKE_TYPES: tuple[str, ...] = ("cobra", "corn", "rainbow_boa", "rattlesnake", "sea_snake")


def _get_dynamic_max_agents() -> int:
    """Re-read max_parallel_agents from config so UI changes take effect immediately."""
    from pokepoke.config import get_config
    return max(1, get_config().max_parallel_agents)


def get_effective_max_agents() -> int:
    """Return max agents to enforce right now."""
    return compute_effective_max_agents(_get_dynamic_max_agents())


def request_spawn_agent() -> None:
    """Signal the parallel loop to spawn an additional agent immediately."""
    _spawn_wakeup.set()


def _hash_string(value: str) -> int:
    """Mirror desktop snake hash: deterministic 32-bit string hash (Math.abs())."""
    hash_val = 0
    for ch in value:
        hash_val = ((hash_val << 5) - hash_val + ord(ch)) & 0xFFFFFFFF
    # Convert to signed 32-bit then absolute value to match JS behavior
    if hash_val & 0x80000000:
        hash_val -= 0x100000000
    return abs(hash_val)


def _snake_for_work_item(item_id: str) -> str:
    """Deterministically pick a snake type for a work item ID."""
    index = _hash_string(item_id) % len(_SNAKE_TYPES)
    return _SNAKE_TYPES[index]


def _build_worker_name(base_agent_name: str, item_id: str, counter: int) -> str:
    """Compose a worker name that includes the snake icon type and a unique suffix."""
    return f"{base_agent_name}-{_snake_for_work_item(item_id)}-worker-{counter}"


def _parallel_process_item(
    item: BeadsWorkItem, run_logger: RunLogger,
    semaphore: threading.Semaphore, worker_agent_name: str | None = None,
) -> WorkItemResult:
    """Thread-pool wrapper for process_work_item."""
    agent_id = f"{item.id}:{worker_agent_name}" if worker_agent_name else item.id
    display_name = worker_agent_name or "agent"

    if worker_agent_name:
        set_agent_name(worker_agent_name)

    def _push(status: str) -> None:
        terminal_ui.ui.push_agent_status(agent_id, display_name, iteration=1, status=status,
            work_item_id=item.id, work_item_title=item.title, agent_type="work")

    _push("running")
    terminal_ui.ui.log_orchestrator(f"\U0001f680 Agent {display_name} started item {item.id}: {item.title}")

    try:
        with terminal_ui.ui.agent_output_for(agent_id):
            result = process_work_item(item, interactive=False, run_logger=run_logger, agent_id=agent_id)
        success = result.success
        _push("success" if success else "failed")
        emoji = "\u2705" if success else "\u274c"
        terminal_ui.ui.log_orchestrator(f"{emoji} Agent {display_name} {'completed' if success else 'failed'} item {item.id}")
        return result
    except Exception as e:
        logger.warning(f"Failed to process work item {item.id} in parallel: {e}", exc_info=True)
        _push("failed")
        terminal_ui.ui.log_orchestrator(f"\u274c Agent {display_name} raised exception on item {item.id}")
        raise
    finally:
        clear_agent_name()
        semaphore.release()


def _collect_done_futures(
    futures: dict[_Future, BeadsWorkItem],
    failed_claim_ids: set[str],
    total_requests: int,
    session_stats: SessionStats,
    run_logger: RunLogger,
    record_fn: Any,
) -> tuple[int, bool, int, int]:
    """Collect completed futures and record results.

    Returns (total_requests, any_success, success_count, failure_count).
    """
    done_futs: set[_Future] = set()
    for fut in list(futures):
        if fut.done():
            done_futs.add(fut)

    if not done_futs and futures:
        done_batch, _ = concurrent.futures.wait(
            futures, timeout=2.0, return_when=concurrent.futures.FIRST_COMPLETED,
        )
        done_futs.update(done_batch)
        # Second sweep: catch futures that completed while wait() was running.
        # Without this, concurrent completions are missed and slots = 1 not N.
        for fut in list(futures):
            if fut.done():
                done_futs.add(fut)

    if done_futs:
        run_logger.log_orchestrator(
            f"Agent lifecycle: collected {len(done_futs)} agent(s); "
            f"{len(futures) - len(done_futs)} remain active"
        )

    any_success = False
    success_count = 0
    failure_count = 0
    for fut in done_futs:
        item = futures.pop(fut)
        was_exception = False
        try:
            result = fut.result()
        except Exception as exc:
            print(f"\n❌ Agent for {item.id} raised: {exc}")
            run_logger.log_orchestrator(f"Agent error for {item.id}: {exc}", level="ERROR")
            result = WorkItemResult(success=False, request_count=0)
            was_exception = True

        # Only blacklist explicit claim failures, not exception-crashed workers.
        if not result.success and result.request_count == 0 and not was_exception:
            failed_claim_ids.add(item.id)

        if result.success:
            failed_claim_ids.discard(item.id)
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


def run_parallel_loop(
    effective_parallel: int,
    mode_name: str,
    main_repo_path: Any,
    failed_claim_ids: set[str],
    session_stats: SessionStats,
    start_time: float,
    run_logger: RunLogger,
    continuous: bool,
    record_fn: Any,
    finalize_fn: Any,
    *, cli_override: bool = False,
) -> int:
    """Run the parallel orchestrator loop with a ThreadPoolExecutor."""
    total_requests = 0
    items_completed = 0
    pool_size = min(effective_parallel, _DEFAULT_PARALLEL_CEILING)
    if effective_parallel > _DEFAULT_PARALLEL_CEILING:
        logger.warning("max_parallel_agents (%d) exceeds ceiling (%d); clamping pool", effective_parallel, _DEFAULT_PARALLEL_CEILING)
    semaphore = threading.Semaphore(pool_size)
    futures: dict[_Future, BeadsWorkItem] = {}
    executor = concurrent.futures.ThreadPoolExecutor(
        max_workers=pool_size,
        thread_name_prefix="pokepoke-agent",
    )
    set_executor(executor)
    set_runtime_parallel_limits(effective_parallel, cli_override, baseline=_get_dynamic_max_agents() if cli_override else None)

    _worker_counter = 0
    finalized = False
    exit_code = 0
    has_success = False
    idle_sleep = _IDLE_BASE_DELAY
    consecutive_failures = 0
    consecutive_preflight_failures = 0

    try:
        while not is_shutting_down():
            run_logger.log_orchestrator("Running pre-flight health checks")
            should_continue, is_critical = _handle_preflight_checks(main_repo_path, run_logger)
            if not should_continue:
                if is_critical:
                    consecutive_preflight_failures += 1
                    if consecutive_preflight_failures >= _MAX_CONSECUTIVE_PREFLIGHT_FAILURES:
                        run_logger.log_orchestrator(f"Shutting down after {consecutive_preflight_failures} preflight failures", level="ERROR")
                        exit_code = 1
                        break
                exit_code = 1
                break
            consecutive_preflight_failures = 0

            run_logger.log_orchestrator("Checking main repository status")
            if not check_and_commit_main_repo(main_repo_path, run_logger):
                run_logger.log_orchestrator("Main repo check failed", level="ERROR")
                exit_code = 1
                break

            run_logger.log_orchestrator("Fetching ready work from beads")
            try:
                ready_items = get_ready_work_items()
            except Exception as e:
                run_logger.log_orchestrator(f"Failed to fetch ready items: {e}", level="ERROR")
                ready_items = []

            total_requests, any_success, batch_successes, batch_failures = _collect_done_futures(
                futures, failed_claim_ids, total_requests,
                session_stats, run_logger, record_fn,
            )
            items_completed = session_stats.items_completed

            has_success = has_success or any_success

            # Circuit breaker: track consecutive failures
            if batch_failures > 0 and batch_successes == 0:
                consecutive_failures += batch_failures
            elif batch_successes > 0:
                consecutive_failures = 0

            if consecutive_failures >= _MAX_CONSECUTIVE_FAILURES:
                run_logger.log_orchestrator(f"Circuit breaker: {consecutive_failures} consecutive failures", level="ERROR")
                if not futures:
                    exit_code = 1
                    break

            terminal_ui.ui.update_stats(session_stats, time.time() - start_time)

            current_active = {i.id for i in futures.values()}
            current_max = get_effective_max_agents()
            slots = current_max - len(futures)

            # Memory-pressure backpressure: reduce slots when system RAM is low
            slots, avail_mb = apply_memory_backpressure(slots)
            if avail_mb > 0 and slots == 0 and current_max - len(futures) > 0:
                run_logger.log_orchestrator(f"Memory low ({avail_mb}MB) — blocking agents", level="WARNING")
            elif avail_mb > 0 and slots < current_max - len(futures):
                run_logger.log_orchestrator(f"Memory pressure ({avail_mb}MB) — {slots} slot(s)", level="WARNING")
            run_logger.log_orchestrator(f"Lifecycle: active={len(futures)} max={current_max} slots={slots} mem={avail_mb}MB")

            # Periodically kill orphaned Copilot CLI processes that outlived their agent
            kill_orphaned_copilot_processes(expected_count=len(futures))

            if futures or ready_items:
                idle_sleep = _IDLE_BASE_DELAY

            if (
                slots > 0
                and not should_stop_after_current()
                and (continuous or not has_success)
                and consecutive_failures < _MAX_CONSECUTIVE_FAILURES
            ):
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

                    _worker_counter += 1
                    base_name = get_agent_name(default="pokepoke")
                    worker_name = _build_worker_name(base_name, item.id, _worker_counter)

                    # IMPORTANT: Claim (bd update + sync) in the orchestrator thread
                    # to avoid concurrent SQLite writes from multiple workers.
                    if not assign_and_sync_item(item.id, agent_name=worker_name):
                        run_logger.log_orchestrator(f"Claim failed {item.id} (worker: {worker_name})", level="WARNING")
                        failed_claim_ids.add(item.id)
                        continue

                    run_logger.log_orchestrator(f"Submitting item: {item.id} - {item.title} (worker: {worker_name})")
                    semaphore.acquire()
                    try:
                        fut = executor.submit(_parallel_process_item, item, run_logger, semaphore, worker_name)
                    except Exception as e:
                        logger.warning(f"Failed to submit work item {item.id} to executor: {e}")
                        semaphore.release()
                        # Best-effort: return item to queue since no worker will run it.
                        with contextlib.suppress(Exception):
                            unassign_with_retry(item.id)
                        raise
                    futures[fut] = item

            if should_stop_after_current() and not futures:
                cancel_stop_after_current()
                terminal_ui.ui.stop_and_capture()
                run_logger.log_orchestrator("Stop after current item requested - exiting")
                finalize_fn(session_stats, start_time, items_completed, total_requests, run_logger)
                finalized = True
                exit_code = 0
                break

            if not continuous and not futures and total_requests > 0:
                terminal_ui.ui.update_stats(session_stats, time.time() - start_time)
                terminal_ui.ui.stop_and_capture()
                finalize_fn(session_stats, start_time, items_completed, total_requests, run_logger)
                finalized = True
                exit_code = 0 if has_success else 1
                break

            if not futures and not ready_items:
                run_logger.log_orchestrator("No ready items - double-checking beads")
                try:
                    final_check = get_ready_work_items()
                    if final_check:
                        run_logger.log_orchestrator(f"Found {len(final_check)} items on re-check")
                        idle_sleep = _IDLE_BASE_DELAY
                        continue  # Go back to main loop to process these items
                except Exception as e:
                    run_logger.log_orchestrator(f"Final beads check failed: {e}", level="WARNING")

                if continuous:
                    run_logger.log_orchestrator(f"Continuous: sleeping {idle_sleep:.1f}s (no items)")
                    terminal_ui.ui.update_header("PokePoke", f"{mode_name} Mode", "Waiting for work...")
                    time.sleep(idle_sleep)
                    idle_sleep = min(_IDLE_MAX_DELAY, idle_sleep * 2)
                    continue

                terminal_ui.ui.stop_and_capture()
                run_logger.log_orchestrator("No work items available - exiting")
                finalize_fn(session_stats, start_time, items_completed, total_requests, run_logger)
                finalized = True
                exit_code = 0
                break

            terminal_ui.ui.update_header("PokePoke", f"{mode_name} Mode", f"{len(futures)} agents active")
            for _ in range(10):
                if is_shutting_down() or _spawn_wakeup.is_set():
                    break
                time.sleep(0.5)
            _spawn_wakeup.clear()

    finally:
        total_requests, timeout_occurred = _finalize_workers(futures, session_stats, start_time, total_requests, run_logger, record_fn)
        executor.shutdown(wait=True, cancel_futures=timeout_occurred)
        set_executor(None)
        clear_runtime_parallel_limits()
        if not finalized:
            print("\n🏁 Finalizing session...")
            run_logger.log_orchestrator("Finalizing session on exit")
            if terminal_ui.ui._is_running:
                terminal_ui.ui.stop_and_capture()
            finalize_fn(session_stats, start_time, items_completed, total_requests, run_logger)

    return exit_code
