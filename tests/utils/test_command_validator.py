"""Tests for pokepoke.utils.command_validator."""

from pokepoke.utils.command_validator import (
    extract_powershell_command,
    validate_and_rewrite_powershell_command,
    validate_and_rewrite_powershell_tool_args,
)


def test_extract_powershell_command_from_dict():
    assert extract_powershell_command({"command": "echo hi"}) == "echo hi"


def test_extract_powershell_command_from_str():
    assert extract_powershell_command("echo hi") == "echo hi"


def test_validate_denies_select_object_first_last():
    res = validate_and_rewrite_powershell_command("Get-Content foo | Select-Object -First 5")
    assert res.denied_reason is not None
    assert "Select-Object" in res.denied_reason


def test_rewrite_prefixes_set_location_when_required_cwd_and_no_cd():
    res = validate_and_rewrite_powershell_command(
        "git --no-pager status",
        required_cwd=r"C:\repo\worktrees\task-123",
    )
    assert res.denied_reason is None
    assert res.rewritten_command is not None
    assert "Set-Location" in res.rewritten_command
    assert "git --no-pager status" in res.rewritten_command


def test_rewrite_does_not_prefix_when_command_changes_location():
    res = validate_and_rewrite_powershell_command(
        "cd C:\repo; git status",
        required_cwd=r"C:\repo\worktrees\task-123",
    )
    assert res.denied_reason is None
    # It may still rewrite for pytest timeout, but should not add another Set-Location here.
    assert res.rewritten_command is None or "Set-Location" not in res.rewritten_command


def test_rewrite_injects_pytest_timeout_if_missing():
    res = validate_and_rewrite_powershell_command("pytest tests/test_one.py")
    assert res.denied_reason is None
    assert res.rewritten_command is not None
    assert "--timeout=300" in res.rewritten_command


def test_rewrite_does_not_duplicate_pytest_timeout():
    res = validate_and_rewrite_powershell_command("pytest tests/test_one.py --timeout=600")
    assert res.denied_reason is None
    assert res.rewritten_command is None


def test_validate_denies_bare_pytest():
    res = validate_and_rewrite_powershell_command("pytest")
    assert res.denied_reason is not None
    assert "Full-suite pytest" in res.denied_reason


def test_validate_denies_pytest_tests_dir_without_k():
    res = validate_and_rewrite_powershell_command("pytest tests/")
    assert res.denied_reason is not None
    assert "Full-suite pytest" in res.denied_reason


def test_validate_allows_pytest_with_k_filter():
    res = validate_and_rewrite_powershell_command("pytest tests/ -k \"fast\"")
    assert res.denied_reason is None
    # Should inject timeout
    assert res.rewritten_command is not None
    assert "--timeout=300" in res.rewritten_command


def test_tool_args_rewrite_returns_dict_with_updated_command():
    result = validate_and_rewrite_powershell_tool_args(
        {"command": "pytest tests/test_one.py"},
        required_cwd=r"C:\repo\worktrees\task-123",
    )

    assert result.denied_reason is None
    assert isinstance(result.rewritten_tool_args, dict)
    assert "Set-Location" in result.rewritten_tool_args["command"]
    assert "--timeout=300" in result.rewritten_tool_args["command"]
