"""Parallel orchestrator loop for running multiple work items concurrently."""

from __future__ import annotations

import concurrent.futures
import logging
import threading
import time
from dataclasses import dataclass
from typing import Any

from pokepoke.agents.agent_context import clear_agent_name, get_agent_name, set_agent_name
from pokepoke.agents.parallel_runtime import (
    clear_runtime_parallel_limits,
    compute_effective_max_agents,
    set_runtime_parallel_limits,
)
from pokepoke.agents.parallel_worker_pool import (
    ParallelWorkerPool,
    collect_done_futures,
    update_memory_circuit_breaker,
)
from pokepoke.beads.beads import (
    assign_and_sync_item,
    get_ready_work_items,
    is_item_claimable,
    unassign_with_retry,
)
from pokepoke.desktop import terminal_ui
from pokepoke.git.repo_check import check_and_commit_main_repo
from pokepoke.orchestration.work_item_selection import select_multiple_items
from pokepoke.orchestration.workflow import process_work_item
from pokepoke.types import BeadsWorkItem, RecordFn, SessionStats, WorkItemResult
from pokepoke.utils.logging_utils import RunLogger
from pokepoke.utils.shutdown import (
    cancel_stop_after_current,
    is_shutting_down,
    set_executor,
    should_stop_after_current,
)

# Re-exported for test monkey-patching via parallel_support late imports
__all__ = [
    "assign_and_sync_item",
    "cancel_stop_after_current",
    "check_and_commit_main_repo",
    "get_ready_work_items",
    "is_item_claimable",
    "select_multiple_items",
    "should_stop_after_current",
    "unassign_with_retry",
]

from pokepoke.agents.parallel_support import (
    check_loop_exit as _check_loop_exit,
)
from pokepoke.agents.parallel_support import (
    compute_slots as _compute_slots,
)
from pokepoke.agents.parallel_support import (
    dispatch_items as _dispatch_items,
)
from pokepoke.agents.parallel_support import (
    drain_circuit_breaker as _drain_circuit_breaker,
)
from pokepoke.agents.parallel_support import (
    finalize_workers as _finalize_workers,
)
from pokepoke.agents.parallel_support import (
    run_preflight_and_repo_checks as _run_preflight_and_repo_checks,
)
from pokepoke.agents.parallel_support import (
    update_circuit_breaker as _update_circuit_breaker,
)

logger = logging.getLogger(__name__)

# Default pool size; raised when effective_parallel exceeds this.
_DEFAULT_PARALLEL_CEILING = 8

_IDLE_BASE_DELAY = 8.0   # Idle backoff start for continuous mode (exponential to max)
_IDLE_MAX_DELAY = 120.0
_MAX_CONSECUTIVE_FAILURES = 10  # Circuit breaker: stop dispatching after N consecutive failures
_MAX_CONSECUTIVE_PREFLIGHT_FAILURES = 5  # Stop after N preflight failures
_MEMORY_FLOOR_MB = 3072  # Memory circuit breaker: 3GB threshold
_MEMORY_FLOOR_POLL_THRESHOLD = 3  # Trip after 3 consecutive polls below floor

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
    repo_path: str | None = None,
) -> WorkItemResult:
    """Thread-pool wrapper for process_work_item."""
    agent_id = f"{item.id}:{worker_agent_name}" if worker_agent_name else item.id
    display_name = worker_agent_name or get_agent_name(default="pokepoke")
    if worker_agent_name:
        set_agent_name(worker_agent_name)

    def _push(status: str) -> None:
        terminal_ui.ui.push_agent_status(agent_id, display_name, iteration=1, status=status,
            work_item_id=item.id, work_item_title=item.title, agent_type="work")
    _push("running")
    terminal_ui.ui.log_orchestrator(f"\U0001f680 Agent {display_name} started item {item.id}: {item.title}")
    # Increment total attempts counter for this item
    from pokepoke.beads.beads import increment_total_attempts
    increment_total_attempts(item.id)
    try:
        with terminal_ui.ui.agent_output_for(agent_id):
            result = process_work_item(item, interactive=False, run_logger=run_logger, agent_id=agent_id, repo_path=repo_path)
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

# Backward-compatible alias – logic now lives in parallel_worker_pool.py.
# Tests and parallel_support.py reference this name via
# ``@patch("pokepoke.agents.parallel._collect_done_futures")``.
_collect_done_futures = collect_done_futures

@dataclass
class _LoopState:
    """Mutable state carried through the parallel loop iterations."""
    total_requests: int = 0
    items_completed: int = 0
    worker_counter: int = 0
    finalized: bool = False
    exit_code: int = 0
    has_success: bool = False
    idle_sleep: float = _IDLE_BASE_DELAY
    consecutive_failures: int = 0
    consecutive_preflight_failures: int = 0
    circuit_breaker_tripped: bool = False
    consecutive_low_memory_polls: int = 0
    memory_circuit_breaker_tripped: bool = False

def _handle_circuit_breaker_drain(
    state: _LoopState,
    futures: dict[_Future, BeadsWorkItem],
    failed_claim_ids: set[str],
    session_stats: SessionStats,
    run_logger: RunLogger,
    record_fn: RecordFn,
    mode_name: str,
    lock: threading.Lock | None = None,
) -> bool:
    """Drain futures while circuit breaker is tripped. Returns True to break.

    Parameters
    ----------
    lock:
        Optional lock protecting *futures* and *failed_claim_ids*. When
        provided, the lock is passed to drain functions for thread-safe operation.
    """
    if lock is not None:
        with lock:
            has_futures = bool(futures)
    else:
        has_futures = bool(futures)
    if not has_futures:
        run_logger.log_orchestrator("Circuit breaker: all remaining agents finished \u2014 exiting")
        state.exit_code = 1
        return True
    state.total_requests = _drain_circuit_breaker(
        futures, failed_claim_ids, state.total_requests,
        session_stats, run_logger, record_fn, _collect_done_futures, mode_name, lock,
    )
    return False

def _run_loop_iteration(
    state: _LoopState,
    futures: dict[_Future, BeadsWorkItem],
    failed_claim_ids: set[str],
    session_stats: SessionStats,
    run_logger: RunLogger,
    record_fn: RecordFn,
    finalize_fn: Any,
    semaphore: threading.Semaphore,
    executor: concurrent.futures.ThreadPoolExecutor,
    main_repo_path: Any,
    start_time: float,
    continuous: bool,
    mode_name: str,
    lock: threading.Lock | None = None,
) -> str | None:
    """Execute one iteration of the parallel loop.

    Parameters
    ----------
    lock:
        Optional lock protecting *futures* and *failed_claim_ids*. When
        provided, the lock is passed to helper functions for thread-safe operation.

    Returns:
        ``None`` to continue normally, ``"break"`` to exit the loop,
        ``"continue"`` to skip the sleep at the end.
    """
    ok, state.consecutive_preflight_failures, ready_items = _run_preflight_and_repo_checks(
        main_repo_path, run_logger, state.consecutive_preflight_failures,
        _MAX_CONSECUTIVE_PREFLIGHT_FAILURES,
        check_and_commit_main_repo, get_ready_work_items,
    )
    if not ok:
        state.exit_code = 1
        return "break"

    state.total_requests, any_success, batch_successes, batch_failures = _collect_done_futures(
        futures, failed_claim_ids, state.total_requests,
        session_stats, run_logger, record_fn, lock,
    )
    state.items_completed = session_stats.items_completed
    state.has_success = state.has_success or any_success

    state.consecutive_failures, state.circuit_breaker_tripped = _update_circuit_breaker(
        batch_successes, batch_failures, state.consecutive_failures,
        _MAX_CONSECUTIVE_FAILURES, futures, run_logger, lock,
    )
    if lock is not None:
        with lock:
            has_futures = bool(futures)
    else:
        has_futures = bool(futures)
    if state.circuit_breaker_tripped and not has_futures:
        state.exit_code = 1
        return "break"

    terminal_ui.ui.update_stats(session_stats, time.time() - start_time)
    current_active, slots, avail_mb = _compute_slots(futures, run_logger, lock)

    # Check memory circuit breaker
    state.consecutive_low_memory_polls, state.memory_circuit_breaker_tripped = (
        update_memory_circuit_breaker(
            avail_mb,
            _MEMORY_FLOOR_MB,
            _MEMORY_FLOOR_POLL_THRESHOLD,
            state.consecutive_low_memory_polls,
            futures,
            run_logger,
            lock,
        )
    )
    if state.memory_circuit_breaker_tripped and not has_futures:
        state.exit_code = 1
        return "break"

    if lock is not None:
        with lock:
            has_futures = bool(futures)
    else:
        has_futures = bool(futures)
    if has_futures or ready_items:
        state.idle_sleep = _IDLE_BASE_DELAY

    state.worker_counter = _dispatch_items(
        ready_items, slots, continuous, state.has_success,
        state.consecutive_failures, _MAX_CONSECUTIVE_FAILURES,
        failed_claim_ids, current_active,
        futures, semaphore, executor, run_logger, state.worker_counter,
        _build_worker_name, _parallel_process_item, lock,
    )

    action = _check_loop_exit(
        futures, ready_items, continuous, state.has_success,
        state.total_requests, state.items_completed, session_stats,
        start_time, state.idle_sleep, mode_name,
        run_logger, finalize_fn, get_ready_work_items, lock,
    )
    if action is not None:
        if action.startswith("break"):
            state.finalized = True
            state.exit_code = 0 if action != "break-done" or state.has_success else 1
            return "break"
        state.idle_sleep = _IDLE_BASE_DELAY if action == "recheck" else min(_IDLE_MAX_DELAY, state.idle_sleep * 2)
        return "continue"

    return None


def _safe_cleanup(
    state: _LoopState,
    pool: ParallelWorkerPool,
    session_stats: SessionStats,
    start_time: float,
    run_logger: RunLogger,
    record_fn: RecordFn,
    finalize_fn: Any,
    active_lock: threading.Lock | None,
) -> None:
    """Run cleanup operations with individual exception protection."""
    timeout_occurred = False
    try:
        state.total_requests, timeout_occurred = _finalize_workers(
            pool.futures, session_stats, start_time, state.total_requests,
            run_logger, record_fn, active_lock,
        )
    except Exception as e:
        logger.error(f"Failed to finalize workers: {e}", exc_info=True)
        run_logger.log_orchestrator(f"Worker finalization error: {e}", level="ERROR")
    try:
        pool.shutdown(wait=True, cancel_futures=timeout_occurred)
    except Exception as e:
        logger.error(f"Failed to shutdown pool: {e}", exc_info=True)
    set_executor(None)
    clear_runtime_parallel_limits()
    if not state.finalized:
        logger.info("\n🏁 Finalizing session...")
        run_logger.log_orchestrator("Finalizing session on exit")
        try:
            if terminal_ui.ui._is_running:
                terminal_ui.ui.stop_and_capture()
            # Check if we should run post-mortem based on state
            from pokepoke.orchestration.orchestrator import _should_run_post_mortem
            run_pm = False
            if state.circuit_breaker_tripped:
                run_pm = _should_run_post_mortem(session_stats, "circuit breaker tripped")
            elif state.memory_circuit_breaker_tripped:
                run_pm = _should_run_post_mortem(session_stats, "memory circuit breaker")
            elif state.exit_code != 0:
                run_pm = _should_run_post_mortem(session_stats, "abnormal exit")

            finalize_fn(session_stats, start_time, state.items_completed, state.total_requests, run_logger, run_pm)
        except Exception as e:
            logger.error(f"Failed to finalize session: {e}", exc_info=True)
            run_logger.log_orchestrator(f"Session finalization error: {e}", level="ERROR")


def run_parallel_loop(
    effective_parallel: int,
    mode_name: str,
    main_repo_path: Any,
    failed_claim_ids: set[str],
    session_stats: SessionStats,
    start_time: float,
    run_logger: RunLogger,
    continuous: bool,
    record_fn: RecordFn,
    finalize_fn: Any,
    *, cli_override: bool = False,
    external_lock: threading.Lock | None = None,
) -> int:
    """Run the parallel orchestrator loop with a ThreadPoolExecutor.

    Args:
        external_lock: Optional external lock for failed_claim_ids synchronization.
                      If provided, this lock will be used instead of the pool's internal lock
                      to protect failed_claim_ids access, allowing coordination with the main
                      orchestrator thread in hybrid sequential/parallel modes.
    """
    pool_size = min(effective_parallel, _DEFAULT_PARALLEL_CEILING)
    if effective_parallel > _DEFAULT_PARALLEL_CEILING:
        logger.warning("max_parallel_agents (%d) exceeds ceiling (%d); clamping pool", effective_parallel, _DEFAULT_PARALLEL_CEILING)
    pool = ParallelWorkerPool(pool_size)
    set_executor(pool.executor)
    set_runtime_parallel_limits(effective_parallel, cli_override, baseline=_get_dynamic_max_agents() if cli_override else None)

    # Use external lock if provided (for coordination with main orchestrator thread)
    # Otherwise use pool's internal lock
    active_lock = external_lock if external_lock is not None else pool.lock

    state = _LoopState()

    try:
        while not is_shutting_down():
            if state.circuit_breaker_tripped or state.memory_circuit_breaker_tripped:
                if _handle_circuit_breaker_drain(
                    state, pool.futures, failed_claim_ids, session_stats,
                    run_logger, record_fn, mode_name, active_lock,
                ):
                    break
                continue
            result = _run_loop_iteration(
                state, pool.futures, failed_claim_ids, session_stats, run_logger,
                record_fn, finalize_fn, pool.semaphore, pool.executor,
                main_repo_path, start_time, continuous, mode_name, active_lock,
            )
            if result == "break":
                break
            if result == "continue":
                continue
            terminal_ui.ui.update_header("PokePoke", f"{mode_name} Mode", f"{pool.active_count} agents active")
            for _ in range(10):
                if is_shutting_down() or _spawn_wakeup.is_set():
                    break
                time.sleep(0.5)
            _spawn_wakeup.clear()

    except (KeyboardInterrupt, SystemExit, StopIteration):
        raise
    except Exception as loop_exc:
        logger.error(f"Parallel loop crashed: {loop_exc}", exc_info=True)
        run_logger.log_orchestrator(f"Parallel loop exception: {loop_exc}", level="ERROR")
        state.exit_code = 1
    finally:
        _safe_cleanup(state, pool, session_stats, start_time, run_logger, record_fn, finalize_fn, active_lock)

    return state.exit_code
