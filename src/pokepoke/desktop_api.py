"""Python API exposed to the desktop frontend via pywebview.

Every public method on DesktopAPI is callable from JavaScript as:
    await window.pywebview.api.method_name(args)

This is NOT a server. pywebview calls these methods directly in-process.
"""

from __future__ import annotations

import threading
import time
from dataclasses import asdict
from typing import Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from pokepoke.types import SessionStats


class DesktopAPI:
    """API surface exposed to the pywebview frontend.

    pywebview exposes every public method to JavaScript automatically.
    Methods run on a background thread — they won't block the UI.
    """

    def __init__(self) -> None:
        self._window: Optional[Any] = None
        self._lock = threading.Lock()

        # Buffered state — frontend can poll or get pushed updates
        self._log_buffer: list[dict[str, Any]] = []
        self._max_log_buffer = 2000
        self._current_work_item: Optional[dict[str, str]] = None
        self._current_agent_name: str = ""
        self._current_stats: Optional[dict[str, Any]] = None
        self._current_progress: dict[str, Any] = {"active": False, "status": ""}

        # Session start time for dynamic elapsed_time computation
        self._session_start_time: Optional[float] = None

        # Live reference to SessionStats — serialized fresh on each poll
        # so agent run counts, token stats, etc. update in real-time
        self._live_session_stats: Optional["SessionStats"] = None

        # Read index for incremental log fetching
        self._log_read_index: int = 0

    def set_window(self, window: Any) -> None:
        """Called once after pywebview creates the window."""
        self._window = window

    # ─── JS → Python: Query methods ──────────────────────────────────

    def _serialize_live_stats(self) -> Optional[dict[str, Any]]:
        """Serialize session stats fresh on every poll.

        If a live SessionStats reference is stored, it is serialized
        on each call so agent run counts, token stats, retries, etc.
        update in real-time without needing explicit push_stats() calls.
        elapsed_time is also recomputed dynamically from session start.
        """
        stats: dict[str, Any] | None = None
        live = self._live_session_stats
        if live is not None:
            stats = {
                "agent_stats": asdict(live.agent_stats),
                "items_completed": live.items_completed,
                "work_agent_runs": live.work_agent_runs,
                "gate_agent_runs": live.gate_agent_runs,
                "tech_debt_agent_runs": live.tech_debt_agent_runs,
                "janitor_agent_runs": live.janitor_agent_runs,
                "backlog_cleanup_agent_runs": live.backlog_cleanup_agent_runs,
                "cleanup_agent_runs": live.cleanup_agent_runs,
                "beta_tester_agent_runs": live.beta_tester_agent_runs,
                "code_review_agent_runs": live.code_review_agent_runs,
                "worktree_cleanup_agent_runs": live.worktree_cleanup_agent_runs,
                "model_completions": [
                    asdict(mc) for mc in live.model_completions
                ],
            }
            # Carry forward elapsed_time from last push_stats snapshot
            cached = self._current_stats
            if cached is not None and "elapsed_time" in cached:
                stats["elapsed_time"] = cached["elapsed_time"]
        elif self._current_stats is not None:
            stats = dict(self._current_stats)

        # Override with live elapsed_time if session start is known
        if self._session_start_time is not None:
            elapsed = time.time() - self._session_start_time
            if stats is None:
                stats = {"elapsed_time": elapsed}
            else:
                stats["elapsed_time"] = elapsed

        return stats

    def get_state(self) -> dict[str, Any]:
        """Get the full current state snapshot. Called on frontend init."""
        with self._lock:
            return {
                "work_item": self._current_work_item,
                "agent_name": self._current_agent_name,
                "stats": self._serialize_live_stats(),
                "progress": self._current_progress,
                "log_count": len(self._log_buffer),
            }

    def get_new_logs(self) -> list[dict[str, Any]]:
        """Get log entries added since the last call (incremental).

        The frontend polls this on a timer instead of receiving pushes,
        which avoids the complexity of evaluate_js and thread-safety
        issues with pywebview.
        """
        with self._lock:
            if self._log_read_index >= len(self._log_buffer):
                return []
            new_logs = self._log_buffer[self._log_read_index:]
            self._log_read_index = len(self._log_buffer)
            return new_logs

    def get_all_logs(self) -> list[dict[str, Any]]:
        """Get all buffered logs (for reconnect / initial load)."""
        with self._lock:
            self._log_read_index = len(self._log_buffer)
            return list(self._log_buffer)

    def get_work_item(self) -> Optional[dict[str, str]]:
        """Get the current work item."""
        return self._current_work_item

    def get_stats(self) -> Optional[dict[str, Any]]:
        """Get the current session stats."""
        with self._lock:
            return self._serialize_live_stats()

    # ─── Python → State: Called by the orchestrator ───────────────────

    def push_log(
        self, message: str, target: str = "orchestrator", style: Optional[str] = None
    ) -> None:
        """Add a log entry to the buffer."""
        entry = {
            "message": message,
            "target": target,
            "style": style,
            "timestamp": time.time(),
        }
        with self._lock:
            self._log_buffer.append(entry)
            if len(self._log_buffer) > self._max_log_buffer:
                # Trim oldest entries and adjust read index
                trim = len(self._log_buffer) - self._max_log_buffer
                self._log_buffer = self._log_buffer[trim:]
                self._log_read_index = max(0, self._log_read_index - trim)

    def push_work_item(self, item_id: str, title: str, status: str = "") -> None:
        """Update the current work item."""
        self._current_work_item = {
            "item_id": item_id,
            "title": title,
            "status": status,
        }

    def set_session_start_time(self, start_time: float) -> None:
        """Store the session start time for dynamic elapsed_time computation.

        Once set, every call to get_state()/get_stats() will recompute
        elapsed_time = now - start_time so the frontend timer ticks live.
        """
        self._session_start_time = start_time

    def set_live_session_stats(self, session_stats: "SessionStats") -> None:
        """Store a live reference to SessionStats for real-time polling.

        The live object is serialized fresh on every get_state()/get_stats()
        poll, so any mutations (agent run counts, token stats, retries)
        are reflected immediately without needing explicit push calls.
        """
        self._live_session_stats = session_stats

    def push_stats(
        self, session_stats: Optional["SessionStats"], elapsed_time: float = 0.0
    ) -> None:
        """Update session statistics (snapshot fallback).

        Prefer set_live_session_stats() for real-time updates.
        This method is kept for backwards compatibility and is used
        as a fallback when no live reference is set.
        """
        if session_stats:
            self._live_session_stats = session_stats
        stats_data: dict[str, Any] = {"elapsed_time": elapsed_time}
        if session_stats:
            stats_data["agent_stats"] = asdict(session_stats.agent_stats)
            stats_data["items_completed"] = session_stats.items_completed
            stats_data["work_agent_runs"] = session_stats.work_agent_runs
            stats_data["gate_agent_runs"] = session_stats.gate_agent_runs
            stats_data["tech_debt_agent_runs"] = session_stats.tech_debt_agent_runs
            stats_data["janitor_agent_runs"] = session_stats.janitor_agent_runs
            stats_data["backlog_cleanup_agent_runs"] = session_stats.backlog_cleanup_agent_runs
            stats_data["cleanup_agent_runs"] = session_stats.cleanup_agent_runs
            stats_data["beta_tester_agent_runs"] = session_stats.beta_tester_agent_runs
            stats_data["code_review_agent_runs"] = session_stats.code_review_agent_runs
            stats_data["worktree_cleanup_agent_runs"] = session_stats.worktree_cleanup_agent_runs
            stats_data["model_completions"] = [
                asdict(mc) for mc in session_stats.model_completions
            ]
        self._current_stats = stats_data

    def push_agent_name(self, name: str) -> None:
        """Update the current agent name."""
        self._current_agent_name = name

    def push_progress(self, active: bool, status: str = "") -> None:
        """Update the progress indicator."""
        self._current_progress = {"active": active, "status": status}

    def clear_logs(self) -> None:
        """Clear the log buffer."""
        with self._lock:
            self._log_buffer.clear()
            self._log_read_index = 0
