"""Tests for process_snapshot module."""
import subprocess
from unittest.mock import MagicMock, patch

from pokepoke.utils.process_snapshot import log_process_tree_snapshot


class TestLogProcessTreeSnapshot:
    """Tests for log_process_tree_snapshot function."""

    @patch('pokepoke.utils.process_snapshot.os')
    def test_returns_immediately_on_non_windows(self, mock_os: MagicMock) -> None:
        """Should return immediately on non-Windows platforms."""
        mock_os.name = 'posix'
        log_process_tree_snapshot('test_tool', 'args', 60.0)

    @patch('pokepoke.utils.process_snapshot.subprocess.run')
    @patch('pokepoke.utils.process_snapshot.os')
    def test_logs_debug_when_no_processes_found(
        self, mock_os: MagicMock, mock_run: MagicMock
    ) -> None:
        """Should log debug message when no copilot processes found."""
        mock_os.name = 'nt'
        mock_run.return_value = MagicMock(
            stdout='Node,KernelModeTime,ProcessId,UserModeTime,WorkingSetSize'
        )
        # Should not raise
        log_process_tree_snapshot('test_tool', 'args', 60.0)

    @patch('pokepoke.utils.process_snapshot.time')
    @patch('pokepoke.utils.process_snapshot.subprocess.run')
    @patch('pokepoke.utils.process_snapshot.os')
    def test_logs_debug_with_children(
        self, mock_os: MagicMock, mock_run: MagicMock, mock_time: MagicMock
    ) -> None:
        """Should log debug messages when processes have children."""
        mock_os.name = 'nt'
        mock_os.cpu_count.return_value = 4
        mock_time.strftime.return_value = '2026-01-01 00:00:00'
        wmic_csv = (
            'Node,KernelModeTime,ProcessId,UserModeTime,WorkingSetSize\n'
            'PC,1000000,1234,2000000,104857600'
        )
        child_output = 'Name=git.exe\nProcessId=5678\nCommandLine=git status'
        mock_run.side_effect = [
            MagicMock(stdout=wmic_csv),
            MagicMock(stdout=child_output),
        ]
        log_process_tree_snapshot('test_tool', 'args', 60.0)
        assert mock_run.call_count == 2

    @patch('pokepoke.utils.process_snapshot.time')
    @patch('pokepoke.utils.process_snapshot.subprocess.run')
    @patch('pokepoke.utils.process_snapshot.os')
    def test_logs_debug_without_children(
        self, mock_os: MagicMock, mock_run: MagicMock, mock_time: MagicMock
    ) -> None:
        """Should log debug messages when processes have no children."""
        mock_os.name = 'nt'
        mock_os.cpu_count.return_value = 4
        mock_time.strftime.return_value = '2026-01-01 00:00:00'
        wmic_csv = (
            'Node,KernelModeTime,ProcessId,UserModeTime,WorkingSetSize\n'
            'PC,1000000,1234,2000000,104857600'
        )
        mock_run.side_effect = [
            MagicMock(stdout=wmic_csv),
            MagicMock(stdout=''),
        ]
        log_process_tree_snapshot('test_tool', 'args', 60.0)
        assert mock_run.call_count == 2

    @patch('pokepoke.utils.process_snapshot.subprocess.run')
    @patch('pokepoke.utils.process_snapshot.os')
    def test_handles_exception(
        self, mock_os: MagicMock, mock_run: MagicMock
    ) -> None:
        """Should handle exceptions gracefully."""
        mock_os.name = 'nt'
        mock_run.side_effect = subprocess.TimeoutExpired(cmd='wmic', timeout=5)
        # Should not raise
        log_process_tree_snapshot('test_tool', 'args', 60.0)
