"""Memory monitoring utilities: system-wide available memory and process RSS."""

import ctypes
import logging
import os
import threading
import time

try:
    import psutil
    _HAS_PSUTIL = True
except ImportError:
    _HAS_PSUTIL = False

from pokepoke.stats.perf_timing import timed_block

logger = logging.getLogger(__name__)

_cache_lock = threading.Lock()
_MEMORY_CACHE_TTL = 10.0
_memory_cache: tuple[float, int] | None = None
_rss_cache: tuple[float, int] | None = None
_cpu_cache: tuple[float, float] | None = None

_MEMORY_PRESSURE_THRESHOLD_MB = 2048
_MEMORY_CRITICAL_THRESHOLD_MB = 1024


def get_available_memory_mb() -> int:
    """Return available physical memory in MB (Windows only, uses ctypes). Returns 0 on non-Windows or failure."""
    global _memory_cache
    if os.name != 'nt':
        return 0
    now = time.time()
    with _cache_lock:
        if _memory_cache is not None:
            cached_time, cached_mb = _memory_cache
            if now - cached_time < _MEMORY_CACHE_TTL:
                return cached_mb

    try:
        with timed_block("memory.check"):
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
            with _cache_lock:
                _memory_cache = (now, available_mb)
            return available_mb
    except Exception as e:
        logger.debug(f"Failed to query available memory: {e}")
        return 0


def get_process_rss_mb() -> int:
    """Return this process's RSS (resident set size) in MB via psutil.

    Returns 0 if psutil is unavailable or the query fails.
    Cached for _MEMORY_CACHE_TTL seconds to match system memory caching.
    """
    global _rss_cache
    if not _HAS_PSUTIL:
        return 0
    now = time.time()
    with _cache_lock:
        if _rss_cache is not None:
            cached_time, cached_mb = _rss_cache
            if now - cached_time < _MEMORY_CACHE_TTL:
                return cached_mb
    try:
        rss_bytes = psutil.Process(os.getpid()).memory_info().rss
        rss_mb = int(rss_bytes / (1024 * 1024))
        with _cache_lock:
            _rss_cache = (now, rss_mb)
        return rss_mb
    except Exception as e:
        logger.debug("Failed to query process RSS: %s", e)
        return 0


def is_memory_pressure() -> bool:
    """Return True if system memory is under pressure (< 2 GB free)."""
    available = get_available_memory_mb()
    if available == 0:
        return False
    return available < _MEMORY_PRESSURE_THRESHOLD_MB


def is_memory_critical() -> bool:
    """Return True if system memory is critically low (< 1 GB free)."""
    available = get_available_memory_mb()
    if available == 0:
        return False
    return available < _MEMORY_CRITICAL_THRESHOLD_MB


def get_cpu_usage_percent() -> float:
    """Return system-wide CPU usage percentage via psutil.

    Returns a float percentage (0.0-100.0) or 0.0 if psutil is unavailable
    or the query fails. Cached for _MEMORY_CACHE_TTL seconds to match
    memory caching behavior.
    """
    global _cpu_cache
    if not _HAS_PSUTIL:
        return 0.0
    now = time.time()
    with _cache_lock:
        if _cpu_cache is not None:
            cached_time, cached_percent = _cpu_cache
            if now - cached_time < _MEMORY_CACHE_TTL:
                return cached_percent
    try:
        # interval=1.0 for a 1-second measurement (non-blocking after first call)
        cpu_percent = psutil.cpu_percent(interval=1.0)
        with _cache_lock:
            _cpu_cache = (now, cpu_percent)
        return cpu_percent
    except Exception as e:
        logger.debug("Failed to query CPU usage: %s", e)
        return 0.0


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
