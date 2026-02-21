"""Stats serialization and model leaderboard helpers for DesktopAPI.

Extracted to keep desktop_api.py under the line limit.
These are mixed in by DesktopAPI at import time.
"""
from __future__ import annotations

import time
from dataclasses import asdict
from typing import Any


def snapshot_to_dict(snapshot: Any) -> dict[str, Any]:
    """Convert a SessionStatsSnapshot to a JSON-serializable dict."""
    return {
        "agent_stats": asdict(snapshot.agent_stats),
        "items_completed": snapshot.items_completed,
        "items_created": snapshot.items_created,
        "net_items_delta": snapshot.items_created - snapshot.items_completed,
        "lifetime_items_created": snapshot.lifetime_items_created,
        "lifetime_items_completed": snapshot.lifetime_items_completed,
        "created_counts_by_agent_type": dict(snapshot.created_counts_by_agent_type),
        "completed_counts_by_agent_type": dict(snapshot.completed_counts_by_agent_type),
        "completed_items": [
            {
                "id": item.id,
                "title": item.title,
                "status": item.status,
                "issue_type": item.issue_type,
            }
            for item in snapshot.completed_items_list
        ],
        "created_items": [
            {
                "id": item.id,
                "title": item.title,
                "agent_type": item.agent_type,
            }
            for item in snapshot.created_items_list
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
        "agent_type_elapsed_seconds": dict(snapshot.agent_type_elapsed_seconds),
        "model_completions": [asdict(mc) for mc in snapshot.model_completions],
    }


def serialize_live_stats(self: Any) -> dict[str, Any] | None:
    """Serialize session stats fresh on every poll."""
    stats: dict[str, Any] | None = None
    live = self._live_session_stats
    if live is not None:
        stats = snapshot_to_dict(live.snapshot())
        cached = self._current_stats
        if cached is not None and "elapsed_time" in cached:
            stats["elapsed_time"] = cached["elapsed_time"]
    elif self._current_stats is not None:
        stats = dict(self._current_stats)

    # Override with live elapsed_time if session start is known
    if self._session_start_time is not None:
        if self._session_end_time is not None:
            elapsed = self._session_end_time - self._session_start_time
        else:
            elapsed = time.time() - self._session_start_time

        if stats is None:
            stats = {"elapsed_time": elapsed}
        else:
            stats["elapsed_time"] = elapsed

    return stats


def get_cached_leaderboard(self: Any) -> dict[str, Any]:
    """Return model leaderboard, cached for 5s to avoid disk reads on every poll."""
    now = time.time()
    if now - self._leaderboard_cache_time > 5.0:
        from pokepoke.model_stats_store import get_model_summary
        self._leaderboard_cache = get_model_summary()
        self._leaderboard_cache_time = now
    result: dict[str, Any] = self._leaderboard_cache
    return result


def get_model_leaderboard(self: Any) -> dict[str, Any]:
    """Get all-time model performance stats from persistent storage."""
    from pokepoke.model_stats_store import get_model_summary
    return get_model_summary()


def get_model_history(self: Any, limit: int = 200) -> list[dict[str, Any]]:
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


def push_stats(self: Any, session_stats: Any, elapsed_time: float = 0.0) -> None:
    """Update session statistics (snapshot fallback)."""
    if session_stats:
        self._live_session_stats = session_stats
    stats_data: dict[str, Any] = {"elapsed_time": elapsed_time}
    if session_stats:
        stats_data.update(snapshot_to_dict(session_stats.snapshot()))
    self._current_stats = stats_data
