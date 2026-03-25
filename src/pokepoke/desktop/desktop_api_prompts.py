"""Custom maintenance agent prompt file management.

Handles auto-creation of prompt files for custom maintenance agents
when they are configured via the desktop settings UI.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def generate_default_custom_agent_prompt(agent_name: str, description: str = "") -> str:
    """Generate a default prompt template for a custom maintenance agent.

    Args:
        agent_name: Name of the custom agent
        description: Optional description of the agent's purpose

    Returns:
        Default prompt template content
    """
    desc_section = f"\n{description}\n" if description else ""
    return f"""# {agent_name}
{desc_section}
## Instructions

This is a custom maintenance agent prompt. Replace this placeholder with your specific instructions.

## Context

You are working on the following beads work item:

**ID:** {{{{item_id}}}}
**Title:** {{{{title}}}}
**Type:** {{{{issue_type}}}}
**Priority:** {{{{priority}}}}

{{{{#description}}}}
**Description:**
{{{{description}}}}
{{{{/description}}}}

{{{{#labels}}}}
**Labels:** {{{{labels}}}}
{{{{/labels}}}}

## Available Template Variables

The following variables are available for use in this prompt:

- `{{{{item_id}}}}` - Beads work item ID
- `{{{{title}}}}` - Work item title
- `{{{{description}}}}` - Work item description
- `{{{{priority}}}}` - Priority level (0-4)
- `{{{{issue_type}}}}` - Type (bug, feature, task)
- `{{{{labels}}}}` - Comma-separated labels

## Guidelines

- Be specific about what this agent should accomplish
- Include examples when helpful
- Reference relevant files or patterns in the codebase
- Specify any quality gates or validation requirements
- Define success criteria clearly

## Example Task

Replace this with specific instructions for what this agent should do when invoked.
"""


def ensure_custom_agent_prompts(config: dict[str, Any]) -> None:
    """Ensure prompt files exist for all custom maintenance agents.

    Creates missing prompt files with default templates. Does not overwrite existing files.

    Args:
        config: Validated config dictionary
    """
    from pokepoke.config import _find_repo_root
    from pokepoke.prompts.prompts import PromptService

    maintenance = config.get("maintenance", {})
    agents = maintenance.get("agents", [])

    if not agents:
        return

    try:
        repo_root = _find_repo_root()
        prompts_dir = repo_root / ".pokepoke" / "prompts"
    except Exception as e:
        logger.warning(f"Could not find repo root to create custom agent prompts: {e}")
        return

    service = PromptService(prompts_dir=prompts_dir)

    for agent in agents:
        if not agent.get("custom", False):
            continue

        prompt_file = agent.get("prompt_file", "")
        if not prompt_file:
            continue

        prompt_name = prompt_file.replace(".md", "")

        try:
            service.load_prompt(prompt_name)
            logger.debug(f"Prompt file '{prompt_name}' already exists, skipping creation")
        except FileNotFoundError:
            agent_name = agent.get("name", prompt_name)
            description = agent.get("description", "")
            default_content = generate_default_custom_agent_prompt(agent_name, description)

            try:
                service.save_prompt(prompt_name, default_content)
                logger.info(f"Created default prompt file for custom agent '{agent_name}' at '{prompt_name}.md'")
            except Exception as e:
                logger.error(f"Failed to create prompt file for '{agent_name}': {e}")
