"""Tests for DesktopAPI time tracking and session statistics.

This module tests timing and statistics operations including:
- Elapsed time computation and dynamic updates
- Session start/end time tracking
- Live stats updates and mutations
- Stats serialization and retrieval
"""

import time

import pytest

from pokepoke.desktop.desktop_api import DesktopAPI
from pokepoke.types import AgentStats, SessionStats


@pytest.fixture(autouse=True)
def _isolate_desktop_api(monkeypatch):
    """Prevent DesktopAPI from loading real historical agents or calling git."""
    monkeypatch.setattr("pokepoke.desktop.desktop_api_ext._discover_log_roots", lambda: [])
    monkeypatch.setattr("pokepoke.desktop.desktop_api.get_repository_name", lambda: "test-repo")


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


def test_session_end_time_freezes_clock() -> None:
    """Session end time should freeze the elapsed_time clock."""
    api = DesktopAPI()
    start_time = time.time() - 10  # 10 seconds ago
    api.set_session_start_time(start_time)

    # Clock should be running
    stats1 = api.get_stats()
    assert stats1 is not None
    elapsed1 = stats1["elapsed_time"]
    assert elapsed1 >= 9  # Should be ~10 seconds (integer precision)

    # Set end time to freeze the clock
    end_time = start_time + 5.5  # 5.5 seconds after start
    api.set_session_end_time(end_time)

    # Clock should be frozen — elapsed truncated to int seconds (5)
    stats2 = api.get_stats()
    assert stats2 is not None
    elapsed2 = stats2["elapsed_time"]
    # int(5.5) == 5; allow ±1 for integer truncation
    assert abs(elapsed2 - 5.5) <= 1

    # Clock should remain frozen even after waiting
    time.sleep(0.1)
    stats3 = api.get_stats()
    assert stats3 is not None
    elapsed3 = stats3["elapsed_time"]
    assert elapsed3 == elapsed2  # Should not advance


def test_session_end_time_without_start_time() -> None:
    """Session end time should be ignored if no start time is set."""
    api = DesktopAPI()
    api.set_session_end_time(time.time())

    # No session start time set, so elapsed_time shouldn't exist
    stats = api.get_stats()
    assert stats is None or "elapsed_time" not in stats


def test_session_end_time_with_pushed_stats() -> None:
    """Session end time should override elapsed_time from pushed stats."""
    api = DesktopAPI()
    start_time = time.time() - 10
    api.set_session_start_time(start_time)

    # Push stats with some elapsed time
    stats_obj = SessionStats(agent_stats=AgentStats(), items_completed=2)
    api.push_stats(stats_obj, elapsed_time=100.0)  # wrong value

    # Set end time to freeze the clock
    end_time = start_time + 3.0  # 3 seconds after start
    api.set_session_end_time(end_time)

    # Should use frozen time (3.0), not pushed time (100.0)
    state = api.get_state()
    assert state["stats"] is not None
    assert abs(state["stats"]["elapsed_time"] - 3.0) < 0.1
    assert state["stats"]["items_completed"] == 2  # Other data preserved


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
    assert state["stats"]["items_created"] == 0

    # Mutate the live object (as the orchestrator does)
    stats_obj.record_agent_run("work", 1)
    stats_obj.record_agent_run("gate", 2)
    stats_obj.items_completed = 1
    stats_obj.agent_stats.input_tokens = 500

    # Next poll should reflect the mutations without another push_stats()
    state = api.get_state()
    assert state["stats"]["work_agent_runs"] == 1
    assert state["stats"]["gate_agent_runs"] == 2
    assert state["stats"]["items_completed"] == 1
    assert state["stats"]["items_created"] == 0
    assert state["stats"]["agent_stats"]["input_tokens"] == 500


def test_set_live_session_stats_directly() -> None:
    """set_live_session_stats should register the live reference."""
    api = DesktopAPI()
    stats_obj = SessionStats(agent_stats=AgentStats(), work_agent_runs=5)
    api.set_live_session_stats(stats_obj)

    state = api.get_state()
    assert state["stats"] is not None
    assert state["stats"]["work_agent_runs"] == 5


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
