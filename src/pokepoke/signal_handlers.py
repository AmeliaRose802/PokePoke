"""Signal handling utilities for PokePoke orchestrator.

Provides graceful shutdown logging when the process receives termination signals
like SIGTERM (system kill) or SIGINT (Ctrl+C).
"""

import signal
import sys
import threading
from types import FrameType
from typing import Callable, Any
from datetime import datetime

from pokepoke.logging_utils import RunLogger


# Global reference to the current RunLogger
_current_logger: RunLogger | None = None
_original_handlers: dict[int, Callable[..., Any] | None] = {}


def register_shutdown_handlers(run_logger: RunLogger) -> None:
    """Register signal handlers for graceful shutdown logging.

    This should be called early in the orchestrator initialization to ensure
    that termination signals are logged properly.

    Note: signal.signal() only works from the main thread. When the
    orchestrator runs on a background thread (e.g. DesktopUI mode where
    pywebview owns the main thread), we skip signal registration and rely
    on atexit handlers instead.

    Args:
        run_logger: RunLogger instance to use for logging shutdown events
    """
    global _current_logger
    _current_logger = run_logger

    if threading.current_thread() is not threading.main_thread():
        # Cannot register signal handlers from a non-main thread.
        # The logger is still stored so atexit/manual shutdown paths
        # can use it.
        return

    # Store original handlers so we can chain them if needed
    # signal.signal() can return various types, so we use Any for flexibility
    original_sigterm = signal.signal(signal.SIGTERM, _signal_handler)
    original_sigint = signal.signal(signal.SIGINT, _signal_handler)

    # Store with proper type annotation
    _original_handlers[signal.SIGTERM] = original_sigterm if callable(original_sigterm) else None
    _original_handlers[signal.SIGINT] = original_sigint if callable(original_sigint) else None


def _signal_handler(signum: int, frame: FrameType | None) -> None:
    """Handle termination signals by logging and then exiting.

    Args:
        signum: Signal number received
        frame: Current stack frame (unused)
    """
    signal_names: dict[int, str] = {
        signal.SIGTERM: "SIGTERM",
        signal.SIGINT: "SIGINT"
    }

    signal_name = signal_names.get(signum, f"SIG{signum}")
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    try:
        # Try to log through the RunLogger if available
        if _current_logger is not None:
            _current_logger.log_orchestrator(
                f"Process terminated by signal {signal_name} ({signum})",
                level="WARNING"
            )
            _current_logger.log_orchestrator("PokePoke orchestrator shutdown due to signal")
        else:
            # Fallback: log directly to stderr if no logger available
            print(f"[{timestamp}] [WARNING] Process terminated by signal {signal_name} ({signum})",
                  file=sys.stderr)
            print(f"[{timestamp}] [WARNING] PokePoke orchestrator shutdown due to signal",
                  file=sys.stderr)
    except Exception as e:
        # Last resort: basic message to stderr
        print(f"[{timestamp}] [ERROR] Signal handler failed: {e}", file=sys.stderr)
        print(f"[{timestamp}] [WARNING] Process terminated by signal {signal_name}", file=sys.stderr)

    # Exit with appropriate code
    # SIGTERM/SIGINT should result in exit code 128 + signal number
    # This is the standard convention for processes killed by signals
    exit_code = 128 + signum
    sys.exit(exit_code)


def unregister_shutdown_handlers() -> None:
    """Restore original signal handlers.

    This can be called during cleanup if needed, though it's typically not necessary
    since the process will be exiting anyway.
    """
    global _current_logger

    if threading.current_thread() is threading.main_thread():
        for signum, original_handler in _original_handlers.items():
            if original_handler is not None:
                signal.signal(signum, original_handler)
            else:
                signal.signal(signum, signal.SIG_DFL)

    _original_handlers.clear()
    _current_logger = None
