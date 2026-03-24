"""Tests for preflight_checks module — covers all standalone check functions."""

import subprocess
import time
from unittest.mock import MagicMock, patch

import pytest

from pokepoke.utils.preflight_checks import (
    ErrorSeverity,
    check_disk_space,
    check_git_status,
    check_lock_availability,
    check_repository_integrity,
    check_worktree_creation,
    is_lock_stale,
)


@pytest.fixture
def health_config():
    return {
        "min_disk_space_gb": 1,
        "required_tools": ["git"],
        "git_operation_timeout": 10,
        "worktree_test_timeout": 10,
        "lock_timeout_seconds": 5.0,
        "max_orphan_worktrees": 2,
        "enable_self_repair": True,
    }


@pytest.fixture
def fake_repo(tmp_path):
    """Create a directory that looks like a git repo (has .git/)."""
    (tmp_path / ".git").mkdir()
    return tmp_path


# ── check_git_status ────────────────────────────────────────────────


class TestCheckGitStatus:
    """Tests for the check_git_status function."""

    def test_untracked_files_reported(self, fake_repo, health_config):
        mock_result = MagicMock(returncode=0, stdout="?? new_file.py\n")
        with patch("pokepoke.utils.preflight_checks.has_uncommitted_changes", return_value=True), \
             patch("subprocess.run", return_value=mock_result), \
             patch("pokepoke.utils.preflight_checks.categorize_git_changes", return_value={
                 "other": [], "beads": [], "worktree": [], "untracked": ["new_file.py"],
             }):
            errors, warnings = check_git_status(fake_repo, health_config)
        status_errors = [e for e in errors if e.check_name == "git_status_check"]
        assert len(status_errors) == 1
        assert "1 files" in status_errors[0].message

    def test_other_and_untracked_combined(self, fake_repo, health_config):
        mock_result = MagicMock(returncode=0, stdout="M a.py\n?? b.py\n")
        with patch("pokepoke.utils.preflight_checks.has_uncommitted_changes", return_value=True), \
             patch("subprocess.run", return_value=mock_result), \
             patch("pokepoke.utils.preflight_checks.categorize_git_changes", return_value={
                 "other": ["a.py"], "beads": [], "worktree": [], "untracked": ["b.py"],
             }):
            errors, _ = check_git_status(fake_repo, health_config)
        status_errors = [e for e in errors if e.check_name == "git_status_check"]
        assert status_errors[0].details["total_count"] == 2

    def test_no_uncommitted_changes(self, fake_repo, health_config):
        with patch("pokepoke.utils.preflight_checks.has_uncommitted_changes", return_value=False):
            errors, warnings = check_git_status(fake_repo, health_config)
        assert len(errors) == 0

    def test_not_a_git_repo(self, tmp_path, health_config):
        errors, _ = check_git_status(tmp_path, health_config)
        assert any(e.severity == ErrorSeverity.CRITICAL for e in errors)
        assert any("Not a git repository" in e.message for e in errors)

    def test_called_process_error(self, fake_repo, health_config):
        with patch("pokepoke.utils.preflight_checks.has_uncommitted_changes", return_value=True), \
             patch("subprocess.run", side_effect=subprocess.CalledProcessError(1, "git", stderr="bad")):
            errors, _ = check_git_status(fake_repo, health_config)
        assert any(e.severity == ErrorSeverity.ENVIRONMENTAL for e in errors)

    def test_timeout_expired(self, fake_repo, health_config):
        with patch("pokepoke.utils.preflight_checks.has_uncommitted_changes", return_value=True), \
             patch("subprocess.run", side_effect=subprocess.TimeoutExpired("git", 10)):
            errors, _ = check_git_status(fake_repo, health_config)
        assert any("timed out" in e.message.lower() for e in errors)

    def test_beads_changes_warning(self, fake_repo, health_config):
        mock_result = MagicMock(returncode=0, stdout=".beads/issues.jsonl\n")
        with patch("pokepoke.utils.preflight_checks.has_uncommitted_changes", return_value=True), \
             patch("subprocess.run", return_value=mock_result), \
             patch("pokepoke.utils.preflight_checks.categorize_git_changes", return_value={
                 "other": [], "beads": [".beads/issues.jsonl"], "worktree": [], "untracked": [],
             }):
            errors, warnings = check_git_status(fake_repo, health_config)
        assert any("Beads database" in w for w in warnings)
        assert len([e for e in errors if e.check_name == "git_status_check"]) == 0


# ── check_worktree_creation ─────────────────────────────────────────


class TestCheckWorktreeCreation:
    def test_success(self, fake_repo, health_config):
        mock_uuid_val = MagicMock()
        mock_uuid_val.hex = "abcd1234xxxxxxxx"
        with patch("pokepoke.utils.preflight_checks.uuid.uuid4", return_value=mock_uuid_val), \
             patch("subprocess.run", return_value=MagicMock(returncode=0)):
            # Pre-create the directory the function expects to find
            wt_dir = fake_repo / "worktrees" / "test-health-check-abcd1234"
            wt_dir.mkdir(parents=True)
            errors, warnings = check_worktree_creation(fake_repo, health_config)
        assert len(errors) == 0

    def test_creation_fails(self, fake_repo, health_config):
        with patch("subprocess.run", side_effect=subprocess.CalledProcessError(
            128, "git worktree add", stderr="fatal: cannot create"
        )):
            errors, _ = check_worktree_creation(fake_repo, health_config)
        assert len(errors) == 1
        assert errors[0].check_name == "worktree_creation_check"

    def test_timeout(self, fake_repo, health_config):
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("git", 10)):
            errors, _ = check_worktree_creation(fake_repo, health_config)
        assert any("timed out" in e.message.lower() for e in errors)


# ── check_lock_availability ─────────────────────────────────────────


class TestCheckLockAvailability:
    def test_no_locks(self, fake_repo, health_config):
        errors, warnings = check_lock_availability(fake_repo, health_config)
        assert len(errors) == 0

    def test_stale_lock_warning(self, fake_repo, health_config):
        lock_dir = fake_repo / ".pokepoke"
        lock_dir.mkdir()
        lock_file = lock_dir / "orchestrator.lock"
        lock_file.write_text("12345")
        with patch("pokepoke.utils.preflight_checks.is_lock_stale", return_value=(True, {"reason": "old"})):
            errors, warnings = check_lock_availability(fake_repo, health_config)
        assert any("Stale lock" in w for w in warnings)

    def test_active_lock_error(self, fake_repo, health_config):
        lock_dir = fake_repo / ".pokepoke"
        lock_dir.mkdir()
        lock_file = lock_dir / "orchestrator.lock"
        lock_file.write_text("12345")
        with patch("pokepoke.utils.preflight_checks.is_lock_stale",
                    return_value=(False, {"reason": "process_still_running"})):
            errors, _ = check_lock_availability(fake_repo, health_config)
        assert any(e.check_name == "lock_availability_check" for e in errors)


# ── check_disk_space ────────────────────────────────────────────────


class TestCheckDiskSpace:
    def test_sufficient_space(self, fake_repo, health_config):
        usage = MagicMock(free=10 * 1024**3, total=100 * 1024**3, used=90 * 1024**3)
        with patch("shutil.disk_usage", return_value=usage):
            errors, _ = check_disk_space(fake_repo, health_config)
        assert len(errors) == 0

    def test_insufficient_space(self, fake_repo, health_config):
        usage = MagicMock(free=0.1 * 1024**3, total=100 * 1024**3, used=99.9 * 1024**3)
        with patch("shutil.disk_usage", return_value=usage):
            errors, _ = check_disk_space(fake_repo, health_config)
        assert any("Insufficient disk space" in e.message for e in errors)

    def test_low_space_warning(self, fake_repo, health_config):
        # Free space between min and 2*min triggers warning
        usage = MagicMock(free=1.5 * 1024**3, total=100 * 1024**3, used=98.5 * 1024**3)
        with patch("shutil.disk_usage", return_value=usage):
            errors, warnings = check_disk_space(fake_repo, health_config)
        assert len(errors) == 0
        assert any("Low disk space" in w for w in warnings)

    def test_disk_access_error(self, fake_repo, health_config):
        with patch("shutil.disk_usage", side_effect=OSError("Access denied")):
            errors, _ = check_disk_space(fake_repo, health_config)
        assert any("Failed to check disk space" in e.message for e in errors)


# ── check_repository_integrity ──────────────────────────────────────


class TestCheckRepositoryIntegrity:
    def test_no_worktrees_dir(self, fake_repo, health_config):
        with patch("pokepoke.utils.preflight_checks.list_worktrees", return_value=[]):
            errors, warnings = check_repository_integrity(fake_repo, health_config)
        assert len(errors) == 0

    def test_orphaned_worktrees_warning(self, fake_repo, health_config):
        wt_dir = fake_repo / "worktrees"
        wt_dir.mkdir()
        (wt_dir / "orphan-1").mkdir()
        with patch("pokepoke.utils.preflight_checks.list_worktrees", return_value=[]):
            errors, warnings = check_repository_integrity(fake_repo, health_config)
        assert len(errors) == 0  # 1 < max of 2
        assert any("orphaned" in w.lower() for w in warnings)

    def test_too_many_orphaned(self, fake_repo, health_config):
        wt_dir = fake_repo / "worktrees"
        wt_dir.mkdir()
        for i in range(5):
            (wt_dir / f"orphan-{i}").mkdir()
        with patch("pokepoke.utils.preflight_checks.list_worktrees", return_value=[]):
            errors, _ = check_repository_integrity(fake_repo, health_config)
        assert any("Too many orphaned" in e.message for e in errors)


# ── is_lock_stale ───────────────────────────────────────────────────


class TestIsLockStale:
    def test_old_lock_is_stale(self, tmp_path):
        lock = tmp_path / "test.lock"
        lock.write_text("99999")
        with patch("time.time", return_value=time.time() + 7200):
            stale, details = is_lock_stale(lock)
        assert stale is True
        assert details["reason"] == "lock_too_old"

    def test_recent_lock_with_dead_process(self, tmp_path):
        lock = tmp_path / "test.lock"
        lock.write_text("99999")
        with patch("pokepoke.utils.preflight_checks.is_process_running", return_value=False):
            stale, details = is_lock_stale(lock)
        assert stale is True
        assert details["reason"] == "process_not_running"

    def test_recent_lock_with_live_process(self, tmp_path):
        lock = tmp_path / "test.lock"
        lock.write_text("99999")
        with patch("pokepoke.utils.preflight_checks.is_process_running", return_value=True):
            stale, details = is_lock_stale(lock)
        assert stale is False

    def test_lock_without_pid(self, tmp_path):
        lock = tmp_path / "test.lock"
        lock.write_text("not-a-pid")
        stale, details = is_lock_stale(lock)
        assert details["reason"] == "cannot_determine"
