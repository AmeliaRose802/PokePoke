"""Loop state and cleanup helpers extracted from parallel.py for file length compliance."""

from __future__ import annotations

import concurrent.futures
import logging
import threading
from dataclasses import dataclass
from typing import Any

from pokepoke.agents.parallel_runtime import clear_runtime_parallel_limits
from pokepoke.agents.parallel_support import (
    drain_circuit_breaker as _drain_circuit_breaker,
)
from pokepoke.agents.parallel_support import (
    finalize_workers as _finalize_workers,
)
from pokepoke.agents.parallel_worker_pool import (
    ParallelWorkerPool,
    collect_done_futures,
)
from pokepoke.desktop import terminal_ui
from pokepoke.types import WorkItemResult
from pokepoke.types_beads import BeadsWorkItem, RecordFn
from pokepoke.types_stats import SessionStats
from pokepoke.utils.logging_utils import RunLogger
from pokepoke.utils.shutdown import set_executor

logger = logging.getLogger(__name__)

_Future = concurrent.futures.Future[WorkItemResult]

_IDLE_BASE_DELAY = 8.0

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


def _handle_circuit_breaker_drain(  # noqa: PLR0913
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


def _safe_cleanup(  # noqa: PLR0913
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
        logger.info("\n\U0001f3c1 Finalizing session...")
        run_logger.log_orchestrator("Finalizing session on exit")
        try:
            if terminal_ui.ui._is_running:
                terminal_ui.ui.stop_and_capture()
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
