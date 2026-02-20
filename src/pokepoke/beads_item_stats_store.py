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
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pokepoke.coordination import acquire_lock

STATS_FILE = Path(".pokepoke") / "beads_item_stats.json"

_thread_lock = threading.Lock()
_STATS_FILE_LOCK = "beads-item-stats-file"

EventType = Literal["created", "completed"]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


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
    total_created = 0
    total_completed = 0
    by_agent: dict[str, dict[str, int]] = {}

    for entry in log:
        event = entry.get("event")
        agent = entry.get("agent_type") or "unknown"
        if agent not in by_agent:
            by_agent[agent] = {"created": 0, "completed": 0}

        if event == "created":
            total_created += 1
            by_agent[agent]["created"] += 1
        elif event == "completed":
            total_completed += 1
            by_agent[agent]["completed"] += 1

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


def load_beads_item_stats(path: Path | None = None) -> dict[str, Any]:
    stats_path = path or STATS_FILE
    if not stats_path.exists():
        return _empty_store()

    try:
        with open(stats_path, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict) or "log" not in data:
            return _empty_store()
        if not isinstance(data.get("log"), list):
            return _empty_store()
        return data
    except (json.JSONDecodeError, OSError):
        return _empty_store()


def save_beads_item_stats(data: dict[str, Any], path: Path | None = None) -> None:
    stats_path = path or STATS_FILE
    stats_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = stats_path.with_suffix(".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    # Retry os.replace on Windows where the destination file may be briefly
    # locked by a previous operation, causing PermissionError.
    _replace_with_retry(tmp_path, stats_path)


def _replace_with_retry(src: Path, dst: Path, retries: int = 5, delay: float = 0.05) -> None:
    """Replace *dst* with *src*, retrying on PermissionError (Windows)."""
    for attempt in range(retries):
        try:
            os.replace(str(src), str(dst))
            return
        except PermissionError:
            if attempt == retries - 1:
                raise
            time.sleep(delay * (2 ** attempt))


def record_event(
    event: EventType,
    item_id: str,
    agent_type: str = "unknown",
    *,
    path: Path | None = None,
) -> dict[str, Any]:
    """Record a created/completed event and return the updated summary."""
    entry = {
        "event": event,
        "item_id": item_id,
        "agent_type": agent_type or "unknown",
        "timestamp": _now_iso(),
    }

    with _thread_lock:
        with acquire_lock(_STATS_FILE_LOCK):
            data = load_beads_item_stats(path)
            data["log"].append(entry)
            data["summary"] = _rebuild_summary(data["log"])
            save_beads_item_stats(data, path)
            summary: dict[str, Any] = data.get("summary", {})
            return summary


def record_item_created(item_id: str, agent_type: str = "unknown", *, path: Path | None = None) -> dict[str, Any]:
    return record_event("created", item_id, agent_type, path=path)


def record_item_completed(item_id: str, agent_type: str = "unknown", *, path: Path | None = None) -> dict[str, Any]:
    return record_event("completed", item_id, agent_type, path=path)


def get_summary(path: Path | None = None) -> dict[str, Any]:
    data = load_beads_item_stats(path)
    summary: dict[str, Any] = data.get("summary", {})
    if not isinstance(summary, dict):
        return _empty_store()["summary"]
    return summary
