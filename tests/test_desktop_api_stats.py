"""Tests for desktop_api_stats serialization helpers."""

from __future__ import annotations

import time
from types import SimpleNamespace
from unittest.mock import patch

from pokepoke.desktop_api_stats import (
    get_cached_leaderboard,
    get_model_history,
    get_model_leaderboard,
    push_stats,
    serialize_live_stats,
    snapshot_to_dict,
)
from pokepoke.types import (
    AgentStats,
    BeadsCreatedItem,
    BeadsWorkItem,
    ModelCompletionRecord,
    SessionStats,
)


def _make_stats(**kwargs) -> SessionStats:
    """Create a SessionStats with defaults for testing."""
    return SessionStats(agent_stats=AgentStats(), **kwargs)


def _make_self(**kwargs):
    """Create a minimal 'self' mock for mixin functions."""
    defaults = {
        "_live_session_stats": None,
        "_current_stats": None,
        "_session_start_time": None,
        "_session_end_time": None,
        "_leaderboard_cache_time": 0.0,
        "_leaderboard_cache": {},
        "_history_cache": None,
        "_history_cache_limit": None,
        "_history_cache_time": 0.0,
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


class TestSnapshotToDict:
    """Tests for snapshot_to_dict."""

    def test_returns_all_required_keys(self) -> None:
        stats = _make_stats()
        d = snapshot_to_dict(stats.snapshot())
        expected_keys = {
            "agent_stats",
            "items_completed",
            "items_created",
            "net_items_delta",
            "lifetime_items_created",
            "lifetime_items_completed",
            "created_counts_by_agent_type",
            "completed_counts_by_agent_type",
            "completed_items",
            "created_items",
            "work_agent_runs",
            "gate_agent_runs",
            "tech_debt_agent_runs",
            "janitor_agent_runs",
            "backlog_cleanup_agent_runs",
            "cleanup_agent_runs",
            "beta_tester_agent_runs",
            "code_review_agent_runs",
            "worktree_cleanup_agent_runs",
            "agent_type_elapsed_seconds",
            "model_completions",
        }
        assert expected_keys.issubset(d.keys())

    def test_agent_type_elapsed_seconds_empty_by_default(self) -> None:
        stats = _make_stats()
        d = snapshot_to_dict(stats.snapshot())
        assert d["agent_type_elapsed_seconds"] == {}

    def test_agent_type_elapsed_seconds_recorded(self) -> None:
        stats = _make_stats()
        stats.record_agent_elapsed_time("work", 120.0)
        stats.record_agent_elapsed_time("gate", 45.5)
        d = snapshot_to_dict(stats.snapshot())
        assert d["agent_type_elapsed_seconds"]["work"] == 120.0
        assert d["agent_type_elapsed_seconds"]["gate"] == 45.5

    def test_agent_type_elapsed_seconds_accumulates(self) -> None:
        stats = _make_stats()
        stats.record_agent_elapsed_time("work", 60.0)
        stats.record_agent_elapsed_time("work", 40.0)
        d = snapshot_to_dict(stats.snapshot())
        assert d["agent_type_elapsed_seconds"]["work"] == 100.0

    def test_net_items_delta(self) -> None:
        stats = _make_stats()
        stats.items_created = 5
        item = BeadsWorkItem(id="x-1", title="t", status="done", priority=1, issue_type="task")
        stats.record_completion(item)
        stats.record_completion(item.__class__(id="x-2", title="t2", status="done", priority=1, issue_type="task"))
        d = snapshot_to_dict(stats.snapshot())
        assert d["items_created"] == 5
        assert d["items_completed"] == 2
        assert d["net_items_delta"] == 3

    def test_agent_runs_serialized(self) -> None:
        stats = _make_stats()
        stats.record_agent_run("work")
        stats.record_agent_run("gate", 2)
        d = snapshot_to_dict(stats.snapshot())
        assert d["work_agent_runs"] == 1
        assert d["gate_agent_runs"] == 2

    def test_model_completions_serialized(self) -> None:
        stats = _make_stats()
        mc = ModelCompletionRecord(item_id="i-1", model="gpt-4", duration_seconds=30.0, gate_passed=True)
        stats.record_model_completion(mc)
        d = snapshot_to_dict(stats.snapshot())
        assert len(d["model_completions"]) == 1
        assert d["model_completions"][0]["item_id"] == "i-1"

    def test_completed_items_list(self) -> None:
        stats = _make_stats()
        item = BeadsWorkItem(id="p-1", title="Do thing", status="done", priority=1, issue_type="task")
        stats.record_completion(item)
        d = snapshot_to_dict(stats.snapshot())
        assert len(d["completed_items"]) == 1
        assert d["completed_items"][0]["id"] == "p-1"

    def test_created_items_list(self) -> None:
        stats = _make_stats()
        ci = BeadsCreatedItem(id="c-1", title="New item", agent_type="work")
        stats.record_created_item(ci)
        d = snapshot_to_dict(stats.snapshot())
        assert len(d["created_items"]) == 1
        assert d["created_items"][0]["id"] == "c-1"

    def test_elapsed_seconds_is_a_plain_dict(self) -> None:
        stats = _make_stats()
        stats.record_agent_elapsed_time("janitor", 10.0)
        d = snapshot_to_dict(stats.snapshot())
        # Must be JSON-serialisable plain dict
        assert isinstance(d["agent_type_elapsed_seconds"], dict)


class TestSerializeLiveStats:
    def test_returns_none_with_no_data(self) -> None:
        obj = _make_self()
        assert serialize_live_stats(obj) is None

    def test_returns_dict_from_live_session_stats(self) -> None:
        stats = _make_stats()
        obj = _make_self(_live_session_stats=stats)
        result = serialize_live_stats(obj)
        assert result is not None
        assert "agent_stats" in result

    def test_copies_elapsed_time_from_current_stats(self) -> None:
        stats = _make_stats()
        obj = _make_self(
            _live_session_stats=stats,
            _current_stats={"elapsed_time": 99.0},
        )
        result = serialize_live_stats(obj)
        assert result is not None
        assert result["elapsed_time"] == 99.0

    def test_falls_back_to_current_stats_when_no_live(self) -> None:
        obj = _make_self(_current_stats={"elapsed_time": 42.0, "foo": "bar"})
        result = serialize_live_stats(obj)
        assert result is not None
        assert result["foo"] == "bar"

    def test_live_elapsed_time_from_session_start(self) -> None:
        obj = _make_self(_session_start_time=time.time() - 10.0)
        result = serialize_live_stats(obj)
        assert result is not None
        assert result["elapsed_time"] >= 9.0

    def test_live_elapsed_time_overrides_when_stats_present(self) -> None:
        """Elapsed time from session start overrides any existing elapsed_time in stats."""
        stats = _make_stats()
        t0 = time.time() - 20.0
        obj = _make_self(
            _live_session_stats=stats,
            _current_stats={"elapsed_time": 999.0},
            _session_start_time=t0,
        )
        result = serialize_live_stats(obj)
        assert result is not None
        assert result["elapsed_time"] >= 19.0

    def test_live_elapsed_time_uses_session_end_when_set(self) -> None:
        t0 = time.time() - 100.0
        obj = _make_self(_session_start_time=t0, _session_end_time=t0 + 50.0)
        result = serialize_live_stats(obj)
        assert result is not None
        assert abs(result["elapsed_time"] - 50.0) < 1.0


class TestGetCachedLeaderboard:
    def test_returns_cached_value_within_ttl(self) -> None:
        cached = {"model-a": {"success_rate": 0.9}}
        obj = _make_self(_leaderboard_cache=cached, _leaderboard_cache_time=time.time())
        result = get_cached_leaderboard(obj)
        assert result is cached

    def test_refreshes_stale_cache(self) -> None:
        fresh = {"model-b": {"success_rate": 0.8}}
        obj = _make_self(_leaderboard_cache={}, _leaderboard_cache_time=0.0)
        with patch("pokepoke.model_stats_store.get_model_summary", return_value=fresh):
            result = get_cached_leaderboard(obj)
        assert result == fresh


class TestGetModelLeaderboard:
    def test_calls_get_model_summary(self) -> None:
        obj = _make_self()
        expected = {"model-x": {"total_items_attempted": 5}}
        with patch("pokepoke.model_stats_store.get_model_summary", return_value=expected):
            result = get_model_leaderboard(obj)
        assert result == expected


class TestGetModelHistory:
    def test_returns_empty_for_non_positive_limit(self) -> None:
        obj = _make_self()
        assert get_model_history(obj, limit=0) == []
        assert get_model_history(obj, limit=-1) == []

    def test_returns_cached_history(self) -> None:
        # Cached data should already be normalized
        cached = [{"item_id": "x", "duration_seconds": 45.0, "gate_passed": False}]
        obj = _make_self(
            _history_cache=cached,
            _history_cache_limit=200,
            _history_cache_time=time.time(),
        )
        result = get_model_history(obj)
        assert result == cached

    def test_fetches_and_stores_new_history(self) -> None:
        obj = _make_self()
        # Mock raw data from backend (before normalization)
        raw_data = [{"work_item_id": "new", "wall_time_seconds": 30.0, "quality_gates_passed": True}]
        # Expected normalized data
        normalized = [{"item_id": "new", "duration_seconds": 30.0, "gate_passed": True}]

        with patch("pokepoke.model_history.load_model_history_entries", return_value=raw_data):
            result = get_model_history(obj, limit=10)

        assert result == normalized
        assert obj._history_cache == normalized
        assert obj._history_cache_limit == 10

    def test_normalizes_model_history_keys(self) -> None:
        """Test that backend keys are mapped to frontend schema."""
        obj = _make_self()
        # Raw data with backend keys
        raw_data = [
            {
                "timestamp": "2024-01-01T00:00:00",
                "model": "gpt-4",
                "work_item_id": "PokePoke-123",
                "title": "Fix bug",
                "issue_type": "bug",
                "labels": ["backend", "critical"],
                "wall_time_seconds": 45.5,
                "quality_gates_passed": True,
                "success": True,
                "retry_attempts": 0,
            }
        ]

        with patch("pokepoke.model_history.load_model_history_entries", return_value=raw_data):
            result = get_model_history(obj, limit=10)

        assert len(result) == 1
        entry = result[0]

        # Check normalized keys exist
        assert entry["item_id"] == "PokePoke-123"
        assert entry["duration_seconds"] == 45.5
        assert entry["gate_passed"] is True

        # Check old keys are removed
        assert "work_item_id" not in entry
        assert "wall_time_seconds" not in entry
        assert "quality_gates_passed" not in entry

        # Check other fields are preserved
        assert entry["timestamp"] == "2024-01-01T00:00:00"
        assert entry["model"] == "gpt-4"
        assert entry["title"] == "Fix bug"
        assert entry["issue_type"] == "bug"
        assert entry["labels"] == ["backend", "critical"]
        assert entry["success"] is True
        assert entry["retry_attempts"] == 0


class TestPushStats:
    def test_stores_live_session_stats(self) -> None:
        stats = _make_stats()
        obj = _make_self()
        push_stats(obj, stats)
        assert obj._live_session_stats is stats

    def test_stores_current_stats_with_elapsed_time(self) -> None:
        stats = _make_stats()
        obj = _make_self()
        push_stats(obj, stats, elapsed_time=77.5)
        assert obj._current_stats["elapsed_time"] == 77.5

    def test_handles_none_session_stats(self) -> None:
        obj = _make_self()
        push_stats(obj, None, elapsed_time=5.0)
        assert obj._current_stats["elapsed_time"] == 5.0
        assert obj._live_session_stats is None
