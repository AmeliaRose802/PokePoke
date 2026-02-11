"""GitHub Copilot SDK integration.

This module provides SDK-based Copilot integration.
"""

import os
import subprocess
from pathlib import Path
from typing import Optional, TYPE_CHECKING

from .types import BeadsWorkItem, CopilotResult, RetryConfig
from .prompts import PromptService
from .copilot_sdk import invoke_copilot_sdk_sync

if TYPE_CHECKING:
    from .logging_utils import ItemLogger


def get_allowed_directories() -> list[str]:
    """Get the list of allowed directories for Copilot CLI access.
    
    Returns:
        List of absolute paths that Copilot is allowed to access
    """
    allowed = []
    
    # Always add current directory (worktree or main repo)
    current_dir = os.getcwd()
    allowed.append(current_dir)
    
    # Add main repo root if different from current
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--git-common-dir"],
            capture_output=True,
            text=True,
            encoding='utf-8',
            check=True
        )
        git_common_dir = result.stdout.strip()
        repo_root = str(Path(git_common_dir).parent.resolve())
        if repo_root != current_dir:
            allowed.append(repo_root)
    except (subprocess.CalledProcessError, Exception):
        pass  # If git command fails, just use current dir
    
    return allowed


def build_prompt_from_template(
    work_item: BeadsWorkItem,
    template_name: str = "beads-item"
) -> str:
    """Build a prompt from a template file with proper variable substitution.
    
    Args:
        work_item: The beads work item
        template_name: Name of the template file (without .md extension)
        
    Returns:
        Rendered prompt string with all variables substituted
    """
    service = PromptService()
    
    # Get allowed directories
    allowed_dirs = get_allowed_directories()
    
    # Build variables dictionary
    variables = {
        "item_id": work_item.id,
        "title": work_item.title,
        "description": work_item.description or "",
        "issue_type": work_item.issue_type,
        "priority": work_item.priority,
        "labels": ", ".join(work_item.labels) if work_item.labels else None,
        "allowed_directories": allowed_dirs,
    }
    
    return service.load_and_render(template_name, variables)


def build_prompt(work_item: BeadsWorkItem) -> str:
    """Build a prompt for Copilot CLI from a work item.
    
    Args:
        work_item: The beads work item.
        
    Returns:
        Formatted prompt string.
    """
    labels_section = ""
    if work_item.labels:
        labels_section = f"\n**Labels:** {', '.join(work_item.labels)}"
    
    return f"""You are working on a beads work item. Please complete the following task:

**Work Item ID:** {work_item.id}
**Title:** {work_item.title}
**Description:**
{work_item.description}

**Priority:** {work_item.priority}
**Type:** {work_item.issue_type}{labels_section}

Please implement this task according to the project guidelines and best practices. Make sure to:
1. Follow the coding standards
2. Add appropriate tests
3. Update documentation if needed
4. Commit your changes with a descriptive message

Work independently and let me know when complete."""


def invoke_copilot(
    work_item: BeadsWorkItem,
    prompt: Optional[str] = None,
    retry_config: Optional[RetryConfig] = None,
    timeout: Optional[float] = None,
    deny_write: bool = False,
    item_logger: Optional['ItemLogger'] = None,
    model: Optional[str] = None
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
        model=model
    )

