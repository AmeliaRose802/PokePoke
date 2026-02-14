"""GitHub Copilot SDK integration.

This module provides SDK-based Copilot integration.
"""

from typing import Optional, TYPE_CHECKING

from .types import BeadsWorkItem, CopilotResult, RetryConfig
from .copilot_sdk import invoke_copilot_sdk_sync

if TYPE_CHECKING:
    from .logging_utils import ItemLogger


def invoke_copilot(
    work_item: BeadsWorkItem,
    prompt: Optional[str] = None,
    retry_config: Optional[RetryConfig] = None,
    timeout: Optional[float] = None,
    deny_write: bool = False,
    item_logger: Optional['ItemLogger'] = None,
    model: Optional[str] = None,
    cwd: Optional[str] = None
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
        
    Returns:
        Result of the Copilot invocation.
    """
    return invoke_copilot_sdk_sync(
        work_item=work_item,
        prompt=prompt,
        retry_config=retry_config,
        timeout=timeout,
        deny_write=deny_write,
        item_logger=item_logger,
        model=model,
        cwd=cwd
    )

