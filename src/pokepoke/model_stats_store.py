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
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from pokepoke.types import ModelCompletionRecord

STATS_FILE = Path(".pokepoke") / "model_stats.json"

_lock = threading.Lock()


# ── Data helpers ─────────────────────────────────────────────────────

def _empty_store() -> Dict[str, Any]:
    """Return an empty store structure."""
    return {"log": [], "summary": {}}


def _record_to_dict(record: ModelCompletionRecord) -> Dict[str, Any]:
    """Serialise a ModelCompletionRecord to a plain dict."""
    return {
        "item_id": record.item_id,
        "model": record.model,
        "duration_seconds": record.duration_seconds,
        "gate_passed": record.gate_passed,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def _rebuild_summary(log: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Recompute per-model summary from the raw log entries."""
    summary: Dict[str, Dict[str, Any]] = {}
    for entry in log:
        model = entry.get("model", "unknown")
        if model not in summary:
            summary[model] = {
                "total_items_attempted": 0,
                "total_items_succeeded": 0,
                "total_items_failed": 0,
                "total_duration_seconds": 0.0,
                "total_retries": 0,
                "average_duration": 0.0,
                "success_rate": 0.0,
                "last_used": "",
            }
        s = summary[model]
        s["total_items_attempted"] += 1
        gp = entry.get("gate_passed")
        if gp is True:
            s["total_items_succeeded"] += 1
        elif gp is False:
            s["total_items_failed"] += 1
        # If gate_passed is None the item is neither success nor failure
        s["total_duration_seconds"] += entry.get("duration_seconds", 0.0)
        ts = entry.get("timestamp", "")
        if ts and ts > s["last_used"]:
            s["last_used"] = ts
        # Recompute derived fields
        attempted = s["total_items_attempted"]
        s["average_duration"] = round(s["total_duration_seconds"] / attempted, 2) if attempted else 0.0
        decided = s["total_items_succeeded"] + s["total_items_failed"]
        s["success_rate"] = round(s["total_items_succeeded"] / decided, 4) if decided else 0.0
    return summary


# ── Public API ───────────────────────────────────────────────────────

def load_model_stats(path: Optional[Path] = None) -> Dict[str, Any]:
    """Load the persistent model stats from disk.

    Returns an empty store if the file does not exist or is corrupt.
    """
    stats_path = path or STATS_FILE
    if not stats_path.exists():
        return _empty_store()
    try:
        with open(stats_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        # Basic validation
        if not isinstance(data, dict) or "log" not in data:
            return _empty_store()
        return data
    except (json.JSONDecodeError, OSError):
        return _empty_store()


def save_model_stats(data: Dict[str, Any], path: Optional[Path] = None) -> None:
    """Atomically persist model stats to disk.

    Writes to a temporary file first then renames, to avoid corruption
    on crashes.
    """
    stats_path = path or STATS_FILE
    stats_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = stats_path.with_suffix(".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    # Atomic rename (os.replace works on both Windows NTFS and Unix)
    os.replace(str(tmp_path), str(stats_path))


def record_completion(record: ModelCompletionRecord, path: Optional[Path] = None) -> None:
    """Append a completion record and update the summary.

    Thread-safe: uses a module-level lock to serialize read-modify-write.
    """
    with _lock:
        data = load_model_stats(path)
        data["log"].append(_record_to_dict(record))
        data["summary"] = _rebuild_summary(data["log"])
        save_model_stats(data, path)


def record_completions(records: List[ModelCompletionRecord], path: Optional[Path] = None) -> None:
    """Append multiple completion records in a single write.

    More efficient than calling record_completion() in a loop when
    flushing a batch of session records.
    """
    if not records:
        return
    with _lock:
        data = load_model_stats(path)
        for rec in records:
            data["log"].append(_record_to_dict(rec))
        data["summary"] = _rebuild_summary(data["log"])
        save_model_stats(data, path)


def get_model_summary(path: Optional[Path] = None) -> Dict[str, Dict[str, Any]]:
    """Return the per-model summary dict (read-only)."""
    data = load_model_stats(path)
    summary: Dict[str, Dict[str, Any]] = data.get("summary", {})
    return summary


def get_model_weights(path: Optional[Path] = None, min_attempts: int = 3) -> Dict[str, float]:
    """Compute selection weights based on historical success rate.

    Models with fewer than ``min_attempts`` completions get a neutral
    weight of 1.0 (no bias).  Models with enough history get a weight
    proportional to their success rate, with a floor of 0.1 so that
    even poorly-performing models still get occasional runs.

    Returns:
        Mapping of model name → weight (higher = more likely to be selected).
    """
    summary = get_model_summary(path)
    weights: Dict[str, float] = {}
    for model, stats in summary.items():
        attempted = stats.get("total_items_attempted", 0)
        if attempted < min_attempts:
            weights[model] = 1.0
        else:
            rate = stats.get("success_rate", 0.0)
            weights[model] = max(0.1, rate)
    return weights


def print_model_leaderboard(path: Optional[Path] = None) -> None:
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
        rate = s.get("success_rate", 0.0)
        last = s.get("last_used", "never")

        # Truncate model name for display
        display_name = model[:30]

        print(f"\n  #{i} {display_name}")
        print(f"     Attempted: {attempted}  |  ✅ {succeeded}  ❌ {failed}  |  Rate: {rate:.0%}")
        print(f"     Avg time:  {avg_dur:.1f}s  |  Last used: {last[:19]}")

    print("\n" + "=" * 70)
