"""Parallel orchestrator loop for running multiple work items concurrently."""

import concurrent.futures
import logging
import threading
import time
from typing import Any

logger = logging.getLogger(__name__)

from pokepoke.agent_context import get_agent_name, set_agent_name, clear_agent_name
from pokepoke.beads import get_ready_work_items
from pokepoke.types import AgentStats, BeadsWorkItem, ModelCompletionRecord, SessionStats
from pokepoke.workflow import process_work_item
from pokepoke.work_item_selection import select_multiple_items
from pokepoke.logging_utils import RunLogger
from pokepoke import terminal_ui
from pokepoke.repo_check import check_and_commit_main_repo
from pokepoke.shutdown import is_shutting_down, set_executor, should_stop_after_current, cancel_stop_after_current

# Type alias to satisfy mypy strict generics
_Future = concurrent.futures.Future[
    tuple[bool, int, AgentStats | None, int, int, ModelCompletionRecord | None]
]

# Threading event used to wake up the parallel loop immediately when a
# spawn agent request arrives from the desktop UI.
_spawn_wakeup = threading.Event()

_SNAKE_TYPES: tuple[str, ...] = (
    "cobra",
    "corn",
    "rainbow_boa",
    "rattlesnake",
    "sea_snake",
)


def request_spawn_agent() -> None:
    """Signal the parallel loop to attempt spawning an additional agent immediately.

    Called from the desktop UI when the user clicks the Spawn Agent button.
    The loop will wake up early from its sleep and try to fill available slots.
    """
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
    snake_type = _snake_for_work_item(item_id)
    return f"{base_agent_name}-{snake_type}-worker-{counter}"


def _parallel_process_item(
    item: BeadsWorkItem,
    run_logger: RunLogger,
    semaphore: threading.Semaphore,
    worker_agent_name: str | None = None,
) -> tuple[bool, int, AgentStats | None, int, int, ModelCompletionRecord | None]:
    """Wrapper for process_work_item used by the thread pool.

    Sets a per-thread agent name so that beads management / hierarchy
    code resolves the correct identity for this worker instead of the
    process-global ``os.environ['AGENT_NAME']``.

    Registers the agent in the desktop UI agent registry and routes all
    print output to the agent's own log buffer so parallel output is not
    interleaved (dtqz) and the Agents panel shows live data (ukr0).

    Releases the semaphore when done.
    """
    # Combine item id with worker name so two workers on the same item
    # get distinct UI slots (PokePoke-kluq).
    agent_id = f"{item.id}:{worker_agent_name}" if worker_agent_name else item.id
    display_name = worker_agent_name or "agent"

    if worker_agent_name:
        set_agent_name(worker_agent_name)

    # Register agent in the UI panel
    terminal_ui.ui.push_agent_status(
        agent_id,
        display_name,
        iteration=1,
        status="running",
        work_item_id=item.id,
        work_item_title=item.title,
    )
    terminal_ui.ui.log_orchestrator(f"\U0001f680 Agent {display_name} started item {item.id}: {item.title}")

    try:
        with terminal_ui.ui.agent_output_for(agent_id):
            result = process_work_item(
                item,
                interactive=False,
                run_logger=run_logger,
                agent_id=agent_id,
            )
        # Update agent status based on result
        success = result[0]
        terminal_ui.ui.push_agent_status(
            agent_id,
            display_name,
            iteration=1,
            status="success" if success else "failed",
            work_item_id=item.id,
            work_item_title=item.title,
        )
        status_emoji = "\u2705" if success else "\u274c"
        terminal_ui.ui.log_orchestrator(
            f"{status_emoji} Agent {display_name} {'completed' if success else 'failed'} item {item.id}"
        )
        return result
    except Exception as e:
        logger.warning(f"Failed to process work item {item.id} in parallel: {e}", exc_info=True)
        terminal_ui.ui.push_agent_status(
            agent_id,
            display_name,
            iteration=1,
            status="failed",
            work_item_id=item.id,
            work_item_title=item.title,
        )
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
    executor = concurrent.futures.ThreadPoolExecutor(
        max_workers=effective_parallel,
        thread_name_prefix="pokepoke-agent",
    )
    set_executor(executor)

    _worker_counter = 0
    finalized = False
    exit_code = 0

    try:
        while not is_shutting_down():
            print("\n\ud83d\udd0d Checking main repository status...")
            run_logger.log_orchestrator("Checking main repository status")
            if not check_and_commit_main_repo(main_repo_path, run_logger):
                run_logger.log_orchestrator("Main repo check failed", level="ERROR")
                exit_code = 1
                break

            print("\nFetching ready work from beads...")
            run_logger.log_orchestrator("Fetching ready work from beads")
            try:
                ready_items = get_ready_work_items()
            except Exception as e:
                # This should not happen now that get_ready_work_items handles errors,
                # but keep as additional safety measure
                run_logger.log_orchestrator(f"Failed to fetch ready items: {e}", level="ERROR")
                print(f"⚠️  Warning: failed to fetch ready items: {e}")
                ready_items = []

            # Collect completed futures BEFORE calculating slots so the
            # refill logic sees the true number of active agents and can
            # launch enough replacements to fill back to max_agents.
            total_requests, any_success = _collect_done_futures(
                futures, failed_claim_ids, total_requests,
                session_stats, run_logger, record_fn,
            )
            items_completed = session_stats.items_completed

            terminal_ui.ui.update_stats(session_stats, time.time() - start_time)

            current_active = {i.id for i in futures.values()}
            slots = effective_parallel - len(futures)

            if (
                slots > 0
                and not should_stop_after_current()
                and not (not continuous and any_success)
            ):
                selected_items = select_multiple_items(
                    ready_items, count=slots,
                    skip_ids=failed_claim_ids, claimed_ids=current_active,
                )
                for item in selected_items:
                    _worker_counter += 1
                    base_name = get_agent_name(default="pokepoke")
                    worker_name = _build_worker_name(base_name, item.id, _worker_counter)
                    run_logger.log_orchestrator(
                        f"Submitting item: {item.id} - {item.title} (worker: {worker_name})"
                    )
                    semaphore.acquire()
                    try:
                        fut = executor.submit(
                            _parallel_process_item,
                            item, run_logger, semaphore, worker_name,
                        )
                    except Exception as e:
                        logger.warning(f"Failed to submit work item {item.id} to executor: {e}")
                        semaphore.release()
                        raise
                    futures[fut] = item

            # Check if user requested stop after current item
            if should_stop_after_current() and not futures:
                cancel_stop_after_current()
                terminal_ui.ui.stop_and_capture()
                print("\n⏸️  Stopping after current item (user requested).")
                run_logger.log_orchestrator("Stop after current item requested - exiting")
                finalize_fn(session_stats, start_time, items_completed, total_requests, run_logger)
                finalized = True
                exit_code = 0
                break

            if not continuous and (any_success or not futures):
                # Drain remaining futures
                remaining = list(futures.keys())
                for fut in concurrent.futures.as_completed(remaining):
                    item = futures.pop(fut, BeadsWorkItem(
                        id="?", title="?", status="?", priority=0, issue_type="?",
                    ))
                    try:
                        s, r, st, cr, gr, mc = fut.result()
                    except Exception as e:
                        logger.warning(f"Future raised exception: {e}")
                        s, r, st, cr, gr, mc = False, 0, None, 0, 0, None
                    total_requests += r
                    record_fn(item, s, r, st, cr, gr, mc, session_stats, run_logger)
                    items_completed = session_stats.items_completed
                    terminal_ui.ui.update_stats(session_stats, time.time() - start_time)
                # Ensure UI sees the final snapshot even if no futures remained to drain.
                terminal_ui.ui.update_stats(session_stats, time.time() - start_time)
                terminal_ui.ui.stop_and_capture()
                finalize_fn(session_stats, start_time, items_completed, total_requests, run_logger)
                finalized = True
                exit_code = 0 if any_success else 1
                break

            # Only exit if no workers are active AND we have no ready items
            # This ensures we wait for in-flight workers to complete
            if not futures and not ready_items:
                # Double-check that we really have no work before exiting
                # Sometimes beads queries can temporarily fail
                print("\n🔄 No active workers or ready items - double-checking beads...")
                run_logger.log_orchestrator("Double-checking beads before exit")
                try:
                    final_check = get_ready_work_items()
                    if final_check:
                        print(f"📋 Found {len(final_check)} items on final check - continuing...")
                        run_logger.log_orchestrator(f"Found {len(final_check)} items on final check")
                        continue  # Go back to main loop to process these items
                except Exception as e:
                    run_logger.log_orchestrator(f"Final beads check failed: {e}", level="WARNING")

                terminal_ui.ui.stop_and_capture()
                print("\n👋 Exiting PokePoke - no work items available.")
                run_logger.log_orchestrator("No work items available - exiting")
                finalize_fn(session_stats, start_time, items_completed, total_requests, run_logger)
                finalized = True
                exit_code = 0
                break

            terminal_ui.ui.update_header(
                "PokePoke", f"{mode_name} Mode", f"{len(futures)} agents active",
            )
            for _ in range(10):
                if is_shutting_down() or _spawn_wakeup.is_set():
                    break
                time.sleep(0.5)
            _spawn_wakeup.clear()

    finally:
        # Wait for all workers to complete before shutting down
        if futures:
            print(f"\n⏳ Waiting for {len(futures)} active workers to complete...")
            run_logger.log_orchestrator(f"Waiting for {len(futures)} active workers to complete")

            # Wait for all remaining futures to complete (with reasonable timeout)
            remaining = list(futures.keys())
            try:
                for fut in concurrent.futures.as_completed(remaining, timeout=300):  # 5 minute timeout
                    item = futures.pop(fut, BeadsWorkItem(
                        id="?", title="?", status="?", priority=0, issue_type="?",
                    ))
                    try:
                        s, r, st, cr, gr, mc = fut.result()
                        print(f"✅ Worker completed item {item.id}")
                        run_logger.log_orchestrator(f"Worker completed item {item.id}")
                    except Exception as e:
                        print(f"❌ Worker failed for item {item.id}: {e}")
                        run_logger.log_orchestrator(f"Worker failed for item {item.id}: {e}", level="ERROR")
                        s, r, st, cr, gr, mc = False, 0, None, 0, 0, None

                    total_requests += r
                    record_fn(item, s, r, st, cr, gr, mc, session_stats, run_logger)
                    items_completed = session_stats.items_completed
                    terminal_ui.ui.update_stats(session_stats, time.time() - start_time)
            except concurrent.futures.TimeoutError:
                print(f"⚠️  Timeout waiting for {len(futures)} workers after 5 minutes")
                run_logger.log_orchestrator("Timeout waiting for workers", level="WARNING")

            print("✅ All workers completed")
            run_logger.log_orchestrator("All workers completed")
            terminal_ui.ui.update_stats(session_stats, time.time() - start_time)

        # Now shutdown the executor (no need to wait since we already waited above)
        executor.shutdown(wait=False, cancel_futures=False)
        set_executor(None)

        # Call finalize if it hasn't been called yet (e.g., on shutdown or exception)
        if not finalized:
            print("\n🏁 Finalizing session...")
            run_logger.log_orchestrator("Finalizing session on exit")
            if terminal_ui.ui._is_running:
                terminal_ui.ui.stop_and_capture()
            finalize_fn(session_stats, start_time, items_completed, total_requests, run_logger)

    return exit_code
