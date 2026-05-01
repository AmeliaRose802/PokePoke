"""Live quality-gate step tracking for desktop UI visualization.

Tracks the progression of the work-agent → cleanup → gate-agent → retry loop
as documented in docs/quality-gate-validation.md.  Each step has a status
(pending/active/done/failed/skipped) and a log buffer for drill-down.

Thread-safe: a single global tracker is shared by the orchestration loop
and the desktop API poll loop.

Reuses the same data shapes as merge_step_tracker so the frontend
MergeFlowchartView component renders both flows identically.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any

from pokepoke.worktrees.merge_step_tracker import MergeStepStatus

# ── Canonical step IDs matching docs/quality-gate-validation.md ──────

GATE_STEPS: list[dict[str, str]] = [
    {"id": "0", "label": "Work agent invoked"},
    {"id": "1", "label": "Work agent running"},
    {"id": "2", "label": "Work agent result"},
    {"id": "FF", "label": "Fail-fast outcome"},
    {"id": "3", "label": "Cleanup phase"},
    {"id": "4", "label": "Gate agent enabled?"},
    {"id": "5", "label": "Invoke gate agent"},
    {"id": "5T", "label": "Gate timeout retry"},
    {"id": "5C", "label": "Gate crash retry"},
    {"id": "6", "label": "Gate result"},
    {"id": "7", "label": "Build corrective feedback"},
    {"id": "8", "label": "Retry work agent"},
    {"id": "MAX", "label": "Max rejections — defer"},
    {"id": "DONE", "label": "Gate approved — merge"},
]

GATE_EDGES: list[dict[str, str]] = [
    {"from": "0", "to": "1"},
    {"from": "1", "to": "2"},
    {"from": "2", "to": "FF", "label": "Fail-fast"},
    {"from": "2", "to": "3", "label": "Success"},
    {"from": "3", "to": "4"},
    {"from": "4", "to": "DONE", "label": "Disabled"},
    {"from": "4", "to": "5", "label": "Enabled"},
    {"from": "5", "to": "5T", "label": "Timeout"},
    {"from": "5", "to": "5C", "label": "Crash"},
    {"from": "5", "to": "6"},
    {"from": "5T", "to": "5"},
    {"from": "5C", "to": "5"},
    {"from": "6", "to": "DONE", "label": "Approved"},
    {"from": "6", "to": "7", "label": "Rejected"},
    {"from": "7", "to": "MAX", "label": "Max reached"},
    {"from": "7", "to": "8", "label": "Retry"},
    {"from": "8", "to": "1"},
]


@dataclass
class GateStepState:
    """State of a single gate-flow step."""

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
            "logs": list(self.logs[-50:]),
        }


@dataclass
class GateFlowRun:
    """A single gate-flow run's state."""

    agent_id: str
    item_id: str
    started_at: float = field(default_factory=time.time)
    ended_at: float | None = None
    outcome: str = "in_progress"  # "in_progress", "success", "failed"
    iteration: int = 1
    gate_rejections: int = 0
    steps: dict[str, GateStepState] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.steps:
            for step_def in GATE_STEPS:
                self.steps[step_def["id"]] = GateStepState(
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
            "iteration": self.iteration,
            "gate_rejections": self.gate_rejections,
            "steps": {sid: s.to_dict() for sid, s in self.steps.items()},
        }


class GateStepTracker:
    """Thread-safe tracker for the quality-gate workflow visualization."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._current_run: GateFlowRun | None = None
        self._last_completed_run: GateFlowRun | None = None

    def begin_run(self, agent_id: str, item_id: str) -> None:
        with self._lock:
            if self._current_run is not None:
                self._last_completed_run = self._current_run
            self._current_run = GateFlowRun(agent_id=agent_id, item_id=item_id)

    def set_iteration(self, iteration: int) -> None:
        with self._lock:
            if self._current_run:
                self._current_run.iteration = iteration

    def set_gate_rejections(self, count: int) -> None:
        with self._lock:
            if self._current_run:
                self._current_run.gate_rejections = count

    def begin_step(self, step_id: str, log: str | None = None) -> None:
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

    def finish_run(self, outcome: str) -> None:
        with self._lock:
            run = self._current_run
            if run is None:
                return
            run.ended_at = time.time()
            run.outcome = outcome
            self._last_completed_run = run
            self._current_run = None

    def get_state(self) -> dict[str, Any]:
        with self._lock:
            current = self._current_run.to_dict() if self._current_run else None
            last = self._last_completed_run.to_dict() if self._last_completed_run else None
        return {
            "current_run": current,
            "last_completed_run": last,
            "steps_definition": GATE_STEPS,
            "edges": GATE_EDGES,
        }

    # ── Convenience multi-step transitions ───────────────────────────

    def mark_success(self, *step_ids: str) -> None:
        """Complete multiple steps then finish the run as success."""
        for sid in step_ids:
            self.complete_step(sid)
        self.complete_step("DONE")
        self.finish_run("success")

    def mark_failure(self, step_id: str, log: str | None = None) -> None:
        """Fail a single step then finish the run as failed."""
        self.fail_step(step_id, log)
        self.finish_run("failed")

    def start_work(self, agent_id: str, item_id: str, iteration: int, rejections: int) -> None:
        """Begin a new run and mark work agent as starting."""
        self.begin_run(agent_id, item_id)
        self.set_iteration(iteration)
        self.set_gate_rejections(rejections)
        self.begin_step("0")

    def work_done(self) -> None:
        """Mark work agent invocation and result steps as done."""
        self.complete_step("0")
        self.complete_step("1")
        self.begin_step("2")

    def item_closed(self) -> None:
        """Mark flow as complete when agent already closed the item."""
        self.complete_step("2")
        self.skip_step("3")
        self.skip_step("4")
        self.mark_success()

    def cleanup_done(self) -> None:
        """Mark cleanup and gate-check steps as entering gate phase."""
        self.complete_step("2")
        self.begin_step("3")

    def gate_disabled(self) -> None:
        """Mark gate as disabled → skip and succeed."""
        self.complete_step("4")
        self.skip_step("5")
        self.mark_success()

    def gate_start(self) -> None:
        """Mark gate as enabled and begin gate invocation."""
        self.complete_step("4")
        self.begin_step("5")

    def gate_rejected_retry(self, rejections: int, reason: str) -> None:
        """Record a gate rejection that will be retried."""
        self.complete_step("5")
        self.fail_step("6", f"Rejected: {reason[:100]}")
        self.begin_step("7")
        self.complete_step("7")
        self.begin_step("8")
        self.complete_step("8")
        self.set_gate_rejections(rejections)
        self.finish_run("failed")

    def gate_rejected_max(self, rejections: int) -> None:
        """Record a gate rejection that hit the max cap."""
        self.begin_step("7")
        self.mark_failure("MAX")


# ── Module-level singleton ──────────────────────────────────────────

_tracker: GateStepTracker | None = None
_tracker_lock = threading.Lock()


def get_gate_step_tracker() -> GateStepTracker:
    """Return the global GateStepTracker singleton."""
    global _tracker
    if _tracker is None:
        with _tracker_lock:
            if _tracker is None:
                _tracker = GateStepTracker()
    return _tracker
