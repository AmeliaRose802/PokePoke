"""Tests for process_utils module."""
from unittest.mock import patch, MagicMock
import subprocess

from pokepoke.process_utils import check_copilot_processes, wait_for_process_cleanup


class TestCheckCopilotProcesses:
    """Tests for check_copilot_processes."""

    @patch('pokepoke.process_utils.os')
    def test_returns_zero_on_non_windows(self, mock_os):
        mock_os.name = 'posix'
        assert check_copilot_processes() == 0

    @patch('pokepoke.process_utils.os')
    @patch('pokepoke.process_utils.subprocess.run')
    def test_returns_process_count_on_windows(self, mock_run, mock_os):
        mock_os.name = 'nt'
        mock_run.return_value = MagicMock(
            stdout='"Image Name","PID"\n"copilot.exe","1234"\n"copilot.exe","5678"'
        )
        assert check_copilot_processes() == 2

    @patch('pokepoke.process_utils.os')
    @patch('pokepoke.process_utils.subprocess.run')
    def test_returns_zero_when_no_processes(self, mock_run, mock_os):
        mock_os.name = 'nt'
        mock_run.return_value = MagicMock(stdout='INFO: No tasks')
        assert check_copilot_processes() == 0

    @patch('pokepoke.process_utils.os')
    @patch('pokepoke.process_utils.subprocess.run')
    def test_returns_zero_on_exception(self, mock_run, mock_os):
        mock_os.name = 'nt'
        mock_run.side_effect = subprocess.TimeoutExpired(cmd='tasklist', timeout=5)
        assert check_copilot_processes() == 0


class TestWaitForProcessCleanup:
    """Tests for wait_for_process_cleanup."""

    @patch('pokepoke.process_utils.os')
    def test_returns_immediately_on_non_windows(self, mock_os):
        mock_os.name = 'posix'
        wait_for_process_cleanup(max_wait=0.1)

    @patch('pokepoke.process_utils.check_copilot_processes')
    @patch('pokepoke.process_utils.os')
    def test_returns_when_no_processes(self, mock_os, mock_check):
        mock_os.name = 'nt'
        mock_check.return_value = 0
        wait_for_process_cleanup(max_wait=0.1)
        mock_check.assert_called_once()

    @patch('pokepoke.process_utils.check_copilot_processes')
    @patch('pokepoke.process_utils.os')
    def test_waits_for_processes_to_terminate(self, mock_os, mock_check):
        mock_os.name = 'nt'
        mock_check.side_effect = [1, 1, 0]
        wait_for_process_cleanup(max_wait=1.0)
        assert mock_check.call_count == 3
