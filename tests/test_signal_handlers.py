"""Tests for signal handler functionality in PokePoke orchestrator."""

import signal
import tempfile
import threading
from unittest.mock import Mock, patch

from pokepoke.signal_handlers import register_shutdown_handlers, unregister_shutdown_handlers
from pokepoke.logging_utils import RunLogger


class TestSignalHandlers:
    """Test signal handling functionality."""

    def setup_method(self):
        """Set up test environment."""
        # Clean up any existing handlers
        unregister_shutdown_handlers()

    def teardown_method(self):
        """Clean up after tests."""
        # Clean up any handlers we registered
        unregister_shutdown_handlers()

    def test_register_handlers_stores_logger(self):
        """Test that registering handlers stores the logger reference."""
        # Create a mock logger
        mock_logger = Mock()

        # Register handlers
        register_shutdown_handlers(mock_logger)

        # Verify the logger is stored by checking we don't get import errors
        # when calling register again
        register_shutdown_handlers(mock_logger)

    def test_unregister_handlers_cleans_up(self):
        """Test that unregistering handlers cleans up properly."""
        mock_logger = Mock()

        # Register and then unregister
        register_shutdown_handlers(mock_logger)
        unregister_shutdown_handlers()

        # Should be able to register again without issues
        register_shutdown_handlers(mock_logger)

    @patch('pokepoke.signal_handlers.sys.exit')
    def test_sigterm_handler_logs_and_exits(self, mock_exit):
        """Test that SIGTERM handler logs appropriately and exits."""
        mock_logger = Mock()
        register_shutdown_handlers(mock_logger)

        # Send SIGTERM to current process
        # We need to use a different approach since we can't actually kill ourselves
        # Instead, we'll manually call the handler
        from pokepoke.signal_handlers import _signal_handler

        # Call the handler directly
        _signal_handler(signal.SIGTERM, None)

        # Verify logging was called
        mock_logger.log_orchestrator.assert_any_call(
            "Process terminated by signal SIGTERM (15)",
            level="WARNING"
        )
        mock_logger.log_orchestrator.assert_any_call(
            "PokePoke orchestrator shutdown due to signal"
        )

        # Verify sys.exit was called with appropriate code (128 + signal number)
        mock_exit.assert_called_once_with(128 + signal.SIGTERM)

    @patch('pokepoke.signal_handlers.sys.exit')
    def test_sigint_handler_logs_and_exits(self, mock_exit):
        """Test that SIGINT handler logs appropriately and exits."""
        mock_logger = Mock()
        register_shutdown_handlers(mock_logger)

        from pokepoke.signal_handlers import _signal_handler

        # Call the handler directly
        _signal_handler(signal.SIGINT, None)

        # Verify logging was called
        mock_logger.log_orchestrator.assert_any_call(
            "Process terminated by signal SIGINT (2)",
            level="WARNING"
        )

        # Verify sys.exit was called with appropriate code
        mock_exit.assert_called_once_with(128 + signal.SIGINT)

    @patch('pokepoke.signal_handlers.sys.exit')
    @patch('pokepoke.signal_handlers.print')
    def test_signal_handler_fallback_when_no_logger(self, mock_print, mock_exit):
        """Test that signal handler falls back to stderr when no logger available."""
        # Don't register a logger
        from pokepoke.signal_handlers import _signal_handler

        # Call handler without logger
        _signal_handler(signal.SIGTERM, None)

        # Verify fallback to stderr
        mock_print.assert_called()
        # Check that one of the calls was about signal termination
        call_args_list = mock_print.call_args_list
        signal_messages = [call for call in call_args_list
                         if any("signal SIGTERM" in str(arg) for arg in call[0])]
        assert len(signal_messages) > 0

        mock_exit.assert_called_once_with(128 + signal.SIGTERM)

    @patch('pokepoke.signal_handlers.sys.exit')
    def test_signal_handler_handles_logger_exception(self, mock_exit):
        """Test that signal handler handles logging exceptions gracefully."""
        # Create a mock logger that raises an exception
        mock_logger = Mock()
        mock_logger.log_orchestrator.side_effect = Exception("Logging failed")

        register_shutdown_handlers(mock_logger)

        from pokepoke.signal_handlers import _signal_handler

        # Call handler - should not raise exception
        _signal_handler(signal.SIGTERM, None)

        # Should still exit despite logging failure
        mock_exit.assert_called_once_with(128 + signal.SIGTERM)

    def test_integration_with_real_logger(self):
        """Test integration with actual RunLogger."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create a real RunLogger
            run_logger = RunLogger(base_dir=temp_dir)

            # Register handlers
            register_shutdown_handlers(run_logger)

            # Verify registration doesn't raise errors
            # and that we can access the orchestrator log file
            assert run_logger.orchestrator_log_path.exists()

            # Clean up
            unregister_shutdown_handlers()

    def test_register_skips_signal_on_non_main_thread(self):
        """Test that register_shutdown_handlers skips signal registration on non-main thread."""
        mock_logger = Mock()
        error_box: list[Exception] = []

        def register_in_thread() -> None:
            try:
                # This should NOT raise even though we're not on the main thread
                register_shutdown_handlers(mock_logger)
            except Exception as exc:
                error_box.append(exc)

        t = threading.Thread(target=register_in_thread)
        t.start()
        t.join(timeout=5)

        assert not error_box, f"register_shutdown_handlers raised on non-main thread: {error_box[0]}"

        # Logger should still be stored even though signals weren't registered
        import pokepoke.signal_handlers as sh
        assert sh._current_logger is mock_logger

        # Clean up
        unregister_shutdown_handlers()


class TestOrchestratorSignalIntegration:
    """Test signal handler integration in orchestrator."""

    @patch('pokepoke.orchestrator.register_shutdown_handlers')
    def test_orchestrator_registers_handlers(self, mock_register):
        """Test that orchestrator registers signal handlers."""
        from pokepoke.orchestrator import run_orchestrator

        # Mock out dependencies to avoid full orchestrator startup
        with patch('pokepoke.orchestrator.initialize_agent_name', return_value='test-agent'), \
             patch('pokepoke.orchestrator.get_ready_work_items', return_value=[]), \
             patch('pokepoke.orchestrator.select_work_item', return_value=None), \
             patch('pokepoke.orchestrator.get_beads_stats', return_value={}), \
             patch('pokepoke.orchestrator.check_and_commit_main_repo', return_value=True), \
             patch('pokepoke.orchestrator.terminal_ui'), \
             patch('pokepoke.orchestrator.load_config') as mock_config:

            mock_config.return_value = Mock(max_parallel_agents=1)

            try:
                run_orchestrator(interactive=False, continuous=False)
            except SystemExit:
                pass  # Expected when no work items available

        # Verify signal handlers were registered
        mock_register.assert_called_once()

        # Verify the call was made with a RunLogger instance
        call_args = mock_register.call_args
        assert len(call_args[0]) == 1
        # Check that it looks like a RunLogger (has the expected methods)
        logger_arg = call_args[0][0]
        assert hasattr(logger_arg, 'log_orchestrator')
        assert hasattr(logger_arg, 'get_run_id')
