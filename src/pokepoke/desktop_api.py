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

        # Read index for incremental log fetching
        self._log_read_index: int = 0

    def set_window(self, window: Any) -> None:
        """Called once after pywebview creates the window."""
        self._window = window

    # ─── JS → Python: Query methods ──────────────────────────────────

    def get_state(self) -> dict[str, Any]:
        """Get the full current state snapshot. Called on frontend init."""
        with self._lock:
            return {
                "work_item": self._current_work_item,
                "agent_name": self._current_agent_name,
                "stats": self._current_stats,
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
        return self._current_stats

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

    def push_stats(
        self, session_stats: Optional["SessionStats"], elapsed_time: float = 0.0
    ) -> None:
        """Update session statistics."""
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
