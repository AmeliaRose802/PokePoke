"""Tests for tool command validation utilities."""

from pokepoke.utils.tool_command_validator import (
    validate_powershell_command,
    validate_tool_request,
)


def test_validate_powershell_command_blocks_select_object():
    msg = validate_powershell_command("Get-Content foo | Select-Object -First 5")
    assert msg is not None
    assert "Select-Object" in msg


def test_validate_powershell_command_allows_safe_commands():
    assert validate_powershell_command("Get-Content foo -Head 5") is None
    assert validate_powershell_command("Get-Content foo -Tail 5") is None


def test_validate_tool_request_ignores_non_powershell():
    assert validate_tool_request("read_file", {"path": "foo"}) is None


def test_validate_tool_request_blocks_powershell_command():
    msg = validate_tool_request("powershell", {"command": "Select -Last 2"})
    assert msg is not None


def test_validate_tool_request_with_string_args():
    msg = validate_tool_request("powershell", "Select -First 1")
    assert msg is not None


def test_validate_tool_request_with_command_attr():
    class CommandObj:
        command = "Select -First 1"

    msg = validate_tool_request("powershell", CommandObj())
    assert msg is not None


def test_validate_tool_request_missing_command_returns_none():
    assert validate_tool_request("powershell", {"command": None}) is None
    assert validate_tool_request("powershell", {}) is None


def test_validate_powershell_command_empty_returns_none():
    assert validate_powershell_command("") is None
