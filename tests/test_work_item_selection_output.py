
import pytest
from unittest.mock import Mock, patch
from pokepoke.work_item_selection import select_work_item
from pokepoke.types import BeadsWorkItem

class TestWorkItemSelectionOutput:
    """Test output behavior of work item selection."""
    
    @patch('builtins.print')
    @patch('pokepoke.work_item_selection.select_next_hierarchical_item')
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
        
        item_printed = any("Task One" in str(msg) and "Task Two" in str(msg) for msg in printed_messages)
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
