"""Tests for AI backend registry and adapters."""

import logging
import subprocess
from types import SimpleNamespace
from unittest.mock import patch

from pokepoke.models.ai_backends import (
    ClaudeCodeBackend,
    CopilotBackend,
    get_backend,
)
from pokepoke.types import BeadsWorkItem
from pokepoke.types_agent import CopilotResult


def _work_item(item_id: str = "item-1") -> BeadsWorkItem:
    return BeadsWorkItem(
        id=item_id,
        title="Test",
        description="",
        status="open",
        priority=1,
        issue_type="task",
    )


def _config(provider: str = "copilot") -> SimpleNamespace:
    return SimpleNamespace(
        ai_backend=SimpleNamespace(
            provider=provider,
            copilot_cli_path="copilot.cmd",
            claude_code_cli_path="claude",
        )
    )


@patch("pokepoke.models.ai_backends.get_config")
def test_get_backend_default_is_copilot(mock_get_config):
    mock_get_config.return_value = _config("copilot")

    backend = get_backend()

    assert isinstance(backend, CopilotBackend)
    assert backend.name == "copilot"


@patch("pokepoke.models.ai_backends.shutil.which", return_value=None)
@patch("pokepoke.models.ai_backends.get_config")
def test_claude_code_backend_handles_missing_cli(mock_get_config, mock_which):
    mock_get_config.return_value = _config("claude-code")
    backend = get_backend()
    work_item = _work_item()

    result = backend.invoke(work_item, prompt="hello world")

    assert isinstance(backend, ClaudeCodeBackend)
    assert result.success is False
    assert "Claude Code CLI not found" in (result.error or "")
    mock_which.assert_called()


@patch("pokepoke.models.ai_backends.get_config")
def test_unknown_backend_falls_back_to_copilot(mock_get_config, caplog):
    mock_get_config.return_value = _config("mystery")

    with caplog.at_level(logging.DEBUG, logger="pokepoke.models.ai_backends"):
        backend = get_backend()

    assert isinstance(backend, CopilotBackend)
    assert "Unknown AI backend" in caplog.text


def test_claude_backend_subprocess_failure_is_captured():
    backend = ClaudeCodeBackend(cli_path="nonexistent-cli")
    work_item = _work_item("item-2")

    result = backend.invoke(work_item, prompt="test prompt")

    assert isinstance(result, CopilotResult)
    assert result.success is False
    assert "not found" in (result.error or "").lower()


@patch("pokepoke.models.ai_backends.invoke_copilot_sdk_sync")
def test_copilot_backend_invoke_delegates(mock_sdk):
    mock_sdk.return_value = CopilotResult(
        work_item_id="item-1", success=True, output="done", error=None,
        attempt_count=1, model=None,
    )
    backend = CopilotBackend()
    work_item = _work_item()

    result = backend.invoke(work_item, prompt="do it")

    assert result.success is True
    assert result.output == "done"
    mock_sdk.assert_called_once()


@patch("pokepoke.models.ai_backends.subprocess.run")
@patch("pokepoke.models.ai_backends.shutil.which", return_value="/usr/bin/claude")
def test_claude_backend_success(mock_which, mock_run):
    mock_run.return_value = SimpleNamespace(returncode=0, stdout="output text", stderr="")
    backend = ClaudeCodeBackend(cli_path="claude")
    work_item = _work_item()

    result = backend.invoke(work_item, prompt="hello")

    assert result.success is True
    assert result.output == "output text"
    assert result.error is None


@patch("pokepoke.models.ai_backends.subprocess.run")
@patch("pokepoke.models.ai_backends.shutil.which", return_value="/usr/bin/claude")
def test_claude_backend_nonzero_exit(mock_which, mock_run):
    mock_run.return_value = SimpleNamespace(returncode=1, stdout="", stderr="some error")
    backend = ClaudeCodeBackend(cli_path="claude")
    work_item = _work_item()

    result = backend.invoke(work_item, prompt="hello")

    assert result.success is False
    assert "Claude Code exited with 1" in (result.error or "")
    assert "some error" in (result.error or "")


@patch("pokepoke.models.ai_backends.subprocess.run")
@patch("pokepoke.models.ai_backends.shutil.which", return_value="/usr/bin/claude")
def test_claude_backend_nonzero_no_stderr(mock_which, mock_run):
    mock_run.return_value = SimpleNamespace(returncode=2, stdout="", stderr="")
    backend = ClaudeCodeBackend(cli_path="claude")
    work_item = _work_item()

    result = backend.invoke(work_item, prompt="hello")

    assert result.success is False
    assert "Claude Code exited with 2" in (result.error or "")


@patch("pokepoke.models.ai_backends.subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="claude", timeout=10))
@patch("pokepoke.models.ai_backends.shutil.which", return_value="/usr/bin/claude")
def test_claude_backend_timeout(mock_which, mock_run):
    backend = ClaudeCodeBackend(cli_path="claude")
    work_item = _work_item()

    result = backend.invoke(work_item, prompt="hello", timeout=10.0)

    assert result.success is False
    assert "timed out" in (result.error or "").lower()


@patch("pokepoke.models.ai_backends.subprocess.run", side_effect=FileNotFoundError("not found"))
@patch("pokepoke.models.ai_backends.shutil.which", return_value="/usr/bin/claude")
def test_claude_backend_file_not_found_during_run(mock_which, mock_run):
    backend = ClaudeCodeBackend(cli_path="claude")
    work_item = _work_item()

    result = backend.invoke(work_item, prompt="hello")

    assert result.success is False
    assert "not found" in (result.error or "").lower()


@patch("pokepoke.models.ai_backends.build_prompt_from_work_item", return_value="auto prompt")
@patch("pokepoke.models.ai_backends.shutil.which", return_value=None)
def test_claude_backend_builds_prompt_when_none(mock_which, mock_build):
    backend = ClaudeCodeBackend(cli_path="claude")
    work_item = _work_item()

    result = backend.invoke(work_item)

    mock_build.assert_called_once_with(work_item, "beads-item")
    assert result.success is False


@patch("pokepoke.models.ai_backends.get_config")
def test_get_backend_explicit_provider(mock_get_config):
    mock_get_config.return_value = _config("copilot")

    backend = get_backend(provider="copilot")

    assert isinstance(backend, CopilotBackend)
