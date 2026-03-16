"""Tests for desktop_api_setup mixin module — coverage-mapped companion."""

from __future__ import annotations

import os
import subprocess
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from pokepoke.desktop.desktop_api import DesktopAPI
from pokepoke.desktop.desktop_api_setup import (
    complete_setup,
    wait_for_setup_complete,
)
from pokepoke.desktop.desktop_api_utils import coerce_process_output


@pytest.fixture(autouse=True)
def _isolate_desktop_api(monkeypatch):
    """Prevent DesktopAPI from loading real historical agents or calling git."""
    monkeypatch.setattr("pokepoke.desktop.desktop_api_ext._discover_log_roots", lambda: [])
    monkeypatch.setattr("pokepoke.desktop.desktop_api.get_repository_name", lambda: "test-repo")


@contextmanager
def _chdir(path: Path):
    old = Path.cwd()
    try:
        os.chdir(path)
        yield
    finally:
        os.chdir(old)


# ── coerce_process_output ───────────────────────────────────────────────


def test_coerce_none() -> None:
    assert coerce_process_output(None) is None


def test_coerce_empty() -> None:
    assert coerce_process_output("") is None


def test_coerce_whitespace() -> None:
    assert coerce_process_output("   ") is None


def test_coerce_strips() -> None:
    assert coerce_process_output("  hi\n") == "hi"


# ── check_setup_status ───────────────────────────────────────────────────


def test_check_setup_status_needs_setup(tmp_path) -> None:
    api = DesktopAPI()
    with (
        _chdir(tmp_path),
        patch("pokepoke.utils.project_utils.is_git_repo", return_value=False),
        patch("pokepoke.utils.project_utils.resolve_git_toplevel", return_value=None),
        patch("pokepoke.utils.project_utils.has_pokepoke_config", return_value=False),
        patch("pokepoke.utils.project_utils.check_beads_available", return_value=False),
    ):
        result = api.check_setup_status()

    assert result["needs_setup"] is True
    assert result["is_git_repo"] is False
    assert result["config_exists"] is False
    assert result["beads_initialized"] is False
    assert "cwd" in result
    assert "config_path" in result


def test_check_setup_status_fully_configured(tmp_path) -> None:
    api = DesktopAPI()
    with (
        _chdir(tmp_path),
        patch("pokepoke.utils.project_utils.is_git_repo", return_value=True),
        patch("pokepoke.utils.project_utils.resolve_git_toplevel", return_value=tmp_path),
        patch("pokepoke.utils.project_utils.has_pokepoke_config", return_value=True),
        patch("pokepoke.utils.project_utils.check_beads_available", return_value=True),
        patch("shutil.which", return_value="/usr/bin/bd"),
    ):
        result = api.check_setup_status()

    assert result["needs_setup"] is False
    assert result["is_git_repo"] is True
    assert result["config_exists"] is True
    assert result["beads_initialized"] is True
    assert result["beads_installed"] is True
    assert result["project_root"] == str(tmp_path)


def test_check_setup_status_no_git_toplevel(tmp_path) -> None:
    """When resolve_git_toplevel returns None, project_root falls back to cwd."""
    api = DesktopAPI()
    with (
        _chdir(tmp_path),
        patch("pokepoke.utils.project_utils.is_git_repo", return_value=False),
        patch("pokepoke.utils.project_utils.resolve_git_toplevel", return_value=None),
        patch("pokepoke.utils.project_utils.has_pokepoke_config", return_value=False),
        patch("pokepoke.utils.project_utils.check_beads_available", return_value=False),
    ):
        result = api.check_setup_status()

    assert result["project_root"] == str(tmp_path.resolve())


# ── git_init ─────────────────────────────────────────────────────────────


def test_git_init_success(tmp_path) -> None:
    api = DesktopAPI()
    mock_result = Mock(stdout="Initialized empty Git repository\n", stderr="")
    with (
        _chdir(tmp_path),
        patch("pokepoke.desktop.desktop_api_setup.subprocess.run", return_value=mock_result) as mock_run,
    ):
        result = api.git_init("main")

    assert result["success"] is True
    call_args = mock_run.call_args[0][0]
    assert "-b" in call_args
    assert "main" in call_args


def test_git_init_no_branch(tmp_path) -> None:
    api = DesktopAPI()
    mock_result = Mock(stdout="init\n", stderr="")
    with (
        _chdir(tmp_path),
        patch("pokepoke.desktop.desktop_api_setup.subprocess.run", return_value=mock_result) as mock_run,
    ):
        result = api.git_init()

    assert result["success"] is True
    call_args = mock_run.call_args[0][0]
    assert "-b" not in call_args


def test_git_init_timeout(tmp_path) -> None:
    api = DesktopAPI()
    with (
        _chdir(tmp_path),
        patch(
            "pokepoke.desktop.desktop_api_setup.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="git init", timeout=30),
        ),
    ):
        result = api.git_init()

    assert result["success"] is False
    assert "timed out" in result["error"]


def test_git_init_called_process_error(tmp_path) -> None:
    api = DesktopAPI()
    exc = subprocess.CalledProcessError(128, "git init", stderr="fatal: error")
    with (
        _chdir(tmp_path),
        patch("pokepoke.desktop.desktop_api_setup.subprocess.run", side_effect=exc),
    ):
        result = api.git_init()

    assert result["success"] is False
    assert "fatal: error" in result["error"]


def test_git_init_os_error(tmp_path) -> None:
    api = DesktopAPI()
    with (
        _chdir(tmp_path),
        patch("pokepoke.desktop.desktop_api_setup.subprocess.run", side_effect=OSError("git not found")),
    ):
        result = api.git_init()

    assert result["success"] is False
    assert "git not found" in result["error"]


# ── bd_init ──────────────────────────────────────────────────────────────


def test_bd_init_success(tmp_path) -> None:
    api = DesktopAPI()
    with (
        _chdir(tmp_path),
        patch("pokepoke.git.repo_check.initialize_beads_repo", return_value=True) as mock_init,
        patch("pokepoke.utils.project_utils.resolve_git_toplevel", return_value=tmp_path),
    ):
        result = api.bd_init()

    assert result["success"] is True
    mock_init.assert_called_once()


def test_bd_init_failure(tmp_path) -> None:
    api = DesktopAPI()
    with (
        _chdir(tmp_path),
        patch("pokepoke.git.repo_check.initialize_beads_repo", return_value=False),
        patch("pokepoke.utils.project_utils.resolve_git_toplevel", return_value=None),
    ):
        result = api.bd_init()

    assert result["success"] is False


# ── create_default_config ────────────────────────────────────────────────


def test_create_default_config_writes_yaml(tmp_path, monkeypatch) -> None:
    api = DesktopAPI()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("pokepoke.utils.project_utils.resolve_git_toplevel", lambda _: tmp_path)

    result = api.create_default_config({
        "project_name": "TestProj",
        "default_model": "claude-opus-4.6",
        "fallback_model": "claude-sonnet-4.5",
        "max_parallel_agents": 3,
        "default_branch": "main",
    })

    assert result["saved"] is True
    config_path = tmp_path / ".pokepoke" / "config.yaml"
    assert config_path.exists()
    text = config_path.read_text(encoding="utf-8")
    assert "project_name: TestProj" in text
    assert "max_parallel_agents: 3" in text


def test_create_default_config_camelCase_keys(tmp_path, monkeypatch) -> None:
    """Should accept camelCase keys from JS frontend."""
    api = DesktopAPI()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("pokepoke.utils.project_utils.resolve_git_toplevel", lambda _: tmp_path)

    result = api.create_default_config({
        "projectName": "CamelProj",
        "defaultModel": "gpt-5",
        "fallbackModel": "gpt-4",
        "maxParallelAgents": 2,
        "defaultBranch": "dev",
    })

    assert result["saved"] is True
    import yaml
    data = yaml.safe_load((tmp_path / ".pokepoke" / "config.yaml").read_text(encoding="utf-8"))
    assert data["project_name"] == "CamelProj"
    assert data["models"]["default"] == "gpt-5"
    assert data["git"]["default_branch"] == "dev"


def test_create_default_config_minimal(tmp_path, monkeypatch) -> None:
    """Empty dict should still produce valid config with defaults."""
    api = DesktopAPI()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("pokepoke.utils.project_utils.resolve_git_toplevel", lambda _: tmp_path)

    result = api.create_default_config({})
    assert result["saved"] is True


def test_create_default_config_rejects_non_dict() -> None:
    api = DesktopAPI()
    with pytest.raises(ValueError, match="Config must be a dict"):
        api.create_default_config("not a dict")


def test_create_default_config_no_yaml(monkeypatch) -> None:
    api = DesktopAPI()
    monkeypatch.setattr("pokepoke.desktop.desktop_api_utils.HAS_YAML", False)
    monkeypatch.setattr("pokepoke.desktop.desktop_api_setup.HAS_YAML", False)
    with pytest.raises(ImportError, match="PyYAML"):
        api.create_default_config({"project_name": "x"})


def test_create_default_config_no_git_toplevel(tmp_path, monkeypatch) -> None:
    """When resolve_git_toplevel returns None, should use cwd."""
    api = DesktopAPI()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("pokepoke.utils.project_utils.resolve_git_toplevel", lambda _: None)

    result = api.create_default_config({"project_name": "fallback"})
    assert result["saved"] is True
    assert (tmp_path / ".pokepoke" / "config.yaml").exists()


# ── scaffold_prompt_overrides ────────────────────────────────────────────


def test_scaffold_prompt_overrides_default(tmp_path, monkeypatch) -> None:
    api = DesktopAPI()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("pokepoke.utils.project_utils.resolve_git_toplevel", lambda _: tmp_path)

    result = api.scaffold_prompt_overrides(["beads-item"], False)
    assert result["success"] is True
    written = result.get("written") or []
    assert any(p.endswith("beads-item.md") for p in written)


def test_scaffold_prompt_overrides_skips_existing(tmp_path, monkeypatch) -> None:
    api = DesktopAPI()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("pokepoke.utils.project_utils.resolve_git_toplevel", lambda _: tmp_path)

    api.scaffold_prompt_overrides(["beads-item"], False)
    result = api.scaffold_prompt_overrides(["beads-item"], False)
    assert result["success"] is True
    assert len(result["written"]) == 0


def test_scaffold_prompt_overrides_force(tmp_path, monkeypatch) -> None:
    api = DesktopAPI()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("pokepoke.utils.project_utils.resolve_git_toplevel", lambda _: tmp_path)

    api.scaffold_prompt_overrides(["beads-item"], False)
    result = api.scaffold_prompt_overrides(["beads-item"], True)
    assert result["success"] is True
    assert len(result["written"]) >= 1


def test_scaffold_prompt_overrides_missing_template(tmp_path, monkeypatch) -> None:
    """Non-existent template name should be silently skipped."""
    api = DesktopAPI()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("pokepoke.utils.project_utils.resolve_git_toplevel", lambda _: tmp_path)

    result = api.scaffold_prompt_overrides(["nonexistent-template-xyz"], False)
    assert result["success"] is True
    assert result["written"] == []


def test_scaffold_prompt_overrides_none_templates(tmp_path, monkeypatch) -> None:
    """None templates should default to ['beads-item']."""
    api = DesktopAPI()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("pokepoke.utils.project_utils.resolve_git_toplevel", lambda _: tmp_path)

    result = api.scaffold_prompt_overrides(None, False)
    assert result["success"] is True


def test_scaffold_no_git_toplevel(tmp_path, monkeypatch) -> None:
    """When resolve_git_toplevel returns None, should use cwd."""
    api = DesktopAPI()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("pokepoke.utils.project_utils.resolve_git_toplevel", lambda _: None)

    result = api.scaffold_prompt_overrides(["beads-item"], False)
    assert result["success"] is True


# ── complete_setup / wait_for_setup_complete ─────────────────────────────


def test_complete_setup_success() -> None:
    api = DesktopAPI()
    result = api.complete_setup()
    assert result["success"] is True
    assert api._setup_complete_event.is_set()


def test_complete_setup_no_event() -> None:
    """Object without _setup_complete_event should return error."""
    obj = object()
    result = complete_setup(obj)
    assert result["success"] is False
    assert "setup event" in result["error"]


def test_wait_for_setup_complete_true_after_set() -> None:
    api = DesktopAPI()
    api.complete_setup()
    assert api.wait_for_setup_complete(timeout=0.0) is True


def test_wait_for_setup_complete_false_on_timeout() -> None:
    api = DesktopAPI()
    assert api.wait_for_setup_complete(timeout=0.0) is False


def test_wait_for_setup_complete_no_event() -> None:
    """Object without event should return True (nothing to wait for)."""
    obj = object()
    assert wait_for_setup_complete(obj) is True


def test_setup_roundtrip() -> None:
    """complete_setup -> wait_for_setup_complete should succeed."""
    api = DesktopAPI()
    assert api.wait_for_setup_complete(0.0) is False
    api.complete_setup()
    assert api.wait_for_setup_complete(0.0) is True
