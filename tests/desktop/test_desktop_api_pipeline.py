"""Tests for the get_pipeline_state bridge method."""

from unittest.mock import patch

import pytest

from pokepoke.desktop.desktop_api import DesktopAPI
from pokepoke.orchestration.gate_step_tracker import GateStepTracker
from pokepoke.worktrees.merge_step_tracker import MergeStepTracker

GATE_TRACKER_PATH = "pokepoke.orchestration.gate_step_tracker.get_gate_step_tracker"
MERGE_TRACKER_PATH = "pokepoke.worktrees.merge_step_tracker.get_merge_step_tracker"


@pytest.fixture(autouse=True)
def _isolate_desktop_api(monkeypatch):
    """Prevent DesktopAPI from loading real historical agents or calling git."""
    monkeypatch.setattr("pokepoke.desktop.desktop_api_ext._discover_log_roots", lambda: [])
    monkeypatch.setattr("pokepoke.desktop.desktop_api.get_repository_name", lambda: "test-repo")


class TestGetPipelineState:
    """Tests for DesktopAPI.get_pipeline_state()."""

    def test_idle_when_no_runs(self) -> None:
        gate_tracker = GateStepTracker()
        merge_tracker = MergeStepTracker()
        api = DesktopAPI()

        with patch(GATE_TRACKER_PATH, return_value=gate_tracker), \
             patch(MERGE_TRACKER_PATH, return_value=merge_tracker):
            state = api.get_pipeline_state()

        assert state["active_phase"] == "idle"
        assert state["gate"]["current_run"] is None
        assert state["merge"]["current_run"] is None

    def test_gate_active_when_gate_running(self) -> None:
        gate_tracker = GateStepTracker()
        gate_tracker.begin_run("agent-1", "item-42")
        merge_tracker = MergeStepTracker()
        api = DesktopAPI()

        with patch(GATE_TRACKER_PATH, return_value=gate_tracker), \
             patch(MERGE_TRACKER_PATH, return_value=merge_tracker):
            state = api.get_pipeline_state()

        assert state["active_phase"] == "gate"
        assert state["gate"]["current_run"] is not None
        assert state["gate"]["current_run"]["agent_id"] == "agent-1"

    def test_merge_active_when_merge_running(self) -> None:
        gate_tracker = GateStepTracker()
        merge_tracker = MergeStepTracker()
        merge_tracker.begin_run("agent-1", "item-42")
        api = DesktopAPI()

        with patch(GATE_TRACKER_PATH, return_value=gate_tracker), \
             patch(MERGE_TRACKER_PATH, return_value=merge_tracker):
            state = api.get_pipeline_state()

        assert state["active_phase"] == "merge"
        assert state["merge"]["current_run"] is not None

    def test_gate_takes_priority_when_both_running(self) -> None:
        gate_tracker = GateStepTracker()
        gate_tracker.begin_run("agent-1", "item-42")
        merge_tracker = MergeStepTracker()
        merge_tracker.begin_run("agent-2", "item-99")
        api = DesktopAPI()

        with patch(GATE_TRACKER_PATH, return_value=gate_tracker), \
             patch(MERGE_TRACKER_PATH, return_value=merge_tracker):
            state = api.get_pipeline_state()

        assert state["active_phase"] == "gate"

    def test_merge_phase_when_only_merge_completed(self) -> None:
        gate_tracker = GateStepTracker()
        merge_tracker = MergeStepTracker()
        merge_tracker.begin_run("agent-1", "item-42")
        merge_tracker.finish_run("success")
        api = DesktopAPI()

        with patch(GATE_TRACKER_PATH, return_value=gate_tracker), \
             patch(MERGE_TRACKER_PATH, return_value=merge_tracker):
            state = api.get_pipeline_state()

        assert state["active_phase"] == "merge"
        assert state["merge"]["current_run"] is None
        assert state["merge"]["last_completed_run"] is not None
        assert state["merge"]["last_completed_run"]["outcome"] == "success"

    def test_gate_phase_when_only_gate_completed(self) -> None:
        gate_tracker = GateStepTracker()
        gate_tracker.begin_run("agent-1", "item-42")
        gate_tracker.finish_run("success")
        merge_tracker = MergeStepTracker()
        api = DesktopAPI()

        with patch(GATE_TRACKER_PATH, return_value=gate_tracker), \
             patch(MERGE_TRACKER_PATH, return_value=merge_tracker):
            state = api.get_pipeline_state()

        assert state["active_phase"] == "gate"
        assert state["gate"]["last_completed_run"] is not None

    def test_contains_both_flow_states(self) -> None:
        gate_tracker = GateStepTracker()
        merge_tracker = MergeStepTracker()
        api = DesktopAPI()

        with patch(GATE_TRACKER_PATH, return_value=gate_tracker), \
             patch(MERGE_TRACKER_PATH, return_value=merge_tracker):
            state = api.get_pipeline_state()

        assert "gate" in state
        assert "merge" in state
        assert "steps_definition" in state["gate"]
        assert "edges" in state["gate"]
        assert "steps_definition" in state["merge"]
        assert "edges" in state["merge"]
