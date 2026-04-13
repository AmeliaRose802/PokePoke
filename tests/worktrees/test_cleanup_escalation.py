"""Tests for pokepoke.worktrees.cleanup_escalation.

This file ensures the coverage tool can locate tests via the standard
``test_<module>.py`` naming convention.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

from pokepoke.worktrees.cleanup_escalation import (
    _get_quarantine_dir,
    _nuclear_remove,
    _quarantine_directory,
    retry_failed_cleanups,
)


# ---------------------------------------------------------------------------
# _get_quarantine_dir
# ---------------------------------------------------------------------------

class TestGetQuarantineDir:
    """Cover _get_quarantine_dir helper."""

    def test_creates_quarantine_dir(self, tmp_path: Path) -> None:
        with patch("pokepoke.utils.constants.POKEPOKE_DIR", tmp_path):
            result = _get_quarantine_dir()
        assert result == tmp_path / ".quarantine"
        assert result.exists()

    def test_returns_existing_quarantine_dir(self, tmp_path: Path) -> None:
        qdir = tmp_path / ".quarantine"
        qdir.mkdir()
        with patch("pokepoke.utils.constants.POKEPOKE_DIR", tmp_path):
            result = _get_quarantine_dir()
        assert result == qdir


# ---------------------------------------------------------------------------
# _nuclear_remove
# ---------------------------------------------------------------------------

class TestNuclearRemove:
    """Cover _nuclear_remove function."""

    def test_shutil_rmtree_succeeds(self, tmp_path: Path) -> None:
        target = tmp_path / "nuke-me"
        target.mkdir()
        (target / "file.txt").write_text("data")
        assert _nuclear_remove(target) is True
        assert not target.exists()

    def test_returns_false_when_all_fail(self, tmp_path: Path) -> None:
        target = tmp_path / "stubborn"
        target.mkdir()
        with patch("shutil.rmtree", side_effect=OSError("fail")), \
             patch("subprocess.run", side_effect=OSError("fail")):
            assert _nuclear_remove(target) is False

    def test_onerror_handler_recovers_permission(self, tmp_path: Path) -> None:
        """The _on_error callback should chmod then remove the file."""
        target = tmp_path / "locked"
        target.mkdir()
        locked = target / "locked.txt"
        locked.write_text("x")

        with patch("os.chmod") as mock_chmod, \
             patch("os.remove") as mock_remove, \
             patch("shutil.rmtree") as mock_rmtree:
            # Make rmtree call the onerror handler
            def call_onerror(path, onerror=None, **kw):
                if onerror:
                    onerror(None, str(locked), None)
                raise OSError("still fails")
            mock_rmtree.side_effect = call_onerror

            with patch("subprocess.run", side_effect=OSError("nope")):
                _nuclear_remove(target)

            mock_chmod.assert_called_once()
            mock_remove.assert_called_once_with(str(locked))

    def test_os_level_removal_on_windows(self, tmp_path: Path) -> None:
        target = tmp_path / "win-rm"
        target.mkdir()

        with patch("shutil.rmtree", side_effect=OSError("fail")), \
             patch("sys.platform", "win32"), \
             patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            # Directory still exists after subprocess, so returns False
            _nuclear_remove(target)

            mock_run.assert_called_once()
            cmd = mock_run.call_args[0][0]
            assert cmd[0] == "cmd"

    def test_os_level_timeout_returns_false(self, tmp_path: Path) -> None:
        import subprocess
        target = tmp_path / "timeout-dir"
        target.mkdir()
        with patch("shutil.rmtree", side_effect=OSError("fail")), \
             patch("subprocess.run", side_effect=subprocess.TimeoutExpired("cmd", 30)):
            assert _nuclear_remove(target) is False


# ---------------------------------------------------------------------------
# _quarantine_directory
# ---------------------------------------------------------------------------

class TestQuarantineDirectory:
    """Cover _quarantine_directory function."""

    @patch("pokepoke.worktrees.cleanup_escalation._get_quarantine_dir")
    def test_moves_directory(self, mock_qdir: MagicMock, tmp_path: Path) -> None:
        qdir = tmp_path / "quarantine"
        qdir.mkdir()
        mock_qdir.return_value = qdir
        target = tmp_path / "target"
        target.mkdir()
        assert _quarantine_directory(target, "wt-1") is True
        assert not target.exists()

    def test_nonexistent_returns_true(self, tmp_path: Path) -> None:
        assert _quarantine_directory(tmp_path / "gone", "wt-1") is True

    @patch("pokepoke.worktrees.cleanup_escalation._get_quarantine_dir")
    def test_rename_failure(self, mock_qdir: MagicMock, tmp_path: Path) -> None:
        mock_qdir.return_value = tmp_path / "q"
        (tmp_path / "q").mkdir()
        target = tmp_path / "target"
        target.mkdir()
        with patch.object(Path, "rename", side_effect=OSError("denied")):
            assert _quarantine_directory(target, "wt-1") is False


# ---------------------------------------------------------------------------
# retry_failed_cleanups
# ---------------------------------------------------------------------------

class TestRetryFailedCleanups:
    """Cover retry_failed_cleanups function."""

    @patch("pokepoke.worktrees.worktree_cleanup.load_worktree_manifest", return_value={})
    def test_empty_manifest(self, _mock: MagicMock) -> None:
        assert retry_failed_cleanups() == 0

    @patch("pokepoke.worktrees.worktree_cleanup.remove_from_manifest")
    @patch("pokepoke.worktrees.worktree_cleanup.force_remove_directory", return_value=True)
    @patch("pokepoke.worktrees.worktree_cleanup.load_worktree_manifest")
    def test_force_remove_success(self, mock_load: MagicMock, _force: MagicMock, mock_rm: MagicMock) -> None:
        mock_load.return_value = {
            "wt-1": {"path": "/tmp/wt1", "reason": "failed", "timestamp": "t"},
        }
        with patch.object(Path, "exists", return_value=True):
            assert retry_failed_cleanups() == 1
        mock_rm.assert_called_once_with("wt-1")

    @patch("pokepoke.worktrees.worktree_cleanup.remove_from_manifest")
    @patch("pokepoke.worktrees.worktree_cleanup.load_worktree_manifest")
    def test_already_gone(self, mock_load: MagicMock, mock_rm: MagicMock) -> None:
        mock_load.return_value = {
            "wt-1": {"path": "/tmp/gone", "reason": "r", "timestamp": "t"},
        }
        with patch.object(Path, "exists", return_value=False):
            assert retry_failed_cleanups() == 1
        mock_rm.assert_called_once_with("wt-1")

    @patch("pokepoke.worktrees.worktree_cleanup.add_uncleaned_worktree")
    @patch("pokepoke.worktrees.worktree_cleanup.remove_from_manifest")
    @patch("pokepoke.worktrees.worktree_cleanup.force_remove_directory", return_value=False)
    @patch("pokepoke.worktrees.worktree_cleanup.load_worktree_manifest")
    def test_force_fail_bumps_count(self, mock_load: MagicMock, _force: MagicMock, mock_rm: MagicMock, mock_add: MagicMock) -> None:
        mock_load.return_value = {
            "wt-1": {"path": "/tmp/wt1", "reason": "r", "timestamp": "t", "failure_count": "1"},
        }
        with patch.object(Path, "exists", return_value=True):
            assert retry_failed_cleanups() == 0
        mock_rm.assert_not_called()
        mock_add.assert_called_once()

    @patch("pokepoke.worktrees.worktree_cleanup.remove_from_manifest")
    @patch("pokepoke.worktrees.cleanup_escalation._nuclear_remove", return_value=True)
    @patch("pokepoke.worktrees.worktree_cleanup.load_worktree_manifest")
    def test_nuclear_triggered(self, mock_load: MagicMock, mock_nuke: MagicMock, mock_rm: MagicMock) -> None:
        mock_load.return_value = {
            "wt-1": {"path": "/tmp/wt1", "reason": "r", "timestamp": "t", "failure_count": "3"},
        }
        with patch.object(Path, "exists", return_value=True):
            assert retry_failed_cleanups() == 1
        mock_nuke.assert_called_once()
        mock_rm.assert_called_once_with("wt-1")

    @patch("pokepoke.worktrees.worktree_cleanup.remove_from_manifest")
    @patch("pokepoke.worktrees.cleanup_escalation._quarantine_directory", return_value=True)
    @patch("pokepoke.worktrees.cleanup_escalation._nuclear_remove", return_value=False)
    @patch("pokepoke.worktrees.worktree_cleanup.load_worktree_manifest")
    def test_quarantine_on_nuclear_fail(self, mock_load: MagicMock, _nuke: MagicMock, _q: MagicMock, mock_rm: MagicMock) -> None:
        mock_load.return_value = {
            "wt-1": {"path": "/tmp/wt1", "reason": "r", "timestamp": "t", "failure_count": "5"},
        }
        with patch.object(Path, "exists", return_value=True):
            assert retry_failed_cleanups() == 1
        mock_rm.assert_called_once_with("wt-1")

    @patch("pokepoke.worktrees.worktree_cleanup.add_uncleaned_worktree")
    @patch("pokepoke.worktrees.worktree_cleanup.remove_from_manifest")
    @patch("pokepoke.worktrees.cleanup_escalation._quarantine_directory", return_value=False)
    @patch("pokepoke.worktrees.cleanup_escalation._nuclear_remove", return_value=False)
    @patch("pokepoke.worktrees.worktree_cleanup.load_worktree_manifest")
    def test_all_fail_bumps_count(self, mock_load: MagicMock, _nuke: MagicMock, _q: MagicMock, mock_rm: MagicMock, mock_add: MagicMock) -> None:
        mock_load.return_value = {
            "wt-1": {"path": "/tmp/wt1", "reason": "r", "timestamp": "t", "failure_count": "4"},
        }
        with patch.object(Path, "exists", return_value=True):
            assert retry_failed_cleanups() == 0
        mock_rm.assert_not_called()
        mock_add.assert_called_once()

    @patch("pokepoke.worktrees.worktree_cleanup.add_uncleaned_worktree")
    @patch("pokepoke.worktrees.worktree_cleanup.remove_from_manifest")
    @patch("pokepoke.worktrees.worktree_cleanup.force_remove_directory", return_value=False)
    @patch("pokepoke.worktrees.worktree_cleanup.load_worktree_manifest")
    def test_invalid_failure_count_defaults_to_one(self, mock_load: MagicMock, _force: MagicMock, _rm: MagicMock, _add: MagicMock) -> None:
        """ValueError/TypeError from invalid failure_count falls back to 1."""
        mock_load.return_value = {
            "wt-1": {"path": "/tmp/wt1", "reason": "r", "timestamp": "t", "failure_count": "not-a-number"},
        }
        with patch.object(Path, "exists", return_value=True):
            result = retry_failed_cleanups()
        # failure_count=1 < 3, so normal force_remove path, which fails => 0 cleaned
        assert result == 0
