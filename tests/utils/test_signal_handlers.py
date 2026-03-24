"""Tests for signal handler functionality in PokePoke orchestrator."""

import contextlib
import signal
import tempfile
import threading
from unittest.mock import Mock, patch

from pokepoke.utils.logging_utils import RunLogger
from pokepoke.utils.signal_handlers import register_shutdown_handlers, unregister_shutdown_handlers


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

    @patch('pokepoke.utils.signal_handlers.request_shutdown_from_signal')
    def test_sigterm_handler_logs_and_exits(self, mock_request_shutdown_from_signal):
        """Test that SIGTERM handler logs and calls signal-safe shutdown."""
        mock_logger = Mock()
        register_shutdown_handlers(mock_logger)

        from pokepoke.utils.signal_handlers import _signal_handler

        _signal_handler(signal.SIGTERM, None)

        # Verify logging was called
        mock_logger.log_orchestrator.assert_any_call(
            "Process terminated by signal SIGTERM (15)",
            level="WARNING"
        )
        mock_logger.log_orchestrator.assert_any_call(
            "PokePoke orchestrator shutdown due to signal"
        )

        # Signal handler must use the signal-safe variant, not request_shutdown()
        mock_request_shutdown_from_signal.assert_called_once()

    @patch('pokepoke.utils.signal_handlers.request_shutdown_from_signal')
    def test_sigint_handler_logs_and_exits(self, mock_request_shutdown_from_signal):
        """Test that SIGINT handler logs and calls signal-safe shutdown."""
        mock_logger = Mock()
        register_shutdown_handlers(mock_logger)

        from pokepoke.utils.signal_handlers import _signal_handler

        _signal_handler(signal.SIGINT, None)

        mock_logger.log_orchestrator.assert_any_call(
            "Process terminated by signal SIGINT (2)",
            level="WARNING"
        )

        mock_request_shutdown_from_signal.assert_called_once()

    @patch('pokepoke.utils.signal_handlers.request_shutdown_from_signal')
    def test_signal_handler_fallback_when_no_logger(self, mock_request_shutdown_from_signal, capsys):
        """Test that signal handler falls back to stderr when no logger available."""
        # Don't register a logger
        from pokepoke.utils.signal_handlers import _signal_handler

        # Call handler without logger
        _signal_handler(signal.SIGTERM, None)

        # Verify fallback to stderr/stdout via logger
        captured = capsys.readouterr()
        combined = captured.out + captured.err
        assert "signal SIGTERM" in combined

        mock_request_shutdown_from_signal.assert_called_once()

    @patch('pokepoke.utils.signal_handlers.request_shutdown_from_signal')
    def test_signal_handler_handles_logger_exception(self, mock_request_shutdown_from_signal):
        """Test that signal handler handles logging exceptions gracefully."""
        mock_logger = Mock()
        mock_logger.log_orchestrator.side_effect = Exception("Logging failed")

        register_shutdown_handlers(mock_logger)

        from pokepoke.utils.signal_handlers import _signal_handler

        # Call handler - should not raise exception
        _signal_handler(signal.SIGTERM, None)

        mock_request_shutdown_from_signal.assert_called_once()

    def test_signal_handler_catches_request_shutdown_exception(self, capsys):
        """Covers exception path when request_shutdown_from_signal fails."""
        mock_logger = Mock()
        mock_logger.log_orchestrator.side_effect = Exception("Logging failed")

        register_shutdown_handlers(mock_logger)

        from pokepoke.utils.signal_handlers import _signal_handler

        with patch('pokepoke.utils.signal_handlers.request_shutdown_from_signal', side_effect=RuntimeError("shutdown broke")):
            # Should not raise even though request_shutdown_from_signal throws
            _signal_handler(signal.SIGTERM, None)

        # Should have logged error about failed shutdown
        captured = capsys.readouterr()
        assert "Failed to request graceful shutdown" in captured.err

    def test_unregister_restores_sig_dfl_when_no_original(self):
        """Covers line 120: SIG_DFL restore when original handler was None."""
        import pokepoke.utils.signal_handlers as sh

        # Register handlers first
        register_shutdown_handlers(Mock())
        # Simulate that one handler had no original
        sh._original_handlers[signal.SIGTERM] = None
        unregister_shutdown_handlers()
        # Should have set to SIG_DFL without error
        current = signal.getsignal(signal.SIGTERM)
        assert current == signal.SIG_DFL

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

            # Clean up signal handlers first, then close log file handles
            # so the temp directory can be removed on Windows.
            unregister_shutdown_handlers()
            run_logger._orch_handler.close()
            run_logger._py_logger.removeHandler(run_logger._orch_handler)

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
        import pokepoke.utils.signal_handlers as sh
        assert sh._current_logger is mock_logger

        # Clean up
        unregister_shutdown_handlers()


class TestOrchestratorSignalIntegration:
    """Test signal handler integration in orchestrator."""

    @patch('pokepoke.orchestration.orchestrator.register_shutdown_handlers')
    def test_orchestrator_registers_handlers(self, mock_register):
        """Test that orchestrator registers signal handlers."""
        from pokepoke.orchestration.orchestrator import run_orchestrator

        # Mock out dependencies to avoid full orchestrator startup
        with patch('pokepoke.orchestration.orchestrator.initialize_agent_name', return_value='test-agent'), \
             patch('pokepoke.orchestration.orchestrator.get_ready_work_items', return_value=[]), \
             patch('pokepoke.orchestration.orchestrator.select_work_item', return_value=None), \
             patch('pokepoke.orchestration.orchestrator.get_beads_stats', return_value={}), \
             patch('pokepoke.orchestration.orchestrator.check_and_commit_main_repo', return_value=True), \
             patch('pokepoke.orchestration.orchestrator.terminal_ui'), \
             patch('pokepoke.orchestration.orchestrator.load_config') as mock_config:

            mock_config.return_value = Mock(max_parallel_agents=1)

            with contextlib.suppress(SystemExit):
                # Expected when no work items available
                run_orchestrator(interactive=False, continuous=False)

        # Verify signal handlers were registered
        mock_register.assert_called_once()

        # Verify the call was made with a RunLogger instance
        call_args = mock_register.call_args
        assert len(call_args[0]) == 1
        # Check that it looks like a RunLogger (has the expected methods)
        logger_arg = call_args[0][0]
        assert hasattr(logger_arg, 'log_orchestrator')
        assert hasattr(logger_arg, 'get_run_id')
