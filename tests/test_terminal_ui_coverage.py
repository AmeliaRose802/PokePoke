"""Coverage tests for terminal_ui.py."""

import pytest
from unittest.mock import MagicMock, patch
import sys
import builtins
from io import StringIO
from pokepoke.terminal_ui import PokePokeUI

class TestPokePokeUICoverage:
    """Test coverage for PokePokeUI methods."""

    @pytest.fixture
    def ui_mock(self):
        with patch('pokepoke.terminal_ui.Console') as mock_console:
            mock_instance = MagicMock()
            mock_instance.height = 100
            mock_instance.width = 100
            mock_console.return_value = mock_instance
            ui = PokePokeUI()
            ui.console = mock_instance
            return ui

    def test_log_message_orchestrator(self, ui_mock):
        """Test logging to orchestrator buffer."""
        ui_mock.target_buffer = "orchestrator"
        ui_mock.log_message("Test message")
        
        assert len(ui_mock.orchestrator_buffer) == 1
        assert "Test message" in ui_mock.orchestrator_buffer[0]

    def test_log_message_agent(self, ui_mock):
        """Test logging to agent buffer."""
        ui_mock.target_buffer = "agent"
        ui_mock.log_message("Agent message")
        
        assert len(ui_mock.agent_buffer) == 1
        assert "Agent message" in ui_mock.agent_buffer[0]

    def test_print_redirect(self, ui_mock):
        """Test print redirection."""
        # Patch original print to avoid spamming
        with patch('builtins.print'):
            ui_mock.print_redirect("Hello", end="\n")
            # Should end up in buffer
            assert len(ui_mock.orchestrator_buffer) == 1
            assert "Hello" in ui_mock.orchestrator_buffer[0]

            # Test partial
            ui_mock.print_redirect("Partial", end="")
            assert ui_mock.current_line_buffer == "Partial"
            assert len(ui_mock.orchestrator_buffer) == 1
            
            ui_mock.print_redirect(" Line", end="\n")
            assert len(ui_mock.orchestrator_buffer) == 2
            assert "Partial Line" in ui_mock.orchestrator_buffer[1]

    def test_agent_output_context(self, ui_mock):
        """Test agent output context manager."""
        assert ui_mock.target_buffer == "orchestrator"
        with ui_mock.agent_output():
            assert ui_mock.target_buffer == "agent"
            ui_mock.log_message("In agent")
        assert ui_mock.target_buffer == "orchestrator"
        
        assert len(ui_mock.agent_buffer) == 1
        assert "In agent" in ui_mock.agent_buffer[0]

    def test_start_stop(self, ui_mock):
        """Test start and stop methods."""
        with patch('sys.stdout', new=StringIO()) as fake_out:
            # Mock threading.Thread to verify input listener start
            with patch('threading.Thread') as mock_thread:
                ui_mock.start()
                assert ui_mock.is_running
                assert builtins.print == ui_mock.print_redirect
                
                ui_mock.stop()
                assert not ui_mock.is_running
                assert builtins.print == ui_mock.original_print

    def test_update_header(self, ui_mock):
        """Test updating header."""
        ui_mock.update_header("ITEM-123", "Test Title")
        # Header info is now stored in current_work_item and rendered in footer
        assert ui_mock.current_work_item is not None
        assert ui_mock.current_work_item["id"] == "ITEM-123"
        assert ui_mock.current_work_item["title"] == "Test Title"

    def test_update_stats(self, ui_mock):
        """Test updating footer stats."""
        from pokepoke.types import SessionStats, AgentStats
        stats = SessionStats(agent_stats=AgentStats())
        ui_mock.update_stats(stats, 60.0)
        assert ui_mock.layout["footer"] is not None

    def test_set_style(self, ui_mock):
        """Test setting style."""
        ui_mock.set_style("red")
        assert ui_mock.current_style == "red"
        
        ui_mock.current_line_buffer = "buffer"
        ui_mock.set_style("blue")
        assert ui_mock.current_line_buffer == ""
        assert len(ui_mock.orchestrator_buffer) > 0
        assert "buffer" in ui_mock.orchestrator_buffer[0]

    def test_banners(self):
        """Test banner functions."""
        from pokepoke.terminal_ui import format_work_item_banner, set_terminal_banner, clear_terminal_banner
        
        b = format_work_item_banner("ID", "Long title " * 10)
        assert "..." in b
        
        with patch('sys.platform', 'win32'):
            with patch('ctypes.windll.kernel32.SetConsoleTitleW') as mock_title:
                set_terminal_banner("Test")
                mock_title.assert_called_with("Test")
                
                clear_terminal_banner()
                mock_title.assert_called_with("PokePoke")
    
    def test_update_panels_scrolling(self, ui_mock):
        """Test panel updates with scrolling."""
        ui_mock.orchestrator_buffer = [f"Line {i}" for i in range(20)]
        ui_mock.agent_buffer = [f"Agent {i}" for i in range(20)]
        
        ui_mock._update_panels()
        
        # Test scrolled
        ui_mock.scroll_offsets["orchestrator"] = 5
        ui_mock.active_panel = "orchestrator"
        ui_mock._update_panels()
        
        # Test agent active
        ui_mock.active_panel = "agent"
        ui_mock.scroll_offsets["agent"] = 5
        ui_mock._update_panels()

    def test_init_no_console(self):
        """Test init when NameError occurs (simulating rich missing)."""
        with patch('pokepoke.terminal_ui.Console', side_effect=NameError):
            ui = PokePokeUI()
            assert ui.console is None

    def test_get_panel_content(self, ui_mock):
        """Test log slicing logic."""
        logs = ["1", "2", "3", "4", "5"]
        # height 3, offset 0 -> 3,4,5
        c = ui_mock._get_panel_content(logs, 0, 3)
        assert c == ["3", "4", "5"]
        
        # height 3, offset 1 -> 2,3,4
        c = ui_mock._get_panel_content(logs, 1, 3)
        assert c == ["2", "3", "4"]
        
        # height 3, offset 5 -> empty
        c = ui_mock._get_panel_content(logs, 5, 3)
        assert c == []

    def test_input_loop_mock(self, ui_mock):
        """Test input loop logic with mocks."""
        with patch('pokepoke.terminal_ui.msvcrt') as mock_msvcrt:
            # msvcrt present
            # 5 Trues for inputs, then False to fall through to sleep
            mock_msvcrt.kbhit.side_effect = [True, True, True, True, True, False] 
            # Sequence: Tab, Up, Down, PageUp, PageDown
            mock_msvcrt.getch.side_effect = [
                b'\t',                         # Tab -> Switch panel (continues loop immediately)
                b'\xe0', b'H',                 # Up arrow -> Scroll up
                b'\xe0', b'P',                 # Down arrow -> Scroll down
                b'\xe0', b'I',                 # Page Up
                b'\xe0', b'Q',                 # Page Down
            ]
            
            # 4 Nones (Up, Down, PgUp, PgDn) then RuntimeError stops loop at 5th iteration (the False kbhit)
            with patch('time.sleep', side_effect=[None, None, None, None, RuntimeError("Stop")]):
                ui_mock.is_running = True
                try:
                    ui_mock._input_loop()
                except RuntimeError:
                    pass
            
            assert ui_mock.active_panel == "orchestrator"
