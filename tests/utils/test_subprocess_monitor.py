"""Tests for subprocess output monitoring."""

import time
from unittest.mock import Mock, patch

import pytest

from pokepoke.utils.subprocess_monitor import SubprocessMonitor, create_monitor_for_client


def test_subprocess_monitor_initialization():
    """Test SubprocessMonitor can be created with basic config."""
    monitor = SubprocessMonitor(copilot_pid=12345)
    assert monitor._copilot_pid == 12345
    assert monitor._monitoring is False
    assert monitor._item_logger is None
    assert monitor._on_output is None


def test_subprocess_monitor_start_stop():
    """Test monitor can be started and stopped."""
    monitor = SubprocessMonitor(copilot_pid=12345)

    # Start monitoring
    monitor.start()
    assert monitor._monitoring is True
    assert monitor._monitor_thread is not None
    thread = monitor._monitor_thread
    assert thread.is_alive()

    # Stop monitoring
    monitor.stop()
    assert monitor._monitoring is False
    # Thread reference is cleared, but the original thread should be stopped
    time.sleep(0.1)
    assert not thread.is_alive()


def test_subprocess_monitor_double_start_is_safe():
    """Test calling start() twice doesn't create duplicate threads."""
    monitor = SubprocessMonitor(copilot_pid=12345)

    monitor.start()
    first_thread = monitor._monitor_thread

    monitor.start()
    second_thread = monitor._monitor_thread

    # Should be the same thread
    assert first_thread is second_thread

    monitor.stop()


def test_subprocess_monitor_output_callback():
    """Test that output callback is invoked with captured output."""
    output_captured = []

    def capture_output(source: str, text: str) -> None:
        output_captured.append((source, text))

    monitor = SubprocessMonitor(
        copilot_pid=12345,
        on_output=capture_output,
    )

    # Emit some output directly (testing the callback mechanism)
    monitor._emit_output("stdout", "test output")
    monitor._emit_output("stderr", "error message")

    assert len(output_captured) == 2
    assert output_captured[0] == ("stdout", "test output")
    assert output_captured[1] == ("stderr", "error message")


def test_subprocess_monitor_logs_output_to_item_logger():
    """Test that output is logged to ItemLogger if provided."""
    mock_logger = Mock()
    monitor = SubprocessMonitor(
        copilot_pid=12345,
        item_logger=mock_logger,
    )

    monitor._emit_output("stdout", "test output")

    mock_logger.log_copilot_output.assert_called_once_with("test output")


def test_subprocess_monitor_find_children_wmic_success():
    """Test finding child processes via WMIC."""
    monitor = SubprocessMonitor(copilot_pid=12345)

    # Mock subprocess.run to return WMIC-like output
    mock_result = Mock()
    mock_result.returncode = 0
    mock_result.stdout = """Node,CommandLine,ProcessId
HOSTNAME,powershell.exe -Command "test",67890
HOSTNAME,pytest.exe --verbose,67891
"""

    with patch('pokepoke.utils.subprocess_monitor.subprocess.run', return_value=mock_result):
        children = monitor._find_child_processes()

    assert len(children) == 2
    assert (67890, "powershell.exe -Command \"test\"") in children
    assert (67891, "pytest.exe --verbose") in children


def test_subprocess_monitor_find_children_wmic_failure():
    """Test graceful handling when WMIC fails."""
    monitor = SubprocessMonitor(copilot_pid=12345)

    # Mock subprocess.run to simulate WMIC failure
    mock_result = Mock()
    mock_result.returncode = 1
    mock_result.stdout = ""

    with patch('pokepoke.utils.subprocess_monitor.subprocess.run', return_value=mock_result):
        children = monitor._find_child_processes()

    # Should return empty list without crashing
    assert children == []


def test_subprocess_monitor_find_children_wmic_timeout():
    """Test graceful handling when WMIC times out."""
    monitor = SubprocessMonitor(copilot_pid=12345)

    with patch('pokepoke.utils.subprocess_monitor.subprocess.run', side_effect=TimeoutError("Command timed out")):
        children = monitor._find_child_processes()

    # Should return empty list without crashing
    assert children == []


def test_create_monitor_for_client_with_valid_pid():
    """Test creating monitor for a client with extractable PID."""
    mock_client = Mock()
    mock_client._process = Mock()
    mock_client._process.pid = 12345

    monitor = create_monitor_for_client(mock_client)

    assert monitor is not None
    assert monitor._copilot_pid == 12345
    assert monitor._monitoring is True

    # Cleanup
    monitor.stop()


def test_create_monitor_for_client_without_pid():
    """Test creating monitor for a client without extractable PID."""
    mock_client = Mock()
    mock_client._process = None

    monitor = create_monitor_for_client(mock_client)

    # Should return None when PID can't be extracted
    assert monitor is None


def test_create_monitor_for_client_with_callbacks():
    """Test creating monitor with item logger and output callback."""
    mock_client = Mock()
    mock_client._process = Mock()
    mock_client._process.pid = 12345

    mock_logger = Mock()
    output_callback = Mock()

    monitor = create_monitor_for_client(
        mock_client,
        item_logger=mock_logger,
        on_output=output_callback,
    )

    assert monitor is not None
    assert monitor._item_logger is mock_logger
    assert monitor._on_output is output_callback

    # Test that callbacks work
    monitor._emit_output("stdout", "test")
    mock_logger.log_copilot_output.assert_called_once_with("test")
    output_callback.assert_called_once_with("stdout", "test")

    # Cleanup
    monitor.stop()


def test_subprocess_monitor_callback_exception_handling():
    """Test that exceptions in callbacks don't crash the monitor."""
    def bad_callback(source: str, text: str) -> None:
        raise RuntimeError("Callback error")

    monitor = SubprocessMonitor(
        copilot_pid=12345,
        on_output=bad_callback,
    )

    # Should not raise exception
    monitor._emit_output("stdout", "test")


def test_subprocess_monitor_detects_new_children():
    """Test that monitor detects new child processes as they appear."""
    monitor = SubprocessMonitor(copilot_pid=12345)

    # Initially no children
    assert len(monitor._monitored_pids) == 0

    # Mock finding a child process
    mock_result = Mock()
    mock_result.returncode = 0
    mock_result.stdout = """Node,CommandLine,ProcessId
HOSTNAME,powershell.exe -Command "test",67890
"""

    with patch('subprocess.run', return_value=mock_result):
        monitor._check_for_children()

    # Should have detected one child
    assert 67890 in monitor._monitored_pids

    # Check again with the same child - should not duplicate
    with patch('subprocess.run', return_value=mock_result):
        monitor._check_for_children()

    # Still only one child tracked
    assert len(monitor._monitored_pids) == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
