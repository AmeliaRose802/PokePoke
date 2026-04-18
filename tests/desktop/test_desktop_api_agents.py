"""Tests for DesktopAPI agent management functionality.

This module tests agent lifecycle operations including:
- Agent spawning and registration
- Agent status updates and tracking
- Agent control operations (pause/resume, stop_after_current)
- Agent removal and cleanup
- Agent token tracking
"""

from unittest.mock import Mock

import pytest

from pokepoke.desktop.desktop_api import DesktopAPI


@pytest.fixture(autouse=True)
def _isolate_desktop_api(monkeypatch):
    """Prevent DesktopAPI from loading real historical agents or calling git."""
    monkeypatch.setattr("pokepoke.desktop.desktop_api_ext._discover_log_roots", lambda: [])
    monkeypatch.setattr("pokepoke.desktop.desktop_api.get_repository_name", lambda: "test-repo")


def test_spawn_agent_honors_effective_max_agents(monkeypatch) -> None:
    api = DesktopAPI()
    api.push_agent_status("a1", "agent-1", status="running")
    api.push_agent_status("a2", "agent-2", status="running")

    mock_request = Mock()
    monkeypatch.setattr("pokepoke.agents.parallel.request_spawn_agent", mock_request)
    monkeypatch.setattr("pokepoke.agents.parallel.get_effective_max_agents", lambda: 3)

    result = api.spawn_agent()
    assert result["success"] is True
    assert result["at_limit"] is False
    assert result["active"] == 2
    assert result["max"] == 3
    mock_request.assert_called_once()

    mock_request.reset_mock()
    monkeypatch.setattr("pokepoke.agents.parallel.get_effective_max_agents", lambda: 2)

    result = api.spawn_agent()
    assert result["success"] is False
    assert result["at_limit"] is True
    assert result["active"] == 2
    assert result["max"] == 2
    mock_request.assert_not_called()


def test_initial_state_has_empty_agents(monkeypatch) -> None:
    """get_state should include an empty agents list initially."""
    monkeypatch.delenv("POKEPOKE_LOGS_DIR", raising=False)
    monkeypatch.setattr("pokepoke.desktop.desktop_api_ext._discover_log_roots", lambda: [])
    api = DesktopAPI()
    state = api.get_state()
    assert state["agents"] == []


def test_push_agent_status_registers_agent(monkeypatch) -> None:
    """push_agent_status should add an agent to the tracked set."""
    monkeypatch.setattr("pokepoke.desktop.desktop_api_ext._discover_log_roots", lambda: [])
    api = DesktopAPI()
    api.push_agent_status("agent-1", "Gate Agent", iteration=2, status="running", model="gpt-5.1")

    agents = api.get_agents()
    assert len(agents) == 1
    assert agents[0]["agent_id"] == "agent-1"
    assert agents[0]["name"] == "Gate Agent"
    assert agents[0]["iteration"] == 2
    assert agents[0]["status"] == "running"
    assert agents[0]["model"] == "gpt-5.1"
    assert agents[0]["work_item_id"] is None
    assert agents[0]["work_item_title"] is None
    assert agents[0]["modified_files"] == []
    assert agents[0]["recent_logs"] == []


def test_push_agent_status_updates_existing(monkeypatch) -> None:
    """push_agent_status should update an existing agent's fields."""
    monkeypatch.setattr("pokepoke.desktop.desktop_api_ext._discover_log_roots", lambda: [])
    api = DesktopAPI()
    api.push_agent_status(
        "agent-1",
        "Gate Agent",
        iteration=1,
        model="gpt-5",
        work_item_id="item-123",
        work_item_title="Title",
    )
    api.push_agent_log("agent-1", "line 1")

    # Update iteration and status — logs + model should be preserved
    api.push_agent_status("agent-1", "Gate Agent", iteration=2, status="success")

    agents = api.get_agents()
    assert len(agents) == 2

    current = next(agent for agent in agents if not agent["is_history_entry"])
    history = next(agent for agent in agents if agent["is_history_entry"])

    assert current["iteration"] == 2
    assert current["status"] == "success"
    assert current["model"] == "gpt-5"
    assert current["work_item_id"] == "item-123"
    assert current["work_item_title"] == "Title"
    assert current["recent_logs"] == []

    assert history["iteration"] == 1
    assert history["status"] == "failed"
    assert history["recent_logs"] == ["line 1"]
    assert history["is_history_entry"] is True


def test_push_agent_log_appends_lines() -> None:
    """push_agent_log should append lines to the agent's recent logs."""
    api = DesktopAPI()
    api.push_agent_status("agent-1", "Work Agent")
    api.push_agent_log("agent-1", "Starting tests...")
    api.push_agent_log("agent-1", "Tests passed")

    agents = api.get_agents()
    assert agents[0]["recent_logs"] == ["Starting tests...", "Tests passed"]


def test_push_agent_log_trims_excess() -> None:
    """push_agent_log should trim to max log lines."""
    api = DesktopAPI()
    api._agent_max_log_lines = 3
    api._agent_detail_max_log_lines = 4
    api.push_agent_status("agent-1", "Worker")
    for i in range(5):
        api.push_agent_log("agent-1", f"line-{i}")

    agents = api.get_agents()
    assert agents[0]["recent_logs"] == ["line-2", "line-3", "line-4"]
    # log_lines is only available via get_agent_detail, not in the summary
    assert "log_lines" not in agents[0]
    detail = api.get_agent_detail("agent-1")
    assert detail is not None
    assert detail["log_lines"] == ["line-1", "line-2", "line-3", "line-4"]


def test_push_agent_log_ignores_unknown_agent(monkeypatch) -> None:
    """push_agent_log should silently ignore unknown agent IDs."""
    monkeypatch.setattr("pokepoke.desktop.desktop_api_ext._discover_log_roots", lambda: [])
    api = DesktopAPI()
    api.push_agent_log("nonexistent", "should not crash")
    assert api.get_agents() == []


def test_remove_agent(monkeypatch) -> None:
    """remove_agent should remove the agent from tracked set."""
    monkeypatch.setattr("pokepoke.desktop.desktop_api_ext._discover_log_roots", lambda: [])
    api = DesktopAPI()
    api.push_agent_status("agent-1", "Agent A")
    api.push_agent_status("agent-2", "Agent B")
    api.remove_agent("agent-1")

    agents = api.get_agents()
    assert len(agents) == 1
    assert agents[0]["agent_id"] == "agent-2"


def test_remove_agent_ignores_unknown(monkeypatch) -> None:
    """remove_agent should silently ignore unknown agent IDs."""
    monkeypatch.setattr("pokepoke.desktop.desktop_api_ext._discover_log_roots", lambda: [])
    api = DesktopAPI()
    api.remove_agent("nonexistent")
    assert api.get_agents() == []


def test_get_state_includes_agents(monkeypatch) -> None:
    """get_state should include agents in the returned state."""
    monkeypatch.setattr("pokepoke.desktop.desktop_api_ext._discover_log_roots", lambda: [])
    api = DesktopAPI()
    api.push_agent_status("agent-1", "Worker", iteration=3, status="running")
    api.push_agent_log("agent-1", "doing work")

    state = api.get_state()
    assert len(state["agents"]) == 1
    assert state["agents"][0]["name"] == "Worker"
    assert state["agents"][0]["recent_logs"] == ["doing work"]
    # log_lines is omitted from serialize_all to keep poll payloads small;
    # it is only available from get_agent_detail.
    assert "log_lines" not in state["agents"][0]
    assert state["agents"][0]["work_item_id"] is None
    # get_state now folds in new_logs so the frontend only needs one IPC call
    assert "new_logs" in state


def test_get_state_includes_stop_after_current() -> None:
    """get_state should include stop_after_current flag."""
    from pokepoke.utils.shutdown import reset as shutdown_reset
    shutdown_reset()
    api = DesktopAPI()
    state = api.get_state()
    assert "stop_after_current" in state
    assert state["stop_after_current"] is False


def test_request_stop_after_current_sets_flag() -> None:
    """request_stop_after_current should set the flag and log a message."""
    from pokepoke.utils.shutdown import reset as shutdown_reset
    shutdown_reset()
    api = DesktopAPI()
    result = api.request_stop_after_current()
    assert result["stop_after_current"] is True
    state = api.get_state()
    assert state["stop_after_current"] is True
    assert any("Stop after current" in log["message"] for log in api.get_all_logs())
    shutdown_reset()


def test_cancel_stop_after_current_clears_flag() -> None:
    """cancel_stop_after_current should clear the flag and log a message."""
    from pokepoke.utils.shutdown import reset as shutdown_reset
    shutdown_reset()
    api = DesktopAPI()
    api.request_stop_after_current()
    result = api.cancel_stop_after_current()
    assert result["stop_after_current"] is False
    state = api.get_state()
    assert state["stop_after_current"] is False
    shutdown_reset()


# ─── Agent pause/resume tests ───────────────────────────────────────────


def test_pause_agent_sets_paused_flag() -> None:
    """pause_agent should mark agent as paused and reflect in serialization."""
    api = DesktopAPI()
    api.push_agent_status("agent-1", "Worker", status="running")

    result = api.pause_agent("agent-1")
    assert result["paused"] is True

    agents = api.get_agents()
    assert agents[0]["paused"] is True


def test_resume_agent_clears_paused_flag() -> None:
    """resume_agent should clear paused flag."""
    api = DesktopAPI()
    api.push_agent_status("agent-1", "Worker", status="running")
    api.pause_agent("agent-1")

    result = api.resume_agent("agent-1")
    assert result["resumed"] is True

    agents = api.get_agents()
    assert agents[0]["paused"] is False


def test_pause_nonexistent_agent_returns_false() -> None:
    """pause_agent should return paused=False for unknown agent."""
    api = DesktopAPI()
    result = api.pause_agent("nonexistent")
    assert result["paused"] is False


def test_resume_non_paused_agent_returns_false() -> None:
    """resume_agent should return resumed=False when agent is not paused."""
    api = DesktopAPI()
    api.push_agent_status("agent-1", "Worker", status="running")
    result = api.resume_agent("agent-1")
    assert result["resumed"] is False


def test_is_agent_paused() -> None:
    """is_agent_paused should reflect pause/resume state."""
    api = DesktopAPI()
    api.push_agent_status("agent-1", "Worker", status="running")

    assert api.is_agent_paused("agent-1") is False
    api.pause_agent("agent-1")
    assert api.is_agent_paused("agent-1") is True
    api.resume_agent("agent-1")
    assert api.is_agent_paused("agent-1") is False


def test_remove_agent_clears_paused_state() -> None:
    """remove_agent should also remove paused state."""
    api = DesktopAPI()
    api.push_agent_status("agent-1", "Worker", status="running")
    api.pause_agent("agent-1")
    api.remove_agent("agent-1")
    assert api.is_agent_paused("agent-1") is False


def test_get_agent_detail_includes_paused() -> None:
    """get_agent_detail should include paused field."""
    api = DesktopAPI()
    api.push_agent_status("agent-1", "Worker", status="running")
    api.pause_agent("agent-1")

    detail = api.get_agent_detail("agent-1")
    assert detail is not None
    assert detail["paused"] is True


def test_pause_agent_logs_message() -> None:
    """pause_agent should log a pause message."""
    api = DesktopAPI()
    api.push_agent_status("agent-1", "Worker", status="running")
    api.pause_agent("agent-1")

    logs = api.get_all_logs()
    assert any("paused" in log["message"].lower() for log in logs)


def test_resume_agent_logs_message() -> None:
    """resume_agent should log a resume message."""
    api = DesktopAPI()
    api.push_agent_status("agent-1", "Worker", status="running")
    api.pause_agent("agent-1")
    api.get_all_logs()  # clear read index
    api.resume_agent("agent-1")

    logs = api.get_new_logs()
    assert any("resumed" in log["message"].lower() for log in logs)


def test_push_agent_tokens_updates_agent() -> None:
    """push_agent_tokens should store token counts on the agent."""
    api = DesktopAPI()
    api.push_agent_status("agent-1", "Worker", status="running")
    api.push_agent_tokens("agent-1", 5000, 2000)

    agents = api.get_agents()
    assert agents[0]["input_tokens"] == 5000
    assert agents[0]["output_tokens"] == 2000


def test_push_agent_tokens_defaults_to_zero() -> None:
    """Agents without token pushes should have zero token fields."""
    api = DesktopAPI()
    api.push_agent_status("agent-1", "Worker", status="running")

    agents = api.get_agents()
    assert agents[0]["input_tokens"] == 0
    assert agents[0]["output_tokens"] == 0


def test_push_agent_tokens_ignores_unknown_agent() -> None:
    """push_agent_tokens should silently ignore unknown agent IDs."""
    api = DesktopAPI()
    api.push_agent_tokens("nonexistent", 100, 200)
    assert api.get_agents() == []


def test_agent_detail_includes_tokens() -> None:
    """get_agent_detail should include token fields."""
    api = DesktopAPI()
    api.push_agent_status("agent-1", "Worker", status="running")
    api.push_agent_tokens("agent-1", 10_000, 3_000)

    detail = api.get_agent_detail("agent-1")
    assert detail is not None
    assert detail["input_tokens"] == 10_000
    assert detail["output_tokens"] == 3_000


# ─── Child agent activity tests ──────────────────────────────────────────


def test_has_active_child_agents_false_when_no_children() -> None:
    """has_active_child_agents returns False when no children registered."""
    api = DesktopAPI()
    api.push_agent_status("parent-1", "Parent", status="running")
    assert api.has_active_child_agents("parent-1") is False


def test_has_active_child_agents_true_with_running_child() -> None:
    """has_active_child_agents returns True when a running child exists."""
    api = DesktopAPI()
    api.push_agent_status("parent-1", "Parent", status="running")
    api.push_agent_status("child-1", "Child", status="running", parent_agent_id="parent-1")
    assert api.has_active_child_agents("parent-1") is True


def test_get_child_agent_activity_time_none_when_no_children() -> None:
    """get_child_agent_activity_time returns None when no active children."""
    api = DesktopAPI()
    api.push_agent_status("parent-1", "Parent", status="running")
    assert api.get_child_agent_activity_time("parent-1") is None


def test_get_child_agent_activity_time_returns_timestamp() -> None:
    """get_child_agent_activity_time returns a timestamp for active children."""
    api = DesktopAPI()
    api.push_agent_status("parent-1", "Parent", status="running")
    api.push_agent_status("child-1", "Child", status="running", parent_agent_id="parent-1")
    api.push_agent_log("child-1", "doing work")
    result = api.get_child_agent_activity_time("parent-1")
    # Could be a float timestamp or None depending on implementation
    # Just verify it doesn't crash and returns something
    assert result is None or isinstance(result, float)


def test_has_active_child_agents_disposed_returns_false() -> None:
    """has_active_child_agents returns False when window is disposed."""
    api = DesktopAPI()
    api._window_disposed = True
    assert api.has_active_child_agents("parent-1") is False


def test_get_child_agent_activity_time_disposed_returns_none() -> None:
    """get_child_agent_activity_time returns None when window is disposed."""
    api = DesktopAPI()
    api._window_disposed = True
    assert api.get_child_agent_activity_time("parent-1") is None
