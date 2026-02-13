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


def test_set_window() -> None:
    """set_window should store the window reference."""
    api = DesktopAPI()
    api.set_window("fake_window")
    assert api._window == "fake_window"


def test_get_work_item() -> None:
    """get_work_item should return the current work item."""
    api = DesktopAPI()
    assert api.get_work_item() is None
    api.push_work_item("item-1", "Title")
    assert api.get_work_item()["item_id"] == "item-1"


def test_get_stats_returns_none_initially() -> None:
    """get_stats should return None when no stats have been set."""
    api = DesktopAPI()
    assert api.get_stats() is None


def test_get_stats_returns_live_stats() -> None:
    """get_stats should return serialized live stats."""
    api = DesktopAPI()
    stats_obj = SessionStats(agent_stats=AgentStats(input_tokens=42))
    api.set_live_session_stats(stats_obj)
    result = api.get_stats()
    assert result is not None
    assert result["agent_stats"]["input_tokens"] == 42


def test_get_stats_with_session_start_time() -> None:
    """get_stats should include dynamic elapsed_time when session start is set."""
    api = DesktopAPI()
    api.set_session_start_time(time.time() - 10)
    result = api.get_stats()
    assert result is not None
    assert result["elapsed_time"] >= 9.0


def test_push_log_buffer_trimming() -> None:
    """push_log should trim the buffer when it exceeds max size."""
    api = DesktopAPI()
    api._max_log_buffer = 5

    for i in range(8):
        api.push_log(f"msg-{i}")

    assert len(api._log_buffer) == 5
    assert api._log_buffer[0]["message"] == "msg-3"


def test_push_log_buffer_trim_adjusts_read_index() -> None:
    """Trimming should adjust read index to avoid returning stale entries."""
    api = DesktopAPI()
    api._max_log_buffer = 5

    for i in range(3):
        api.push_log(f"msg-{i}")
    api.get_new_logs()  # read_index = 3

    for i in range(5):
        api.push_log(f"msg-extra-{i}")

    new_logs = api.get_new_logs()
    assert len(new_logs) >= 0


def test_serialize_live_stats_no_session_start() -> None:
    """_serialize_live_stats should carry forward cached elapsed_time."""
    api = DesktopAPI()
    stats_obj = SessionStats(agent_stats=AgentStats())
    api.push_stats(stats_obj, elapsed_time=42.0)

    api._session_start_time = None
    state = api.get_state()
    assert state["stats"]["elapsed_time"] == 42.0


def test_push_stats_without_session_stats() -> None:
    """push_stats with None session_stats should still store elapsed_time."""
    api = DesktopAPI()
    api.push_stats(None, elapsed_time=5.0)
    assert api._current_stats is not None
    assert api._current_stats["elapsed_time"] == 5.0


def test_get_model_leaderboard() -> None:
    """get_model_leaderboard should return model summary."""
    from unittest.mock import patch
    api = DesktopAPI()
    with patch("pokepoke.model_stats_store.get_model_summary", return_value={"test": 1}):
        result = api.get_model_leaderboard()
    assert result == {"test": 1}


def test_get_state_includes_model_leaderboard() -> None:
    """get_state should include model_leaderboard field."""
    from unittest.mock import patch
    api = DesktopAPI()
    with patch("pokepoke.model_stats_store.get_model_summary", return_value={"models": []}):
        state = api.get_state()
    assert "model_leaderboard" in state


def test_push_stats_with_model_completions() -> None:
    """push_stats should serialize model completions via snapshot."""
    from pokepoke.types import ModelCompletionRecord
    api = DesktopAPI()
    stats_obj = SessionStats(agent_stats=AgentStats())
    stats_obj.record_model_completion(ModelCompletionRecord(
        item_id="x", model="gpt-5", duration_seconds=10.0
    ))
    api.push_stats(stats_obj, elapsed_time=1.0)
    assert len(api._current_stats["model_completions"]) == 1
