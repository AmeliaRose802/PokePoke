"""Pluggable AI backend registry and adapters."""

import logging
import os
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from pokepoke.config import get_config
from pokepoke.models.copilot_sdk import (
    CopilotInvocationConfig,
    build_prompt_from_work_item,
    invoke_copilot_sdk_sync,
)
from pokepoke.types import BeadsWorkItem, RetryConfig
from pokepoke.types_agent import CopilotResult
from pokepoke.utils.constants import DEFAULT_AGENT_TIMEOUT
from pokepoke.utils.logging_utils import ItemLogger

logger = logging.getLogger(__name__)


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
        item_logger: ItemLogger | None = None,
        model: str | None = None,
        cwd: str | None = None,
        template_name: str | None = None,
        session_id: str | None = None,
        is_resume: bool = False,
        add_parent_dir: bool = False,
    ) -> CopilotResult:
        ...


@dataclass
class CopilotBackend:
    """Default backend using the Copilot SDK."""

    name: str = "copilot"

    def invoke(
        self,
        work_item: BeadsWorkItem,
        prompt: str | None = None,
        retry_config: RetryConfig | None = None,
        timeout: float | None = None,
        deny_write: bool = False,
        item_logger: ItemLogger | None = None,
        model: str | None = None,
        cwd: str | None = None,
        template_name: str | None = None,
        session_id: str | None = None,
        is_resume: bool = False,
        add_parent_dir: bool = False,
    ) -> CopilotResult:
        config = CopilotInvocationConfig(
            retry_config=retry_config,
            timeout=timeout,
            deny_write=deny_write,
            model=model,
            cwd=cwd,
            template_name=template_name,
            session_id=session_id,
            is_resume=is_resume,
            add_parent_dir=add_parent_dir,
        )
        return invoke_copilot_sdk_sync(
            work_item=work_item,
            prompt=prompt,
            config=config,
            item_logger=item_logger,
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
        item_logger: ItemLogger | None = None,
        model: str | None = None,
        cwd: str | None = None,
        template_name: str | None = None,
        session_id: str | None = None,
        is_resume: bool = False,
        add_parent_dir: bool = False,
    ) -> CopilotResult:
        final_prompt = prompt or build_prompt_from_work_item(work_item, template_name or "beads-item")
        # Claude Code is read-only by design; deny_write is inherent.
        # session_id / is_resume are not supported by Claude Code CLI.
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
                encoding='utf-8',
                errors='replace',
                capture_output=True,
                timeout=timeout or DEFAULT_AGENT_TIMEOUT,
                cwd=cwd,
                env=env,
            )
        except subprocess.TimeoutExpired:
            return CopilotResult(
                work_item_id=work_item.id,
                success=False,
                output=None,
                error=f"Claude Code CLI timed out after {timeout or DEFAULT_AGENT_TIMEOUT}s",
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
        logger.warning("Unknown AI backend '%s', falling back to Copilot", name)
        return _BACKENDS["copilot"]()
    return factory()


def invoke_copilot(
    work_item: BeadsWorkItem,
    prompt: str | None = None,
    retry_config: RetryConfig | None = None,
    timeout: float | None = None,
    deny_write: bool = False,
    item_logger: ItemLogger | None = None,
    model: str | None = None,
    cwd: str | None = None,
    provider: str | None = None,
    template_name: str | None = None,
    session_id: str | None = None,
    is_resume: bool = False,
    add_parent_dir: bool = False,
) -> CopilotResult:
    """Invoke an AI backend to process a work item.

    Args:
        work_item: The beads work item to process.
        prompt: Optional pre-built prompt (if not provided, will build one from template).
        retry_config: Retry configuration (uses defaults if not provided).
        timeout: Maximum execution time in seconds (default: DEFAULT_AGENT_TIMEOUT).
        deny_write: If True, deny file write tools (for beads-only agents).
        item_logger: Optional item logger for file logging.
        model: Optional model name to use.
        cwd: Optional working directory for the process.
        provider: Optional backend provider override (e.g., 'copilot', 'claude-code').
        template_name: Optional prompt template name from assignment rules.
        session_id: Optional SDK session ID for resuming a timed-out session.
        is_resume: When True, the invocation is a resume after timeout.
        add_parent_dir: When True, pass ``--add-dir`` to give the agent
            visibility into the parent repository (for cleanup/gate agents).

    Returns:
        Result of the invocation.
    """
    backend = get_backend(provider)
    return backend.invoke(
        work_item=work_item,
        prompt=prompt,
        retry_config=retry_config,
        timeout=timeout,
        deny_write=deny_write,
        item_logger=item_logger,
        model=model,
        cwd=cwd,
        template_name=template_name,
        session_id=session_id,
        is_resume=is_resume,
        add_parent_dir=add_parent_dir,
    )
