"""Global registry for the active SessionStats object.

Some signals (like beads item creation) are observed deep in the Copilot SDK
streaming/tool event handler, which doesn't have direct access to the
orchestrator's SessionStats reference.

This module provides a small, thread-safe bridge so those components can
update the live stats object (which is already internally locked).
"""

from __future__ import annotations

import threading

from pokepoke.types import SessionStats


_lock = threading.Lock()
_current: SessionStats | None = None


def set_current_session_stats(stats: SessionStats | None) -> None:
    global _current
    with _lock:
        _current = stats


def get_current_session_stats() -> SessionStats | None:
    with _lock:
        return _current
