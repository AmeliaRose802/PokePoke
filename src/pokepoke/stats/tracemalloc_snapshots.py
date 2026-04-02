"""Optional tracemalloc integration for detecting memory growth between completions.

Enable by calling ``start()`` at orchestrator startup. After each successful
agent completion, call ``snapshot_and_compare()`` to log the top allocation
growth points since the previous snapshot.

All operations are no-ops when tracemalloc is not started, so callers do not
need to guard every call site.
"""

import logging
import threading
import tracemalloc
from typing import Any

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_previous_snapshot: tracemalloc.Snapshot | None = None
_started = False


def start(nframes: int = 10) -> None:
    """Start tracemalloc with the given number of frames.

    Safe to call multiple times; subsequent calls are no-ops.
    """
    global _started, _previous_snapshot
    with _lock:
        if _started:
            return
        tracemalloc.start(nframes)
        _previous_snapshot = tracemalloc.take_snapshot()
        _started = True
    logger.info("tracemalloc started (nframes=%d)", nframes)


def is_started() -> bool:
    """Return whether tracemalloc tracking is active."""
    with _lock:
        return _started


def snapshot_and_compare(top_n: int = 5) -> list[dict[str, Any]]:
    """Take a snapshot and compare against the previous one.

    Returns the top *top_n* allocation growth entries as dicts with
    ``file``, ``line``, ``size_diff_kb``, and ``size_kb`` keys.

    If tracemalloc is not started or this is the first call, returns an empty list.
    """
    global _previous_snapshot
    with _lock:
        if not _started or _previous_snapshot is None:
            return []
        current = tracemalloc.take_snapshot()
        prev = _previous_snapshot
        _previous_snapshot = current

    current_filtered = current.filter_traces((
        tracemalloc.Filter(False, "<frozen importlib._bootstrap>"),
        tracemalloc.Filter(False, "<frozen importlib._bootstrap_external>"),
        tracemalloc.Filter(False, tracemalloc.__file__),
    ))
    prev_filtered = prev.filter_traces((
        tracemalloc.Filter(False, "<frozen importlib._bootstrap>"),
        tracemalloc.Filter(False, "<frozen importlib._bootstrap_external>"),
        tracemalloc.Filter(False, tracemalloc.__file__),
    ))

    stats = current_filtered.compare_to(prev_filtered, "lineno")
    results: list[dict[str, Any]] = []
    for stat in stats[:top_n]:
        if stat.size_diff <= 0:
            continue
        frame = stat.traceback[0]
        entry = {
            "file": frame.filename,
            "line": frame.lineno,
            "size_diff_kb": round(stat.size_diff / 1024, 1),
            "size_kb": round(stat.size / 1024, 1),
        }
        results.append(entry)
        logger.debug(
            "tracemalloc growth: %s:%d +%.1fKB (total %.1fKB)",
            frame.filename, frame.lineno,
            entry["size_diff_kb"], entry["size_kb"],
        )

    if results:
        logger.info(
            "tracemalloc: top %d growth points after completion (%d entries with growth)",
            min(top_n, len(results)), len(results),
        )
    return results


def stop() -> None:
    """Stop tracemalloc tracking."""
    global _started, _previous_snapshot
    with _lock:
        if not _started:
            return
        tracemalloc.stop()
        _previous_snapshot = None
        _started = False
    logger.info("tracemalloc stopped")
