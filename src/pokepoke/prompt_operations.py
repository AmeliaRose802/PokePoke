"""Prompt template operations for desktop API."""

from typing import Any


def list_prompts() -> list[dict[str, Any]]:
    """List all prompt templates with override metadata.

    Returns a list of dicts with keys: name, is_override, has_builtin, source.
    """
    from pokepoke.prompts import get_prompt_service

    service = get_prompt_service()
    return service.list_prompts()


def get_prompt(name: str) -> dict[str, Any]:
    """Get a prompt template's content and metadata.

    Args:
        name: Template name (without .md extension).

    Returns:
        Dict with name, content, is_override, has_builtin, source,
        and template_variables.
    """
    from pokepoke.prompts import get_prompt_service

    service = get_prompt_service()
    return service.get_prompt_metadata(name)


def save_prompt(name: str, content: str) -> dict[str, Any]:
    """Save a prompt override to the user prompts directory.

    Args:
        name: Template name (without .md extension).
        content: New template content.

    Returns:
        Dict with path and saved status.
    """
    from pokepoke.prompts import get_prompt_service

    service = get_prompt_service()
    return service.save_prompt(name, content)


def reset_prompt(name: str) -> dict[str, Any]:
    """Reset a prompt to the built-in default by removing the user override.

    Args:
        name: Template name (without .md extension).

    Returns:
        Dict with reset and had_override status.
    """
    from pokepoke.prompts import get_prompt_service

    service = get_prompt_service()
    return service.reset_prompt(name)