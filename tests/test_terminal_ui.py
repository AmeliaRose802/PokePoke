"""Tests for terminal UI utilities."""

import pytest
from unittest.mock import MagicMock, patch
from pokepoke.terminal_ui import format_work_item_banner, set_terminal_banner, clear_terminal_banner, PokePokeUI


class TestFormatWorkItemBanner:
    """Test work item banner formatting."""
    
    def test_basic_formatting(self):
        """Test basic banner formatting."""
        banner = format_work_item_banner("PokePoke-123", "Add new feature")
        assert banner == "🚀 PokePoke: PokePoke-123 - Add new feature [In Progress]"
    
    def test_custom_status(self):
        """Test banner with custom status."""
        banner = format_work_item_banner("PokePoke-456", "Fix bug", "Completed")
        assert banner == "🚀 PokePoke: PokePoke-456 - Fix bug [Completed]"
    
    def test_long_title_truncation(self):
        """Test that long titles are truncated."""
        long_title = "This is a very long title that exceeds the maximum allowed length for terminal display"
        banner = format_work_item_banner("PokePoke-789", long_title)
        
        # Should truncate to 60 chars plus "..."
        assert len(banner) < len(long_title) + 50  # Much shorter than original
        assert "..." in banner
        assert "PokePoke-789" in banner
    
    def test_short_title_no_truncation(self):
        """Test that short titles are not truncated."""
        short_title = "Short title"
        banner = format_work_item_banner("PokePoke-100", short_title)
        assert short_title in banner
        assert "..." not in banner


class TestSetTerminalBanner:
    """Test terminal banner setting."""
    
    def test_set_banner_no_crash(self):
        """Test that setting banner doesn't crash (may not work on all platforms)."""
        # This test just verifies no exceptions are raised
        set_terminal_banner("Test Banner")
        # No assertion needed - we just want to ensure no exception
    
    def test_clear_banner_no_crash(self):
        """Test that clearing banner doesn't crash."""
        clear_terminal_banner()
        # No assertion needed - we just want to ensure no exception
    
    def test_set_and_clear(self):
        """Test setting and clearing banner in sequence."""
        set_terminal_banner("Test 1")
        set_terminal_banner("Test 2")
        clear_terminal_banner()
        # No assertion needed - we just want to ensure no exceptions


class TestPokePokeUI:
    @patch('pokepoke.terminal_ui.Console')
    def test_init_check_layout(self, mock_console):
        """Test PokePokeUI initialization and layout structure."""
        # Mock Console to avoid real terminal interaction
        mock_console.return_value = MagicMock()
        
        ui = PokePokeUI()
        
        # Check layout structure
        # _setup_layout splits the root layout. We verify correct children are present.
        children = ui.layout.children
        # Expect 2 children now: body, footer (header removed and merged into footer)
        assert len(children) == 2
        
        names = [child.name for child in children]
        assert 'header' not in names
        assert 'body' in names
        assert 'footer' in names
        
        # Check specific constraints
        for child in children:
            if child.name == 'footer':
                assert child.size == 7
            elif child.name == 'body':
                assert child.ratio == 1

    @patch('pokepoke.terminal_ui.Console')
    def test_update_header_footer_merge(self, mock_console):
        """Test header update now updates the footer status panel."""
        mock_console_instance = MagicMock()
        mock_console_instance.width = 100
        mock_console.return_value = mock_console_instance
        
        ui = PokePokeUI()
        ui.update_header('ITEM-123', 'Test Title', 'Active')
        
        # Verify state is updated
        assert ui.current_work_item["id"] == "ITEM-123"
        assert ui.current_work_item["title"] == "Test Title"
        assert ui.current_work_item["status"] == "Active"
        
        # Verify footer exists
        footer_layout = ui.layout['footer']
        assert footer_layout is not None

