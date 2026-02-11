"""Tests for beads availability check at orchestrator startup (rn3k)."""

import subprocess
from unittest.mock import Mock, patch

import pytest

from pokepoke.orchestrator import _check_beads_available


class TestCheckBeadsAvailable:
    """Test _check_beads_available function."""

    @patch('shutil.which')
    def test_bd_not_installed(self, mock_which: Mock, capsys) -> None:
        """Test error when bd command is not found."""
        mock_which.return_value = None

        result = _check_beads_available()

        assert result is False
        captured = capsys.readouterr()
        assert "'bd' (beads) command not found" in captured.err

    @patch('subprocess.run')
    @patch('shutil.which')
    def test_bd_not_initialized(self, mock_which: Mock, mock_run: Mock, capsys) -> None:
        """Test error when beads is not initialized in the directory."""
        mock_which.return_value = '/usr/bin/bd'
        mock_run.return_value = Mock(returncode=1, stdout='', stderr='Not a beads repo')

        result = _check_beads_available()

        assert result is False
        captured = capsys.readouterr()
        assert "not a beads repository" in captured.err

    @patch('subprocess.run')
    @patch('shutil.which')
    def test_bd_info_timeout(self, mock_which: Mock, mock_run: Mock, capsys) -> None:
        """Test error when bd info command times out."""
        mock_which.return_value = '/usr/bin/bd'
        mock_run.side_effect = subprocess.TimeoutExpired(cmd='bd', timeout=10)

        result = _check_beads_available()

        assert result is False
        captured = capsys.readouterr()
        assert "timed out" in captured.err

    @patch('subprocess.run')
    @patch('shutil.which')
    def test_bd_info_exception(self, mock_which: Mock, mock_run: Mock, capsys) -> None:
        """Test error when bd info raises unexpected exception."""
        mock_which.return_value = '/usr/bin/bd'
        mock_run.side_effect = OSError("Something went wrong")

        result = _check_beads_available()

        assert result is False
        captured = capsys.readouterr()
        assert "Failed to check beads status" in captured.err

    @patch('subprocess.run')
    @patch('shutil.which')
    def test_bd_available_and_initialized(self, mock_which: Mock, mock_run: Mock) -> None:
        """Test success when bd is installed and initialized."""
        mock_which.return_value = '/usr/bin/bd'
        mock_run.return_value = Mock(returncode=0, stdout='{"version": "1.0"}')

        result = _check_beads_available()

        assert result is True
        mock_run.assert_called_once_with(
            ['bd', 'info', '--json'],
            capture_output=True, text=True, encoding='utf-8',
            timeout=10
        )
