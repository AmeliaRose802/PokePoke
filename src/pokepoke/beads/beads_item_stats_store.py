"""Persistent beads item created/completed metrics.

Tracks how many beads items agents *create* versus *complete* over time in
`.pokepoke/beads_item_stats.json`.

File layout:
{
  "log": [
    {
      "event": "created" | "completed",
      "item_id": "PokePoke-....",
      "agent_type": "janitor" | "work" | ...,
      "timestamp": "<iso-timestamp>"
    }
  ],
  "summary": {
    "total_created": int,
    "total_completed": int,
    "net_delta": int,
    "by_agent_type": {
      "work": {"created": int, "completed": int, "net_delta": int}
    },
    "last_updated": "<iso-timestamp>"
  }
}

The raw log is append-only; summary can be rebuilt at any time.
"""

from __future__ import annotations

import json
import os
import threading
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pokepoke.worktrees.coordination import acquire_lock
from pokepoke.utils.file_utils import replace_with_retry

STATS_FILE = Path(".pokepoke") / "beads_item_stats.json"

_thread_lock = threading.Lock()
_STATS_FILE_LOCK = "beads-item-stats-file"

EventType = Literal["created", "completed"]


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _empty_store() -> dict[str, Any]:
    return {
        "log": [],
        "summary": {
            "total_created": 0,
            "total_completed": 0,
            "net_delta": 0,
            "by_agent_type": {},
            "last_updated": "",
        },
    }


def _rebuild_summary(log: list[dict[str, Any]]) -> dict[str, Any]:
    """Rebuild summary from log entries.

    Counts unique items (deduplicates by item_id + event type to prevent
    duplicate event recording from inflating counts).
    """
    created_items: set[str] = set()
    completed_items: set[str] = set()
    by_agent: dict[str, dict[str, int]] = {}

    for entry in log:
        event = entry.get("event")
        item_id = entry.get("item_id")
        agent = entry.get("agent_type") or "unknown"

        if not item_id:
            continue

        if agent not in by_agent:
            by_agent[agent] = {"created": 0, "completed": 0}

        if event == "created" and item_id not in created_items:
            created_items.add(item_id)
            by_agent[agent]["created"] += 1
        elif event == "completed" and item_id not in completed_items:
            completed_items.add(item_id)
            by_agent[agent]["completed"] += 1

    total_created = len(created_items)
    total_completed = len(completed_items)

    by_agent_out: dict[str, dict[str, int]] = {}
    for agent, counts in by_agent.items():
        created = int(counts.get("created", 0))
        completed = int(counts.get("completed", 0))
        by_agent_out[agent] = {
            "created": created,
            "completed": completed,
            "net_delta": created - completed,
        }

    return {
        "total_created": total_created,
        "total_completed": total_completed,
        "net_delta": total_created - total_completed,
        "by_agent_type": by_agent_out,
        "last_updated": _now_iso(),
    }


def _resolve_stats_path(path: Path | None = None) -> Path:
    if path is not None:
        return path
    worker = os.environ.get("PYTEST_XDIST_WORKER")
    if worker:
        return Path(".pokepoke") / f"beads_item_stats.{worker}.json"
    return STATS_FILE


def _resolve_lock_name() -> str:
    worker = os.environ.get("PYTEST_XDIST_WORKER")
    if worker:
        return f"{_STATS_FILE_LOCK}-{worker}"
    return _STATS_FILE_LOCK


def load_beads_item_stats(path: Path | None = None) -> dict[str, Any]:
    stats_path = _resolve_stats_path(path)
    if not stats_path.exists():
        return _empty_store()

    try:
        with stats_path.open(encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict) or "log" not in data:
            return _empty_store()
        if not isinstance(data.get("log"), list):
            return _empty_store()
        return data
    except (json.JSONDecodeError, OSError):
        return _empty_store()


def save_beads_item_stats(data: dict[str, Any], path: Path | None = None) -> None:
    stats_path = _resolve_stats_path(path)
    stats_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = stats_path.with_suffix(".tmp")
    with tmp_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.flush()
        with suppress(OSError):
            os.fsync(f.fileno())
    # Retry os.replace on Windows where the destination file may be briefly
    # locked by a previous operation, causing PermissionError.
    replace_with_retry(tmp_path, stats_path)


def record_event(
    event: EventType,
    item_id: str,
    agent_type: str = "unknown",
    *,
    path: Path | None = None,
    repo_name: str = "",
) -> dict[str, Any]:
    """Record a created/completed event and return the updated summary."""
    from pokepoke.stats.metrics_context import get_current_repo_name

    resolved_repo = repo_name or get_current_repo_name()
    entry = {
        "event": event,
        "item_id": item_id,
        "agent_type": agent_type or "unknown",
        "repo_name": resolved_repo,
        "timestamp": _now_iso(),
    }

    lock_name = _resolve_lock_name()
    with _thread_lock, acquire_lock(lock_name, timeout=60):
        data = load_beads_item_stats(path)
        data["log"].append(entry)
        data["summary"] = _rebuild_summary(data["log"])
        save_beads_item_stats(data, path)
        summary: dict[str, Any] = data.get("summary", {})
        return summary


def record_item_created(
    item_id: str,
    agent_type: str = "unknown",
    *,
    path: Path | None = None,
    repo_name: str = "",
) -> dict[str, Any]:
    return record_event("created", item_id, agent_type, path=path, repo_name=repo_name)


def record_item_completed(
    item_id: str,
    agent_type: str = "unknown",
    *,
    path: Path | None = None,
    repo_name: str = "",
) -> dict[str, Any]:
    return record_event("completed", item_id, agent_type, path=path, repo_name=repo_name)


def get_summary(path: Path | None = None) -> dict[str, Any]:
    data = load_beads_item_stats(path)
    summary: dict[str, Any] = data.get("summary", {})
    if not isinstance(summary, dict):
        return _empty_store()["summary"]
    return summary


def get_summary_by_repo(path: Path | None = None) -> dict[str, dict[str, Any]]:
    """Return beads item stats summary segmented by repo name.

    Returns a mapping of ``repo_name`` → summary dict with total_created,
    total_completed, and net_delta.
    """
    data = load_beads_item_stats(path)
    log = data.get("log", [])
    if not isinstance(log, list):
        return {}

    buckets: dict[str, dict[str, set[str]]] = {}
    for entry in log:
        repo = entry.get("repo_name", "") or ""
        item_id = entry.get("item_id")
        event = entry.get("event")
        if not item_id:
            continue
        if repo not in buckets:
            buckets[repo] = {"created": set(), "completed": set()}
        if event == "created":
            buckets[repo]["created"].add(item_id)
        elif event == "completed":
            buckets[repo]["completed"].add(item_id)

    result: dict[str, dict[str, Any]] = {}
    for repo, sets in buckets.items():
        created = len(sets["created"])
        completed = len(sets["completed"])
        result[repo] = {
            "total_created": created,
            "total_completed": completed,
            "net_delta": created - completed,
        }
    return result
