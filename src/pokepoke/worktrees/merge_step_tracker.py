"""Live merge step tracking for desktop UI visualization.

Tracks the progression of merge workflow steps (0–11) as defined in
docs/merge-workflow.md. Each step has a status (pending/active/done/failed/skipped)
and a log buffer for drill-down in the UI.

Thread-safe: a single global tracker is shared by the merge handler and
the desktop API poll loop.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class MergeStepStatus(str, Enum):
    PENDING = "pending"
    ACTIVE = "active"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"


# Canonical step IDs matching docs/merge-workflow.md
# Steps 4 and 5 run before the merge lock (read-only worktree checks).
MERGE_STEPS: list[dict[str, str]] = [
    {"id": "0", "label": "Agent work complete"},
    {"id": "4", "label": "Worktree clean? (pre-lock)"},
    {"id": "5", "label": "Commits on branch? (pre-lock)"},
    {"id": "5a", "label": "Skip merge — cleanup worktree"},
    {"id": "1", "label": "Acquire merge lock"},
    {"id": "2", "label": "Main repo clean?"},
    {"id": "3a", "label": "Auto-commit .beads/"},
    {"id": "3b", "label": "Invoke cleanup agent"},
    {"id": "3c", "label": "Main repo clean now?"},
    {"id": "6", "label": "Sync & prepare main"},
    {"id": "7", "label": "Checkout target branch"},
    {"id": "8", "label": "Merge --no-ff branch"},
    {"id": "8C", "label": "Merge conflict cleanup"},
    {"id": "1r", "label": "Re-acquire merge lock"},
    {"id": "9", "label": "Post-merge validation"},
    {"id": "10", "label": "Worktree remove + branch delete"},
    {"id": "11", "label": "Release merge lock — DONE"},
]


# Edges define the default path through the flowchart.
# The UI renders these as connectors between nodes.
MERGE_EDGES: list[dict[str, str]] = [
    {"from": "0", "to": "4"},
    {"from": "4", "to": "5", "label": "Clean"},
    {"from": "5", "to": "5a", "label": "0 commits"},
    {"from": "5", "to": "1", "label": "≥1 commit"},
    {"from": "5a", "to": "11"},
    {"from": "1", "to": "2"},
    {"from": "2", "to": "3a", "label": "Only .beads/ changes"},
    {"from": "2", "to": "6", "label": "Clean"},
    {"from": "2", "to": "3b", "label": "Non-beads dirty"},
    {"from": "3a", "to": "6"},
    {"from": "3b", "to": "3c"},
    {"from": "3c", "to": "6", "label": "Yes"},
    {"from": "6", "to": "7"},
    {"from": "7", "to": "8"},
    {"from": "8", "to": "9", "label": "Success"},
    {"from": "8", "to": "8C", "label": "Conflict"},
    {"from": "8C", "to": "1r"},
    {"from": "1r", "to": "8"},
    {"from": "9", "to": "10", "label": "Pass"},
    {"from": "10", "to": "11"},
]


@dataclass
class MergeStepState:
    """State of a single merge step."""

    step_id: str
    label: str
    status: MergeStepStatus = MergeStepStatus.PENDING
    started_at: float | None = None
    ended_at: float | None = None
    logs: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "label": self.label,
            "status": self.status.value,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "logs": list(self.logs[-50:]),  # Cap at 50 log lines per step
        }


@dataclass
class MergeFlowRun:
    """A single merge run's state."""

    agent_id: str
    item_id: str
    started_at: float = field(default_factory=time.time)
    ended_at: float | None = None
    outcome: str = "in_progress"  # "in_progress", "success", "failed"
    steps: dict[str, MergeStepState] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.steps:
            for step_def in MERGE_STEPS:
                self.steps[step_def["id"]] = MergeStepState(
                    step_id=step_def["id"],
                    label=step_def["label"],
                )

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "item_id": self.item_id,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "outcome": self.outcome,
            "steps": {sid: s.to_dict() for sid, s in self.steps.items()},
        }


class MergeStepTracker:
    """Thread-safe tracker for live merge workflow visualization.

    Maintains the current (or most recent) merge run, emitting step
    transitions that the desktop UI can poll.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._current_run: MergeFlowRun | None = None
        self._last_completed_run: MergeFlowRun | None = None

    def begin_run(self, agent_id: str, item_id: str) -> None:
        """Start a new merge run, archiving any current run."""
        with self._lock:
            if self._current_run is not None:
                self._last_completed_run = self._current_run
            self._current_run = MergeFlowRun(agent_id=agent_id, item_id=item_id)

    def begin_step(self, step_id: str, log: str | None = None) -> None:
        """Mark a step as active."""
        with self._lock:
            run = self._current_run
            if run is None:
                return
            step = run.steps.get(step_id)
            if step is None:
                return
            step.status = MergeStepStatus.ACTIVE
            step.started_at = time.time()
            if log:
                step.logs.append(log)

    def complete_step(self, step_id: str, log: str | None = None) -> None:
        """Mark a step as done."""
        with self._lock:
            run = self._current_run
            if run is None:
                return
            step = run.steps.get(step_id)
            if step is None:
                return
            step.status = MergeStepStatus.DONE
            step.ended_at = time.time()
            if log:
                step.logs.append(log)

    def fail_step(self, step_id: str, log: str | None = None) -> None:
        """Mark a step as failed."""
        with self._lock:
            run = self._current_run
            if run is None:
                return
            step = run.steps.get(step_id)
            if step is None:
                return
            step.status = MergeStepStatus.FAILED
            step.ended_at = time.time()
            if log:
                step.logs.append(log)

    def skip_step(self, step_id: str, log: str | None = None) -> None:
        """Mark a step as skipped."""
        with self._lock:
            run = self._current_run
            if run is None:
                return
            step = run.steps.get(step_id)
            if step is None:
                return
            step.status = MergeStepStatus.SKIPPED
            if log:
                step.logs.append(log)

    def log_to_step(self, step_id: str, message: str) -> None:
        """Append a log line to a step without changing its status."""
        with self._lock:
            run = self._current_run
            if run is None:
                return
            step = run.steps.get(step_id)
            if step is None:
                return
            step.logs.append(message)

    def finish_run(self, outcome: str) -> None:
        """Finalize the current run with an outcome."""
        with self._lock:
            run = self._current_run
            if run is None:
                return
            run.ended_at = time.time()
            run.outcome = outcome
            self._last_completed_run = run
            self._current_run = None

    def get_state(self) -> dict[str, Any]:
        """Return serializable state for the desktop bridge poll."""
        with self._lock:
            current = self._current_run.to_dict() if self._current_run else None
            last = self._last_completed_run.to_dict() if self._last_completed_run else None

        return {
            "current_run": current,
            "last_completed_run": last,
            "steps_definition": MERGE_STEPS,
            "edges": MERGE_EDGES,
        }


# ── Module-level singleton ──────────────────────────────────────────

_tracker: MergeStepTracker | None = None
_tracker_lock = threading.Lock()


def get_merge_step_tracker() -> MergeStepTracker:
    """Return the global MergeStepTracker singleton."""
    global _tracker
    if _tracker is None:
        with _tracker_lock:
            if _tracker is None:
                _tracker = MergeStepTracker()
    return _tracker
