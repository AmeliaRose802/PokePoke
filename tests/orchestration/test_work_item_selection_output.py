
import logging
from unittest.mock import Mock, patch

from pokepoke.orchestration.work_item_selection import (
    _is_human_required,
    autonomous_selection,
    interactive_selection,
    select_multiple_items,
    select_work_item,
)
from pokepoke.types_beads import BeadsWorkItem


def _make_item(id: str = "task-1", title: str = "Task", labels: list[str] | None = None,
               description: str | None = "Desc", priority: int = 1) -> BeadsWorkItem:
    return BeadsWorkItem(
        id=id, title=title, description=description,
        status="open", priority=priority, issue_type="task",
        labels=labels,
    )


class TestIsHumanRequired:
    """Tests for _is_human_required helper."""

    def test_no_labels_returns_false(self):
        assert _is_human_required(_make_item(labels=None)) is False

    def test_empty_labels_returns_false(self):
        assert _is_human_required(_make_item(labels=[])) is False

    def test_human_required_label_returns_true(self):
        assert _is_human_required(_make_item(labels=["human-required"])) is True

    def test_other_labels_returns_false(self):
        assert _is_human_required(_make_item(labels=["tech-debt", "bug"])) is False


class TestSelectWorkItem:
    """Tests for select_work_item filtering logic."""

    @patch('builtins.print')
    def test_empty_ready_items(self, mock_print: Mock, caplog):
        with caplog.at_level(logging.DEBUG, logger="pokepoke.orchestration.work_item_selection"):
            result = select_work_item([], interactive=False)
        assert result is None
        assert "No ready work" in caplog.text

    @patch('builtins.print')
    @patch('pokepoke.orchestration.work_item_selection.select_next_hierarchical_item')
    def test_skip_ids_filters_items(self, mock_select: Mock, mock_print: Mock):
        items = [_make_item(id="a"), _make_item(id="b")]
        mock_select.return_value = items[1]
        result = select_work_item(items, interactive=False, skip_ids={"a"})
        assert result is items[1]
        # select_next_hierarchical_item should only receive item "b"
        call_args = mock_select.call_args[0][0]
        assert len(call_args) == 1
        assert call_args[0].id == "b"

    @patch('builtins.print')
    def test_all_items_skipped(self, mock_print: Mock, caplog):
        items = [_make_item(id="a")]
        with caplog.at_level(logging.DEBUG, logger="pokepoke.orchestration.work_item_selection"):
            result = select_work_item(items, interactive=False, skip_ids={"a"})
        assert result is None
        assert "previously skipped" in caplog.text

    @patch('builtins.print')
    @patch('pokepoke.orchestration.work_item_selection.is_assigned_to_current_user', return_value=False)
    def test_filters_items_assigned_to_other_agents(self, _mock_assigned: Mock, mock_print: Mock, caplog):
        items = [_make_item(id="a")]
        with caplog.at_level(logging.DEBUG, logger="pokepoke.orchestration.work_item_selection"):
            result = select_work_item(items, interactive=False)
        assert result is None
        assert "Skipped" in caplog.text

    @patch('builtins.print')
    @patch('pokepoke.orchestration.work_item_selection.is_assigned_to_current_user', return_value=True)
    @patch('pokepoke.orchestration.work_item_selection.select_next_hierarchical_item')
    def test_filters_human_required_items(self, mock_select: Mock, _m1: Mock, mock_print: Mock, caplog):
        human = _make_item(id="h", labels=["human-required"])
        normal = _make_item(id="n")
        mock_select.return_value = normal
        with caplog.at_level(logging.DEBUG, logger="pokepoke.orchestration.work_item_selection"):
            result = select_work_item([human, normal], interactive=False)
        assert result is normal
        assert "human-required" in caplog.text

    @patch('builtins.print')
    @patch('builtins.input')
    @patch('pokepoke.orchestration.work_item_selection.is_assigned_to_current_user', return_value=True)
    def test_interactive_long_description_truncated(self, _m1: Mock, mock_input: Mock, mock_print: Mock):
        """Items with descriptions > 80 chars get truncated with '...'."""
        long_desc = "A" * 100
        items = [_make_item(id="a", description=long_desc)]
        mock_input.return_value = '1'
        select_work_item(items, interactive=True)
        printed = " ".join(str(c) for c in mock_print.call_args_list)
        assert "..." in printed


class TestInteractiveSelection:
    """Tests for interactive_selection."""

    @patch('builtins.input', return_value='q')
    def test_quit(self, _mock_input: Mock):
        result = interactive_selection([_make_item()])
        assert result is None

    @patch('builtins.input', side_effect=['2', '1'])
    @patch('builtins.print')
    def test_out_of_range_then_valid(self, _mock_print: Mock, _mock_input: Mock):
        items = [_make_item()]
        result = interactive_selection(items)
        assert result is items[0]

    @patch('builtins.input', side_effect=['abc', '1'])
    @patch('builtins.print')
    def test_invalid_input_then_valid(self, _mock_print: Mock, _mock_input: Mock):
        items = [_make_item()]
        result = interactive_selection(items)
        assert result is items[0]

    @patch('builtins.input', side_effect=KeyboardInterrupt)
    @patch('builtins.print')
    def test_keyboard_interrupt(self, _mock_print: Mock, _mock_input: Mock):
        result = interactive_selection([_make_item()])
        assert result is None


class TestAutonomousSelection:
    """Tests for autonomous_selection."""

    @patch('builtins.print')
    @patch('pokepoke.orchestration.work_item_selection.select_next_hierarchical_item', return_value=None)
    def test_returns_none_when_no_selection(self, _mock_select: Mock, _mock_print: Mock):
        result = autonomous_selection([_make_item()])
        assert result is None


class TestSelectMultipleItems:
    """Tests for select_multiple_items."""

    def test_empty_items_returns_empty(self):
        assert select_multiple_items([], 3) == []

    def test_zero_count_returns_empty(self):
        assert select_multiple_items([_make_item()], 0) == []

    @patch('pokepoke.orchestration.work_item_selection.is_assigned_to_current_user', return_value=True)
    @patch('pokepoke.orchestration.work_item_selection.select_next_hierarchical_item')
    def test_selects_up_to_count(self, mock_select: Mock, _m1: Mock):
        a, b = _make_item(id="a"), _make_item(id="b")
        mock_select.side_effect = [a, b]
        result = select_multiple_items([a, b], 2)
        assert len(result) == 2

    @patch('pokepoke.orchestration.work_item_selection.is_assigned_to_current_user', return_value=True)
    @patch('pokepoke.orchestration.work_item_selection.select_next_hierarchical_item')
    def test_skips_claimed_ids(self, mock_select: Mock, _m1: Mock):
        a, b = _make_item(id="a"), _make_item(id="b")
        mock_select.return_value = b
        select_multiple_items([a, b], 2, claimed_ids={"a"})
        # Only b should be available
        call_args = mock_select.call_args[0][0]
        assert all(i.id != "a" for i in call_args)

    @patch('pokepoke.orchestration.work_item_selection.is_assigned_to_current_user', return_value=True)
    @patch('pokepoke.orchestration.work_item_selection.select_next_hierarchical_item', return_value=None)
    def test_returns_empty_when_hierarchical_returns_none(self, _m1: Mock, _m2: Mock):
        assert select_multiple_items([_make_item()], 3) == []


class TestWorkItemSelectionOutput:
    """Test output behavior of work item selection."""

    @patch('builtins.print')
    @patch('pokepoke.orchestration.work_item_selection.select_next_hierarchical_item')
    def test_autonomous_mode_suppresses_list_output(
        self,
        mock_select_hierarchical: Mock,
        mock_print: Mock
    ) -> None:
        """Verify that the list of items is not printed in autonomous mode."""
        items = [
            BeadsWorkItem(
                id="task-1",
                title="Task One",
                description="Desc 1",
                status="open",
                priority=1,
                issue_type="task"
            ),
            BeadsWorkItem(
                id="task-2",
                title="Task Two",
                description="Desc 2",
                status="open",
                priority=2,
                issue_type="task"
            )
        ]
        mock_select_hierarchical.return_value = items[0]

        select_work_item(items, interactive=False)

        # Verify select_next_hierarchical_item was called
        mock_select_hierarchical.assert_called_once()

        # Verify that "Found X ready work items" was NOT printed
        # captures args of all print calls
        printed_messages = [call[0][0] for call in mock_print.call_args_list if call[0]]

        # We expect some output like "Hierarchically selected item: task-1" if selected
        # But we DO NOT expect the list output

        list_header_printed = any("Found 2 ready work items" in str(msg) for msg in printed_messages)
        assert not list_header_printed, "Should not print item list in autonomous mode"

        _item_printed = any("Task One" in str(msg) and "Task Two" in str(msg) for msg in printed_messages)
        # However, "Task One" might be printed if it's the selected item?
        # The selected item IS printed: print(f"🤖 Hierarchically selected item: {selected.id}")

        # Check specifically for the loop output "1. [task-1] Task One"
        loop_output_printed = any("1. [task-1]" in str(msg) for msg in printed_messages)
        assert not loop_output_printed, "Should not print indexed list in autonomous mode"

    @patch('builtins.print')
    @patch('builtins.input')
    def test_interactive_mode_prints_list_output(
        self,
        mock_input: Mock,
        mock_print: Mock
    ) -> None:
        """Verify that the list of items IS printed in interactive mode."""
        items = [
            BeadsWorkItem(
                id="task-1",
                title="Task One",
                description="Desc 1",
                status="open",
                priority=1,
                issue_type="task"
            )
        ]
        mock_input.return_value = '1'

        select_work_item(items, interactive=True)

        printed_messages = [call[0][0] for call in mock_print.call_args_list if call[0]]

        list_header_printed = any("Found 1 ready work items" in str(msg) for msg in printed_messages)
        assert list_header_printed, "Should print item list in interactive mode"


class TestInteractiveSelectionShutdown:
    """Test interactive_selection exits when shutdown is requested."""

    @patch('pokepoke.orchestration.work_item_selection.is_shutting_down', return_value=True)
    def test_returns_none_on_shutdown(self, mock_shutdown):
        """Covers line 124: return None when is_shutting_down() is True."""
        from pokepoke.orchestration.work_item_selection import interactive_selection
        items = [
            BeadsWorkItem(
                id="task-1", title="Task", description="",
                status="open", priority=1, issue_type="task"
            )
        ]
        result = interactive_selection(items)
        assert result is None
