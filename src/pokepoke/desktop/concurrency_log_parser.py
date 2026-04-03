"""Parse orchestrator.log to extract concurrency timeline data.

Extracts Lifecycle entries (active agent counts over time) and
item completion/failure events for the concurrency chart.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

# Lifecycle: active=3 max=8 slots=5 mem=2048MB rss=150MB cpu=25.3%
_LIFECYCLE_RE = re.compile(
    r"\[(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\] \[(?:INFO|DEBUG)\].*"
    r"Lifecycle: active=(?P<active>\d+) max=(?P<max>\d+) slots=(?P<slots>\d+) mem=(?P<mem>\d+)MB"
    r"(?: rss=(?P<rss>\d+)MB)?"
    r"(?: cpu=(?P<cpu>[\d.]+)%)?"
)

# Worker completed <item_id>  OR  ✅ Agent <name> completed item <item_id>
_COMPLETED_RE = re.compile(
    r"\[(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\] \[(?:INFO)\].*"
    r"(?:Worker completed (?P<wid1>\S+)|"
    r"\u2705 Agent \S+ completed item (?P<wid2>\S+))"
)

# Worker failed <item_id>  OR  ❌ Agent <name> failed item <item_id>
_FAILED_RE = re.compile(
    r"\[(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\] \[(?:INFO|ERROR)\].*"
    r"(?:Worker failed (?P<wid1>\S+)|"
    r"\u274c Agent \S+ (?:failed|raised exception on) item (?P<wid2>\S+))"
)


def parse_concurrency_timeline(log_path: str | Path) -> dict[str, Any]:
    """Parse an orchestrator.log and return concurrency timeline data.

    Returns a dict with:
        lifecycle: list of {ts, active, max, slots, mem, rss?, cpu?}
        completions: list of {ts, item_id}
        failures: list of {ts, item_id}
    """
    log_path = Path(log_path)
    if not log_path.is_file():
        return {"lifecycle": [], "completions": [], "failures": []}

    lifecycle: list[dict[str, Any]] = []
    completions: list[dict[str, str]] = []
    failures: list[dict[str, str]] = []

    seen_completions: set[tuple[str, str]] = set()
    seen_failures: set[tuple[str, str]] = set()

    try:
        with open(log_path, encoding="utf-8", errors="replace") as f:
            for line in f:
                m = _LIFECYCLE_RE.search(line)
                if m:
                    entry: dict[str, Any] = {
                        "ts": m.group("ts"),
                        "active": int(m.group("active")),
                        "max": int(m.group("max")),
                        "slots": int(m.group("slots")),
                        "mem": int(m.group("mem")),
                    }
                    rss_str = m.group("rss")
                    if rss_str is not None:
                        entry["rss"] = int(rss_str)
                    cpu_str = m.group("cpu")
                    if cpu_str is not None:
                        entry["cpu"] = float(cpu_str)
                    lifecycle.append(entry)
                    continue

                m = _COMPLETED_RE.search(line)
                if m:
                    item_id = m.group("wid1") or m.group("wid2")
                    key = (m.group("ts"), item_id)
                    if key not in seen_completions:
                        seen_completions.add(key)
                        completions.append({"ts": m.group("ts"), "item_id": item_id})
                    continue

                m = _FAILED_RE.search(line)
                if m:
                    item_id = m.group("wid1") or m.group("wid2")
                    key = (m.group("ts"), item_id)
                    if key not in seen_failures:
                        seen_failures.add(key)
                        failures.append({"ts": m.group("ts"), "item_id": item_id})
    except OSError:
        pass

    return {
        "lifecycle": lifecycle,
        "completions": completions,
        "failures": failures,
    }
