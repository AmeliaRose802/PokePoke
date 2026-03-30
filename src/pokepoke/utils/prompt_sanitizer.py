"""Sanitization utilities for user-provided content entering AI prompts.

Mitigates prompt injection attacks by sanitizing work item fields before
they are interpolated into prompt templates.
"""

import re

# Maximum lengths for different field types
MAX_DESCRIPTION_LENGTH = 4000
MAX_SHORT_FIELD_LENGTH = 200

# Characters that could be used for prompt manipulation
_CONTROL_CHAR_RE = re.compile(
    r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]'
)

# Template syntax that could interfere with the Mustache-like engine
_TEMPLATE_INJECTION_RE = re.compile(r'\{\{[^}]*\}\}')


def _strip_control_characters(text: str) -> str:
    """Remove ASCII/Unicode control characters (preserving newlines, tabs, CR)."""
    return _CONTROL_CHAR_RE.sub('', text)


def _neutralize_template_syntax(text: str) -> str:
    """Replace ``{{ }}`` sequences so they cannot inject template variables."""
    return _TEMPLATE_INJECTION_RE.sub(
        lambda m: m.group(0).replace('{{', '{ {').replace('}}', '} }'),
        text,
    )


def _enforce_length(text: str, max_length: int) -> str:
    """Truncate text to *max_length* characters, adding an ellipsis marker."""
    if len(text) <= max_length:
        return text
    return text[:max_length] + "\n[...truncated...]"


def _wrap_with_delimiters(text: str, field_name: str) -> str:
    """Wrap user-provided content in XML-style boundary markers."""
    tag = f"user_{field_name}"
    return f"<{tag}>\n{text}\n</{tag}>"


def sanitize_prompt_input(
    text: str | None,
    *,
    field_name: str = "content",
    max_length: int = MAX_DESCRIPTION_LENGTH,
    wrap: bool = True,
) -> str:
    """Sanitize a user-provided string before inserting it into an AI prompt.

    Steps applied (in order):
    1. Strip control characters (keep newlines/tabs/CR).
    2. Neutralize ``{{ }}`` template syntax to prevent variable injection.
    3. Enforce a maximum character length.
    4. Optionally wrap in ``<user_*>`` delimiters for clear content boundaries.

    Args:
        text: Raw input string (``None`` is treated as empty).
        field_name: Identifier used in the delimiter tags (e.g. ``"description"``).
        max_length: Maximum allowed character length.
        wrap: Whether to wrap the output in XML-style boundary tags.

    Returns:
        The sanitized (and optionally wrapped) string.
    """
    if not text:
        return ""

    result = _strip_control_characters(text)
    result = _neutralize_template_syntax(result)
    result = _enforce_length(result, max_length)

    if wrap:
        result = _wrap_with_delimiters(result, field_name)

    return result


def sanitize_short(text: str | None, field_name: str = "content") -> str:
    """Shortcut: sanitize a short field (title, labels) — no wrapping."""
    return sanitize_prompt_input(
        text, field_name=field_name, max_length=MAX_SHORT_FIELD_LENGTH, wrap=False,
    )
