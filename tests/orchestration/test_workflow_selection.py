"""Unit tests for workflow work item selection.

This module tests the work item selection logic including:
- Work item filtering and selection
- Interactive user selection
- Autonomous agent-based selection
"""

from unittest.mock import Mock, patch

from pokepoke.orchestration.work_item_selection import autonomous_selection, interactive_selection
from pokepoke.orchestration.workflow import select_work_item
from pokepoke.types_beads import BeadsWorkItem
from tests.orchestration.conftest import (
    make_selection_mocks,
    make_work_item,
)


class TestSelectWorkItem:
    """Test select_work_item function."""

    def test_empty_list(self) -> None:
        """Test with empty work item list."""
        result = select_work_item([], interactive=False)

        assert result is None

    def test_autonomous_selection(self) -> None:
        """Test autonomous mode selection."""
        item = make_work_item(id="task-1", title="Task 1")

        with make_selection_mocks(selected_item=item) as mocks:
            result = select_work_item([item], interactive=False)

            assert result is not None
            assert result.id == "task-1"
            mocks['select'].assert_called_once()

    @patch('builtins.input')
    def test_interactive_selection(self, mock_input: Mock) -> None:
        """Test interactive mode selection."""
        item = make_work_item(id="task-1", title="Task 1")
        mock_input.return_value = '1'

        result = select_work_item([item], interactive=True)

        assert result is not None
        assert result.id == "task-1"

    def test_filters_items_assigned_to_others(self) -> None:
        """Test that items assigned to other agents are filtered out."""
        import os
        os.environ['AGENT_NAME'] = 'agent_alpha'

        item1 = make_work_item(
            id="task-1",
            title="Task assigned to other agent",
            status="in_progress",
            assignee="agent_beta"
        )
        item2 = make_work_item(
            id="task-2",
            title="Task available",
            priority=2,
            status="open",
            assignee=None
        )

        with make_selection_mocks(selected_item=item2) as mocks:
            result = select_work_item([item1, item2], interactive=False)

            # Should have filtered out task-1 and only passed task-2
            mocks['select'].assert_called_once()
            passed_items = mocks['select'].call_args[0][0]
            assert len(passed_items) == 1
            assert passed_items[0].id == "task-2"
            assert result is not None
            assert result.id == "task-2"

    def test_all_items_assigned_to_others(self) -> None:
        """Test when all items are assigned to other agents."""
        import os
        os.environ['AGENT_NAME'] = 'agent_alpha'

        items = [
            make_work_item(
                id="task-1",
                title="Task assigned to beta",
                status="in_progress",
                assignee="agent_beta"
            ),
            make_work_item(
                id="task-2",
                title="Task assigned to gamma",
                priority=2,
                status="in_progress",
                assignee="agent_gamma"
            )
        ]

        result = select_work_item(items, interactive=False)

        # Should return None since all items are assigned to others
        assert result is None


class TestInteractiveSelection:
    """Test interactive_selection function."""

    @patch('builtins.input')
    def test_valid_selection(self, mock_input: Mock) -> None:
        """Test valid item selection."""
        items = [
            BeadsWorkItem(
                id="task-1",
                title="Task 1",
                description="",
                status="open",
                priority=1,
                issue_type="task"
            ),
            BeadsWorkItem(
                id="task-2",
                title="Task 2",
                description="",
                status="open",
                priority=2,
                issue_type="task"
            )
        ]
        mock_input.return_value = '2'

        result = interactive_selection(items)

        assert result is not None
        assert result.id == "task-2"

    @patch('builtins.input')
    def test_quit_selection(self, mock_input: Mock) -> None:
        """Test quit option."""
        items = [
            BeadsWorkItem(
                id="task-1",
                title="Task 1",
                description="",
                status="open",
                priority=1,
                issue_type="task"
            )
        ]
        mock_input.return_value = 'q'

        result = interactive_selection(items)

        assert result is None

    @patch('builtins.input')
    def test_invalid_then_valid(self, mock_input: Mock) -> None:
        """Test invalid input followed by valid input."""
        items = [
            BeadsWorkItem(
                id="task-1",
                title="Task 1",
                description="",
                status="open",
                priority=1,
                issue_type="task"
            )
        ]
        mock_input.side_effect = ['invalid', '1']

        result = interactive_selection(items)

        assert result is not None
        assert result.id == "task-1"

    @patch('builtins.input')
    def test_out_of_range_then_valid(self, mock_input: Mock) -> None:
        """Test out of range input followed by valid input."""
        items = [
            BeadsWorkItem(
                id="task-1",
                title="Task 1",
                description="",
                status="open",
                priority=1,
                issue_type="task"
            )
        ]
        mock_input.side_effect = ['99', '1']

        result = interactive_selection(items)

        assert result is not None
        assert result.id == "task-1"

    @patch('builtins.input')
    def test_keyboard_interrupt(self, mock_input: Mock) -> None:
        """Test keyboard interrupt during selection."""
        items = [
            BeadsWorkItem(
                id="task-1",
                title="Task 1",
                description="",
                status="open",
                priority=1,
                issue_type="task"
            )
        ]
        mock_input.side_effect = KeyboardInterrupt()

        result = interactive_selection(items)

        assert result is None


class TestAutonomousSelection:
    """Test autonomous_selection function."""

    @patch('pokepoke.orchestration.work_item_selection.select_next_hierarchical_item')
    def test_item_selected(self, mock_select: Mock) -> None:
        """Test successful hierarchical selection."""
        items = [
            BeadsWorkItem(
                id="task-1",
                title="Task 1",
                description="",
                status="open",
                priority=1,
                issue_type="task"
            )
        ]
        mock_select.return_value = items[0]

        result = autonomous_selection(items)

        assert result is not None
        assert result.id == "task-1"

    @patch('pokepoke.orchestration.work_item_selection.select_next_hierarchical_item')
    def test_no_item_selected(self, mock_select: Mock) -> None:
        """Test when no item is selected."""
        items = [
            BeadsWorkItem(
                id="task-1",
                title="Task 1",
                description="",
                status="open",
                priority=1,
                issue_type="task"
            )
        ]
        mock_select.return_value = None

        result = autonomous_selection(items)

        assert result is None
