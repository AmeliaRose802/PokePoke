"""Persistent model performance statistics store.

Tracks per-model performance data (success rate, duration, retries, etc.)
across sessions in .pokepoke/model_stats.json.  Uses an append-log of raw
completion records plus a computed summary so that raw data is never lost
even on crashes, and the summary can be recalculated at any time.

File layout (.pokepoke/model_stats.json):
{
  "log": [ <ModelCompletionRecord-dicts>, ... ],
  "summary": {
    "<model-name>": {
      "total_items_attempted": int,
      "total_items_succeeded": int,
      "total_items_failed": int,
      "total_duration_seconds": float,
      "total_retries": int,
      "average_duration": float,
      "success_rate": float,           # 0.0–1.0
      "last_used": "<iso-timestamp>"
    }
  }
}
"""

from __future__ import annotations

import json
import os
import statistics
import threading
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pokepoke.worktrees.coordination import acquire_lock
from pokepoke.utils.file_utils import replace_with_retry
from pokepoke.stats.perf_timing import timed_block
from pokepoke.types import ModelCompletionRecord

STATS_FILE = Path(".pokepoke") / "model_stats.json"

# Thread lock for intra-process serialization (fast path)
_thread_lock = threading.Lock()
# Cross-process lock name for file-based coordination
_STATS_FILE_LOCK = "model-stats-file"


# ── Data helpers ─────────────────────────────────────────────────────

def _empty_store() -> dict[str, Any]:
    """Return an empty store structure."""
    return {"log": [], "summary": {}}


def _record_to_dict(record: ModelCompletionRecord) -> dict[str, Any]:
    """Serialise a ModelCompletionRecord to a plain dict."""
    from pokepoke.stats.metrics_context import get_current_repo_name

    return {
        "item_id": record.item_id,
        "model": record.model,
        "duration_seconds": record.duration_seconds,
        "gate_passed": record.gate_passed,
        "input_tokens": record.input_tokens,
        "output_tokens": record.output_tokens,
        "agent_turns": record.agent_turns,
        "cost": record.cost,
        "gate_model": record.gate_model,
        "repo_name": get_current_repo_name(),
        "timestamp": datetime.now(UTC).isoformat(),
    }


def _rebuild_summary(log: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Recompute per-model summary from the raw log entries."""
    # First pass: collect per-model data
    buckets: dict[str, dict[str, Any]] = {}
    for entry in log:
        model = entry.get("model", "unknown")
        if model not in buckets:
            buckets[model] = {
                "total_items_attempted": 0,
                "total_items_succeeded": 0,
                "total_items_failed": 0,
                "total_duration_seconds": 0.0,
                "total_retries": 0,
                "average_duration": 0.0,
                "median_duration": 0.0,
                "stddev_duration": 0.0,
                "success_rate": 0.0,
                "last_used": "",
                "_durations": [],
            }
        s = buckets[model]
        s["total_items_attempted"] += 1
        gp = entry.get("gate_passed")
        if gp is True:
            s["total_items_succeeded"] += 1
        elif gp is False:
            s["total_items_failed"] += 1
        dur = entry.get("duration_seconds", 0.0)
        s["total_duration_seconds"] += dur
        s["_durations"].append(dur)
        ts = entry.get("timestamp", "")
        if ts and ts > s["last_used"]:
            s["last_used"] = ts

    # Second pass: compute derived fields
    summary: dict[str, dict[str, Any]] = {}
    for model, s in buckets.items():
        attempted = s["total_items_attempted"]
        durations = s["_durations"]
        s["average_duration"] = round(s["total_duration_seconds"] / attempted, 2) if attempted else 0.0
        s["median_duration"] = round(statistics.median(durations), 2) if durations else 0.0
        s["stddev_duration"] = round(statistics.pstdev(durations), 2) if len(durations) >= 2 else 0.0
        decided = s["total_items_succeeded"] + s["total_items_failed"]
        s["success_rate"] = round(s["total_items_succeeded"] / decided, 4) if decided else 0.0
        # Keep _durations for incremental updates
        summary[model] = s
    return summary


def _update_summary_incremental(
    summary: dict[str, dict[str, Any]],
    entry: dict[str, Any],
) -> None:
    """Fold a single log entry into the existing summary.

    Unlike ``_rebuild_summary`` which scans the entire log, this only touches
    the single model bucket affected by *entry*.  Per-model ``_durations``
    lists are kept in the summary so that median/stddev can be recomputed
    from the per-model data (much smaller than the full cross-model log).
    """
    model = entry.get("model", "unknown")

    if model not in summary:
        summary[model] = {
            "total_items_attempted": 0,
            "total_items_succeeded": 0,
            "total_items_failed": 0,
            "total_duration_seconds": 0.0,
            "total_retries": 0,
            "average_duration": 0.0,
            "median_duration": 0.0,
            "stddev_duration": 0.0,
            "success_rate": 0.0,
            "last_used": "",
            "_durations": [],
        }

    s = summary[model]

    # Ensure _durations exists (migration from old format)
    if "_durations" not in s:
        s["_durations"] = []

    s["total_items_attempted"] += 1
    gp = entry.get("gate_passed")
    if gp is True:
        s["total_items_succeeded"] += 1
    elif gp is False:
        s["total_items_failed"] += 1

    dur = entry.get("duration_seconds", 0.0)
    s["total_duration_seconds"] += dur
    s["_durations"].append(dur)

    ts = entry.get("timestamp", "")
    if ts and ts > s["last_used"]:
        s["last_used"] = ts

    # Recompute derived fields for this model only
    attempted = s["total_items_attempted"]
    durations = s["_durations"]
    s["average_duration"] = round(s["total_duration_seconds"] / attempted, 2) if attempted else 0.0
    s["median_duration"] = round(statistics.median(durations), 2) if durations else 0.0
    s["stddev_duration"] = round(statistics.pstdev(durations), 2) if len(durations) >= 2 else 0.0
    decided = s["total_items_succeeded"] + s["total_items_failed"]
    s["success_rate"] = round(s["total_items_succeeded"] / decided, 4) if decided else 0.0


# ── Public API ───────────────────────────────────────────────────────

def load_model_stats(path: Path | None = None) -> dict[str, Any]:
    """Load the persistent model stats from disk.

    Returns an empty store if the file does not exist or is corrupt.
    """
    with timed_block("model_stats.load"):
        stats_path = path or STATS_FILE
        if not stats_path.exists():
            return _empty_store()
        try:
            with stats_path.open(encoding="utf-8") as f:
                data = json.load(f)
            # Basic validation
            if not isinstance(data, dict) or "log" not in data:
                return _empty_store()
            return data
        except (json.JSONDecodeError, OSError):
            return _empty_store()


def save_model_stats(data: dict[str, Any], path: Path | None = None) -> None:
    """Atomically persist model stats to disk.

    Writes to a temporary file first then renames, to avoid corruption
    on crashes.
    """
    with timed_block("model_stats.save"):
        stats_path = path or STATS_FILE
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


def record_completion(record: ModelCompletionRecord, path: Path | None = None) -> None:
    """Append a completion record and update the summary.

    Thread-safe and process-safe: uses both a thread lock (fast path) and
    a cross-process file lock to serialize read-modify-write across multiple
    worker processes in multi-agent mode.

    Uses incremental summary update — only the affected model's bucket is
    touched, avoiding O(N) full-log rescans on every call.
    """
    with _thread_lock, acquire_lock(_STATS_FILE_LOCK, timeout=60):
        data = load_model_stats(path)
        entry = _record_to_dict(record)
        data["log"].append(entry)

        summary = data.get("summary", {})

        # Migration: if any model summary lacks _durations (old format),
        # do a one-time full rebuild to populate _durations per model.
        if summary and any("_durations" not in s for s in summary.values()):
            data["summary"] = _rebuild_summary(data["log"])
        else:
            _update_summary_incremental(summary, entry)
            data["summary"] = summary

        save_model_stats(data, path)


def get_model_summary(path: Path | None = None) -> dict[str, dict[str, Any]]:
    """Return the per-model summary dict (read-only).

    Internal fields (prefixed with ``_``) are stripped from the output.
    """
    data = load_model_stats(path)
    raw: dict[str, dict[str, Any]] = data.get("summary", {})
    return {
        model: {k: v for k, v in stats.items() if not k.startswith("_")}
        for model, stats in raw.items()
    }


def get_model_history(
    path: Path | None = None,
    limit: int = 200,
    repo_name: str = "",
) -> list[dict[str, Any]]:
    """Return the most recent completion log entries up to ``limit``.

    If *repo_name* is given, only entries for that repo are returned.
    """
    capped_limit = int(limit)
    if capped_limit <= 0:
        return []
    data = load_model_stats(path)
    log = data.get("log", [])
    if not isinstance(log, list):
        return []
    if repo_name:
        log = [e for e in log if e.get("repo_name", "") == repo_name]
    slice_start = max(0, len(log) - capped_limit)
    return list(log[slice_start:])


def get_model_weights(path: Path | None = None, min_attempts: int = 3) -> dict[str, float]:
    """Compute selection weights based on historical success rate.

    Models with fewer than ``min_attempts`` completions get a neutral
    weight of 1.0 (no bias).  Models with enough history get a weight
    proportional to their success rate, with a floor of 0.1 so that
    even poorly-performing models still get occasional runs.

    Returns:
        Mapping of model name → weight (higher = more likely to be selected).
    """
    summary = get_model_summary(path)
    weights: dict[str, float] = {}
    for model, stats in summary.items():
        attempted = stats.get("total_items_attempted", 0)
        if attempted < min_attempts:
            weights[model] = 1.0
        else:
            rate = stats.get("success_rate", 0.0)
            weights[model] = max(0.1, rate)
    return weights


def print_model_leaderboard(path: Path | None = None) -> None:
    """Print a human-readable leaderboard of model performance."""
    summary = get_model_summary(path)
    if not summary:
        print("📊 No model performance data available yet.")
        return

    print("\n" + "=" * 70)
    print("📊 Model Performance Leaderboard (All-Time)")
    print("=" * 70)

    # Sort by success rate (descending), then by attempts (descending)
    ranked = sorted(
        summary.items(),
        key=lambda kv: (kv[1].get("success_rate", 0), kv[1].get("total_items_attempted", 0)),
        reverse=True,
    )

    for i, (model, s) in enumerate(ranked, 1):
        attempted = s.get("total_items_attempted", 0)
        succeeded = s.get("total_items_succeeded", 0)
        failed = s.get("total_items_failed", 0)
        avg_dur = s.get("average_duration", 0.0)
        median_dur = s.get("median_duration", avg_dur)
        stddev_dur = s.get("stddev_duration", 0.0)
        rate = s.get("success_rate", 0.0)
        last = s.get("last_used", "never")

        # Truncate model name for display
        display_name = model[:30]

        print(f"\n  #{i} {display_name}")
        print(f"     Attempted: {attempted}  |  ✅ {succeeded}  ❌ {failed}  |  Rate: {rate:.0%}")
        print(f"     Median:    {median_dur:.1f}s ±{stddev_dur:.1f}s  |  Avg: {avg_dur:.1f}s  |  Last: {last[:19]}")
    print("\n" + "=" * 70)


def get_model_summary_by_repo(
    path: Path | None = None,
    repo_name: str = "",
) -> dict[str, dict[str, Any]]:
    """Return per-model summary filtered to *repo_name* (empty → global)."""
    if not repo_name:
        return get_model_summary(path)
    data = load_model_stats(path)
    log = data.get("log", [])
    filtered = [e for e in log if e.get("repo_name", "") == repo_name]
    raw = _rebuild_summary(filtered)
    return {
        model: {k: v for k, v in stats.items() if not k.startswith("_")}
        for model, stats in raw.items()
    }


def get_repo_summary_metrics(path: Path | None = None) -> dict[str, dict[str, Any]]:
    """Return per-repo metrics: total_items_processed, success_rate, total_cost."""
    data = load_model_stats(path)
    log = data.get("log", [])

    buckets: dict[str, dict[str, Any]] = {}
    for entry in log:
        repo = entry.get("repo_name", "") or ""
        if repo not in buckets:
            buckets[repo] = {
                "total_items_processed": 0,
                "total_succeeded": 0,
                "total_failed": 0,
                "total_cost": 0.0,
            }
        b = buckets[repo]
        b["total_items_processed"] += 1
        gp = entry.get("gate_passed")
        if gp is True:
            b["total_succeeded"] += 1
        elif gp is False:
            b["total_failed"] += 1
        b["total_cost"] += entry.get("cost", 0.0) or 0.0

    for b in buckets.values():
        decided = b["total_succeeded"] + b["total_failed"]
        b["success_rate"] = round(b["total_succeeded"] / decided, 4) if decided else 0.0
        b["total_cost"] = round(b["total_cost"], 4)

    return buckets
