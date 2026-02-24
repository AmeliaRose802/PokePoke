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
    has_active_agents,
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

    @patch("pokepoke.shutdown._thread.interrupt_main")
    @patch("pokepoke.shutdown.merge_lock_active", return_value=False)
    @patch("pokepoke.shutdown.time.sleep")
    def test_force_exits_when_still_shutting_down(self, mock_sleep, _mock_lock, mock_interrupt):
        from pokepoke.shutdown import _watchdog_thread

        _shutdown_event.set()
        _watchdog_thread(1.0)

        mock_sleep.assert_called_once_with(1.0)
        mock_interrupt.assert_called_once()

    @patch("pokepoke.shutdown._thread.interrupt_main")
    @patch("pokepoke.shutdown.time.sleep")
    def test_no_exit_when_not_shutting_down(self, mock_sleep, mock_interrupt):
        from pokepoke.shutdown import _watchdog_thread

        # Don't set shutdown event
        _watchdog_thread(1.0)

        mock_sleep.assert_called_once_with(1.0)
        mock_interrupt.assert_not_called()

    @patch("pokepoke.shutdown._thread.interrupt_main")
    @patch("pokepoke.shutdown.merge_lock_active")
    @patch("pokepoke.shutdown.time.sleep")
    def test_waits_for_merge_lock_before_exit(self, mock_sleep, mock_lock, mock_interrupt):
        from pokepoke.shutdown import _watchdog_thread

        _shutdown_event.set()
        # First call: lock active; subsequent call: lock released
        mock_lock.side_effect = [True, False]

        _watchdog_thread(1.0)

        # First call is the initial timeout, then at least one poll while lock is active
        assert mock_sleep.call_count >= 2
        mock_sleep.assert_any_call(1.0)
        mock_interrupt.assert_called_once()

    @patch("pokepoke.shutdown._thread.interrupt_main")
    @patch("pokepoke.shutdown.merge_lock_active")
    @patch("pokepoke.shutdown.time.sleep")
    @patch("pokepoke.shutdown.time.monotonic")
    def test_merge_lock_wait_cap(self, mock_monotonic, mock_sleep, mock_lock, mock_interrupt):
        """Watchdog interrupts after merge lock wait cap even if lock is still held."""
        from pokepoke.shutdown import _watchdog_thread

        _shutdown_event.set()
        # Lock is always active
        mock_lock.return_value = True
        # Simulate time progression past the 120s cap
        mock_monotonic.side_effect = [0.0, 121.0]

        _watchdog_thread(1.0)

        mock_interrupt.assert_called_once()

    @patch("pokepoke.shutdown._thread.interrupt_main")
    @patch("pokepoke.shutdown.merge_lock_active")
    @patch("pokepoke.shutdown.time.sleep")
    def test_merge_lock_exception_falls_through(self, mock_sleep, mock_lock, mock_interrupt):
        """Watchdog still interrupts if merge_lock_active raises an exception."""
        from pokepoke.shutdown import _watchdog_thread

        _shutdown_event.set()
        mock_lock.side_effect = RuntimeError("file lock broken")

        _watchdog_thread(1.0)

        mock_interrupt.assert_called_once()


class TestMergeQueueShutdown:
    """Tests for merge queue shutdown coordination in request_shutdown."""

    @patch("pokepoke.shutdown.threading.Thread")
    def test_shutdown_calls_merge_queue_shutdown(self, mock_thread_cls):
        """request_shutdown synchronously shuts down the merge queue if running."""
        mock_thread_cls.return_value.start = lambda: None

        shutdown_calls: list[float] = []
        mock_mq = type(
            "FakeMQ",
            (),
            {
                "is_running": True,
                "shutdown": lambda self, timeout=30.0: shutdown_calls.append(timeout),
            },
        )()

        with patch("pokepoke.merge_queue.get_merge_queue", return_value=mock_mq):
            request_shutdown()
            assert shutdown_calls == [180.0]

    @patch("pokepoke.shutdown.threading.Thread")
    def test_shutdown_skips_merge_queue_if_not_running(self, mock_thread_cls):
        """request_shutdown does not shut down merge queue if queue not running."""
        mock_thread_cls.return_value.start = lambda: None

        shutdown_calls: list[float] = []
        mock_mq = type(
            "FakeMQ",
            (),
            {
                "is_running": False,
                "shutdown": lambda self, timeout=30.0: shutdown_calls.append(timeout),
            },
        )()

        with patch("pokepoke.merge_queue.get_merge_queue", return_value=mock_mq):
            request_shutdown()
            assert shutdown_calls == []

    @patch("pokepoke.shutdown.threading.Thread")
    def test_shutdown_handles_merge_queue_exception(self, mock_thread_cls):
        """request_shutdown continues if merge queue raises."""
        mock_thread_cls.return_value.start = lambda: None
        with patch("pokepoke.merge_queue.get_merge_queue", side_effect=RuntimeError("no queue")):
            request_shutdown()
            # Should still start the watchdog thread
            assert any(
                call.kwargs.get("name") == "shutdown-watchdog"
                for call in mock_thread_cls.call_args_list
            )


class TestHasActiveAgents:
    """Tests for has_active_agents()."""

    def test_false_when_no_agents_and_no_executor(self):
        assert has_active_agents() is False

    def test_true_when_agents_registered(self):
        register_agent()
        assert has_active_agents() is True

    def test_true_when_executor_set(self):
        import pokepoke.shutdown as mod
        mock_executor = object()
        mod._executor = mock_executor
        assert has_active_agents() is True

    def test_false_after_agents_unregistered_and_no_executor(self):
        register_agent()
        unregister_agent()
        assert has_active_agents() is False


class TestShutdownReset:
    """Additional shutdown coordination tests."""

    def test_reset_clears_shutdown_and_stop(self):
        """Verify reset clears shutdown event and stop flag."""
        request_shutdown()
        request_stop_after_current()
        reset()
        assert not is_shutting_down()
        assert not should_stop_after_current()
