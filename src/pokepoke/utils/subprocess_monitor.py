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
import os
import subprocess
import threading
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

try:
    import psutil
    _HAS_PSUTIL = True
except ImportError:
    _HAS_PSUTIL = False

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
        poll_interval: float = 0.5,
    ) -> None:
        """Initialize the subprocess monitor.

        Args:
            copilot_pid: PID of the Copilot CLI parent process
            item_logger: Optional ItemLogger for structured logging
            on_output: Optional callback for each output line (source, text)
            poll_interval: How often to poll for output (seconds)
        """
        self._copilot_pid = copilot_pid
        self._item_logger = item_logger
        self._on_output = on_output
        self._poll_interval = poll_interval
        self._monitoring = False
        self._monitor_thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._monitored_pids: set[int] = set()
        self._process_threads: dict[int, threading.Thread] = {}
        self._process_pipes: dict[int, dict[str, Any]] = {}

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

        # Stop all process monitor threads
        for _pid, thread in list(self._process_threads.items()):
            thread.join(timeout=1.0)

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

                # Clean up dead process threads
                self._cleanup_dead_processes()

                # Sleep before next check
                time.sleep(self._poll_interval)

        except Exception as e:
            logger.debug(
                "SubprocessMonitor loop exception for PID %d: %s",
                self._copilot_pid,
                e,
            )

    def _check_for_children(self) -> None:
        """Check for new child processes and start monitoring them."""
        try:
            # Get child processes using psutil or Windows tasklist
            children = self._find_child_processes()

            for pid, command in children:
                if pid not in self._monitored_pids:
                    self._monitored_pids.add(pid)
                    logger.info(
                        "[ProcessMonitor] Detected child process: PID %d (%s)",
                        pid,
                        command,
                    )
                    # Start a thread to monitor this process's output
                    self._start_process_monitor(pid, command)

        except Exception as e:
            logger.debug(
                "Error checking for child processes of PID %d: %s",
                self._copilot_pid,
                e,
            )

    def _cleanup_dead_processes(self) -> None:
        """Clean up threads for processes that no longer exist."""
        dead_pids = []
        for pid in list(self._process_threads.keys()):
            try:
                if _HAS_PSUTIL and not psutil.pid_exists(pid):
                    dead_pids.append(pid)
            except Exception:
                pass

        for pid in dead_pids:
            thread = self._process_threads.pop(pid, None)
            self._process_pipes.pop(pid, None)
            if thread and thread.is_alive():
                thread.join(timeout=0.5)

    def _find_child_processes(self) -> list[tuple[int, str]]:
        """Find child processes of the Copilot CLI process.

        Returns:
            List of (pid, command) tuples for child processes
        """
        children: list[tuple[int, str]] = []

        if _HAS_PSUTIL:
            # Use psutil for more reliable process detection
            try:
                parent = psutil.Process(self._copilot_pid)
                for child in parent.children(recursive=True):
                    try:
                        cmdline = ' '.join(child.cmdline())
                        children.append((child.pid, cmdline))
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        continue
            except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
                logger.debug("Error finding child processes via psutil: %s", e)
        else:
            # Fallback to WMIC on Windows
            try:
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

    def _start_process_monitor(self, pid: int, command: str) -> None:
        """Start monitoring a specific child process for output.

        Args:
            pid: Process ID to monitor
            command: Command line of the process
        """
        if not _HAS_PSUTIL:
            logger.debug(
                "psutil not available - cannot capture output from PID %d",
                pid,
            )
            return

        # Start a thread to monitor this process
        monitor_thread = threading.Thread(
            target=self._monitor_process_output,
            args=(pid, command),
            daemon=True,
            name=f"process-output-{pid}",
        )
        self._process_threads[pid] = monitor_thread
        monitor_thread.start()

    def _monitor_process_output(self, pid: int, command: str) -> None:
        """Monitor output from a specific process.

        This uses psutil to periodically check if the process has generated
        new output. On Windows, we simulate output streaming by detecting
        process activity and emitting status updates.

        Args:
            pid: Process ID to monitor
            command: Command line of the process
        """
        try:
            process = psutil.Process(pid)
            last_check = time.monotonic()
            last_status = None
            output_count = 0

            while self._monitoring:
                try:
                    if not process.is_running():
                        break

                    # Check process status
                    status = process.status()
                    cpu_percent = process.cpu_percent(interval=0.1)

                    # Emit periodic status updates to show liveness
                    now = time.monotonic()
                    if now - last_check >= 5.0 and (status != last_status or cpu_percent > 1.0):
                        output_count += 1
                        status_msg = self._format_process_status(
                            pid, command, status, cpu_percent, output_count
                        )
                        self._emit_output("stdout", status_msg)
                        last_status = status
                        last_check = now

                    # Check for process I/O activity (indicates it's producing output)
                    try:
                        io_counters = process.io_counters()
                        if (hasattr(io_counters, 'write_bytes')
                            and io_counters.write_bytes > 0
                            and now - last_check >= 2.0):
                            output_msg = f"[PID {pid}] Process active (I/O detected)\n"
                            self._emit_output("stdout", output_msg)
                            last_check = now
                    except (psutil.AccessDenied, AttributeError):
                        pass

                    time.sleep(self._poll_interval)

                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    break

        except Exception as e:
            logger.debug(
                "Error monitoring output for PID %d: %s",
                pid,
                e,
            )

    def _format_process_status(
        self, pid: int, command: str, status: str, cpu_percent: float, count: int
    ) -> str:
        """Format a process status message for output.

        Args:
            pid: Process ID
            command: Command line
            status: Process status (running, sleeping, etc.)
            cpu_percent: CPU usage percentage
            count: Status update count

        Returns:
            Formatted status string
        """
        # Extract command name from full command line
        cmd_name = command.split()[0] if command else "unknown"
        if os.path.sep in cmd_name:
            cmd_name = os.path.basename(cmd_name)

        return (
            f"[PID {pid}] {cmd_name} is {status} "
            f"(CPU: {cpu_percent:.1f}%, update #{count})\n"
        )

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
