"""Comprehensive coverage tests for pokepoke.worktrees.worktree_cleanup.

Covers force_remove_directory, manifest operations, _handle_worktree_removal_error,
cleanup_worktree_and_branch, _delete_branch, cleanup_after_merge,
get_uncleaned_worktree_count, and has_unmerged_worktrees.
"""

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from pokepoke.worktrees.worktree_cleanup import (
    PathBoundaryError,
    SymlinkFoundError,
    _delete_branch,
    _handle_worktree_removal_error,
    add_uncleaned_worktree,
    cleanup_after_merge,
    cleanup_worktree_and_branch,
    force_remove_directory,
    get_uncleaned_worktree_count,
    has_unmerged_worktrees,
    remove_from_manifest,
)

MODULE = "pokepoke.worktrees.worktree_cleanup"


# ---------------------------------------------------------------------------
# force_remove_directory
# ---------------------------------------------------------------------------
class TestForceRemoveDirectory:
    """Tests for force_remove_directory."""

    @patch(f"{MODULE}._is_junction", return_value=False)
    @patch(f"{MODULE}._validate_within_worktrees_dir")
    @patch(f"{MODULE}.run_git")
    def test_success_first_attempt(self, mock_run_git, mock_validate, mock_junction, tmp_path):
        """git worktree remove succeeds on the first attempt."""
        d = tmp_path / "worktrees" / "task-abc"
        d.mkdir(parents=True)

        result = force_remove_directory(d, max_attempts=3)

        assert result is True
        mock_run_git.assert_called_once_with(
            ["git", "worktree", "remove", "--force", str(d)]
        )

    @patch(f"{MODULE}._is_junction", return_value=False)
    @patch(f"{MODULE}._validate_within_worktrees_dir", side_effect=PathBoundaryError("outside"))
    def test_boundary_validation_raises(self, mock_validate, mock_junction, tmp_path):
        """PathBoundaryError raised when path is outside worktrees dir."""
        d = tmp_path / "evil"
        d.mkdir()

        with pytest.raises(PathBoundaryError, match="outside"):
            force_remove_directory(d)

    @patch(f"{MODULE}._is_junction", return_value=True)
    @patch(f"{MODULE}._validate_within_worktrees_dir")
    def test_symlink_detection_raises(self, mock_validate, mock_junction, tmp_path):
        """SymlinkFoundError raised when path is a junction."""
        d = tmp_path / "worktrees" / "task-link"
        d.mkdir(parents=True)

        with pytest.raises(SymlinkFoundError, match="symlink or junction"):
            force_remove_directory(d)

    @patch(f"{MODULE}.sleep_with_backoff", return_value=0.0)
    @patch(f"{MODULE}._is_junction", return_value=False)
    @patch(f"{MODULE}._validate_within_worktrees_dir")
    @patch(f"{MODULE}._safe_rmtree")
    @patch(f"{MODULE}.run_git")
    def test_git_remove_fails_fallback_rmtree_succeeds(
        self, mock_run_git, mock_rmtree, mock_validate, mock_junction, mock_sleep, tmp_path
    ):
        """When git worktree remove fails, fallback to _safe_rmtree succeeds."""
        d = tmp_path / "worktrees" / "task-fb"
        d.mkdir(parents=True)

        err = subprocess.CalledProcessError(1, "git")
        err.stderr = "some error"
        mock_run_git.side_effect = [err, MagicMock()]  # fail first, prune ok

        result = force_remove_directory(d, max_attempts=1)

        assert result is True
        mock_rmtree.assert_called_once_with(d)

    @patch(f"{MODULE}.sleep_with_backoff", return_value=0.0)
    @patch(f"{MODULE}._is_junction", return_value=False)
    @patch(f"{MODULE}._validate_within_worktrees_dir")
    @patch(f"{MODULE}._safe_rmtree", side_effect=PermissionError("Access is denied"))
    @patch(f"{MODULE}.run_git")
    @patch(f"{MODULE}._is_windows_lock_error", return_value=True)
    def test_windows_lock_error_retry(
        self, mock_is_lock, mock_run_git, mock_rmtree, mock_validate,
        mock_junction, mock_sleep, tmp_path
    ):
        """Windows lock error triggers retry loop."""
        d = tmp_path / "worktrees" / "task-lock"
        d.mkdir(parents=True)

        err = subprocess.CalledProcessError(1, "git")
        err.stderr = "Access is denied"
        mock_run_git.side_effect = err

        with patch(f"{MODULE}.wait_for_process_cleanup", create=True):
            result = force_remove_directory(d, max_attempts=2)

        assert result is False

    @patch(f"{MODULE}.sleep_with_backoff", return_value=0.0)
    @patch(f"{MODULE}._is_junction", return_value=False)
    @patch(f"{MODULE}._validate_within_worktrees_dir")
    @patch(f"{MODULE}._safe_rmtree", side_effect=OSError("nope"))
    @patch(f"{MODULE}.run_git", side_effect=subprocess.CalledProcessError(1, "git", stderr="fail"))
    def test_all_attempts_fail_returns_false(
        self, mock_run_git, mock_rmtree, mock_validate, mock_junction, mock_sleep, tmp_path
    ):
        """Returns False when all attempts are exhausted."""
        d = tmp_path / "worktrees" / "task-fail"
        d.mkdir(parents=True)

        with patch(f"{MODULE}.wait_for_process_cleanup", create=True):
            result = force_remove_directory(d, max_attempts=2)

        assert result is False

    @patch(f"{MODULE}.sleep_with_backoff", return_value=0.0)
    @patch(f"{MODULE}._is_junction", return_value=False)
    @patch(f"{MODULE}._validate_within_worktrees_dir")
    @patch(f"{MODULE}._safe_rmtree")
    @patch(f"{MODULE}.run_git")
    def test_timeout_on_git_worktree_remove(
        self, mock_run_git, mock_rmtree, mock_validate, mock_junction, mock_sleep, tmp_path
    ):
        """TimeoutExpired on git worktree remove triggers fallback."""
        d = tmp_path / "worktrees" / "task-to"
        d.mkdir(parents=True)

        mock_run_git.side_effect = [
            subprocess.TimeoutExpired("git", 30),
            MagicMock(),  # prune
        ]

        result = force_remove_directory(d, max_attempts=1)

        assert result is True
        mock_rmtree.assert_called_once_with(d)


# ---------------------------------------------------------------------------
# add_uncleaned_worktree / remove_from_manifest
# ---------------------------------------------------------------------------
class TestAddUncleanedWorktree:
    """Tests for add_uncleaned_worktree."""

    @patch(f"{MODULE}.save_worktree_manifest")
    @patch(f"{MODULE}.load_worktree_manifest", return_value={})
    @patch("pokepoke.worktrees.coordination.manifest_lock")
    def test_new_entry(self, mock_lock, mock_load, mock_save):
        """Adds a new entry with failure_count=1."""
        from contextlib import nullcontext
        mock_lock.return_value = nullcontext()

        add_uncleaned_worktree("wt-1", "/path/to/wt", "removal failed")

        saved = mock_save.call_args[0][0]
        assert "wt-1" in saved
        assert saved["wt-1"]["path"] == "/path/to/wt"
        assert saved["wt-1"]["reason"] == "removal failed"
        assert saved["wt-1"]["failure_count"] == "1"

    @patch(f"{MODULE}.save_worktree_manifest")
    @patch(f"{MODULE}.load_worktree_manifest", return_value={
        "wt-2": {"path": "/p", "reason": "r", "timestamp": "t", "failure_count": "3"},
    })
    @patch("pokepoke.worktrees.coordination.manifest_lock")
    def test_existing_entry_increments_failure_count(self, mock_lock, mock_load, mock_save):
        """Existing entry has failure_count incremented."""
        from contextlib import nullcontext
        mock_lock.return_value = nullcontext()

        add_uncleaned_worktree("wt-2", "/p", "retry")

        saved = mock_save.call_args[0][0]
        assert saved["wt-2"]["failure_count"] == "4"

    @patch(f"{MODULE}.save_worktree_manifest")
    @patch(f"{MODULE}.load_worktree_manifest", return_value={
        "wt-3": {"path": "/p", "reason": "r", "timestamp": "t", "failure_count": "bad"},
    })
    @patch("pokepoke.worktrees.coordination.manifest_lock")
    def test_existing_entry_invalid_failure_count_resets(self, mock_lock, mock_load, mock_save):
        """Invalid failure_count resets to 1."""
        from contextlib import nullcontext
        mock_lock.return_value = nullcontext()

        add_uncleaned_worktree("wt-3", "/p", "retry")

        saved = mock_save.call_args[0][0]
        assert saved["wt-3"]["failure_count"] == "1"


class TestRemoveFromManifest:
    """Tests for remove_from_manifest."""

    @patch(f"{MODULE}.save_worktree_manifest")
    @patch(f"{MODULE}.load_worktree_manifest", return_value={
        "wt-x": {"path": "/p", "reason": "r", "timestamp": "t", "failure_count": "1"},
    })
    @patch("pokepoke.worktrees.coordination.manifest_lock")
    def test_existing_entry_removed(self, mock_lock, mock_load, mock_save):
        """Removes an existing entry and saves."""
        from contextlib import nullcontext
        mock_lock.return_value = nullcontext()

        remove_from_manifest("wt-x")

        saved = mock_save.call_args[0][0]
        assert "wt-x" not in saved

    @patch(f"{MODULE}.save_worktree_manifest")
    @patch(f"{MODULE}.load_worktree_manifest", return_value={})
    @patch("pokepoke.worktrees.coordination.manifest_lock")
    def test_nonexistent_entry_noop(self, mock_lock, mock_load, mock_save):
        """Non-existent entry is a no-op (save not called)."""
        from contextlib import nullcontext
        mock_lock.return_value = nullcontext()

        remove_from_manifest("wt-missing")

        mock_save.assert_not_called()


# ---------------------------------------------------------------------------
# _handle_worktree_removal_error
# ---------------------------------------------------------------------------
class TestHandleWorktreeRemovalError:
    """Tests for _handle_worktree_removal_error."""

    def test_not_a_working_tree_ignored(self, tmp_path):
        """'not a working tree' error is silently ignored."""
        err = subprocess.CalledProcessError(128, "git")
        err.stderr = "fatal: not a working tree"
        wt = tmp_path / "worktrees" / "task-nwt"
        wt.mkdir(parents=True)

        # Should not raise or call force_remove_directory
        with patch(f"{MODULE}.force_remove_directory") as mock_frd:
            _handle_worktree_removal_error(err, wt, "task-nwt", False, False)
            mock_frd.assert_not_called()

    @patch(f"{MODULE}.remove_from_manifest")
    @patch(f"{MODULE}.force_remove_directory", return_value=True)
    def test_force_remove_succeeds(self, mock_frd, mock_rm, tmp_path):
        """Force remove succeeds and removes from manifest."""
        err = subprocess.CalledProcessError(1, "git")
        err.stderr = "directory not empty"
        wt = tmp_path / "worktrees" / "task-frs"
        wt.mkdir(parents=True)

        _handle_worktree_removal_error(err, wt, "task-frs", False, True)

        mock_frd.assert_called_once_with(wt, max_attempts=1)
        mock_rm.assert_called_once_with("task-frs")

    @patch(f"{MODULE}.add_uncleaned_worktree")
    @patch(f"{MODULE}.force_remove_directory", return_value=False)
    def test_force_remove_fails_post_merge(self, mock_frd, mock_add, tmp_path):
        """Force remove fails with post_merge=True logs warning."""
        err = subprocess.CalledProcessError(1, "git")
        err.stderr = "locked"
        wt = tmp_path / "worktrees" / "task-pm"
        wt.mkdir(parents=True)

        _handle_worktree_removal_error(err, wt, "task-pm", post_merge=True, print_success=False)

        mock_frd.assert_called_once()
        # worktree_path.exists() is True → adds to manifest
        mock_add.assert_called_once_with("task-pm", str(wt), "Post-merge cleanup failed: locked")

    @patch(f"{MODULE}.add_uncleaned_worktree")
    @patch(f"{MODULE}.force_remove_directory", return_value=False)
    def test_force_remove_fails_adds_to_manifest(self, mock_frd, mock_add, tmp_path):
        """Force remove fails, adds to uncleaned manifest."""
        err = subprocess.CalledProcessError(1, "git")
        err.stderr = "cannot remove"
        wt = tmp_path / "worktrees" / "task-man"
        wt.mkdir(parents=True)

        _handle_worktree_removal_error(err, wt, "task-man", post_merge=False, print_success=False)

        mock_add.assert_called_once_with("task-man", str(wt), "Worktree removal failed: cannot remove")


# ---------------------------------------------------------------------------
# cleanup_worktree_and_branch
# ---------------------------------------------------------------------------
class TestCleanupWorktreeAndBranch:
    """Tests for cleanup_worktree_and_branch."""

    @patch(f"{MODULE}._delete_branch", return_value=True)
    @patch(f"{MODULE}.remove_from_manifest")
    @patch(f"{MODULE}._run_git")
    def test_success_worktree_removed_branch_deleted(self, mock_git, mock_rm, mock_del, tmp_path):
        """Worktree removed successfully, branch deleted."""
        import shutil
        wt = tmp_path / "worktrees" / "task-ok"
        wt.mkdir(parents=True)

        def _fake_git_remove(cmd, cwd=None):
            # Simulate git worktree remove by deleting the directory
            if "worktree" in cmd and "remove" in cmd:
                shutil.rmtree(wt, ignore_errors=True)

        mock_git.side_effect = _fake_git_remove

        result = cleanup_worktree_and_branch(
            wt, "task/task-ok", worktree_id="task-ok", print_success=True
        )

        assert result is True
        mock_git.assert_called_once()
        mock_rm.assert_called_once_with("task-ok")
        mock_del.assert_called_once()

    @patch(f"{MODULE}._delete_branch", return_value=True)
    @patch(f"{MODULE}._run_git")
    def test_worktree_path_doesnt_exist_just_delete_branch(self, mock_git, mock_del, tmp_path):
        """When worktree path doesn't exist, skip removal, delete branch."""
        wt = tmp_path / "worktrees" / "task-gone"

        result = cleanup_worktree_and_branch(wt, "task/task-gone", worktree_id="task-gone")

        assert result is True
        mock_git.assert_not_called()

    @patch(f"{MODULE}._delete_branch")
    @patch(f"{MODULE}._handle_worktree_removal_error")
    @patch(f"{MODULE}._run_git", side_effect=subprocess.CalledProcessError(1, "git", stderr="err"))
    def test_removal_error_dir_still_exists_skip_branch_delete(
        self, mock_git, mock_handle, mock_del, tmp_path
    ):
        """Worktree removal error + dir still exists → skip branch delete."""
        wt = tmp_path / "worktrees" / "task-err"
        wt.mkdir(parents=True)

        result = cleanup_worktree_and_branch(
            wt, "task/task-err", worktree_id="task-err",
            skip_branch_delete_if_dir_exists=True
        )

        assert result is False
        mock_handle.assert_called_once()
        mock_del.assert_not_called()

    @patch(f"{MODULE}._delete_branch", return_value=True)
    @patch(f"{MODULE}._run_git")
    def test_derives_worktree_id_from_branch_name(self, mock_git, mock_del, tmp_path):
        """worktree_id derived from branch_name when branch starts with BRANCH_PREFIX."""
        wt = tmp_path / "worktrees" / "task-derive"
        # Path doesn't exist, so no removal attempted

        result = cleanup_worktree_and_branch(wt, "task/my-feature")

        assert result is True
        mock_del.assert_called_once()

    @patch(f"{MODULE}._delete_branch", return_value=True)
    @patch(f"{MODULE}._run_git")
    def test_derives_worktree_id_from_worktree_path(self, mock_git, mock_del, tmp_path):
        """worktree_id derived from worktree_path.name when branch has no prefix."""
        wt = tmp_path / "worktrees" / "task-pathid"
        # Path doesn't exist, no removal

        result = cleanup_worktree_and_branch(wt, "some-branch")

        assert result is True


# ---------------------------------------------------------------------------
# _delete_branch
# ---------------------------------------------------------------------------
class TestDeleteBranch:
    """Tests for _delete_branch."""

    @patch(f"{MODULE}._run_git")
    def test_success(self, mock_git):
        """Branch deleted successfully."""
        result = _delete_branch("task/abc", None, False, True, False)

        assert result is True
        mock_git.assert_called_once_with(
            ["git", "branch", "-d", "task/abc"], cwd=None
        )

    @patch(f"{MODULE}._run_git")
    def test_failure_with_fallback_success(self, mock_git):
        """Primary fails, fallback branch deleted successfully."""
        err = subprocess.CalledProcessError(1, "git")
        err.stderr = "not fully merged"
        mock_git.side_effect = [err, MagicMock()]

        result = _delete_branch("task/abc", "task/abc-fallback", False, True, False)

        assert result is True
        assert mock_git.call_count == 2

    @patch(f"{MODULE}._run_git")
    def test_failure_with_fallback_not_found(self, mock_git):
        """Primary fails, fallback not found → returns True."""
        err1 = subprocess.CalledProcessError(1, "git")
        err1.stderr = "not merged"
        err2 = subprocess.CalledProcessError(1, "git")
        err2.stderr = "branch 'x' not found"
        mock_git.side_effect = [err1, err2]

        result = _delete_branch("task/abc", "task/abc-fb", False, False, False)

        assert result is True

    @patch(f"{MODULE}._run_git")
    def test_failure_with_no_fallback(self, mock_git):
        """Primary fails, no fallback → returns True with warning."""
        err = subprocess.CalledProcessError(1, "git")
        err.stderr = "error: branch 'x' not found"
        mock_git.side_effect = err

        result = _delete_branch("task/abc", None, False, False, False)

        assert result is True


# ---------------------------------------------------------------------------
# cleanup_after_merge
# ---------------------------------------------------------------------------
class TestCleanupAfterMerge:
    """Tests for cleanup_after_merge."""

    @patch(f"{MODULE}.cleanup_worktree_and_branch")
    def test_delegates_correctly(self, mock_cleanup, tmp_path):
        """cleanup_after_merge delegates with expected parameters."""
        wt = tmp_path / "worktrees" / "task-merge"
        wt.mkdir(parents=True)

        cleanup_after_merge(wt, "task/merge-branch", cwd="/repo")

        mock_cleanup.assert_called_once_with(
            wt,
            "task/merge-branch",
            skip_branch_delete_if_dir_exists=True,
            post_merge=True,
            print_success=True,
            cwd="/repo",
        )


# ---------------------------------------------------------------------------
# get_uncleaned_worktree_count
# ---------------------------------------------------------------------------
class TestGetUncleanedWorktreeCount:
    """Tests for get_uncleaned_worktree_count."""

    @patch(f"{MODULE}.load_worktree_manifest", return_value={})
    def test_empty_manifest(self, mock_load):
        """Empty manifest returns 0."""
        assert get_uncleaned_worktree_count() == 0

    @patch(f"{MODULE}.load_worktree_manifest", return_value={
        "a": {"path": "/a"}, "b": {"path": "/b"}, "c": {"path": "/c"},
    })
    def test_non_empty_manifest(self, mock_load):
        """Non-empty manifest returns correct count."""
        assert get_uncleaned_worktree_count() == 3


# ---------------------------------------------------------------------------
# has_unmerged_worktrees
# ---------------------------------------------------------------------------
class TestHasUnmergedWorktrees:
    """Tests for has_unmerged_worktrees."""

    @patch(f"{MODULE}.load_worktree_manifest", return_value={})
    @patch("pokepoke.git.git_operations.list_worktrees", return_value=[])
    def test_no_task_worktrees_empty_manifest(self, mock_list, mock_manifest):
        """No task worktrees and empty manifest → False."""
        assert has_unmerged_worktrees() is False

    @patch("pokepoke.git.git_operations.list_worktrees", return_value=[
        {"path": "/repo/worktrees/task-active", "branch": "task/active"},
    ])
    def test_has_task_worktrees(self, mock_list):
        """Task worktrees present → True."""
        assert has_unmerged_worktrees() is True

    @patch(f"{MODULE}.load_worktree_manifest", return_value={
        "wt-leftover": {"path": "/p", "reason": "r"},
    })
    @patch("pokepoke.git.git_operations.list_worktrees", return_value=[
        {"path": "/repo/other-dir", "branch": "main"},
    ])
    def test_no_task_worktrees_but_manifest_entries(self, mock_list, mock_manifest):
        """No task worktrees but manifest has entries → True."""
        assert has_unmerged_worktrees() is True
