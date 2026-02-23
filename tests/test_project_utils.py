"""Tests for project_utils validation helpers."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock

from pokepoke.project_utils import (
    is_git_repo,
    resolve_git_toplevel,
    has_pokepoke_config,
    check_beads_available,
)


class TestIsGitRepo:
    def test_returns_true_for_git_repo(self, tmp_path: Path) -> None:
        mock_result = MagicMock(returncode=0)
        with patch("pokepoke.project_utils.subprocess.run", return_value=mock_result):
            assert is_git_repo(tmp_path) is True

    def test_returns_false_for_non_git_dir(self, tmp_path: Path) -> None:
        mock_result = MagicMock(returncode=128)
        with patch("pokepoke.project_utils.subprocess.run", return_value=mock_result):
            assert is_git_repo(tmp_path) is False

    def test_returns_false_on_timeout(self, tmp_path: Path) -> None:
        with patch(
            "pokepoke.project_utils.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="git", timeout=10),
        ):
            assert is_git_repo(tmp_path) is False

    def test_returns_false_on_os_error(self, tmp_path: Path) -> None:
        with patch(
            "pokepoke.project_utils.subprocess.run",
            side_effect=OSError("git not found"),
        ):
            assert is_git_repo(tmp_path) is False


class TestResolveGitToplevel:
    def test_returns_resolved_path(self, tmp_path: Path) -> None:
        mock_result = MagicMock(returncode=0, stdout=str(tmp_path) + "\n")
        with patch("pokepoke.project_utils.subprocess.run", return_value=mock_result):
            result = resolve_git_toplevel(tmp_path / "subdir")
            assert result == tmp_path.resolve()

    def test_returns_none_on_failure(self, tmp_path: Path) -> None:
        mock_result = MagicMock(returncode=128, stdout="")
        with patch("pokepoke.project_utils.subprocess.run", return_value=mock_result):
            assert resolve_git_toplevel(tmp_path) is None

    def test_returns_none_on_empty_stdout(self, tmp_path: Path) -> None:
        mock_result = MagicMock(returncode=0, stdout="   ")
        with patch("pokepoke.project_utils.subprocess.run", return_value=mock_result):
            assert resolve_git_toplevel(tmp_path) is None

    def test_returns_none_on_timeout(self, tmp_path: Path) -> None:
        with patch(
            "pokepoke.project_utils.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="git", timeout=10),
        ):
            assert resolve_git_toplevel(tmp_path) is None

    def test_returns_none_on_os_error(self, tmp_path: Path) -> None:
        with patch(
            "pokepoke.project_utils.subprocess.run",
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
        mock_result = MagicMock(returncode=0)
        with patch("pokepoke.project_utils.subprocess.run", return_value=mock_result):
            assert check_beads_available(tmp_path) is True

    def test_returns_false_when_bd_fails(self, tmp_path: Path) -> None:
        mock_result = MagicMock(returncode=1)
        with patch("pokepoke.project_utils.subprocess.run", return_value=mock_result):
            assert check_beads_available(tmp_path) is False

    def test_returns_false_on_timeout(self, tmp_path: Path) -> None:
        with patch(
            "pokepoke.project_utils.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="bd", timeout=10),
        ):
            assert check_beads_available(tmp_path) is False

    def test_returns_false_on_os_error(self, tmp_path: Path) -> None:
        with patch(
            "pokepoke.project_utils.subprocess.run",
            side_effect=OSError("bd not found"),
        ):
            assert check_beads_available(tmp_path) is False
