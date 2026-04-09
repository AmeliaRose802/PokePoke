"""Process tree snapshot capture for diagnostics and desktop UI visualization."""
import logging
import os
import subprocess
import time
from typing import Any

logger = logging.getLogger(__name__)


def log_process_tree_snapshot(
    tool_name: str, args_str: str, elapsed: float,
    handler: Any = None,
) -> None:
    """Capture child process tree and resource usage metrics.

    Logs all child processes of known copilot.exe instances so we can
    determine whether the hang is git contention, a stuck subprocess,
    antivirus scanning, or the CLI itself.

    Also captures CPU%, memory usage, and process counts for performance
    monitoring and visualization in the desktop UI.
    """
    if os.name != 'nt':
        return
    try:
        # Get copilot.exe processes with CPU and memory metrics
        result = subprocess.run(
            ['wmic', 'process', 'where', "Name='copilot.exe'",
             'get', 'ProcessId,WorkingSetSize,KernelModeTime,UserModeTime',
             '/format:csv'],
            capture_output=True, text=True, timeout=5,
            encoding='utf-8', errors='replace',
        )
        lines = [line.strip() for line in result.stdout.strip().split('\n') if line.strip()]
        if len(lines) <= 1:
            logger.debug("TOOL_TIMEOUT_DIAG: No copilot.exe processes found")
            return

        # Parse CSV: Node,KernelModeTime,ProcessId,UserModeTime,WorkingSetSize
        copilot_pids: list[int] = []
        total_memory_bytes = 0
        total_cpu_time_100ns = 0
        for line in lines[1:]:  # Skip header
            parts = [p.strip() for p in line.split(',')]
            if len(parts) >= 5:
                try:
                    kernel_time = int(parts[1])
                    pid = int(parts[2])
                    user_time = int(parts[3])
                    memory_bytes = int(parts[4])
                    copilot_pids.append(pid)
                    total_memory_bytes += memory_bytes
                    total_cpu_time_100ns += kernel_time + user_time
                except (ValueError, IndexError):
                    continue

        # Count child processes across all copilot instances
        total_children = 0
        for cpid in copilot_pids:
            child_result = subprocess.run(
                ['wmic', 'process', 'where', f'ParentProcessId={cpid}',
                 'get', 'ProcessId,Name,CommandLine', '/format:list'],
                capture_output=True, text=True, timeout=5,
                encoding='utf-8', errors='replace',
            )
            children = child_result.stdout.strip()
            if children:
                child_count = len([line for line in children.split('\n')
                                 if line.strip() and 'ProcessId=' in line])
                total_children += child_count
                logger.debug(
                    "TOOL_TIMEOUT_DIAG: copilot_pid=%d tool=%s elapsed=%.0fs children=%d:\n%s",
                    cpid, tool_name, elapsed, child_count, children,
                )
            else:
                logger.debug(
                    "TOOL_TIMEOUT_DIAG: copilot_pid=%d tool=%s elapsed=%.0fs — no child processes",
                    cpid, tool_name, elapsed,
                )

        # Log structured metrics for parsing by frontend
        total_memory_mb = total_memory_bytes / (1024 * 1024)
        # Estimate CPU% from total CPU time across all copilot processes.
        # KernelModeTime + UserModeTime are in 100-nanosecond units since
        # process creation. We convert to seconds and divide by number of
        # logical CPUs to approximate an instantaneous percentage.
        num_cpus = os.cpu_count() or 1
        total_cpu_seconds = total_cpu_time_100ns / 1e7
        cpu_percent = min(
            (total_cpu_seconds / max(elapsed, 1.0)) / num_cpus * 100.0,
            100.0 * len(copilot_pids),
        )
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        metrics_line = (
            f"[{ts}] PROCESS_SNAPSHOT "
            f"copilot_count={len(copilot_pids)} "
            f"child_count={total_children} "
            f"total_memory_mb={total_memory_mb:.1f} "
            f"cpu_percent={cpu_percent:.1f}"
        )
        logger.debug(metrics_line)

        # Also write to dedicated diagnostics log if available
        if handler and hasattr(handler, '_item_logger') and handler._item_logger:
            try:
                from pokepoke.models.sdk_watchdog_diagnostics import resolve_diagnostics_log_path
                diag_log_path = resolve_diagnostics_log_path(handler)
                if diag_log_path:
                    with open(diag_log_path, 'a', encoding='utf-8') as f:
                        f.write(f"{metrics_line}\n")
            except Exception:
                pass

            handler._item_logger.log_debug(f"TOOL_TIMEOUT_DIAG: {len(copilot_pids)} copilot process(es), "
                f"{total_children} children, {total_memory_mb:.0f}MB, "
                f"tool={tool_name}, elapsed={elapsed:.0f}s"
            )
    except Exception as e:
        logger.debug("Failed to capture process tree snapshot: %s", e)
