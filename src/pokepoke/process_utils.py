"""Process utilities for SDK client management and memory monitoring."""
import asyncio
import ctypes
import logging
import os
import subprocess
import time
from typing import Any

logger = logging.getLogger(__name__)

# Cache *successful* tasklist results to avoid flooding the console with timeout messages
# under high parallelism. Stores (timestamp, count) or None if uncached.
_copilot_process_cache: tuple[float, int] | None = None

# Rate-limit warning logs for tasklist failures (we still re-run tasklist immediately).
_copilot_last_tasklist_failure_log: float | None = None

_COPILOT_CACHE_TTL = 5.0  # seconds between actual tasklist invocations

# Memory monitoring constants
_MEMORY_PRESSURE_THRESHOLD_MB = 2048  # Throttle new agents when <2 GB free
_MEMORY_CRITICAL_THRESHOLD_MB = 1024  # Block new agents when <1 GB free
_MEMORY_CACHE_TTL = 10.0  # seconds between memory checks
_memory_cache: tuple[float, int] | None = None  # (timestamp, available_mb)


def get_available_memory_mb() -> int:
    """Return available physical memory in MB.

    Uses Windows GlobalMemoryStatusEx via ctypes (no external deps).
    Returns 0 on non-Windows or on failure.
    """
    global _memory_cache

    if os.name != 'nt':
        return 0

    now = time.time()
    if _memory_cache is not None:
        cached_time, cached_mb = _memory_cache
        if now - cached_time < _MEMORY_CACHE_TTL:
            return cached_mb

    try:
        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        mem_status = MEMORYSTATUSEX()
        mem_status.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(mem_status))
        available_mb = int(mem_status.ullAvailPhys / (1024 * 1024))
        _memory_cache = (now, available_mb)
        return available_mb
    except Exception as e:
        logger.debug(f"Failed to query available memory: {e}")
        return 0


def is_memory_pressure() -> bool:
    """Return True if system memory is under pressure (< 2 GB free)."""
    available = get_available_memory_mb()
    if available == 0:
        return False  # Can't determine; assume OK
    return available < _MEMORY_PRESSURE_THRESHOLD_MB


def is_memory_critical() -> bool:
    """Return True if system memory is critically low (< 1 GB free)."""
    available = get_available_memory_mb()
    if available == 0:
        return False
    return available < _MEMORY_CRITICAL_THRESHOLD_MB


def kill_orphaned_copilot_processes(expected_count: int = 0) -> int:
    """Kill Copilot CLI processes that exceed the expected active count.

    Args:
        expected_count: Number of Copilot processes that should be alive
            (i.e. one per active agent). Processes above this count are
            considered orphans and terminated.

    Returns:
        Number of processes killed.
    """
    if os.name != 'nt':
        return 0

    try:
        result = subprocess.run(
            ['tasklist', '/FI', 'IMAGENAME eq copilot.exe', '/FO', 'CSV'],
            capture_output=True, text=True, timeout=30,
            encoding='utf-8', errors='replace',
        )
        lines = result.stdout.strip().split('\n')
        if len(lines) <= 1:
            return 0  # No copilot processes at all

        # Parse PIDs from CSV: "copilot.exe","12345",...
        pids: list[int] = []
        for line in lines[1:]:
            parts = line.strip().strip('"').split('","')
            if len(parts) >= 2:
                try:
                    pids.append(int(parts[1]))
                except ValueError:
                    continue

        excess = len(pids) - expected_count
        if excess <= 0:
            return 0

        # Kill oldest (lowest PID) first — they're most likely orphans
        pids.sort()
        killed = 0
        for pid in pids[:excess]:
            try:
                subprocess.run(
                    ['taskkill', '/F', '/T', '/PID', str(pid)],
                    capture_output=True, timeout=10,
                )
                killed += 1
            except Exception as e:
                logger.debug(f"Failed to kill copilot PID {pid}: {e}")

        if killed > 0:
            logger.info(f"Killed {killed} orphaned Copilot CLI process(es)")
            # Invalidate cache after killing processes
            global _copilot_process_cache
            _copilot_process_cache = None

        return killed
    except Exception as e:
        logger.debug(f"Failed to clean orphaned Copilot processes: {e}")
        return 0


def apply_memory_backpressure(slots: int) -> tuple[int, int]:
    """Apply memory-based backpressure to available agent slots.

    Returns (adjusted_slots, available_mb).
    """
    avail_mb = get_available_memory_mb()
    if avail_mb <= 0:
        return slots, avail_mb
    if is_memory_critical():
        return 0, avail_mb
    if is_memory_pressure() and slots > 0:
        return min(slots, 1), avail_mb
    return slots, avail_mb


def check_copilot_processes() -> int:
    """Check for running Copilot-related processes on Windows.

    Results are cached for _COPILOT_CACHE_TTL seconds to prevent hundreds of
    tasklist invocations when many parallel agents poll simultaneously.

    Returns the number of processes found.
    """
    global _copilot_process_cache, _copilot_last_tasklist_failure_log

    if os.name != 'nt':
        return 0

    now = time.time()
    if _copilot_process_cache is not None:
        cached_time, cached_count = _copilot_process_cache
        if now - cached_time < _COPILOT_CACHE_TTL:
            return cached_count

    try:
        result = subprocess.run([
            'tasklist', '/FI', 'IMAGENAME eq copilot.exe', '/FO', 'CSV'
        ], capture_output=True, text=True, timeout=30,
           encoding='utf-8', errors='replace')

        # Count lines excluding header
        lines = result.stdout.strip().split('\n')
        count = max(0, len(lines) - 1) if len(lines) > 1 else 0

        _copilot_process_cache = (now, count)
        return count
    except Exception as e:
        # Do not cache failures: a transient tasklist error must not mask still-running processes.
        if (
            _copilot_last_tasklist_failure_log is None
            or now - _copilot_last_tasklist_failure_log >= _COPILOT_CACHE_TTL
        ):
            logger.warning(f"Failed to check for Copilot processes: {e}")
            _copilot_last_tasklist_failure_log = now
        return 0


def is_process_running(pid: int) -> bool:
    """Check if a process with the given PID is currently running.

    Args:
        pid: Process ID to check

    Returns:
        True if the process is running, False otherwise
    """
    if os.name == 'nt':
        # Windows implementation
        try:
            result = subprocess.run(
                ['tasklist', '/FI', f'PID eq {pid}', '/FO', 'CSV'],
                capture_output=True, text=True, timeout=10,
                encoding='utf-8', errors='replace'
            )
            # If process exists, tasklist returns header + process line
            lines = result.stdout.strip().split('\n')
            return len(lines) > 1
        except Exception:
            return False
    else:
        # Unix/Linux implementation
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False


def wait_for_process_cleanup(max_wait: float = 3.0) -> None:
    """Wait for Copilot processes to terminate on Windows.

    Args:
        max_wait: Maximum time to wait in seconds
    """
    if os.name != 'nt':
        return

    start_time = time.time()
    while time.time() - start_time < max_wait:
        if check_copilot_processes() == 0:
            return  # All processes cleaned up
        time.sleep(0.1)


async def shutdown_copilot_client(client: Any) -> None:
    """Shut down the Copilot client gracefully with fallbacks."""
    try:
        print("\n[SDK] Initiating graceful client shutdown...")
        await asyncio.sleep(0.5)
        try:
            await asyncio.wait_for(client.stop(), timeout=10.0)
            print("[SDK] Client stopped gracefully")
            if os.name == "nt":
                wait_for_process_cleanup(max_wait=2.0)
        except TimeoutError:
            print("[SDK] Client stop timed out after 10s - forcing shutdown")
            try:
                await asyncio.wait_for(client.stop(), timeout=5.0)
                if os.name == "nt":
                    wait_for_process_cleanup(max_wait=1.0)
            except TimeoutError:
                logger.warning("Force-killing copilot process after double timeout")
                try:
                    await client.force_stop()
                    if os.name == "nt":
                        wait_for_process_cleanup(max_wait=1.0)
                except Exception as force_error:
                    logger.error(f"Failed to force stop client: {force_error}")
            except Exception as e:
                logger.debug(f"Failed to force stop client: {e}")
    except UnicodeDecodeError:
        print("[SDK] Client stopped (encoding error suppressed)")
    except Exception as e:
        print(f"[SDK] Error stopping client: {e}")
