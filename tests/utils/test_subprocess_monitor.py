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

    # Mock psutil to fall back to WMIC
    with (
        patch('pokepoke.utils.subprocess_monitor._HAS_PSUTIL', False),
        patch('pokepoke.utils.subprocess_monitor.subprocess.run', return_value=mock_result),
    ):
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

    with (
        patch('pokepoke.utils.subprocess_monitor._HAS_PSUTIL', False),
        patch('pokepoke.utils.subprocess_monitor.subprocess.run', return_value=mock_result),
    ):
        children = monitor._find_child_processes()

    # Should return empty list without crashing
    assert children == []


def test_subprocess_monitor_find_children_wmic_timeout():
    """Test graceful handling when WMIC times out."""
    monitor = SubprocessMonitor(copilot_pid=12345)

    with (
        patch('pokepoke.utils.subprocess_monitor._HAS_PSUTIL', False),
        patch('pokepoke.utils.subprocess_monitor.subprocess.run', side_effect=TimeoutError("Command timed out")),
    ):
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

    # Mock psutil to fall back to WMIC
    with (
        patch('pokepoke.utils.subprocess_monitor._HAS_PSUTIL', False),
        patch('subprocess.run', return_value=mock_result),
    ):
        monitor._check_for_children()

    # Should have detected one child
    assert 67890 in monitor._monitored_pids

    # Check again with the same child - should not duplicate
    with (
        patch('pokepoke.utils.subprocess_monitor._HAS_PSUTIL', False),
        patch('subprocess.run', return_value=mock_result),
    ):
        monitor._check_for_children()

    # Still only one child tracked
    assert len(monitor._monitored_pids) == 1


def test_subprocess_monitor_psutil_detection():
    """Test child process detection via psutil."""
    from unittest.mock import MagicMock

    monitor = SubprocessMonitor(copilot_pid=12345)

    # Create mock psutil process structure
    mock_child1 = MagicMock()
    mock_child1.pid = 67890
    mock_child1.cmdline.return_value = ['pytest', '--verbose']

    mock_child2 = MagicMock()
    mock_child2.pid = 67891
    mock_child2.cmdline.return_value = ['powershell.exe', '-Command', 'test']

    mock_parent = MagicMock()
    mock_parent.children.return_value = [mock_child1, mock_child2]

    with patch('psutil.Process', return_value=mock_parent):
        children = monitor._find_child_processes()

    assert len(children) == 2
    assert (67890, 'pytest --verbose') in children
    assert (67891, 'powershell.exe -Command test') in children


def test_subprocess_monitor_psutil_access_denied():
    """Test graceful handling when psutil access is denied."""
    import psutil

    monitor = SubprocessMonitor(copilot_pid=12345)

    with patch('psutil.Process', side_effect=psutil.AccessDenied(pid=12345)):
        children = monitor._find_child_processes()

    # Should return empty list, not raise exception
    assert children == []


def test_subprocess_monitor_cleanup_dead_processes():
    """Test cleanup of dead process monitoring threads."""

    monitor = SubprocessMonitor(copilot_pid=12345)

    # Add some fake process threads
    fake_thread1 = Mock()
    fake_thread1.is_alive.return_value = False
    monitor._process_threads[67890] = fake_thread1
    monitor._process_pipes[67890] = {}

    fake_thread2 = Mock()
    fake_thread2.is_alive.return_value = True
    monitor._process_threads[67891] = fake_thread2
    monitor._process_pipes[67891] = {}

    # Mock psutil to say first process is dead
    with patch('psutil.pid_exists', side_effect=lambda pid: pid != 67890):
        monitor._cleanup_dead_processes()

    # Dead process should be removed
    assert 67890 not in monitor._process_threads
    assert 67890 not in monitor._process_pipes

    # Alive process should remain
    assert 67891 in monitor._process_threads
    assert 67891 in monitor._process_pipes


def test_subprocess_monitor_format_status():
    """Test formatting of process status messages."""
    monitor = SubprocessMonitor(copilot_pid=12345)

    status_msg = monitor._format_process_status(
        pid=67890,
        command="C:\\path\\to\\pytest.exe --verbose",
        status="running",
        cpu_percent=15.5,
        count=3,
    )

    assert "67890" in status_msg
    assert "pytest.exe" in status_msg
    assert "running" in status_msg
    assert "15.5" in status_msg
    assert "#3" in status_msg


def test_subprocess_monitor_start_process_monitor_no_psutil():
    """Test that process monitoring is skipped when psutil unavailable."""
    monitor = SubprocessMonitor(copilot_pid=12345)

    with patch('pokepoke.utils.subprocess_monitor._HAS_PSUTIL', False):
        # Should not raise exception, just log and return
        monitor._start_process_monitor(67890, "pytest --verbose")

    # No thread should be created
    assert 67890 not in monitor._process_threads


def test_subprocess_monitor_process_output_monitoring():
    """Test the process output monitoring loop."""

    monitor = SubprocessMonitor(copilot_pid=12345, poll_interval=0.05)

    # Create mock process
    mock_process = Mock()
    mock_process.is_running.side_effect = [True, True, True, False]  # Run 3 times then exit
    mock_process.status.return_value = "running"
    mock_process.cpu_percent.return_value = 5.0

    # Mock io_counters with increasing bytes to simulate I/O activity
    io_values = [1000, 2000, 3000, 3000]  # Bytes increase, then stay same
    io_index = [0]

    def mock_io_counters():
        mock_io = Mock()
        mock_io.write_bytes = io_values[io_index[0]]
        io_index[0] = min(io_index[0] + 1, len(io_values) - 1)
        return mock_io

    mock_process.io_counters = mock_io_counters

    output_captured = []

    def capture_output(source: str, text: str) -> None:
        output_captured.append((source, text))

    monitor._on_output = capture_output
    monitor._monitoring = True

    # Patch time.monotonic to control timing
    start_time = [0.0]
    call_count = [0]

    def mock_monotonic():
        call_count[0] += 1
        # First calls: fast forward to trigger I/O messages
        if call_count[0] <= 10:
            start_time[0] += 1.5  # Fast forward to trigger I/O checks
        else:
            start_time[0] += 11.0  # Fast forward to trigger status update
        return start_time[0]

    # Run monitoring with mocked process
    with (
        patch('psutil.Process', return_value=mock_process),
        patch('time.monotonic', side_effect=mock_monotonic),
    ):
        monitor._monitor_process_output(67890, "pytest --verbose")

    # Should have captured multiple types of output
    assert len(output_captured) >= 3, f"Expected at least 3 outputs, got {len(output_captured)}"

    # Check for start message
    start_messages = [msg for src, msg in output_captured if "Started monitoring" in msg]
    assert len(start_messages) >= 1, "Should emit start monitoring message"

    # Check for I/O activity messages
    io_messages = [msg for src, msg in output_captured if "active - wrote" in msg]
    assert len(io_messages) >= 1, "Should emit I/O activity messages"

    # Check for completion message
    completion_messages = [msg for src, msg in output_captured if "completed" in msg]
    assert len(completion_messages) >= 1, "Should emit completion message"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
