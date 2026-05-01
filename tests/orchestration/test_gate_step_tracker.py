"""Tests for the GateStepTracker used in quality-gate workflow visualization."""

from pokepoke.orchestration.gate_step_tracker import (
    GATE_EDGES,
    GATE_STEPS,
    GateFlowRun,
    GateStepTracker,
)
from pokepoke.worktrees.merge_step_tracker import MergeStepStatus


class TestGateStepTracker:
    """Tests for GateStepTracker lifecycle and state serialization."""

    def test_initial_state_empty(self) -> None:
        tracker = GateStepTracker()
        state = tracker.get_state()
        assert state["current_run"] is None
        assert state["last_completed_run"] is None
        assert len(state["steps_definition"]) == len(GATE_STEPS)
        assert len(state["edges"]) == len(GATE_EDGES)

    def test_begin_run_creates_steps(self) -> None:
        tracker = GateStepTracker()
        tracker.begin_run("agent-1", "item-42")
        state = tracker.get_state()
        assert state["current_run"] is not None
        run = state["current_run"]
        assert run["agent_id"] == "agent-1"
        assert run["item_id"] == "item-42"
        assert run["outcome"] == "in_progress"
        for step_def in GATE_STEPS:
            assert step_def["id"] in run["steps"]
            assert run["steps"][step_def["id"]]["status"] == "pending"

    def test_step_transitions(self) -> None:
        tracker = GateStepTracker()
        tracker.begin_run("a1", "i1")

        tracker.begin_step("0", "Starting work agent")
        state = tracker.get_state()
        step = state["current_run"]["steps"]["0"]
        assert step["status"] == "active"
        assert "Starting work agent" in step["logs"]

        tracker.complete_step("0", "Done")
        state = tracker.get_state()
        step = state["current_run"]["steps"]["0"]
        assert step["status"] == "done"

    def test_fail_step(self) -> None:
        tracker = GateStepTracker()
        tracker.begin_run("a1", "i1")
        tracker.begin_step("2")
        tracker.fail_step("2", "Copilot crashed")
        state = tracker.get_state()
        assert state["current_run"]["steps"]["2"]["status"] == "failed"

    def test_skip_step(self) -> None:
        tracker = GateStepTracker()
        tracker.begin_run("a1", "i1")
        tracker.skip_step("5", "Gate disabled")
        state = tracker.get_state()
        assert state["current_run"]["steps"]["5"]["status"] == "skipped"

    def test_set_iteration_and_gate_rejections(self) -> None:
        tracker = GateStepTracker()
        tracker.begin_run("a1", "i1")
        tracker.set_iteration(3)
        tracker.set_gate_rejections(2)
        state = tracker.get_state()
        assert state["current_run"]["iteration"] == 3
        assert state["current_run"]["gate_rejections"] == 2

    def test_finish_run_archives(self) -> None:
        tracker = GateStepTracker()
        tracker.begin_run("a1", "i1")
        tracker.complete_step("0")
        tracker.finish_run("success")
        state = tracker.get_state()
        assert state["current_run"] is None
        assert state["last_completed_run"] is not None
        assert state["last_completed_run"]["outcome"] == "success"

    def test_new_run_replaces_current(self) -> None:
        tracker = GateStepTracker()
        tracker.begin_run("a1", "i1")
        tracker.finish_run("success")
        tracker.begin_run("a2", "i2")
        state = tracker.get_state()
        assert state["current_run"]["agent_id"] == "a2"
        assert state["last_completed_run"]["agent_id"] == "a1"

    def test_operations_on_no_run_are_noop(self) -> None:
        tracker = GateStepTracker()
        tracker.begin_step("0")
        tracker.complete_step("0")
        tracker.fail_step("0")
        tracker.skip_step("0")
        tracker.finish_run("failed")

    def test_skip_step_with_log(self) -> None:
        tracker = GateStepTracker()
        tracker.begin_run("a1", "i1")
        tracker.skip_step("0", log="skipped reason")
        state = tracker.get_state()
        step = state["current_run"]["steps"]["0"]
        assert step["status"] == "skipped"
        assert "skipped reason" in step["logs"]

    def test_fail_step_records_status(self) -> None:
        tracker = GateStepTracker()
        tracker.begin_run("a1", "i1")
        tracker.begin_step("0")
        tracker.fail_step("0", log="error detail")
        state = tracker.get_state()
        step = state["current_run"]["steps"]["0"]
        assert step["status"] == "failed"
        assert "error detail" in step["logs"]

    def test_get_state_serialization(self) -> None:
        tracker = GateStepTracker()
        tracker.begin_run("a1", "i1")
        tracker.begin_step("0")
        tracker.complete_step("0")
        tracker.finish_run("success")
        state = tracker.get_state()
        assert state["last_completed_run"]["outcome"] == "success"
        assert state["last_completed_run"]["agent_id"] == "a1"
        assert "steps" in state["last_completed_run"]
        assert "started_at" in state["last_completed_run"]

class TestGateFlowRun:
    def test_to_dict_has_iteration_and_rejections(self) -> None:
        run = GateFlowRun(agent_id="a1", item_id="i1", iteration=2, gate_rejections=1)
        d = run.to_dict()
        assert d["iteration"] == 2
        assert d["gate_rejections"] == 1
        assert len(d["steps"]) == len(GATE_STEPS)


class TestConvenienceMethods:
    """Tests for multi-step convenience methods."""

    def test_mark_success_completes_steps_and_finishes(self) -> None:
        tracker = GateStepTracker()
        tracker.begin_run("a1", "i1")
        tracker.mark_success("0", "1")
        state = tracker.get_state()
        assert state["current_run"] is None
        assert state["last_completed_run"]["outcome"] == "success"

    def test_mark_failure_fails_step_and_finishes(self) -> None:
        tracker = GateStepTracker()
        tracker.begin_run("a1", "i1")
        tracker.mark_failure("0", "error detail")
        state = tracker.get_state()
        assert state["last_completed_run"]["outcome"] == "failed"

    def test_start_work_begins_run_and_first_step(self) -> None:
        tracker = GateStepTracker()
        tracker.start_work("a1", "i1", iteration=3, rejections=1)
        state = tracker.get_state()
        run = state["current_run"]
        assert run["iteration"] == 3
        assert run["gate_rejections"] == 1
        assert run["steps"]["0"]["status"] == "active"

    def test_work_done_completes_work_steps(self) -> None:
        tracker = GateStepTracker()
        tracker.start_work("a1", "i1", iteration=1, rejections=0)
        tracker.work_done()
        state = tracker.get_state()
        assert state["current_run"]["steps"]["0"]["status"] == "done"
        assert state["current_run"]["steps"]["1"]["status"] == "done"

    def test_gate_disabled_skips_gate(self) -> None:
        tracker = GateStepTracker()
        tracker.start_work("a1", "i1", iteration=1, rejections=0)
        tracker.work_done()
        tracker.cleanup_done()
        tracker.gate_disabled()
        state = tracker.get_state()
        assert state["last_completed_run"]["outcome"] == "success"

    def test_gate_rejected_retry(self) -> None:
        tracker = GateStepTracker()
        tracker.start_work("a1", "i1", iteration=1, rejections=0)
        tracker.work_done()
        tracker.cleanup_done()
        tracker.gate_start()
        tracker.gate_rejected_retry(1, "bad code")
        state = tracker.get_state()
        assert state["last_completed_run"]["outcome"] == "failed"
        assert state["last_completed_run"]["gate_rejections"] == 1

    def test_gate_rejected_max(self) -> None:
        tracker = GateStepTracker()
        tracker.start_work("a1", "i1", iteration=1, rejections=5)
        tracker.gate_rejected_max(5)
        state = tracker.get_state()
        assert state["last_completed_run"]["outcome"] == "failed"

    def test_item_closed_skips_gate_steps(self) -> None:
        tracker = GateStepTracker()
        tracker.start_work("a1", "i1", iteration=1, rejections=0)
        tracker.work_done()
        tracker.item_closed()
        state = tracker.get_state()
        assert state["last_completed_run"]["outcome"] == "success"

class TestGateStepDefinitions:
    def test_steps_have_unique_ids(self) -> None:
        ids = [s["id"] for s in GATE_STEPS]
        assert len(ids) == len(set(ids))

    def test_edges_reference_valid_steps(self) -> None:
        valid_ids = {s["id"] for s in GATE_STEPS}
        for edge in GATE_EDGES:
            assert edge["from"] in valid_ids, f"Edge 'from' {edge['from']} not in steps"
            assert edge["to"] in valid_ids, f"Edge 'to' {edge['to']} not in steps"

    def test_step_status_enum_reused(self) -> None:
        """GateStepTracker reuses MergeStepStatus from merge_step_tracker."""
        assert MergeStepStatus.PENDING.value == "pending"
        assert MergeStepStatus.DONE.value == "done"
