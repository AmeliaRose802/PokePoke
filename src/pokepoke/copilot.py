"""GitHub Copilot SDK integration.

This module provides SDK-based Copilot integration.
"""

from typing import TYPE_CHECKING

from .ai_backends import get_backend
from .types import BeadsWorkItem, CopilotResult, RetryConfig

if TYPE_CHECKING:
    from .logging_utils import ItemLogger


def invoke_copilot(
    work_item: BeadsWorkItem,
    prompt: str | None = None,
    retry_config: RetryConfig | None = None,
    timeout: float | None = None,
    deny_write: bool = False,
    item_logger: 'ItemLogger | None' = None,
    model: str | None = None,
    cwd: str | None = None,
    provider: str | None = None,
) -> CopilotResult:
    """Invoke GitHub Copilot using SDK.
    
    Args:
        work_item: The beads work item to process.
        prompt: Optional pre-built prompt (if not provided, will build one from template).
        retry_config: Retry configuration (uses defaults if not provided).
        timeout: Maximum execution time in seconds (default: 7200 = 2 hours).
        deny_write: If True, deny file write tools (for beads-only agents).
        item_logger: Optional item logger for file logging.
        model: Optional model name to use (e.g., 'gpt-5.1-codex', defaults to 'claude-opus-4.6').
        cwd: Optional working directory for the Copilot process (for thread-safe worktree isolation).
        provider: Optional backend provider override (e.g., 'copilot', 'claude-code').
        
    Returns:
        Result of the Copilot invocation.
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
    )

