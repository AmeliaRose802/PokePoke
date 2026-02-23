"""Process utilities for SDK client management."""
import logging
import os
import subprocess
import time

logger = logging.getLogger(__name__)

# Cache tasklist results to avoid flooding the console with timeout messages
# under high parallelism. Stores (timestamp, count) or None if uncached.
_copilot_process_cache: tuple[float, int] | None = None
_COPILOT_CACHE_TTL = 5.0  # seconds between actual tasklist invocations


def check_copilot_processes() -> int:
    """Check for running Copilot-related processes on Windows.

    Results are cached for _COPILOT_CACHE_TTL seconds to prevent hundreds of
    tasklist invocations when many parallel agents poll simultaneously.

    Returns the number of processes found.
    """
    global _copilot_process_cache

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
    except Exception as e:
        logger.warning(f"Failed to check for Copilot processes: {e}")
        count = 0  # Assume no processes if check fails

    _copilot_process_cache = (now, count)
    return count


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
