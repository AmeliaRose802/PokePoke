"""Global shutdown coordination for PokePoke.

Provides a process-wide shutdown signal that all loops, async tasks,
and subprocesses can check to enable clean Ctrl+C / quit handling.

Uses a threading.Event for cross-thread shutdown signaling, and a
watchdog thread that force-kills the process if graceful shutdown stalls.

Multi-agent shutdown coordination:
- Tracks active agents to scale watchdog timeout
- Coordinates with merge queue to finish merges
- Future: Will coordinate with ThreadPoolExecutor
"""

from __future__ import annotations

import _thread
import concurrent.futures
import logging
import threading
import time

from pokepoke.coordination import merge_lock_active

logger = logging.getLogger(__name__)

# Global shutdown event - checked by all loops
_shutdown_event = threading.Event()

# "Stop after current item" event — causes the continuous loop to exit
# cleanly after the currently running work item finishes, without
# killing in-progress work.
_stop_after_current_event = threading.Event()

# Base grace period before force-kill (seconds)
_WATCHDOG_BASE_SECONDS = 5.0

# Additional time per active agent (seconds)
_WATCHDOG_PER_AGENT_SECONDS = 3.0

# Active agent count for scaling watchdog timeout
_active_agent_count = 0
_agent_count_lock = threading.Lock()

# Future: ThreadPoolExecutor for parallel agents (set by orchestrator)
_executor: concurrent.futures.ThreadPoolExecutor | None = None


def request_shutdown() -> None:
    """Signal all components to shut down.

    Call this from the UI quit action or any Ctrl+C handler.
    Starts a watchdog that will force-kill the process if graceful
    shutdown doesn't complete within the grace period.

    Shutdown coordination:
    1. Signals all agent threads via Event
    2. Shuts down ThreadPoolExecutor (if present)
    3. Shuts down merge queue to finish pending merges
    4. Starts watchdog with timeout scaled to active agent count
    """
    if _shutdown_event.is_set():
        return  # Already shutting down

    _shutdown_event.set()

    # Shutdown ThreadPoolExecutor (future: when parallel agents are implemented)
    if _executor is not None:
        _executor.shutdown(wait=False, cancel_futures=True)

    # Shutdown merge queue to drain pending merges.
    # This is intentionally synchronous so we don't lose pending merges due to
    # daemon thread teardown during interpreter shutdown.
    try:
        from pokepoke.merge_queue import get_merge_queue

        merge_queue = get_merge_queue()
        if merge_queue.is_running:
            merge_queue.shutdown(timeout=180.0)
    except Exception as e:
        logger.debug(f"Failed to shutdown merge queue: {e}")

    # Calculate watchdog timeout based on active agents
    with _agent_count_lock:
        agent_count = _active_agent_count

    watchdog_timeout = _WATCHDOG_BASE_SECONDS + (_WATCHDOG_PER_AGENT_SECONDS * agent_count)

    # Start a daemon watchdog thread that will *cooperatively* nudge the main
    # thread to exit if shutdown appears stalled.
    watchdog = threading.Thread(
        target=_watchdog_thread,
        args=(watchdog_timeout,),
        daemon=True,
        name="shutdown-watchdog",
    )
    watchdog.start()


def is_shutting_down() -> bool:
    """Check if shutdown has been requested.

    Use this in while-loops:
        while not is_shutting_down():
            ...
    """
    return _shutdown_event.is_set()


def wait_for_shutdown(timeout: float | None = None) -> bool:
    """Block until shutdown is requested or timeout expires.

    Returns True if shutdown was requested, False on timeout.
    """
    return _shutdown_event.wait(timeout=timeout)


def reset() -> None:
    """Reset the shutdown state. Only for tests."""
    _shutdown_event.clear()
    _stop_after_current_event.clear()


def register_agent() -> None:
    """Register an active agent to scale shutdown timeout.

    Call this when an agent thread starts processing work.
    Increases the watchdog timeout to allow time for graceful shutdown.
    """
    global _active_agent_count
    with _agent_count_lock:
        _active_agent_count += 1


def unregister_agent() -> None:
    """Unregister an active agent.

    Call this when an agent thread completes or exits.
    """
    global _active_agent_count
    with _agent_count_lock:
        _active_agent_count = max(0, _active_agent_count - 1)


def get_active_agent_count() -> int:
    """Get the current number of active agents."""
    with _agent_count_lock:
        return _active_agent_count


def has_active_agents() -> bool:
    """Check if there are currently active agent threads or pending futures.

    Returns True if:
    - Any agent threads are running (get_active_agent_count > 0), OR
    - The ThreadPoolExecutor has pending/running futures

    This is used to prevent project switching while agents are active,
    which would break relative-path-based coordination locks.
    """
    # Check registered agent count
    if get_active_agent_count() > 0:
        return True

    # Check if executor has pending futures
    if _executor is not None:
        # An executor exists; check if it has any pending work
        # We can't directly query pending futures, but the presence of
        # an executor during orchestration means agents might be starting/running
        return True

    return False


def set_executor(executor: concurrent.futures.ThreadPoolExecutor | None) -> None:
    """Set the global ThreadPoolExecutor for shutdown coordination.

    Call this from orchestrator when parallel agent mode is enabled.
    Future: Used when ThreadPoolExecutor is implemented (PokePoke-3f87).
    """
    global _executor
    _executor = executor


def request_stop_after_current() -> None:
    """Signal the orchestrator to stop after the current work item completes.

    Unlike :func:`request_shutdown`, this does NOT interrupt running agents.
    The current item is allowed to finish fully (including merge) before
    the continuous loop exits.
    """
    _stop_after_current_event.set()


def cancel_stop_after_current() -> None:
    """Cancel a pending stop-after-current request.

    The orchestrator will continue picking up new items as normal.
    """
    _stop_after_current_event.clear()


def should_stop_after_current() -> bool:
    """Check whether a stop-after-current has been requested."""
    return _stop_after_current_event.is_set()


def _watchdog_thread(timeout: float) -> None:
    """Cooperatively accelerate shutdown if it appears stalled.

    After a grace period, the watchdog waits for any in-flight merge (as
    signaled by the cross-process merge lock) to complete. Once no merge is
    active, it triggers a main-thread KeyboardInterrupt via
    ``_thread.interrupt_main()`` to help unwind normal ``try/finally``
    cleanup paths.

    This intentionally avoids ``os._exit`` because hard-exiting from a
    background thread bypasses finally blocks/context managers and can leave
    the repository in a half-merged state.

    Args:
        timeout: Grace period in seconds before considering shutdown stalled.
    """
    time.sleep(timeout)
    if not _shutdown_event.is_set():
        return

    _MERGE_LOCK_WAIT_MAX_SECONDS = 120.0
    try:
        lock_wait_start = time.monotonic()
        while merge_lock_active():
            if time.monotonic() - lock_wait_start >= _MERGE_LOCK_WAIT_MAX_SECONDS:
                logger.warning(
                    "Merge lock still held after %ds; proceeding with cooperative interrupt.",
                    int(_MERGE_LOCK_WAIT_MAX_SECONDS),
                )
                break
            time.sleep(1.0)
    except Exception as e:
        logger.debug("Watchdog merge lock check failed: %s", e)

    if _shutdown_event.is_set():
        try:
            _thread.interrupt_main()
        except Exception as e:
            logger.debug("Watchdog could not interrupt main thread: %s", e)
