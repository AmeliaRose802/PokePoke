"""Extended coverage tests for worktree_cleanup module.

Covers uncovered paths in _validate_within_worktrees_dir, _is_junction,
_handle_worktree_removal_error, cleanup_worktree_and_branch, _delete_branch,
retry_failed_cleanups, get_uncleaned_worktree_count, and has_unmerged_worktrees.
"""

import os
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

from pokepoke.worktrees.cleanup_escalation import (
    _nuclear_remove,
    _quarantine_directory,
    retry_failed_cleanups,
)
from pokepoke.worktrees.worktree_cleanup import (
    PathBoundaryError,
    _delete_branch,
    _handle_worktree_removal_error,
    _is_junction,
    _release_known_lock_files,
    _safe_rmtree,
    _validate_within_worktrees_dir,
    cleanup_worktree_and_branch,
    get_uncleaned_worktree_count,
    has_unmerged_worktrees,
)

# ---------------------------------------------------------------------------
# _validate_within_worktrees_dir – repo root discovery failure (lines 54-61)
# ---------------------------------------------------------------------------

class TestValidateWithinWorktreesDirRepoRootFailure:
    """Cover the branch where _find_repo_root raises an exception."""

    @patch("pokepoke.config._find_repo_root", side_effect=RuntimeError("no repo"))
    def test_raises_path_boundary_error_when_repo_root_cannot_be_found(self, _mock_find) -> None:
        """When _find_repo_root fails, PathBoundaryError is raised (lines 55-61)."""
        with pytest.raises(PathBoundaryError, match="Cannot determine repository root"):
            _validate_within_worktrees_dir(Path("some/path"))

    @patch("pokepoke.config._find_repo_root", side_effect=OSError("disk error"))
    def test_raises_path_boundary_error_on_os_error(self, _mock_find) -> None:
        """OSError from _find_repo_root also triggers PathBoundaryError."""
        with pytest.raises(PathBoundaryError, match="Cannot determine repository root"):
            _validate_within_worktrees_dir(Path("/tmp/whatever"))


# ---------------------------------------------------------------------------
# _safe_rmtree – permission recovery in _remove_tree (line 100)
# ---------------------------------------------------------------------------

class TestSafeRmtreePermissionRecovery:
    """Cover the chmod-then-retry path inside _remove_tree (lines 96-102)."""

    def test_permission_recovery_after_chmod(self, tmp_path: Path) -> None:
        """When iterdir fails then succeeds after chmod, tree is still removed."""
        subdir = tmp_path / "target"
        subdir.mkdir()
        (subdir / "file.txt").write_text("data")

        original_iterdir = Path.iterdir
        call_count = {"n": 0}

        def _flaky_iterdir(self_path):
            if self_path == subdir and call_count["n"] == 0:
                call_count["n"] += 1
                raise PermissionError("access denied")
            return original_iterdir(self_path)

        with patch.object(Path, "iterdir", _flaky_iterdir):
            _safe_rmtree(subdir)

        assert not subdir.exists()

    def test_permission_recovery_fails_reraises(self, tmp_path: Path) -> None:
        """When iterdir keeps failing even after chmod, the error propagates."""
        subdir = tmp_path / "target"
        subdir.mkdir()

        def _always_fail(self_path):
            raise PermissionError("permanently broken")

        with patch.object(Path, "iterdir", _always_fail), \
             pytest.raises(PermissionError, match="permanently broken"):
            _safe_rmtree(subdir)


# ---------------------------------------------------------------------------
# _is_junction – fallback path when Path.is_junction doesn't exist (lines 125-140)
# ---------------------------------------------------------------------------

class TestIsJunctionFallback:
    """Cover the ctypes fallback path when Path.is_junction raises AttributeError."""

    def test_fallback_detects_reparse_point(self) -> None:
        """When is_junction unavailable but ctypes reports reparse point (line 138)."""
        path = Mock(spec=Path)
        path.is_junction = Mock(side_effect=AttributeError)
        path.is_symlink.return_value = False
        path.__str__ = lambda self: r"C:\fake\path"

        mock_kernel32 = Mock()
        mock_kernel32.GetFileAttributesW.return_value = 0x400  # FILE_ATTRIBUTE_REPARSE_POINT

        mock_wintypes = MagicMock()
        mock_windll = Mock()
        mock_windll.kernel32 = mock_kernel32

        with patch.dict("sys.modules", {"ctypes.wintypes": mock_wintypes}), \
             patch("ctypes.windll", mock_windll, create=True):
            result = _is_junction(path)

        assert result is True

    def test_fallback_returns_false_for_attrs_negative_one(self) -> None:
        """When GetFileAttributesW returns -1, is_junction returns False (line 137)."""
        path = Mock(spec=Path)
        path.is_junction = Mock(side_effect=AttributeError)
        path.__str__ = lambda self: r"C:\fake\path"

        mock_kernel32 = Mock()
        mock_kernel32.GetFileAttributesW.return_value = -1

        mock_wintypes = MagicMock()
        mock_windll = Mock()
        mock_windll.kernel32 = mock_kernel32

        with patch.dict("sys.modules", {"ctypes.wintypes": mock_wintypes}), \
             patch("ctypes.windll", mock_windll, create=True):
            result = _is_junction(path)

        assert result is False

    def test_fallback_returns_false_when_ctypes_unavailable(self) -> None:
        """When both is_junction and ctypes are unavailable, returns False (line 140)."""
        path = Mock(spec=Path)
        path.is_junction = Mock(side_effect=AttributeError)
        path.__str__ = lambda self: r"C:\fake\path"

        with patch.dict("sys.modules", {"ctypes.wintypes": None}), \
             patch("builtins.__import__", side_effect=ImportError("no ctypes")):
            result = _is_junction(path)

        assert result is False

    def test_fallback_returns_false_for_symlink_with_reparse(self) -> None:
        """Reparse point that is a symlink is NOT a junction (line 138)."""
        path = Mock(spec=Path)
        path.is_junction = Mock(side_effect=AttributeError)
        path.is_symlink.return_value = True
        path.__str__ = lambda self: r"C:\fake\path"

        mock_kernel32 = Mock()
        mock_kernel32.GetFileAttributesW.return_value = 0x400

        mock_wintypes = MagicMock()
        mock_windll = Mock()
        mock_windll.kernel32 = mock_kernel32

        with patch.dict("sys.modules", {"ctypes.wintypes": mock_wintypes}), \
             patch("ctypes.windll", mock_windll, create=True):
            result = _is_junction(path)

        assert result is False

    def test_normal_is_junction_returns_true(self) -> None:
        """When Path.is_junction exists and returns True, we return True (line 128)."""
        path = Mock(spec=Path)
        path.is_junction.return_value = True
        assert _is_junction(path) is True

    def test_normal_is_junction_returns_false(self) -> None:
        """When Path.is_junction exists and returns False, we return False."""
        path = Mock(spec=Path)
        path.is_junction.return_value = False
        assert _is_junction(path) is False


# ---------------------------------------------------------------------------
# _handle_worktree_removal_error (lines 316-358)
# ---------------------------------------------------------------------------

class TestHandleWorktreeRemovalError:
    """Cover the various branches of _handle_worktree_removal_error."""

    def _make_cpe(self, stderr: str) -> subprocess.CalledProcessError:
        exc = subprocess.CalledProcessError(1, "git worktree remove")
        exc.stderr = stderr
        return exc

    @patch("pokepoke.worktrees.worktree_cleanup.force_remove_directory")
    def test_not_a_working_tree_returns_early(self, mock_force) -> None:
        """'not a working tree' in stderr causes early return (line 328)."""
        exc = self._make_cpe("fatal: not a working tree")
        _handle_worktree_removal_error(exc, Path("/tmp/wt"), "wt-1", False, False)
        mock_force.assert_not_called()

    @patch("pokepoke.worktrees.worktree_cleanup.force_remove_directory")
    def test_no_such_file_returns_early(self, mock_force) -> None:
        """'no such file' in stderr causes early return (line 328)."""
        exc = self._make_cpe("fatal: No such file or directory")
        _handle_worktree_removal_error(exc, Path("/tmp/wt"), "wt-1", False, False)
        mock_force.assert_not_called()

    @patch("pokepoke.worktrees.worktree_cleanup.add_uncleaned_worktree")
    @patch("pokepoke.worktrees.worktree_cleanup.force_remove_directory", return_value=False)
    def test_non_lock_error_logs_generic_message(self, mock_force, mock_add) -> None:
        """Non-lock error triggers generic log message (line 337) and manifest add."""
        exc = self._make_cpe("some other git error")
        wt_path = Mock(spec=Path)
        wt_path.exists.return_value = True
        wt_path.__str__ = lambda self: "/tmp/wt"

        _handle_worktree_removal_error(exc, wt_path, "wt-1", False, False)

        mock_force.assert_called_once_with(wt_path, max_attempts=1)
        mock_add.assert_called_once()

    @patch("pokepoke.worktrees.worktree_cleanup.remove_from_manifest")
    @patch("pokepoke.worktrees.worktree_cleanup.force_remove_directory", return_value=True)
    def test_force_remove_success_removes_from_manifest(self, mock_force, mock_remove) -> None:
        """Successful force remove cleans manifest and returns (lines 343-348)."""
        exc = self._make_cpe("some error")
        _handle_worktree_removal_error(exc, Path("/tmp/wt"), "wt-1", False, True)

        mock_remove.assert_called_once_with("wt-1")

    @patch("pokepoke.worktrees.worktree_cleanup.remove_from_manifest")
    @patch("pokepoke.worktrees.worktree_cleanup.force_remove_directory", return_value=True)
    def test_force_remove_success_no_worktree_id_skips_manifest(self, mock_force, mock_remove) -> None:
        """When worktree_id is None, skip manifest removal (line 344 branch)."""
        exc = self._make_cpe("some error")
        _handle_worktree_removal_error(exc, Path("/tmp/wt"), None, False, True)

        mock_remove.assert_not_called()

    @patch("pokepoke.worktrees.worktree_cleanup.add_uncleaned_worktree")
    @patch("pokepoke.worktrees.worktree_cleanup.force_remove_directory", return_value=False)
    def test_post_merge_failure_logs_merge_context(self, mock_force, mock_add) -> None:
        """Post-merge path logs merge-specific warning (lines 350-352)."""
        exc = self._make_cpe("error")
        wt_path = Mock(spec=Path)
        wt_path.exists.return_value = True
        wt_path.__str__ = lambda self: "/tmp/wt"

        _handle_worktree_removal_error(exc, wt_path, "wt-1", True, False)
        mock_add.assert_called_once()
        # Verify reason prefix
        args = mock_add.call_args
        assert "Post-merge" in args[0][2]

    @patch("pokepoke.worktrees.worktree_cleanup.add_uncleaned_worktree")
    @patch("pokepoke.worktrees.worktree_cleanup.force_remove_directory", return_value=False)
    def test_non_post_merge_failure_logs_generic_warning(self, mock_force, mock_add) -> None:
        """Non-post-merge path logs generic warning (line 354)."""
        exc = self._make_cpe("error")
        wt_path = Mock(spec=Path)
        wt_path.exists.return_value = True
        wt_path.__str__ = lambda self: "/tmp/wt"

        _handle_worktree_removal_error(exc, wt_path, "wt-1", False, False)
        mock_add.assert_called_once()
        args = mock_add.call_args
        assert "Worktree removal" in args[0][2]

    @patch("pokepoke.worktrees.worktree_cleanup.add_uncleaned_worktree")
    @patch("pokepoke.worktrees.worktree_cleanup.force_remove_directory", return_value=False)
    def test_no_manifest_add_when_worktree_id_none(self, mock_force, mock_add) -> None:
        """When worktree_id is None, do not add to manifest (line 356 guard)."""
        exc = self._make_cpe("error")
        wt_path = Mock(spec=Path)
        wt_path.exists.return_value = True
        wt_path.__str__ = lambda self: "/tmp/wt"

        _handle_worktree_removal_error(exc, wt_path, None, False, False)
        mock_add.assert_not_called()

    @patch("pokepoke.worktrees.worktree_cleanup.add_uncleaned_worktree")
    @patch("pokepoke.worktrees.worktree_cleanup.force_remove_directory", return_value=False)
    def test_no_manifest_add_when_path_gone(self, mock_force, mock_add) -> None:
        """When worktree path no longer exists, do not add to manifest."""
        exc = self._make_cpe("error")
        wt_path = Mock(spec=Path)
        wt_path.exists.return_value = False
        wt_path.__str__ = lambda self: "/tmp/wt"

        _handle_worktree_removal_error(exc, wt_path, "wt-1", False, False)
        mock_add.assert_not_called()


# ---------------------------------------------------------------------------
# cleanup_worktree_and_branch (lines 361-409)
# ---------------------------------------------------------------------------

class TestCleanupWorktreeAndBranch:
    """Cover uncovered paths in cleanup_worktree_and_branch."""

    @patch("pokepoke.worktrees.worktree_cleanup._delete_branch", return_value=True)
    @patch("pokepoke.worktrees.worktree_cleanup._run_git")
    def test_worktree_id_from_path_name(self, mock_git, mock_del) -> None:
        """When branch doesn't start with prefix and path given, id comes from path.name (lines 385-386)."""
        wt_path = Mock(spec=Path)
        wt_path.exists.return_value = False
        wt_path.name = "task-abc-123"

        result = cleanup_worktree_and_branch(
            wt_path, "some-other-branch", force=False,
        )

        assert result is True
        mock_git.assert_not_called()  # path doesn't exist

    @patch("pokepoke.worktrees.worktree_cleanup._delete_branch", return_value=True)
    @patch("pokepoke.worktrees.worktree_cleanup.remove_from_manifest")
    @patch("pokepoke.worktrees.worktree_cleanup._run_git")
    def test_force_flag_appended(self, mock_git, mock_manifest, mock_del) -> None:
        """When force=True, --force is appended to git worktree remove (line 393)."""
        wt_path = Mock(spec=Path)
        wt_path.exists.return_value = True
        wt_path.__str__ = lambda self: "/tmp/wt"

        cleanup_worktree_and_branch(
            wt_path, "task/my-task", force=True, print_success=True,
        )

        call_args = mock_git.call_args[0][0]
        assert "--force" in call_args

    @patch("pokepoke.worktrees.worktree_cleanup._delete_branch", return_value=True)
    @patch("pokepoke.worktrees.worktree_cleanup._run_git")
    def test_returns_delete_branch_result(self, mock_git, mock_del) -> None:
        """cleanup_worktree_and_branch returns result of _delete_branch (line 409)."""
        result = cleanup_worktree_and_branch(
            None, "task/my-task", force=False,
        )
        assert result is True
        mock_del.assert_called_once()

    @patch("pokepoke.worktrees.worktree_cleanup._delete_branch", return_value=False)
    @patch("pokepoke.worktrees.worktree_cleanup._run_git")
    def test_returns_false_from_delete_branch(self, mock_git, mock_del) -> None:
        """When _delete_branch fails, the overall result is False."""
        mock_del.return_value = False
        result = cleanup_worktree_and_branch(
            None, "task/my-task", force=False,
        )
        assert result is False

    @patch("pokepoke.worktrees.worktree_cleanup._delete_branch")
    @patch("pokepoke.worktrees.worktree_cleanup._handle_worktree_removal_error")
    @patch("pokepoke.worktrees.worktree_cleanup._run_git", side_effect=subprocess.CalledProcessError(1, "git"))
    def test_removal_error_delegates_to_handler(self, mock_git, mock_handler, mock_del) -> None:
        """CalledProcessError delegates to _handle_worktree_removal_error."""
        wt_path = Mock(spec=Path)
        wt_path.exists.side_effect = [True, False]  # exists then removed
        wt_path.__str__ = lambda self: "/tmp/wt"

        cleanup_worktree_and_branch(wt_path, "task/my-task")

        mock_handler.assert_called_once()


# ---------------------------------------------------------------------------
# _delete_branch (lines 418-450)
# ---------------------------------------------------------------------------

class TestDeleteBranch:
    """Cover all branches of _delete_branch."""

    @patch("pokepoke.worktrees.worktree_cleanup._run_git")
    def test_successful_deletion(self, mock_git) -> None:
        """Primary branch deleted successfully (line 430-433)."""
        result = _delete_branch("task/x", None, False, True, False)
        assert result is True
        call_args = mock_git.call_args[0][0]
        assert "-d" in call_args

    @patch("pokepoke.worktrees.worktree_cleanup._run_git")
    def test_force_uses_capital_d(self, mock_git) -> None:
        """When force=True, -D is used instead of -d (line 427)."""
        _delete_branch("task/x", None, True, False, False)
        call_args = mock_git.call_args[0][0]
        assert "-D" in call_args

    @patch("pokepoke.worktrees.worktree_cleanup._run_git")
    def test_no_fallback_returns_true_on_error(self, mock_git) -> None:
        """When primary fails and no fallback, returns True with warning (line 435-437)."""
        mock_git.side_effect = subprocess.CalledProcessError(1, "git", stderr="error")
        result = _delete_branch("task/x", None, False, False, False)
        assert result is True

    @patch("pokepoke.worktrees.worktree_cleanup._run_git")
    def test_fallback_branch_deleted_successfully(self, mock_git) -> None:
        """Fallback branch deleted on second try (lines 440-444)."""
        mock_git.side_effect = [
            subprocess.CalledProcessError(1, "git", stderr="error"),
            None,  # fallback succeeds
        ]
        result = _delete_branch("task/x", "fallback-branch", False, True, False)
        assert result is True

    @patch("pokepoke.worktrees.worktree_cleanup._run_git")
    def test_fallback_not_found_returns_true(self, mock_git) -> None:
        """Fallback 'not found' error returns True (lines 446-448)."""
        exc = subprocess.CalledProcessError(1, "git", stderr="error: branch 'x' not found")
        mock_git.side_effect = [
            subprocess.CalledProcessError(1, "git", stderr="error"),
            exc,
        ]
        result = _delete_branch("task/x", "fallback-branch", False, False, False)
        assert result is True

    @patch("pokepoke.worktrees.worktree_cleanup._run_git")
    def test_fallback_does_not_exist_returns_true(self, mock_git) -> None:
        """Fallback 'does not exist' error returns True (line 447)."""
        exc = subprocess.CalledProcessError(1, "git", stderr="branch does not exist")
        mock_git.side_effect = [
            subprocess.CalledProcessError(1, "git", stderr="error"),
            exc,
        ]
        result = _delete_branch("task/x", "fallback-branch", False, False, False)
        assert result is True

    @patch("pokepoke.worktrees.worktree_cleanup._run_git")
    def test_fallback_real_error_returns_false(self, mock_git) -> None:
        """Fallback with a real error returns False (lines 449-450)."""
        exc = subprocess.CalledProcessError(1, "git", stderr="protected branch")
        mock_git.side_effect = [
            subprocess.CalledProcessError(1, "git", stderr="error"),
            exc,
        ]
        result = _delete_branch("task/x", "fallback-branch", False, False, False)
        assert result is False


# ---------------------------------------------------------------------------
# retry_failed_cleanups (lines 465-507)
# ---------------------------------------------------------------------------

class TestRetryFailedCleanups:
    """Cover retry_failed_cleanups function."""

    @patch("pokepoke.worktrees.worktree_cleanup.load_worktree_manifest", return_value={})
    def test_empty_manifest_returns_zero(self, mock_load) -> None:
        """Empty manifest returns 0 immediately."""
        assert retry_failed_cleanups() == 0

    @patch("pokepoke.worktrees.worktree_cleanup.remove_from_manifest")
    @patch("pokepoke.worktrees.worktree_cleanup.force_remove_directory", return_value=True)
    @patch("pokepoke.worktrees.worktree_cleanup.load_worktree_manifest")
    def test_removes_existing_worktree(self, mock_load, mock_force, mock_remove) -> None:
        """Existing worktree that force_remove succeeds on is cleaned."""
        mock_load.return_value = {
            "wt-1": {"path": "/tmp/wt1", "reason": "failed", "timestamp": "2025-01-01"},
        }
        with patch.object(Path, "exists", return_value=True):
            result = retry_failed_cleanups()

        assert result == 1
        mock_remove.assert_called_once_with("wt-1")

    @patch("pokepoke.worktrees.worktree_cleanup.remove_from_manifest")
    @patch("pokepoke.worktrees.worktree_cleanup.load_worktree_manifest")
    def test_removes_already_gone_worktree(self, mock_load, mock_remove) -> None:
        """Worktree that no longer exists is removed from manifest."""
        mock_load.return_value = {
            "wt-1": {"path": "/tmp/gone", "reason": "failed", "timestamp": "2025-01-01"},
        }
        with patch.object(Path, "exists", return_value=False):
            result = retry_failed_cleanups()

        assert result == 1
        mock_remove.assert_called_once_with("wt-1")

    @patch("pokepoke.worktrees.worktree_cleanup.add_uncleaned_worktree")
    @patch("pokepoke.worktrees.worktree_cleanup.remove_from_manifest")
    @patch("pokepoke.worktrees.worktree_cleanup.force_remove_directory", return_value=False)
    @patch("pokepoke.worktrees.worktree_cleanup.load_worktree_manifest")
    def test_force_remove_failure_keeps_entry(self, mock_load, mock_force, mock_remove, mock_add) -> None:
        """When force_remove fails, entry stays in manifest and failure count is bumped."""
        mock_load.return_value = {
            "wt-1": {"path": "/tmp/wt1", "reason": "failed", "timestamp": "2025-01-01", "failure_count": "1"},
        }
        with patch.object(Path, "exists", return_value=True):
            result = retry_failed_cleanups()

        assert result == 0
        mock_remove.assert_not_called()
        mock_add.assert_called_once_with("wt-1", str(Path("/tmp/wt1")), "failed")

    @patch("pokepoke.worktrees.worktree_cleanup.remove_from_manifest")
    @patch("pokepoke.worktrees.worktree_cleanup.force_remove_directory", return_value=True)
    @patch("pokepoke.worktrees.worktree_cleanup.load_worktree_manifest")
    def test_mixed_results_returns_cleaned_count(self, mock_load, mock_force, mock_remove) -> None:
        """Mixed successes and failures returns correct cleaned count."""
        mock_load.return_value = {
            "wt-ok": {"path": "/tmp/ok", "reason": "r", "timestamp": "t"},
            "wt-fail": {"path": "/tmp/fail", "reason": "r", "timestamp": "t"},
        }

        def _exists_side_effect(self):
            return str(self) == "/tmp/fail"

        # wt-ok: path doesn't exist -> cleaned; wt-fail: exists -> force_remove succeeds
        exists_orig = Path.exists

        def smart_exists(self):
            s = str(self)
            if s == "/tmp/ok":
                return False
            if s == "/tmp/fail":
                return True
            return exists_orig(self)

        with patch.object(Path, "exists", smart_exists):
            result = retry_failed_cleanups()

        assert result == 2


    @patch("pokepoke.worktrees.worktree_cleanup.remove_from_manifest")
    @patch("pokepoke.worktrees.cleanup_escalation._nuclear_remove", return_value=True)
    @patch("pokepoke.worktrees.worktree_cleanup.load_worktree_manifest")
    def test_nuclear_option_triggered_after_threshold(self, mock_load, mock_nuclear, mock_remove) -> None:
        """After 3+ failures, nuclear removal is used instead of force_remove."""
        mock_load.return_value = {
            "wt-1": {"path": "/tmp/wt1", "reason": "failed", "timestamp": "2025-01-01", "failure_count": "3"},
        }
        with patch.object(Path, "exists", return_value=True):
            result = retry_failed_cleanups()

        assert result == 1
        mock_nuclear.assert_called_once()
        mock_remove.assert_called_once_with("wt-1")

    @patch("pokepoke.worktrees.worktree_cleanup.add_uncleaned_worktree")
    @patch("pokepoke.worktrees.worktree_cleanup.remove_from_manifest")
    @patch("pokepoke.worktrees.cleanup_escalation._quarantine_directory", return_value=True)
    @patch("pokepoke.worktrees.cleanup_escalation._nuclear_remove", return_value=False)
    @patch("pokepoke.worktrees.worktree_cleanup.load_worktree_manifest")
    def test_quarantine_used_when_nuclear_fails(self, mock_load, mock_nuclear, mock_quarantine, mock_remove, mock_add) -> None:
        """When nuclear removal fails, directory is quarantined."""
        mock_load.return_value = {
            "wt-1": {"path": "/tmp/wt1", "reason": "failed", "timestamp": "2025-01-01", "failure_count": "5"},
        }
        with patch.object(Path, "exists", return_value=True):
            result = retry_failed_cleanups()

        assert result == 1
        mock_nuclear.assert_called_once()
        mock_quarantine.assert_called_once()
        mock_remove.assert_called_once_with("wt-1")

    @patch("pokepoke.worktrees.worktree_cleanup.add_uncleaned_worktree")
    @patch("pokepoke.worktrees.worktree_cleanup.remove_from_manifest")
    @patch("pokepoke.worktrees.cleanup_escalation._quarantine_directory", return_value=False)
    @patch("pokepoke.worktrees.cleanup_escalation._nuclear_remove", return_value=False)
    @patch("pokepoke.worktrees.worktree_cleanup.load_worktree_manifest")
    def test_all_escalations_fail_bumps_count(self, mock_load, mock_nuclear, mock_quarantine, mock_remove, mock_add) -> None:
        """When nuclear and quarantine both fail, failure count is bumped."""
        mock_load.return_value = {
            "wt-1": {"path": "/tmp/wt1", "reason": "failed", "timestamp": "2025-01-01", "failure_count": "4"},
        }
        with patch.object(Path, "exists", return_value=True):
            result = retry_failed_cleanups()

        assert result == 0
        mock_remove.assert_not_called()
        mock_add.assert_called_once_with("wt-1", str(Path("/tmp/wt1")), "failed")


# ---------------------------------------------------------------------------
# _release_known_lock_files
# ---------------------------------------------------------------------------

class TestReleaseKnownLockFiles:
    """Cover _release_known_lock_files function."""

    def test_removes_existing_lock_files(self, tmp_path: Path) -> None:
        """Lock files in .git/ are removed."""
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        lock = git_dir / "index.lock"
        lock.write_text("lock")

        removed = _release_known_lock_files(tmp_path)

        assert len(removed) == 1
        assert not lock.exists()

    def test_no_git_dir_returns_empty(self, tmp_path: Path) -> None:
        """No .git directory returns empty list."""
        removed = _release_known_lock_files(tmp_path)
        assert removed == []

    def test_non_lock_files_left_alone(self, tmp_path: Path) -> None:
        """Files that are not known lock files are untouched."""
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        other_file = git_dir / "config"
        other_file.write_text("data")

        _release_known_lock_files(tmp_path)

        assert other_file.exists()


# ---------------------------------------------------------------------------
# _safe_rmtree error logging
# ---------------------------------------------------------------------------

class TestSafeRmtreeErrorLogging:
    """Cover _safe_rmtree failed file logging."""

    def test_logs_specific_failed_files(self, tmp_path: Path, caplog) -> None:
        """When a file cannot be deleted, it is logged with the reason."""
        subdir = tmp_path / "target"
        subdir.mkdir()
        (subdir / "good.txt").write_text("ok")
        (subdir / "locked.txt").write_text("locked")

        original_remove = os.remove

        def _selective_remove(path):
            if "locked.txt" in path:
                raise OSError("[WinError 32] being used by another process")
            return original_remove(path)

        import logging
        with patch("os.remove", side_effect=_selective_remove), \
             caplog.at_level(logging.WARNING), \
             pytest.raises(OSError):
            _safe_rmtree(subdir)

        assert any("locked.txt" in r.message for r in caplog.records)
        assert any("could not be removed" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# _nuclear_remove
# ---------------------------------------------------------------------------

class TestNuclearRemove:
    """Cover _nuclear_remove function."""

    def test_removes_directory_with_shutil(self, tmp_path: Path) -> None:
        """shutil.rmtree succeeds and removes the directory."""
        target = tmp_path / "nuke-me"
        target.mkdir()
        (target / "file.txt").write_text("data")

        result = _nuclear_remove(target)

        assert result is True
        assert not target.exists()

    def test_returns_false_when_all_fail(self, tmp_path: Path) -> None:
        """Returns False when directory cannot be removed by any method."""
        target = tmp_path / "stubborn"
        target.mkdir()

        with patch("shutil.rmtree", side_effect=OSError("fail")), \
             patch("subprocess.run", side_effect=OSError("fail")):
            result = _nuclear_remove(target)

        assert result is False


# ---------------------------------------------------------------------------
# _quarantine_directory
# ---------------------------------------------------------------------------

class TestQuarantineDirectory:
    """Cover _quarantine_directory function."""

    @patch("pokepoke.worktrees.cleanup_escalation._get_quarantine_dir")
    def test_moves_directory_to_quarantine(self, mock_qdir, tmp_path: Path) -> None:
        """Directory is renamed into quarantine location."""
        qdir = tmp_path / "quarantine"
        qdir.mkdir()
        mock_qdir.return_value = qdir

        target = tmp_path / "target"
        target.mkdir()
        (target / "file.txt").write_text("data")

        result = _quarantine_directory(target, "wt-1")

        assert result is True
        assert not target.exists()
        quarantined = list(qdir.iterdir())
        assert len(quarantined) == 1
        assert quarantined[0].name.startswith("wt-1_")

    def test_nonexistent_directory_returns_true(self, tmp_path: Path) -> None:
        """If directory doesn't exist, returns True."""
        target = tmp_path / "gone"
        result = _quarantine_directory(target, "wt-1")
        assert result is True

    @patch("pokepoke.worktrees.cleanup_escalation._get_quarantine_dir")
    def test_rename_failure_returns_false(self, mock_qdir, tmp_path: Path) -> None:
        """If rename fails, returns False."""
        mock_qdir.return_value = tmp_path / "quarantine"
        (tmp_path / "quarantine").mkdir()

        target = tmp_path / "target"
        target.mkdir()

        with patch.object(Path, "rename", side_effect=OSError("access denied")):
            result = _quarantine_directory(target, "wt-1")

        assert result is False


# ---------------------------------------------------------------------------
# get_uncleaned_worktree_count (lines 510-513)
# ---------------------------------------------------------------------------

class TestGetUncleanedWorktreeCount:
    """Cover get_uncleaned_worktree_count."""

    @patch("pokepoke.worktrees.worktree_cleanup.load_worktree_manifest", return_value={})
    def test_empty_manifest(self, mock_load) -> None:
        """Empty manifest returns 0 (line 512-513)."""
        assert get_uncleaned_worktree_count() == 0

    @patch("pokepoke.worktrees.worktree_cleanup.load_worktree_manifest")
    def test_non_empty_manifest(self, mock_load) -> None:
        """Non-empty manifest returns correct count."""
        mock_load.return_value = {"a": {}, "b": {}, "c": {}}
        assert get_uncleaned_worktree_count() == 3


# ---------------------------------------------------------------------------
# has_unmerged_worktrees (lines 516-527)
# ---------------------------------------------------------------------------

class TestHasUnmergedWorktrees:
    """Cover has_unmerged_worktrees."""

    @patch("pokepoke.worktrees.worktree_cleanup.load_worktree_manifest", return_value={})
    @patch("pokepoke.git.git_operations.list_worktrees", return_value=[])
    def test_no_worktrees_and_empty_manifest(self, mock_list, mock_load) -> None:
        """No worktrees and empty manifest returns False (lines 518-527)."""
        assert has_unmerged_worktrees() is False

    @patch("pokepoke.git.git_operations.list_worktrees")
    def test_task_worktree_found(self, mock_list) -> None:
        """Task worktree detected returns True (lines 520-525)."""
        mock_list.return_value = [
            {"path": "/repo/worktrees/task-abc-123"},
        ]
        assert has_unmerged_worktrees() is True

    @patch("pokepoke.worktrees.worktree_cleanup.load_worktree_manifest")
    @patch("pokepoke.git.git_operations.list_worktrees", return_value=[])
    def test_manifest_entries_returns_true(self, mock_list, mock_load) -> None:
        """No live worktrees but manifest has entries returns True (line 527)."""
        mock_load.return_value = {"wt-1": {"path": "/tmp/wt"}}
        assert has_unmerged_worktrees() is True

    @patch("pokepoke.worktrees.worktree_cleanup.load_worktree_manifest", return_value={})
    @patch("pokepoke.git.git_operations.list_worktrees")
    def test_non_task_worktree_ignored(self, mock_list, mock_load) -> None:
        """Worktrees that are not task worktrees are ignored."""
        mock_list.return_value = [
            {"path": "/repo/worktrees/some-other-thing"},
        ]
        assert has_unmerged_worktrees() is False
