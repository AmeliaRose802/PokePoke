"""Tests for beads availability check at orchestrator startup (rn3k)."""

import subprocess
from pathlib import Path
from unittest.mock import Mock, patch


from pokepoke.repo_check import check_beads_available, initialize_beads_repo


class TestCheckBeadsAvailable:
    """Test check_beads_available function."""

    @patch('pokepoke.repo_check.shutil.which')
    def test_bd_not_installed(self, mock_which: Mock, capsys) -> None:
        """Test error when bd command is not found."""
        mock_which.return_value = None

        result = check_beads_available()

        assert result is False
        captured = capsys.readouterr()
        assert "'bd' (beads) command not found" in captured.err

    @patch('subprocess.run')
    @patch('pokepoke.repo_check.shutil.which')
    def test_bd_not_initialized(self, mock_which: Mock, mock_run: Mock, capsys) -> None:
        """Test error when beads is not initialized in the directory."""
        mock_which.return_value = '/usr/bin/bd'
        mock_run.return_value = Mock(returncode=1, stdout='', stderr='Not a beads repo')

        result = check_beads_available()

        assert result is False
        captured = capsys.readouterr()
        assert "not a beads repository" in captured.err

    @patch('subprocess.run')
    @patch('pokepoke.repo_check.shutil.which')
    def test_bd_info_timeout(self, mock_which: Mock, mock_run: Mock, capsys) -> None:
        """Test error when bd info command times out."""
        mock_which.return_value = '/usr/bin/bd'
        mock_run.side_effect = subprocess.TimeoutExpired(cmd='bd', timeout=30)

        result = check_beads_available()

        assert result is False
        captured = capsys.readouterr()
        assert "timed out" in captured.err

    @patch('subprocess.run')
    @patch('pokepoke.repo_check.shutil.which')
    def test_bd_info_exception(self, mock_which: Mock, mock_run: Mock, capsys) -> None:
        """Test error when bd info raises unexpected exception."""
        mock_which.return_value = '/usr/bin/bd'
        mock_run.side_effect = OSError("Something went wrong")

        result = check_beads_available()

        assert result is False
        captured = capsys.readouterr()
        assert "Failed to check beads status" in captured.err

    @patch('subprocess.run')
    @patch('pokepoke.repo_check.shutil.which')
    def test_bd_available_and_initialized(self, mock_which: Mock, mock_run: Mock) -> None:
        """Test success when bd is installed and initialized."""
        mock_which.return_value = '/usr/bin/bd'
        mock_run.return_value = Mock(returncode=0, stdout='{"version": "1.0"}')

        result = check_beads_available()

        assert result is True
        mock_run.assert_called_once_with(
            ['bd', 'info', '--json'],
            capture_output=True, text=True, encoding='utf-8',
            timeout=30
        )


class TestInitializeBeadsRepo:
    """Test initialize_beads_repo helper."""

    @patch('subprocess.run')
    @patch('pokepoke.repo_check.shutil.which')
    def test_already_initialized(self, mock_which: Mock, mock_run: Mock) -> None:
        """If bd info succeeds, init should be a no-op and return True."""
        repo_path = Path('C:\\repo')
        mock_which.return_value = 'C:\\Python\\Scripts\\bd.exe'
        mock_run.return_value = Mock(returncode=0, stdout='{}', stderr='')

        result = initialize_beads_repo(repo_path)

        assert result is True
        mock_run.assert_called_once()
        assert mock_run.call_args.kwargs.get('cwd') == str(repo_path)

    @patch('subprocess.run')
    @patch('pokepoke.repo_check.shutil.which')
    def test_runs_init_and_verifies(self, mock_which: Mock, mock_run: Mock) -> None:
        """If not initialized, runs bd init and then verifies with bd info."""
        repo_path = Path('C:\\repo')
        mock_which.return_value = 'C:\\Python\\Scripts\\bd.exe'
        mock_run.side_effect = [
            Mock(returncode=1, stdout='', stderr='Not a beads repo'),
            Mock(returncode=0, stdout='', stderr=''),
            Mock(returncode=0, stdout='{}', stderr=''),
        ]

        result = initialize_beads_repo(repo_path)

        assert result is True
        assert mock_run.call_count == 3
        assert mock_run.call_args_list[1].args[0] == ['bd', 'init', '--quiet']
        assert mock_run.call_args_list[1].kwargs.get('cwd') == str(repo_path)

    @patch('subprocess.run')
    @patch('pokepoke.repo_check.shutil.which')
    def test_init_failure_returns_false(self, mock_which: Mock, mock_run: Mock) -> None:
        """If bd init fails, returns False."""
        repo_path = Path('C:\\repo')
        mock_which.return_value = 'C:\\Python\\Scripts\\bd.exe'
        mock_run.side_effect = [
            Mock(returncode=1, stdout='', stderr='Not a beads repo'),
            Mock(returncode=1, stdout='', stderr='init failed'),
        ]

        result = initialize_beads_repo(repo_path)

        assert result is False
        assert mock_run.call_count == 2

    @patch('pokepoke.repo_check.shutil.which')
    def test_bd_not_installed_returns_false(self, mock_which: Mock, capsys) -> None:
        """Test error when bd command is not found."""
        repo_path = Path('C:\\repo')
        mock_which.return_value = None

        result = initialize_beads_repo(repo_path)

        assert result is False
        captured = capsys.readouterr()
        assert "command not found" in captured.err

    @patch('subprocess.run')
    @patch('pokepoke.repo_check.shutil.which')
    def test_bd_info_timeout_returns_false(self, mock_which: Mock, mock_run: Mock, capsys) -> None:
        """Test error when bd info times out during initialization check."""
        repo_path = Path('C:\\repo')
        mock_which.return_value = 'C:\\Python\\Scripts\\bd.exe'
        mock_run.side_effect = subprocess.TimeoutExpired(cmd='bd', timeout=30)

        result = initialize_beads_repo(repo_path)

        assert result is False
        captured = capsys.readouterr()
        assert "timed out" in captured.err

    @patch('subprocess.run')
    @patch('pokepoke.repo_check.shutil.which')
    def test_verify_failure_returns_false(self, mock_which: Mock, mock_run: Mock) -> None:
        """If verification fails after init, returns False."""
        repo_path = Path('C:\\repo')
        mock_which.return_value = 'C:\\Python\\Scripts\\bd.exe'
        mock_run.side_effect = [
            Mock(returncode=1, stdout='', stderr='Not a beads repo'),
            Mock(returncode=0, stdout='', stderr=''),
            Mock(returncode=1, stdout='', stderr='still failing'),
        ]

        result = initialize_beads_repo(repo_path)

        assert result is False
        assert mock_run.call_count == 3
