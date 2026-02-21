"""Pluggable AI backend registry and adapters."""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from collections.abc import Callable
from typing import Any, Protocol

from pokepoke.config import get_config
from pokepoke.copilot_sdk import build_prompt_from_work_item, invoke_copilot_sdk_sync
from pokepoke.types import BeadsWorkItem, CopilotResult, RetryConfig


class AIBackend(Protocol):
    """Protocol for AI backend adapters."""

    name: str

    def invoke(
        self,
        work_item: BeadsWorkItem,
        prompt: str | None = None,
        retry_config: RetryConfig | None = None,
        timeout: float | None = None,
        deny_write: bool = False,
        item_logger: Any = None,
        model: str | None = None,
        cwd: str | None = None,
    ) -> CopilotResult:
        ...


@dataclass
class CopilotBackend:
    """Default backend using the Copilot SDK/CLI."""

    name: str = "copilot"

    def invoke(
        self,
        work_item: BeadsWorkItem,
        prompt: str | None = None,
        retry_config: RetryConfig | None = None,
        timeout: float | None = None,
        deny_write: bool = False,
        item_logger: Any = None,
        model: str | None = None,
        cwd: str | None = None,
    ) -> CopilotResult:
        return invoke_copilot_sdk_sync(
            work_item=work_item,
            prompt=prompt,
            retry_config=retry_config,
            timeout=timeout,
            deny_write=deny_write,
            item_logger=item_logger,
            model=model,
            cwd=cwd,
        )


@dataclass
class ClaudeCodeBackend:
    """Claude Code CLI backend adapter.

    Uses a simple subprocess invocation to stream a prompt to the Claude Code
    CLI. If the CLI is unavailable, returns a failed result with a clear error.
    """

    cli_path: str
    name: str = "claude-code"

    def invoke(
        self,
        work_item: BeadsWorkItem,
        prompt: str | None = None,
        retry_config: RetryConfig | None = None,
        timeout: float | None = None,
        deny_write: bool = False,
        item_logger: Any = None,
        model: str | None = None,
        cwd: str | None = None,
    ) -> CopilotResult:
        final_prompt = prompt or build_prompt_from_work_item(work_item)
        # Claude Code is read-only by design; deny_write is inherent.
        if shutil.which(self.cli_path) is None:
            return CopilotResult(
                work_item_id=work_item.id,
                success=False,
                output=None,
                error=f"Claude Code CLI not found: {self.cli_path}",
                attempt_count=1,
                model=model,
            )

        env = {**os.environ, "PYTHONIOENCODING": "utf-8:replace"}
        args = [self.cli_path, "code", "--raw"]
        try:
            proc = subprocess.run(
                args,
                input=final_prompt,
                text=True,
                capture_output=True,
                timeout=timeout or 7200.0,
                cwd=cwd,
                env=env,
            )
        except subprocess.TimeoutExpired:
            return CopilotResult(
                work_item_id=work_item.id,
                success=False,
                output=None,
                error=f"Claude Code CLI timed out after {timeout or 7200.0}s",
                attempt_count=1,
                model=model,
            )
        except FileNotFoundError:
            return CopilotResult(
                work_item_id=work_item.id,
                success=False,
                output=None,
                error=f"Claude Code CLI not found: {self.cli_path}",
                attempt_count=1,
                model=model,
            )
        except Exception as exc:  # pragma: no cover - defensive fallback
            return CopilotResult(
                work_item_id=work_item.id,
                success=False,
                output=None,
                error=f"Claude Code CLI failed: {exc}",
                attempt_count=1,
                model=model,
            )

        success = proc.returncode == 0
        stderr = (proc.stderr or "").strip()
        error = None if success else (f"Claude Code exited with {proc.returncode}: {stderr}" if stderr else f"Claude Code exited with {proc.returncode}")

        return CopilotResult(
            work_item_id=work_item.id,
            success=success,
            output=proc.stdout,
            error=error,
            attempt_count=1,
            model=model,
        )


BackendFactory = Callable[[], AIBackend]

_BACKENDS: dict[str, BackendFactory] = {}


def _register_defaults() -> None:
    """Register built-in backends."""
    _BACKENDS.setdefault("copilot", CopilotBackend)

    def _claude_factory() -> ClaudeCodeBackend:
        cfg = get_config()
        return ClaudeCodeBackend(cli_path=cfg.ai_backend.claude_code_cli_path)

    _BACKENDS.setdefault("claude-code", _claude_factory)


def get_backend(provider: str | None = None) -> AIBackend:
    """Resolve the backend to use based on provider or config.

    Falls back to Copilot if the requested provider is unknown.
    """
    _register_defaults()
    cfg = get_config()
    name = (provider or cfg.ai_backend.provider or "copilot").lower()
    factory = _BACKENDS.get(name)
    if factory is None:
        # Fallback to default backend with a clear warning in output
        print(f"⚠️  Unknown AI backend '{name}', falling back to Copilot")
        return _BACKENDS["copilot"]()
    return factory()
