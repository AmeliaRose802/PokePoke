"""Tests for DesktopAPI project management functionality.

This module tests project lifecycle operations including:
- Opening projects and validation
- Project browsing and directory resolution
- Project state management
- Agent registry clearing on project changes
"""

from unittest.mock import Mock

import pytest

from pokepoke.desktop.desktop_api import DesktopAPI


@pytest.fixture(autouse=True)
def _isolate_desktop_api(monkeypatch):
    """Prevent DesktopAPI from loading real historical agents or calling git."""
    monkeypatch.setattr("pokepoke.desktop.desktop_api.get_repository_name", lambda: "test-repo")


def test_open_project_nonexistent_directory() -> None:
    api = DesktopAPI()
    result = api.open_project("/nonexistent/path/xyz")
    assert result["success"] is False
    assert "does not exist" in result["error"]


def test_open_project_not_a_git_repo(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        "pokepoke.desktop.desktop_api_ext._is_git_repo", lambda p: False
    )
    result = DesktopAPI().open_project(str(tmp_path))
    assert result["success"] is False
    assert "Not a git repository" in result["error"]


def test_open_project_success_with_pokepoke_config(tmp_path, monkeypatch) -> None:
    # Set up a fake project dir with .pokepoke/ and actual config file
    (tmp_path / ".pokepoke").mkdir()
    (tmp_path / ".pokepoke" / "config.yaml").write_text(
        "project_name: test-proj\n", encoding="utf-8"
    )
    (tmp_path / ".git").mkdir()  # So _find_repo_root resolves to tmp_path

    monkeypatch.setattr(
        "pokepoke.desktop.desktop_api_ext._is_git_repo", lambda p: True
    )
    monkeypatch.setattr(
        "pokepoke.desktop.desktop_api_ext._resolve_git_toplevel", lambda p: p
    )
    monkeypatch.setattr(
        "pokepoke.desktop.desktop_api_ext._check_beads_available", lambda p: True
    )
    monkeypatch.setattr(
        "pokepoke.git.repo_utils.get_repository_name", lambda: "test-repo"
    )

    api = DesktopAPI()
    result = api.open_project(str(tmp_path))

    assert result["success"] is True
    assert result["needs_init"] is False
    assert result["needs_beads_init"] is False
    assert result["project_name"] == "test-proj"
    # Session state should be reset
    state = api.get_state()
    assert state["work_item"] is None
    assert state["agent_name"] == ""
    assert state["repository_name"] == "test-repo"


def test_open_project_needs_init_when_no_pokepoke_dir(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        "pokepoke.desktop.desktop_api_ext._is_git_repo", lambda p: True
    )
    monkeypatch.setattr(
        "pokepoke.desktop.desktop_api_ext._resolve_git_toplevel", lambda p: p
    )
    monkeypatch.setattr(
        "pokepoke.desktop.desktop_api_ext._check_beads_available", lambda p: False
    )
    monkeypatch.setattr(
        "pokepoke.git.repo_utils.get_repository_name", lambda: "bare-repo"
    )

    result = DesktopAPI().open_project(str(tmp_path))
    assert result["success"] is True
    assert result["needs_init"] is True
    assert result["needs_beads_init"] is True


def test_browse_for_project_no_window() -> None:
    api = DesktopAPI()
    # _window is None by default
    result = api.browse_for_project()
    assert result["success"] is False
    assert "No window" in result["error"]


def test_browse_for_project_cancelled() -> None:
    api = DesktopAPI()
    mock_window = Mock()
    mock_window.create_file_dialog.return_value = None
    api.set_window(mock_window)

    result = api.browse_for_project()
    assert result["success"] is False
    assert result.get("cancelled") is True


def test_browse_for_project_delegates_to_open_project(tmp_path, monkeypatch) -> None:
    (tmp_path / ".pokepoke").mkdir()
    (tmp_path / ".pokepoke" / "config.yaml").write_text(
        "project_name: picked\n", encoding="utf-8"
    )
    (tmp_path / ".git").mkdir()  # So _find_repo_root resolves to tmp_path

    monkeypatch.setattr(
        "pokepoke.desktop.desktop_api_ext._is_git_repo", lambda p: True
    )
    monkeypatch.setattr(
        "pokepoke.desktop.desktop_api_ext._resolve_git_toplevel", lambda p: p
    )
    monkeypatch.setattr(
        "pokepoke.desktop.desktop_api_ext._check_beads_available", lambda p: True
    )
    monkeypatch.setattr(
        "pokepoke.git.repo_utils.get_repository_name", lambda: "picked-repo"
    )

    api = DesktopAPI()
    mock_window = Mock()
    mock_window.create_file_dialog.return_value = (str(tmp_path),)
    api.set_window(mock_window)

    result = api.browse_for_project()
    assert result["success"] is True
    assert result["project_name"] == "picked"


def test_open_project_resolves_subdirectory_to_git_toplevel(tmp_path, monkeypatch) -> None:
    """When user picks a subdirectory, open_project resolves to the git repo root."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    subdir = repo_root / "src" / "app"
    subdir.mkdir(parents=True)
    (repo_root / ".pokepoke").mkdir()
    (repo_root / ".pokepoke" / "config.yaml").write_text(
        "project_name: resolved-proj\n", encoding="utf-8"
    )
    (repo_root / ".git").mkdir()  # So _find_repo_root resolves to repo_root

    monkeypatch.setattr(
        "pokepoke.desktop.desktop_api_ext._is_git_repo", lambda p: True
    )
    monkeypatch.setattr(
        "pokepoke.desktop.desktop_api_ext._resolve_git_toplevel", lambda p: repo_root
    )
    monkeypatch.setattr(
        "pokepoke.desktop.desktop_api_ext._check_beads_available", lambda p: True
    )
    monkeypatch.setattr(
        "pokepoke.git.repo_utils.get_repository_name", lambda: "resolved-repo"
    )

    result = DesktopAPI().open_project(str(subdir))
    assert result["success"] is True
    assert result["path"] == str(repo_root)
    assert result["needs_init"] is False
    assert result["project_name"] == "resolved-proj"


def test_open_project_needs_init_with_empty_pokepoke_dir(tmp_path, monkeypatch) -> None:
    """A .pokepoke/ dir with no config file still reports needs_init=True."""
    (tmp_path / ".pokepoke").mkdir()
    # No config.yaml/yml/json inside

    monkeypatch.setattr(
        "pokepoke.desktop.desktop_api_ext._is_git_repo", lambda p: True
    )
    monkeypatch.setattr(
        "pokepoke.desktop.desktop_api_ext._resolve_git_toplevel", lambda p: p
    )
    monkeypatch.setattr(
        "pokepoke.desktop.desktop_api_ext._check_beads_available", lambda p: True
    )
    monkeypatch.setattr(
        "pokepoke.git.repo_utils.get_repository_name", lambda: "empty-config"
    )

    result = DesktopAPI().open_project(str(tmp_path))
    assert result["success"] is True
    assert result["needs_init"] is True


def test_open_project_clears_agent_registry(tmp_path, monkeypatch) -> None:
    """Opening a new project clears previously tracked agents."""
    monkeypatch.setattr(
        "pokepoke.desktop.desktop_api_ext._is_git_repo", lambda p: True
    )
    monkeypatch.setattr(
        "pokepoke.desktop.desktop_api_ext._resolve_git_toplevel", lambda p: p
    )
    monkeypatch.setattr(
        "pokepoke.desktop.desktop_api_ext._check_beads_available", lambda p: True
    )
    monkeypatch.setattr(
        "pokepoke.git.repo_utils.get_repository_name", lambda: "fresh-repo"
    )

    api = DesktopAPI()
    api.push_agent_status("agent-1", "Worker", 1, "running")
    assert len(api.get_agents()) == 1

    api.open_project(str(tmp_path))
    assert len(api.get_agents()) == 0


def test_open_project_cancels_stop_after_current(tmp_path, monkeypatch) -> None:
    """Opening a new project cancels any pending stop-after-current request."""
    from pokepoke.utils.shutdown import (
        request_stop_after_current,
        should_stop_after_current,
    )
    from pokepoke.utils.shutdown import (
        reset as reset_shutdown,
    )

    monkeypatch.setattr(
        "pokepoke.desktop.desktop_api_ext._is_git_repo", lambda p: True
    )
    monkeypatch.setattr(
        "pokepoke.desktop.desktop_api_ext._resolve_git_toplevel", lambda p: p
    )
    monkeypatch.setattr(
        "pokepoke.desktop.desktop_api_ext._check_beads_available", lambda p: True
    )
    monkeypatch.setattr(
        "pokepoke.git.repo_utils.get_repository_name", lambda: "fresh-repo"
    )

    try:
        request_stop_after_current()
        assert should_stop_after_current() is True

        DesktopAPI().open_project(str(tmp_path))
        assert should_stop_after_current() is False
    finally:
        reset_shutdown()


def test_open_project_needs_beads_init_when_bd_unavailable(tmp_path, monkeypatch) -> None:
    """When beads is not available, needs_beads_init should be True."""
    (tmp_path / ".pokepoke").mkdir()
    (tmp_path / ".pokepoke" / "config.yaml").write_text(
        "project_name: no-beads\n", encoding="utf-8"
    )

    monkeypatch.setattr(
        "pokepoke.desktop.desktop_api_ext._is_git_repo", lambda p: True
    )
    monkeypatch.setattr(
        "pokepoke.desktop.desktop_api_ext._resolve_git_toplevel", lambda p: p
    )
    monkeypatch.setattr(
        "pokepoke.desktop.desktop_api_ext._check_beads_available", lambda p: False
    )
    monkeypatch.setattr(
        "pokepoke.git.repo_utils.get_repository_name", lambda: "no-beads-repo"
    )

    result = DesktopAPI().open_project(str(tmp_path))
    assert result["success"] is True
    assert result["needs_beads_init"] is True


def test_open_project_fails_when_agents_active(tmp_path, monkeypatch) -> None:
    """open_project should fail when agents are actively running."""
    (tmp_path / ".pokepoke").mkdir()
    (tmp_path / ".pokepoke" / "config.yaml").write_text(
        "project_name: test\n", encoding="utf-8"
    )

    monkeypatch.setattr(
        "pokepoke.desktop.desktop_api_ext._is_git_repo", lambda p: True
    )
    monkeypatch.setattr(
        "pokepoke.desktop.desktop_api_ext._resolve_git_toplevel", lambda p: p
    )
    monkeypatch.setattr(
        "pokepoke.desktop.desktop_api_ext._has_pokepoke_config", lambda p: True
    )
    monkeypatch.setattr(
        "pokepoke.desktop.desktop_api_ext._check_beads_available", lambda p: True
    )
    # Mock has_active_agents in the shutdown module where it's defined
    monkeypatch.setattr(
        "pokepoke.utils.shutdown.has_active_agents", lambda: True
    )

    result = DesktopAPI().open_project(str(tmp_path))
    assert result["success"] is False
    assert "Cannot switch projects while agents are running" in result["error"]
