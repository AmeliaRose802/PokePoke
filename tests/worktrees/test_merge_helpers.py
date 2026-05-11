"""Tests for worktree merge helper functions."""

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from pokepoke.worktrees.merge_helpers import (
    _log_post_merge_diagnostics,
    integrate_target_into_worktree,
    is_worktree_merged,
    log_merge_failure,
    validate_post_merge_or_rollback,
    validate_pre_merge_quality,
)

# ---------------------------------------------------------------------------
# integrate_target_into_worktree
# ---------------------------------------------------------------------------

class TestIntegrateTargetIntoWorktree:
    @patch("pokepoke.worktrees.merge_helpers._run_git")
    def test_success_path(self, mock_git, tmp_path) -> None:
        mock_git.return_value = MagicMock(returncode=0)
        result = integrate_target_into_worktree(tmp_path, "main")
        assert result.success is True

    @patch("pokepoke.git.merge_conflict.is_merge_in_progress", return_value=False)
    @patch("pokepoke.git.merge_conflict.get_unmerged_files", return_value=["a.py"])
    @patch("pokepoke.worktrees.merge_helpers._run_git", side_effect=subprocess.CalledProcessError(1, "git"))
    def test_conflict_aborts(self, mock_git, mock_unmerged, mock_in_progress, tmp_path) -> None:
        result = integrate_target_into_worktree(tmp_path, "main")
        assert result.success is False

    @patch("pokepoke.git.merge_conflict.is_merge_in_progress", return_value=True)
    @patch("pokepoke.git.merge_conflict.abort_merge", return_value=(True, ""))
    @patch("pokepoke.git.merge_conflict.get_unmerged_files", return_value=["a.py"])
    @patch("pokepoke.worktrees.merge_helpers._run_git", side_effect=subprocess.TimeoutExpired("git", 120))
    def test_timeout_aborts(self, mock_git, mock_unmerged, mock_abort, mock_in_progress, tmp_path) -> None:
        result = integrate_target_into_worktree(tmp_path, "main")
        assert result.success is False

# ---------------------------------------------------------------------------
# log_merge_failure
# ---------------------------------------------------------------------------

class TestLogMergeFailure:
    def test_logs_unmerged_files(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level("ERROR"):
            log_merge_failure(None, ["a.py", "b.py"])
        assert "Merge conflicts detected in 2 file(s)" in caplog.text

    def test_truncates_at_10_files(self, caplog: pytest.LogCaptureFixture) -> None:
        files = [f"file{i}.py" for i in range(15)]
        with caplog.at_level("INFO"):
            log_merge_failure(None, files)
        assert "and 5 more" in caplog.text

    def test_logs_merge_error_when_no_files(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level("ERROR"):
            log_merge_failure("bad merge", [])
        assert "Merge failed: bad merge" in caplog.text

# ---------------------------------------------------------------------------
# validate_post_merge_or_rollback
# ---------------------------------------------------------------------------

class TestValidatePostMergeOrRollback:
    @patch("pokepoke.worktrees.merge_helpers.validate_post_merge", return_value=True)
    def test_returns_none_on_success(self, _mock: MagicMock) -> None:
        result = validate_post_merge_or_rollback("master")
        assert result is None

    @patch("pokepoke.worktrees.merge_helpers._run_git")
    @patch("pokepoke.worktrees.merge_helpers.validate_post_merge", return_value=False)
    def test_returns_failure_result_when_validation_fails(
        self, _mock_validate: MagicMock, mock_git: MagicMock,
    ) -> None:
        mock_git.return_value = subprocess.CompletedProcess([], 0, stdout="")
        result = validate_post_merge_or_rollback("master")
        assert result is not None
        assert result.success is False
        assert result.halt_required is True

    @patch("pokepoke.worktrees.merge_helpers._run_git")
    @patch("pokepoke.worktrees.merge_helpers.validate_post_merge", side_effect=RuntimeError("oops"))
    def test_returns_failure_on_exception(
        self, _mock_validate: MagicMock, mock_git: MagicMock,
    ) -> None:
        mock_git.return_value = subprocess.CompletedProcess([], 0, stdout="")
        result = validate_post_merge_or_rollback("master")
        assert result is not None
        assert result.success is False
        assert result.halt_required is True

# ---------------------------------------------------------------------------
# _log_post_merge_diagnostics
# ---------------------------------------------------------------------------

class TestLogPostMergeDiagnostics:
    @patch("pokepoke.worktrees.merge_helpers._run_git")
    def test_collects_all_diagnostics(self, mock_git: MagicMock, caplog: pytest.LogCaptureFixture) -> None:
        mock_git.side_effect = [
            subprocess.CompletedProcess([], 0, stdout=" M foo.py"),
            subprocess.CompletedProcess([], 0, stdout="abc1234 commit msg"),
            subprocess.CompletedProcess([], 0, stdout="feature-branch"),
        ]
        with caplog.at_level("CRITICAL"):
            _log_post_merge_diagnostics("master", None)
        assert "POST-MERGE INVARIANT VIOLATION" in caplog.text
        assert "foo.py" in caplog.text
        assert "feature-branch" in caplog.text

    @patch("pokepoke.worktrees.merge_helpers._run_git", side_effect=Exception("fail"))
    def test_handles_all_git_failures(self, _mock: MagicMock, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level("CRITICAL"):
            _log_post_merge_diagnostics("master", None)
        assert "<unavailable>" in caplog.text

# ---------------------------------------------------------------------------
# is_worktree_merged
# ---------------------------------------------------------------------------

class TestIsWorktreeMerged:
    @patch("pokepoke.worktrees.merge_helpers.get_default_branch", return_value="master")
    @patch("pokepoke.worktrees.merge_helpers._run_git")
    def test_returns_true_when_branch_in_merged_list(
        self, mock_git: MagicMock, _mock_branch: MagicMock,
    ) -> None:
        mock_git.return_value = subprocess.CompletedProcess(
            [], 0, stdout="  task/my-item\n  master\n",
        )
        assert is_worktree_merged("my-item") is True

    @patch("pokepoke.worktrees.merge_helpers.get_default_branch", return_value="master")
    @patch("pokepoke.worktrees.merge_helpers._run_git")
    def test_returns_false_when_branch_not_merged(
        self, mock_git: MagicMock, _mock_branch: MagicMock,
    ) -> None:
        mock_git.return_value = subprocess.CompletedProcess([], 0, stdout="  master\n")
        assert is_worktree_merged("other-item") is False

    @patch("pokepoke.worktrees.merge_helpers._run_git")
    def test_uses_explicit_target_branch(self, mock_git: MagicMock) -> None:
        mock_git.return_value = subprocess.CompletedProcess(
            [], 0, stdout="  task/item-1\n",
        )
        assert is_worktree_merged("item-1", target_branch="develop") is True
        mock_git.assert_called_once_with(
            ["git", "branch", "--merged", "develop"], cwd=None,
        )

    @patch("pokepoke.worktrees.merge_helpers.get_default_branch", return_value="master")
    @patch("pokepoke.worktrees.merge_helpers._run_git")
    def test_returns_false_on_error(
        self, mock_git: MagicMock, _mock_branch: MagicMock,
    ) -> None:
        mock_git.side_effect = subprocess.CalledProcessError(1, "git")
        assert is_worktree_merged("item-1") is False

# ---------------------------------------------------------------------------
# validate_pre_merge_quality
# ---------------------------------------------------------------------------

class TestValidatePreMergeQuality:
    """Tests for the pre-merge quality gate that prevents violations landing on main."""

    @patch("pokepoke.worktrees.merge_helpers._run_git")
    def test_passes_when_files_under_limit(self, mock_git, tmp_path) -> None:
        mock_git.return_value = MagicMock(
            stdout="src/pokepoke/foo.py\n", returncode=0,
        )
        # Create a file under the limit
        src = tmp_path / "src" / "pokepoke"
        src.mkdir(parents=True)
        (src / "foo.py").write_text("\n".join(f"line {i}" for i in range(100)))

        violations = validate_pre_merge_quality(tmp_path, "main")
        assert violations == []

    @patch("pokepoke.worktrees.merge_helpers._run_git")
    def test_fails_when_python_file_exceeds_limit(self, mock_git, tmp_path) -> None:
        mock_git.return_value = MagicMock(
            stdout="src/pokepoke/big.py\n", returncode=0,
        )
        src = tmp_path / "src" / "pokepoke"
        src.mkdir(parents=True)
        # 410 non-blank lines exceeds the 400 limit
        (src / "big.py").write_text("\n".join(f"line {i}" for i in range(410)))

        violations = validate_pre_merge_quality(tmp_path, "main")
        assert len(violations) == 1
        assert "big.py" in violations[0]
        assert "+10" in violations[0]

    @patch("pokepoke.worktrees.merge_helpers._run_git")
    def test_ignores_test_files(self, mock_git, tmp_path) -> None:
        mock_git.return_value = MagicMock(
            stdout="tests/test_big.py\n", returncode=0,
        )
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_big.py").write_text("\n".join(f"line {i}" for i in range(500)))

        violations = validate_pre_merge_quality(tmp_path, "main")
        assert violations == []

    @patch("pokepoke.worktrees.merge_helpers._run_git")
    def test_blank_lines_not_counted(self, mock_git, tmp_path) -> None:
        mock_git.return_value = MagicMock(
            stdout="src/pokepoke/padded.py\n", returncode=0,
        )
        src = tmp_path / "src" / "pokepoke"
        src.mkdir(parents=True)
        # 300 real lines + 200 blank lines = under limit for non-blank
        lines = [f"line {i}" if i % 2 == 0 else "" for i in range(500)]
        (src / "padded.py").write_text("\n".join(lines))

        violations = validate_pre_merge_quality(tmp_path, "main")
        assert violations == []

    @patch("pokepoke.worktrees.merge_helpers._run_git")
    def test_handles_diff_failure_gracefully(self, mock_git, tmp_path) -> None:
        mock_git.side_effect = subprocess.CalledProcessError(1, "git")

        violations = validate_pre_merge_quality(tmp_path, "main")
        assert violations == []

    @patch("pokepoke.worktrees.merge_helpers._run_git")
    def test_desktop_ts_file_over_limit(self, mock_git, tmp_path) -> None:
        mock_git.return_value = MagicMock(
            stdout="desktop/src/components/Big.tsx\n", returncode=0,
        )
        comp = tmp_path / "desktop" / "src" / "components"
        comp.mkdir(parents=True)
        (comp / "Big.tsx").write_text("\n".join(f"line {i}" for i in range(510)))

        violations = validate_pre_merge_quality(tmp_path, "main")
        assert len(violations) == 1
        assert "Big.tsx" in violations[0]
