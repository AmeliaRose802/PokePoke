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

from pokepoke.agent_registry import AgentRegistry

from pokepoke.shutdown import (
    request_stop_after_current as _request_stop_after_current,
    cancel_stop_after_current as _cancel_stop_after_current,
    should_stop_after_current as _should_stop_after_current,
)

from pokepoke import desktop_api_ext as _ext

if TYPE_CHECKING:
    from pokepoke.types import SessionStats


class DesktopAPI:
    """API surface exposed to the pywebview frontend.

    pywebview exposes every public method to JavaScript automatically.
    Methods run on a background thread — they won't block the UI.
    """

    def __init__(self) -> None:
        self._window: Optional[Any] = None
        self._lock = threading.RLock()

        # Buffered state — frontend can poll or get pushed updates
        self._log_buffer: list[dict[str, Any]] = []
        self._max_log_buffer = 2000
        self._current_work_item: Optional[dict[str, str]] = None
        self._current_agent_name: str = ""
        self._current_stats: Optional[dict[str, Any]] = None
        self._current_progress: dict[str, Any] = {"active": False, "status": ""}

        # Session start time for dynamic elapsed_time computation
        self._session_start_time: Optional[float] = None
        # Session end time to freeze the clock when agents complete
        self._session_end_time: Optional[float] = None

        # Live reference to SessionStats — serialized fresh on each poll
        # so agent run counts, token stats, etc. update in real-time
        self._live_session_stats: Optional["SessionStats"] = None

        # Read index for incremental log fetching
        self._log_read_index: int = 0

        # Leaderboard cache for model performance stats
        self._leaderboard_cache: dict[str, Any] = {}
        self._leaderboard_cache_time: float = 0.0
        self._history_cache: list[dict[str, Any]] = []
        self._history_cache_limit: int = 200
        self._history_cache_time: float = 0.0

        # Running agents — keyed by agent_id
        self._agent_max_log_lines_internal = 20
        self._agent_detail_max_log_lines_internal = 200
        self._agent_registry = AgentRegistry(
            self._lock,
            preview_limit=self._agent_max_log_lines_internal,
            detail_limit=self._agent_detail_max_log_lines_internal,
        )

    def set_window(self, window: Any) -> None:
        """Called once after pywebview creates the window."""
        self._window = window

    @staticmethod
    def _snapshot_to_dict(snapshot: Any) -> dict[str, Any]:
        """Convert a SessionStatsSnapshot to a JSON-serializable dict."""
        return {
            "agent_stats": asdict(snapshot.agent_stats),
            "items_completed": snapshot.items_completed,
            "completed_items": [
                {
                    "id": item.id,
                    "title": item.title,
                    "status": item.status,
                    "issue_type": item.issue_type,
                }
                for item in snapshot.completed_items_list
            ],
            "work_agent_runs": snapshot.work_agent_runs,
            "gate_agent_runs": snapshot.gate_agent_runs,
            "tech_debt_agent_runs": snapshot.tech_debt_agent_runs,
            "janitor_agent_runs": snapshot.janitor_agent_runs,
            "backlog_cleanup_agent_runs": snapshot.backlog_cleanup_agent_runs,
            "cleanup_agent_runs": snapshot.cleanup_agent_runs,
            "beta_tester_agent_runs": snapshot.beta_tester_agent_runs,
            "code_review_agent_runs": snapshot.code_review_agent_runs,
            "worktree_cleanup_agent_runs": snapshot.worktree_cleanup_agent_runs,
            "model_completions": [asdict(mc) for mc in snapshot.model_completions],
        }

    def _serialize_live_stats(self) -> Optional[dict[str, Any]]:
        """Serialize session stats fresh on every poll."""
        stats: dict[str, Any] | None = None
        live = self._live_session_stats
        if live is not None:
            stats = self._snapshot_to_dict(live.snapshot())
            cached = self._current_stats
            if cached is not None and "elapsed_time" in cached:
                stats["elapsed_time"] = cached["elapsed_time"]
        elif self._current_stats is not None:
            stats = dict(self._current_stats)

        # Override with live elapsed_time if session start is known
        if self._session_start_time is not None:
            # If session has ended, use the final elapsed time (frozen clock)
            if self._session_end_time is not None:
                elapsed = self._session_end_time - self._session_start_time
            else:
                # Session is still running, calculate live elapsed time
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
                "model_leaderboard": self._get_cached_leaderboard(),
                "agents": self._agent_registry.serialize_all(),
                "stop_after_current": _should_stop_after_current(),
            }

    def _get_cached_leaderboard(self) -> dict[str, Any]:
        """Return model leaderboard, cached for 5 seconds to avoid disk reads on every poll."""
        now = time.time()
        if now - self._leaderboard_cache_time > 5.0:
            from pokepoke.model_stats_store import get_model_summary
            self._leaderboard_cache = get_model_summary()
            self._leaderboard_cache_time = now
        return self._leaderboard_cache

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

    def get_model_leaderboard(self) -> dict[str, Any]:
        """Get all-time model performance stats from persistent storage."""
        from pokepoke.model_stats_store import get_model_summary
        return get_model_summary()

    def get_model_history(self, limit: int = 200) -> list[dict[str, Any]]:
        """Return recent model completion history for trend charts."""
        if limit <= 0:
            return []
        now = time.time()
        if (
            self._history_cache
            and limit == self._history_cache_limit
            and now - self._history_cache_time <= 5.0
        ):
            return list(self._history_cache)

        from pokepoke.model_stats_store import get_model_history as _get_model_history

        history = list(_get_model_history(limit=limit))
        self._history_cache = history
        self._history_cache_limit = limit
        self._history_cache_time = now
        return list(history)

    get_config = _ext.get_config
    save_config = _ext.save_config

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

    def set_session_end_time(self, end_time: float) -> None:
        """Store the session end time to freeze the elapsed_time clock.

        When called, the session clock will stop and show the final
        session duration instead of continuing to tick. This should
        be called when all agents have finished and the session is complete.
        """
        self._session_end_time = end_time

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
        """
        if session_stats:
            self._live_session_stats = session_stats
        stats_data: dict[str, Any] = {"elapsed_time": elapsed_time}
        if session_stats:
            stats_data.update(self._snapshot_to_dict(session_stats.snapshot()))
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

    @property
    def _agent_max_log_lines(self) -> int:
        return self._agent_max_log_lines_internal

    @_agent_max_log_lines.setter
    def _agent_max_log_lines(self, value: int) -> None:
        self._agent_max_log_lines_internal = value
        self._agent_registry.set_limits(value, self._agent_detail_max_log_lines_internal)

    @property
    def _agent_detail_max_log_lines(self) -> int:
        return self._agent_detail_max_log_lines_internal

    @_agent_detail_max_log_lines.setter
    def _agent_detail_max_log_lines(self, value: int) -> None:
        self._agent_detail_max_log_lines_internal = value
        self._agent_registry.set_limits(self._agent_max_log_lines_internal, value)

    def push_agent_status(
        self, agent_id: str, name: str, iteration: int = 1, status: str = "running",
    ) -> None:
        """Register or update a running agent."""
        self._agent_registry.update_status(agent_id, name, iteration, status)

    def push_agent_log(self, agent_id: str, line: str) -> None:
        """Append a log line to an agent's recent log preview."""
        self._agent_registry.append_log(agent_id, line)

    def remove_agent(self, agent_id: str) -> None:
        """Remove a finished agent from the tracked set."""
        self._agent_registry.remove(agent_id)

    def get_agents(self) -> list[dict[str, Any]]:
        """Return the list of currently tracked agents."""
        return self._agent_registry.serialize_all()

    def get_agent_detail(self, agent_id: str) -> Optional[dict[str, Any]]:
        """Return a deep copy of a single agent's detail state (logs included)."""
        return self._agent_registry.get_detail(agent_id)

    def request_stop_after_current(self) -> dict[str, bool]:
        """Request that the orchestrator stop after the current item completes."""
        _request_stop_after_current()
        self.push_log("⏸️  Stop after current item requested", "orchestrator", "yellow")
        return {"stop_after_current": True}

    def cancel_stop_after_current(self) -> dict[str, bool]:
        """Cancel a pending stop-after-current request."""
        _cancel_stop_after_current()
        self.push_log("▶️  Stop after current item cancelled", "orchestrator")
        return {"stop_after_current": False}

    list_prompts = _ext.list_prompts
    get_prompt = _ext.get_prompt
    save_prompt = _ext.save_prompt
    reset_prompt = _ext.reset_prompt
