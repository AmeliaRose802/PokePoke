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

import os
import threading
import time
from typing import Optional

# Global shutdown event - checked by all loops
_shutdown_event = threading.Event()

# Base grace period before force-kill (seconds)
_WATCHDOG_BASE_SECONDS = 5.0

# Additional time per active agent (seconds)
_WATCHDOG_PER_AGENT_SECONDS = 3.0

# Active agent count for scaling watchdog timeout
_active_agent_count = 0
_agent_count_lock = threading.Lock()

# Future: ThreadPoolExecutor for parallel agents (set by orchestrator)
_executor: Optional['concurrent.futures.ThreadPoolExecutor'] = None  # type: ignore[name-defined]


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

    # Shutdown merge queue to drain pending merges
    # Give merge queue 30 seconds to finish current merge
    try:
        from pokepoke.merge_queue import get_merge_queue
        merge_queue = get_merge_queue()
        if merge_queue.is_running:
            # Start shutdown asynchronously - watchdog will enforce timeout
            threading.Thread(
                target=merge_queue.shutdown,
                args=(30.0,),
                daemon=True,
                name="merge-queue-shutdown"
            ).start()
    except Exception:
        pass  # Merge queue shutdown is best-effort

    # Calculate watchdog timeout based on active agents
    with _agent_count_lock:
        agent_count = _active_agent_count
    
    watchdog_timeout = _WATCHDOG_BASE_SECONDS + (_WATCHDOG_PER_AGENT_SECONDS * agent_count)

    # Start a daemon watchdog thread that will hard-kill after grace period
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


def set_executor(executor: Optional['concurrent.futures.ThreadPoolExecutor']) -> None:  # type: ignore[name-defined]
    """Set the global ThreadPoolExecutor for shutdown coordination.
    
    Call this from orchestrator when parallel agent mode is enabled.
    Future: Used when ThreadPoolExecutor is implemented (PokePoke-3f87).
    """
    global _executor
    _executor = executor


def _watchdog_thread(timeout: float) -> None:
    """Force-terminate the process if graceful shutdown stalls.
    
    Args:
        timeout: Grace period in seconds before force-exit.
    """
    time.sleep(timeout)
    if _shutdown_event.is_set():
        # Still shutting down after grace period - force exit
        os._exit(130)  # 130 = 128 + SIGINT
