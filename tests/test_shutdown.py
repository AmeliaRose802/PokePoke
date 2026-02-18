"""Tests for the shutdown coordination module."""

import threading
import time
from unittest.mock import patch

import pytest

from pokepoke.shutdown import (
    request_shutdown,
    is_shutting_down,
    wait_for_shutdown,
    reset,
    request_stop_after_current,
    cancel_stop_after_current,
    should_stop_after_current,
    register_agent,
    unregister_agent,
    get_active_agent_count,
    set_executor,
    _shutdown_event,
)


@pytest.fixture(autouse=True)
def _reset_shutdown():
    """Reset shutdown state before each test."""
    reset()
    import pokepoke.shutdown as _mod
    _mod._active_agent_count = 0
    _mod._executor = None
    yield
    reset()
    _mod._active_agent_count = 0
    _mod._executor = None


class TestIsShuttingDown:
    """Tests for is_shutting_down()."""

    def test_initially_false(self):
        assert is_shutting_down() is False

    def test_true_after_request(self):
        request_shutdown()
        assert is_shutting_down() is True


class TestRequestShutdown:
    """Tests for request_shutdown()."""

    @patch("pokepoke.shutdown.threading.Thread")
    def test_sets_event(self, mock_thread_cls):
        mock_thread_cls.return_value.start = lambda: None
        request_shutdown()
        assert _shutdown_event.is_set()

    @patch("pokepoke.shutdown.threading.Thread")
    def test_starts_watchdog(self, mock_thread_cls):
        mock_thread_cls.return_value.start = lambda: None
        request_shutdown()
        mock_thread_cls.assert_called_once()
        call_kwargs = mock_thread_cls.call_args
        assert call_kwargs.kwargs["daemon"] is True
        assert call_kwargs.kwargs["name"] == "shutdown-watchdog"

    @patch("pokepoke.shutdown.threading.Thread")
    def test_idempotent(self, mock_thread_cls):
        """Calling request_shutdown twice only starts one watchdog."""
        mock_thread_cls.return_value.start = lambda: None
        request_shutdown()
        request_shutdown()
        # Only one Thread created
        assert mock_thread_cls.call_count == 1


class TestWaitForShutdown:
    """Tests for wait_for_shutdown()."""

    def test_returns_false_on_timeout(self):
        result = wait_for_shutdown(timeout=0.01)
        assert result is False

    def test_returns_true_when_set(self):
        _shutdown_event.set()
        result = wait_for_shutdown(timeout=0.1)
        assert result is True

    def test_unblocks_when_shutdown_requested(self):
        """wait_for_shutdown unblocks promptly when shutdown is requested."""
        result_holder = [None]

        def waiter():
            result_holder[0] = wait_for_shutdown(timeout=5.0)

        t = threading.Thread(target=waiter)
        t.start()
        time.sleep(0.05)
        _shutdown_event.set()
        t.join(timeout=1.0)
        assert result_holder[0] is True


class TestReset:
    """Tests for reset()."""

    def test_clears_event(self):
        _shutdown_event.set()
        reset()
        assert is_shutting_down() is False

    def test_clears_stop_after_current(self):
        request_stop_after_current()
        reset()
        assert should_stop_after_current() is False


class TestStopAfterCurrent:
    """Tests for stop-after-current flag."""

    def test_initially_false(self):
        assert should_stop_after_current() is False

    def test_true_after_request(self):
        request_stop_after_current()
        assert should_stop_after_current() is True

    def test_cancel_clears_flag(self):
        request_stop_after_current()
        cancel_stop_after_current()
        assert should_stop_after_current() is False

    def test_cancel_when_not_set_is_safe(self):
        cancel_stop_after_current()
        assert should_stop_after_current() is False

    def test_request_is_idempotent(self):
        request_stop_after_current()
        request_stop_after_current()
        assert should_stop_after_current() is True
        cancel_stop_after_current()
        assert should_stop_after_current() is False


class TestAgentRegistration:
    """Tests for register_agent / unregister_agent / get_active_agent_count."""

    def test_initially_zero(self):
        assert get_active_agent_count() == 0

    def test_register_increments(self):
        register_agent()
        assert get_active_agent_count() == 1
        register_agent()
        assert get_active_agent_count() == 2

    def test_unregister_decrements(self):
        register_agent()
        register_agent()
        unregister_agent()
        assert get_active_agent_count() == 1

    def test_unregister_does_not_go_negative(self):
        unregister_agent()
        assert get_active_agent_count() == 0

    def test_watchdog_timeout_scales_with_agents(self):
        """Watchdog timeout increases per registered agent."""
        register_agent()
        register_agent()
        register_agent()
        with patch("pokepoke.shutdown.threading.Thread") as mock_thread_cls:
            mock_thread_cls.return_value.start = lambda: None
            request_shutdown()
            call_args = mock_thread_cls.call_args
            timeout_arg = call_args.kwargs["args"][0]
            # Base (5.0) + 3 agents * 3.0 = 14.0
            assert timeout_arg == 14.0


class TestSetExecutor:
    """Tests for set_executor."""

    def test_set_executor_stores_value(self):
        import pokepoke.shutdown as mod
        mock_executor = object()
        set_executor(mock_executor)
        assert mod._executor is mock_executor

    def test_set_executor_to_none(self):
        import pokepoke.shutdown as mod
        set_executor(object())
        set_executor(None)
        assert mod._executor is None

    @patch("pokepoke.shutdown.threading.Thread")
    def test_shutdown_calls_executor_shutdown(self, mock_thread_cls):
        """request_shutdown shuts down the executor if set."""
        mock_thread_cls.return_value.start = lambda: None
        mock_exec = patch("pokepoke.shutdown._executor").start()
        mock_exec.is_set = False

        import pokepoke.shutdown as mod
        mock_executor = type("FakeExecutor", (), {
            "shutdown": lambda self, wait=True, cancel_futures=False: None
        })()
        mod._executor = mock_executor

        with patch.object(mock_executor, "shutdown") as mock_sd:
            request_shutdown()
            mock_sd.assert_called_once_with(wait=False, cancel_futures=True)


class TestWatchdogThread:
    """Tests for _watchdog_thread."""

    @patch("pokepoke.shutdown.os._exit")
    @patch("pokepoke.shutdown.time.sleep")
    def test_force_exits_when_still_shutting_down(self, mock_sleep, mock_exit):
        from pokepoke.shutdown import _watchdog_thread
        _shutdown_event.set()
        _watchdog_thread(1.0)
        mock_sleep.assert_called_once_with(1.0)
        mock_exit.assert_called_once_with(130)

    @patch("pokepoke.shutdown.os._exit")
    @patch("pokepoke.shutdown.time.sleep")
    def test_no_exit_when_not_shutting_down(self, mock_sleep, mock_exit):
        from pokepoke.shutdown import _watchdog_thread
        # Don't set shutdown event
        _watchdog_thread(1.0)
        mock_sleep.assert_called_once_with(1.0)
        mock_exit.assert_not_called()


class TestMergeQueueShutdown:
    """Tests for merge queue shutdown coordination in request_shutdown."""

    @patch("pokepoke.shutdown.threading.Thread")
    def test_shutdown_starts_merge_queue_shutdown(self, mock_thread_cls):
        """request_shutdown starts a thread for merge queue shutdown."""
        calls = []
        def track_thread(*args, **kwargs):
            inst = type("FakeThread", (), {"start": lambda self: calls.append(kwargs.get("name"))})()
            return inst
        mock_thread_cls.side_effect = track_thread

        mock_mq = type("FakeMQ", (), {"is_running": True, "shutdown": lambda self, t: None})()
        with patch("pokepoke.merge_queue.get_merge_queue", return_value=mock_mq):
            request_shutdown()
            assert "merge-queue-shutdown" in calls

    @patch("pokepoke.shutdown.threading.Thread")
    def test_shutdown_skips_merge_queue_if_not_running(self, mock_thread_cls):
        """request_shutdown doesn't start merge queue thread if queue not running."""
        calls = []
        def track_thread(*args, **kwargs):
            inst = type("FakeThread", (), {"start": lambda self: calls.append(kwargs.get("name"))})()
            return inst
        mock_thread_cls.side_effect = track_thread

        mock_mq = type("FakeMQ", (), {"is_running": False, "shutdown": lambda self, t: None})()
        with patch("pokepoke.merge_queue.get_merge_queue", return_value=mock_mq):
            request_shutdown()
            assert "merge-queue-shutdown" not in calls
