"""Global shutdown coordination for PokePoke.

Provides a process-wide shutdown signal that all loops, async tasks,
and subprocesses can check to enable clean Ctrl+C / quit handling.

The problem: Textual intercepts Ctrl+C as a key event on Windows
(disables ENABLE_PROCESSED_INPUT), so KeyboardInterrupt never reaches
the orchestrator worker thread. This module bridges that gap with a
threading.Event that Textual's quit action sets, and a watchdog thread
that force-kills the process if graceful shutdown stalls.
"""

import os
import threading
import time

# Global shutdown event - checked by all loops
_shutdown_event = threading.Event()

# Grace period before force-kill (seconds)
_WATCHDOG_GRACE_SECONDS = 5.0


def request_shutdown() -> None:
    """Signal all components to shut down.

    Call this from Textual's quit action or any Ctrl+C handler.
    Starts a watchdog that will force-kill the process if graceful
    shutdown doesn't complete within the grace period.
    """
    if _shutdown_event.is_set():
        return  # Already shutting down

    _shutdown_event.set()

    # Start a daemon watchdog thread that will hard-kill after grace period
    watchdog = threading.Thread(
        target=_watchdog_thread,
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


def _watchdog_thread() -> None:
    """Force-terminate the process if graceful shutdown stalls."""
    time.sleep(_WATCHDOG_GRACE_SECONDS)
    if _shutdown_event.is_set():
        # Still shutting down after grace period - force exit
        os._exit(130)  # 130 = 128 + SIGINT
