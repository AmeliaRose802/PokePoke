"""Tests for repo_utils module."""

import subprocess
from unittest.mock import Mock, patch

from pokepoke.git.repo_utils import get_repository_name, _get_repo_name_from_git, _get_repo_name_from_config


class TestGetRepositoryName:
    """Tests for get_repository_name function."""

    @patch('pokepoke.git.repo_utils._get_repo_name_from_git')
    def test_returns_git_name_when_available(self, mock_git):
        mock_git.return_value = "my-repo"

        result = get_repository_name()

        assert result == "my-repo"

    @patch('pokepoke.git.repo_utils._get_repo_name_from_git')
    @patch('pokepoke.git.repo_utils._get_repo_name_from_config')
    def test_returns_config_name_when_git_unavailable(self, mock_config, mock_git):
        mock_git.return_value = None
        mock_config.return_value = "config-repo"

        result = get_repository_name()

        assert result == "config-repo"

    @patch('pokepoke.git.repo_utils._get_repo_name_from_git')
    @patch('pokepoke.git.repo_utils._get_repo_name_from_config')
    @patch('pokepoke.git.repo_utils.Path')
    def test_returns_directory_name_when_git_and_config_unavailable(
        self, mock_path_class, mock_config, mock_git
    ):
        mock_git.return_value = None
        mock_config.return_value = None
        mock_path = Mock()
        mock_path.name = "fallback-dir"
        mock_path_class.cwd.return_value = mock_path

        result = get_repository_name()

        assert result == "fallback-dir"

    @patch('pokepoke.git.repo_utils._get_repo_name_from_git')
    @patch('pokepoke.git.repo_utils._get_repo_name_from_config')
    @patch('pokepoke.git.repo_utils.Path')
    def test_returns_unknown_when_all_sources_fail(
        self, mock_path_class, mock_config, mock_git
    ):
        mock_git.return_value = None
        mock_config.return_value = None
        mock_path_class.cwd.side_effect = Exception("Path error")

        result = get_repository_name()

        assert result == "Unknown"


class TestGetRepoNameFromGit:
    """Tests for _get_repo_name_from_git function."""

    @patch('pokepoke.git.repo_utils.subprocess.run')
    def test_extracts_repo_name_from_https_url(self, mock_run):
        mock_run.return_value = Mock(
            returncode=0,
            stdout="https://github.com/user/my-repo.git\n"
        )

        result = _get_repo_name_from_git()

        assert result == "my-repo"

    @patch('pokepoke.git.repo_utils.subprocess.run')
    def test_extracts_repo_name_from_ssh_url(self, mock_run):
        mock_run.return_value = Mock(
            returncode=0,
            stdout="git@github.com:user/my-repo.git\n"
        )

        result = _get_repo_name_from_git()

        assert result == "my-repo"

    @patch('pokepoke.git.repo_utils.subprocess.run')
    def test_extracts_repo_name_without_git_extension(self, mock_run):
        mock_run.return_value = Mock(
            returncode=0,
            stdout="https://github.com/user/my-repo\n"
        )

        result = _get_repo_name_from_git()

        assert result == "my-repo"

    @patch('pokepoke.git.repo_utils.subprocess.run')
    def test_returns_none_when_git_command_fails(self, mock_run):
        mock_run.return_value = Mock(returncode=1, stdout="")

        result = _get_repo_name_from_git()

        assert result is None

    @patch('pokepoke.git.repo_utils.subprocess.run')
    def test_returns_none_when_git_command_has_no_output(self, mock_run):
        mock_run.return_value = Mock(returncode=0, stdout="")

        result = _get_repo_name_from_git()

        assert result is None

    @patch('pokepoke.git.repo_utils.subprocess.run')
    def test_returns_none_when_url_pattern_doesnt_match(self, mock_run):
        mock_run.return_value = Mock(returncode=0, stdout="invalid-url")

        result = _get_repo_name_from_git()

        assert result is None

    @patch('pokepoke.git.repo_utils.subprocess.run')
    def test_returns_none_when_subprocess_raises_called_process_error(self, mock_run):
        mock_run.side_effect = subprocess.CalledProcessError(1, "git")

        result = _get_repo_name_from_git()

        assert result is None

    @patch('pokepoke.git.repo_utils.subprocess.run')
    def test_returns_none_when_subprocess_times_out(self, mock_run):
        mock_run.side_effect = subprocess.TimeoutExpired("git", 5)

        result = _get_repo_name_from_git()

        assert result is None

    @patch('pokepoke.git.repo_utils.subprocess.run')
    def test_returns_none_when_file_not_found(self, mock_run):
        mock_run.side_effect = FileNotFoundError("git not found")

        result = _get_repo_name_from_git()

        assert result is None


class TestGetRepoNameFromConfig:
    """Tests for _get_repo_name_from_config function."""

    @patch('pokepoke.config.get_config')
    def test_returns_project_name_when_available(self, mock_get_config):
        mock_config = Mock()
        mock_config.project_name = "config-project"
        mock_get_config.return_value = mock_config

        result = _get_repo_name_from_config()

        assert result == "config-project"

    @patch('pokepoke.config.get_config')
    def test_returns_none_when_project_name_empty(self, mock_get_config):
        mock_config = Mock()
        mock_config.project_name = ""
        mock_get_config.return_value = mock_config

        result = _get_repo_name_from_config()

        assert result is None

    @patch('builtins.__import__')
    def test_returns_none_when_config_import_fails(self, mock_import):
        def side_effect(name, *args, **kwargs):
            if name == 'pokepoke.config':
                raise ImportError("Module not found")
            return __import__(name, *args, **kwargs)
        mock_import.side_effect = side_effect

        result = _get_repo_name_from_config()

        assert result is None

    @patch('pokepoke.config.get_config')
    def test_returns_none_when_get_config_raises_exception(self, mock_get_config):
        mock_get_config.side_effect = Exception("Config error")

        result = _get_repo_name_from_config()

        assert result is None
