"""Process utilities for SDK client management and memory monitoring."""
import asyncio
import contextlib
import logging
import os
import subprocess
import threading
import time
from collections.abc import Generator
from typing import Any

try:
    import psutil
    _HAS_PSUTIL = True
except ImportError:
    _HAS_PSUTIL = False

from pokepoke.stats.perf_timing import timed_block

# Re-export memory functions so existing callers continue to work.
from pokepoke.utils.memory_utils import (
    apply_memory_backpressure as apply_memory_backpressure,
)
from pokepoke.utils.memory_utils import (
    get_available_memory_mb as get_available_memory_mb,
)
from pokepoke.utils.memory_utils import (
    get_process_rss_mb as get_process_rss_mb,
)
from pokepoke.utils.memory_utils import (
    is_memory_critical as is_memory_critical,
)
from pokepoke.utils.memory_utils import (
    is_memory_pressure as is_memory_pressure,
)

logger = logging.getLogger(__name__)

_cache_lock = threading.Lock()  # Protects global cache state
_copilot_process_cache: tuple[float, int] | None = None  # (timestamp, count)
_copilot_last_tasklist_failure_log: float | None = None
_COPILOT_CACHE_TTL = 5.0


class ActivePidRegistry:
    """Thread-safe registry of active copilot worker PIDs. Orphan killer uses this to distinguish zombies from legitimate processes."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._pids: set[int] = set()

    def register(self, pid: int) -> None:
        """Mark *pid* as an active worker-owned copilot process."""
        with self._lock:
            self._pids.add(pid)
        logger.debug("ActivePidRegistry: registered PID %d", pid)

    def deregister(self, pid: int) -> None:
        """Remove *pid* from the active set (worker finished or crashed)."""
        with self._lock:
            self._pids.discard(pid)
        logger.debug("ActivePidRegistry: deregistered PID %d", pid)

    @property
    def active_pids(self) -> frozenset[int]:
        """Snapshot of currently registered PIDs."""
        with self._lock:
            return frozenset(self._pids)

    @contextlib.contextmanager
    def tracked(self, pid: int) -> Generator[None, None, None]:
        """Context manager: register on entry, deregister on exit."""
        self.register(pid)
        try:
            yield
        finally:
            self.deregister(pid)

    def clear(self) -> None:
        """Remove all registered PIDs (for testing or reset)."""
        with self._lock:
            self._pids.clear()


# Module-level singleton
_active_pid_registry = ActivePidRegistry()


def get_active_pid_registry() -> ActivePidRegistry:
    """Return the module-level ActivePidRegistry singleton."""
    return _active_pid_registry


def extract_client_pid(client: Any) -> int | None:
    """Extract copilot subprocess PID from SDK client._process (defensive for SDK version changes)."""
    try:
        proc = getattr(client, '_process', None)
        if proc is not None and hasattr(proc, 'pid'):
            return proc.pid  # type: ignore[no-any-return]
    except Exception:
        pass
    return None


def register_client_pid(client: Any, registry: ActivePidRegistry) -> int | None:
    """Extract the copilot subprocess PID and register it. Returns the PID if successful, or None."""
    pid = extract_client_pid(client)
    if pid is not None:
        registry.register(pid)
        logger.debug("Registered copilot PID %d", pid)
    return pid


def deregister_client_pid(pid: int | None, registry: ActivePidRegistry) -> None:
    """Deregister a copilot PID if one was registered."""
    if pid is not None:
        registry.deregister(pid)

def kill_orphaned_copilot_processes(
    active_pids: frozenset[int] | set[int] | None = None,
) -> int:
    """Kill orphaned copilot.exe processes. Consults ActivePidRegistry to protect legitimate PIDs. Returns count killed."""
    if os.name != 'nt':
        return 0
    if active_pids is None:
        active_pids = _active_pid_registry.active_pids
    try:
        result = subprocess.run(
            ['tasklist', '/FI', 'IMAGENAME eq copilot.exe', '/FO', 'CSV'],
            capture_output=True, text=True, timeout=30,
            encoding='utf-8', errors='replace',
        )
        lines = result.stdout.strip().split('\n')
        if len(lines) <= 1:
            return 0
        all_pids: list[int] = []
        for line in lines[1:]:
            parts = line.strip().strip('"').split('","')
            if len(parts) >= 2:
                with contextlib.suppress(ValueError):
                    all_pids.append(int(parts[1]))
        orphan_pids = [p for p in all_pids if p not in active_pids]
        if not orphan_pids:
            return 0
        killed = 0
        for pid in orphan_pids:
            try:
                subprocess.run(['taskkill', '/F', '/T', '/PID', str(pid)], capture_output=True, timeout=10)
                killed += 1
            except Exception as e:
                logger.warning(f"Failed to kill copilot PID {pid}: {e}")
        if killed > 0:
            logger.info(f"Killed {killed} orphaned Copilot process(es) (protected {len(active_pids)} active)")
            global _copilot_process_cache
            with _cache_lock:
                _copilot_process_cache = None
        return killed
    except Exception as e:
        logger.warning(f"Failed to clean orphaned Copilot processes: {e}")
        return 0


def log_process_tree_snapshot(
    tool_name: str, args_str: str, elapsed: float, handler: Any = None,
) -> None:
    """Capture child process tree when a tool timeout fires."""
    if os.name != 'nt':
        return
    try:
        result = subprocess.run(
            ['tasklist', '/FI', 'IMAGENAME eq copilot.exe', '/FO', 'CSV'],
            capture_output=True, text=True, timeout=5,
            encoding='utf-8', errors='replace',
        )
        lines = result.stdout.strip().split('\n')
        if len(lines) <= 1:
            logger.info("TOOL_TIMEOUT_DIAG: No copilot.exe processes found")
            return
        copilot_pids: list[int] = []
        for line in lines[1:]:
            parts = line.strip().strip('"').split('","')
            if len(parts) >= 2:
                with contextlib.suppress(ValueError):
                    copilot_pids.append(int(parts[1]))
        for cpid in copilot_pids:
            child_result = subprocess.run(
                ['wmic', 'process', 'where', f'ParentProcessId={cpid}',
                 'get', 'ProcessId,Name,CommandLine', '/format:list'],
                capture_output=True, text=True, timeout=5,
                encoding='utf-8', errors='replace',
            )
            children = child_result.stdout.strip()
            suffix = f"children:\n{children}" if children else "— no child processes"
            logger.info("TOOL_TIMEOUT_DIAG: copilot_pid=%d tool=%s elapsed=%.0fs %s", cpid, tool_name, elapsed, suffix)
        if handler and hasattr(handler, '_item_logger') and handler._item_logger:
            handler._item_logger.log_error(
                f"TOOL_TIMEOUT_DIAG: {len(copilot_pids)} copilot process(es), "
                f"tool={tool_name}, elapsed={elapsed:.0f}s"
            )
    except Exception as e:
        logger.debug("Failed to capture process tree snapshot: %s", e)

def kill_process_tree(pid: int) -> bool:
    """Kill a process and its entire child tree.

    Windows: ``taskkill /F /T /PID``.
    Unix: Uses psutil to recursively kill children, then kills parent.
          Falls back to process group termination if psutil unavailable.
    Returns True on success (or if the process already exited).
    """
    if os.name == 'nt':
        try:
            result = subprocess.run(
                ['taskkill', '/F', '/T', '/PID', str(pid)],
                capture_output=True, text=True, timeout=15,
                encoding='utf-8', errors='replace',
            )
            if result.returncode == 0:
                logger.info("Killed process tree for PID %d", pid)
            else:
                stderr = (result.stderr or "").strip()
                log = logger.debug if "not found" in stderr.lower() else logger.warning
                log("taskkill /T for PID %d returned %d: %s", pid, result.returncode, stderr)
            return result.returncode == 0
        except (subprocess.TimeoutExpired, Exception) as e:
            logger.warning("Failed to kill process tree for PID %d: %s", pid, e)
            return False
    # Unix: Kill children first, then parent
    if _HAS_PSUTIL:
        try:
            parent = psutil.Process(pid)
            children = parent.children(recursive=True)
            for child in children:
                try:
                    child.kill()
                    logger.debug("Killed child process PID %d", child.pid)
                except psutil.NoSuchProcess:
                    pass
                except Exception as e:
                    logger.warning("Failed to kill child PID %d: %s", child.pid, e)
            parent.kill()
            logger.info("Killed process tree for PID %d (%d children)", pid, len(children))
            return True
        except psutil.NoSuchProcess:
            logger.debug("Process %d already exited", pid)
            return True
        except Exception as e:
            logger.warning("Failed to kill process tree for PID %d: %s", pid, e)
    # Fallback: Try process group kill, then direct kill
    try:
        try:
            pgid = os.getpgid(pid)  # type: ignore[attr-defined]  # Unix only
            os.killpg(pgid, 9)  # type: ignore[attr-defined]  # Unix only, SIGKILL
            logger.info("Killed process group %d for PID %d", pgid, pid)
            return True
        except (ProcessLookupError, PermissionError, OSError):
            os.kill(pid, 9)  # SIGKILL
            logger.info("Sent SIGKILL to PID %d (no process group)", pid)
            return True
    except ProcessLookupError:
        logger.debug("Process %d already exited", pid)
        return True
    except Exception as e:
        logger.warning("Failed to kill PID %d: %s", pid, e)
        return False


def check_copilot_processes() -> int:
    """Check running Copilot processes on Windows (cached for _COPILOT_CACHE_TTL seconds). Returns count."""
    global _copilot_process_cache, _copilot_last_tasklist_failure_log

    if os.name != 'nt':
        return 0

    now = time.time()
    with _cache_lock:
        if _copilot_process_cache is not None:
            cached_time, cached_count = _copilot_process_cache
            if now - cached_time < _COPILOT_CACHE_TTL:
                return cached_count

    try:
        with timed_block("tasklist.copilot"):
            result = subprocess.run([
                'tasklist', '/FI', 'IMAGENAME eq copilot.exe', '/FO', 'CSV'
            ], capture_output=True, text=True, timeout=30,
               encoding='utf-8', errors='replace')

        # Count lines excluding header
        lines = result.stdout.strip().split('\n')
        count = max(0, len(lines) - 1) if len(lines) > 1 else 0

        with _cache_lock:
            _copilot_process_cache = (now, count)
        return count
    except Exception as e:
        # Do not cache failures: a transient tasklist error must not mask still-running processes.
        with _cache_lock:
            if (
                _copilot_last_tasklist_failure_log is None
                or now - _copilot_last_tasklist_failure_log >= _COPILOT_CACHE_TTL
            ):
                logger.warning(f"Failed to check for Copilot processes: {e}")
                _copilot_last_tasklist_failure_log = now
        return 0


def is_process_running(pid: int) -> bool:
    """Check if a process with the given PID is currently running. Returns True if running, False otherwise."""
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
            logger.debug("Failed to check if process %d exists", pid, exc_info=True)
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
    """Shut down the Copilot client gracefully with fallbacks.

    Also deregisters the client's copilot PID from the active registry
    so the orphan killer knows it's no longer an active worker.
    """
    # Deregister PID before shutdown so orphan killer won't protect a dying process
    pid = extract_client_pid(client)
    if pid is not None:
        _active_pid_registry.deregister(pid)

    try:
        logger.info("\n[SDK] Initiating graceful client shutdown...")
        await asyncio.sleep(0.5)
        try:
            await asyncio.wait_for(client.stop(), timeout=10.0)
            logger.info("[SDK] Client stopped gracefully")
            if os.name == "nt":
                wait_for_process_cleanup(max_wait=2.0)
        except TimeoutError:
            logger.info("[SDK] Client stop timed out after 10s - forcing shutdown")
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
        logger.error("[SDK] Client stopped (encoding error suppressed)")
    except Exception as e:
        logger.error(f"[SDK] Error stopping client: {e}")
    finally:
        # Kill the full process tree as a safety net to prevent orphaned
        # child processes (Node.js sub-agents, PowerShell tool calls, etc.)
        if pid is not None and is_process_running(pid):
            logger.info("[SDK] Killing remaining process tree for PID %d", pid)
            kill_process_tree(pid)
