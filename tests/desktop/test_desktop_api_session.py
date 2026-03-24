"""Tests for desktop_api_session mixin module — coverage-mapped companion."""

from __future__ import annotations

import pytest

from pokepoke.desktop.desktop_api import DesktopAPI
from pokepoke.desktop.desktop_api_session import (
    set_live_session_stats,
    set_session_end_time,
    set_session_start_time,
)
from pokepoke.types import AgentStats, SessionStats


@pytest.fixture(autouse=True)
def _isolate_desktop_api(monkeypatch):
    """Prevent DesktopAPI from loading real historical agents or calling git."""
    monkeypatch.setattr("pokepoke.desktop.desktop_api_ext._discover_log_roots", lambda: [])
    monkeypatch.setattr("pokepoke.desktop.desktop_api.get_repository_name", lambda: "test-repo")


# ── set_session_start_time ───────────────────────────────────────────────


def test_set_session_start_time_stores_values() -> None:
    api = DesktopAPI()
    set_session_start_time(api, 1000.0)
    assert api._session_start_time == 1000.0
    assert api._current_session_id == "1000.0"


def test_set_session_start_time_via_api() -> None:
    api = DesktopAPI()
    api.set_session_start_time(42.5)
    assert api._session_start_time == 42.5
    assert api._current_session_id == "42.5"


def test_set_session_start_time_ignored_after_dispose() -> None:
    api = DesktopAPI()
    api.dispose()
    set_session_start_time(api, 999.0)
    assert api._session_start_time is None
    assert api._current_session_id is None


# ── set_session_end_time ─────────────────────────────────────────────────


def test_set_session_end_time_stores_value() -> None:
    api = DesktopAPI()
    set_session_end_time(api, 2000.0)
    assert api._session_end_time == 2000.0


def test_set_session_end_time_via_api() -> None:
    api = DesktopAPI()
    api.set_session_end_time(55.5)
    assert api._session_end_time == 55.5


def test_set_session_end_time_ignored_after_dispose() -> None:
    api = DesktopAPI()
    api.dispose()
    set_session_end_time(api, 999.0)
    assert api._session_end_time is None


# ── set_live_session_stats ───────────────────────────────────────────────


def test_set_live_session_stats_stores_value() -> None:
    api = DesktopAPI()
    stats = SessionStats(agent_stats=AgentStats())
    set_live_session_stats(api, stats)
    assert api._live_session_stats is stats


def test_set_live_session_stats_via_api() -> None:
    api = DesktopAPI()
    stats = SessionStats(agent_stats=AgentStats())
    api.set_live_session_stats(stats)
    assert api._live_session_stats is stats


def test_set_live_session_stats_ignored_after_dispose() -> None:
    api = DesktopAPI()
    api.dispose()
    stats = SessionStats(agent_stats=AgentStats())
    set_live_session_stats(api, stats)
    assert api._live_session_stats is None
