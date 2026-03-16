from __future__ import annotations

from pathlib import Path
from unittest.mock import patch, Mock

import os
import subprocess
from contextlib import contextmanager


@contextmanager
def _chdir(path: Path):
    """Simple chdir helper that always restores cwd."""
    old = Path.cwd()
    try:
        os.chdir(path)
        yield
    finally:
        os.chdir(old)


def test_setup_complete_event_roundtrip() -> None:
    from pokepoke.desktop.desktop_api import DesktopAPI

    api = DesktopAPI()

    assert api.wait_for_setup_complete(0.0) is False
    result = api.complete_setup()
    assert result["success"] is True
    assert api.wait_for_setup_complete(0.0) is True


def test_create_default_config_writes_yaml(tmp_path: Path, monkeypatch) -> None:
    from pokepoke.desktop.desktop_api import DesktopAPI

    api = DesktopAPI()

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("pokepoke.utils.project_utils.resolve_git_toplevel", lambda _: tmp_path)
    result = api.create_default_config(
        {
            "project_name": "ExampleProject",
            "default_model": "claude-opus-4.6",
            "fallback_model": "claude-sonnet-4.5",
            "max_parallel_agents": 2,
            "default_branch": "main",
        }
    )

    assert result["saved"] is True
    config_path = tmp_path / ".pokepoke" / "config.yaml"
    assert config_path.exists()
    text = config_path.read_text(encoding="utf-8")
    assert "project_name: ExampleProject" in text
    assert "max_parallel_agents: 2" in text
    assert "default: claude-opus-4.6" in text


def test_scaffold_prompt_overrides_copies_beads_item(tmp_path: Path, monkeypatch) -> None:
    from pokepoke.desktop.desktop_api import DesktopAPI

    api = DesktopAPI()

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("pokepoke.utils.project_utils.resolve_git_toplevel", lambda _: tmp_path)
    result = api.scaffold_prompt_overrides(["beads-item"], False)
    assert result["success"] is True
    written = result.get("written") or []
    assert any(p.endswith("beads-item.md") for p in written)
    assert (tmp_path / ".pokepoke" / "prompts" / "beads-item.md").exists()


def test_orchestrator_main_waits_for_setup_then_runs(tmp_path: Path) -> None:
    from pokepoke.desktop.desktop_ui import DesktopUI

    class FakeDesktopUI(DesktopUI):
        def __init__(self) -> None:
            super().__init__()
            self.wait_calls: int = 0

        def wait_for_setup_complete(self, timeout: float | None = None) -> bool:
            self.wait_calls += 1
            return True

        def run_with_orchestrator(self, orchestrator_func):
            return orchestrator_func()

    fake_ui = FakeDesktopUI()

    with (
        _chdir(tmp_path),
        patch("pokepoke.desktop.terminal_ui.ui", fake_ui),
        patch("pokepoke.orchestration.orchestrator.run_orchestrator", return_value=0) as mock_run,
        patch("pokepoke.utils.project_utils.is_git_repo", side_effect=[False, True]),
        patch("pokepoke.utils.project_utils.has_pokepoke_config", return_value=True),
        patch("pokepoke.utils.project_utils.check_beads_available", return_value=True),
        patch("sys.argv", ["pokepoke", "--autonomous"]),
    ):
        from pokepoke.__main__ import main

        assert main() == 0

    assert fake_ui.wait_calls == 1
    mock_run.assert_called_once()


def test_check_setup_status_returns_correct_structure(tmp_path: Path) -> None:
    from pokepoke.desktop.desktop_api import DesktopAPI

    api = DesktopAPI()

    with (
        _chdir(tmp_path),
        patch("pokepoke.utils.project_utils.is_git_repo", return_value=True),
        patch("pokepoke.utils.project_utils.resolve_git_toplevel", return_value=tmp_path),
        patch("pokepoke.utils.project_utils.has_pokepoke_config", return_value=False),
        patch("pokepoke.utils.project_utils.check_beads_available", return_value=False),
    ):
        result = api.check_setup_status()

    assert result["is_git_repo"] is True
    assert result["config_exists"] is False
    assert result["beads_initialized"] is False
    assert result["needs_setup"] is True
    assert "project_root" in result
    assert "config_path" in result


def test_git_init_success(tmp_path: Path) -> None:
    from pokepoke.desktop.desktop_api import DesktopAPI

    api = DesktopAPI()

    mock_result = Mock(stdout="Initialized empty Git repository\n", stderr="")
    with (
        _chdir(tmp_path),
        patch("pokepoke.desktop.desktop_api_setup.subprocess.run", return_value=mock_result) as mock_run,
    ):
        result = api.git_init("main")

    assert result["success"] is True
    mock_run.assert_called_once()
    call_args = mock_run.call_args
    assert "-b" in call_args[0][0]
    assert "main" in call_args[0][0]


def test_git_init_timeout(tmp_path: Path) -> None:
    from pokepoke.desktop.desktop_api import DesktopAPI

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


def test_git_init_failure(tmp_path: Path) -> None:
    from pokepoke.desktop.desktop_api import DesktopAPI

    api = DesktopAPI()

    exc = subprocess.CalledProcessError(128, "git init", stderr="fatal: error")
    with (
        _chdir(tmp_path),
        patch("pokepoke.desktop.desktop_api_setup.subprocess.run", side_effect=exc),
    ):
        result = api.git_init()

    assert result["success"] is False


def test_coerce_process_output() -> None:
    from pokepoke.desktop.desktop_api_utils import coerce_process_output

    assert coerce_process_output(None) is None
    assert coerce_process_output("") is None
    assert coerce_process_output("  ") is None
    assert coerce_process_output("hello\n") == "hello"


def test_require_yaml_available() -> None:
    """require_yaml should not raise when yaml is installed."""
    from pokepoke.desktop.desktop_api_utils import require_yaml
    require_yaml("load config")  # should not raise


def test_require_yaml_missing(monkeypatch) -> None:
    """require_yaml should raise ImportError when HAS_YAML is False."""
    import pytest
    import pokepoke.desktop.desktop_api_utils as dau

    monkeypatch.setattr(dau, "HAS_YAML", False)
    with pytest.raises(ImportError, match="PyYAML is required"):
        dau.require_yaml("load config")


def test_bd_init_delegates(tmp_path: Path) -> None:
    from pokepoke.desktop.desktop_api import DesktopAPI

    api = DesktopAPI()

    with (
        _chdir(tmp_path),
        patch("pokepoke.git.repo_check.initialize_beads_repo", return_value=True) as mock_init,
        patch("pokepoke.utils.project_utils.resolve_git_toplevel", return_value=tmp_path),
    ):
        result = api.bd_init()

    assert result["success"] is True
    mock_init.assert_called_once()


def test_create_default_config_rejects_non_dict() -> None:
    from pokepoke.desktop.desktop_api import DesktopAPI
    import pytest

    api = DesktopAPI()

    with pytest.raises(ValueError, match="Config must be a dict"):
        api.create_default_config("not a dict")


def test_scaffold_prompt_overrides_skips_existing(tmp_path: Path) -> None:
    from pokepoke.desktop.desktop_api import DesktopAPI

    api = DesktopAPI()

    with _chdir(tmp_path):
        # First call: scaffold
        api.scaffold_prompt_overrides(["beads-item"], False)
        # Second call without force: should skip
        result = api.scaffold_prompt_overrides(["beads-item"], False)

    assert result["success"] is True
    assert len(result["written"]) == 0


def test_complete_setup_without_event() -> None:
    from pokepoke.desktop.desktop_api_setup import complete_setup

    obj = object()
    result = complete_setup(obj)
    assert result["success"] is False


def test_wait_for_setup_complete_without_event() -> None:
    from pokepoke.desktop.desktop_api_setup import wait_for_setup_complete

    obj = object()
    assert wait_for_setup_complete(obj) is True
