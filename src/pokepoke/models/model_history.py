"""Per-model work item completion history.

Records an append-only JSONL log at .pokepoke/model_history.jsonl with one
JSON object per completed work item/model pair. This is used for detailed
model performance analysis and routing.
"""

import json
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pokepoke.types import AgentStats, BeadsWorkItem, ModelCompletionRecord

HISTORY_FILE = Path(".pokepoke") / "model_history.jsonl"

_lock = threading.Lock()


def build_model_history_record(
    *,
    item: BeadsWorkItem,
    model_completion: ModelCompletionRecord,
    success: bool,
    request_count: int,
    gate_runs: int,
    item_stats: AgentStats | None = None,
    timestamp: datetime | None = None,
) -> dict[str, Any]:
    """Build a JSON-serialisable dict for a model history entry.

    Args:
        item: The beads work item being processed.
        model_completion: Per-model completion summary from the workflow.
        success: Overall success/failure outcome for the work item.
        request_count: Total Copilot requests (including retries).
        gate_runs: Number of gate agent runs for this item.
        item_stats: Aggregated AgentStats for this item, if available.
        timestamp: Optional explicit timestamp for testing; defaults to now() UTC.
    """
    ts = timestamp or datetime.now(UTC)

    # Retry attempts are total requests minus the first attempt (never negative)
    retry_attempts = request_count - 1 if request_count > 0 else 0

    # Per-item stats may be missing for some failure modes
    wall_time = model_completion.duration_seconds
    api_time = item_stats.api_duration if item_stats is not None else None
    input_tokens = item_stats.input_tokens if item_stats is not None else None
    output_tokens = item_stats.output_tokens if item_stats is not None else None
    lines_added = item_stats.lines_added if item_stats is not None else None
    lines_removed = item_stats.lines_removed if item_stats is not None else None

    # Quality gate metrics
    if gate_runs <= 0:
        quality_gates_ran = False
        quality_gates_passed_first_try: bool | None = None
    else:
        quality_gates_ran = True
        if not success or not model_completion.gate_passed:
            # Either final outcome failed or gate never passed
            quality_gates_passed_first_try = False
        else:
            # Only passes-on-first-try if gate succeeded and ran exactly once
            quality_gates_passed_first_try = gate_runs == 1

    record: dict[str, Any] = {
        "timestamp": ts.isoformat(),
        "model": model_completion.model,
        "work_item_id": item.id,
        "title": item.title,
        "issue_type": item.issue_type,
        "labels": item.labels or [],
        "success": success,
        "retry_attempts": retry_attempts,
        "wall_time_seconds": wall_time,
        "api_time_seconds": api_time,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "lines_added": lines_added,
        "lines_removed": lines_removed,
        "quality_gates_ran": quality_gates_ran,
        "quality_gates_passed": model_completion.gate_passed,
        "quality_gates_passed_first_try": quality_gates_passed_first_try,
    }

    return record


def append_model_history_entry(
    *,
    item: BeadsWorkItem,
    model_completion: ModelCompletionRecord,
    success: bool,
    request_count: int,
    gate_runs: int,
    item_stats: AgentStats | None = None,
    path: Path | None = None,
) -> None:
    """Append a model history entry to .pokepoke/model_history.jsonl.

    This function is append-only and writes exactly one JSON object per line.
    """
    history_path = path or HISTORY_FILE
    history_path.parent.mkdir(parents=True, exist_ok=True)

    record = build_model_history_record(
        item=item,
        model_completion=model_completion,
        success=success,
        request_count=request_count,
        gate_runs=gate_runs,
        item_stats=item_stats,
    )

    line = json.dumps(record, ensure_ascii=False)
    with _lock, history_path.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def load_model_history_entries(
    path: Path | None = None, limit: int = 200, repo_name: str = ""
) -> list[dict[str, Any]]:
    """Load recent model history entries from .pokepoke/model_history.jsonl.

    Returns entries from the JSONL file with full details including labels and issue_type.
    Falls back to empty list if file doesn't exist.

    Args:
        path: Optional path to model_history.jsonl (defaults to HISTORY_FILE).
        limit: Maximum number of recent entries to return (default 200).
        repo_name: If provided, only entries matching this repo are returned.
            The limit is applied *after* filtering so the caller always gets
            up to ``limit`` results for the requested repo.

    Returns:
        List of history entry dicts, most recent last.
    """
    history_path = path or HISTORY_FILE
    if not history_path.exists():
        return []

    entries: list[dict[str, Any]] = []
    try:
        with _lock, history_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    # Skip malformed lines
                    continue
                if repo_name and entry.get("repo_name", "") != repo_name:
                    continue
                entries.append(entry)
    except OSError:
        # File disappeared or unreadable
        return []

    # Return most recent entries up to limit
    if limit > 0 and len(entries) > limit:
        return entries[-limit:]
    return entries
