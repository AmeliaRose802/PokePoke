"""Per-gate-model rejection rate tracking.

Records gate agent pass/fail outcomes per model to track rejection rates,
identify strict vs lenient gate models, and surface trends over time.

Stores data in .pokepoke/gate_rejection_stats.json with an append-log
of check results plus a computed per-model summary.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pokepoke.utils.file_utils import replace_with_retry
from pokepoke.worktrees.coordination import acquire_lock

logger = logging.getLogger(__name__)

GATE_STATS_FILE = Path(".pokepoke") / "gate_rejection_stats.json"

_gate_thread_lock = threading.Lock()
_GATE_STATS_FILE_LOCK = "gate-stats-file"


# ── Data helpers ─────────────────────────────────────────────────────

def _empty_gate_store() -> dict[str, Any]:
    """Return an empty gate rejection stats store structure."""
    return {"log": [], "summary": {}}


def load_gate_stats(path: Path | None = None) -> dict[str, Any]:
    """Load the persistent gate rejection stats from disk."""
    stats_path = path or GATE_STATS_FILE
    if not stats_path.exists():
        return _empty_gate_store()
    try:
        with stats_path.open(encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict) or "log" not in data:
            return _empty_gate_store()
        return data
    except (json.JSONDecodeError, OSError):
        return _empty_gate_store()


def save_gate_stats(data: dict[str, Any], path: Path | None = None) -> None:
    """Atomically persist gate rejection stats to disk."""
    stats_path = path or GATE_STATS_FILE
    stats_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = stats_path.with_suffix(".tmp")
    with tmp_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.flush()
        with suppress(OSError):
            os.fsync(f.fileno())
    replace_with_retry(tmp_path, stats_path)


def _rebuild_gate_summary(log: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Recompute per-gate-model summary from the raw log entries."""
    buckets: dict[str, dict[str, Any]] = {}
    for entry in log:
        model = entry.get("gate_model", "unknown")
        if model not in buckets:
            buckets[model] = {
                "total_checks": 0, "total_passed": 0, "total_rejected": 0,
                "rejection_rate": 0.0, "last_used": "", "trend": [],
            }
        s = buckets[model]
        s["total_checks"] += 1
        if entry.get("passed") is True:
            s["total_passed"] += 1
        else:
            s["total_rejected"] += 1
        ts = entry.get("timestamp", "")
        if ts and ts > s["last_used"]:
            s["last_used"] = ts
        s["trend"].append({"timestamp": ts, "passed": entry.get("passed", False)})
        s["trend"] = s["trend"][-50:]

    for s in buckets.values():
        if s["total_checks"] > 0:
            s["rejection_rate"] = round(s["total_rejected"] / s["total_checks"], 4)

    return buckets


def _update_gate_summary_incremental(
    summary: dict[str, dict[str, Any]], entry: dict[str, Any],
) -> None:
    """Fold a single gate check entry into the existing summary."""
    model = entry.get("gate_model", "unknown")
    if model not in summary:
        summary[model] = {
            "total_checks": 0, "total_passed": 0, "total_rejected": 0,
            "rejection_rate": 0.0, "last_used": "", "trend": [],
        }

    s = summary[model]
    s["total_checks"] += 1
    if entry.get("passed") is True:
        s["total_passed"] += 1
    else:
        s["total_rejected"] += 1

    ts = entry.get("timestamp", "")
    if ts and ts > s["last_used"]:
        s["last_used"] = ts

    s["trend"].append({"timestamp": ts, "passed": entry.get("passed", False)})
    s["trend"] = s["trend"][-50:]

    if s["total_checks"] > 0:
        s["rejection_rate"] = round(s["total_rejected"] / s["total_checks"], 4)


# ── Public API ───────────────────────────────────────────────────────

def record_gate_check(
    gate_model: str, item_id: str, passed: bool, path: Path | None = None,
) -> None:
    """Record a gate agent check result for per-gate-model rejection rate tracking.

    Thread-safe and process-safe.
    """
    from pokepoke.stats.metrics_context import get_current_repo_name

    entry = {
        "gate_model": gate_model, "item_id": item_id, "passed": passed,
        "repo_name": get_current_repo_name(),
        "timestamp": datetime.now(UTC).isoformat(),
    }

    with _gate_thread_lock, acquire_lock(_GATE_STATS_FILE_LOCK, timeout=60):
        data = load_gate_stats(path)
        data["log"].append(entry)
        summary = data.get("summary", {})
        _update_gate_summary_incremental(summary, entry)
        data["summary"] = summary
        save_gate_stats(data, path)


def get_gate_rejection_stats(path: Path | None = None) -> dict[str, dict[str, Any]]:
    """Return per-gate-model rejection rate statistics."""
    data = load_gate_stats(path)
    raw: dict[str, dict[str, Any]] = data.get("summary", {})
    return dict(raw)


def print_gate_rejection_leaderboard(path: Path | None = None) -> None:
    """Print a human-readable report of gate rejection rates per model."""
    stats = get_gate_rejection_stats(path)
    if not stats:
        return

    logger.info("\n" + "=" * 70)
    logger.info("🕵️ Gate Agent Rejection Rates (Per Model)")
    logger.info("=" * 70)

    ranked = sorted(
        stats.items(),
        key=lambda kv: (kv[1].get("rejection_rate", 0), kv[1].get("total_checks", 0)),
        reverse=True,
    )

    for i, (model, s) in enumerate(ranked, 1):
        total = s.get("total_checks", 0)
        passed = s.get("total_passed", 0)
        rejected = s.get("total_rejected", 0)
        rate = s.get("rejection_rate", 0.0)
        last = s.get("last_used", "never")
        trend_str = _format_trend(s.get("trend", []))

        logger.info(f"\n  #{i} {model[:30]}")
        logger.error(f"     Checks: {total}  |  ✅ {passed}  ❌ {rejected}  |  Rejection rate: {rate:.0%}")
        logger.info(f"     Last used: {last[:19]}")
        if trend_str:
            logger.info(f"     Trend:     {trend_str}")
    logger.info("\n" + "=" * 70)


def _format_trend(trend_data: list[dict[str, Any]], max_markers: int = 20) -> str:
    """Format recent trend data as a compact visual string."""
    if not trend_data:
        return ""
    recent = trend_data[-max_markers:]
    return "".join("✓" if e.get("passed") else "✗" for e in recent)
