"""Unit tests for types_stats module — verifies direct imports and re-exports."""

from pokepoke.types_stats import (
    AgentStats,
    BeadsStats,
    ModelCompletionRecord,
    SessionStats,
    SessionStatsSnapshot,
    _AgentRunCountsMixin,
    _session_stats_init,
)


class TestDirectImports:
    """Verify all stats types are importable directly from types_stats."""

    def test_agent_stats_importable(self) -> None:
        stats = AgentStats()
        assert stats.wall_duration == 0.0

    def test_beads_stats_importable(self) -> None:
        stats = BeadsStats()
        assert stats.total_issues == 0

    def test_model_completion_record_importable(self) -> None:
        rec = ModelCompletionRecord(item_id="x", model="m", duration_seconds=1.0)
        assert rec.item_id == "x"

    def test_session_stats_importable(self) -> None:
        stats = SessionStats(agent_stats=AgentStats())
        assert stats.items_completed == 0

    def test_session_stats_snapshot_importable(self) -> None:
        snap = SessionStatsSnapshot(agent_stats=AgentStats())
        assert snap.items_completed == 0

    def test_agent_run_counts_mixin_importable(self) -> None:
        assert hasattr(_AgentRunCountsMixin, "get_agent_run_count")

    def test_session_stats_init_importable(self) -> None:
        assert callable(_session_stats_init)


class TestReExports:
    """Verify backward-compatible re-exports from types.py."""

    def test_all_stats_types_available_from_types(self) -> None:
        from pokepoke import types as types_mod

        assert types_mod.AgentStats is AgentStats
        assert types_mod.BeadsStats is BeadsStats
        assert types_mod.ModelCompletionRecord is ModelCompletionRecord
        assert types_mod.SessionStats is SessionStats
        assert types_mod.SessionStatsSnapshot is SessionStatsSnapshot
        assert types_mod._AgentRunCountsMixin is _AgentRunCountsMixin
        assert types_mod._session_stats_init is _session_stats_init


class TestAgentStatsAccumulate:
    """Test AgentStats.accumulate method."""

    def test_accumulate_adds_all_fields(self) -> None:
        a = AgentStats(wall_duration=1.0, input_tokens=10, tool_calls=3)
        b = AgentStats(wall_duration=2.0, input_tokens=20, tool_calls=7)
        a.accumulate(b)
        assert a.wall_duration == 3.0
        assert a.input_tokens == 30
        assert a.tool_calls == 10


class TestSessionStatsLegacyInit:
    """Test the _session_stats_init monkey-patch for legacy kwargs."""

    def test_legacy_agent_runs_kwargs(self) -> None:
        stats = SessionStats(agent_stats=AgentStats(), janitor_agent_runs=5)
        assert stats.agent_run_counts["janitor"] == 5

    def test_unknown_agent_raises(self) -> None:
        import pytest
        with pytest.raises(ValueError, match="Unknown agent type"):
            SessionStats(agent_stats=AgentStats(), nonexistent_agent_runs=1)
