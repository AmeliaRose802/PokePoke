"""Tests for DesktopAPI state buffering and retrieval."""

import time

from pokepoke.desktop_api import DesktopAPI
from pokepoke.types import SessionStats, AgentStats


def test_initial_state_defaults() -> None:
    api = DesktopAPI()
    state = api.get_state()
    assert state["work_item"] is None
    assert state["agent_name"] == ""
    assert state["stats"] is None
    assert state["progress"] == {"active": False, "status": ""}
    assert state["log_count"] == 0


def test_push_log_and_incremental_reads() -> None:
    api = DesktopAPI()
    api.push_log("first", "orchestrator", None)
    api.push_log("second", "agent", "red")

    logs = api.get_new_logs()
    assert len(logs) == 2
    assert logs[0]["message"] == "first"
    assert logs[1]["target"] == "agent"

    # Subsequent call returns nothing new
    assert api.get_new_logs() == []


def test_get_all_logs_resets_index() -> None:
    api = DesktopAPI()
    api.push_log("one")
    api.push_log("two")

    _ = api.get_new_logs()
    all_logs = api.get_all_logs()
    assert len(all_logs) == 2

    # After get_all_logs, incremental should be empty
    assert api.get_new_logs() == []


def test_push_state_updates() -> None:
    api = DesktopAPI()
    api.push_work_item("item-1", "Title", "open")
    api.push_agent_name("agent-1")

    stats = SessionStats(
        agent_stats=AgentStats(input_tokens=10, output_tokens=5),
        items_completed=2,
    )
    api.push_stats(stats, elapsed_time=12.5)
    api.push_progress(True, "Working")

    state = api.get_state()
    assert state["work_item"]["item_id"] == "item-1"
    assert state["agent_name"] == "agent-1"
    assert state["stats"]["elapsed_time"] == 12.5
    assert state["stats"]["agent_stats"]["input_tokens"] == 10
    assert state["progress"] == {"active": True, "status": "Working"}


def test_clear_logs() -> None:
    api = DesktopAPI()
    api.push_log("test")
    assert api.get_state()["log_count"] == 1
    api.clear_logs()
    assert api.get_state()["log_count"] == 0


def test_elapsed_time_computed_dynamically() -> None:
    """Timer should tick on every poll, not freeze between push_stats() calls."""
    api = DesktopAPI()
    start = time.time()
    api.set_session_start_time(start)

    # Even without push_stats, get_state should report non-zero elapsed
    state = api.get_state()
    assert state["stats"] is not None
    assert state["stats"]["elapsed_time"] >= 0.0

    # get_stats should also compute it dynamically
    stats = api.get_stats()
    assert stats is not None
    assert stats["elapsed_time"] >= 0.0


def test_elapsed_time_overrides_push_stats_value() -> None:
    """Dynamic elapsed_time should override stale push_stats value."""
    api = DesktopAPI()
    start = time.time() - 100  # pretend session started 100s ago
    api.set_session_start_time(start)

    stats_obj = SessionStats(agent_stats=AgentStats(), items_completed=3)
    api.push_stats(stats_obj, elapsed_time=5.0)  # stale value

    state = api.get_state()
    # Should be ~100s, not the stale 5.0
    assert state["stats"]["elapsed_time"] >= 99.0
    # Other stats should still be present
    assert state["stats"]["items_completed"] == 3


def test_live_stats_update_in_realtime() -> None:
    """Mutating the live SessionStats object should be reflected on next poll."""
    api = DesktopAPI()
    stats_obj = SessionStats(agent_stats=AgentStats(), items_completed=0)
    api.push_stats(stats_obj, elapsed_time=0.0)

    # Verify initial state
    state = api.get_state()
    assert state["stats"]["work_agent_runs"] == 0
    assert state["stats"]["gate_agent_runs"] == 0
    assert state["stats"]["items_completed"] == 0

    # Mutate the live object (as the orchestrator does)
    stats_obj.work_agent_runs += 1
    stats_obj.gate_agent_runs += 2
    stats_obj.items_completed = 1
    stats_obj.agent_stats.input_tokens = 500

    # Next poll should reflect the mutations without another push_stats()
    state = api.get_state()
    assert state["stats"]["work_agent_runs"] == 1
    assert state["stats"]["gate_agent_runs"] == 2
    assert state["stats"]["items_completed"] == 1
    assert state["stats"]["agent_stats"]["input_tokens"] == 500


def test_set_live_session_stats_directly() -> None:
    """set_live_session_stats should register the live reference."""
    api = DesktopAPI()
    stats_obj = SessionStats(agent_stats=AgentStats(), work_agent_runs=5)
    api.set_live_session_stats(stats_obj)

    state = api.get_state()
    assert state["stats"] is not None
    assert state["stats"]["work_agent_runs"] == 5
