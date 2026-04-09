"""Unit tests for type definitions."""

import threading

import pytest

from pokepoke.types import (
    AgentStats,
    BeadsStats,
    BeadsWorkItem,
    CopilotResult,
    Dependency,
    ModelCompletionRecord,
    SessionStats,
    SessionStatsSnapshot,
)


def _make_item(item_id: str = "test-123", title: str = "Test task") -> BeadsWorkItem:
    """Create a basic BeadsWorkItem for testing."""
    return BeadsWorkItem(
        id=item_id,
        title=title,
        issue_type="task",
        status="open",
        priority=1,
        description=""
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

    def test_is_ephemeral_defaults_to_false(self) -> None:
        """Test that is_ephemeral defaults to False for real beads items."""
        item = _make_item()
        assert item.is_ephemeral is False

    def test_is_ephemeral_can_be_set_true(self) -> None:
        """Test that is_ephemeral can be explicitly set to True."""
        item = BeadsWorkItem(
            id="task-1-cleanup",
            title="Cleanup",
            issue_type="task",
            status="in_progress",
            priority=0,
            description="",
            is_ephemeral=True,
        )
        assert item.is_ephemeral is True


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

    def test_work_agent_outcome_default_none(self):
        from pokepoke.types import CopilotResult
        result = CopilotResult(work_item_id="test", success=True)
        assert result.work_agent_outcome is None


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


class TestSessionStats:
    """Test SessionStats thread-safe methods."""

    def test_record_completion_increments_and_copies(self) -> None:
        """Test recording a completed item copies the work item."""
        stats = SessionStats(agent_stats=AgentStats())
        item = _make_item()

        count = stats.record_completion(item)

        assert count == 1
        assert stats.items_completed == 1
        assert stats.completed_items_list[0] == item
        assert stats.completed_items_list[0] is not item

        item.title = "Updated title"
        assert stats.completed_items_list[0].title == "Test task"

    def test_record_completion_validates_explicit_count(self) -> None:
        """Test record_completion handles explicit counts and validation."""
        stats = SessionStats(agent_stats=AgentStats())
        item = _make_item()

        count = stats.record_completion(item, items_completed=5)

        assert count == 5
        assert stats.items_completed == 5

        with pytest.raises(ValueError):
            stats.record_completion(item, items_completed=-1)

        assert len(stats.completed_items_list) == 1

    def test_record_agent_run_increments_known_types(self) -> None:
        """Test agent run counts increment with normalization."""
        stats = SessionStats(agent_stats=AgentStats())

        stats.record_agent_run("Janitor")
        stats.record_agent_run("Worktree Cleanup", count=2)
        stats.record_agent_run("Janitor", count=0)

        assert stats.janitor_agent_runs == 1
        assert stats.worktree_cleanup_agent_runs == 2

    def test_record_agent_run_rejects_invalid_input(self) -> None:
        """Test agent run validation rejects invalid values."""
        stats = SessionStats(agent_stats=AgentStats())

        with pytest.raises(ValueError):
            stats.record_agent_run("Unknown Agent")

        with pytest.raises(ValueError):
            stats.record_agent_run("Janitor", count=-1)

    def test_record_agent_stats_and_retries(self) -> None:
        """Test agent stats aggregation and retry tracking."""
        stats = SessionStats(agent_stats=AgentStats())
        item_stats = AgentStats(
            wall_duration=1.5,
            api_duration=2.5,
            input_tokens=3,
            output_tokens=4,
            lines_added=5,
            lines_removed=6,
            premium_requests=1,
            retries=2,
            tool_calls=7,
        )

        stats.record_agent_stats(item_stats)
        stats.record_retries(3)

        assert stats.agent_stats.wall_duration == 1.5
        assert stats.agent_stats.api_duration == 2.5
        assert stats.agent_stats.input_tokens == 3
        assert stats.agent_stats.output_tokens == 4
        assert stats.agent_stats.lines_added == 5
        assert stats.agent_stats.lines_removed == 6
        assert stats.agent_stats.premium_requests == 1
        assert stats.agent_stats.tool_calls == 7
        assert stats.agent_stats.retries == 5

        stats.record_retries(0)
        assert stats.agent_stats.retries == 5

        with pytest.raises(ValueError):
            stats.record_retries(-1)

    def test_record_model_completion_copies(self) -> None:
        """Test model completion records are copied."""
        stats = SessionStats(agent_stats=AgentStats())
        completion = ModelCompletionRecord(
            item_id="item-1",
            model="model-a",
            duration_seconds=3.2,
            gate_passed=True,
        )

        stats.record_model_completion(completion)

        assert len(stats.model_completions) == 1
        assert stats.model_completions[0] == completion
        assert stats.model_completions[0] is not completion

        completion.model = "model-b"
        assert stats.model_completions[0].model == "model-a"

    def test_record_janitor_lines_removed_and_beads_stats(self) -> None:
        """Test janitor lines removed tracking and beads stats setters."""
        stats = SessionStats(agent_stats=AgentStats())
        stats.record_janitor_lines_removed(12)

        assert stats.janitor_lines_removed == 12

        starting = BeadsStats(total_issues=10, ready_issues=2)
        stats.set_starting_beads_stats(starting)
        assert stats.starting_beads_stats == starting
        assert stats.starting_beads_stats is not starting

        starting.total_issues = 99
        assert stats.starting_beads_stats.total_issues == 10

        ending = BeadsStats(total_issues=5, ready_issues=1)
        stats.set_ending_beads_stats(ending)
        assert stats.ending_beads_stats == ending
        assert stats.ending_beads_stats is not ending

        stats.set_ending_beads_stats(None)
        assert stats.ending_beads_stats is None

    def test_snapshot_returns_frozen_copy(self) -> None:
        """Test snapshot returns immutable copies of stats."""
        stats = SessionStats(agent_stats=AgentStats())
        stats.record_agent_run("Janitor")
        stats.record_completion(_make_item())
        stats.record_model_completion(
            ModelCompletionRecord(
                item_id="item-1",
                model="model-a",
                duration_seconds=1.0,
            )
        )

        snapshot = stats.snapshot()

        assert isinstance(snapshot, SessionStatsSnapshot)
        assert snapshot.items_completed == 1
        assert snapshot.janitor_agent_runs == 1
        assert isinstance(snapshot.completed_items_list, tuple)
        assert isinstance(snapshot.model_completions, tuple)
        assert snapshot.agent_stats is not stats.agent_stats

        stats.record_agent_run("Janitor")
        assert snapshot.janitor_agent_runs == 1

    def test_thread_safe_updates_with_multiple_threads(self) -> None:
        """Test concurrent updates do not lose increments."""
        stats = SessionStats(agent_stats=AgentStats())

        def worker() -> None:
            for _ in range(50):
                stats.record_agent_run("Janitor")

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert stats.janitor_agent_runs == 200

    def test_completed_items_list_evicts_oldest_half_at_max(self) -> None:
        """Test that completed_items_list evicts oldest half when reaching MAX_LIST_ENTRIES."""
        max_entries = 20
        stats = SessionStats(agent_stats=AgentStats())
        stats.MAX_LIST_ENTRIES = max_entries

        for i in range(max_entries):
            stats.record_completion(_make_item(item_id=f"item-{i}"))

        # After reaching max, oldest half (10) is evicted leaving 10
        assert len(stats.completed_items_list) == max_entries // 2
        # The oldest items should be gone, newest should remain
        ids = [item.id for item in stats.completed_items_list]
        assert "item-0" not in ids
        assert f"item-{max_entries - 1}" in ids

    def test_created_items_list_evicts_oldest_half_at_max(self) -> None:
        """Test that created_items_list evicts oldest half when reaching MAX_LIST_ENTRIES."""
        from pokepoke.types import BeadsCreatedItem
        max_entries = 20
        stats = SessionStats(agent_stats=AgentStats())
        stats.MAX_LIST_ENTRIES = max_entries

        for i in range(max_entries):
            stats.record_created_item(BeadsCreatedItem(id=f"created-{i}", title=f"Item {i}"))

        assert len(stats.created_items_list) == max_entries // 2
        ids = [item.id for item in stats.created_items_list]
        assert "created-0" not in ids
        assert f"created-{max_entries - 1}" in ids

    def test_model_completions_evicts_oldest_half_at_max(self) -> None:
        """Test that model_completions evicts oldest half when reaching MAX_LIST_ENTRIES."""
        max_entries = 20
        stats = SessionStats(agent_stats=AgentStats())
        stats.MAX_LIST_ENTRIES = max_entries

        for i in range(max_entries):
            stats.record_model_completion(
                ModelCompletionRecord(item_id=f"mc-{i}", model="model-a", duration_seconds=1.0)
            )

        assert len(stats.model_completions) == max_entries // 2
        ids = [mc.item_id for mc in stats.model_completions]
        assert "mc-0" not in ids
        assert f"mc-{max_entries - 1}" in ids

    def test_eviction_preserves_counters(self) -> None:
        """Test that eviction trims lists but does not affect scalar counters."""
        max_entries = 10
        stats = SessionStats(agent_stats=AgentStats())
        stats.MAX_LIST_ENTRIES = max_entries

        for i in range(max_entries + 5):
            stats.record_completion(_make_item(item_id=f"item-{i}"))

        # items_completed counter should still reflect total, not list length
        assert stats.items_completed == max_entries + 5
        assert len(stats.completed_items_list) < max_entries

class TestWorkAgentOutcome:
    """Tests for the WorkAgentOutcome dataclass."""

    def test_valid_completed_status(self):
        from pokepoke.types import WorkAgentOutcome
        outcome = WorkAgentOutcome(status="completed", reason="All done")
        assert outcome.status == "completed"
        assert outcome.reason == "All done"

    def test_valid_blocked_status(self):
        from pokepoke.types import WorkAgentOutcome
        outcome = WorkAgentOutcome(status="blocked", reason="Missing dep")
        assert outcome.status == "blocked"

    def test_valid_needs_clarification(self):
        from pokepoke.types import WorkAgentOutcome
        outcome = WorkAgentOutcome(status="needs_clarification")
        assert outcome.status == "needs_clarification"

    def test_valid_too_large(self):
        from pokepoke.types import WorkAgentOutcome
        outcome = WorkAgentOutcome(status="too_large", suggested_split=["a", "b"])
        assert outcome.suggested_split == ["a", "b"]

    def test_invalid_status_raises(self):
        import pytest

        from pokepoke.types import WorkAgentOutcome
        with pytest.raises(ValueError, match="Invalid work agent outcome status"):
            WorkAgentOutcome(status="invalid_status")

    def test_default_fields(self):
        from pokepoke.types import WorkAgentOutcome
        outcome = WorkAgentOutcome(status="completed")
        assert outcome.reason == ""
        assert outcome.files_modified == []
        assert outcome.tests_added == []
        assert outcome.suggested_split == []

    def test_files_modified_and_tests_added(self):
        from pokepoke.types import WorkAgentOutcome
        outcome = WorkAgentOutcome(
            status="completed",
            files_modified=["a.py", "b.py"],
            tests_added=["test_a.py"],
        )
        assert outcome.files_modified == ["a.py", "b.py"]
        assert outcome.tests_added == ["test_a.py"]


class TestParseWorkAgentOutcome:
    """Tests for parse_work_agent_outcome()."""

    def test_returns_none_for_none_input(self):
        from pokepoke.types import parse_work_agent_outcome
        assert parse_work_agent_outcome(None) is None

    def test_returns_none_for_empty_string(self):
        from pokepoke.types import parse_work_agent_outcome
        assert parse_work_agent_outcome("") is None

    def test_returns_none_for_no_json_blocks(self):
        from pokepoke.types import parse_work_agent_outcome
        assert parse_work_agent_outcome("just some text") is None

    def test_parses_completed_outcome(self):
        from pokepoke.types import parse_work_agent_outcome
        output = '''Some text
```json
{"status": "completed", "reason": "All tasks done", "files_modified": ["a.py"]}
```
'''
        result = parse_work_agent_outcome(output)
        assert result is not None
        assert result.status == "completed"
        assert result.reason == "All tasks done"
        assert result.files_modified == ["a.py"]

    def test_parses_blocked_outcome(self):
        from pokepoke.types import parse_work_agent_outcome
        output = '''```json
{"status": "blocked", "reason": "Need API key"}
```'''
        result = parse_work_agent_outcome(output)
        assert result is not None
        assert result.status == "blocked"
        assert result.reason == "Need API key"

    def test_parses_too_large_with_split(self):
        from pokepoke.types import parse_work_agent_outcome
        output = '''```json
{"status": "too_large", "reason": "Too many changes", "suggested_split": ["part1", "part2"]}
```'''
        result = parse_work_agent_outcome(output)
        assert result is not None
        assert result.status == "too_large"
        assert result.suggested_split == ["part1", "part2"]

    def test_uses_last_matching_json_block(self):
        from pokepoke.types import parse_work_agent_outcome
        output = '''```json
{"status": "blocked", "reason": "first"}
```
Some work...
```json
{"status": "completed", "reason": "final"}
```'''
        result = parse_work_agent_outcome(output)
        assert result is not None
        assert result.status == "completed"
        assert result.reason == "final"

    def test_skips_non_outcome_json(self):
        from pokepoke.types import parse_work_agent_outcome
        output = '''```json
{"name": "test", "value": 42}
```
```json
{"status": "completed", "reason": "done"}
```'''
        result = parse_work_agent_outcome(output)
        assert result is not None
        assert result.status == "completed"

    def test_skips_invalid_json(self):
        from pokepoke.types import parse_work_agent_outcome
        output = '''```json
{invalid json here}
```
```json
{"status": "completed"}
```'''
        result = parse_work_agent_outcome(output)
        assert result is not None
        assert result.status == "completed"

    def test_returns_none_for_unknown_status(self):
        from pokepoke.types import parse_work_agent_outcome
        output = '''```json
{"status": "unknown_status", "reason": "test"}
```'''
        assert parse_work_agent_outcome(output) is None

    def test_coerces_non_list_fields(self):
        from pokepoke.types import parse_work_agent_outcome
        output = '''```json
{"status": "completed", "files_modified": "not_a_list", "tests_added": 42}
```'''
        result = parse_work_agent_outcome(output)
        assert result is not None
        assert result.files_modified == []
        assert result.tests_added == []

    def test_case_insensitive_json_fence(self):
        from pokepoke.types import parse_work_agent_outcome
        output = '''```JSON
{"status": "completed", "reason": "done"}
```'''
        result = parse_work_agent_outcome(output)
        assert result is not None
        assert result.status == "completed"

    def test_process_monitor_lines_stripped_from_json(self):
        """ProcessMonitor lines interleaved in JSON block should be stripped."""
        from pokepoke.types import parse_work_agent_outcome
        output = (
            '```json\n'
            '{\n'
            '  "status": "completed",\n'
            '[ProcessMonitor] PID 12345 (pytest.exe) active - wrote 2048 bytes\n'
            '  "reason": "All tests pass",\n'
            '  "files_modified": ["src/foo.py"]\n'
            '}\n'
            '```'
        )
        result = parse_work_agent_outcome(output)
        assert result is not None
        assert result.status == "completed"
        assert result.reason == "All tests pass"
        assert result.files_modified == ["src/foo.py"]
