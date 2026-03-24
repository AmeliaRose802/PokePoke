"""Unit tests for handoff_context module."""

import subprocess
from unittest.mock import Mock, patch

import pytest

from pokepoke.prompts import handoff_context
from pokepoke.prompts.handoff_context import _MAX_DIFF_CHARS, build_handoff_context

# handoff_context.py calls run_git() (from git.git_helpers), which internally
# calls subprocess.run.  Patching run_git directly is the correct level.
# get_default_branch is lazy-imported inside the function from git_operations.
_PATCH_RUN_GIT = 'pokepoke.prompts.handoff_context.run_git'
_PATCH_DEFAULT_BRANCH = 'pokepoke.git.git_operations.get_default_branch'


class TestBuildHandoffContext:
    """Test build_handoff_context function."""

    @patch(_PATCH_DEFAULT_BRANCH, return_value='main')
    @patch(_PATCH_RUN_GIT)
    def test_returns_empty_when_no_changes(
        self, mock_run: Mock, mock_branch: Mock
    ) -> None:
        """Return empty string when no files changed."""
        mock_run.return_value = Mock(returncode=0, stdout="")

        result = build_handoff_context(cwd="C:\\tmp\\worktree")

        assert result == ""
        assert mock_run.call_count == 1

    @patch(_PATCH_DEFAULT_BRANCH, return_value='main')
    @patch(_PATCH_RUN_GIT)
    def test_builds_full_context_with_edge_cases(
        self, mock_run: Mock, mock_branch: Mock
    ) -> None:
        """Include renamed files, binary diff lines, and non-empty commit history."""
        def side_effect(cmd: list[str], **kwargs: object) -> Mock:
            if "--name-status" in cmd:
                return Mock(
                    returncode=0,
                    stdout="M\tsrc/foo.py\nR100\told.txt\tnew.txt\nA\tassets/logo.png\n"
                )
            if "--stat" in cmd:
                return Mock(
                    returncode=0,
                    stdout=" src/foo.py | 2 +-\n old.txt | 1 -\n new.txt | 1 +\n"
                )
            if cmd[:2] == ["git", "log"]:
                return Mock(
                    returncode=0,
                    stdout="abc1234 feat: add bar\n\n"
                )
            return Mock(
                returncode=0,
                stdout="Binary files a/assets/logo.png and b/assets/logo.png differ"
            )

        mock_run.side_effect = side_effect

        result = build_handoff_context(cwd="C:\\tmp\\worktree")

        assert "### Changed Files" in result
        assert "R100\told.txt\tnew.txt" in result
        assert "### Diff Summary" in result
        assert "### Commit History" in result
        assert "abc1234 feat: add bar" in result
        assert "### Diff Content" in result
        assert "Binary files a/assets/logo.png" in result
        commit_section = result.split("### Commit History", 1)[1]
        commit_block = commit_section.split("```", 2)[1]
        commit_lines = commit_block.splitlines()
        while commit_lines and commit_lines[0] == "":
            commit_lines.pop(0)
        while commit_lines and commit_lines[-1] == "":
            commit_lines.pop()
        assert all(line.strip() for line in commit_lines)

    @patch(_PATCH_DEFAULT_BRANCH, return_value='main')
    @patch(_PATCH_RUN_GIT)
    def test_truncates_large_diff(
        self, mock_run: Mock, mock_branch: Mock
    ) -> None:
        """Truncate diffs exceeding the maximum size."""
        large_diff = "x" * (_MAX_DIFF_CHARS + 10)

        def side_effect(cmd: list[str], **kwargs: object) -> Mock:
            if "--name-status" in cmd:
                return Mock(returncode=0, stdout="M\tsrc/big.py\n")
            if "--stat" in cmd:
                return Mock(returncode=1, stdout="")
            if cmd[:2] == ["git", "log"]:
                return Mock(returncode=1, stdout="")
            return Mock(returncode=0, stdout=large_diff)

        mock_run.side_effect = side_effect

        result = build_handoff_context(cwd="C:\\tmp\\worktree")

        assert "diff truncated" in result
        diff_section = result.split("```diff", 1)[1]
        diff_body = diff_section.split("```", 1)[0].lstrip("\n").rstrip("\n")
        assert len(diff_body) == _MAX_DIFF_CHARS

    @pytest.mark.parametrize(
        "exception",
        [
            subprocess.TimeoutExpired(cmd="git", timeout=15),
            FileNotFoundError("git not found"),
        ],
    )
    @patch(_PATCH_DEFAULT_BRANCH, return_value='main')
    @patch(_PATCH_RUN_GIT)
    def test_returns_empty_on_initial_git_errors(
        self, mock_run: Mock, mock_branch: Mock, exception: Exception
    ) -> None:
        """Return empty string when the initial git command fails."""
        mock_run.side_effect = exception

        result = build_handoff_context(cwd="C:\\tmp\\worktree")

        assert result == ""

    @patch(_PATCH_DEFAULT_BRANCH, return_value='main')
    @patch(_PATCH_RUN_GIT)
    def test_omits_sections_when_subsequent_commands_fail(
        self, mock_run: Mock, mock_branch: Mock
    ) -> None:
        """Omit stat/log/diff sections when those commands fail."""
        def side_effect(cmd: list[str], **kwargs: object) -> Mock:
            if "--name-status" in cmd:
                return Mock(returncode=0, stdout="M\tsrc/only.py\n")
            if "--stat" in cmd:
                raise FileNotFoundError("git not found")
            if cmd[:2] == ["git", "log"]:
                return Mock(returncode=1, stdout="")
            return Mock(returncode=1, stdout="")

        mock_run.side_effect = side_effect

        result = build_handoff_context(cwd="C:\\tmp\\worktree")

        assert "### Changed Files" in result
        assert "### Diff Summary" not in result
        assert "### Commit History" not in result
        assert "### Diff Content" not in result

    @patch(_PATCH_DEFAULT_BRANCH, return_value='main')
    @patch(_PATCH_RUN_GIT)
    def test_logs_debug_on_subprocess_failures(
        self, mock_run: Mock, mock_branch: Mock
    ) -> None:
        """Verify subprocess failures are logged at DEBUG level."""
        timeout_error = subprocess.TimeoutExpired(cmd="git", timeout=15)

        def side_effect(cmd: list[str], **kwargs: object) -> Mock:
            if "--name-status" in cmd:
                return Mock(returncode=0, stdout="M\tsrc/foo.py\n")
            if "--stat" in cmd:
                raise timeout_error
            if cmd[:2] == ["git", "log"]:
                raise FileNotFoundError("git not found")
            return Mock(returncode=0, stdout="some diff")

        mock_run.side_effect = side_effect

        with patch.object(handoff_context.logger, 'debug') as mock_debug:
            result = build_handoff_context(cwd="C:\\tmp\\worktree")

        assert result != ""
        assert mock_debug.call_count >= 2
        debug_messages = [str(call) for call in mock_debug.call_args_list]
        assert any("git diff --stat failed" in msg for msg in debug_messages)
        assert any("git log --oneline failed" in msg for msg in debug_messages)
