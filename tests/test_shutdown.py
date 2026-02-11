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
    _shutdown_event,
    _WATCHDOG_GRACE_SECONDS,
)


@pytest.fixture(autouse=True)
def _reset_shutdown():
    """Reset shutdown state before each test."""
    reset()
    yield
    reset()


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
