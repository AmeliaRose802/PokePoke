"""Tests for the MergeStepTracker used in live merge workflow visualization."""

from pokepoke.worktrees.merge_step_tracker import (
    MERGE_EDGES,
    MERGE_STEPS,
    MergeFlowRun,
    MergeStepStatus,
    MergeStepTracker,
)


class TestMergeStepTracker:
    """Tests for MergeStepTracker lifecycle and state serialization."""

    def test_initial_state_empty(self) -> None:
        tracker = MergeStepTracker()
        state = tracker.get_state()
        assert state["current_run"] is None
        assert state["last_completed_run"] is None
        assert len(state["steps_definition"]) == len(MERGE_STEPS)
        assert len(state["edges"]) == len(MERGE_EDGES)

    def test_begin_run_creates_steps(self) -> None:
        tracker = MergeStepTracker()
        tracker.begin_run("agent-1", "item-42")
        state = tracker.get_state()
        assert state["current_run"] is not None
        run = state["current_run"]
        assert run["agent_id"] == "agent-1"
        assert run["item_id"] == "item-42"
        assert run["outcome"] == "in_progress"
        # All canonical steps should be present
        for step_def in MERGE_STEPS:
            assert step_def["id"] in run["steps"]
            assert run["steps"][step_def["id"]]["status"] == "pending"

    def test_step_transitions(self) -> None:
        tracker = MergeStepTracker()
        tracker.begin_run("a1", "i1")

        tracker.begin_step("1", "Starting lock acquisition")
        state = tracker.get_state()
        step = state["current_run"]["steps"]["1"]
        assert step["status"] == "active"
        assert step["started_at"] is not None
        assert "Starting lock acquisition" in step["logs"]

        tracker.complete_step("1", "Lock acquired")
        state = tracker.get_state()
        step = state["current_run"]["steps"]["1"]
        assert step["status"] == "done"
        assert step["ended_at"] is not None
        assert "Lock acquired" in step["logs"]

    def test_fail_step(self) -> None:
        tracker = MergeStepTracker()
        tracker.begin_run("a1", "i1")
        tracker.begin_step("2")
        tracker.fail_step("2", "Dirty files found")
        state = tracker.get_state()
        step = state["current_run"]["steps"]["2"]
        assert step["status"] == "failed"
        assert "Dirty files found" in step["logs"]

    def test_skip_step(self) -> None:
        tracker = MergeStepTracker()
        tracker.begin_run("a1", "i1")
        tracker.skip_step("3a", "Not needed")
        state = tracker.get_state()
        step = state["current_run"]["steps"]["3a"]
        assert step["status"] == "skipped"

    def test_log_to_step(self) -> None:
        tracker = MergeStepTracker()
        tracker.begin_run("a1", "i1")
        tracker.begin_step("8")
        tracker.log_to_step("8", "line 1")
        tracker.log_to_step("8", "line 2")
        state = tracker.get_state()
        assert state["current_run"]["steps"]["8"]["logs"] == ["line 1", "line 2"]

    def test_finish_run_archives_to_last_completed(self) -> None:
        tracker = MergeStepTracker()
        tracker.begin_run("a1", "i1")
        tracker.complete_step("0")
        tracker.finish_run("success")

        state = tracker.get_state()
        assert state["current_run"] is None
        assert state["last_completed_run"] is not None
        assert state["last_completed_run"]["outcome"] == "success"
        assert state["last_completed_run"]["ended_at"] is not None

    def test_new_run_replaces_current(self) -> None:
        tracker = MergeStepTracker()
        tracker.begin_run("a1", "i1")
        tracker.finish_run("success")
        tracker.begin_run("a2", "i2")

        state = tracker.get_state()
        assert state["current_run"]["agent_id"] == "a2"
        assert state["last_completed_run"]["agent_id"] == "a1"

    def test_operations_on_no_run_are_noop(self) -> None:
        tracker = MergeStepTracker()
        # These should not raise
        tracker.begin_step("1")
        tracker.complete_step("1")
        tracker.fail_step("1")
        tracker.skip_step("1")
        tracker.log_to_step("1", "msg")
        tracker.finish_run("failed")

    def test_operations_on_nonexistent_step_are_noop(self) -> None:
        tracker = MergeStepTracker()
        tracker.begin_run("a1", "i1")
        # Invalid step IDs should not raise
        tracker.begin_step("nonexistent")
        tracker.complete_step("nonexistent")
        tracker.fail_step("nonexistent")

    def test_step_log_capped_at_50(self) -> None:
        tracker = MergeStepTracker()
        tracker.begin_run("a1", "i1")
        tracker.begin_step("8")
        for i in range(60):
            tracker.log_to_step("8", f"line {i}")
        state = tracker.get_state()
        logs = state["current_run"]["steps"]["8"]["logs"]
        assert len(logs) == 50
        # Should be the last 50 lines
        assert logs[0] == "line 10"
        assert logs[-1] == "line 59"


class TestMergeFlowRun:
    """Tests for MergeFlowRun dataclass."""

    def test_to_dict_serialization(self) -> None:
        run = MergeFlowRun(agent_id="a1", item_id="i1")
        d = run.to_dict()
        assert d["agent_id"] == "a1"
        assert d["item_id"] == "i1"
        assert d["outcome"] == "in_progress"
        assert isinstance(d["steps"], dict)
        assert len(d["steps"]) == len(MERGE_STEPS)

    def test_step_status_values(self) -> None:
        """Verify all MergeStepStatus values are valid strings."""
        assert MergeStepStatus.PENDING.value == "pending"
        assert MergeStepStatus.ACTIVE.value == "active"
        assert MergeStepStatus.DONE.value == "done"
        assert MergeStepStatus.FAILED.value == "failed"
        assert MergeStepStatus.SKIPPED.value == "skipped"


class TestMergeStepDefinitions:
    """Tests for canonical step definitions and edges."""

    def test_steps_have_unique_ids(self) -> None:
        ids = [s["id"] for s in MERGE_STEPS]
        assert len(ids) == len(set(ids)), f"Duplicate step IDs: {ids}"

    def test_edges_reference_valid_steps(self) -> None:
        valid_ids = {s["id"] for s in MERGE_STEPS}
        for edge in MERGE_EDGES:
            assert edge["from"] in valid_ids, f"Edge 'from' {edge['from']} not in steps"
            assert edge["to"] in valid_ids, f"Edge 'to' {edge['to']} not in steps"

    def test_step_0_and_11_exist(self) -> None:
        """Start and end steps must be present."""
        ids = {s["id"] for s in MERGE_STEPS}
        assert "0" in ids
        assert "11" in ids
