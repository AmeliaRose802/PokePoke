"""Parallel orchestrator loop for running multiple work items concurrently."""

import concurrent.futures
import threading
import time
from typing import Any

from pokepoke.beads import get_ready_work_items
from pokepoke.types import AgentStats, BeadsWorkItem, ModelCompletionRecord, SessionStats
from pokepoke.workflow import process_work_item
from pokepoke.work_item_selection import select_multiple_items
from pokepoke.logging_utils import RunLogger
from pokepoke import terminal_ui
from pokepoke.repo_check import check_and_commit_main_repo
from pokepoke.shutdown import is_shutting_down, set_executor

# Type alias to satisfy mypy strict generics
_Future = concurrent.futures.Future[
    tuple[bool, int, AgentStats | None, int, int, ModelCompletionRecord | None]
]


def _parallel_process_item(
    item: BeadsWorkItem,
    run_logger: RunLogger,
    semaphore: threading.Semaphore,
    active_ids: set[str],
    active_ids_lock: threading.Lock,
) -> tuple[bool, int, AgentStats | None, int, int, ModelCompletionRecord | None]:
    """Wrapper for process_work_item used by the thread pool.

    Releases the semaphore and removes the item from active_ids when done.
    """
    try:
        return process_work_item(item, interactive=False, run_logger=run_logger)
    finally:
        with active_ids_lock:
            active_ids.discard(item.id)
        semaphore.release()


def _collect_done_futures(
    futures: dict[_Future, BeadsWorkItem],
    failed_claim_ids: set[str],
    total_requests: int,
    session_stats: SessionStats,
    run_logger: RunLogger,
    record_fn: Any,
) -> tuple[int, bool]:
    """Collect completed futures and record results.

    Returns:
        (updated total_requests, any_success)
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

    any_success = False
    for fut in done_futs:
        item = futures.pop(fut)
        try:
            success, requests, item_stats, cleanup_runs, gate_runs, mc = fut.result()
        except Exception as exc:
            print(f"\n❌ Agent for {item.id} raised: {exc}")
            run_logger.log_orchestrator(f"Agent error for {item.id}: {exc}", level="ERROR")
            success, requests, item_stats = False, 0, None
            cleanup_runs, gate_runs, mc = 0, 0, None

        if not success and requests == 0:
            failed_claim_ids.add(item.id)
        elif success:
            failed_claim_ids.discard(item.id)
            any_success = True

        total_requests += requests
        record_fn(
            item, success, requests, item_stats,
            cleanup_runs, gate_runs, mc,
            session_stats, run_logger,
        )

    return total_requests, any_success


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
) -> int:
    """Run the parallel orchestrator loop with a ThreadPoolExecutor.

    Returns:
        Exit code (0 for success, 1 for failure).
    """
    total_requests = 0
    items_completed = 0
    semaphore = threading.Semaphore(effective_parallel)
    futures: dict[_Future, BeadsWorkItem] = {}
    active_ids: set[str] = set()
    active_ids_lock = threading.Lock()
    executor = concurrent.futures.ThreadPoolExecutor(
        max_workers=effective_parallel,
        thread_name_prefix="pokepoke-agent",
    )
    set_executor(executor)

    try:
        while not is_shutting_down():
            print("\n\ud83d\udd0d Checking main repository status...")
            run_logger.log_orchestrator("Checking main repository status")
            if not check_and_commit_main_repo(main_repo_path, run_logger):
                run_logger.log_orchestrator("Main repo check failed", level="ERROR")
                return 1

            print("\nFetching ready work from beads...")
            run_logger.log_orchestrator("Fetching ready work from beads")
            ready_items = get_ready_work_items()

            with active_ids_lock:
                current_active = set(active_ids)
            slots = effective_parallel - len(current_active)

            if slots > 0:
                selected_items = select_multiple_items(
                    ready_items, count=slots,
                    skip_ids=failed_claim_ids, claimed_ids=current_active,
                )
                for item in selected_items:
                    run_logger.log_orchestrator(f"Submitting item: {item.id} - {item.title}")
                    with active_ids_lock:
                        active_ids.add(item.id)
                    semaphore.acquire()
                    fut = executor.submit(
                        _parallel_process_item,
                        item, run_logger, semaphore, active_ids, active_ids_lock,
                    )
                    futures[fut] = item

            total_requests, any_success = _collect_done_futures(
                futures, failed_claim_ids, total_requests,
                session_stats, run_logger, record_fn,
            )
            items_completed = session_stats.items_completed

            terminal_ui.ui.update_stats(session_stats, time.time() - start_time)

            if not continuous and (any_success or not futures):
                # Drain remaining futures
                remaining = list(futures.keys())
                for fut in concurrent.futures.as_completed(remaining):
                    item = futures.pop(fut, BeadsWorkItem(
                        id="?", title="?", status="?", priority=0, issue_type="?",
                    ))
                    try:
                        s, r, st, cr, gr, mc = fut.result()
                    except Exception:
                        s, r, st, cr, gr, mc = False, 0, None, 0, 0, None
                    total_requests += r
                    record_fn(item, s, r, st, cr, gr, mc, session_stats, run_logger)
                    items_completed = session_stats.items_completed
                terminal_ui.ui.stop_and_capture()
                finalize_fn(session_stats, start_time, items_completed, total_requests, run_logger)
                return 0 if any_success else 1

            if not futures and not ready_items:
                terminal_ui.ui.stop_and_capture()
                print("\n👋 Exiting PokePoke - no work items available.")
                run_logger.log_orchestrator("No work items available - exiting")
                finalize_fn(session_stats, start_time, items_completed, total_requests, run_logger)
                return 0

            terminal_ui.ui.update_header(
                "PokePoke", f"{mode_name} Mode", f"{len(futures)} agents active",
            )
            for _ in range(10):
                if is_shutting_down():
                    break
                time.sleep(0.5)

    finally:
        executor.shutdown(wait=False, cancel_futures=True)
        set_executor(None)

    return 0
