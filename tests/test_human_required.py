"""Tests for the human-required label filtering.

Items labeled 'human-required' should be skipped by PokePoke in all
selection paths: top-level filtering, hierarchical selection, and
child task selection.
"""

from unittest.mock import Mock, patch
import pytest

from src.pokepoke.types import BeadsWorkItem
from src.pokepoke.work_item_selection import (
    select_work_item,
    _is_human_required,
    HUMAN_REQUIRED_LABEL,
)
from src.pokepoke.beads_management import select_next_hierarchical_item
from src.pokepoke.beads_hierarchy import get_next_child_task


def _make_item(
    id: str = "task-1",
    title: str = "Task",
    status: str = "open",
    priority: int = 1,
    issue_type: str = "task",
    labels: list[str] | None = None,
    **kwargs,
) -> BeadsWorkItem:
    """Helper to create a BeadsWorkItem with defaults."""
    return BeadsWorkItem(
        id=id,
        title=title,
        description="",
        status=status,
        priority=priority,
        issue_type=issue_type,
        labels=labels,
        **kwargs,
    )


class TestIsHumanRequired:
    """Tests for the _is_human_required helper."""

    def test_no_labels(self) -> None:
        item = _make_item(labels=None)
        assert _is_human_required(item) is False

    def test_empty_labels(self) -> None:
        item = _make_item(labels=[])
        assert _is_human_required(item) is False

    def test_unrelated_labels(self) -> None:
        item = _make_item(labels=["backend", "urgent"])
        assert _is_human_required(item) is False

    def test_human_required_label_present(self) -> None:
        item = _make_item(labels=["human-required"])
        assert _is_human_required(item) is True

    def test_human_required_among_other_labels(self) -> None:
        item = _make_item(labels=["backend", "human-required", "urgent"])
        assert _is_human_required(item) is True


class TestSelectWorkItemHumanRequired:
    """Tests for human-required filtering in select_work_item."""

    @patch("src.pokepoke.work_item_selection.select_next_hierarchical_item")
    def test_human_required_items_filtered_out(
        self, mock_hierarchical: Mock
    ) -> None:
        """Human-required items should be excluded before selection."""
        human_item = _make_item(
            id="hr-1", title="Needs human", labels=["human-required"]
        )
        normal_item = _make_item(id="task-1", title="Normal task")
        mock_hierarchical.return_value = normal_item

        result = select_work_item([human_item, normal_item], interactive=False)

        # The hierarchical selector should only see the normal item
        called_items = mock_hierarchical.call_args[0][0]
        assert len(called_items) == 1
        assert called_items[0].id == "task-1"
        assert result is not None
        assert result.id == "task-1"

    @patch("src.pokepoke.work_item_selection.select_next_hierarchical_item")
    def test_all_items_human_required_returns_none(
        self, mock_hierarchical: Mock
    ) -> None:
        """When all items are human-required, select_work_item returns None."""
        items = [
            _make_item(id="hr-1", labels=["human-required"]),
            _make_item(id="hr-2", labels=["human-required"]),
        ]

        result = select_work_item(items, interactive=False)

        assert result is None
        mock_hierarchical.assert_not_called()

    @patch("builtins.print")
    @patch("src.pokepoke.work_item_selection.select_next_hierarchical_item")
    def test_human_required_skip_message_printed(
        self, mock_hierarchical: Mock, mock_print: Mock
    ) -> None:
        """A skip message should be printed for each human-required item."""
        items = [
            _make_item(id="hr-1", labels=["human-required"]),
            _make_item(id="task-1"),
        ]
        mock_hierarchical.return_value = items[1]

        select_work_item(items, interactive=False)

        printed = [str(c) for c in mock_print.call_args_list]
        assert any("hr-1" in msg and "human-required" in msg for msg in printed)

    @patch("builtins.input", return_value="1")
    @patch("builtins.print")
    def test_human_required_filtered_in_interactive_mode(
        self, mock_print: Mock, mock_input: Mock
    ) -> None:
        """Human-required items should also be filtered in interactive mode."""
        items = [
            _make_item(id="hr-1", labels=["human-required"]),
            _make_item(id="task-1", title="Available task"),
        ]

        result = select_work_item(items, interactive=True)

        assert result is not None
        assert result.id == "task-1"


class TestSelectNextHierarchicalItemHumanRequired:
    """Tests for human-required filtering in select_next_hierarchical_item."""

    def test_skips_human_required_task(self) -> None:
        """Human-required standalone tasks should be skipped."""
        items = [
            _make_item(id="hr-1", priority=1, labels=["human-required"]),
            _make_item(id="task-2", priority=2),
        ]

        selected = select_next_hierarchical_item(items)

        assert selected is not None
        assert selected.id == "task-2"

    def test_skips_human_required_feature(self) -> None:
        """Human-required features should be skipped entirely."""
        items = [
            _make_item(
                id="feat-1",
                priority=1,
                issue_type="feature",
                labels=["human-required"],
            ),
            _make_item(id="task-2", priority=2),
        ]

        selected = select_next_hierarchical_item(items)

        assert selected is not None
        assert selected.id == "task-2"

    def test_all_human_required_returns_none(self) -> None:
        """When all items are human-required, returns None."""
        items = [
            _make_item(id="hr-1", labels=["human-required"]),
            _make_item(id="hr-2", labels=["human-required"]),
        ]

        selected = select_next_hierarchical_item(items)

        assert selected is None


class TestGetNextChildTaskHumanRequired:
    """Tests for human-required filtering in get_next_child_task."""

    @patch("src.pokepoke.beads_hierarchy.get_children")
    def test_skips_human_required_children(
        self, mock_get_children: Mock
    ) -> None:
        """Child tasks with human-required should be skipped."""
        mock_get_children.return_value = [
            _make_item(
                id="child-1", priority=1, labels=["human-required"]
            ),
            _make_item(id="child-2", priority=2),
        ]

        result = get_next_child_task("parent-1")

        assert result is not None
        assert result.id == "child-2"

    @patch("src.pokepoke.beads_hierarchy.get_children")
    def test_all_children_human_required_returns_none(
        self, mock_get_children: Mock
    ) -> None:
        """When all children are human-required, returns None."""
        mock_get_children.return_value = [
            _make_item(
                id="child-1", priority=1, labels=["human-required"]
            ),
            _make_item(
                id="child-2", priority=2, labels=["human-required"]
            ),
        ]

        result = get_next_child_task("parent-1")

        assert result is None

    @patch("src.pokepoke.beads_hierarchy.get_children")
    def test_human_required_among_completed_children(
        self, mock_get_children: Mock
    ) -> None:
        """Human-required + done children should result in None."""
        mock_get_children.return_value = [
            _make_item(
                id="child-1",
                status="done",
                priority=1,
            ),
            _make_item(
                id="child-2",
                priority=2,
                labels=["human-required"],
            ),
        ]

        result = get_next_child_task("parent-1")

        assert result is None
