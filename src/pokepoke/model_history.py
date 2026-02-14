"""Per-model work item completion history.

Records an append-only JSONL log at .pokepoke/model_history.jsonl with one
JSON object per completed work item/model pair. This is used for detailed
model performance analysis and routing.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

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
    item_stats: Optional[AgentStats] = None,
    timestamp: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Build a JSON-serialisable dict for a model history entry.

    Args:
        item: The beads work item being processed.
        model_completion: Per-model completion summary from the workflow.
        success: Overall success/failure outcome for the work item.
        request_count: Total Copilot CLI requests (including retries).
        gate_runs: Number of gate agent runs for this item.
        item_stats: Aggregated AgentStats for this item, if available.
        timestamp: Optional explicit timestamp for testing; defaults to now() UTC.
    """
    ts = timestamp or datetime.now(timezone.utc)

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
        quality_gates_passed_first_try: Optional[bool] = None
    else:
        quality_gates_ran = True
        if not success or not model_completion.gate_passed:
            # Either final outcome failed or gate never passed
            quality_gates_passed_first_try = False
        else:
            # Only passes-on-first-try if gate succeeded and ran exactly once
            quality_gates_passed_first_try = gate_runs == 1

    record: Dict[str, Any] = {
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
    item_stats: Optional[AgentStats] = None,
    path: Optional[Path] = None,
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
    with _lock:
        with open(history_path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
