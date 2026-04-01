"""Tool command validation utilities for Copilot permission handling.

This module keeps a small compatibility surface (validate_* functions) while
newer deny/rewrite logic lives in :mod:`pokepoke.utils.command_validator`.
"""

from __future__ import annotations

from typing import Any

from pokepoke.utils.command_validator import (
    extract_powershell_command,
    validate_and_rewrite_powershell_command,
    validate_and_rewrite_powershell_tool_args,
)


def validate_powershell_command(command: str) -> str | None:
    """Validate a PowerShell command string. Returns error message if invalid."""
    return validate_and_rewrite_powershell_command(command).denied_reason


def validate_tool_request(tool_name: str | None, tool_args: Any) -> str | None:
    """Validate a tool request by name/args. Returns error message if invalid."""
    if not tool_name or tool_name.lower() != "powershell":
        return None
    command = _extract_command(tool_args)
    if not command:
        return None
    return validate_powershell_command(command)


def validate_and_rewrite_powershell_args(
    tool_args: object,
    *,
    required_cwd: str | None = None,
) -> tuple[str | None, object | None]:
    """Validate and potentially rewrite PowerShell tool args.

    Returns:
        (denied_reason, rewritten_tool_args)
    """
    result = validate_and_rewrite_powershell_tool_args(tool_args, required_cwd=required_cwd)
    return result.denied_reason, result.rewritten_tool_args


def _extract_command(tool_args: Any) -> str | None:
    """Extract a PowerShell command string from tool args."""
    return extract_powershell_command(tool_args)
