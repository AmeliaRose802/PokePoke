"""Process utilities for SDK client management."""
import asyncio
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
