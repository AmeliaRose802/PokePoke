"""Tests for DesktopAPI disposal and cleanup functionality.

This module tests disposal operations including:
- Window disposal and cleanup
- Thread safety of disposal
- Post-disposal behavior (blocking mutations, allowing reads)
- Silent handling of operations after disposal
"""

from unittest.mock import Mock

import pytest

from pokepoke.desktop.desktop_api import DesktopAPI
from pokepoke.types import AgentStats, SessionStats


@pytest.fixture(autouse=True)
def _isolate_desktop_api(monkeypatch):
    """Prevent DesktopAPI from loading real historical agents or calling git."""
    monkeypatch.setattr("pokepoke.desktop.desktop_api_ext._discover_log_roots", lambda: [])
    monkeypatch.setattr("pokepoke.desktop.desktop_api.get_repository_name", lambda: "test-repo")


def test_dispose_marks_window_as_disposed() -> None:
    """dispose() should set the _window_disposed flag and clear window reference."""
    api = DesktopAPI()
    mock_window = Mock()
    api.set_window(mock_window)

    assert api._window == mock_window
    assert api._window_disposed is False

    api.dispose()

    assert api._window is None
    assert api._window_disposed is True


def test_push_log_silently_ignores_after_disposal() -> None:
    """push_log() should silently return when window is disposed to prevent ObjectDisposedException spam."""
    api = DesktopAPI()

    # Log before disposal - should work
    api.push_log("before disposal")
    assert len(api._log_buffer) == 1
    assert api._log_buffer[0]["message"] == "before disposal"

    # Dispose the window
    api.dispose()

    # Log after disposal - should be silently ignored
    api.push_log("after disposal")
    assert len(api._log_buffer) == 1  # Should still be 1, not 2
    assert api._log_buffer[0]["message"] == "before disposal"  # Original log preserved

    # Verify no exceptions are raised
    api.push_log("another log", "agent", "red")
    assert len(api._log_buffer) == 1


def test_disposal_is_thread_safe() -> None:
    """dispose() should be thread-safe using the existing lock."""
    api = DesktopAPI()

    # Add some logs before disposal
    for i in range(10):
        api.push_log(f"pre-dispose log {i}")

    assert len(api._log_buffer) == 10

    # Dispose the window
    api.dispose()
    assert api._window_disposed is True


def test_push_methods_silently_ignore_after_disposal() -> None:
    """All push methods should silently return when window is disposed."""

    api = DesktopAPI()

    # Set initial state before disposal
    api.push_work_item("item-1", "Test Item", "open", ["label1"])
    api.push_agent_name("Test Agent")
    api.push_progress(True, "working")
    api.push_agent_status("agent-1", "Worker", status="running")
    api.push_agent_log("agent-1", "log line")
    api.push_agent_tokens("agent-1", 100, 50)
    api.set_session_start_time(1000.0)
    api.set_session_end_time(2000.0)
    api.set_logs_dir("/logs")

    stats = SessionStats(
        agent_stats=AgentStats(),
        items_completed=1,
        items_created=0,
        lifetime_items_created=10,
        lifetime_items_completed=9,
    )
    api.set_live_session_stats(stats)
    api.push_stats(stats, elapsed_time=100.0)

    # Capture initial state
    initial_work_item = api._current_work_item
    initial_agent_name = api._current_agent_name
    initial_progress = api._current_progress.copy()
    initial_agents_count = len(api.get_agents())
    initial_session_start = api._session_start_time
    initial_session_end = api._session_end_time
    initial_logs_dir = api._current_logs_dir
    initial_live_stats = api._live_session_stats
    initial_current_stats = api._current_stats

    # Dispose the window
    api.dispose()

    # All push methods should now silently ignore updates
    api.push_work_item("item-2", "New Item", "closed", ["label2"])
    api.push_agent_name("Different Agent")
    api.push_progress(False, "done")
    api.push_agent_status("agent-2", "Another Worker", status="done")
    api.push_agent_log("agent-1", "should be ignored")
    api.push_agent_tokens("agent-1", 200, 100)
    api.set_session_start_time(3000.0)
    api.set_session_end_time(4000.0)
    api.set_logs_dir("/different/logs")

    new_stats = SessionStats(
        agent_stats=AgentStats(),
        items_completed=5,
        items_created=2,
        lifetime_items_created=20,
        lifetime_items_completed=18,
    )
    api.set_live_session_stats(new_stats)
    api.push_stats(new_stats, elapsed_time=200.0)
    api.clear_logs()  # Should also be ignored

    # Verify state hasn't changed
    assert api._current_work_item == initial_work_item
    assert api._current_agent_name == initial_agent_name
    assert api._current_progress == initial_progress
    assert len(api.get_agents()) == initial_agents_count  # No new agent added
    assert api._session_start_time == initial_session_start
    assert api._session_end_time == initial_session_end
    assert api._current_logs_dir == initial_logs_dir
    assert api._live_session_stats == initial_live_stats
    assert api._current_stats == initial_current_stats
    assert len(api._log_buffer) == 0  # clear_logs was not executed


def test_remove_agent_silently_ignored_after_disposal() -> None:
    """remove_agent() should be a no-op after disposal."""
    api = DesktopAPI()
    api.push_agent_status("agent-1", "Worker", status="running")
    assert len(api.get_agents()) == 1

    api.dispose()

    # remove_agent should silently ignore the call
    api.remove_agent("agent-1")
    # Agent is still in registry (not removed) because disposal blocks mutations
    assert len(api.get_agents()) == 1


def test_pause_agent_returns_false_after_disposal() -> None:
    """pause_agent() should return paused=False and not log after disposal."""
    api = DesktopAPI()
    api.push_agent_status("agent-1", "Worker", status="running")
    api.dispose()

    result = api.pause_agent("agent-1")
    assert result == {"agent_id": "agent-1", "paused": False}
    # No log entry should be added (push_log is also blocked after disposal)
    assert len(api._log_buffer) == 0


def test_resume_agent_returns_false_after_disposal() -> None:
    """resume_agent() should return resumed=False and not log after disposal."""
    api = DesktopAPI()
    api.push_agent_status("agent-1", "Worker", status="running")
    api.pause_agent("agent-1")
    api.dispose()

    result = api.resume_agent("agent-1")
    assert result == {"agent_id": "agent-1", "resumed": False}


def test_get_agents_still_works_after_disposal() -> None:
    """get_agents() should still return data after disposal (read-only)."""
    api = DesktopAPI()
    api.push_agent_status("agent-1", "Worker", status="running")
    api.dispose()

    agents = api.get_agents()
    assert len(agents) == 1
    assert agents[0]["agent_id"] == "agent-1"


def test_get_agent_detail_still_works_after_disposal() -> None:
    """get_agent_detail() should still return data after disposal (read-only)."""
    api = DesktopAPI()
    api.push_agent_status("agent-1", "Worker", status="running")
    api.dispose()

    detail = api.get_agent_detail("agent-1")
    assert detail is not None
    assert detail["agent_id"] == "agent-1"


def test_is_agent_paused_still_works_after_disposal() -> None:
    """is_agent_paused() should still return data after disposal (read-only)."""
    api = DesktopAPI()
    api.push_agent_status("agent-1", "Worker", status="running")
    api.pause_agent("agent-1")
    api.dispose()

    assert api.is_agent_paused("agent-1") is True
