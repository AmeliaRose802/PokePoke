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
  },
  "items": {
    "PokePoke-abc": {
      "attempt_count": int,
      "total_tokens": int,
      "total_duration_seconds": float,
      "first_attempted": "<iso-timestamp>",
      "last_attempted": "<iso-timestamp>",
      "last_result": "success" | "failed",
      "consecutive_failures": int,
      "needs_human_attention": bool,
      "failure_reasons": ["reason1", ...]
    }
  }
}

The raw log is append-only; summary can be rebuilt at any time.
Per-item metrics in "items" are updated incrementally on each attempt.
"""

import os
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pokepoke.constants import DEFAULT_NEEDS_HUMAN_ATTENTION_FAILURES
from pokepoke.stats.persistent_json_store import PersistentJsonStore

STATS_FILE = Path(".pokepoke") / "beads_item_stats.json"

_thread_lock = threading.Lock()
_STATS_FILE_LOCK = "beads-item-stats-file"

EventType = Literal["created", "completed", "failed"]


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _empty_store() -> dict[str, Any]:
    return {
        "log": [],
        "summary": {
            "total_created": 0,
            "total_completed": 0,
            "total_failed": 0,
            "net_delta": 0,
            "by_agent_type": {},
            "last_updated": "",
        },
        "items": {},
    }


def _rebuild_summary(log: list[dict[str, Any]]) -> dict[str, Any]:
    """Rebuild summary from log entries.

    Counts unique items (deduplicates by item_id + event type to prevent
    duplicate event recording from inflating counts).
    Failed events are NOT deduplicated — each attempt is counted so the
    total reflects the real number of failures across retries.
    """
    created_items: set[str] = set()
    completed_items: set[str] = set()
    total_failed = 0
    by_agent: dict[str, dict[str, int]] = {}

    for entry in log:
        event = entry.get("event")
        item_id = entry.get("item_id")
        agent = entry.get("agent_type") or "unknown"

        if not item_id:
            continue

        if agent not in by_agent:
            by_agent[agent] = {"created": 0, "completed": 0, "failed": 0}

        if event == "created" and item_id not in created_items:
            created_items.add(item_id)
            by_agent[agent]["created"] += 1
        elif event == "completed" and item_id not in completed_items:
            completed_items.add(item_id)
            by_agent[agent]["completed"] += 1
        elif event == "failed":
            total_failed += 1
            by_agent[agent]["failed"] += 1

    total_created = len(created_items)
    total_completed = len(completed_items)

    by_agent_out: dict[str, dict[str, int]] = {}
    for agent, counts in by_agent.items():
        created = int(counts.get("created", 0))
        completed = int(counts.get("completed", 0))
        failed = int(counts.get("failed", 0))
        by_agent_out[agent] = {
            "created": created,
            "completed": completed,
            "failed": failed,
            "net_delta": created - completed,
        }

    return {
        "total_created": total_created,
        "total_completed": total_completed,
        "total_failed": total_failed,
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


def _normalize_store(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict) or "log" not in data:
        return _empty_store()
    if not isinstance(data.get("log"), list):
        return _empty_store()
    # Ensure "items" key exists (migration for stores created before quality scoring)
    if "items" not in data or not isinstance(data.get("items"), dict):
        data["items"] = {}
    return data


_STORE = PersistentJsonStore(
    default_path=STATS_FILE,
    empty=_empty_store,
    thread_lock=_thread_lock,
    lock_name_resolver=_resolve_lock_name,
    path_resolver=_resolve_stats_path,
    normalize=_normalize_store,
)


def load_beads_item_stats(path: Path | None = None) -> dict[str, Any]:
    return _STORE.load(path)


def save_beads_item_stats(data: dict[str, Any], path: Path | None = None) -> None:
    _STORE.save(data, path)


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

    with _STORE.lock(timeout=60):
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


def record_item_failed(
    item_id: str,
    agent_type: str = "unknown",
    *,
    path: Path | None = None,
    repo_name: str = "",
) -> dict[str, Any]:
    """Record that an item processing attempt failed."""
    return record_event("failed", item_id, agent_type, path=path, repo_name=repo_name)


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


# ── Per-item quality metrics ─────────────────────────────────────────────────

_MAX_FAILURE_REASONS = 10  # Cap stored failure reasons per item


def _empty_item_metrics() -> dict[str, Any]:
    """Return a fresh per-item metrics dict."""
    return {
        "attempt_count": 0,
        "total_tokens": 0,
        "total_duration_seconds": 0.0,
        "first_attempted": "",
        "last_attempted": "",
        "last_result": "",
        "consecutive_failures": 0,
        "needs_human_attention": False,
        "failure_reasons": [],
    }


def record_item_attempt(
    item_id: str,
    *,
    success: bool,
    tokens_used: int = 0,
    duration_seconds: float = 0.0,
    failure_reason: str | None = None,
    attention_threshold: int = DEFAULT_NEEDS_HUMAN_ATTENTION_FAILURES,
    path: Path | None = None,
) -> dict[str, Any]:
    """Record a processing attempt for a specific item and return its updated metrics.

    Updates per-item counters (attempt_count, tokens, duration) and manages
    the ``needs_human_attention`` flag based on consecutive failures.
    """
    now = _now_iso()

    with _STORE.lock(timeout=60):
        data = load_beads_item_stats(path)
        items: dict[str, Any] = data.setdefault("items", {})
        metrics = items.get(item_id)
        if not isinstance(metrics, dict):
            metrics = _empty_item_metrics()

        metrics["attempt_count"] = int(metrics.get("attempt_count", 0)) + 1
        metrics["total_tokens"] = int(metrics.get("total_tokens", 0)) + max(0, tokens_used)
        metrics["total_duration_seconds"] = (
            float(metrics.get("total_duration_seconds", 0.0)) + max(0.0, duration_seconds)
        )
        if not metrics.get("first_attempted"):
            metrics["first_attempted"] = now
        metrics["last_attempted"] = now

        if success:
            metrics["last_result"] = "success"
            metrics["consecutive_failures"] = 0
            metrics["needs_human_attention"] = False
        else:
            metrics["last_result"] = "failed"
            metrics["consecutive_failures"] = int(metrics.get("consecutive_failures", 0)) + 1
            if failure_reason:
                reasons = metrics.get("failure_reasons", [])
                if not isinstance(reasons, list):
                    reasons = []
                reasons.append(failure_reason)
                if len(reasons) > _MAX_FAILURE_REASONS:
                    reasons = reasons[-_MAX_FAILURE_REASONS:]
                metrics["failure_reasons"] = reasons
            if metrics["consecutive_failures"] >= attention_threshold:
                metrics["needs_human_attention"] = True

        items[item_id] = metrics
        data["items"] = items
        save_beads_item_stats(data, path)
        return dict(metrics)

