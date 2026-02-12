"""Tests for DesktopAPI state buffering and retrieval."""

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
