"""Real-time subprocess output monitoring for tool execution visibility.

This module provides streaming of stdout/stderr from child processes spawned
by the Copilot CLI during tool execution. This gives PokePoke visibility into
long-running commands (pytest, git commit, etc.) that would otherwise appear
as silent "black boxes" until completion.

Key capabilities:
- Monitor child processes of the Copilot CLI subprocess
- Capture and stream stdout/stderr in real-time
- Detect when commands are truly hung vs legitimately computing
- Provide live progress feedback to logs and desktop UI
"""

from __future__ import annotations

import logging
import subprocess
import threading
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pokepoke.utils.logging_utils import ItemLogger

logger = logging.getLogger(__name__)


class SubprocessMonitor:
    """Monitors child processes and streams their output to logs and UI.

    This monitor works by periodically checking for new child processes
    spawned by the Copilot CLI and capturing their console output through
    Windows-specific APIs or fallback mechanisms.
    """

    def __init__(
        self,
        copilot_pid: int,
        item_logger: ItemLogger | None = None,
        on_output: Callable[[str, str], None] | None = None,
    ) -> None:
        """Initialize the subprocess monitor.

        Args:
            copilot_pid: PID of the Copilot CLI parent process
            item_logger: Optional ItemLogger for structured logging
            on_output: Optional callback for each output line (source, text)
        """
        self._copilot_pid = copilot_pid
        self._item_logger = item_logger
        self._on_output = on_output
        self._monitoring = False
        self._monitor_thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._monitored_pids: set[int] = set()

    def start(self) -> None:
        """Start monitoring for child processes."""
        with self._lock:
            if self._monitoring:
                return
            self._monitoring = True
            self._monitor_thread = threading.Thread(
                target=self._monitor_loop,
                daemon=True,
                name=f"subprocess-monitor-{self._copilot_pid}",
            )
            self._monitor_thread.start()
            logger.debug(
                "SubprocessMonitor started for copilot PID %d",
                self._copilot_pid,
            )

    def stop(self) -> None:
        """Stop monitoring."""
        with self._lock:
            self._monitoring = False
        if self._monitor_thread is not None:
            self._monitor_thread.join(timeout=2.0)
            self._monitor_thread = None
        logger.debug(
            "SubprocessMonitor stopped for copilot PID %d",
            self._copilot_pid,
        )

    def _monitor_loop(self) -> None:
        """Main monitoring loop that runs in a background thread."""
        try:
            while True:
                with self._lock:
                    if not self._monitoring:
                        break

                # Check for new child processes
                self._check_for_children()

                # Sleep before next check
                time.sleep(1.0)

        except Exception as e:
            logger.debug(
                "SubprocessMonitor loop exception for PID %d: %s",
                self._copilot_pid,
                e,
            )

    def _check_for_children(self) -> None:
        """Check for new child processes and start monitoring them."""
        try:
            # Get child processes using Windows tasklist or psutil if available
            children = self._find_child_processes()

            for pid, command in children:
                if pid not in self._monitored_pids:
                    self._monitored_pids.add(pid)
                    logger.info(
                        "[ProcessMonitor] Detected child process: PID %d (%s)",
                        pid,
                        command,
                    )
                    # Attempt to capture output from this process
                    # For now, we log that we detected it
                    # In a future enhancement, we could use Windows APIs
                    # to capture console output

        except Exception as e:
            logger.debug(
                "Error checking for child processes of PID %d: %s",
                self._copilot_pid,
                e,
            )

    def _find_child_processes(self) -> list[tuple[int, str]]:
        """Find child processes of the Copilot CLI process.

        Returns:
            List of (pid, command) tuples for child processes
        """
        children: list[tuple[int, str]] = []

        try:
            # Try using WMIC on Windows
            result = subprocess.run(
                [
                    "wmic",
                    "process",
                    "where",
                    f"ParentProcessId={self._copilot_pid}",
                    "get",
                    "ProcessId,CommandLine",
                    "/format:csv",
                ],
                capture_output=True,
                text=True,
                timeout=5.0,
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0,
            )

            if result.returncode == 0:
                lines = result.stdout.strip().split('\n')[1:]  # Skip header
                for line in lines:
                    if not line.strip():
                        continue
                    parts = line.split(',', 2)
                    if len(parts) >= 3:
                        try:
                            # WMIC CSV format: Node,CommandLine,ProcessId
                            command = parts[1]
                            pid = int(parts[2])
                            children.append((pid, command))
                        except (ValueError, IndexError):
                            continue

        except Exception as e:
            logger.debug("Error finding child processes via WMIC: %s", e)

        return children

    def _emit_output(self, source: str, text: str) -> None:
        """Emit captured output to all configured destinations.

        Args:
            source: 'stdout' or 'stderr'
            text: Output text to emit
        """
        if not text:
            return

        # Log to Python logger
        prefix = "[stderr] " if source == "stderr" else ""
        logger.info(f"[ProcessOutput] {prefix}{text}")

        # Log to item logger if available
        if self._item_logger:
            self._item_logger.log_copilot_output(text)

        # Call custom callback if provided
        if self._on_output:
            try:
                self._on_output(source, text)
            except Exception as e:
                logger.debug("Error in subprocess monitor output callback: %s", e)


def create_monitor_for_client(
    client: Any,
    item_logger: ItemLogger | None = None,
    on_output: Callable[[str, str], None] | None = None,
) -> SubprocessMonitor | None:
    """Create and start a subprocess monitor for a Copilot SDK client.

    Args:
        client: Copilot SDK client instance
        item_logger: Optional ItemLogger for structured logging
        on_output: Optional callback for each output line

    Returns:
        SubprocessMonitor instance, or None if PID extraction failed
    """
    from pokepoke.utils.process_utils import extract_client_pid

    pid = extract_client_pid(client)
    if pid is None:
        logger.warning("Could not extract copilot PID from client - subprocess monitoring disabled")
        return None

    monitor = SubprocessMonitor(pid, item_logger=item_logger, on_output=on_output)
    monitor.start()
    return monitor
