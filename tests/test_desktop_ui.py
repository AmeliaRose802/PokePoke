"""Tests for PokePoke desktop UI adapter."""

import builtins
import sys
import threading
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

# Check if websockets is available
try:
    import websockets
    HAS_WEBSOCKETS = True
except ImportError:
    HAS_WEBSOCKETS = False


pytestmark = pytest.mark.skipif(
    not HAS_WEBSOCKETS,
    reason="websockets package not installed"
)


class TestDesktopUIInit:
    """Test DesktopUI initialization."""

    def test_init_default_port(self):
        from pokepoke.desktop_ui import DesktopUI
        ui = DesktopUI()
        assert ui._port == 9160
        assert ui.is_running is False

    def test_init_custom_port(self):
        from pokepoke.desktop_ui import DesktopUI
        ui = DesktopUI(port=8888)
        assert ui._port == 8888

    def test_bridge_property(self):
        from pokepoke.desktop_ui import DesktopUI
        from pokepoke.desktop_bridge import DesktopBridge
        ui = DesktopUI()
        assert isinstance(ui.bridge, DesktopBridge)


class TestDesktopUIOutputRouting:
    """Test print redirect and output routing."""

    def test_orchestrator_output_context(self):
        from pokepoke.desktop_ui import DesktopUI
        ui = DesktopUI()
        assert ui._target_buffer == "orchestrator"
        with ui.agent_output():
            assert ui._target_buffer == "agent"
        assert ui._target_buffer == "orchestrator"

    def test_agent_output_context(self):
        from pokepoke.desktop_ui import DesktopUI
        ui = DesktopUI()
        with ui.orchestrator_output():
            assert ui._target_buffer == "orchestrator"

    def test_styled_output_context(self):
        from pokepoke.desktop_ui import DesktopUI
        ui = DesktopUI()
        assert ui._current_style is None
        with ui.styled_output("bold red"):
            assert ui._current_style == "bold red"
        assert ui._current_style is None

    def test_set_style(self):
        from pokepoke.desktop_ui import DesktopUI
        ui = DesktopUI()
        ui.set_style("green")
        assert ui._current_style == "green"
        ui.set_style(None)
        assert ui._current_style is None

    def test_nested_output_contexts(self):
        from pokepoke.desktop_ui import DesktopUI
        ui = DesktopUI()
        with ui.orchestrator_output():
            assert ui._target_buffer == "orchestrator"
            with ui.agent_output():
                assert ui._target_buffer == "agent"
            assert ui._target_buffer == "orchestrator"


class TestDesktopUIStateUpdates:
    """Test state update methods forward to bridge."""

    def test_update_header(self):
        from pokepoke.desktop_ui import DesktopUI
        ui = DesktopUI()
        ui._bridge = MagicMock()
        ui.update_header("item-1", "Fix bug", "in_progress")
        ui._bridge.send_work_item.assert_called_once_with(
            "item-1", "Fix bug", "in_progress"
        )

    def test_set_current_agent(self):
        from pokepoke.desktop_ui import DesktopUI
        ui = DesktopUI()
        ui._bridge = MagicMock()
        ui.set_current_agent("pokepoke_agent_42")
        ui._bridge.send_agent_name.assert_called_once_with("pokepoke_agent_42")

    def test_set_current_agent_none(self):
        from pokepoke.desktop_ui import DesktopUI
        ui = DesktopUI()
        ui._bridge = MagicMock()
        ui.set_current_agent(None)
        ui._bridge.send_agent_name.assert_called_once_with("")

    def test_update_stats(self):
        from pokepoke.desktop_ui import DesktopUI
        from pokepoke.types import SessionStats, AgentStats
        ui = DesktopUI()
        ui._bridge = MagicMock()
        stats = SessionStats(agent_stats=AgentStats())
        ui.update_stats(stats, 60.0)
        ui._bridge.send_stats.assert_called_once_with(stats, 60.0)

    def test_log_orchestrator(self):
        from pokepoke.desktop_ui import DesktopUI
        ui = DesktopUI()
        ui._bridge = MagicMock()
        ui.log_orchestrator("test message", "green")
        ui._bridge.send_log.assert_called_once_with(
            "test message", "orchestrator", "green"
        )

    def test_log_agent(self):
        from pokepoke.desktop_ui import DesktopUI
        ui = DesktopUI()
        ui._bridge = MagicMock()
        ui.log_agent("agent output")
        ui._bridge.send_log.assert_called_once_with(
            "agent output", "agent", None
        )

    def test_log_message_default_target(self):
        from pokepoke.desktop_ui import DesktopUI
        ui = DesktopUI()
        ui._bridge = MagicMock()
        ui.log_message("hello")
        ui._bridge.send_log.assert_called_once_with(
            "hello", "orchestrator", None
        )


class TestDesktopUIStartStop:
    """Test start/stop/exit lifecycle."""

    def test_start_enables_running(self):
        from pokepoke.desktop_ui import DesktopUI
        ui = DesktopUI()
        original_print = builtins.print
        ui.start()
        try:
            assert ui.is_running is True
            # Print should be redirected
            assert builtins.print is not original_print
        finally:
            builtins.print = original_print
            ui._is_running = False

    def test_stop_restores_print(self):
        from pokepoke.desktop_ui import DesktopUI
        ui = DesktopUI()
        original_print = builtins.print
        ui.start()
        ui.stop()
        assert ui.is_running is False
        assert builtins.print is original_print

    def test_stop_and_capture(self):
        from pokepoke.desktop_ui import DesktopUI
        ui = DesktopUI()
        ui._is_running = True
        ui.stop_and_capture()
        assert ui.is_running is False

    def test_exit_stops_bridge(self):
        from pokepoke.desktop_ui import DesktopUI
        ui = DesktopUI()
        ui._bridge = MagicMock()
        ui.exit()
        assert ui.is_running is False
        ui._bridge.stop.assert_called_once()


class TestDesktopUIPrintRedirect:
    """Test the print redirect mechanism."""

    def test_redirect_captures_complete_line(self):
        from pokepoke.desktop_ui import DesktopUI
        ui = DesktopUI()
        ui._bridge = MagicMock()
        ui._is_running = True
        ui._print_redirect("Hello, world!")
        ui._bridge.send_log.assert_called_once_with(
            "Hello, world!", "orchestrator", None
        )

    def test_redirect_respects_target_buffer(self):
        from pokepoke.desktop_ui import DesktopUI
        ui = DesktopUI()
        ui._bridge = MagicMock()
        ui._is_running = True
        ui._target_buffer = "agent"
        ui._print_redirect("agent output")
        ui._bridge.send_log.assert_called_once_with(
            "agent output", "agent", None
        )

    def test_redirect_respects_style(self):
        from pokepoke.desktop_ui import DesktopUI
        ui = DesktopUI()
        ui._bridge = MagicMock()
        ui._is_running = True
        ui._current_style = "bold red"
        ui._print_redirect("error msg")
        ui._bridge.send_log.assert_called_once_with(
            "error msg", "orchestrator", "bold red"
        )

    def test_redirect_to_stderr_passes_through(self):
        from pokepoke.desktop_ui import DesktopUI
        ui = DesktopUI()
        ui._bridge = MagicMock()
        ui._is_running = True
        # Writing to stderr should go through original print
        ui._print_redirect("error", file=sys.stderr)
        ui._bridge.send_log.assert_not_called()

    def test_redirect_handles_multiple_args(self):
        from pokepoke.desktop_ui import DesktopUI
        ui = DesktopUI()
        ui._bridge = MagicMock()
        ui._is_running = True
        ui._print_redirect("hello", "world")
        ui._bridge.send_log.assert_called_once_with(
            "hello world", "orchestrator", None
        )

    def test_redirect_handles_custom_sep(self):
        from pokepoke.desktop_ui import DesktopUI
        ui = DesktopUI()
        ui._bridge = MagicMock()
        ui._is_running = True
        ui._print_redirect("a", "b", "c", sep=", ")
        ui._bridge.send_log.assert_called_once_with(
            "a, b, c", "orchestrator", None
        )


class TestUseDesktopUI:
    """Test the use_desktop_ui() switcher function."""

    def test_switches_global_ui(self):
        from pokepoke.terminal_ui import use_desktop_ui
        import pokepoke.terminal_ui as module
        from pokepoke.desktop_ui import DesktopUI
        from pokepoke.textual_ui import TextualUI

        original = module.ui
        try:
            result = use_desktop_ui(port=9999)
            assert isinstance(result, DesktopUI)
            assert module.ui is result
            assert result._port == 9999
        finally:
            # Restore original UI
            module.ui = original


class TestDesktopUIRunWithOrchestrator:
    """Test run_with_orchestrator lifecycle."""

    def test_run_success(self):
        from pokepoke.desktop_ui import DesktopUI
        ui = DesktopUI(port=19200)
        ui._bridge = MagicMock()

        def fake_orchestrator():
            return 0

        result = ui.run_with_orchestrator(fake_orchestrator)
        assert result == 0
        ui._bridge.start.assert_called_once()
        ui._bridge.stop.assert_called_once()
        assert ui.is_running is False

    def test_run_nonzero_exit(self):
        from pokepoke.desktop_ui import DesktopUI
        ui = DesktopUI(port=19201)
        ui._bridge = MagicMock()

        def failing_orchestrator():
            return 42

        result = ui.run_with_orchestrator(failing_orchestrator)
        assert result == 42

    def test_run_exception_returns_1(self):
        from pokepoke.desktop_ui import DesktopUI
        ui = DesktopUI(port=19202)
        ui._bridge = MagicMock()

        def crashing_orchestrator():
            raise RuntimeError("boom")

        result = ui.run_with_orchestrator(crashing_orchestrator)
        assert result == 1
        ui._bridge.send_log.assert_called()  # Error was logged

    def test_run_keyboard_interrupt_returns_130(self):
        from pokepoke.desktop_ui import DesktopUI
        from pokepoke.shutdown import reset
        ui = DesktopUI(port=19203)
        ui._bridge = MagicMock()

        def interrupted_orchestrator():
            raise KeyboardInterrupt()

        result = ui.run_with_orchestrator(interrupted_orchestrator)
        assert result == 130
        reset()  # Clean up shutdown state

    def test_run_restores_print(self):
        from pokepoke.desktop_ui import DesktopUI
        ui = DesktopUI(port=19204)
        ui._bridge = MagicMock()
        original = builtins.print

        def noop():
            return 0

        ui.run_with_orchestrator(noop)
        assert builtins.print is original

    def test_run_sends_startup_log(self):
        from pokepoke.desktop_ui import DesktopUI
        ui = DesktopUI(port=19205)
        ui._bridge = MagicMock()

        ui.run_with_orchestrator(lambda: 0)

        # Should have sent a startup log message
        calls = ui._bridge.send_log.call_args_list
        startup_msgs = [c for c in calls if "Desktop bridge started" in str(c)]
        assert len(startup_msgs) >= 1


class TestDesktopUIDeferredFlush:
    """Test the deferred flush mechanism for streaming output."""

    def test_deferred_flush_sends_buffer(self):
        from pokepoke.desktop_ui import DesktopUI
        ui = DesktopUI()
        ui._bridge = MagicMock()
        ui._is_running = True
        ui._line_buffer = "partial text"
        ui._target_buffer = "agent"
        ui._current_style = "cyan"
        ui._deferred_flush()
        ui._bridge.send_log.assert_called_once_with("partial text", "agent", "cyan")
        assert ui._line_buffer == ""
        assert ui._flush_timer is None

    def test_deferred_flush_empty_buffer(self):
        from pokepoke.desktop_ui import DesktopUI
        ui = DesktopUI()
        ui._bridge = MagicMock()
        ui._line_buffer = ""
        ui._deferred_flush()
        ui._bridge.send_log.assert_not_called()

    def test_set_session_start_time(self):
        from pokepoke.desktop_ui import DesktopUI
        ui = DesktopUI()
        ui._bridge = MagicMock()
        ui.set_session_start_time(1000.0)
        ui._bridge.send_stats.assert_called_once()
        args = ui._bridge.send_stats.call_args
        assert args[0][0] is None  # No session stats
        assert args[0][1] > 0  # Elapsed time > 0
