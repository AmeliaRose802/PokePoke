"""Stats serialization and model leaderboard helpers for DesktopAPI.

Extracted to keep desktop_api.py under the line limit.
These are mixed in by DesktopAPI at import time.
"""
from __future__ import annotations

import time
from dataclasses import asdict
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from pokepoke.desktop_api import DesktopAPI

from pokepoke.agent_types import iter_agent_types


def snapshot_to_dict(snapshot: Any) -> dict[str, Any]:
    """Convert a SessionStatsSnapshot to a JSON-serializable dict."""
    stats = {
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
        "agent_type_elapsed_seconds": dict(snapshot.agent_type_elapsed_seconds),
        "model_completions": [asdict(mc) for mc in snapshot.model_completions],
    }
    for agent in iter_agent_types():
        stats[agent.run_attr] = snapshot.agent_run_counts.get(agent.key, 0)
    return stats


def serialize_live_stats(self: DesktopAPI) -> dict[str, Any] | None:
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

        # Truncate to integer seconds so that shallowEqual on the stats dict
        # succeeds between polls when nothing else has changed.  Without this,
        # the ever-changing float causes React to re-render the StatsBar (and
        # anything else consuming stats) on every single 250 ms poll cycle.
        elapsed = int(elapsed)

        if stats is None:
            stats = {"elapsed_time": elapsed}
        else:
            stats["elapsed_time"] = elapsed

    return stats


def get_cached_leaderboard(self: DesktopAPI) -> dict[str, Any]:
    """Return model leaderboard, cached for 5s to avoid disk reads on every poll."""
    now = time.time()
    if now - self._leaderboard_cache_time > 5.0:
        from pokepoke.model_stats_store import get_model_summary
        self._leaderboard_cache = get_model_summary()
        self._leaderboard_cache_time = now
    result: dict[str, Any] = self._leaderboard_cache
    return result


def get_model_leaderboard(self: DesktopAPI, repo_name: str = "") -> dict[str, Any]:
    """Get all-time model performance stats from persistent storage.

    If *repo_name* is given, returns stats only for that repo.
    """
    from pokepoke.model_stats_store import get_model_summary, get_model_summary_by_repo
    if repo_name:
        return get_model_summary_by_repo(repo_name=repo_name)
    return get_model_summary()


def get_model_history(self: DesktopAPI, limit: int = 200, repo_name: str = "") -> list[dict[str, Any]]:
    """Return recent model completion history for trend charts.

    If *repo_name* is given, only entries for that repo are returned.

    Reads from model_history.jsonl which includes labels and issue_type for better charting.
    Falls back to model_stats.json if history file doesn't exist (backward compatibility).

    Normalizes keys to match frontend ModelHistoryEntry schema:
    - work_item_id → item_id
    - wall_time_seconds → duration_seconds
    - quality_gates_passed → gate_passed
    """
    if limit <= 0:
        return []

    # Skip cache when filtering by repo
    if not repo_name:
        now = time.time()
        if (
            self._history_cache
            and limit == self._history_cache_limit
            and now - self._history_cache_time <= 5.0
        ):
            return list(self._history_cache)

    # Try to load from detailed history first (includes labels and issue_type)
    from pokepoke.model_history import load_model_history_entries
    raw_history = load_model_history_entries(limit=limit)

    # Fall back to model_stats.json if history file doesn't exist
    if not raw_history:
        from pokepoke.model_stats_store import get_model_history as _get_model_history
        raw_history = list(_get_model_history(limit=limit, repo_name=repo_name))

    # Normalize keys to match frontend schema
    history = []
    for entry in raw_history:
        # Apply repo filter if requested (for model_history.jsonl path)
        if repo_name and entry.get("repo_name", "") != repo_name:
            continue
        normalized = dict(entry)

        # Map backend keys to frontend keys
        if "work_item_id" in normalized:
            normalized["item_id"] = normalized.pop("work_item_id")
        if "wall_time_seconds" in normalized:
            normalized["duration_seconds"] = normalized.pop("wall_time_seconds")
        if "quality_gates_passed" in normalized:
            normalized["gate_passed"] = normalized.pop("quality_gates_passed")

        history.append(normalized)

    if not repo_name:
        self._history_cache = history
        self._history_cache_limit = limit
        self._history_cache_time = time.time()
    return list(history)


def push_stats(self: DesktopAPI, session_stats: Any, elapsed_time: float = 0.0) -> None:
    """Update session statistics (snapshot fallback)."""
    if getattr(self, "_window_disposed", False):  # Silently ignore after window disposal
        return

    if session_stats:
        self._live_session_stats = session_stats
    stats_data: dict[str, Any] = {"elapsed_time": elapsed_time}
    if session_stats:
        stats_data.update(snapshot_to_dict(session_stats.snapshot()))
    self._current_stats = stats_data


def get_lock_contention_stats(self: DesktopAPI) -> dict[str, Any]:
    """Get lock contention metrics for all named locks."""
    from pokepoke.lock_contention import get_lock_contention_stats as _get
    return _get()


def get_repo_summary(self: DesktopAPI) -> dict[str, dict[str, Any]]:
    """Return per-repo summary metrics for the dashboard.

    Combines model stats (items processed, success rate, cost) with
    beads item stats (items created/completed) per repo.
    """
    from pokepoke.model_stats_store import get_repo_summary_metrics
    from pokepoke.beads_item_stats_store import get_summary_by_repo

    model_metrics = get_repo_summary_metrics()
    beads_metrics = get_summary_by_repo()

    all_repos = set(model_metrics) | set(beads_metrics)
    result: dict[str, dict[str, Any]] = {}
    for repo in sorted(all_repos):
        mm = model_metrics.get(repo, {})
        bm = beads_metrics.get(repo, {})
        result[repo] = {
            "total_items_processed": mm.get("total_items_processed", 0),
            "total_succeeded": mm.get("total_succeeded", 0),
            "total_failed": mm.get("total_failed", 0),
            "success_rate": mm.get("success_rate", 0.0),
            "total_cost": mm.get("total_cost", 0.0),
            "items_created": bm.get("total_created", 0),
            "items_completed": bm.get("total_completed", 0),
            "net_items_delta": bm.get("net_delta", 0),
        }
    return result
