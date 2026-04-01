"""Tests for preflight_repair module -- covers all repair functions."""

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from pokepoke.utils.preflight_checks import HealthCheckError
from pokepoke.utils.preflight_repair import (
    _invoke_preflight_cleanup,
    attempt_repair,
    repair_git_status,
    repair_lock_availability,
    repair_repository_integrity,
)

# -- Fixtures -----------------------------------------------------------------


@pytest.fixture
def repo_path(tmp_path):
    return tmp_path / "repo"


@pytest.fixture
def git_status_error():
    return HealthCheckError(
        check_name="git_status_check",
        message="Uncommitted changes",
        severity="recoverable",
        details={"uncommitted_files": ["a.py"], "total_count": 1},
    )


@pytest.fixture
def integrity_error(tmp_path):
    orphan = tmp_path / "worktrees" / "orphan-1"
    orphan.mkdir(parents=True)
    return HealthCheckError(
        check_name="repository_integrity_check",
        message="Too many orphaned worktrees",
        severity="recoverable",
        details={"orphaned_paths": [str(orphan)]},
    )


@pytest.fixture
def lock_error(tmp_path):
    lock = tmp_path / ".pokepoke" / "orchestrator.lock"
    lock.parent.mkdir(parents=True)
    lock.write_text("12345")
    return HealthCheckError(
        check_name="lock_availability_check",
        message="Active lock",
        severity="recoverable",
        details={"lock_file": str(lock)},
    )


# -- repair_git_status --------------------------------------------------------


class TestRepairGitStatus:
    """Tests for repair_git_status."""

    @pytest.mark.allow_git_repair
    def test_success_path_commit_succeeds(self, git_status_error, repo_path):
        commit_result = MagicMock(returncode=0)
        with patch("pokepoke.utils.preflight_repair.subprocess.run") as mock_run:
            # First call: git add -u, second call: git commit
            mock_run.side_effect = [MagicMock(), commit_result]
            assert repair_git_status(git_status_error, repo_path) is True

        assert mock_run.call_count == 2
        # Verify git add -u was called first
        add_call = mock_run.call_args_list[0]
        assert "add" in add_call[0][0]
        assert "-u" in add_call[0][0]

    @pytest.mark.allow_git_repair
    def test_failed_commit_invokes_cleanup(self, git_status_error, repo_path):
        commit_result = MagicMock(returncode=1, stderr="hook failed")
        with patch("pokepoke.utils.preflight_repair.subprocess.run") as mock_run, \
             patch("pokepoke.utils.preflight_repair._invoke_preflight_cleanup", return_value=True) as mock_cleanup:
            mock_run.side_effect = [MagicMock(), commit_result]
            assert repair_git_status(git_status_error, repo_path) is True

        mock_cleanup.assert_called_once_with(repo_path, "hook failed")

    @pytest.mark.allow_git_repair
    def test_failed_commit_cleanup_returns_false(self, git_status_error, repo_path):
        commit_result = MagicMock(returncode=1, stderr="")
        with patch("pokepoke.utils.preflight_repair.subprocess.run") as mock_run, \
             patch("pokepoke.utils.preflight_repair._invoke_preflight_cleanup", return_value=False) as mock_cleanup:
            mock_run.side_effect = [MagicMock(), commit_result]
            assert repair_git_status(git_status_error, repo_path) is False

        # Empty stderr -> "Unknown commit failure"
        mock_cleanup.assert_called_once_with(repo_path, "Unknown commit failure")

    @pytest.mark.allow_git_repair
    def test_called_process_error_returns_false(self, git_status_error, repo_path):
        with patch("pokepoke.utils.preflight_repair.subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.CalledProcessError(
                128, "git", stderr="fatal error"
            )
            assert repair_git_status(git_status_error, repo_path) is False

    @pytest.mark.allow_git_repair
    def test_general_exception_returns_false(self, git_status_error, repo_path):
        with patch("pokepoke.utils.preflight_repair.subprocess.run") as mock_run:
            mock_run.side_effect = OSError("disk failure")
            assert repair_git_status(git_status_error, repo_path) is False


# -- _invoke_preflight_cleanup ------------------------------------------------


class TestInvokePreflightCleanup:
    """Tests for _invoke_preflight_cleanup."""

    @pytest.mark.allow_git_repair
    def test_success_path(self, repo_path):
        mock_invoke_fn = MagicMock(return_value=(True, None))
        mock_bwi = MagicMock()

        with (
            patch("pokepoke.agents.cleanup_agents.invoke_cleanup_agent", mock_invoke_fn),
            patch("pokepoke.types.BeadsWorkItem", mock_bwi),
        ):
            result = _invoke_preflight_cleanup(repo_path, "lint errors")

        assert result is True
        mock_invoke_fn.assert_called_once()
        mock_bwi.assert_called_once()
        kwargs = mock_bwi.call_args
        assert kwargs[1]["id"] == "preflight-repair"

    @pytest.mark.allow_git_repair
    def test_cleanup_agent_raises_exception(self, repo_path):
        mock_invoke_fn = MagicMock(side_effect=RuntimeError("agent crashed"))
        mock_bwi = MagicMock()

        with (
            patch("pokepoke.agents.cleanup_agents.invoke_cleanup_agent", mock_invoke_fn),
            patch("pokepoke.types.BeadsWorkItem", mock_bwi),
        ):
            result = _invoke_preflight_cleanup(repo_path, "test failure")

        assert result is False

    @pytest.mark.allow_git_repair
    def test_import_error_returns_false(self, repo_path):
        import sys
        saved_cleanup = sys.modules.get("pokepoke.agents.cleanup_agents")
        saved_types = sys.modules.get("pokepoke.types")
        try:
            sys.modules["pokepoke.agents.cleanup_agents"] = None  # type: ignore[assignment]
            sys.modules["pokepoke.types"] = None  # type: ignore[assignment]
            result = _invoke_preflight_cleanup(repo_path, "error msg")
            assert result is False
        finally:
            if saved_cleanup is not None:
                sys.modules["pokepoke.agents.cleanup_agents"] = saved_cleanup
            else:
                sys.modules.pop("pokepoke.agents.cleanup_agents", None)
            if saved_types is not None:
                sys.modules["pokepoke.types"] = saved_types
            else:
                sys.modules.pop("pokepoke.types", None)


# -- repair_repository_integrity ----------------------------------------------


class TestRepairRepositoryIntegrity:
    """Tests for repair_repository_integrity."""

    @pytest.mark.allow_git_repair
    def test_removes_orphaned_dirs(self, tmp_path):
        orphan = tmp_path / "worktrees" / "orphan-1"
        orphan.mkdir(parents=True)
        error = HealthCheckError(
            check_name="repository_integrity_check",
            message="Orphans",
            severity="recoverable",
            details={"orphaned_paths": [str(orphan)]},
        )
        assert repair_repository_integrity(error) is True
        assert not orphan.exists()

    @pytest.mark.allow_git_repair
    def test_handles_nonexistent_paths(self):
        error = HealthCheckError(
            check_name="repository_integrity_check",
            message="Orphans",
            severity="recoverable",
            details={"orphaned_paths": ["/nonexistent/path/abc123"]},
        )
        # Non-existent paths are simply skipped — should succeed
        assert repair_repository_integrity(error) is True

    @pytest.mark.allow_git_repair
    def test_handles_removal_failure(self, tmp_path):
        orphan = tmp_path / "worktrees" / "stuck"
        orphan.mkdir(parents=True)
        error = HealthCheckError(
            check_name="repository_integrity_check",
            message="Orphans",
            severity="recoverable",
            details={"orphaned_paths": [str(orphan)]},
        )
        with patch("pokepoke.utils.preflight_repair.shutil.rmtree") as mock_rm:
            # rmtree does nothing (ignore_errors=True), dir still exists
            mock_rm.return_value = None
            assert repair_repository_integrity(error) is False

    @pytest.mark.allow_git_repair
    def test_empty_orphaned_paths(self):
        error = HealthCheckError(
            check_name="repository_integrity_check",
            message="Orphans",
            severity="recoverable",
            details={"orphaned_paths": []},
        )
        assert repair_repository_integrity(error) is True

    @pytest.mark.allow_git_repair
    def test_exception_returns_false(self):
        error = HealthCheckError(
            check_name="repository_integrity_check",
            message="Orphans",
            severity="recoverable",
            details={"orphaned_paths": ["some/path"]},
        )
        with patch("pokepoke.utils.preflight_repair.Path") as mock_path_cls:
            mock_path_cls.side_effect = RuntimeError("unexpected")
            assert repair_repository_integrity(error) is False


# -- repair_lock_availability -------------------------------------------------


class TestRepairLockAvailability:
    """Tests for repair_lock_availability."""

    @pytest.mark.allow_git_repair
    def test_removes_stale_lock(self, tmp_path):
        lock = tmp_path / "orchestrator.lock"
        lock.write_text("99999")
        error = HealthCheckError(
            check_name="lock_availability_check",
            message="Active lock",
            severity="recoverable",
            details={"lock_file": str(lock)},
        )
        with patch("pokepoke.utils.preflight_repair.is_lock_stale", return_value=(True, {"reason": "old"})):
            assert repair_lock_availability(error, tmp_path) is True
        assert not lock.exists()

    @pytest.mark.allow_git_repair
    def test_lock_already_gone(self, tmp_path):
        error = HealthCheckError(
            check_name="lock_availability_check",
            message="Active lock",
            severity="recoverable",
            details={"lock_file": str(tmp_path / "gone.lock")},
        )
        assert repair_lock_availability(error, tmp_path) is True

    @pytest.mark.allow_git_repair
    def test_lock_not_stale(self, tmp_path):
        lock = tmp_path / "orchestrator.lock"
        lock.write_text("12345")
        error = HealthCheckError(
            check_name="lock_availability_check",
            message="Active lock",
            severity="recoverable",
            details={"lock_file": str(lock)},
        )
        with patch("pokepoke.utils.preflight_repair.is_lock_stale", return_value=(False, {"reason": "running"})):
            assert repair_lock_availability(error, tmp_path) is False
        assert lock.exists()

    @pytest.mark.allow_git_repair
    def test_no_lock_file_in_details(self, tmp_path):
        error = HealthCheckError(
            check_name="lock_availability_check",
            message="Active lock",
            severity="recoverable",
            details={},
        )
        assert repair_lock_availability(error, tmp_path) is False

    @pytest.mark.allow_git_repair
    def test_exception_returns_false(self, tmp_path):
        error = HealthCheckError(
            check_name="lock_availability_check",
            message="Active lock",
            severity="recoverable",
            details={"lock_file": str(tmp_path / "lock")},
        )
        with patch("pokepoke.utils.preflight_repair.Path") as mock_path_cls:
            mock_path_cls.side_effect = RuntimeError("unexpected")
            assert repair_lock_availability(error, tmp_path) is False


# -- attempt_repair -----------------------------------------------------------


class TestAttemptRepair:
    """Tests for attempt_repair orchestrator."""

    @pytest.mark.allow_git_repair
    def test_no_recoverable_errors_returns_true(self, repo_path):
        health_result = MagicMock()
        health_result.get_recoverable_errors.return_value = []
        assert attempt_repair(health_result, repo_path, {}) is True

    @pytest.mark.allow_git_repair
    def test_routes_git_status_check(self, repo_path):
        error = HealthCheckError(
            check_name="git_status_check",
            message="dirty",
            severity="recoverable",
        )
        health_result = MagicMock()
        health_result.get_recoverable_errors.return_value = [error]

        with patch("pokepoke.utils.preflight_repair.repair_git_status", return_value=True) as mock_fn:
            result = attempt_repair(health_result, repo_path, {"max_repair_attempts": 1})

        assert result is True
        mock_fn.assert_called_once_with(error, repo_path)
        assert error.recovery_attempted is True
        assert error.recovery_successful is True

    @pytest.mark.allow_git_repair
    def test_routes_repository_integrity_check(self, repo_path):
        error = HealthCheckError(
            check_name="repository_integrity_check",
            message="orphans",
            severity="recoverable",
        )
        health_result = MagicMock()
        health_result.get_recoverable_errors.return_value = [error]

        with patch("pokepoke.utils.preflight_repair.repair_repository_integrity", return_value=True) as mock_fn:
            result = attempt_repair(health_result, repo_path, {"max_repair_attempts": 1})

        assert result is True
        mock_fn.assert_called_once_with(error)

    @pytest.mark.allow_git_repair
    def test_routes_lock_availability_check(self, repo_path):
        error = HealthCheckError(
            check_name="lock_availability_check",
            message="stale lock",
            severity="recoverable",
        )
        health_result = MagicMock()
        health_result.get_recoverable_errors.return_value = [error]

        with patch("pokepoke.utils.preflight_repair.repair_lock_availability", return_value=True) as mock_fn:
            result = attempt_repair(health_result, repo_path, {"max_repair_attempts": 1})

        assert result is True
        mock_fn.assert_called_once_with(error, repo_path)

    @pytest.mark.allow_git_repair
    def test_unknown_check_name_fails(self, repo_path):
        error = HealthCheckError(
            check_name="unknown_check",
            message="wat",
            severity="recoverable",
        )
        health_result = MagicMock()
        health_result.get_recoverable_errors.return_value = [error]

        result = attempt_repair(health_result, repo_path, {"max_repair_attempts": 1})
        assert result is False

    @pytest.mark.allow_git_repair
    def test_retry_with_exponential_backoff(self, repo_path):
        error = HealthCheckError(
            check_name="git_status_check",
            message="dirty",
            severity="recoverable",
        )
        health_result = MagicMock()
        health_result.get_recoverable_errors.return_value = [error]

        with patch("pokepoke.utils.preflight_repair.repair_git_status", side_effect=[False, False, True]) as mock_fn, \
             patch("pokepoke.utils.retry_utils.time.sleep") as mock_sleep:
            result = attempt_repair(health_result, repo_path, {"max_repair_attempts": 3})

        assert result is True
        assert mock_fn.call_count == 3
        # Exponential backoff with jitter: attempt 0 = 2.0 * [0.5, 1.5], attempt 1 = 4.0 * [0.5, 1.5]
        assert mock_sleep.call_count == 2
        delays = [c.args[0] for c in mock_sleep.call_args_list]
        assert 1.0 <= delays[0] <= 3.0  # 2.0 * [0.5, 1.5]
        assert 2.0 <= delays[1] <= 6.0  # 4.0 * [0.5, 1.5]

    @pytest.mark.allow_git_repair
    def test_all_attempts_fail(self, repo_path):
        error = HealthCheckError(
            check_name="git_status_check",
            message="dirty",
            severity="recoverable",
        )
        health_result = MagicMock()
        health_result.get_recoverable_errors.return_value = [error]

        with patch("pokepoke.utils.preflight_repair.repair_git_status", return_value=False), \
             patch("pokepoke.utils.retry_utils.time.sleep"):
            result = attempt_repair(health_result, repo_path, {"max_repair_attempts": 3})

        assert result is False
        assert error.recovery_attempted is True
        assert error.recovery_successful is False

    @pytest.mark.allow_git_repair
    def test_default_max_attempts(self, repo_path):
        """Config without max_repair_attempts defaults to 3."""
        error = HealthCheckError(
            check_name="git_status_check",
            message="dirty",
            severity="recoverable",
        )
        health_result = MagicMock()
        health_result.get_recoverable_errors.return_value = [error]

        with patch("pokepoke.utils.preflight_repair.repair_git_status", return_value=False) as mock_fn, \
             patch("pokepoke.utils.retry_utils.time.sleep"):
            attempt_repair(health_result, repo_path, {})

        assert mock_fn.call_count == 3
