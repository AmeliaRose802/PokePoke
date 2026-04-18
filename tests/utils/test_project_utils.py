"""Tests for project_utils validation helpers."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

from pokepoke.utils.project_utils import (
    check_beads_available,
    ensure_project_ready,
    has_pokepoke_config,
    is_git_repo,
    resolve_git_toplevel,
)


class TestIsGitRepo:
    def test_returns_true_for_git_repo(self, tmp_path: Path) -> None:
        mock_result = MagicMock(returncode=0)
        with patch("pokepoke.utils.project_utils.subprocess.run", return_value=mock_result):
            assert is_git_repo(tmp_path) is True

    def test_returns_false_for_non_git_dir(self, tmp_path: Path) -> None:
        mock_result = MagicMock(returncode=128)
        with patch("pokepoke.utils.project_utils.subprocess.run", return_value=mock_result):
            assert is_git_repo(tmp_path) is False

    def test_returns_false_on_timeout(self, tmp_path: Path) -> None:
        with patch(
            "pokepoke.utils.project_utils.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="git", timeout=10),
        ):
            assert is_git_repo(tmp_path) is False

    def test_returns_false_on_os_error(self, tmp_path: Path) -> None:
        with patch(
            "pokepoke.utils.project_utils.subprocess.run",
            side_effect=OSError("git not found"),
        ):
            assert is_git_repo(tmp_path) is False


class TestResolveGitToplevel:
    def test_returns_resolved_path(self, tmp_path: Path) -> None:
        mock_result = MagicMock(returncode=0, stdout=str(tmp_path) + "\n")
        with patch("pokepoke.utils.project_utils.subprocess.run", return_value=mock_result):
            result = resolve_git_toplevel(tmp_path / "subdir")
            assert result == tmp_path.resolve()

    def test_returns_none_on_failure(self, tmp_path: Path) -> None:
        mock_result = MagicMock(returncode=128, stdout="")
        with patch("pokepoke.utils.project_utils.subprocess.run", return_value=mock_result):
            assert resolve_git_toplevel(tmp_path) is None

    def test_returns_none_on_empty_stdout(self, tmp_path: Path) -> None:
        mock_result = MagicMock(returncode=0, stdout="   ")
        with patch("pokepoke.utils.project_utils.subprocess.run", return_value=mock_result):
            assert resolve_git_toplevel(tmp_path) is None

    def test_returns_none_on_timeout(self, tmp_path: Path) -> None:
        with patch(
            "pokepoke.utils.project_utils.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="git", timeout=10),
        ):
            assert resolve_git_toplevel(tmp_path) is None

    def test_returns_none_on_os_error(self, tmp_path: Path) -> None:
        with patch(
            "pokepoke.utils.project_utils.subprocess.run",
            side_effect=OSError("git not found"),
        ):
            assert resolve_git_toplevel(tmp_path) is None


class TestHasPokpokeConfig:
    def test_returns_false_when_no_pokepoke_dir(self, tmp_path: Path) -> None:
        assert has_pokepoke_config(tmp_path) is False

    def test_returns_false_when_dir_empty(self, tmp_path: Path) -> None:
        (tmp_path / ".pokepoke").mkdir()
        assert has_pokepoke_config(tmp_path) is False

    def test_returns_true_for_config_yaml(self, tmp_path: Path) -> None:
        (tmp_path / ".pokepoke").mkdir()
        (tmp_path / ".pokepoke" / "config.yaml").write_text("project_name: x\n")
        assert has_pokepoke_config(tmp_path) is True

    def test_returns_true_for_config_yml(self, tmp_path: Path) -> None:
        (tmp_path / ".pokepoke").mkdir()
        (tmp_path / ".pokepoke" / "config.yml").write_text("project_name: x\n")
        assert has_pokepoke_config(tmp_path) is True

    def test_returns_true_for_config_json(self, tmp_path: Path) -> None:
        (tmp_path / ".pokepoke").mkdir()
        (tmp_path / ".pokepoke" / "config.json").write_text("{}")
        assert has_pokepoke_config(tmp_path) is True


class TestCheckBeadsAvailable:
    def test_returns_true_when_bd_succeeds(self, tmp_path: Path) -> None:
        beads_dir = tmp_path / ".beads"
        beads_dir.mkdir()
        (beads_dir / "config.yaml").write_text("test: true")
        assert check_beads_available(tmp_path) is True

    def test_returns_false_when_bd_fails(self, tmp_path: Path) -> None:
        assert check_beads_available(tmp_path) is False

    def test_returns_false_on_timeout(self, tmp_path: Path) -> None:
        (tmp_path / ".beads").mkdir()
        assert check_beads_available(tmp_path) is False

    def test_returns_false_on_os_error(self, tmp_path: Path) -> None:
        beads_dir = tmp_path / ".beads"
        beads_dir.mkdir()
        (beads_dir / "random.txt").write_text("not a marker")
        assert check_beads_available(tmp_path) is False


class TestEnsureProjectReady:
    """Test ensure_project_ready function."""

    @patch("pokepoke.utils.project_utils.check_beads_available", return_value=True)
    @patch("pokepoke.utils.project_utils.has_pokepoke_config", return_value=True)
    @patch("pokepoke.utils.project_utils.is_git_repo", return_value=True)
    @patch("pokepoke.utils.project_utils.resolve_git_toplevel")
    @patch("pokepoke.git.repo_check.check_beads_available", return_value=True)
    def test_returns_true_when_all_checks_pass(
        self, mock_beads_cli, mock_toplevel, mock_git, mock_config, mock_beads
    ) -> None:
        mock_toplevel.return_value = Path.cwd()
        assert ensure_project_ready(interactive=False) is True

    @patch("pokepoke.utils.project_utils.check_beads_available", return_value=False)
    @patch("pokepoke.utils.project_utils.has_pokepoke_config", return_value=False)
    @patch("pokepoke.utils.project_utils.is_git_repo", return_value=False)
    @patch("pokepoke.utils.project_utils.resolve_git_toplevel", return_value=None)
    @patch("pokepoke.git.repo_check.check_beads_available", return_value=False)
    def test_desktop_ui_no_wait_fn(
        self, mock_beads_cli, mock_toplevel, mock_git, mock_config, mock_beads
    ) -> None:
        desktop_ui = MagicMock(spec=[])  # no wait_for_setup_complete attr
        assert ensure_project_ready(interactive=False, desktop_ui=desktop_ui) is False

    @patch("pokepoke.utils.project_utils.check_beads_available", return_value=False)
    @patch("pokepoke.utils.project_utils.has_pokepoke_config", return_value=False)
    @patch("pokepoke.utils.project_utils.is_git_repo", return_value=False)
    @patch("pokepoke.utils.project_utils.resolve_git_toplevel", return_value=None)
    @patch("pokepoke.git.repo_check.check_beads_available", return_value=False)
    def test_desktop_ui_setup_fails(
        self, mock_beads_cli, mock_toplevel, mock_git, mock_config, mock_beads
    ) -> None:
        desktop_ui = MagicMock()
        desktop_ui.wait_for_setup_complete.return_value = False
        assert ensure_project_ready(interactive=False, desktop_ui=desktop_ui) is False

    @patch("pokepoke.utils.project_utils.check_beads_available", return_value=False)
    @patch("pokepoke.utils.project_utils.has_pokepoke_config", return_value=False)
    @patch("pokepoke.utils.project_utils.is_git_repo", return_value=False)
    @patch("pokepoke.utils.project_utils.resolve_git_toplevel", return_value=None)
    @patch("pokepoke.git.repo_check.check_beads_available", return_value=False)
    def test_cli_non_interactive_returns_false(
        self, mock_beads_cli, mock_toplevel, mock_git, mock_config, mock_beads
    ) -> None:
        assert ensure_project_ready(interactive=False) is False

    @patch("pokepoke.utils.project_utils.check_beads_available", return_value=False)
    @patch("pokepoke.utils.project_utils.has_pokepoke_config", return_value=True)
    @patch("pokepoke.utils.project_utils.is_git_repo", return_value=True)
    @patch("pokepoke.utils.project_utils.resolve_git_toplevel")
    @patch("pokepoke.git.repo_check.check_beads_available", return_value=False)
    @patch("builtins.input", return_value="n")
    def test_cli_interactive_user_declines(  # noqa: PLR0913
        self, mock_input, mock_beads_cli, mock_toplevel, mock_git, mock_config, mock_beads
    ) -> None:
        mock_toplevel.return_value = Path.cwd()
        assert ensure_project_ready(interactive=True) is False

    @patch("pokepoke.utils.project_utils.check_beads_available", return_value=False)
    @patch("pokepoke.utils.project_utils.has_pokepoke_config", return_value=True)
    @patch("pokepoke.utils.project_utils.is_git_repo", return_value=True)
    @patch("pokepoke.utils.project_utils.resolve_git_toplevel")
    @patch("pokepoke.git.repo_check.check_beads_available")
    @patch("pokepoke.git.repo_check.initialize_beads_repo", return_value=True)
    @patch("builtins.input", return_value="y")
    def test_cli_interactive_user_accepts(  # noqa: PLR0913
        self, mock_input, mock_init, mock_beads_cli, mock_toplevel,
        mock_git, mock_config, mock_beads
    ) -> None:
        mock_toplevel.return_value = Path.cwd()
        mock_beads_cli.side_effect = [False, True]
        assert ensure_project_ready(interactive=True) is True
