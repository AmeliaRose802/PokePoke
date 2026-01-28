import pytest
from unittest.mock import MagicMock, patch
import sys

# Skip if win32 specific components break import (though we mock msvcrt if needed)
from pokepoke.terminal_ui import PokePokeUI

class TestUIScrolling:
    """Test UI scrolling logic."""

    @pytest.fixture
    def ui_mock(self):
        with patch('pokepoke.terminal_ui.Console') as mock_console:
            # Mock console height
            mock_instance = MagicMock()
            mock_instance.height = 100
            mock_console.return_value = mock_instance
            
            ui = PokePokeUI()
            # Ensure console is set
            ui.console = mock_instance
            return ui

    def test_scroll_logic_tail(self, ui_mock):
        """Test default scrolling (tail)."""
        ui = ui_mock
        # Use orchestrator buffer for test
        ui.orchestrator_buffer = [f"Line {i}" for i in range(200)]
        ui.scroll_offsets["orchestrator"] = 0
        
        # Mock layout dictionary access
        mock_orch_layout = MagicMock()
        mock_agent_layout = MagicMock()
        ui.layout = {
            "orchestrator": mock_orch_layout,
            "agent": mock_agent_layout
        }
        
        ui._update_panels()
        
        # With height=100, body lines = max(5, 100 - 10) = 90
        # Should show last 90 lines: 110 to 199
        args, kwargs = mock_orch_layout.update.call_args
        panel = args[0]
        content = panel.renderable
        
        assert "Line 199" in content
        assert "Line 110" in content
        assert "Line 109" not in content
        assert "Orchestrator" in panel.title
        assert "scrolled" not in panel.title.lower()

    def test_scroll_logic_offset(self, ui_mock):
        """Test scrolling back."""
        ui = ui_mock
        ui.orchestrator_buffer = [f"Line {i}" for i in range(200)]
        ui.scroll_offsets["orchestrator"] = 10
        
        # Mock layout
        mock_orch_layout = MagicMock()
        mock_agent_layout = MagicMock()
        ui.layout = {
            "orchestrator": mock_orch_layout,
            "agent": mock_agent_layout
        }
        
        ui._update_panels()
        
        # Offset 10: end_index = 200 - 10 = 190
        # start_index = 190 - 90 = 100
        # Should show Line 100 to Line 189
        
        args, kwargs = mock_orch_layout.update.call_args
        panel = args[0]
        content = panel.renderable
        
        assert "Line 189" in content
        assert "Line 190" not in content  # Should be scrolled off bottom
        assert "Line 100" in content
        assert "scrolled" in panel.title.lower()
