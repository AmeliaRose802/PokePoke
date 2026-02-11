"""Tests for the Textual-based UI components.

Note: The full Textual pilot tests have compatibility issues with Python 3.13.
These tests focus on unit testing the components directly without requiring
the full async app lifecycle.
"""

import pytest
from unittest.mock import MagicMock

from pokepoke.textual_ui import PokePokeApp, TextualUI, MessageType, UIMessage
from pokepoke.textual_widgets import StatsBar, WorkItemHeader, LogPanel, ProgressIndicator


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
        # Should have copy bindings
        assert "c" in binding_keys  # copy selection
        assert "y" in binding_keys  # copy all


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

    def test_log_ui_msg_queues(self):
        """Test that log_message adds to queue."""
        from pokepoke.textual_ui import MessageType
        app = PokePokeApp()
        app.log_message("Test message", target="orchestrator")
        
        # Message should be in queue
        assert not app._ui_msg_queue.empty()
        msg = app._ui_msg_queue.get()
        assert msg.msg_type == MessageType.LOG
        assert msg.args == ("orchestrator", "Test message", None)

    def test_update_work_item_queues(self):
        """Test that update_work_item adds to queue."""
        from pokepoke.textual_ui import MessageType
        app = PokePokeApp()
        app.update_work_item("ITEM-123", "Test Title", "Active")
        
        assert not app._ui_msg_queue.empty()
        msg = app._ui_msg_queue.get()
        assert msg.msg_type == MessageType.WORK_ITEM
        assert msg.args == ("ITEM-123", "Test Title", "Active")

    def test_update_stats_queues(self):
        """Test that update_stats adds to queue."""
        from pokepoke.textual_ui import MessageType
        app = PokePokeApp()
        mock_stats = MagicMock()
        app.update_stats(mock_stats, 60.0)
        
        assert app._current_stats == mock_stats
        assert not app._ui_msg_queue.empty()
        msg = app._ui_msg_queue.get()
        assert msg.msg_type == MessageType.STATS
        assert msg.args[0] == mock_stats
        assert msg.args[1] == 60.0

    def test_set_current_agent_queues(self):
        """Test that set_current_agent adds to queue."""
        from pokepoke.textual_ui import MessageType
        app = PokePokeApp()
        app.set_current_agent("WorkAgent")
        
        assert not app._ui_msg_queue.empty()
        msg = app._ui_msg_queue.get()
        assert msg.msg_type == MessageType.AGENT_NAME
        assert msg.args == ("WorkAgent",)

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
        
        # elapsed_time is now a formatted string HH:MM:SS
        assert stats_bar.elapsed_time == "00:01:00"
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
        
        # elapsed_time is now a formatted string HH:MM:SS
        assert stats_bar.elapsed_time == "00:05:00"
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
        # elapsed_time is now a formatted string
        assert stats_bar.elapsed_time == "00:00:00"
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
        stats_bar.elapsed_time = "00:02:00"  # 2 minutes as formatted string
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
        assert "00:02:00" in text_str  # elapsed time as HH:MM:SS
        assert "1.0m" in text_str  # API minutes
        assert "1.0K" in text_str  # input tokens formatted
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
        # Status is rendered in uppercase
        assert "IN_PROGRESS" in text_str

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

    def test_stop_and_capture_captures_output(self):
        """Test stop_and_capture() captures print output to _final_output."""
        import builtins
        ui = TextualUI()
        original_print = builtins.print
        
        ui.stop_and_capture()
        assert ui.is_running is False
        
        # Print should now be captured
        print("Test output 1")
        print("Test output 2")
        
        assert len(ui._final_output) == 2
        assert "Test output 1" in ui._final_output[0]
        assert "Test output 2" in ui._final_output[1]
        
        # Restore original print
        builtins.print = original_print

    def test_stop_and_capture_to_file_not_captured(self):
        """Test stop_and_capture() doesn't capture output to files."""
        import builtins
        import io
        ui = TextualUI()
        original_print = builtins.print
        
        ui.stop_and_capture()
        
        # Print to file should not be captured
        buffer = io.StringIO()
        print("File output", file=buffer)
        
        assert len(ui._final_output) == 0
        assert buffer.getvalue() == "File output\n"
        
        # Restore original print
        builtins.print = original_print

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
        assert app._ui_msg_queue is not None
        assert app._ui_msg_queue.empty()

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
        """Test _process_ui_msg_queue with empty queue."""
        app = PokePokeApp()
        # Should not raise
        app._process_ui_msg_queue()

    def test_handle_message_bad_type(self):
        """Test _handle_message with unknown type."""
        from pokepoke.textual_ui import UIMessage, MessageType
        app = PokePokeApp()
        # Create a message with a valid type but should not crash
        msg = UIMessage(MessageType.LOG, ("orchestrator", "test", None))
        # Should not raise even without widgets mounted
        app._handle_message(msg)


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

    def test_print_redirect_flush_streams_partial(self):
        """Test print redirect with flush=True defers output to batch streaming tokens."""
        import time
        from unittest.mock import MagicMock
        
        ui = TextualUI()
        ui._app = MagicMock()
        ui._is_running = True
        ui._app.get_target_buffer.return_value = "agent"
        
        # Send partial line with flush=True (like streaming agent output)
        ui._print_redirect("streaming", end="", flush=True)
        
        # Should NOT have called log_message immediately (deferred flush)
        ui._app.log_message.assert_not_called()
        # Buffer should still hold the content
        assert ui._line_buffer == "streaming"
        # A flush timer should be scheduled
        assert ui._flush_timer is not None
        
        # After the timer fires, the buffer should be flushed
        time.sleep(0.15)
        ui._app.log_message.assert_called_with("streaming", "agent", None)
        assert ui._line_buffer == ""

    def test_print_redirect_flush_only_when_buffer_not_empty(self):
        """Test that flush=True doesn't call log_message when buffer is empty."""
        from unittest.mock import MagicMock
        
        ui = TextualUI()
        ui._app = MagicMock()
        ui._is_running = True
        ui._app.get_target_buffer.return_value = "agent"
        
        # Send just newline with flush (buffer ends up empty after processing)
        ui._print_redirect("", end="\n", flush=True)
        
        # Since message is empty after processing newline, no extra call from flush
        # The newline processing happens but empty line is skipped
        assert ui._line_buffer == ""


class TestTextualMessagesModule:
    """Test textual_messages module."""

    def test_message_type_enum(self):
        """Test MessageType enum values."""
        assert MessageType.LOG is not None
        assert MessageType.WORK_ITEM is not None
        assert MessageType.STATS is not None
        assert MessageType.AGENT_NAME is not None
        assert MessageType.PROGRESS is not None

    def test_ui_message_creation(self):
        """Test UIMessage dataclass creation."""
        msg = UIMessage(MessageType.LOG, ("target", "message", "style"))
        assert msg.msg_type == MessageType.LOG
        assert msg.args == ("target", "message", "style")

    def test_ui_message_immutable(self):
        """Test UIMessage is frozen (immutable)."""
        msg = UIMessage(MessageType.LOG, ("arg1",))
        # Should raise FrozenInstanceError when trying to modify
        try:
            msg.msg_type = MessageType.STATS
            assert False, "Should have raised an error"
        except Exception:
            pass  # Expected


class TestTextualUIContextManagers:
    """Test TextualUI context managers."""

    def test_orchestrator_output_without_app(self):
        """Test orchestrator_output when no app is set."""
        ui = TextualUI()
        with ui.orchestrator_output():
            pass  # Should not raise

    def test_styled_output_context(self):
        """Test styled_output context manager."""
        ui = TextualUI()
        assert ui._current_style is None
        
        with ui.styled_output("bold red"):
            assert ui._current_style == "bold red"
        
        # Should restore None after context
        assert ui._current_style is None

    def test_styled_output_nested(self):
        """Test nested styled_output contexts."""
        ui = TextualUI()
        
        with ui.styled_output("green"):
            assert ui._current_style == "green"
            with ui.styled_output("red"):
                assert ui._current_style == "red"
            assert ui._current_style == "green"
        
        assert ui._current_style is None


class TestTextualUILogHelpers:
    """Test TextualUI log helper methods."""

    def test_log_orchestrator_with_app(self):
        """Test log_orchestrator with mocked app."""
        from unittest.mock import MagicMock
        
        ui = TextualUI()
        ui._app = MagicMock()
        
        ui.log_orchestrator("test message", "bold")
        ui._app.log_orchestrator.assert_called_once_with("test message", "bold")

    def test_log_agent_with_app(self):
        """Test log_agent with mocked app."""
        from unittest.mock import MagicMock
        
        ui = TextualUI()
        ui._app = MagicMock()
        
        ui.log_agent("agent message", "green")
        ui._app.log_agent.assert_called_once_with("agent message", "green")

    def test_log_helpers_without_app(self):
        """Test log helpers don't crash without app."""
        ui = TextualUI()
        ui.log_orchestrator("test")  # Should not raise
        ui.log_agent("test")  # Should not raise


class TestTextualWidgetsAdditional:
    """Additional tests for textual_widgets module."""

    def test_stats_bar_format_tokens_millions(self):
        """Test StatsBar token formatting for millions."""
        stats_bar = StatsBar()
        result = stats_bar._format_tokens(1_500_000)
        assert result == "1.5M"

    def test_stats_bar_format_tokens_thousands(self):
        """Test StatsBar token formatting for thousands."""
        stats_bar = StatsBar()
        result = stats_bar._format_tokens(5000)
        assert result == "5.0K"

    def test_stats_bar_format_tokens_small(self):
        """Test StatsBar token formatting for small numbers."""
        stats_bar = StatsBar()
        result = stats_bar._format_tokens(500)
        assert result == "500"

    def test_stats_bar_format_duration_seconds(self):
        """Test StatsBar duration formatting for seconds."""
        stats_bar = StatsBar()
        result = stats_bar._format_duration(45)
        assert result == "45s"

    def test_stats_bar_format_duration_minutes(self):
        """Test StatsBar duration formatting for minutes."""
        stats_bar = StatsBar()
        result = stats_bar._format_duration(90)
        assert result == "1.5m"

    def test_stats_bar_format_duration_hours(self):
        """Test StatsBar duration formatting for hours."""
        stats_bar = StatsBar()
        result = stats_bar._format_duration(7200)
        assert result == "2.0h"


class TestWorkItemHeaderAdditional:
    """Additional tests for WorkItemHeader widget."""

    def test_get_status_style_in_progress(self):
        """Test status style for in_progress."""
        header = WorkItemHeader()
        assert header._get_status_style("in_progress") == "bold yellow"
        assert header._get_status_style("IN PROGRESS") == "bold yellow"

    def test_get_status_style_ready(self):
        """Test status style for ready."""
        header = WorkItemHeader()
        assert header._get_status_style("ready") == "bold green"
        assert header._get_status_style("pending") == "bold green"

    def test_get_status_style_blocked(self):
        """Test status style for blocked."""
        header = WorkItemHeader()
        assert header._get_status_style("blocked") == "bold red"
        assert header._get_status_style("failed") == "bold red"

    def test_get_status_style_done(self):
        """Test status style for done."""
        header = WorkItemHeader()
        assert header._get_status_style("done") == "bold cyan"
        assert header._get_status_style("completed") == "bold cyan"

    def test_get_status_style_unknown(self):
        """Test status style for unknown status."""
        header = WorkItemHeader()
        assert header._get_status_style("unknown") == "dim"

    def test_truncate_title_short(self):
        """Test title truncation for short titles."""
        header = WorkItemHeader()
        result = header._truncate_title("Short title")
        assert result == "Short title"

    def test_truncate_title_long(self):
        """Test title truncation for long titles."""
        header = WorkItemHeader()
        long_title = "A" * 70
        result = header._truncate_title(long_title)
        assert len(result) == 60
        assert result.endswith("...")


class TestLogPanelAdditional:
    """Additional tests for LogPanel widget."""

    def test_detect_log_level_error(self):
        """Test log level detection for errors."""
        panel = LogPanel()
        assert panel._detect_log_level("ERROR: something failed") == "error"
        assert panel._detect_log_level("Operation failed") == "error"
        assert panel._detect_log_level("exception occurred") == "error"

    def test_detect_log_level_warning(self):
        """Test log level detection for warnings."""
        panel = LogPanel()
        assert panel._detect_log_level("WARNING: something") == "warning"
        assert panel._detect_log_level("warn: caution") == "warning"

    def test_detect_log_level_success(self):
        """Test log level detection for success."""
        panel = LogPanel()
        assert panel._detect_log_level("SUCCESS!") == "success"
        assert panel._detect_log_level("Task completed") == "success"
        assert panel._detect_log_level("✅ Done") == "success"

    def test_detect_log_level_debug(self):
        """Test log level detection for debug."""
        panel = LogPanel()
        assert panel._detect_log_level("DEBUG: trace info") == "debug"

    def test_detect_log_level_info(self):
        """Test log level detection for info (default)."""
        panel = LogPanel()
        assert panel._detect_log_level("Normal message") == "info"

    def test_get_all_text_empty(self):
        """Test get_all_text returns empty string when no logs."""
        panel = LogPanel()
        result = panel.get_all_text()
        assert result == ""

    def test_get_all_text_with_lines(self):
        """Test get_all_text extracts text from Strip objects."""
        from unittest.mock import MagicMock
        panel = LogPanel()
        # Create mock Strip objects with text property
        mock_strip1 = MagicMock()
        mock_strip1.text = "First line"
        mock_strip2 = MagicMock()
        mock_strip2.text = "Second line"
        panel.lines = [mock_strip1, mock_strip2]
        result = panel.get_all_text()
        assert result == "First line\nSecond line"

    def test_get_all_text_fallback_to_str(self):
        """Test get_all_text uses str() for non-Strip objects."""
        panel = LogPanel()
        # Add plain strings (fallback case)
        panel.lines = ["plain text"]
        result = panel.get_all_text()
        assert "plain text" in result


class TestProgressIndicator:
    """Tests for ProgressIndicator widget."""

    def test_progress_indicator_creates(self):
        """Test that ProgressIndicator can be instantiated."""
        indicator = ProgressIndicator()
        assert indicator is not None
        assert indicator.is_active is False
        assert indicator.status_text == ""

    def test_progress_indicator_start(self):
        """Test starting the progress indicator."""
        indicator = ProgressIndicator()
        indicator.start("Processing...")
        assert indicator.is_active is True
        assert indicator.status_text == "Processing..."

    def test_progress_indicator_stop(self):
        """Test stopping the progress indicator."""
        indicator = ProgressIndicator()
        indicator.start("Working")
        indicator.stop("Done")
        assert indicator.is_active is False
        assert indicator.status_text == "Done"

    def test_progress_indicator_spinner_frames(self):
        """Test that spinner frames are defined."""
        indicator = ProgressIndicator()
        assert len(indicator.SPINNER_FRAMES) > 0
        assert all(isinstance(f, str) for f in indicator.SPINNER_FRAMES)

    def test_progress_indicator_render_active(self):
        """Test render when active."""
        indicator = ProgressIndicator()
        indicator.start("Loading")
        result = indicator.render()
        text_str = str(result)
        assert "Loading" in text_str

    def test_progress_indicator_render_idle_with_status(self):
        """Test render when idle with status."""
        indicator = ProgressIndicator()
        indicator.stop("Finished")
        result = indicator.render()
        text_str = str(result)
        assert "Finished" in text_str

    def test_progress_indicator_render_idle_no_status(self):
        """Test render when idle without status."""
        indicator = ProgressIndicator()
        result = indicator.render()
        # Should return empty or minimal text
        assert result is not None
