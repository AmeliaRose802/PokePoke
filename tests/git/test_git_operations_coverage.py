"""Extended coverage tests for git_operations module.

Covers edge cases and paths not exercised by test_git_operations.py:
- categorize_git_changes edge cases
- sanitize_branch_name exhaustive special-char handling
- get_default_branch fallback chain
- _handle_merge_failure scenarios
- get_status_porcelain_and_changes
- execute_merge_sequence timeout paths
"""

import subprocess
from unittest.mock import Mock, patch

import pytest

from pokepoke.git.git_operations import (
    _auto_resolve_pokepoke_conflicts,
    _handle_merge_failure,
    branch_exists,
    categorize_git_changes,
    execute_merge_sequence,
    get_default_branch,
    get_status_porcelain_and_changes,
    sanitize_branch_name,
)


# ---------------------------------------------------------------------------
# categorize_git_changes – edge cases
# ---------------------------------------------------------------------------
class TestCategorizeGitChangesEdgeCases:
    """Edge cases for categorize_git_changes."""

    def test_empty_lines_are_filtered(self) -> None:
        lines = ["", " M src/foo.py", "", ""]
        result = categorize_git_changes(lines)
        assert result["other"] == [" M src/foo.py"]
        assert result["beads"] == []
        assert result["worktree"] == []
        assert result["untracked"] == []

    def test_all_empty_input(self) -> None:
        assert categorize_git_changes([]) == {
            "beads": [], "worktree": [], "untracked": [], "other": [],
        }

    def test_mixed_beads_worktree_untracked_other(self) -> None:
        lines = [
            " M .beads/issues.jsonl",
            " M worktrees/task-123/file.py",
            "?? new_file.txt",
            " M src/main.py",
        ]
        result = categorize_git_changes(lines)
        assert result["beads"] == [" M .beads/issues.jsonl"]
        assert result["worktree"] == [" M worktrees/task-123/file.py"]
        assert result["untracked"] == ["?? new_file.txt"]
        assert result["other"] == [" M src/main.py"]

    def test_untracked_worktree_path_is_untracked_not_worktree(self) -> None:
        """Lines with ?? prefix containing worktree paths → untracked only."""
        lines = ["?? worktrees/task-abc/leftover.txt"]
        result = categorize_git_changes(lines)
        assert result["untracked"] == ["?? worktrees/task-abc/leftover.txt"]
        # Must NOT appear in worktree bucket (line starts with ??)
        assert result["worktree"] == []

    def test_beads_untracked_goes_to_both_beads_and_untracked(self) -> None:
        """Untracked beads file appears in both beads and untracked."""
        lines = ["?? .beads/new.jsonl"]
        result = categorize_git_changes(lines)
        assert result["beads"] == ["?? .beads/new.jsonl"]
        assert result["untracked"] == ["?? .beads/new.jsonl"]

    def test_only_untracked_lines(self) -> None:
        lines = ["?? file1.txt", "?? file2.txt"]
        result = categorize_git_changes(lines)
        assert len(result["untracked"]) == 2
        assert result["other"] == []
        assert result["beads"] == []
        assert result["worktree"] == []


# ---------------------------------------------------------------------------
# sanitize_branch_name – exhaustive special character handling
# ---------------------------------------------------------------------------
class TestSanitizeBranchNameEdgeCases:
    """Exhaustive edge cases for sanitize_branch_name."""

    @pytest.mark.parametrize("char", list("~^:?*[]\\@{}#<>|&;"))
    def test_individual_special_chars_replaced(self, char: str) -> None:
        result = sanitize_branch_name(f"a{char}b")
        assert char not in result
        assert "a" in result and "b" in result

    def test_multiple_consecutive_invalid_chars_collapse_to_single_hyphen(self) -> None:
        assert sanitize_branch_name("a::;;b") == "a-b"

    def test_double_dots_collapsed_to_single_dot(self) -> None:
        assert sanitize_branch_name("a..b") == "a.b"

    def test_triple_dots_collapsed_to_single_dot(self) -> None:
        assert sanitize_branch_name("a...b") == "a.b"

    def test_leading_hyphens_stripped(self) -> None:
        result = sanitize_branch_name("---branch")
        assert not result.startswith("-")

    def test_trailing_hyphens_stripped(self) -> None:
        result = sanitize_branch_name("branch---")
        assert not result.endswith("-")

    def test_leading_dots_stripped(self) -> None:
        result = sanitize_branch_name("...branch")
        assert not result.startswith(".")

    def test_trailing_dots_stripped(self) -> None:
        result = sanitize_branch_name("branch...")
        assert not result.endswith(".")

    def test_already_valid_name_unchanged(self) -> None:
        assert sanitize_branch_name("feature/my-branch") == "feature/my-branch"

    def test_only_invalid_chars_returns_empty(self) -> None:
        result = sanitize_branch_name("::;;")
        assert result == ""

    def test_whitespace_replaced(self) -> None:
        assert sanitize_branch_name("my branch\there") == "my-branch-here"


# ---------------------------------------------------------------------------
# branch_exists – verify all return paths
# ---------------------------------------------------------------------------
class TestBranchExistsReturnPaths:
    """Ensure all three code paths in branch_exists are covered."""

    @patch("pokepoke.git.git_helpers.subprocess.run")
    def test_branch_exists_returns_true(self, mock_run: Mock) -> None:
        mock_run.return_value = Mock(returncode=0, stdout="", stderr="")
        assert branch_exists("main") is True

    @patch("pokepoke.git.git_helpers.subprocess.run")
    def test_branch_missing_returns_false(self, mock_run: Mock) -> None:
        mock_run.return_value = Mock(returncode=1, stdout="", stderr="")
        assert branch_exists("nonexistent") is False

    @patch("pokepoke.git.git_helpers.subprocess.run")
    def test_called_process_error_returns_false(self, mock_run: Mock) -> None:
        mock_run.side_effect = subprocess.CalledProcessError(128, "git")
        assert branch_exists("main") is False


# ---------------------------------------------------------------------------
# get_default_branch – fallback chain
# ---------------------------------------------------------------------------
class TestGetDefaultBranchFallbackChain:
    """Test all fallback paths in get_default_branch."""

    @patch("pokepoke.config.get_config")
    @patch("pokepoke.git.git_helpers.subprocess.run")
    def test_preferred_exists_locally(self, mock_run: Mock, mock_cfg: Mock) -> None:
        """Preferred branch exists locally → returned directly."""
        cfg = Mock()
        cfg.git.get_preferred_branch.return_value = "develop"
        cfg.git.fallback_branch = "main"
        mock_cfg.return_value = cfg
        # branch_exists calls show-ref → returncode 0
        mock_run.return_value = Mock(returncode=0, stdout="abc123", stderr="")
        assert get_default_branch() == "develop"

    @patch("pokepoke.config.get_config")
    @patch("pokepoke.git.git_helpers.subprocess.run")
    def test_preferred_exists_on_remote_creates_tracking(
        self, mock_run: Mock, mock_cfg: Mock
    ) -> None:
        """Preferred branch on remote → creates tracking branch."""
        cfg = Mock()
        cfg.git.get_preferred_branch.return_value = "develop"
        cfg.git.fallback_branch = "main"
        mock_cfg.return_value = cfg

        call_count = 0

        def side_effect(cmd, **kwargs):
            nonlocal call_count
            call_count += 1
            if "refs/heads/develop" in cmd:
                # Local check fails
                return Mock(returncode=1, stdout="", stderr="")
            if "refs/remotes/origin/develop" in cmd:
                # Remote exists
                return Mock(returncode=0, stdout="abc123", stderr="")
            if cmd[:2] == ["git", "branch"] and "--track" in cmd:
                return Mock(returncode=0, stdout="", stderr="")
            raise AssertionError(f"Unexpected command: {cmd}")

        mock_run.side_effect = side_effect
        assert get_default_branch() == "develop"
        # Verify tracking branch creation was called
        tracking_calls = [
            c for c in mock_run.call_args_list
            if "--track" in c[0][0]
        ]
        assert len(tracking_calls) == 1

    @patch("pokepoke.config.get_config")
    @patch("pokepoke.git.git_helpers.subprocess.run")
    def test_falls_back_to_origin_head(self, mock_run: Mock, mock_cfg: Mock) -> None:
        """Preferred branch not found → falls back to origin/HEAD."""
        cfg = Mock()
        cfg.git.get_preferred_branch.return_value = "develop"
        cfg.git.fallback_branch = "main"
        mock_cfg.return_value = cfg

        def side_effect(cmd, **kwargs):
            if "refs/heads/develop" in cmd:
                return Mock(returncode=1, stdout="", stderr="")
            if "refs/remotes/origin/develop" in cmd:
                raise subprocess.CalledProcessError(1, cmd)
            if "symbolic-ref" in cmd:
                return Mock(returncode=0, stdout="origin/main\n", stderr="")
            raise AssertionError(f"Unexpected command: {cmd}")

        mock_run.side_effect = side_effect
        assert get_default_branch() == "main"

    @patch("pokepoke.config.get_config")
    @patch("pokepoke.git.git_helpers.subprocess.run")
    def test_falls_back_to_current_branch(self, mock_run: Mock, mock_cfg: Mock) -> None:
        """origin/HEAD not available → falls back to current branch."""
        cfg = Mock()
        cfg.git.get_preferred_branch.return_value = "develop"
        cfg.git.fallback_branch = "main"
        mock_cfg.return_value = cfg

        def side_effect(cmd, **kwargs):
            if "refs/heads/develop" in cmd:
                return Mock(returncode=1, stdout="", stderr="")
            if "refs/remotes/origin/develop" in cmd:
                raise subprocess.CalledProcessError(1, cmd)
            if "symbolic-ref" in cmd:
                raise subprocess.CalledProcessError(1, cmd)
            if "rev-parse" in cmd and "--abbrev-ref" in cmd:
                return Mock(returncode=0, stdout="feature/xyz\n", stderr="")
            raise AssertionError(f"Unexpected command: {cmd}")

        mock_run.side_effect = side_effect
        assert get_default_branch() == "feature/xyz"

    @patch("pokepoke.config.get_config")
    @patch("pokepoke.git.git_helpers.subprocess.run")
    def test_all_fallbacks_fail_returns_fallback_string(
        self, mock_run: Mock, mock_cfg: Mock
    ) -> None:
        """All fallbacks fail → returns the fallback parameter."""
        cfg = Mock()
        cfg.git.get_preferred_branch.return_value = "develop"
        cfg.git.fallback_branch = "main"
        mock_cfg.return_value = cfg

        def side_effect(cmd, **kwargs):
            if "refs/heads/develop" in cmd:
                return Mock(returncode=1, stdout="", stderr="")
            if "refs/remotes/origin/develop" in cmd:
                raise subprocess.CalledProcessError(1, cmd)
            if "symbolic-ref" in cmd:
                raise subprocess.CalledProcessError(1, cmd)
            if "rev-parse" in cmd and "--abbrev-ref" in cmd:
                raise subprocess.CalledProcessError(1, cmd)
            raise AssertionError(f"Unexpected command: {cmd}")

        mock_run.side_effect = side_effect
        assert get_default_branch() == "main"

    @patch("pokepoke.config.get_config")
    @patch("pokepoke.git.git_helpers.subprocess.run")
    def test_explicit_preferred_and_fallback_override_config(
        self, mock_run: Mock, mock_cfg: Mock
    ) -> None:
        """Explicit preferred/fallback args override config values."""
        cfg = Mock()
        cfg.git.get_preferred_branch.return_value = "from-config"
        cfg.git.fallback_branch = "config-fallback"
        mock_cfg.return_value = cfg

        # All git calls fail
        mock_run.side_effect = subprocess.CalledProcessError(1, "git")

        result = get_default_branch(preferred="custom", fallback="custom-fallback")
        assert result == "custom-fallback"


# ---------------------------------------------------------------------------
# _auto_resolve_pokepoke_conflicts – resolution failure
# ---------------------------------------------------------------------------
class TestAutoResolvePokepokeConflictsFailure:
    """Test resolution failure adds file to remaining."""

    @patch("pokepoke.git.git_helpers.subprocess.run")
    def test_timeout_during_resolve_adds_to_remaining(self, mock_run: Mock) -> None:
        mock_run.side_effect = subprocess.TimeoutExpired("git", 10)
        remaining = _auto_resolve_pokepoke_conflicts(
            [".pokepoke/state.json"]
        )
        assert remaining == [".pokepoke/state.json"]

    @patch("pokepoke.git.git_helpers.subprocess.run")
    def test_mixed_with_partial_failure(self, mock_run: Mock) -> None:
        """First .pokepoke/ file resolves, second fails."""
        call_idx = 0

        def side_effect(cmd, **kwargs):
            nonlocal call_idx
            call_idx += 1
            # First two calls (checkout --ours + add) succeed for first file
            if call_idx <= 2:
                return Mock(returncode=0, stdout="", stderr="")
            # Third call (checkout --ours for second file) fails
            raise subprocess.CalledProcessError(1, cmd)

        mock_run.side_effect = side_effect
        remaining = _auto_resolve_pokepoke_conflicts(
            [".pokepoke/ok.json", ".pokepoke/fail.json", "src/app.py"]
        )
        assert ".pokepoke/ok.json" not in remaining
        assert ".pokepoke/fail.json" in remaining
        assert "src/app.py" in remaining


# ---------------------------------------------------------------------------
# _handle_merge_failure – scenarios
# ---------------------------------------------------------------------------
class TestHandleMergeFailure:
    """Test _handle_merge_failure code paths."""

    @patch("pokepoke.git.merge_conflict.is_merge_in_progress", return_value=True)
    @patch(
        "pokepoke.git.merge_conflict.get_unmerged_files",
        return_value=[".pokepoke/state.json"],
    )
    @patch("pokepoke.git.git_helpers.subprocess.run")
    def test_all_pokepoke_conflicts_auto_resolved_and_committed(
        self, mock_run: Mock, mock_unmerged: Mock, mock_merging: Mock
    ) -> None:
        """All .pokepoke/ conflicts → auto-resolve + commit → success."""
        mock_run.return_value = Mock(returncode=0, stdout="", stderr="")
        exc = subprocess.CalledProcessError(1, "git merge", stderr="CONFLICT")
        success, msg, files = _handle_merge_failure(exc, cwd="/repo")
        assert success is True
        assert msg == ""
        assert files == []

    @patch("pokepoke.git.merge_conflict.is_merge_in_progress", return_value=True)
    @patch(
        "pokepoke.git.merge_conflict.get_unmerged_files",
        return_value=[".pokepoke/state.json"],
    )
    @patch("pokepoke.git.git_helpers.subprocess.run")
    def test_auto_resolve_succeeds_but_commit_fails(
        self, mock_run: Mock, mock_unmerged: Mock, mock_merging: Mock
    ) -> None:
        """Auto-resolve works but final commit fails → merge aborted."""
        call_count = 0

        def side_effect(cmd, **kwargs):
            nonlocal call_count
            call_count += 1
            # checkout --ours and git add succeed
            if "checkout" in cmd and "--ours" in cmd:
                return Mock(returncode=0, stdout="", stderr="")
            if cmd[:2] == ["git", "add"]:
                return Mock(returncode=0, stdout="", stderr="")
            if cmd[:2] == ["git", "commit"]:
                raise subprocess.CalledProcessError(1, cmd, stderr="commit failed")
            # merge --abort
            if cmd[:2] == ["git", "merge"] and "--abort" in cmd:
                return Mock(returncode=0, stdout="", stderr="")
            return Mock(returncode=0, stdout="", stderr="")

        mock_run.side_effect = side_effect
        exc = subprocess.CalledProcessError(1, "git merge", stderr="CONFLICT")
        success, _, _ = _handle_merge_failure(exc, cwd="/repo")
        assert success is False

    @patch("pokepoke.git.merge_conflict.abort_merge", return_value=(True, ""))
    @patch("pokepoke.git.merge_conflict.is_merge_in_progress", return_value=True)
    @patch(
        "pokepoke.git.merge_conflict.get_unmerged_files",
        return_value=["src/main.py"],
    )
    def test_non_pokepoke_conflicts_abort_merge(
        self, mock_unmerged: Mock, mock_merging: Mock, mock_abort: Mock
    ) -> None:
        """Non-.pokepoke/ conflicts → abort merge."""
        exc = subprocess.CalledProcessError(1, "git merge", stderr="CONFLICT")
        success, _, files = _handle_merge_failure(exc, cwd="/repo")
        assert success is False
        assert "src/main.py" in files
        mock_abort.assert_called_once()

    @patch("pokepoke.git.merge_conflict.is_merge_in_progress", return_value=False)
    @patch("pokepoke.git.merge_conflict.get_unmerged_files", return_value=[])
    def test_timeout_expired_returns_specific_message(
        self, mock_unmerged: Mock, mock_merging: Mock
    ) -> None:
        """TimeoutExpired → specific timeout error message."""
        exc = subprocess.TimeoutExpired("git merge", 60)
        success, msg, _ = _handle_merge_failure(exc, cwd=None)
        assert success is False
        assert "timed out" in msg.lower()

    @patch("pokepoke.git.merge_conflict.is_merge_in_progress", return_value=False)
    @patch("pokepoke.git.merge_conflict.get_unmerged_files", return_value=[])
    def test_no_unmerged_files_returns_generic_error(
        self, mock_unmerged: Mock, mock_merging: Mock
    ) -> None:
        """No unmerged files → generic merge failure message."""
        exc = subprocess.CalledProcessError(1, "git merge", stderr="fatal error")
        success, msg, files = _handle_merge_failure(exc, cwd=None)
        assert success is False
        assert "Merge failed" in msg
        assert files == []

    @patch("pokepoke.git.merge_conflict.abort_merge", return_value=(False, "abort err"))
    @patch("pokepoke.git.merge_conflict.is_merge_in_progress", return_value=True)
    @patch(
        "pokepoke.git.merge_conflict.get_unmerged_files",
        return_value=["src/x.py"],
    )
    def test_merge_abort_failure_is_logged_not_raised(
        self, mock_unmerged: Mock, mock_merging: Mock, mock_abort: Mock
    ) -> None:
        """Merge abort failure is logged but doesn't raise."""
        exc = subprocess.CalledProcessError(1, "git merge", stderr="CONFLICT")
        success, _, _ = _handle_merge_failure(exc, cwd=None)
        assert success is False
        mock_abort.assert_called_once()


# ---------------------------------------------------------------------------
# get_status_porcelain_and_changes
# ---------------------------------------------------------------------------
class TestGetStatusPorcelainAndChanges:
    """Test get_status_porcelain_and_changes."""

    @patch("pokepoke.git.git_helpers.subprocess.run")
    def test_clean_repo(self, mock_run: Mock) -> None:
        mock_run.return_value = Mock(returncode=0, stdout="", stderr="")
        raw, changes = get_status_porcelain_and_changes()
        assert raw == ""
        assert changes == {
            "beads": [], "worktree": [], "untracked": [], "other": [],
        }

    @patch("pokepoke.git.git_helpers.subprocess.run")
    def test_dirty_repo_with_various_types(self, mock_run: Mock) -> None:
        stdout = (
            " M .beads/issues.jsonl\n"
            " M worktrees/task-1/f.py\n"
            "?? untracked.txt\n"
            " M src/foo.py\n"
        )
        mock_run.return_value = Mock(returncode=0, stdout=stdout, stderr="")
        raw, changes = get_status_porcelain_and_changes()
        assert raw == stdout.strip()
        assert len(changes["beads"]) == 1
        assert len(changes["worktree"]) == 1
        assert len(changes["untracked"]) == 1
        assert len(changes["other"]) == 1


# ---------------------------------------------------------------------------
# execute_merge_sequence – additional timeout/stash paths
# ---------------------------------------------------------------------------
class TestExecuteMergeSequenceTimeoutPaths:
    """Additional timeout and stash paths in execute_merge_sequence."""

    @patch("pokepoke.git.git_helpers.subprocess.run")
    def test_checkout_timeout(self, mock_run: Mock) -> None:
        """Checkout timeout returns specific message."""
        mock_run.side_effect = subprocess.TimeoutExpired("git checkout", 30)
        success, msg, unmerged = execute_merge_sequence("feat", "main")
        assert success is False
        assert "timed out" in msg.lower()
        assert unmerged == []

    @patch("pokepoke.git.merge_conflict.is_merge_in_progress", return_value=True)
    @patch(
        "pokepoke.git.merge_conflict.get_unmerged_files",
        return_value=[".pokepoke/state.json"],
    )
    @patch("pokepoke.git.git_helpers.subprocess.run")
    def test_merge_timeout_handles_failure(
        self, mock_run: Mock,
        mock_unmerged: Mock, mock_merging: Mock
    ) -> None:
        """Merge timeout → _handle_merge_failure called."""

        def side_effect(cmd, **kwargs):
            if cmd[:2] == ["git", "checkout"]:
                return Mock(returncode=0, stdout="", stderr="")
            if cmd[:3] == ["git", "merge", "--no-ff"]:
                raise subprocess.TimeoutExpired(cmd, 60)
            # auto-resolve calls
            if "--ours" in cmd:
                return Mock(returncode=0, stdout="", stderr="")
            if cmd[:2] == ["git", "add"]:
                return Mock(returncode=0, stdout="", stderr="")
            if cmd[:2] == ["git", "commit"]:
                return Mock(returncode=0, stdout="", stderr="")
            raise AssertionError(f"Unexpected: {cmd}")

        mock_run.side_effect = side_effect
        success, _, _ = execute_merge_sequence("feat", "main")
        # Auto-resolve of .pokepoke/ should succeed even after timeout
        assert success is True

    @patch("pokepoke.git.git_helpers.subprocess.run")
    def test_merge_success_simple(
        self, mock_run: Mock,
    ) -> None:
        """Checkout + merge succeeds with no stash or pull."""

        def side_effect(cmd, **kwargs):
            if cmd[:2] == ["git", "checkout"]:
                return Mock(returncode=0, stdout="", stderr="")
            if cmd[:2] == ["git", "merge"]:
                return Mock(returncode=0, stdout="", stderr="")
            raise AssertionError(f"Unexpected: {cmd}")

        mock_run.side_effect = side_effect
        success, _, _ = execute_merge_sequence("feat", "main")
        assert success is True
