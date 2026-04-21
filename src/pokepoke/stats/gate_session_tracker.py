"""Persistent tracking for fresh vs resumed gate sessions."""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pokepoke.stats.persistent_json_store import PersistentJsonStore

logger = logging.getLogger(__name__)

GATE_SESSION_STATS_FILE = Path(".pokepoke") / "gate_session_stats.json"

_gate_session_thread_lock = threading.Lock()
_GATE_SESSION_STATS_FILE_LOCK = "gate-session-stats-file"
_MAX_LOG_ENTRIES = 500


@dataclass(frozen=True)
class GateSessionCheck:
    gate_model: str
    item_id: str
    passed: bool
    resumed: bool
    input_tokens: int = 0
    output_tokens: int = 0
    reason: str = ""


def _empty_gate_session_store() -> dict[str, Any]:
    return {"log": [], "summary": {}}


def _normalize_gate_session_store(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict) or "log" not in data:
        return _empty_gate_session_store()
    return data


_STORE = PersistentJsonStore(
    default_path=GATE_SESSION_STATS_FILE,
    empty=_empty_gate_session_store,
    thread_lock=_gate_session_thread_lock,
    lock_name=_GATE_SESSION_STATS_FILE_LOCK,
    normalize=_normalize_gate_session_store,
)


def _session_variant(resumed: bool) -> str:
    return "resumed" if resumed else "fresh"


def _empty_summary() -> dict[str, Any]:
    return {
        "total_runs": 0,
        "total_passed": 0,
        "total_failed": 0,
        "total_input_tokens": 0,
        "total_output_tokens": 0,
        "average_input_tokens": 0.0,
        "average_output_tokens": 0.0,
        "pass_rate": 0.0,
        "last_used": "",
    }


def _update_summary_incremental(summary: dict[str, dict[str, Any]], entry: dict[str, Any]) -> None:
    variant = entry.get("variant", "fresh")
    if variant not in summary:
        summary[variant] = _empty_summary()

    s = summary[variant]
    s["total_runs"] += 1
    if entry.get("passed") is True:
        s["total_passed"] += 1
    else:
        s["total_failed"] += 1
    s["total_input_tokens"] += int(entry.get("input_tokens", 0) or 0)
    s["total_output_tokens"] += int(entry.get("output_tokens", 0) or 0)
    ts = entry.get("timestamp", "")
    if ts and ts > s["last_used"]:
        s["last_used"] = ts
    if s["total_runs"] > 0:
        s["average_input_tokens"] = round(s["total_input_tokens"] / s["total_runs"], 2)
        s["average_output_tokens"] = round(s["total_output_tokens"] / s["total_runs"], 2)
    decided = s["total_passed"] + s["total_failed"]
    s["pass_rate"] = round(s["total_passed"] / decided, 4) if decided else 0.0


def _rebuild_summary(log: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    summary: dict[str, dict[str, Any]] = {}
    for entry in log:
        _update_summary_incremental(summary, entry)
    return summary


def load_gate_session_stats(path: Path | None = None) -> dict[str, Any]:
    return _STORE.load(path)


def save_gate_session_stats(data: dict[str, Any], path: Path | None = None) -> None:
    _STORE.save(data, path)


def record_gate_session_check(check: GateSessionCheck, path: Path | None = None) -> None:
    from pokepoke.stats.metrics_context import get_current_repo_name

    entry: dict[str, Any] = {
        "gate_model": check.gate_model,
        "item_id": check.item_id,
        "passed": check.passed,
        "variant": _session_variant(check.resumed),
        "input_tokens": int(check.input_tokens),
        "output_tokens": int(check.output_tokens),
        "repo_name": get_current_repo_name(),
        "timestamp": datetime.now(UTC).isoformat(),
    }
    if check.reason:
        entry["reason"] = check.reason

    with _STORE.lock(timeout=60):
        data = load_gate_session_stats(path)
        data["log"].append(entry)
        if len(data["log"]) >= _MAX_LOG_ENTRIES:
            del data["log"][: len(data["log"]) // 2]
        summary = data.get("summary", {})
        _update_summary_incremental(summary, entry)
        data["summary"] = summary
        save_gate_session_stats(data, path)


def get_gate_session_stats(path: Path | None = None) -> dict[str, dict[str, Any]]:
    data = load_gate_session_stats(path)
    raw = data.get("summary", {})
    return dict(raw)


def print_gate_session_leaderboard(path: Path | None = None) -> None:
    stats = get_gate_session_stats(path)
    if not stats:
        return

    logger.info("\n" + "=" * 70)
    logger.info("🔬 Gate Session Comparison (Fresh vs Resumed)")
    logger.info("=" * 70)
    for variant in ("fresh", "resumed"):
        s = stats.get(variant)
        if not s:
            continue
        logger.info(f"\n  {variant.title()}")
        logger.info(
            f"     Runs: {s.get('total_runs', 0)}  |  ✅ {s.get('total_passed', 0)}  "
            f"❌ {s.get('total_failed', 0)}  |  Pass rate: {s.get('pass_rate', 0.0):.0%}"
        )
        logger.info(
            f"     Avg tokens: in {s.get('average_input_tokens', 0.0):.1f} / "
            f"out {s.get('average_output_tokens', 0.0):.1f}  |  Last: {str(s.get('last_used', 'never'))[:19]}"
        )
    logger.info("\n" + "=" * 70)
