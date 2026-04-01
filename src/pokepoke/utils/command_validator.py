"""Command validation and rewrite utilities.

This module provides a defensive layer for tool command execution, especially
for PowerShell commands invoked by Copilot agents.

It is designed to run *before* tool execution (via the Copilot SDK
on_permission_request hook), so we can deny hang-prone patterns and apply safe
rewrites.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PowerShellValidationResult:
    """Outcome of validating a PowerShell command."""

    denied_reason: str | None
    rewritten_command: str | None

    @property
    def allowed(self) -> bool:
        return self.denied_reason is None


@dataclass(frozen=True, slots=True)
class ToolValidationResult:
    """Outcome of validating (and potentially rewriting) a tool request."""

    denied_reason: str | None
    rewritten_tool_args: object | None

    @property
    def allowed(self) -> bool:
        return self.denied_reason is None


_DEFAULT_PYTEST_TIMEOUT_SECONDS: Final[int] = 300


def extract_powershell_command(tool_args: object) -> str | None:
    """Extract a PowerShell command string from tool args."""
    if isinstance(tool_args, dict):
        command = tool_args.get("command") or tool_args.get("cmd") or tool_args.get("script")
        return command if isinstance(command, str) else None
    if isinstance(tool_args, str):
        return tool_args
    command = getattr(tool_args, "command", None)
    return command if isinstance(command, str) else None


def validate_and_rewrite_powershell_tool_args(
    tool_args: object,
    *,
    required_cwd: str | None = None,
    pytest_timeout_seconds: int = _DEFAULT_PYTEST_TIMEOUT_SECONDS,
) -> ToolValidationResult:
    """Validate and optionally rewrite tool args for the PowerShell tool."""
    command = extract_powershell_command(tool_args)
    if not command:
        return ToolValidationResult(denied_reason=None, rewritten_tool_args=None)

    result = validate_and_rewrite_powershell_command(
        command,
        required_cwd=required_cwd,
        pytest_timeout_seconds=pytest_timeout_seconds,
    )
    if result.denied_reason:
        return ToolValidationResult(denied_reason=result.denied_reason, rewritten_tool_args=None)

    if not result.rewritten_command:
        return ToolValidationResult(denied_reason=None, rewritten_tool_args=None)

    # Apply rewrite while preserving the original tool_args type.
    if isinstance(tool_args, dict):
        rewritten_args = {**tool_args, "command": result.rewritten_command}
        return ToolValidationResult(denied_reason=None, rewritten_tool_args=rewritten_args)
    if isinstance(tool_args, str):
        return ToolValidationResult(denied_reason=None, rewritten_tool_args=result.rewritten_command)

    # Unknown tool_args shape: don't attempt mutation here.
    return ToolValidationResult(denied_reason=None, rewritten_tool_args=None)


def validate_and_rewrite_powershell_command(
    command: str,
    *,
    required_cwd: str | None = None,
    pytest_timeout_seconds: int = _DEFAULT_PYTEST_TIMEOUT_SECONDS,
) -> PowerShellValidationResult:
    """Validate and optionally rewrite a PowerShell command.

    Args:
        command: The PowerShell command string.
        required_cwd: If provided, ensure the command executes from this
            directory by prefixing a Set-Location guard unless the command
            already changes location.
        pytest_timeout_seconds: Timeout value to inject for pytest invocations.

    Returns:
        A PowerShellValidationResult. If denied_reason is set, the command
        should be rejected. If rewritten_command is set, it should be used
        instead of the original.
    """
    if not command:
        return PowerShellValidationResult(denied_reason=None, rewritten_command=None)

    # Deny hang-prone Select-Object -First/-Last (known to deadlock pipelines).
    if _has_select_object_first_last(command):
        return PowerShellValidationResult(
            denied_reason=(
                "PowerShell Select-Object -First/-Last is forbidden because it can hang in pipelines. "
                "Use Get-Content -Head/-Tail, or collect output first then slice: "
                "$items = <cmd>; $items[0..9]."
            ),
            rewritten_command=None,
        )

    rewritten = command

    # Guardrail: ensure we are in the worktree directory.
    if required_cwd and not _changes_location(rewritten):
        rewritten = _prefix_set_location(rewritten, required_cwd)

    # Guardrail: inject pytest timeout if absent.
    rewritten = _inject_pytest_timeout(rewritten, pytest_timeout_seconds)

    # Deny wasteful full-suite pytest runs.
    if _is_full_suite_pytest(rewritten):
        return PowerShellValidationResult(
            denied_reason=(
                "Full-suite pytest runs are disallowed here because they frequently waste tool timeouts. "
                "Run a targeted test instead, e.g. `pytest tests/test_file.py --timeout=300` or "
                "`pytest -k \"pattern\" --timeout=300`."
            ),
            rewritten_command=None,
        )

    if rewritten != command:
        return PowerShellValidationResult(denied_reason=None, rewritten_command=rewritten)
    return PowerShellValidationResult(denied_reason=None, rewritten_command=None)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


_SELECT_OBJECT_RE: Final[re.Pattern[str]] = re.compile(r"(?i)\bselect(?:-object)?\b")
_FIRST_LAST_RE: Final[re.Pattern[str]] = re.compile(r"(?i)(?:^|\s)-(first|last)\b")


def _has_select_object_first_last(command: str) -> bool:
    return bool(_SELECT_OBJECT_RE.search(command) and _FIRST_LAST_RE.search(command))


_LOCATION_CHANGE_RE: Final[re.Pattern[str]] = re.compile(
    r"(?i)\b(?:cd|set-location|sl|push-location|pushd)\b"
)


def _changes_location(command: str) -> bool:
    """True if the command text appears to change directory."""
    return bool(_LOCATION_CHANGE_RE.search(command))


def _escape_pwsh_single_quotes(text: str) -> str:
    # PowerShell single-quoted string escaping: ''
    return text.replace("'", "''")


def _prefix_set_location(command: str, required_cwd: str) -> str:
    escaped = _escape_pwsh_single_quotes(required_cwd)
    return f"Set-Location -LiteralPath '{escaped}'; {command}"


# Match segments separated by common PowerShell command delimiters.
# We keep this intentionally simple and conservative.
_PYTEST_INVOKE_RE: Final[re.Pattern[str]] = re.compile(
    r"(?is)\b(?P<invoker>pytest|python\s+-m\s+pytest)\b(?P<args>[^\r\n;&]*)(?P<tail>(?:\s*&&|\s*;|\r?\n|$))"
)


def _inject_pytest_timeout(command: str, timeout_seconds: int) -> str:
    """Inject --timeout=N into pytest invocations that lack it."""

    def _rewrite(match: re.Match[str]) -> str:
        invoker = match.group("invoker")
        args = match.group("args") or ""
        tail = match.group("tail") or ""

        if re.search(r"(?i)\s--timeout(?:=|\s)\d+\b", args):
            return match.group(0)

        injected = f"{invoker}{args} --timeout={timeout_seconds}".rstrip()
        return f"{injected}{tail}"

    return _PYTEST_INVOKE_RE.sub(_rewrite, command)


# Full-suite patterns to deny.
# - bare `pytest`
# - `pytest tests/` or `python -m pytest tests/` without -k
_FULL_SUITE_PYTEST_RE: Final[re.Pattern[str]] = re.compile(
    r"(?is)\b(?:pytest|python\s+-m\s+pytest)\b(?P<args>[^\r\n;&]*)(?:\s*&&|\s*;|\r?\n|$)"
)


def _is_full_suite_pytest(command: str) -> bool:
    for m in _FULL_SUITE_PYTEST_RE.finditer(command):
        args = (m.group("args") or "").strip()
        if not args:
            return True

        # If -k is present, treat it as targeted enough.
        if re.search(r"(?i)(?:^|\s)-k\b", args):
            continue

        # If there are no positional arguments (only flags), it's effectively a full-suite run.
        tokens = re.findall(r"\S+", args)
        positional = [t for t in tokens if not t.startswith("-")]
        if not positional:
            return True

        # Deny directory-level run of tests/ (as requested).
        if re.search(r"(?i)(?:^|\s)tests(?:\\|/)?\s*(?:$|\s)", args):
            # Allow if an explicit test file under tests/ is provided.
            if re.search(r"(?i)tests(?:\\|/)[^\s]+\.py\b", args):
                continue
            return True

    return False
