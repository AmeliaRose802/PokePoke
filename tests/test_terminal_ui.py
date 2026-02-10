"""Tests for terminal UI banner utilities."""

import pytest
from unittest.mock import patch
from pokepoke.terminal_ui import format_work_item_banner, set_terminal_banner, clear_terminal_banner


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
    
    def test_set_banner_windows(self):
        """Test setting banner on Windows platform."""
        with patch('sys.platform', 'win32'):
            with patch('ctypes.windll.kernel32.SetConsoleTitleW') as mock_title:
                set_terminal_banner("Test Banner")
                mock_title.assert_called_with("Test Banner")
    
    def test_clear_banner_windows(self):
        """Test clearing banner on Windows platform."""
        with patch('sys.platform', 'win32'):
            with patch('ctypes.windll.kernel32.SetConsoleTitleW') as mock_title:
                clear_terminal_banner()
                mock_title.assert_called_with("PokePoke")

