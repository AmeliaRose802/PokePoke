"""Unit tests for git_operations module."""

import subprocess
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from pokepoke.git.git_operations import (
    build_handoff_context,
    check_main_repo_ready_for_merge,
    commit_all_changes,
    execute_merge_sequence,
    get_main_repo_root,
    handle_beads_auto_commit,
    has_commits_ahead,
    has_uncommitted_changes,
    is_worktree_clean,
    validate_post_merge,
    verify_main_repo_clean,
)


class TestVerifyMainRepoClean:
    """Test verify_main_repo_clean function."""

    @patch('pokepoke.git.git_helpers.subprocess.run')
    def test_clean_repo(self, mock_run: Mock) -> None:
        """Test clean repository with no changes."""
        mock_run.return_value = Mock(
            stdout="",
            returncode=0
        )

        is_clean, output, non_beads_changes = verify_main_repo_clean()

        assert is_clean is True
        assert output == ""
        assert non_beads_changes == []
        mock_run.assert_called_once_with(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            check=True,
            timeout=10,
            cwd=None
        )

    @patch('pokepoke.git.git_helpers.subprocess.run')
    def test_only_beads_changes(self, mock_run: Mock) -> None:
        """Test repository with only beads changes."""
        mock_run.return_value = Mock(
            stdout=" M .beads/issues.jsonl\n M .beads/beads.db",
            returncode=0
        )

        is_clean, output, non_beads_changes = verify_main_repo_clean()

        assert is_clean is True
        assert ".beads/" in output
        assert non_beads_changes == []

    @patch('pokepoke.git.git_helpers.subprocess.run')
    def test_non_beads_changes(self, mock_run: Mock) -> None:
        """Test repository with non-beads changes."""
        mock_run.return_value = Mock(
            stdout=" M src/pokepoke/orchestrator.py\n M tests/test_orchestrator.py",
            returncode=0
        )

        is_clean, output, non_beads_changes = verify_main_repo_clean()

        assert is_clean is False
        assert "orchestrator.py" in output
        assert len(non_beads_changes) == 2
        assert "orchestrator.py" in non_beads_changes[0]
        assert "test_orchestrator.py" in non_beads_changes[1]

    @patch('pokepoke.git.git_helpers.subprocess.run')
    def test_mixed_changes(self, mock_run: Mock) -> None:
        """Test repository with both beads and non-beads changes."""
        mock_run.return_value = Mock(
            stdout=" M .beads/issues.jsonl\n M src/pokepoke/orchestrator.py",
            returncode=0
        )

        is_clean, _output, non_beads_changes = verify_main_repo_clean()

        assert is_clean is False
        assert len(non_beads_changes) == 1
        assert non_beads_changes[0] == " M src/pokepoke/orchestrator.py"

    @patch('pokepoke.git.git_helpers.subprocess.run')
    def test_git_error(self, mock_run: Mock) -> None:
        """Test error handling when git command fails."""
        mock_run.side_effect = subprocess.CalledProcessError(1, "git status")

        with pytest.raises(RuntimeError, match="Error checking git status"):
            verify_main_repo_clean()

    @patch('pokepoke.git.git_helpers.subprocess.run')
    def test_empty_lines_filtered(self, mock_run: Mock) -> None:
        """Test that empty lines are filtered out."""
        mock_run.return_value = Mock(
            stdout=" M src/file.py\n\n M other.py",
            returncode=0
        )

        is_clean, _output, non_beads_changes = verify_main_repo_clean()

        assert is_clean is False
        assert len(non_beads_changes) == 2


class TestHandleBeadsAutoCommit:
    """Test handle_beads_auto_commit function."""

    @patch('pokepoke.git.git_operations.run_git')
    def test_successful_commit(self, mock_run_git: Mock) -> None:
        """Test successful beads auto-commit."""
        mock_run_git.return_value = Mock(returncode=0)

        handle_beads_auto_commit()

        assert mock_run_git.call_count == 2
        mock_run_git.assert_any_call(["git", "add", ".beads/"], timeout=10, cwd=None)
        mock_run_git.assert_any_call(
            ["git", "commit", "-m", "chore: sync beads before worktree merge"],
            timeout=300,
            cwd=None,
        )

    @patch('pokepoke.git.git_operations.subprocess.run')
    def test_commit_failure(self, mock_run: Mock) -> None:
        """Test failure during beads commit."""
        mock_run.side_effect = [
            Mock(returncode=0),  # git add succeeds
            subprocess.CalledProcessError(1, "git commit")  # git commit fails
        ]

        with pytest.raises(RuntimeError, match="Failed to commit beads changes"):
            handle_beads_auto_commit()

    @patch('pokepoke.git.git_operations.subprocess.run')
    def test_add_failure(self, mock_run: Mock) -> None:
        """Test failure during git add."""
        mock_run.side_effect = subprocess.CalledProcessError(1, "git add")

        with pytest.raises(RuntimeError, match="Failed to commit beads changes"):
            handle_beads_auto_commit()


class TestCheckMainRepoReadyForMerge:
    """Test check_main_repo_ready_for_merge function."""

    @patch('pokepoke.git.git_operations.handle_beads_auto_commit')
    @patch('pokepoke.git.git_operations.verify_main_repo_clean')
    def test_clean_repo(self, mock_verify: Mock, mock_handle: Mock) -> None:
        """Test clean repository ready for merge."""
        mock_verify.return_value = (True, "", [])

        is_ready, error_msg = check_main_repo_ready_for_merge()

        assert is_ready is True
        assert error_msg == ""
        mock_handle.assert_not_called()

    @patch('pokepoke.git.git_operations.handle_beads_auto_commit')
    @patch('pokepoke.git.git_operations.verify_main_repo_clean')
    def test_only_beads_changes_auto_commit(
        self,
        mock_verify: Mock,
        mock_handle: Mock
    ) -> None:
        """Test beads-only changes trigger auto-commit."""
        mock_verify.return_value = (True, " M .beads/issues.jsonl", [])

        is_ready, error_msg = check_main_repo_ready_for_merge()

        assert is_ready is True
        assert error_msg == ""
        mock_handle.assert_called_once()

    @patch('pokepoke.git.git_operations.handle_beads_auto_commit')
    @patch('pokepoke.git.git_operations.verify_main_repo_clean')
    def test_non_beads_changes_not_ready(
        self,
        mock_verify: Mock,
        mock_handle: Mock
    ) -> None:
        """Test non-beads changes prevent merge."""
        mock_verify.return_value = (
            False,
            " M src/file.py",
            [" M src/file.py"]
        )

        is_ready, error_msg = check_main_repo_ready_for_merge()

        assert is_ready is False
        assert "uncommitted non-beads changes" in error_msg
        assert "src/file.py" in error_msg
        mock_handle.assert_not_called()

    @patch('pokepoke.git.git_operations.handle_beads_auto_commit')
    @patch('pokepoke.git.git_operations.verify_main_repo_clean')
    def test_auto_commit_failure(
        self,
        mock_verify: Mock,
        mock_handle: Mock
    ) -> None:
        """Test auto-commit failure is caught."""
        mock_verify.return_value = (True, " M .beads/issues.jsonl", [])
        mock_handle.side_effect = RuntimeError("Commit failed")

        is_ready, error_msg = check_main_repo_ready_for_merge()

        assert is_ready is False
        assert "Error checking main repo status" in error_msg
        assert "Commit failed" in error_msg

    @patch('pokepoke.git.git_operations.verify_main_repo_clean')
    def test_verify_exception(self, mock_verify: Mock) -> None:
        """Test exception during verification."""
        mock_verify.side_effect = RuntimeError("Git error")

        is_ready, error_msg = check_main_repo_ready_for_merge()

        assert is_ready is False
        assert "Error checking main repo status" in error_msg
        assert "Git error" in error_msg


class TestHasUncommittedChanges:
    """Test has_uncommitted_changes function."""

    @patch('pokepoke.git.git_helpers.subprocess.run')
    def test_no_changes(self, mock_run: Mock) -> None:
        """Test repository with no uncommitted changes."""
        mock_run.return_value = Mock(
            stdout="",
            returncode=0
        )

        result = has_uncommitted_changes()

        assert result is False
        mock_run.assert_called_once_with(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            check=True,
            timeout=10,
            cwd=None
        )

    @patch('pokepoke.git.git_helpers.subprocess.run')
    def test_has_changes(self, mock_run: Mock) -> None:
        """Test repository with uncommitted changes."""
        mock_run.return_value = Mock(
            stdout=" M src/file.py\n M tests/test.py",
            returncode=0
        )

        result = has_uncommitted_changes()

        assert result is True

    @patch('pokepoke.git.git_helpers.subprocess.run')
    def test_whitespace_only(self, mock_run: Mock) -> None:
        """Test output with only whitespace is treated as no changes."""
        mock_run.return_value = Mock(
            stdout="   \n  \n",
            returncode=0
        )

        result = has_uncommitted_changes()

        assert result is False

    @patch('pokepoke.git.git_helpers.subprocess.run')
    def test_git_error(self, mock_run: Mock) -> None:
        """Test error handling when git command fails.

        When git fails, assume dirty to prevent data loss during merge operations.
        """
        mock_run.side_effect = subprocess.CalledProcessError(1, "git status")

        result = has_uncommitted_changes()

        assert result is True  # Assume dirty when git fails to prevent data loss

    @patch('pokepoke.git.git_helpers.sleep_with_backoff')
    @patch('pokepoke.git.git_helpers.subprocess.run')
    def test_git_timeout(self, mock_run: Mock, mock_sleep: Mock) -> None:
        """Test error handling when git command times out.

        When git times out, assume dirty to prevent data loss during merge operations.
        """
        mock_run.side_effect = subprocess.TimeoutExpired("git status", 10)

        result = has_uncommitted_changes()

        assert result is True  # Assume dirty when git times out to prevent data loss
        assert mock_run.call_count == 3  # retries 3 times before giving up


class TestCommitAllChanges:
    """Test commit_all_changes function."""

    @patch('pokepoke.git.git_operations.run_git')
    def test_successful_commit(self, mock_run_git: Mock) -> None:
        """Test successful commit with all changes."""
        mock_run_git.return_value = Mock(returncode=0, stderr="")

        success, error_msg = commit_all_changes("Test commit")

        assert success is True
        assert error_msg == ""
        assert mock_run_git.call_count == 2
        mock_run_git.assert_any_call(
            ["git", "add", "-A"],
            timeout=240,
            cwd=None,
        )
        mock_run_git.assert_any_call(
            ["git", "commit", "-m", "Test commit"],
            timeout=300,
            cwd=None,
            check=False,
        )

    @patch('pokepoke.git.git_operations.subprocess.run')
    def test_commit_with_default_message(self, mock_run: Mock) -> None:
        """Test commit with default message."""
        mock_run.return_value = Mock(returncode=0, stderr="")

        success, _error_msg = commit_all_changes()

        assert success is True
        # Check default message was used
        calls = mock_run.call_args_list
        assert calls[1][0][0] == ["git", "commit", "-m", "Auto-commit by PokePoke"]

    @patch('pokepoke.git.git_operations.subprocess.run')
    def test_commit_failure_with_stderr(self, mock_run: Mock) -> None:
        """Test commit failure with error details in stderr."""
        mock_run.side_effect = [
            Mock(returncode=0),  # git add succeeds
            Mock(
                returncode=1,
                stderr="error: pre-commit hook failed\nTest failed\nhint: use --no-verify"
            )
        ]

        success, error_msg = commit_all_changes("Test commit")

        assert success is False
        assert "error: pre-commit hook failed" in error_msg
        assert "Test failed" in error_msg
        assert "hint:" not in error_msg  # Hints should be filtered

    @patch('pokepoke.git.git_operations.subprocess.run')
    def test_commit_failure_no_stderr(self, mock_run: Mock) -> None:
        """Test commit failure with no error details."""
        mock_run.side_effect = [
            Mock(returncode=0),  # git add succeeds
            Mock(returncode=1, stderr="")
        ]

        success, error_msg = commit_all_changes("Test commit")

        assert success is False
        assert "Commit failed" in error_msg

    @patch('pokepoke.git.git_operations.subprocess.run')
    def test_add_stage_exception(self, mock_run: Mock) -> None:
        """Test exception during git add stage."""
        mock_run.side_effect = subprocess.CalledProcessError(
            1,
            "git add",
            stderr="Permission denied"
        )

        success, error_msg = commit_all_changes("Test commit")

        assert success is False
        assert "Commit error" in error_msg
        assert "Permission denied" in error_msg

    @patch('pokepoke.git.git_operations.subprocess.run')
    def test_commit_stage_exception(self, mock_run: Mock) -> None:
        """Test exception during commit stage."""
        mock_run.side_effect = [
            Mock(returncode=0),  # git add succeeds
            subprocess.CalledProcessError(1, "git commit", stderr="Disk full")
        ]

        success, error_msg = commit_all_changes("Test commit")

        assert success is False
        assert "Commit error" in error_msg
        assert "Disk full" in error_msg

    @patch('pokepoke.git.git_operations.subprocess.run')
    def test_error_line_limit(self, mock_run: Mock) -> None:
        """Test that error messages are limited to 5 lines."""
        long_stderr = "\n".join([f"error line {i}" for i in range(10)])
        mock_run.side_effect = [
            Mock(returncode=0),  # git add succeeds
            Mock(returncode=1, stderr=long_stderr)
        ]

        success, error_msg = commit_all_changes("Test commit")

        assert success is False
        # Should only have first 5 error lines
        error_lines = error_msg.split('\n')
        assert len(error_lines) <= 6  # 5 errors + potential join artifacts


    @patch('pokepoke.git.git_operations.subprocess.run')
    def test_tracked_only_uses_git_add_u(self, mock_run: Mock) -> None:
        """Test that tracked_only=True uses git add -u instead of -A."""
        mock_run.return_value = Mock(returncode=0, stderr="")

        success, error_msg = commit_all_changes("Test commit", tracked_only=True)

        assert success is True
        assert error_msg == ""
        mock_run.assert_any_call(
            ["git", "add", "-u"],
            check=True,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=240,
            cwd=None
        )

    @patch('pokepoke.git.git_operations.subprocess.run')
    def test_default_uses_git_add_all(self, mock_run: Mock) -> None:
        """Test that default (tracked_only=False) uses git add -A."""
        mock_run.return_value = Mock(returncode=0, stderr="")

        success, _error_msg = commit_all_changes("Test commit")

        assert success is True
        mock_run.assert_any_call(
            ["git", "add", "-A"],
            check=True,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=240,
            cwd=None
        )


class TestExecuteMergeSequence:
    """Tests for execute_merge_sequence checkout-and-merge."""

    @patch('pokepoke.git.git_operations.subprocess.run')
    def test_checkout_and_merge_success(
        self,
        mock_run: Mock,
    ) -> None:
        """Successful checkout + merge returns success."""

        def side_effect(cmd, **kwargs):
            if cmd[:2] == ["git", "checkout"]:
                return Mock(returncode=0)
            if cmd[:2] == ["git", "merge"]:
                return Mock(returncode=0)
            raise AssertionError(f"Unexpected command: {cmd}")

        mock_run.side_effect = side_effect

        success, message, unmerged = execute_merge_sequence("feature/foo", "main")

        assert success is True
        assert message == ""
        assert unmerged == []

    @patch('pokepoke.git.git_operations.subprocess.run')
    def test_checkout_failure_returns_error(
        self,
        mock_run: Mock,
    ) -> None:
        """Checkout failure returns an error without attempting merge."""

        def side_effect(cmd, **kwargs):
            if cmd[:2] == ["git", "checkout"]:
                raise subprocess.CalledProcessError(1, cmd, stderr="checkout error")
            raise AssertionError(f"Unexpected command: {cmd}")

        mock_run.side_effect = side_effect

        success, message, unmerged = execute_merge_sequence("feature/foo", "main")

        assert success is False
        assert "Failed to checkout" in message
        assert unmerged == []


class TestBuildHandoffContext:
    """Test build_handoff_context function."""

    @patch('pokepoke.git.git_operations.get_default_branch', return_value='master')
    @patch('pokepoke.prompts.handoff_context.run_git')
    def test_returns_full_context_with_all_sections(
        self, mock_run: Mock, mock_branch: Mock
    ) -> None:
        """Test that handoff context includes changed files, diff stat, commits, and diff content."""
        fake_diff = "diff --git a/src/foo.py b/src/foo.py\n--- a/src/foo.py\n+++ b/src/foo.py\n@@ -1 +1 @@\n-old\n+new\n"

        def side_effect(cmd: list[str], **kwargs: object) -> Mock:
            if "diff" in cmd and "--name-status" in cmd:
                return Mock(returncode=0, stdout="M\tsrc/foo.py\nA\tsrc/bar.py\n")
            if "diff" in cmd and "--stat" in cmd:
                return Mock(returncode=0, stdout=" src/foo.py | 10 ++++------\n src/bar.py |  5 +++++\n 2 files changed, 9 insertions(+), 6 deletions(-)\n")
            if "log" in cmd and "--oneline" in cmd:
                return Mock(returncode=0, stdout="abc1234 feat: add bar module\ndef5678 fix: update foo logic\n")
            if "diff" in cmd:
                return Mock(returncode=0, stdout=fake_diff)
            return Mock(returncode=1, stdout="")

        mock_run.side_effect = side_effect

        result = build_handoff_context(cwd="/tmp/worktree")

        assert "## Work Agent Handoff Context" in result
        assert "### Changed Files" in result
        assert "M\tsrc/foo.py" in result
        assert "A\tsrc/bar.py" in result
        assert "### Diff Summary" in result
        assert "2 files changed" in result
        assert "### Commit History" in result
        assert "abc1234 feat: add bar module" in result
        assert "### Diff Content" in result
        assert "```diff" in result
        assert "-old" in result
        assert "+new" in result
        assert "Start your verification" in result

    @patch('pokepoke.git.git_operations.get_default_branch', return_value='master')
    @patch('pokepoke.prompts.handoff_context.run_git')
    def test_returns_empty_when_no_changes(
        self, mock_run: Mock, mock_branch: Mock
    ) -> None:
        """Test that handoff returns empty string when no files changed."""
        mock_run.return_value = Mock(returncode=0, stdout="")

        result = build_handoff_context(cwd="/tmp/worktree")

        assert result == ""

    @patch('pokepoke.git.git_operations.get_default_branch', return_value='master')
    @patch('pokepoke.prompts.handoff_context.run_git')
    def test_returns_empty_on_git_failure(
        self, mock_run: Mock, mock_branch: Mock
    ) -> None:
        """Test that handoff returns empty string when git commands fail."""
        mock_run.return_value = Mock(returncode=1, stdout="")

        result = build_handoff_context(cwd="/tmp/worktree")

        assert result == ""

    @patch('pokepoke.git.git_operations.get_default_branch', return_value='master')
    @patch('pokepoke.prompts.handoff_context.run_git')
    def test_handles_timeout(
        self, mock_run: Mock, mock_branch: Mock
    ) -> None:
        """Test graceful handling of subprocess timeout."""
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="git", timeout=15)

        result = build_handoff_context(cwd="/tmp/worktree")

        assert result == ""

    @patch('pokepoke.git.git_operations.get_default_branch', return_value='master')
    @patch('pokepoke.prompts.handoff_context.run_git')
    def test_omits_missing_sections(
        self, mock_run: Mock, mock_branch: Mock
    ) -> None:
        """Test that missing sections (stat, log, diff content) are omitted gracefully."""
        def side_effect(cmd: list[str], **kwargs: object) -> Mock:
            if "diff" in cmd and "--name-status" in cmd:
                return Mock(returncode=0, stdout="M\tsrc/only.py\n")
            # stat, log, and bare diff all fail
            return Mock(returncode=1, stdout="")

        mock_run.side_effect = side_effect

        result = build_handoff_context(cwd="/tmp/worktree")

        assert "### Changed Files" in result
        assert "M\tsrc/only.py" in result
        assert "### Diff Summary" not in result
        assert "### Commit History" not in result
        assert "### Diff Content" not in result

    @patch('pokepoke.git.git_operations.get_default_branch', return_value='master')
    @patch('pokepoke.prompts.handoff_context.run_git')
    def test_passes_cwd_to_subprocess(
        self, mock_run: Mock, mock_branch: Mock
    ) -> None:
        """Test that cwd is passed to all subprocess calls."""
        def side_effect(cmd: list[str], **kwargs: object) -> Mock:
            if "diff" in cmd and "--name-status" in cmd:
                return Mock(returncode=0, stdout="M\tsrc/a.py\n")
            if "diff" in cmd and "--stat" in cmd:
                return Mock(returncode=0, stdout=" src/a.py | 1 +\n")
            if "log" in cmd:
                return Mock(returncode=0, stdout="abc fix\n")
            if "diff" in cmd:
                return Mock(returncode=0, stdout="diff --git a/src/a.py\n")
            return Mock(returncode=0, stdout="")

        mock_run.side_effect = side_effect

        build_handoff_context(cwd="/my/worktree")

        for call in mock_run.call_args_list:
            assert call.kwargs.get("cwd") == "/my/worktree"

    @patch('pokepoke.git.git_operations.get_default_branch', return_value='master')
    @patch('pokepoke.prompts.handoff_context.run_git')
    def test_truncates_large_diff(
        self, mock_run: Mock, mock_branch: Mock
    ) -> None:
        """Test that very large diffs are truncated with a note."""
        large_diff = "x" * 30_000

        def side_effect(cmd: list[str], **kwargs: object) -> Mock:
            if "diff" in cmd and "--name-status" in cmd:
                return Mock(returncode=0, stdout="M\tsrc/big.py\n")
            if "diff" in cmd and "--stat" in cmd:
                return Mock(returncode=1, stdout="")
            if "log" in cmd:
                return Mock(returncode=1, stdout="")
            if "diff" in cmd:
                return Mock(returncode=0, stdout=large_diff)
            return Mock(returncode=1, stdout="")

        mock_run.side_effect = side_effect

        result = build_handoff_context(cwd="/tmp/worktree")

        assert "### Diff Content" in result
        assert "diff truncated" in result
        # Verify the content was actually truncated (not the full 30k)
        assert len(result) < 25_000


class TestHandleBeadsAutoCommitTimeout:
    """Test handle_beads_auto_commit TimeoutExpired branch."""

    @patch('pokepoke.git.git_operations.subprocess.run')
    def test_commit_timeout_raises_runtime_error(self, mock_run: Mock) -> None:
        """Timeout during commit raises RuntimeError."""
        mock_run.side_effect = [
            Mock(returncode=0),  # git add succeeds
            subprocess.TimeoutExpired("git commit", 300),
        ]
        with pytest.raises(RuntimeError, match="timed out"):
            handle_beads_auto_commit()


class TestCommitAllChangesTimeout:
    """Test commit_all_changes TimeoutExpired branch."""

    @patch('pokepoke.git.git_operations.subprocess.run')
    def test_timeout_during_commit_returns_error(self, mock_run: Mock) -> None:
        """TimeoutExpired during commit returns failure with message."""
        mock_run.side_effect = [
            Mock(returncode=0),  # git add succeeds
            subprocess.TimeoutExpired("git commit", 300),
        ]
        success, message = commit_all_changes("Test")
        assert success is False
        assert "timed out" in message


class TestGetMainRepoRoot:
    """Tests for get_main_repo_root."""

    @patch('pokepoke.git.git_operations.subprocess.run')
    def test_returns_parent_of_git_common_dir(self, mock_run: Mock) -> None:
        mock_run.return_value = Mock(stdout="/repo/.git\n", returncode=0)
        root = get_main_repo_root()
        assert root == Path("/repo/.git").parent

    @patch('pokepoke.git.git_operations.subprocess.run')
    def test_raises_runtime_error_outside_repo(self, mock_run: Mock) -> None:
        mock_run.side_effect = subprocess.CalledProcessError(128, "git")
        with pytest.raises(RuntimeError, match="Not in a git repository"):
            get_main_repo_root()


class TestSanitizeBranchName:
    """Tests for sanitize_branch_name."""

    def test_replaces_spaces(self) -> None:
        from pokepoke.git.git_operations import sanitize_branch_name
        assert sanitize_branch_name("my feature") == "my-feature"

    def test_replaces_special_chars(self) -> None:
        from pokepoke.git.git_operations import sanitize_branch_name
        result = sanitize_branch_name("fix: thing")
        # Colon and space are replaced with hyphens, collapsed to one
        assert "fix" in result
        assert "thing" in result
        assert ":" not in result

    def test_collapses_dots(self) -> None:
        from pokepoke.git.git_operations import sanitize_branch_name
        assert sanitize_branch_name("my...branch") == "my.branch"

    def test_strips_leading_trailing(self) -> None:
        from pokepoke.git.git_operations import sanitize_branch_name
        result = sanitize_branch_name("-my-branch-")
        assert not result.startswith("-")
        assert not result.endswith("-")


class TestBranchExists:
    """Tests for branch_exists."""

    @patch('pokepoke.git.git_operations.subprocess.run')
    def test_returns_true_when_branch_exists(self, mock_run: Mock) -> None:
        from pokepoke.git.git_operations import branch_exists
        mock_run.return_value = Mock(returncode=0)
        assert branch_exists("main") is True

    @patch('pokepoke.git.git_operations.subprocess.run')
    def test_returns_false_when_branch_missing(self, mock_run: Mock) -> None:
        from pokepoke.git.git_operations import branch_exists
        mock_run.return_value = Mock(returncode=1)
        assert branch_exists("nonexistent") is False

    @patch('pokepoke.git.git_operations.subprocess.run')
    def test_returns_false_on_exception(self, mock_run: Mock) -> None:
        from pokepoke.git.git_operations import branch_exists
        mock_run.side_effect = subprocess.CalledProcessError(128, "git")
        assert branch_exists("main") is False


class TestIsWorktreeClean:
    """Tests for is_worktree_clean."""

    @patch('pokepoke.git.git_operations.subprocess.run')
    def test_returns_true_for_clean_worktree(self, mock_run: Mock) -> None:
        mock_run.return_value = Mock(stdout="", returncode=0)
        assert is_worktree_clean(Path("/some/worktree")) is True

    @patch('pokepoke.git.git_operations.subprocess.run')
    def test_returns_false_for_dirty_worktree(self, mock_run: Mock) -> None:
        mock_run.return_value = Mock(stdout=" M file.py\n", returncode=0)
        assert is_worktree_clean(Path("/some/worktree")) is False

    @patch('pokepoke.git.git_operations.subprocess.run')
    def test_returns_false_on_error(self, mock_run: Mock) -> None:
        mock_run.side_effect = subprocess.CalledProcessError(128, "git")
        assert is_worktree_clean(Path("/some/worktree")) is False


class TestValidatePostMerge:
    """Tests for validate_post_merge."""

    @patch('pokepoke.git.git_operations.subprocess.run')
    def test_passes_when_on_target_and_clean(self, mock_run: Mock) -> None:
        mock_run.side_effect = [
            Mock(stdout="main\n", returncode=0),   # git branch --show-current
            Mock(stdout="", returncode=0),          # git status --porcelain
        ]
        assert validate_post_merge("main") is True

    @patch('pokepoke.git.git_operations.subprocess.run')
    def test_fails_when_on_wrong_branch(self, mock_run: Mock) -> None:
        mock_run.return_value = Mock(stdout="feature\n", returncode=0)
        assert validate_post_merge("main") is False

    @patch('pokepoke.git.git_operations.subprocess.run')
    def test_fails_when_uncommitted_changes(self, mock_run: Mock) -> None:
        mock_run.side_effect = [
            Mock(stdout="main\n", returncode=0),
            Mock(stdout=" M dirty.py\n", returncode=0),
        ]
        assert validate_post_merge("main") is False


class TestHasCommitsAhead:
    """Tests for has_commits_ahead."""

    @patch('pokepoke.git.git_operations.subprocess.run')
    def test_returns_commit_count(self, mock_run: Mock) -> None:
        mock_run.return_value = Mock(stdout="3\n", returncode=0)
        result = has_commits_ahead("main")
        assert result == 3

    @patch('pokepoke.git.git_operations.subprocess.run')
    def test_returns_zero_on_failure(self, mock_run: Mock) -> None:
        mock_run.return_value = Mock(stdout="", returncode=1)
        result = has_commits_ahead("main")
        assert result == 0

    @patch('pokepoke.git.git_operations.subprocess.run')
    def test_returns_zero_on_exception(self, mock_run: Mock) -> None:
        mock_run.side_effect = subprocess.TimeoutExpired("git", 10)
        result = has_commits_ahead("main")
        assert result == 0

    @patch('pokepoke.git.git_operations.get_default_branch', return_value='main')
    @patch('pokepoke.git.git_operations.subprocess.run')
    def test_resolves_default_branch_when_none(
        self, mock_run: Mock, mock_branch: Mock
    ) -> None:
        """When target_branch is None, get_default_branch() is called."""
        mock_run.return_value = Mock(stdout="2\n", returncode=0)
        result = has_commits_ahead(None)
        mock_branch.assert_called_once()
        assert result == 2


class TestExecuteMergeSequenceAdditional:
    """Additional tests for execute_merge_sequence uncovered paths."""

    @patch('pokepoke.git.git_operations.subprocess.run')
    def test_checkout_failure_returns_error(self, mock_run: Mock) -> None:
        """CalledProcessError during checkout returns failure immediately."""
        mock_run.side_effect = subprocess.CalledProcessError(
            1, "git checkout", stderr="error: pathspec 'main' did not match"
        )
        success, message, unmerged = execute_merge_sequence("feature", "main")
        assert success is False
        assert "Failed to checkout main" in message
        assert unmerged == []

    @patch('pokepoke.git.merge_conflict.is_merge_in_progress', return_value=True)
    @patch('pokepoke.git.merge_conflict.get_unmerged_files', return_value=["file.py"])
    @patch('pokepoke.git.git_operations.subprocess.run')
    def test_merge_conflict_returns_unmerged_files(
        self, mock_run: Mock,
        mock_unmerged: Mock, mock_in_progress: Mock
    ) -> None:
        """Merge conflicts return the list of unmerged files."""

        def side_effect(cmd, **kwargs):
            if cmd[:2] == ["git", "checkout"]:
                return Mock(returncode=0)
            if cmd[:2] == ["git", "merge"]:
                raise subprocess.CalledProcessError(1, cmd, stderr="CONFLICT")
            raise AssertionError(f"Unexpected command: {cmd}")

        mock_run.side_effect = side_effect
        success, message, unmerged = execute_merge_sequence("feature", "main")
        assert success is False
        assert "conflicts" in message.lower()
        assert "file.py" in unmerged

    @patch('pokepoke.git.merge_conflict.is_merge_in_progress', return_value=False)
    @patch('pokepoke.git.merge_conflict.get_unmerged_files', return_value=[])
    @patch('pokepoke.git.git_operations.subprocess.run')
    def test_merge_failure_without_conflict(
        self, mock_run: Mock,
        mock_unmerged: Mock, mock_in_progress: Mock
    ) -> None:
        """Merge failure without conflict files returns generic failure."""

        def side_effect(cmd, **kwargs):
            if cmd[:2] == ["git", "checkout"]:
                return Mock(returncode=0)
            if cmd[:2] == ["git", "merge"]:
                raise subprocess.CalledProcessError(1, cmd, stderr="merge error")
            raise AssertionError(f"Unexpected: {cmd}")

        mock_run.side_effect = side_effect
        success, message, _unmerged = execute_merge_sequence("feature", "main")
        assert success is False
        assert "Merge failed" in message


class TestExecuteMergeSequenceRollback:
    """Tests for execute_merge_sequence rollback on failure."""

    @patch('pokepoke.git.merge_conflict.is_merge_in_progress', return_value=True)
    @patch('pokepoke.git.merge_conflict.get_unmerged_files', return_value=["conflict.py"])
    @patch('pokepoke.git.git_operations.subprocess.run')
    def test_merge_abort_called_on_conflict(
        self, mock_run: Mock, mock_unmerged: Mock, mock_in_progress: Mock
    ) -> None:
        """git merge --abort is called when merge conflict is detected."""
        abort_called = []

        def side_effect(cmd, **kwargs):
            if cmd[:2] == ["git", "checkout"]:
                return Mock(returncode=0)
            if cmd[:3] == ["git", "merge", "--no-ff"]:
                raise subprocess.CalledProcessError(1, cmd, stderr="CONFLICT")
            if cmd[:3] == ["git", "merge", "--abort"]:
                abort_called.append(True)
                return Mock(returncode=0)
            raise AssertionError(f"Unexpected: {cmd}")

        mock_run.side_effect = side_effect
        success, message, _unmerged = execute_merge_sequence("feature", "main")

        assert success is False
        assert "conflict" in message.lower()
        assert abort_called, "git merge --abort should have been called"

    @patch('pokepoke.git.merge_conflict.is_merge_in_progress', return_value=False)
    @patch('pokepoke.git.merge_conflict.get_unmerged_files', return_value=[])
    @patch('pokepoke.git.git_operations.subprocess.run')
    def test_merge_abort_not_called_when_no_merge_in_progress(
        self, mock_run: Mock, mock_unmerged: Mock, mock_in_progress: Mock
    ) -> None:
        """git merge --abort is NOT called when no merge is in progress."""
        abort_called = []

        def side_effect(cmd, **kwargs):
            if cmd[:2] == ["git", "checkout"]:
                return Mock(returncode=0)
            if cmd[:3] == ["git", "merge", "--no-ff"]:
                raise subprocess.CalledProcessError(1, cmd, stderr="error")
            if cmd[:3] == ["git", "merge", "--abort"]:
                abort_called.append(True)
                return Mock(returncode=0)
            raise AssertionError(f"Unexpected: {cmd}")

        mock_run.side_effect = side_effect
        success, _message, _unmerged = execute_merge_sequence("feature", "main")

        assert success is False
        assert not abort_called, "git merge --abort should NOT be called when no merge in progress"

    @patch('pokepoke.git.merge_conflict.is_merge_in_progress', return_value=True)
    @patch('pokepoke.git.merge_conflict.get_unmerged_files', return_value=["conflict.py"])
    @patch('pokepoke.git.git_operations.subprocess.run')
    def test_merge_abort_failure_does_not_mask_error(
        self, mock_run: Mock, mock_unmerged: Mock, mock_in_progress: Mock
    ) -> None:
        """If git merge --abort fails, the original error is still returned."""

        def side_effect(cmd, **kwargs):
            if cmd[:2] == ["git", "checkout"]:
                return Mock(returncode=0)
            if cmd[:3] == ["git", "merge", "--no-ff"]:
                raise subprocess.CalledProcessError(1, cmd, stderr="CONFLICT")
            if cmd[:3] == ["git", "merge", "--abort"]:
                raise subprocess.CalledProcessError(1, cmd, stderr="abort failed")
            raise AssertionError(f"Unexpected: {cmd}")

        mock_run.side_effect = side_effect
        success, message, unmerged = execute_merge_sequence("feature", "main")

        assert success is False
        assert "conflict" in message.lower()
        assert "conflict.py" in unmerged


class TestExecuteMergeSequenceTimeoutExpired:
    """Tests for execute_merge_sequence TimeoutExpired handling."""

    @patch('pokepoke.git.git_operations.subprocess.run')
    def test_checkout_timeout_returns_failure(self, mock_run: Mock) -> None:
        """TimeoutExpired during checkout returns failure tuple."""
        mock_run.side_effect = subprocess.TimeoutExpired("git checkout", 30)
        success, message, unmerged = execute_merge_sequence("feature", "main")
        assert success is False
        assert "timed out" in message
        assert "30s" in message
        assert unmerged == []

    @patch('pokepoke.git.merge_conflict.is_merge_in_progress', return_value=True)
    @patch('pokepoke.git.merge_conflict.get_unmerged_files', return_value=["dirty.py"])
    @patch('pokepoke.git.git_operations.subprocess.run')
    def test_merge_timeout_aborts_merge_and_returns_unmerged(
        self, mock_run: Mock,
        mock_unmerged: Mock, mock_in_progress: Mock
    ) -> None:
        """TimeoutExpired during merge aborts and returns unmerged files."""
        def side_effect(cmd, **kwargs):
            if cmd[:2] == ["git", "checkout"]:
                return Mock(returncode=0)
            if cmd[:3] == ["git", "merge", "--no-ff"]:
                raise subprocess.TimeoutExpired("git merge", 60)
            if cmd[:2] == ["git", "merge"]:
                return Mock(returncode=0)
            raise AssertionError(f"Unexpected: {cmd}")

        mock_run.side_effect = side_effect
        success, message, unmerged = execute_merge_sequence("feature", "main")
        assert success is False
        assert "timed out" in message
        assert "60s" in message
        assert "dirty.py" in unmerged

    @patch('pokepoke.git.merge_conflict.is_merge_in_progress', return_value=False)
    @patch('pokepoke.git.merge_conflict.get_unmerged_files', return_value=[])
    @patch('pokepoke.git.git_operations.subprocess.run')
    def test_merge_timeout_no_merge_in_progress(
        self, mock_run: Mock,
        mock_unmerged: Mock, mock_in_progress: Mock
    ) -> None:
        """TimeoutExpired during merge when no merge state skips abort."""
        def side_effect(cmd, **kwargs):
            if cmd[:2] == ["git", "checkout"]:
                return Mock(returncode=0)
            if cmd[:3] == ["git", "merge", "--no-ff"]:
                raise subprocess.TimeoutExpired("git merge", 60)
            raise AssertionError(f"Unexpected: {cmd}")

        mock_run.side_effect = side_effect
        success, message, unmerged = execute_merge_sequence("feature", "main")
        assert success is False
        assert "timed out" in message
        assert unmerged == []


class TestAutoResolvePokepokeConflicts:
    """Tests for _auto_resolve_pokepoke_conflicts helper."""

    @patch('pokepoke.git.git_helpers.subprocess.run')
    def test_resolves_pokepoke_files(self, mock_run: Mock) -> None:
        """Files under .pokepoke/ are auto-resolved with --ours."""
        from pokepoke.git.git_operations import _auto_resolve_pokepoke_conflicts
        mock_run.return_value = Mock(returncode=0, stdout="", stderr="")

        remaining = _auto_resolve_pokepoke_conflicts(
            [".pokepoke/model_registry.json", ".pokepoke/failed_unassigns.json"],
        )

        assert remaining == []
        # Should have called checkout --ours and add for each file
        cmds = [call[0][0] for call in mock_run.call_args_list]
        assert any("checkout" in cmd and "--ours" in cmd for cmd in cmds)
        assert any(cmd[:2] == ["git", "add"] for cmd in cmds)

    def test_leaves_non_pokepoke_files(self) -> None:
        """Files outside .pokepoke/ are left unresolved."""
        from pokepoke.git.git_operations import _auto_resolve_pokepoke_conflicts

        remaining = _auto_resolve_pokepoke_conflicts(
            ["src/main.py", "README.md"],
        )

        assert remaining == ["src/main.py", "README.md"]

    @patch('pokepoke.git.git_helpers.subprocess.run')
    def test_mixed_files_resolves_only_pokepoke(self, mock_run: Mock) -> None:
        """Only .pokepoke/ files are resolved; others are returned."""
        from pokepoke.git.git_operations import _auto_resolve_pokepoke_conflicts
        mock_run.return_value = Mock(returncode=0, stdout="", stderr="")

        remaining = _auto_resolve_pokepoke_conflicts(
            [".pokepoke/model_registry.json", "src/main.py"],
        )

        assert remaining == ["src/main.py"]

    @patch('pokepoke.git.git_helpers.subprocess.run')
    def test_git_failure_keeps_file_in_remaining(self, mock_run: Mock) -> None:
        """If git checkout --ours fails, the file stays in remaining."""
        from pokepoke.git.git_operations import _auto_resolve_pokepoke_conflicts
        mock_run.side_effect = subprocess.CalledProcessError(1, "git checkout")

        remaining = _auto_resolve_pokepoke_conflicts(
            [".pokepoke/model_registry.json"],
        )

        assert remaining == [".pokepoke/model_registry.json"]

    def test_empty_list_returns_empty(self) -> None:
        """Empty input returns empty output."""
        from pokepoke.git.git_operations import _auto_resolve_pokepoke_conflicts

        assert _auto_resolve_pokepoke_conflicts([]) == []


class TestMergeSequencePokepokeAutoResolve:
    """Tests for .pokepoke/ auto-resolution in execute_merge_sequence."""

    @patch('pokepoke.git.merge_conflict.is_merge_in_progress', return_value=True)
    @patch('pokepoke.git.merge_conflict.get_unmerged_files',
           return_value=[".pokepoke/model_registry.json", ".pokepoke/failed_unassigns.json"])
    @patch('pokepoke.git.git_operations.subprocess.run')
    def test_all_pokepoke_conflicts_auto_resolved(
        self, mock_run: Mock,
        mock_unmerged: Mock, mock_in_progress: Mock,
    ) -> None:
        """When all conflicts are .pokepoke/ files, merge completes successfully."""
        def side_effect(cmd, **kwargs):
            if cmd[:2] == ["git", "checkout"] and "--ours" not in cmd:
                return Mock(returncode=0)
            if cmd[:3] == ["git", "merge", "--no-ff"]:
                raise subprocess.CalledProcessError(1, cmd, stderr="CONFLICT")
            if cmd[:2] == ["git", "checkout"] and "--ours" in cmd:
                return Mock(returncode=0)
            if cmd[:2] == ["git", "add"]:
                return Mock(returncode=0)
            if cmd[:2] == ["git", "commit"]:
                return Mock(returncode=0)
            raise AssertionError(f"Unexpected command: {cmd}")

        mock_run.side_effect = side_effect
        success, _message, unmerged = execute_merge_sequence("feature", "main")

        assert success is True
        assert unmerged == []

    @patch('pokepoke.git.merge_conflict.abort_merge', return_value=(True, ""))
    @patch('pokepoke.git.merge_conflict.is_merge_in_progress', return_value=True)
    @patch('pokepoke.git.merge_conflict.get_unmerged_files',
           return_value=[".pokepoke/model_registry.json", "src/main.py"])
    @patch('pokepoke.git.git_operations.subprocess.run')
    def test_mixed_conflicts_resolves_pokepoke_returns_others(
        self, mock_run: Mock,
        mock_unmerged: Mock, mock_in_progress: Mock, mock_abort: Mock,
    ) -> None:
        """When some conflicts are .pokepoke/ and others aren't, only others remain."""
        def side_effect(cmd, **kwargs):
            if cmd[:2] == ["git", "checkout"] and "--ours" not in cmd:
                return Mock(returncode=0)
            if cmd[:3] == ["git", "merge", "--no-ff"]:
                raise subprocess.CalledProcessError(1, cmd, stderr="CONFLICT")
            if cmd[:2] == ["git", "checkout"] and "--ours" in cmd:
                return Mock(returncode=0)
            if cmd[:2] == ["git", "add"]:
                return Mock(returncode=0)
            raise AssertionError(f"Unexpected command: {cmd}")

        mock_run.side_effect = side_effect
        success, _message, unmerged = execute_merge_sequence("feature", "main")

        assert success is False
        assert "src/main.py" in unmerged
        assert ".pokepoke/model_registry.json" not in unmerged
