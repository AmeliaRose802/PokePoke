"""Contract tests between beads types and workflow modules.

Validates that BeadsWorkItem produced by BeadsClient flows correctly through
work_item_selection and that WorkItemResult contains every field consumed by
the orchestrator's _record_item_result and session-stats recording helpers.
"""

from __future__ import annotations

import dataclasses
from unittest.mock import patch

import pytest

from pokepoke.orchestration.work_item_selection import (
    _exceeds_gate_rejection_cap,
    _filter_skip_ids,
    _is_blocked,
    _is_closed,
    _is_human_required,
    select_work_item,
)
from pokepoke.types import (
    AgentStats,
    BeadsWorkItem,
    ModelCompletionRecord,
    WorkItemResult,
)
from tests.fakes import FakeBeadsClient

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _item(**overrides) -> BeadsWorkItem:
    """Create a BeadsWorkItem with sensible defaults, applying *overrides*."""
    defaults = dict(
        id="item-1",
        title="A task",
        status="open",
        priority=1,
        issue_type="task",
    )
    defaults.update(overrides)
    return BeadsWorkItem(**defaults)


# ---------------------------------------------------------------------------
# 1. BeadsWorkItem ➜ work_item_selection contract
# ---------------------------------------------------------------------------


class TestBeadsWorkItemThroughSelection:
    """BeadsWorkItem with various field combos passes through select_work_item."""

    @patch("pokepoke.orchestration.work_item_selection.select_next_hierarchical_item")
    @patch("pokepoke.orchestration.work_item_selection.is_assigned_to_current_user", return_value=True)
    def test_minimal_item_selected(self, _assigned, mock_select):
        """An item with only required fields is selected in autonomous mode."""
        item = _item()
        mock_select.return_value = item
        result = select_work_item([item], interactive=False)
        assert result is item

    @patch("pokepoke.orchestration.work_item_selection.select_next_hierarchical_item")
    @patch("pokepoke.orchestration.work_item_selection.is_assigned_to_current_user", return_value=True)
    def test_fully_populated_item_selected(self, _assigned, mock_select):
        """An item with every optional field populated is accepted."""
        item = _item(
            description="Long description",
            owner="alice",
            assignee=None,
            created_at="2025-01-01T00:00:00Z",
            created_by="bob",
            updated_at="2025-06-01T00:00:00Z",
            labels=["tests", "coverage"],
            metadata={"gate_rejection_count": 0, "custom": True},
            is_ephemeral=False,
        )
        mock_select.return_value = item
        result = select_work_item([item], interactive=False)
        assert result is item

    @patch("pokepoke.orchestration.work_item_selection.select_next_hierarchical_item")
    @patch("pokepoke.orchestration.work_item_selection.is_assigned_to_current_user", return_value=True)
    def test_ephemeral_item_accepted(self, _assigned, mock_select):
        """Synthetic/ephemeral items flow through selection."""
        item = _item(is_ephemeral=True, id="ephemeral-cleanup")
        mock_select.return_value = item
        result = select_work_item([item], interactive=False)
        assert result is item

    @patch("pokepoke.orchestration.work_item_selection.select_next_hierarchical_item")
    @patch("pokepoke.orchestration.work_item_selection.is_assigned_to_current_user", return_value=True)
    def test_none_optional_fields_accepted(self, _assigned, mock_select):
        """All optional fields set to None are handled without error."""
        item = _item(
            description=None,
            owner=None,
            assignee=None,
            created_at=None,
            created_by=None,
            updated_at=None,
            labels=None,
            metadata=None,
        )
        mock_select.return_value = item
        result = select_work_item([item], interactive=False)
        assert result is item

    def test_closed_item_filtered(self):
        """Items with status='closed' are filtered out."""
        assert _is_closed(_item(status="closed")) is True
        assert _is_closed(_item(status="open")) is False

    def test_blocked_item_filtered(self):
        """Items with status='blocked' are filtered out."""
        assert _is_blocked(_item(status="blocked")) is True
        assert _is_blocked(_item(status="open")) is False

    def test_human_required_label_filtered(self):
        """Items with 'human-required' label are filtered."""
        assert _is_human_required(_item(labels=["human-required"])) is True
        assert _is_human_required(_item(labels=["tests"])) is False
        assert _is_human_required(_item(labels=None)) is False

    @pytest.mark.parametrize(
        "metadata, max_rej, expected",
        [
            ({"gate_rejection_count": 5}, 5, True),
            ({"gate_rejection_count": 4}, 5, False),
            ({"gate_rejection_count": 0}, 1, False),
            (None, 5, False),
            ({}, 5, False),
            ({"gate_rejection_count": "bad"}, 5, False),
        ],
        ids=[
            "at_cap",
            "below_cap",
            "zero_count",
            "no_metadata",
            "empty_metadata",
            "non_numeric_count",
        ],
    )
    def test_gate_rejection_cap(self, metadata, max_rej, expected):
        """_exceeds_gate_rejection_cap correctly reads metadata."""
        item = _item(metadata=metadata)
        assert _exceeds_gate_rejection_cap(item, max_rej) is expected

    def test_filter_skip_ids_removes_matching(self):
        """_filter_skip_ids removes items whose id is in skip_ids."""
        items = [_item(id="a"), _item(id="b"), _item(id="c")]
        result = _filter_skip_ids(items, {"a", "c"})
        assert [i.id for i in result] == ["b"]

    def test_filter_skip_ids_noop_when_none(self):
        """_filter_skip_ids returns all items when skip_ids is None."""
        items = [_item(id="a"), _item(id="b")]
        result = _filter_skip_ids(items, None)
        assert len(result) == 2

    def test_filter_skip_ids_noop_when_empty(self):
        """_filter_skip_ids returns all items when skip_ids is empty set."""
        items = [_item(id="a")]
        result = _filter_skip_ids(items, set())
        assert len(result) == 1


# ---------------------------------------------------------------------------
# 2. FakeBeadsClient return types ➜ workflow contract
# ---------------------------------------------------------------------------


class TestBeadsClientReturnsMatchWorkflow:
    """FakeBeadsClient produces types that process_work_item / select_work_item accept."""

    def test_get_ready_returns_list_of_beads_work_items(self):
        """get_ready_work_items returns a list[BeadsWorkItem]."""
        client = FakeBeadsClient()
        client.add_item(_item(id="a"))
        client.add_item(_item(id="b", status="open"))
        result = client.get_ready_work_items()
        assert isinstance(result, list)
        assert all(isinstance(i, BeadsWorkItem) for i in result)

    def test_ready_items_have_required_fields_for_selection(self):
        """Every item returned has the fields select_work_item inspects."""
        client = FakeBeadsClient()
        client.add_item(_item(id="x", labels=["tests"], metadata={"gate_rejection_count": 0}))
        items = client.get_ready_work_items()
        for item in items:
            assert hasattr(item, "id")
            assert hasattr(item, "status")
            assert hasattr(item, "priority")
            assert hasattr(item, "labels")
            assert hasattr(item, "metadata")
            assert hasattr(item, "assignee")

    @patch("pokepoke.orchestration.work_item_selection.select_next_hierarchical_item")
    @patch("pokepoke.orchestration.work_item_selection.is_assigned_to_current_user", return_value=True)
    def test_client_items_pass_through_select_work_item(self, _assigned, mock_select):
        """Items from FakeBeadsClient flow through select_work_item without error."""
        client = FakeBeadsClient()
        client.add_item(_item(id="c1", priority=2))
        client.add_item(_item(id="c2", priority=1))
        items = client.get_ready_work_items()
        mock_select.return_value = items[0]
        result = select_work_item(items, interactive=False)
        assert result is not None
        assert isinstance(result, BeadsWorkItem)

    def test_process_work_item_signature_accepts_beads_types(self):
        """process_work_item accepts BeadsWorkItem and BeadsClient arguments.

        We only verify the signature is compatible — actually calling
        process_work_item requires heavy mocking of worktree/copilot
        subsystems which is out of scope for this contract test.
        """
        import inspect

        from pokepoke.orchestration.workflow import process_work_item

        sig = inspect.signature(process_work_item)
        params = sig.parameters

        # First positional param must accept BeadsWorkItem
        assert "item" in params
        ann = params["item"].annotation
        assert ann is BeadsWorkItem or (isinstance(ann, str) and "BeadsWorkItem" in ann)

        # beads_client keyword accepts BeadsClient | None
        assert "beads_client" in params


# ---------------------------------------------------------------------------
# 3. WorkItemResult contract for workflow consumers
# ---------------------------------------------------------------------------


class TestWorkItemResultContract:
    """WorkItemResult has every field that orchestrator consumers read."""

    # Fields accessed by _record_item_result in orchestrator.py
    _CONSUMED_FIELDS = {
        "success",
        "request_count",
        "stats",
        "cleanup_agent_runs",
        "gate_agent_runs",
        "model_completion",
        "failure_reason",
    }

    def test_all_consumed_fields_exist(self):
        """WorkItemResult dataclass has every field the orchestrator accesses."""
        field_names = {f.name for f in dataclasses.fields(WorkItemResult)}
        missing = self._CONSUMED_FIELDS - field_names
        assert not missing, f"WorkItemResult missing fields: {missing}"

    def test_success_result_shape(self):
        """A successful WorkItemResult has expected defaults."""
        result = WorkItemResult(success=True, request_count=1)
        assert result.success is True
        assert result.request_count == 1
        assert result.stats is None
        assert result.cleanup_agent_runs == 0
        assert result.gate_agent_runs == 0
        assert result.model_completion is None
        assert result.failure_reason is None

    def test_failure_result_shape(self):
        """A failed WorkItemResult can carry failure metadata."""
        result = WorkItemResult(
            success=False,
            request_count=3,
            stats=AgentStats(wall_duration=120.0, input_tokens=500),
            cleanup_agent_runs=1,
            gate_agent_runs=2,
            failure_reason="Gate agent rejected changes",
        )
        assert result.success is False
        assert result.request_count == 3
        assert result.stats is not None
        assert result.stats.wall_duration == 120.0
        assert result.cleanup_agent_runs == 1
        assert result.gate_agent_runs == 2
        assert result.failure_reason == "Gate agent rejected changes"

    def test_result_with_model_completion(self):
        """WorkItemResult carries ModelCompletionRecord for A/B tracking."""
        mc = ModelCompletionRecord(
            item_id="t-1",
            model="gpt-4",
            duration_seconds=60.0,
            gate_passed=True,
            input_tokens=100,
            output_tokens=50,
        )
        result = WorkItemResult(
            success=True,
            request_count=1,
            model_completion=mc,
        )
        assert result.model_completion is mc
        assert result.model_completion.gate_passed is True
        assert result.model_completion.model == "gpt-4"

    def test_stats_accumulate_compatible(self):
        """AgentStats.accumulate works with stats from WorkItemResult."""
        session_stats = AgentStats()
        item_stats = AgentStats(
            wall_duration=10.0,
            api_duration=5.0,
            input_tokens=200,
            output_tokens=100,
            lines_added=50,
            lines_removed=10,
            retries=1,
        )
        result = WorkItemResult(success=True, request_count=1, stats=item_stats)
        session_stats.accumulate(result.stats)
        assert session_stats.wall_duration == 10.0
        assert session_stats.input_tokens == 200
        assert session_stats.retries == 1

    def test_agent_stats_all_fields_exist(self):
        """AgentStats dataclass has every field that accumulate touches."""
        expected_fields = {
            "wall_duration", "api_duration", "input_tokens", "output_tokens",
            "lines_added", "lines_removed", "premium_requests", "retries",
            "tool_calls",
        }
        actual_fields = {f.name for f in dataclasses.fields(AgentStats)}
        missing = expected_fields - actual_fields
        assert not missing, f"AgentStats missing fields: {missing}"

    def test_agent_stats_accumulate_all_fields(self):
        """accumulate sums every numeric field, not just a subset."""
        a = AgentStats()
        b = AgentStats(
            wall_duration=1.0, api_duration=2.0,
            input_tokens=3, output_tokens=4,
            lines_added=5, lines_removed=6,
            premium_requests=7, retries=8, tool_calls=9,
        )
        a.accumulate(b)
        assert a.wall_duration == 1.0
        assert a.api_duration == 2.0
        assert a.input_tokens == 3
        assert a.output_tokens == 4
        assert a.lines_added == 5
        assert a.lines_removed == 6
        assert a.premium_requests == 7
        assert a.retries == 8
        assert a.tool_calls == 9

    def test_model_completion_record_all_fields_exist(self):
        """ModelCompletionRecord has every field workflow consumers read."""
        expected_fields = {
            "item_id", "model", "duration_seconds", "gate_passed",
            "input_tokens", "output_tokens", "agent_turns", "cost",
            "retry_attempts", "api_duration", "lines_added",
            "lines_removed", "gate_model",
        }
        actual_fields = {f.name for f in dataclasses.fields(ModelCompletionRecord)}
        missing = expected_fields - actual_fields
        assert not missing, f"ModelCompletionRecord missing fields: {missing}"


# ---------------------------------------------------------------------------
# 4. Round-trip: FakeBeadsClient ➜ selection ➜ result recording shape
# ---------------------------------------------------------------------------


class TestEndToEndContractShape:
    """Full round-trip: items from beads client, selected, result recorded."""

    @patch("pokepoke.orchestration.work_item_selection.select_next_hierarchical_item")
    @patch("pokepoke.orchestration.work_item_selection.is_assigned_to_current_user", return_value=True)
    def test_selected_item_is_valid_for_result_recording(self, _assigned, mock_select):
        """The BeadsWorkItem returned by selection has everything needed to
        construct a WorkItemResult and record it in SessionStats.
        """
        client = FakeBeadsClient()
        client.add_item(_item(
            id="round-trip-1",
            title="Round-trip test",
            priority=1,
            issue_type="task",
            labels=["tests"],
        ))
        items = client.get_ready_work_items()
        mock_select.return_value = items[0]
        selected = select_work_item(items, interactive=False)
        assert selected is not None

        # Build a WorkItemResult like workflow.py would
        result = WorkItemResult(
            success=True,
            request_count=1,
            stats=AgentStats(wall_duration=30.0),
            cleanup_agent_runs=0,
            gate_agent_runs=1,
        )
        # Verify all consumed fields are accessible (no AttributeError)
        assert isinstance(result.success, bool)
        assert isinstance(result.request_count, int)
        assert result.stats.wall_duration == 30.0
        assert isinstance(result.cleanup_agent_runs, int)
        assert isinstance(result.gate_agent_runs, int)
        assert result.failure_reason is None

    def test_multiple_issue_types_accepted(self):
        """selection accepts all common beads issue types without filtering."""
        client = FakeBeadsClient()
        for itype in ("task", "bug", "feature", "chore", "improvement"):
            client.add_item(_item(id=f"{itype}-1", issue_type=itype))
        items = client.get_ready_work_items()
        assert len(items) == 5
        # All items have the correct type stored
        types = {i.issue_type for i in items}
        assert types == {"task", "bug", "feature", "chore", "improvement"}

    def test_priority_ordering_preserved(self):
        """FakeBeadsClient select_next_hierarchical_item picks lowest priority."""
        client = FakeBeadsClient()
        client.add_item(_item(id="low", priority=5))
        client.add_item(_item(id="high", priority=1))
        client.add_item(_item(id="mid", priority=3))
        items = client.get_ready_work_items()
        selected = client.select_next_hierarchical_item(items)
        assert selected is not None
        assert selected.id == "high"
        assert selected.priority == 1
