"""Tool command validation utilities for Copilot permission handling."""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

_SELECT_OBJECT_RE = re.compile(r"(?i)\bselect(?:-object)?\b")
_FIRST_LAST_RE = re.compile(r"(?i)(?:^|\s)-(first|last)\b")


def validate_powershell_command(command: str) -> str | None:
    """Validate a PowerShell command string. Returns error message if invalid."""
    if not command:
        return None
    if _SELECT_OBJECT_RE.search(command) and _FIRST_LAST_RE.search(command):
        return (
            "PowerShell Select-Object -First/-Last is forbidden because it can hang. "
            "Use Get-Content -Head/-Tail or array slicing instead."
        )
    return None


def validate_tool_request(tool_name: str | None, tool_args: Any) -> str | None:
    """Validate a tool request by name/args. Returns error message if invalid."""
    if not tool_name:
        return None
    if tool_name.lower() != "powershell":
        return None
    command = _extract_command(tool_args)
    if not command:
        return None
    return validate_powershell_command(command)


def _extract_command(tool_args: Any) -> str | None:
    """Extract a PowerShell command string from tool args."""
    if isinstance(tool_args, dict):
        command = tool_args.get("command") or tool_args.get("cmd") or tool_args.get("script")
        if isinstance(command, str):
            return command
        return None
    if isinstance(tool_args, str):
        return tool_args
    try:
        command = tool_args.command
    except AttributeError:
        return None
    if isinstance(command, str):
        return command
    return None
