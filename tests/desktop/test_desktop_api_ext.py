"""Tests for desktop_api_ext mixin module — coverage-mapped companion."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest
import yaml

from pokepoke.desktop.desktop_api import DesktopAPI
from pokepoke.desktop.desktop_api_ext import (
    _build_label_error_result,
    _update_current_labels,
)
from pokepoke.desktop.desktop_api_utils import coerce_process_output as _coerce_process_output


@pytest.fixture(autouse=True)
def _isolate_desktop_api(monkeypatch):
    """Prevent DesktopAPI from loading real historical agents or calling git."""
    monkeypatch.setattr("pokepoke.desktop.desktop_api.get_repository_name", lambda: "test-repo")


# ── _coerce_process_output ───────────────────────────────────────────────


def test_coerce_process_output_none() -> None:
    assert _coerce_process_output(None) is None


def test_coerce_process_output_empty_string() -> None:
    assert _coerce_process_output("") is None


def test_coerce_process_output_whitespace() -> None:
    assert _coerce_process_output("  \n  ") is None


def test_coerce_process_output_strips() -> None:
    assert _coerce_process_output("  hello\n") == "hello"


# ── _build_label_error_result ────────────────────────────────────────────


def test_build_label_error_result_minimal() -> None:
    result = _build_label_error_result("item-1", "urgent", "something broke")
    assert result == {"item_id": "item-1", "label": "urgent", "success": False, "error": "something broke"}


def test_build_label_error_result_with_extras() -> None:
    result = _build_label_error_result("item-1", "urgent", "fail", stderr="details", returncode=2)
    assert result["stderr"] == "details"
    assert result["returncode"] == 2


# ── _update_current_labels ───────────────────────────────────────────────


def test_update_current_labels_add() -> None:
    api = DesktopAPI()
    api.push_work_item("item-1", "T", "open", ["a"])
    labels = _update_current_labels(api, "item-1", "b", "add")
    assert labels == ["a", "b"]


def test_update_current_labels_add_idempotent() -> None:
    api = DesktopAPI()
    api.push_work_item("item-1", "T", "open", ["a"])
    labels = _update_current_labels(api, "item-1", "a", "add")
    assert labels == ["a"]


def test_update_current_labels_remove() -> None:
    api = DesktopAPI()
    api.push_work_item("item-1", "T", "open", ["a", "b"])
    labels = _update_current_labels(api, "item-1", "a", "remove")
    assert labels == ["b"]


def test_update_current_labels_wrong_item() -> None:
    api = DesktopAPI()
    api.push_work_item("item-1", "T", "open", ["a"])
    assert _update_current_labels(api, "item-999", "a", "add") is None


def test_update_current_labels_no_current_item() -> None:
    api = DesktopAPI()
    assert _update_current_labels(api, "item-1", "a", "add") is None


def test_update_current_labels_unknown_action() -> None:
    api = DesktopAPI()
    api.push_work_item("item-1", "T", "open", [])
    with pytest.raises(ValueError, match="Unknown label action"):
        _update_current_labels(api, "item-1", "a", "toggle")


# ── get_config / save_config ─────────────────────────────────────────────


def test_get_config_reads_yaml(tmp_path) -> None:
    api = DesktopAPI()
    (tmp_path / ".pokepoke").mkdir()
    (tmp_path / ".pokepoke" / "config.yaml").write_text("project_name: X\n", encoding="utf-8")

    with patch("pokepoke.config._find_repo_root", return_value=tmp_path):
        result = api.get_config()

    assert result["exists"] is True
    assert result["config"]["project_name"] == "X"


def test_get_config_file_missing(tmp_path) -> None:
    api = DesktopAPI()
    with patch("pokepoke.config._find_repo_root", return_value=tmp_path):
        result = api.get_config()
    assert result["exists"] is False
    assert result["config"] == {}


def test_get_config_no_yaml(tmp_path, monkeypatch) -> None:
    api = DesktopAPI()
    (tmp_path / ".pokepoke").mkdir()
    (tmp_path / ".pokepoke" / "config.yaml").write_text("key: val\n", encoding="utf-8")
    monkeypatch.setattr("pokepoke.desktop.desktop_api_ext.HAS_YAML", False)
    with patch("pokepoke.config._find_repo_root", return_value=tmp_path), \
         pytest.raises(ImportError, match="PyYAML"):
        api.get_config()


def test_get_config_non_dict_yaml(tmp_path) -> None:
    """Non-dict YAML is treated as empty config; canonical defaults are applied."""
    api = DesktopAPI()
    (tmp_path / ".pokepoke").mkdir()
    (tmp_path / ".pokepoke" / "config.yaml").write_text("- item\n", encoding="utf-8")
    with patch("pokepoke.config._find_repo_root", return_value=tmp_path):
        result = api.get_config()
    assert result["exists"] is True
    # Validated through the canonical path — defaults are filled in
    assert result["config"]["project_name"] == ""
    assert "models" in result["config"]


def test_save_config_dict(tmp_path) -> None:
    api = DesktopAPI()
    with patch("pokepoke.config._find_repo_root", return_value=tmp_path):
        result = api.save_config({"project_name": "TestProj"})
    assert result["saved"] is True
    loaded = yaml.safe_load((tmp_path / ".pokepoke" / "config.yaml").read_text(encoding="utf-8"))
    assert loaded["project_name"] == "TestProj"


def test_save_config_yaml_string(tmp_path) -> None:
    api = DesktopAPI()
    with patch("pokepoke.config._find_repo_root", return_value=tmp_path):
        result = api.save_config("project_name: FromStr\n")
    assert result["saved"] is True
    loaded = yaml.safe_load((tmp_path / ".pokepoke" / "config.yaml").read_text(encoding="utf-8"))
    assert loaded["project_name"] == "FromStr"


def test_save_config_rejects_invalid_type() -> None:
    api = DesktopAPI()
    with patch("pokepoke.config._find_repo_root"), pytest.raises(ValueError, match="Config must be a dict or YAML string"):
        api.save_config(42)


def test_save_config_rejects_non_dict_yaml() -> None:
    api = DesktopAPI()
    with patch("pokepoke.config._find_repo_root"), pytest.raises(ValueError, match="Config YAML must parse to an object"):
        api.save_config("- item1\n- item2\n")


def test_save_config_no_yaml(monkeypatch) -> None:
    api = DesktopAPI()
    monkeypatch.setattr("pokepoke.desktop.desktop_api_ext.HAS_YAML", False)
    with patch("pokepoke.config._find_repo_root"), pytest.raises(ImportError, match="PyYAML"):
        api.save_config({"key": "val"})


def test_save_config_creates_custom_agent_prompt_file(tmp_path) -> None:
    """Test that save_config auto-creates prompt files for custom maintenance agents."""
    api = DesktopAPI()
    prompts_dir = tmp_path / ".pokepoke" / "prompts"
    prompts_dir.mkdir(parents=True)

    config_with_custom_agent = {
        "project_name": "TestProj",
        "maintenance": {
            "agents": [
                {
                    "name": "My Custom Agent",
                    "prompt_file": "my-custom-agent.md",
                    "frequency": 5,
                    "custom": True,
                    "description": "Does custom things",
                    "enabled": True,
                }
            ]
        }
    }

    with patch("pokepoke.config._find_repo_root", return_value=tmp_path):
        result = api.save_config(config_with_custom_agent)

    assert result["saved"] is True

    # Check that the prompt file was created
    prompt_file = prompts_dir / "my-custom-agent.md"
    assert prompt_file.exists()
    content = prompt_file.read_text(encoding="utf-8")
    assert "# My Custom Agent" in content
    assert "Does custom things" in content
    assert "{{item_id}}" in content


def test_save_config_does_not_overwrite_existing_prompt(tmp_path) -> None:
    """Test that save_config doesn't overwrite existing custom agent prompts."""
    api = DesktopAPI()
    prompts_dir = tmp_path / ".pokepoke" / "prompts"
    prompts_dir.mkdir(parents=True)

    # Pre-create a prompt file with custom content
    prompt_file = prompts_dir / "existing-agent.md"
    original_content = "# Original Content\nDo not modify this!"
    prompt_file.write_text(original_content, encoding="utf-8")

    config_with_existing_agent = {
        "project_name": "TestProj",
        "maintenance": {
            "agents": [
                {
                    "name": "Existing Agent",
                    "prompt_file": "existing-agent.md",
                    "frequency": 3,
                    "custom": True,
                    "enabled": True,
                }
            ]
        }
    }

    with patch("pokepoke.config._find_repo_root", return_value=tmp_path):
        result = api.save_config(config_with_existing_agent)

    assert result["saved"] is True

    # Verify the original content wasn't modified
    assert prompt_file.read_text(encoding="utf-8") == original_content


def test_save_config_skips_non_custom_agents(tmp_path) -> None:
    """Test that save_config only creates prompts for custom agents, not built-in ones."""
    api = DesktopAPI()
    prompts_dir = tmp_path / ".pokepoke" / "prompts"
    prompts_dir.mkdir(parents=True)

    config_with_builtin_agent = {
        "project_name": "TestProj",
        "maintenance": {
            "agents": [
                {
                    "name": "Tech Debt",
                    "prompt_file": "tech-debt.md",
                    "frequency": 5,
                    "custom": False,  # Not a custom agent
                    "enabled": True,
                }
            ]
        }
    }

    with patch("pokepoke.config._find_repo_root", return_value=tmp_path):
        result = api.save_config(config_with_builtin_agent)

    assert result["saved"] is True

    # Verify no prompt file was created in user directory (builtin uses its own dir)
    prompt_file = prompts_dir / "tech-debt.md"
    assert not prompt_file.exists()


def test_save_config_handles_prompt_file_without_extension(tmp_path) -> None:
    """Test that save_config handles prompt files specified without .md extension."""
    api = DesktopAPI()
    prompts_dir = tmp_path / ".pokepoke" / "prompts"
    prompts_dir.mkdir(parents=True)

    config = {
        "project_name": "TestProj",
        "maintenance": {
            "agents": [
                {
                    "name": "No Extension Agent",
                    "prompt_file": "no-extension",  # No .md
                    "frequency": 5,
                    "custom": True,
                    "enabled": True,
                }
            ]
        }
    }

    with patch("pokepoke.config._find_repo_root", return_value=tmp_path):
        result = api.save_config(config)

    assert result["saved"] is True

    # Check that the prompt file was created with .md extension
    prompt_file = prompts_dir / "no-extension.md"
    assert prompt_file.exists()


def test_save_config_handles_empty_maintenance_agents(tmp_path) -> None:
    """Test that save_config works when there are no maintenance agents."""
    api = DesktopAPI()

    config = {
        "project_name": "TestProj",
        "maintenance": {
            "agents": []
        }
    }

    with patch("pokepoke.config._find_repo_root", return_value=tmp_path):
        result = api.save_config(config)

    assert result["saved"] is True


# ── Prompt delegation ────────────────────────────────────────────────────


def test_list_prompts_delegates() -> None:
    api = DesktopAPI()
    mock_svc = MagicMock()
    mock_svc.list_prompts.return_value = [{"name": "a"}]
    with patch("pokepoke.prompts.prompts.get_prompt_service", return_value=mock_svc):
        assert api.list_prompts() == [{"name": "a"}]


def test_get_prompt_delegates() -> None:
    api = DesktopAPI()
    mock_svc = MagicMock()
    mock_svc.get_prompt_metadata.return_value = {"name": "x", "content": "c"}
    with patch("pokepoke.prompts.prompts.get_prompt_service", return_value=mock_svc):
        result = api.get_prompt("x")
    assert result["name"] == "x"


def test_save_prompt_delegates() -> None:
    api = DesktopAPI()
    mock_svc = MagicMock()
    mock_svc.save_prompt.return_value = {"saved": True}
    with patch("pokepoke.prompts.prompts.get_prompt_service", return_value=mock_svc):
        result = api.save_prompt("x", "content")
    assert result["saved"]
    mock_svc.save_prompt.assert_called_once_with("x", "content")


def test_reset_prompt_delegates() -> None:
    api = DesktopAPI()
    mock_svc = MagicMock()
    mock_svc.reset_prompt.return_value = {"reset": True}
    with patch("pokepoke.prompts.prompts.get_prompt_service", return_value=mock_svc):
        result = api.reset_prompt("x")
    assert result["reset"]


# ── _mutate_work_item_label ──────────────────────────────────────────────


def test_add_work_item_label_success(monkeypatch) -> None:
    api = DesktopAPI()
    api.push_work_item("PK-1", "T", "open", ["urgent"])
    mock_run = Mock(returncode=0, stdout="{}", stderr="")
    monkeypatch.setattr("pokepoke.desktop.desktop_api_ext._run_bd_with_retry", lambda *a, **kw: mock_run)
    result = api.add_work_item_label("PK-1", "human-required")
    assert result["success"] is True
    assert "human-required" in result["labels"]


def test_remove_work_item_label_success(monkeypatch) -> None:
    api = DesktopAPI()
    api.push_work_item("PK-1", "T", "open", ["urgent", "x"])
    mock_run = Mock(returncode=0, stdout="{}", stderr="")
    monkeypatch.setattr("pokepoke.desktop.desktop_api_ext._run_bd_with_retry", lambda *a, **kw: mock_run)
    result = api.remove_work_item_label("PK-1", "urgent")
    assert result["success"] is True
    assert "urgent" not in result["labels"]


def test_add_label_empty_raises() -> None:
    api = DesktopAPI()
    with pytest.raises(ValueError, match="Label cannot be empty"):
        api.add_work_item_label("PK-1", "  ")


def test_remove_label_empty_raises() -> None:
    api = DesktopAPI()
    with pytest.raises(ValueError, match="Label cannot be empty"):
        api.remove_work_item_label("PK-1", "")


def test_add_label_called_process_error(monkeypatch) -> None:
    api = DesktopAPI()
    api.push_work_item("PK-1", "T", "open", ["a"])

    def _raise(*a, **kw):
        raise subprocess.CalledProcessError(1, "bd", stderr="network down")

    monkeypatch.setattr("pokepoke.desktop.desktop_api_ext._run_bd_with_retry", _raise)
    result = api.add_work_item_label("PK-1", "b")
    assert result["success"] is False
    assert "network down" in result["error"]


def test_add_label_called_process_error_no_stderr(monkeypatch) -> None:
    api = DesktopAPI()
    api.push_work_item("PK-1", "T", "open", [])

    def _raise(*a, **kw):
        raise subprocess.CalledProcessError(42, "bd", stderr="")

    monkeypatch.setattr("pokepoke.desktop.desktop_api_ext._run_bd_with_retry", _raise)
    result = api.add_work_item_label("PK-1", "b")
    assert result["success"] is False
    assert "exit code 42" in result["error"]


def test_remove_label_timeout(monkeypatch) -> None:
    api = DesktopAPI()
    api.push_work_item("PK-1", "T", "open", ["a"])

    def _timeout(*a, **kw):
        raise subprocess.TimeoutExpired(cmd="bd", timeout=30, stderr="timed")

    monkeypatch.setattr("pokepoke.desktop.desktop_api_ext._run_bd_with_retry", _timeout)
    result = api.remove_work_item_label("PK-1", "a")
    assert result["success"] is False
    assert "timed out" in result["error"]


def test_mutate_label_os_error(monkeypatch) -> None:
    api = DesktopAPI()
    api.push_work_item("PK-1", "T", "open", [])

    def _raise(*a, **kw):
        raise OSError("bd not found")

    monkeypatch.setattr("pokepoke.desktop.desktop_api_ext._run_bd_with_retry", _raise)
    result = api.add_work_item_label("PK-1", "x")
    assert result["success"] is False
    assert "bd not found" in result["error"]


# ── open_project ─────────────────────────────────────────────────────────


def test_open_project_nonexistent() -> None:
    api = DesktopAPI()
    result = api.open_project("/nonexistent/path/xyz")
    assert result["success"] is False
    assert "does not exist" in result["error"]


def test_open_project_not_git_repo(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("pokepoke.desktop.desktop_api_ext._is_git_repo", lambda p: False)
    result = DesktopAPI().open_project(str(tmp_path))
    assert result["success"] is False
    assert "Not a git repository" in result["error"]


def test_open_project_agents_active(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("pokepoke.desktop.desktop_api_ext._is_git_repo", lambda p: True)
    monkeypatch.setattr("pokepoke.utils.shutdown.has_active_agents", lambda: True)
    result = DesktopAPI().open_project(str(tmp_path))
    assert result["success"] is False
    assert "agents are running" in result["error"]


def test_open_project_success(tmp_path, monkeypatch) -> None:
    (tmp_path / ".pokepoke").mkdir()
    (tmp_path / ".pokepoke" / "config.yaml").write_text("project_name: Proj\n", encoding="utf-8")
    (tmp_path / ".git").mkdir()

    monkeypatch.setattr("pokepoke.desktop.desktop_api_ext._is_git_repo", lambda p: True)
    monkeypatch.setattr("pokepoke.desktop.desktop_api_ext._resolve_git_toplevel", lambda p: p)
    monkeypatch.setattr("pokepoke.desktop.desktop_api_ext._check_beads_available", lambda p: True)
    monkeypatch.setattr("pokepoke.git.repo_utils.get_repository_name", lambda: "test-repo")

    result = DesktopAPI().open_project(str(tmp_path))
    assert result["success"] is True
    assert result["needs_init"] is False
    assert result["needs_beads_init"] is False


def test_open_project_resolves_to_toplevel(tmp_path, monkeypatch) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    subdir = repo_root / "src"
    subdir.mkdir()
    (repo_root / ".pokepoke").mkdir()
    (repo_root / ".pokepoke" / "config.yaml").write_text("project_name: R\n", encoding="utf-8")
    (repo_root / ".git").mkdir()

    monkeypatch.setattr("pokepoke.desktop.desktop_api_ext._is_git_repo", lambda p: True)
    monkeypatch.setattr("pokepoke.desktop.desktop_api_ext._resolve_git_toplevel", lambda p: repo_root)
    monkeypatch.setattr("pokepoke.desktop.desktop_api_ext._check_beads_available", lambda p: True)
    monkeypatch.setattr("pokepoke.git.repo_utils.get_repository_name", lambda: "repo")

    result = DesktopAPI().open_project(str(subdir))
    assert result["success"] is True
    assert result["path"] == str(repo_root)


def test_open_project_needs_init_no_config(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("pokepoke.desktop.desktop_api_ext._is_git_repo", lambda p: True)
    monkeypatch.setattr("pokepoke.desktop.desktop_api_ext._resolve_git_toplevel", lambda p: p)
    monkeypatch.setattr("pokepoke.desktop.desktop_api_ext._check_beads_available", lambda p: False)
    monkeypatch.setattr("pokepoke.git.repo_utils.get_repository_name", lambda: "bare-repo")

    result = DesktopAPI().open_project(str(tmp_path))
    assert result["success"] is True
    assert result["needs_init"] is True
    assert result["needs_beads_init"] is True


def test_open_project_toplevel_returns_none(tmp_path, monkeypatch) -> None:
    """When _resolve_git_toplevel returns None, project_path should not change."""
    (tmp_path / ".pokepoke").mkdir()
    (tmp_path / ".pokepoke" / "config.yaml").write_text("project_name: P\n", encoding="utf-8")
    (tmp_path / ".git").mkdir()

    monkeypatch.setattr("pokepoke.desktop.desktop_api_ext._is_git_repo", lambda p: True)
    monkeypatch.setattr("pokepoke.desktop.desktop_api_ext._resolve_git_toplevel", lambda p: None)
    monkeypatch.setattr("pokepoke.desktop.desktop_api_ext._check_beads_available", lambda p: True)
    monkeypatch.setattr("pokepoke.git.repo_utils.get_repository_name", lambda: "p")

    result = DesktopAPI().open_project(str(tmp_path))
    assert result["success"] is True


# ── browse_for_project ───────────────────────────────────────────────────


def test_browse_for_project_no_window() -> None:
    api = DesktopAPI()
    result = api.browse_for_project()
    assert result["success"] is False
    assert "No window" in result["error"]


def test_browse_for_project_cancelled() -> None:
    api = DesktopAPI()
    mock_win = Mock()
    mock_win.create_file_dialog.return_value = None
    api.set_window(mock_win)
    result = api.browse_for_project()
    assert result.get("cancelled") is True


def test_browse_for_project_dialog_exception() -> None:
    api = DesktopAPI()
    mock_win = Mock()
    mock_win.create_file_dialog.side_effect = RuntimeError("fail")
    api.set_window(mock_win)
    result = api.browse_for_project()
    assert result["success"] is False
    assert "Dialog failed" in result["error"]


def test_browse_for_project_delegates(tmp_path, monkeypatch) -> None:
    (tmp_path / ".pokepoke").mkdir()
    (tmp_path / ".pokepoke" / "config.yaml").write_text("project_name: P\n", encoding="utf-8")
    (tmp_path / ".git").mkdir()

    monkeypatch.setattr("pokepoke.desktop.desktop_api_ext._is_git_repo", lambda p: True)
    monkeypatch.setattr("pokepoke.desktop.desktop_api_ext._resolve_git_toplevel", lambda p: p)
    monkeypatch.setattr("pokepoke.desktop.desktop_api_ext._check_beads_available", lambda p: True)
    monkeypatch.setattr("pokepoke.git.repo_utils.get_repository_name", lambda: "P")

    api = DesktopAPI()
    mock_win = Mock()
    mock_win.create_file_dialog.return_value = (str(tmp_path),)
    api.set_window(mock_win)
    result = api.browse_for_project()
    assert result["success"] is True


def test_browse_for_project_string_result(tmp_path, monkeypatch) -> None:
    """pywebview may return a plain string instead of tuple."""
    (tmp_path / ".pokepoke").mkdir()
    (tmp_path / ".pokepoke" / "config.yaml").write_text("project_name: Q\n", encoding="utf-8")
    (tmp_path / ".git").mkdir()

    monkeypatch.setattr("pokepoke.desktop.desktop_api_ext._is_git_repo", lambda p: True)
    monkeypatch.setattr("pokepoke.desktop.desktop_api_ext._resolve_git_toplevel", lambda p: p)
    monkeypatch.setattr("pokepoke.desktop.desktop_api_ext._check_beads_available", lambda p: True)
    monkeypatch.setattr("pokepoke.git.repo_utils.get_repository_name", lambda: "Q")

    api = DesktopAPI()
    mock_win = Mock()
    mock_win.create_file_dialog.return_value = str(tmp_path)
    api.set_window(mock_win)
    result = api.browse_for_project()
    assert result["success"] is True


# ── Helper wrappers (_is_git_repo etc.) ──────────────────────────────────


def test_is_git_repo_delegates() -> None:
    from pokepoke.desktop.desktop_api_ext import _is_git_repo
    with patch("pokepoke.utils.project_utils.is_git_repo", return_value=True) as mock_fn:
        assert _is_git_repo(Path(".")) is True
        mock_fn.assert_called_once()


def test_resolve_git_toplevel_delegates() -> None:
    from pokepoke.desktop.desktop_api_ext import _resolve_git_toplevel
    with patch("pokepoke.utils.project_utils.resolve_git_toplevel", return_value=Path("/x")):
        assert _resolve_git_toplevel(Path(".")) == Path("/x")


def test_has_pokepoke_config_delegates() -> None:
    from pokepoke.desktop.desktop_api_ext import _has_pokepoke_config
    with patch("pokepoke.utils.project_utils.has_pokepoke_config", return_value=True):
        assert _has_pokepoke_config(Path(".")) is True


def test_check_beads_available_delegates() -> None:
    from pokepoke.desktop.desktop_api_ext import _check_beads_available
    with patch("pokepoke.utils.project_utils.check_beads_available", return_value=False):
        assert _check_beads_available(Path(".")) is False


# ── open_project thread safety ───────────────────────────────────────────


def test_open_project_chdir_under_lock(tmp_path, monkeypatch) -> None:
    """os.chdir inside open_project must happen under self._lock."""
    (tmp_path / ".pokepoke").mkdir()
    (tmp_path / ".pokepoke" / "config.yaml").write_text("project_name: P\n", encoding="utf-8")
    (tmp_path / ".git").mkdir()

    monkeypatch.setattr("pokepoke.desktop.desktop_api_ext._is_git_repo", lambda p: True)
    monkeypatch.setattr("pokepoke.desktop.desktop_api_ext._resolve_git_toplevel", lambda p: p)
    monkeypatch.setattr("pokepoke.desktop.desktop_api_ext._check_beads_available", lambda p: True)
    monkeypatch.setattr("pokepoke.git.repo_utils.get_repository_name", lambda: "P")

    api = DesktopAPI()
    chdir_was_locked = []

    original_chdir = os.chdir

    def tracking_chdir(path):
        # Check if lock is held (RLock._is_owned is a private method but safe for testing)
        chdir_was_locked.append(api._lock._is_owned())
        return original_chdir(path)

    monkeypatch.setattr("pokepoke.desktop.desktop_api_ext.os.chdir", tracking_chdir)

    result = api.open_project(str(tmp_path))
    assert result["success"] is True
    assert chdir_was_locked == [True], "os.chdir must be called while holding self._lock"
