"""Unit tests for types_stats module — verifies direct imports, re-exports,
and comprehensive SessionStats method behavior.
"""

from dataclasses import replace

import pytest

from pokepoke.git.merge_queue_stats import MergeQueueStats
from pokepoke.types_beads import BeadsCreatedItem, BeadsWorkItem
from pokepoke.types_stats import (
    AgentStats,
    BeadsStats,
    ModelCompletionRecord,
    SessionStats,
    SessionStatsSnapshot,
    _AgentRunCountsMixin,
    _session_stats_init,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_stats() -> SessionStats:
    return SessionStats(agent_stats=AgentStats())


def _make_item(item_id: str = "bd-1") -> BeadsWorkItem:
    return BeadsWorkItem(
        id=item_id, title="test", status="open",
        priority=1, issue_type="task",
    )


def _make_created(item_id: str = "ci-1") -> BeadsCreatedItem:
    return BeadsCreatedItem(id=item_id, title="new", agent_type="work")


# ---------------------------------------------------------------------------
# Direct imports
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# AgentStats.accumulate
# ---------------------------------------------------------------------------

class TestAgentStatsAccumulate:
    """Test AgentStats.accumulate method."""

    def test_accumulate_adds_all_fields(self) -> None:
        a = AgentStats(wall_duration=1.0, input_tokens=10, tool_calls=3)
        b = AgentStats(wall_duration=2.0, input_tokens=20, tool_calls=7)
        a.accumulate(b)
        assert a.wall_duration == 3.0
        assert a.input_tokens == 30
        assert a.tool_calls == 10

    def test_accumulate_zero_stats_is_noop(self) -> None:
        a = AgentStats(wall_duration=5.0, retries=2)
        a.accumulate(AgentStats())
        assert a.wall_duration == 5.0
        assert a.retries == 2

    def test_accumulate_all_numeric_fields(self) -> None:
        a = AgentStats(
            wall_duration=1.0, api_duration=2.0,
            input_tokens=3, output_tokens=4,
            lines_added=5, lines_removed=6,
            premium_requests=7, retries=8, tool_calls=9,
        )
        b = replace(a)
        a.accumulate(b)
        assert a.wall_duration == 2.0
        assert a.api_duration == 4.0
        assert a.input_tokens == 6
        assert a.output_tokens == 8
        assert a.lines_added == 10
        assert a.lines_removed == 12
        assert a.premium_requests == 14
        assert a.retries == 16
        assert a.tool_calls == 18


# ---------------------------------------------------------------------------
# SessionStats legacy init
# ---------------------------------------------------------------------------

class TestSessionStatsLegacyInit:
    """Test the _session_stats_init monkey-patch for legacy kwargs."""

    def test_legacy_agent_runs_kwargs(self) -> None:
        stats = SessionStats(agent_stats=AgentStats(), janitor_agent_runs=5)
        assert stats.agent_run_counts["janitor"] == 5

    def test_unknown_agent_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown agent type"):
            SessionStats(agent_stats=AgentStats(), nonexistent_agent_runs=1)


# ---------------------------------------------------------------------------
# SessionStats.record_completion
# ---------------------------------------------------------------------------

class TestRecordCompletion:
    """Test SessionStats.record_completion."""

    def test_increments_items_completed(self) -> None:
        stats = _make_stats()
        result = stats.record_completion(_make_item())
        assert result == 1
        assert stats.items_completed == 1

    def test_explicit_items_completed_value(self) -> None:
        stats = _make_stats()
        stats.record_completion(_make_item(), items_completed=10)
        assert stats.items_completed == 10

    def test_negative_items_completed_raises(self) -> None:
        stats = _make_stats()
        with pytest.raises(ValueError, match="cannot be negative"):
            stats.record_completion(_make_item(), items_completed=-1)

    def test_appends_to_completed_list(self) -> None:
        stats = _make_stats()
        stats.record_completion(_make_item("bd-A"))
        stats.record_completion(_make_item("bd-B"))
        assert len(stats.completed_items_list) == 2
        assert stats.completed_items_list[0].id == "bd-A"

    def test_agent_type_tracking(self) -> None:
        stats = _make_stats()
        stats.record_completion(_make_item(), agent_type="Work")
        stats.record_completion(_make_item(), agent_type="work")
        assert stats.completed_counts_by_agent_type["work"] == 2

    def test_list_truncation_at_max_entries(self) -> None:
        stats = _make_stats()
        for i in range(SessionStats.MAX_LIST_ENTRIES):
            stats.record_completion(_make_item(f"bd-{i}"))
        # After reaching MAX, the oldest half should be evicted
        assert len(stats.completed_items_list) < SessionStats.MAX_LIST_ENTRIES


# ---------------------------------------------------------------------------
# SessionStats.record_created_item
# ---------------------------------------------------------------------------

class TestRecordCreatedItem:
    """Test SessionStats.record_created_item."""

    def test_increments_items_created(self) -> None:
        stats = _make_stats()
        result = stats.record_created_item(_make_created("ci-1"))
        assert result == 1
        assert stats.items_created == 1

    def test_deduplication_by_id(self) -> None:
        stats = _make_stats()
        stats.record_created_item(_make_created("ci-dup"))
        stats.record_created_item(_make_created("ci-dup"))
        assert stats.items_created == 1

    def test_different_ids_counted(self) -> None:
        stats = _make_stats()
        stats.record_created_item(_make_created("ci-a"))
        stats.record_created_item(_make_created("ci-b"))
        assert stats.items_created == 2

    def test_agent_type_counting(self) -> None:
        stats = _make_stats()
        stats.record_created_item(BeadsCreatedItem(id="c1", agent_type="gate"))
        stats.record_created_item(BeadsCreatedItem(id="c2", agent_type="Gate"))
        assert stats.created_counts_by_agent_type["gate"] == 2

    def test_empty_agent_type_defaults_unknown(self) -> None:
        stats = _make_stats()
        stats.record_created_item(BeadsCreatedItem(id="c3", agent_type=""))
        assert stats.created_counts_by_agent_type.get("unknown", 0) == 1

    def test_list_truncation(self) -> None:
        stats = _make_stats()
        for i in range(SessionStats.MAX_LIST_ENTRIES):
            stats.record_created_item(_make_created(f"ci-{i}"))
        assert len(stats.created_items_list) < SessionStats.MAX_LIST_ENTRIES


# ---------------------------------------------------------------------------
# SessionStats.record_agent_run
# ---------------------------------------------------------------------------

class TestRecordAgentRun:
    """Test SessionStats.record_agent_run."""

    def test_increments_count(self) -> None:
        stats = _make_stats()
        stats.record_agent_run("work")
        assert stats.agent_run_counts["work"] == 1

    def test_multiple_increments(self) -> None:
        stats = _make_stats()
        stats.record_agent_run("gate", count=3)
        assert stats.agent_run_counts["gate"] == 3

    def test_negative_count_raises(self) -> None:
        stats = _make_stats()
        with pytest.raises(ValueError, match="cannot be negative"):
            stats.record_agent_run("work", count=-1)

    def test_zero_count_is_noop(self) -> None:
        stats = _make_stats()
        stats.record_agent_run("work", count=0)
        assert stats.agent_run_counts["work"] == 0


# ---------------------------------------------------------------------------
# SessionStats.record_agent_elapsed_time
# ---------------------------------------------------------------------------

class TestRecordAgentElapsedTime:
    """Test SessionStats.record_agent_elapsed_time."""

    def test_accumulates_time(self) -> None:
        stats = _make_stats()
        stats.record_agent_elapsed_time("work", 10.5)
        stats.record_agent_elapsed_time("work", 5.5)
        assert stats.agent_type_elapsed_seconds["work"] == 16.0

    def test_zero_elapsed_ignored(self) -> None:
        stats = _make_stats()
        stats.record_agent_elapsed_time("work", 0)
        assert "work" not in stats.agent_type_elapsed_seconds

    def test_negative_elapsed_ignored(self) -> None:
        stats = _make_stats()
        stats.record_agent_elapsed_time("work", -5.0)
        assert "work" not in stats.agent_type_elapsed_seconds


# ---------------------------------------------------------------------------
# SessionStats.record_agent_stats
# ---------------------------------------------------------------------------

class TestRecordAgentStats:
    """Test SessionStats.record_agent_stats."""

    def test_aggregates_into_session(self) -> None:
        stats = _make_stats()
        item_stats = AgentStats(wall_duration=5.0, input_tokens=100)
        stats.record_agent_stats(item_stats)
        assert stats.agent_stats.wall_duration == 5.0
        assert stats.agent_stats.input_tokens == 100

    def test_multiple_accumulations(self) -> None:
        stats = _make_stats()
        stats.record_agent_stats(AgentStats(tool_calls=3))
        stats.record_agent_stats(AgentStats(tool_calls=7))
        assert stats.agent_stats.tool_calls == 10


# ---------------------------------------------------------------------------
# SessionStats.record_retries
# ---------------------------------------------------------------------------

class TestRecordRetries:
    """Test SessionStats.record_retries."""

    def test_adds_retries(self) -> None:
        stats = _make_stats()
        stats.record_retries(3)
        assert stats.agent_stats.retries == 3

    def test_negative_raises(self) -> None:
        stats = _make_stats()
        with pytest.raises(ValueError, match="cannot be negative"):
            stats.record_retries(-1)

    def test_zero_is_noop(self) -> None:
        stats = _make_stats()
        stats.record_retries(0)
        assert stats.agent_stats.retries == 0


# ---------------------------------------------------------------------------
# SessionStats.record_model_completion
# ---------------------------------------------------------------------------

class TestRecordModelCompletion:
    """Test SessionStats.record_model_completion."""

    def test_appends_completion(self) -> None:
        stats = _make_stats()
        mc = ModelCompletionRecord(item_id="i1", model="gpt-4", duration_seconds=5.0)
        stats.record_model_completion(mc)
        assert len(stats.model_completions) == 1
        assert stats.model_completions[0].item_id == "i1"

    def test_list_truncation(self) -> None:
        stats = _make_stats()
        for i in range(SessionStats.MAX_LIST_ENTRIES):
            mc = ModelCompletionRecord(
                item_id=f"i-{i}", model="m", duration_seconds=1.0,
            )
            stats.record_model_completion(mc)
        assert len(stats.model_completions) < SessionStats.MAX_LIST_ENTRIES


# ---------------------------------------------------------------------------
# SessionStats.record_janitor_lines_removed
# ---------------------------------------------------------------------------

class TestRecordJanitorLinesRemoved:
    """Test SessionStats.record_janitor_lines_removed."""

    def test_accumulates(self) -> None:
        stats = _make_stats()
        stats.record_janitor_lines_removed(10)
        stats.record_janitor_lines_removed(20)
        assert stats.janitor_lines_removed == 30


# ---------------------------------------------------------------------------
# SessionStats.set_lifetime_beads_item_totals
# ---------------------------------------------------------------------------

class TestSetLifetimeBeadsItemTotals:
    """Test SessionStats.set_lifetime_beads_item_totals."""

    def test_sets_values(self) -> None:
        stats = _make_stats()
        stats.set_lifetime_beads_item_totals(created=100, completed=50)
        assert stats.lifetime_items_created == 100
        assert stats.lifetime_items_completed == 50


# ---------------------------------------------------------------------------
# SessionStats.set_starting/ending_beads_stats
# ---------------------------------------------------------------------------

class TestBeadsStatsSetters:
    """Test set_starting_beads_stats and set_ending_beads_stats."""

    def test_set_starting(self) -> None:
        stats = _make_stats()
        bs = BeadsStats(total_issues=10, open_issues=5)
        stats.set_starting_beads_stats(bs)
        assert stats.starting_beads_stats is not None
        assert stats.starting_beads_stats.total_issues == 10
        # Verify it's a copy
        assert stats.starting_beads_stats is not bs

    def test_set_ending(self) -> None:
        stats = _make_stats()
        bs = BeadsStats(total_issues=20)
        stats.set_ending_beads_stats(bs)
        assert stats.ending_beads_stats is not None
        assert stats.ending_beads_stats.total_issues == 20

    def test_set_none(self) -> None:
        stats = _make_stats()
        stats.set_starting_beads_stats(None)
        assert stats.starting_beads_stats is None


# ---------------------------------------------------------------------------
# SessionStats.record_merge_queue_stats
# ---------------------------------------------------------------------------

class TestRecordMergeQueueStats:
    """Test SessionStats.record_merge_queue_stats."""

    def test_copies_stats(self) -> None:
        stats = _make_stats()
        mq = MergeQueueStats(total_merges=5, successful_merges=4)
        stats.record_merge_queue_stats(mq)
        assert stats.merge_queue_stats.total_merges == 5
        assert stats.merge_queue_stats.successful_merges == 4


# ---------------------------------------------------------------------------
# SessionStats.snapshot
# ---------------------------------------------------------------------------

class TestSnapshot:
    """Test SessionStats.snapshot produces a correct frozen copy."""

    def test_snapshot_returns_frozen(self) -> None:
        stats = _make_stats()
        snap = stats.snapshot()
        assert isinstance(snap, SessionStatsSnapshot)

    def test_snapshot_captures_current_state(self) -> None:
        stats = _make_stats()
        stats.record_completion(_make_item("bd-snap"))
        stats.record_created_item(_make_created("ci-snap"))
        stats.record_agent_run("work", count=2)
        stats.record_janitor_lines_removed(15)

        snap = stats.snapshot()
        assert snap.items_completed == 1
        assert snap.items_created == 1
        assert snap.agent_run_counts["work"] == 2
        assert snap.janitor_lines_removed == 15
        assert len(snap.completed_items_list) == 1
        assert len(snap.created_items_list) == 1

    def test_snapshot_is_independent_of_later_mutations(self) -> None:
        stats = _make_stats()
        stats.record_completion(_make_item())
        snap = stats.snapshot()
        stats.record_completion(_make_item("bd-2"))
        # Snapshot should still reflect the state at time of capture
        assert snap.items_completed == 1
        assert stats.items_completed == 2


# ---------------------------------------------------------------------------
# _AgentRunCountsMixin
# ---------------------------------------------------------------------------

class TestAgentRunCountsMixin:
    """Test the mixin's dynamic attribute access."""

    def test_get_agent_run_count(self) -> None:
        stats = _make_stats()
        stats.record_agent_run("work", count=3)
        assert stats.get_agent_run_count("work") == 3

    def test_dynamic_attr_access(self) -> None:
        stats = _make_stats()
        stats.record_agent_run("gate", count=2)
        assert stats.gate_agent_runs == 2  # type: ignore[attr-defined]

    def test_unknown_attr_raises(self) -> None:
        stats = _make_stats()
        with pytest.raises(AttributeError):
            _ = stats.totally_unknown_attr  # type: ignore[attr-defined]

    def test_snapshot_mixin_works(self) -> None:
        stats = _make_stats()
        stats.record_agent_run("janitor", count=4)
        snap = stats.snapshot()
        assert snap.get_agent_run_count("janitor") == 4
        assert snap.janitor_agent_runs == 4  # type: ignore[attr-defined]
