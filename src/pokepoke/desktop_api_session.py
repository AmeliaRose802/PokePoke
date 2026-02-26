"""Session management helpers for DesktopAPI.

Extracted to keep desktop_api.py under the line limit.
"""
from __future__ import annotations

from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from pokepoke.types import SessionStats


def set_session_start_time(self: Any, start_time: float) -> None:
    """Store session start time (enables live elapsed_time ticking)."""
    with self._lock:
        if self._window_disposed:  # Silently ignore after window disposal
            return
        self._session_start_time = start_time
        self._current_session_id = str(start_time)


def set_session_end_time(self: Any, end_time: float) -> None:
    """Store session end time (freezes elapsed_time)."""
    with self._lock:
        if self._window_disposed:  # Silently ignore after window disposal
            return
        self._session_end_time = end_time


def set_live_session_stats(self: Any, session_stats: SessionStats) -> None:
    """Store a live SessionStats reference for real-time polling."""
    with self._lock:
        if self._window_disposed:  # Silently ignore after window disposal
            return
        self._live_session_stats = session_stats
