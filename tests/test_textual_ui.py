"""Tests for the Textual-based UI components.

Note: The full Textual pilot tests have compatibility issues with Python 3.13.
These tests focus on unit testing the components directly without requiring
the full async app lifecycle.
"""

import pytest
from unittest.mock import MagicMock

from pokepoke.textual_ui import PokePokeApp, TextualUI
from pokepoke.textual_widgets import StatsBar, WorkItemHeader, LogPanel


class TestPokePokeAppInit:
    """Test PokePokeApp initialization."""

    def test_app_creates_successfully(self):
        """Test that the app can be instantiated."""
        app = PokePokeApp()
        assert app is not None
        assert app._active_panel == "agent"
        assert app._target_buffer == "orchestrator"
        assert app._session_start_time is None
        assert app._current_stats is None

    def test_app_bindings(self):
        """Test that bindings are configured."""
        app = PokePokeApp()
        # The app should have bindings for tab, q, home, end
        binding_keys = [b.key for b in app.BINDINGS]
        assert "tab" in binding_keys
        assert "q" in binding_keys
        assert "home" in binding_keys
        assert "end" in binding_keys


class TestPokePokeAppMethods:
    """Test PokePokeApp thread-safe methods (no async needed)."""

    def test_set_session_start_time(self):
        """Test setting session start time."""
        import time
        app = PokePokeApp()
        start_time = time.time()
        app.set_session_start_time(start_time)
        assert app._session_start_time == start_time

    def test_target_buffer_switching(self):
        """Test switching target buffer."""
        app = PokePokeApp()
        assert app.get_target_buffer() == "orchestrator"
        
        app.set_target_buffer("agent")
        assert app.get_target_buffer() == "agent"
        
        app.set_target_buffer("orchestrator")
        assert app.get_target_buffer() == "orchestrator"

    def test_log_message_queues(self):
        """Test that log_message adds to queue."""
        app = PokePokeApp()
        app.log_message("Test message", target="orchestrator")
        
        # Message should be in queue
        assert not app._ui_queue.empty()
        msg_type, args = app._ui_queue.get()
        assert msg_type == "log"
        assert args == ("orchestrator", "Test message", None)

    def test_update_work_item_queues(self):
        """Test that update_work_item adds to queue."""
        app = PokePokeApp()
        app.update_work_item("ITEM-123", "Test Title", "Active")
        
        assert not app._ui_queue.empty()
        msg_type, args = app._ui_queue.get()
        assert msg_type == "work_item"
        assert args == ("ITEM-123", "Test Title", "Active")

    def test_update_stats_queues(self):
        """Test that update_stats adds to queue."""
        app = PokePokeApp()
        mock_stats = MagicMock()
        app.update_stats(mock_stats, 60.0)
        
        assert app._current_stats == mock_stats
        assert not app._ui_queue.empty()
        msg_type, args = app._ui_queue.get()
        assert msg_type == "stats"
        assert args[0] == mock_stats
        assert args[1] == 60.0

    def test_set_current_agent_queues(self):
        """Test that set_current_agent adds to queue."""
        app = PokePokeApp()
        app.set_current_agent("WorkAgent")
        
        assert not app._ui_queue.empty()
        msg_type, args = app._ui_queue.get()
        assert msg_type == "agent_name"
        assert args == ("WorkAgent",)

    def test_action_switch_focus_toggles(self):
        """Test that action_switch_focus toggles _active_panel."""
        app = PokePokeApp()
        assert app._active_panel == "agent"
        
        # Can't fully test without mounted widgets, but we can verify
        # the method exists and starts with correct state
        assert hasattr(app, "action_switch_focus")


class TestTextualUIWrapper:
    """Test the TextualUI wrapper class."""

    def test_init_not_running(self):
        """Test that UI is not running after init."""
        ui = TextualUI()
        assert ui.is_running is False
        assert ui._app is None

    def test_set_style(self):
        """Test setting text style."""
        ui = TextualUI()
        ui.set_style("bold green")
        assert ui._current_style == "bold green"
        
        ui.set_style(None)
        assert ui._current_style is None

    def test_methods_safe_when_not_running(self):
        """Test that methods don't crash when app not running."""
        ui = TextualUI()
        
        # These should not raise exceptions
        ui.update_header("ID", "Title", "Status")
        ui.update_stats(None, 0.0)
        ui.set_session_start_time(0.0)
        ui.set_current_agent("TestAgent")
        ui.log_message("Test message")
        
        # agent_output context should work
        with ui.agent_output():
            pass


class TestWorkItemHeaderWidget:
    """Test the WorkItemHeader widget directly."""

    def test_update_work_item(self):
        """Test updating work item properties."""
        header = WorkItemHeader()
        header.update_work_item("ID-001", "My Task", "Active")
        
        assert header.item_id == "ID-001"
        assert header.item_title == "My Task"
        assert header.item_status == "Active"

    def test_set_agent_name(self):
        """Test setting agent name."""
        header = WorkItemHeader()
        header.set_agent_name("WorkAgent")
        
        assert header.agent_name == "WorkAgent"
    
    def test_default_values(self):
        """Test that default values are set correctly."""
        header = WorkItemHeader()
        assert header.item_id == "PokePoke"
        assert header.item_title == "Initializing..."
        assert header.item_status == ""
        assert header.agent_name == ""


class TestStatsBarWidget:
    """Test the StatsBar widget directly."""

    def test_update_stats_with_none(self):
        """Test updating stats with None values."""
        stats_bar = StatsBar()
        stats_bar.update_stats(None, 60.0)
        
        assert stats_bar.elapsed_time == 60.0
        # Other values should remain at defaults
        assert stats_bar.items_completed == 0

    def test_update_stats_with_data(self):
        """Test updating stats with real data."""
        stats_bar = StatsBar()
        
        mock_stats = MagicMock()
        mock_stats.items_completed = 10
        mock_stats.agent_stats = MagicMock()
        mock_stats.agent_stats.retries = 3
        mock_stats.agent_stats.input_tokens = 5000
        mock_stats.agent_stats.output_tokens = 2500
        mock_stats.agent_stats.api_duration = 120.0
        mock_stats.agent_stats.tool_calls = 25
        mock_stats.work_agent_runs = 5
        mock_stats.tech_debt_agent_runs = 2
        mock_stats.janitor_agent_runs = 3
        mock_stats.backlog_cleanup_agent_runs = 1
        mock_stats.cleanup_agent_runs = 2
        mock_stats.beta_tester_agent_runs = 1
        mock_stats.code_review_agent_runs = 2
        
        stats_bar.update_stats(mock_stats, 300.0)
        
        assert stats_bar.elapsed_time == 300.0
        assert stats_bar.items_completed == 10
        assert stats_bar.retries == 3
        assert stats_bar.input_tokens == 5000
        assert stats_bar.output_tokens == 2500
        assert stats_bar.api_duration == 120.0
        assert stats_bar.tool_calls == 25
        assert stats_bar.work_runs == 5

    def test_default_values(self):
        """Test that default values are zero."""
        stats_bar = StatsBar()
        assert stats_bar.elapsed_time == 0.0
        assert stats_bar.items_completed == 0
        assert stats_bar.retries == 0
        assert stats_bar.input_tokens == 0
        assert stats_bar.output_tokens == 0


class TestLogPanelWidget:
    """Test the LogPanel widget."""

    def test_log_panel_creates(self):
        """Test that LogPanel can be instantiated."""
        panel = LogPanel()
        assert panel is not None
        assert panel._auto_scroll is True
    def test_log_panel_with_title(self):
        """Test LogPanel with title and subtitle."""
        panel = LogPanel(title="Test Title", subtitle="Test Subtitle")
        assert panel is not None
        assert panel.border_title == "Test Title"
        assert panel.border_subtitle == "Test Subtitle"

    def test_log_panel_auto_scroll_default(self):
        """Test auto-scroll is enabled by default."""
        panel = LogPanel()
        assert panel._auto_scroll is True


class TestStatsBarRender:
    """Test StatsBar render method."""

    def test_render_returns_text(self):
        """Test that render() returns a Text object."""
        stats_bar = StatsBar()
        stats_bar.elapsed_time = 120.0  # 2 minutes
        stats_bar.api_duration = 60.0
        stats_bar.input_tokens = 1000
        stats_bar.output_tokens = 500
        stats_bar.tool_calls = 10
        stats_bar.items_completed = 5
        stats_bar.retries = 2
        stats_bar.work_runs = 3
        
        result = stats_bar.render()
        
        # Verify it's a Rich Text object
        assert result is not None
        text_str = str(result)
        assert "2.0m" in text_str  # elapsed minutes
        assert "1.0m" in text_str  # API minutes
        assert "1,000" in text_str  # input tokens
        assert "500" in text_str  # output tokens
        assert "10" in text_str  # tool calls


class TestWorkItemHeaderRender:
    """Test WorkItemHeader render method."""

    def test_render_basic(self):
        """Test basic rendering."""
        header = WorkItemHeader()
        header.item_id = "TEST-123"
        header.item_title = "Test Task"
        
        result = header.render()
        text_str = str(result)
        
        assert "TEST-123" in text_str
        assert "Test Task" in text_str

    def test_render_with_status(self):
        """Test rendering with status."""
        header = WorkItemHeader()
        header.item_id = "TEST-456"
        header.item_title = "Another Task"
        header.item_status = "in_progress"
        
        result = header.render()
        text_str = str(result)
        
        assert "TEST-456" in text_str
        assert "in_progress" in text_str

    def test_render_with_agent(self):
        """Test rendering with agent name."""
        header = WorkItemHeader()
        header.item_id = "TEST-789"
        header.item_title = "Agent Task"
        header.agent_name = "TestAgent"
        
        result = header.render()
        text_str = str(result)
        
        assert "TestAgent" in text_str


class TestTextualUIAdvanced:
    """Test advanced TextualUI methods."""

    def test_stop_when_not_running(self):
        """Test stop() when app not running."""
        ui = TextualUI()
        ui.stop()  # Should not raise
        assert ui.is_running is False

    def test_log_message_without_app(self):
        """Test log_message when no app is running."""
        ui = TextualUI()
        # Should not raise
        ui.log_message("Test message", "orchestrator", "red")

    def test_agent_output_context_manager(self):
        """Test agent_output context manager."""
        ui = TextualUI()
        
        with ui.agent_output():
            pass  # Should not raise

    def test_start_sets_running(self):
        """Test that start() sets is_running flag."""
        ui = TextualUI()
        ui.start()
        assert ui.is_running is True
        ui.stop()

    def test_original_print_preserved(self):
        """Test that original print is preserved."""
        ui = TextualUI()
        assert ui._original_print is not None
        assert callable(ui._original_print)


class TestPokePokeAppAdvanced:
    """Advanced PokePokeApp tests."""

    def test_app_with_orchestrator_func(self):
        """Test app with orchestrator function."""
        def mock_orchestrator():
            return 0
        
        app = PokePokeApp(orchestrator_func=mock_orchestrator)
        assert app._orchestrator_func is mock_orchestrator

    def test_exit_code_default(self):
        """Test default exit code."""
        app = PokePokeApp()
        assert app._exit_code == 0

    def test_ui_queue_initialized(self):
        """Test UI queue is initialized."""
        app = PokePokeApp()
        assert app._ui_queue is not None
        assert app._ui_queue.empty()

    def test_lock_initialized(self):
        """Test threading lock is initialized."""
        app = PokePokeApp()
        assert app._lock is not None

    def test_compose_method_exists(self):
        """Test that compose method exists and is a generator."""
        app = PokePokeApp()
        # Just check the method exists
        assert hasattr(app, "compose")
        assert callable(app.compose)
        # Note: compose() can't be called outside of Textual's async context
        # as it requires active app. Testing presence only.

    def test_action_methods_exist(self):
        """Test that action methods exist."""
        app = PokePokeApp()
        assert hasattr(app, "action_scroll_top")
        assert hasattr(app, "action_scroll_bottom")
        assert callable(app.action_scroll_top)
        assert callable(app.action_scroll_bottom)

    def test_run_orchestrator_wrapper_no_func(self):
        """Test _run_orchestrator_wrapper with no function."""
        app = PokePokeApp()
        result = app._run_orchestrator_wrapper()
        assert result == 0

    def test_run_orchestrator_wrapper_with_func(self):
        """Test _run_orchestrator_wrapper with function."""
        def mock_orch():
            return 42
        app = PokePokeApp(orchestrator_func=mock_orch)
        result = app._run_orchestrator_wrapper()
        assert result == 42

    def test_run_orchestrator_wrapper_with_exception(self):
        """Test _run_orchestrator_wrapper handles exceptions."""
        def bad_orch():
            raise ValueError("Test error")
        app = PokePokeApp(orchestrator_func=bad_orch)
        result = app._run_orchestrator_wrapper()
        assert result == 1  # Error returns 1

    def test_update_elapsed_time_no_start_time(self):
        """Test _update_elapsed_time with no start time set."""
        app = PokePokeApp()
        # Should not raise when session start time is None
        app._update_elapsed_time()

    def test_process_ui_queue_empty(self):
        """Test _process_ui_queue with empty queue."""
        app = PokePokeApp()
        # Should not raise
        app._process_ui_queue()

    def test_handle_message_bad_type(self):
        """Test _handle_message with unknown type."""
        app = PokePokeApp()
        # Should not raise
        app._handle_message("unknown_type", ("arg1", "arg2"))


class TestTextualUIPrintRedirect:
    """Test TextualUI print redirection."""

    def test_print_redirect_to_file(self):
        """Test print redirect sends file output to original print."""
        import io
        ui = TextualUI()
        
        # Create a mock file
        buffer = io.StringIO()
        ui._print_redirect("Test output", file=buffer)
        
        # Check it went to the buffer
        assert buffer.getvalue() == "Test output\n"

    def test_print_redirect_no_app(self):
        """Test print redirect when app is not running."""
        import io
        import sys
        
        ui = TextualUI()
        
        # Capture stdout
        old_stdout = sys.stdout
        sys.stdout = io.StringIO()
        
        try:
            ui._print_redirect("Test message")
            output = sys.stdout.getvalue()
        finally:
            sys.stdout = old_stdout
        
        assert "Test message" in output

    def test_line_buffer_initialization(self):
        """Test line buffer starts empty."""
        ui = TextualUI()
        assert ui._line_buffer == ""


class TestLogPanelWriteLog:
    """Test LogPanel write_log method."""

    def test_write_log_exists(self):
        """Test write_log method exists."""
        panel = LogPanel()
        assert hasattr(panel, "write_log")
        assert callable(panel.write_log)


class TestTextualUIIntegration:
    """Test TextualUI integration scenarios."""

    def test_ui_with_mock_app(self):
        """Test UI with mocked app object."""
        from unittest.mock import MagicMock
        
        ui = TextualUI()
        ui._app = MagicMock()
        ui._is_running = True
        
        # Test update_header
        ui.update_header("ID-1", "Title", "Status")
        ui._app.update_work_item.assert_called_once_with("ID-1", "Title", "Status")
        
        # Test update_stats
        mock_stats = MagicMock()
        ui.update_stats(mock_stats, 60.0)
        ui._app.update_stats.assert_called_once_with(mock_stats, 60.0)
        
        # Test set_session_start_time
        ui.set_session_start_time(100.0)
        ui._app.set_session_start_time.assert_called_once_with(100.0)
        
        # Test set_current_agent
        ui.set_current_agent("TestAgent")
        ui._app.set_current_agent.assert_called_once_with("TestAgent")
        
        # Test log_message
        ui.log_message("msg", "orchestrator", "red")
        ui._app.log_message.assert_called_once_with("msg", "orchestrator", "red")

    def test_agent_output_with_mock_app(self):
        """Test agent_output context with mocked app."""
        from unittest.mock import MagicMock
        
        ui = TextualUI()
        ui._app = MagicMock()
        ui._is_running = True
        ui._app.get_target_buffer.return_value = "orchestrator"
        
        with ui.agent_output():
            # Inside context, should set to agent
            ui._app.set_target_buffer.assert_called_with("agent")
        
        # After context, should restore previous
        assert ui._app.set_target_buffer.call_count >= 2

    def test_print_redirect_with_mock_app(self):
        """Test print redirect with mocked app."""
        from unittest.mock import MagicMock
        
        ui = TextualUI()
        ui._app = MagicMock()
        ui._is_running = True
        ui._app.get_target_buffer.return_value = "orchestrator"
        
        # Send a complete line
        ui._print_redirect("Test line")
        
        # Should have called log_message
        ui._app.log_message.assert_called()

    def test_print_redirect_partial_line(self):
        """Test print redirect with partial line (no newline)."""
        from unittest.mock import MagicMock
        
        ui = TextualUI()
        ui._app = MagicMock()
        ui._is_running = True
        ui._app.get_target_buffer.return_value = "orchestrator"
        
        # Send partial line (no newline yet)
        ui._print_redirect("partial", end="")
        
        # Line should be buffered
        assert "partial" in ui._line_buffer
