"""Unit tests for type definitions."""

import threading
import pytest
from src.pokepoke.types import (
    AgentStats, BeadsStats, BeadsWorkItem, CopilotResult, Dependency,
    ModelCompletionRecord, SessionStats, SessionStatsSnapshot,
)


def _make_item(item_id: str = "test-123") -> BeadsWorkItem:
    """Helper to create a BeadsWorkItem for testing."""
    return BeadsWorkItem(
        id=item_id, title="Test task", issue_type="task",
        status="open", priority=1, description=""
    )


class TestBeadsWorkItem:
    """Test BeadsWorkItem dataclass."""
    
    def test_create_basic_work_item(self) -> None:
        """Test creating a basic work item."""
        item = BeadsWorkItem(
            id="test-123",
            title="Test task",
            issue_type="task",
            status="open",
            priority=1,
            description=""
        )
        
        assert item.id == "test-123"
        assert item.title == "Test task"
        assert item.issue_type == "task"
        assert item.status == "open"
        assert item.priority == 1
    
    def test_create_work_item_with_description(self) -> None:
        """Test creating work item with description."""
        item = BeadsWorkItem(
            id="test-123",
            title="Test task",
            issue_type="task",
            status="open",
            priority=1,
            description="A detailed description"
        )
        
        assert item.description == "A detailed description"


class TestCopilotResult:
    """Test CopilotResult dataclass."""
    
    def test_create_successful_result(self) -> None:
        """Test creating a successful result."""
        result = CopilotResult(
            work_item_id="test-123",
            success=True,
            output="Task completed"
        )
        
        assert result.work_item_id == "test-123"
        assert result.success is True
        assert result.output == "Task completed"
        assert result.error is None
    
    def test_create_failed_result(self) -> None:
        """Test creating a failed result."""
        result = CopilotResult(
            work_item_id="test-123",
            success=False,
            error="Something went wrong"
        )
        
        assert result.success is False
        assert result.error == "Something went wrong"


class TestDependency:
    """Test Dependency dataclass."""
    
    def test_create_dependency(self) -> None:
        """Test creating a dependency."""
        dep = Dependency(
            id="dep-456",
            title="Dependency task",
            issue_type="task",
            dependency_type="blocks"
        )
        
        assert dep.id == "dep-456"
        assert dep.dependency_type == "blocks"


class TestSessionStatsRecordCompletion:
    """Test SessionStats.record_completion method."""

    def test_increments_counter(self) -> None:
        stats = SessionStats(agent_stats=AgentStats())
        result = stats.record_completion(_make_item())
        assert result == 1
        assert stats.items_completed == 1

    def test_appends_item_copy(self) -> None:
        stats = SessionStats(agent_stats=AgentStats())
        item = _make_item("item-1")
        stats.record_completion(item)
        assert len(stats.completed_items_list) == 1
        assert stats.completed_items_list[0].id == "item-1"
        assert stats.completed_items_list[0] is not item

    def test_explicit_count(self) -> None:
        stats = SessionStats(agent_stats=AgentStats())
        stats.record_completion(_make_item(), items_completed=5)
        assert stats.items_completed == 5

    def test_negative_count_raises(self) -> None:
        stats = SessionStats(agent_stats=AgentStats())
        with pytest.raises(ValueError, match="cannot be negative"):
            stats.record_completion(_make_item(), items_completed=-1)


class TestSessionStatsRecordAgentRun:
    """Test SessionStats.record_agent_run method."""

    def test_increments_work(self) -> None:
        stats = SessionStats(agent_stats=AgentStats())
        stats.record_agent_run("work")
        assert stats.work_agent_runs == 1

    def test_increments_gate(self) -> None:
        stats = SessionStats(agent_stats=AgentStats())
        stats.record_agent_run("gate", count=3)
        assert stats.gate_agent_runs == 3

    def test_case_insensitive(self) -> None:
        stats = SessionStats(agent_stats=AgentStats())
        stats.record_agent_run("Janitor")
        assert stats.janitor_agent_runs == 1

    def test_unknown_agent_raises(self) -> None:
        stats = SessionStats(agent_stats=AgentStats())
        with pytest.raises(ValueError, match="Unknown agent type"):
            stats.record_agent_run("nonexistent_agent")

    def test_negative_count_raises(self) -> None:
        stats = SessionStats(agent_stats=AgentStats())
        with pytest.raises(ValueError, match="cannot be negative"):
            stats.record_agent_run("work", count=-1)

    def test_zero_count_noop(self) -> None:
        stats = SessionStats(agent_stats=AgentStats())
        stats.record_agent_run("work", count=0)
        assert stats.work_agent_runs == 0


class TestSessionStatsRecordAgentStats:
    """Test SessionStats.record_agent_stats method."""

    def test_aggregates_all_fields(self) -> None:
        stats = SessionStats(agent_stats=AgentStats())
        item_stats = AgentStats(
            wall_duration=10.0, api_duration=5.0,
            input_tokens=100, output_tokens=50,
            lines_added=20, lines_removed=5,
            premium_requests=2, tool_calls=8, retries=1
        )
        stats.record_agent_stats(item_stats)
        assert stats.agent_stats.wall_duration == 10.0
        assert stats.agent_stats.input_tokens == 100
        assert stats.agent_stats.lines_added == 20
        assert stats.agent_stats.retries == 1

    def test_accumulates_across_calls(self) -> None:
        stats = SessionStats(agent_stats=AgentStats())
        stats.record_agent_stats(AgentStats(input_tokens=100))
        stats.record_agent_stats(AgentStats(input_tokens=200))
        assert stats.agent_stats.input_tokens == 300


class TestSessionStatsRecordRetries:
    """Test SessionStats.record_retries method."""

    def test_adds_retries(self) -> None:
        stats = SessionStats(agent_stats=AgentStats())
        stats.record_retries(3)
        assert stats.agent_stats.retries == 3

    def test_negative_raises(self) -> None:
        stats = SessionStats(agent_stats=AgentStats())
        with pytest.raises(ValueError, match="cannot be negative"):
            stats.record_retries(-1)

    def test_zero_noop(self) -> None:
        stats = SessionStats(agent_stats=AgentStats())
        stats.record_retries(0)
        assert stats.agent_stats.retries == 0


class TestSessionStatsRecordModelCompletion:
    """Test SessionStats.record_model_completion method."""

    def test_appends_record(self) -> None:
        stats = SessionStats(agent_stats=AgentStats())
        rec = ModelCompletionRecord(item_id="x", model="gpt-5", duration_seconds=10.0)
        stats.record_model_completion(rec)
        assert len(stats.model_completions) == 1
        assert stats.model_completions[0].item_id == "x"
        assert stats.model_completions[0] is not rec


class TestSessionStatsRecordJanitorLinesRemoved:
    """Test SessionStats.record_janitor_lines_removed method."""

    def test_adds_lines(self) -> None:
        stats = SessionStats(agent_stats=AgentStats())
        stats.record_janitor_lines_removed(25)
        assert stats.janitor_lines_removed == 25

    def test_accumulates(self) -> None:
        stats = SessionStats(agent_stats=AgentStats())
        stats.record_janitor_lines_removed(10)
        stats.record_janitor_lines_removed(15)
        assert stats.janitor_lines_removed == 25


class TestSessionStatsBeadsStats:
    """Test SessionStats.set_starting_beads_stats and set_ending_beads_stats."""

    def test_set_starting(self) -> None:
        stats = SessionStats(agent_stats=AgentStats())
        bs = BeadsStats(total_issues=10, open_issues=5)
        stats.set_starting_beads_stats(bs)
        assert stats.starting_beads_stats is not None
        assert stats.starting_beads_stats.total_issues == 10
        assert stats.starting_beads_stats is not bs

    def test_set_ending(self) -> None:
        stats = SessionStats(agent_stats=AgentStats())
        bs = BeadsStats(total_issues=12, closed_issues=7)
        stats.set_ending_beads_stats(bs)
        assert stats.ending_beads_stats is not None
        assert stats.ending_beads_stats.closed_issues == 7

    def test_set_none(self) -> None:
        stats = SessionStats(agent_stats=AgentStats())
        stats.set_starting_beads_stats(BeadsStats())
        stats.set_starting_beads_stats(None)
        assert stats.starting_beads_stats is None


class TestSessionStatsSnapshot:
    """Test SessionStats.snapshot method."""

    def test_returns_frozen_copy(self) -> None:
        stats = SessionStats(agent_stats=AgentStats(input_tokens=42))
        stats.record_completion(_make_item("a"))
        stats.record_agent_run("work")
        snap = stats.snapshot()
        assert isinstance(snap, SessionStatsSnapshot)
        assert snap.items_completed == 1
        assert snap.work_agent_runs == 1
        assert snap.agent_stats.input_tokens == 42

    def test_snapshot_is_frozen(self) -> None:
        stats = SessionStats(agent_stats=AgentStats())
        snap = stats.snapshot()
        with pytest.raises(AttributeError):
            snap.items_completed = 99  # type: ignore[misc]

    def test_snapshot_independent_of_source(self) -> None:
        stats = SessionStats(agent_stats=AgentStats(input_tokens=10))
        snap = stats.snapshot()
        stats.record_agent_stats(AgentStats(input_tokens=100))
        assert snap.agent_stats.input_tokens == 10

    def test_completed_items_as_tuple(self) -> None:
        stats = SessionStats(agent_stats=AgentStats())
        stats.record_completion(_make_item("a"))
        snap = stats.snapshot()
        assert isinstance(snap.completed_items_list, tuple)
        assert len(snap.completed_items_list) == 1


class TestSessionStatsThreadSafety:
    """Test concurrent access to SessionStats."""

    def test_concurrent_record_completion(self) -> None:
        stats = SessionStats(agent_stats=AgentStats())
        errors: list[Exception] = []

        def worker(n: int) -> None:
            try:
                for _ in range(100):
                    stats.record_completion(_make_item(f"item-{n}"))
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert stats.items_completed == 500
        assert len(stats.completed_items_list) == 500

    def test_concurrent_record_agent_run(self) -> None:
        stats = SessionStats(agent_stats=AgentStats())
        errors: list[Exception] = []

        def worker() -> None:
            try:
                for _ in range(100):
                    stats.record_agent_run("work")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert stats.work_agent_runs == 500

    def test_concurrent_snapshot_with_mutations(self) -> None:
        stats = SessionStats(agent_stats=AgentStats())
        errors: list[Exception] = []
        snapshots: list[SessionStatsSnapshot] = []

        def mutator() -> None:
            try:
                for _ in range(100):
                    stats.record_agent_stats(AgentStats(input_tokens=1))
            except Exception as e:
                errors.append(e)

        def reader() -> None:
            try:
                for _ in range(100):
                    snapshots.append(stats.snapshot())
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=mutator) for _ in range(3)]
        threads += [threading.Thread(target=reader) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert stats.agent_stats.input_tokens == 300
        assert len(snapshots) == 200
