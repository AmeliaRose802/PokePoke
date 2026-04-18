"""Tests for preflight health checks and error handling.

This module tests:
- handle_preflight_checks function and its configuration handling
- Preflight error formatting
- Rate-limiting of preflight warning messages
"""

from unittest.mock import MagicMock, patch

from pokepoke.agents.parallel_support import handle_preflight_checks
from pokepoke.utils.preflight_log_utils import (
    format_preflight_errors,
    reset_preflight_rate_limit,
    should_log_preflight_warning,
)


class TestHandlePreflightChecks:
    """Tests for handle_preflight_checks."""

    def _mock_config(self, *, enabled: bool = True, fail_critical: bool = True,
                     fail_env: bool = True, graceful: bool = True):
        cfg = MagicMock()
        cfg.preflight_health.enabled = enabled
        cfg.preflight_health.fail_on_critical_errors = fail_critical
        cfg.preflight_health.fail_on_environmental_errors = fail_env
        cfg.preflight_health.graceful_shutdown_on_failure = graceful
        cfg.preflight_health.min_disk_space_gb = 5
        cfg.preflight_health.lock_timeout_seconds = 30
        cfg.preflight_health.worktree_test_timeout = 60
        cfg.preflight_health.max_orphan_worktrees = 10
        cfg.preflight_health.git_operation_timeout = 60
        cfg.preflight_health.enable_self_repair = False
        cfg.preflight_health.max_repair_attempts = 3
        return cfg

    def _mock_health_result(self, *, passed: bool = True, errors=None,  # noqa: PLR0913
                            warnings=None, self_repair_attempted: bool = False,
                            self_repair_successful: bool = False,
                            critical: bool = False, environmental: bool = False):
        result = MagicMock()
        result.passed = passed
        result.errors = errors or []
        result.warnings = warnings or []
        result.self_repair_attempted = self_repair_attempted
        result.self_repair_successful = self_repair_successful
        result.has_critical_errors.return_value = critical
        result.has_environmental_errors.return_value = environmental
        return result

    @patch("pokepoke.config.get_config")
    def test_disabled_returns_true(self, mock_get_config):
        mock_get_config.return_value = self._mock_config(enabled=False)
        run_logger = MagicMock()
        should_continue, is_critical = handle_preflight_checks("/repo", run_logger)
        assert should_continue is True
        assert is_critical is False

    @patch("pokepoke.utils.preflight_health.run_preflight_checks")
    @patch("pokepoke.config.get_config")
    def test_passed_returns_true(self, mock_get_config, mock_run):
        mock_get_config.return_value = self._mock_config()
        mock_run.return_value = self._mock_health_result(passed=True, warnings=["low disk"])
        run_logger = MagicMock()
        should_continue, is_critical = handle_preflight_checks("/repo", run_logger)
        assert should_continue is True
        assert is_critical is False

    @patch("pokepoke.utils.preflight_health.run_preflight_checks")
    @patch("pokepoke.config.get_config")
    def test_critical_failure_shuts_down(self, mock_get_config, mock_run):
        err = MagicMock()
        err.check_name = "disk_space"
        err.message = "Disk full"
        mock_get_config.return_value = self._mock_config(fail_critical=True)
        mock_run.return_value = self._mock_health_result(
            passed=False, errors=[err], critical=True,
        )
        run_logger = MagicMock()
        should_continue, is_critical = handle_preflight_checks("/repo", run_logger)
        assert should_continue is False
        assert is_critical is True

    @patch("pokepoke.utils.preflight_health.run_preflight_checks")
    @patch("pokepoke.config.get_config")
    def test_environmental_failure_shuts_down(self, mock_get_config, mock_run):
        err = MagicMock()
        err.check_name = "network"
        err.message = "No network"
        mock_get_config.return_value = self._mock_config(fail_env=True, graceful=True)
        mock_run.return_value = self._mock_health_result(
            passed=False, errors=[err], environmental=True,
        )
        run_logger = MagicMock()
        should_continue, is_critical = handle_preflight_checks("/repo", run_logger)
        assert should_continue is False
        assert is_critical is True

    @patch("pokepoke.utils.preflight_health.run_preflight_checks")
    @patch("pokepoke.config.get_config")
    def test_non_critical_failure_continues(self, mock_get_config, mock_run):
        err = MagicMock()
        err.check_name = "worktree"
        err.message = "Stale worktree found"
        mock_get_config.return_value = self._mock_config(fail_critical=True)
        mock_run.return_value = self._mock_health_result(
            passed=False, errors=[err], critical=False, environmental=False,
            warnings=["stale worktree"],
        )
        run_logger = MagicMock()
        should_continue, is_critical = handle_preflight_checks("/repo", run_logger)
        assert should_continue is True
        assert is_critical is False

    @patch("pokepoke.utils.preflight_health.run_preflight_checks")
    @patch("pokepoke.config.get_config")
    def test_self_repair_attempted_and_succeeded(self, mock_get_config, mock_run):
        err = MagicMock()
        err.check_name = "git_locks"
        err.message = "Lock file found"
        mock_get_config.return_value = self._mock_config(fail_critical=True)
        mock_run.return_value = self._mock_health_result(
            passed=False, errors=[err], self_repair_attempted=True,
            self_repair_successful=True, critical=False, environmental=False,
        )
        run_logger = MagicMock()
        should_continue, is_critical = handle_preflight_checks("/repo", run_logger)
        assert should_continue is True
        assert is_critical is False

    @patch("pokepoke.utils.preflight_health.run_preflight_checks")
    @patch("pokepoke.config.get_config")
    def test_self_repair_attempted_and_failed(self, mock_get_config, mock_run):
        err = MagicMock()
        err.check_name = "git_locks"
        err.message = "Lock file found"
        mock_get_config.return_value = self._mock_config(fail_critical=True)
        mock_run.return_value = self._mock_health_result(
            passed=False, errors=[err], self_repair_attempted=True,
            self_repair_successful=False, critical=True,
        )
        run_logger = MagicMock()
        should_continue, is_critical = handle_preflight_checks("/repo", run_logger)
        assert should_continue is False
        assert is_critical is True

    @patch("pokepoke.utils.preflight_health.run_preflight_checks")
    @patch("pokepoke.config.get_config")
    def test_environmental_no_graceful(self, mock_get_config, mock_run):
        """Environmental failure with graceful shutdown disabled continues."""
        err = MagicMock()
        err.check_name = "network"
        err.message = "No network"
        mock_get_config.return_value = self._mock_config(fail_env=True, graceful=False)
        mock_run.return_value = self._mock_health_result(
            passed=False, errors=[err], environmental=True, critical=False,
            warnings=["network down"],
        )
        run_logger = MagicMock()
        should_continue, is_critical = handle_preflight_checks("/repo", run_logger)
        # graceful_shutdown_on_failure is False, so it continues
        assert should_continue is True
        assert is_critical is False


class TestFormatPreflightErrors:
    """Tests for format_preflight_errors."""

    def test_single_error(self):
        err = MagicMock()
        err.check_name = "disk_space"
        err.message = "Low disk space"
        assert format_preflight_errors([err]) == "disk_space: Low disk space"

    def test_multiple_errors(self):
        e1 = MagicMock(check_name="disk_space", message="Low disk")
        e2 = MagicMock(check_name="git_locks", message="Stale lock")
        result = format_preflight_errors([e1, e2])
        assert result == "disk_space: Low disk; git_locks: Stale lock"

    def test_empty_errors(self):
        assert format_preflight_errors([]) == ""


class TestPreflightRateLimiting:
    """Tests for should_log_preflight_warning and rate-limiting."""

    def setup_method(self):
        reset_preflight_rate_limit()

    def teardown_method(self):
        reset_preflight_rate_limit()

    def test_first_occurrence_always_logged(self):
        assert should_log_preflight_warning("disk_space: Low disk") is True

    def test_second_occurrence_suppressed(self):
        should_log_preflight_warning("disk_space: Low disk")
        assert should_log_preflight_warning("disk_space: Low disk") is False

    def test_different_signature_resets(self):
        should_log_preflight_warning("disk_space: Low disk")
        assert should_log_preflight_warning("git_locks: Stale lock") is True

    def test_50th_occurrence_logged(self):
        sig = "disk_space: Low disk"
        should_log_preflight_warning(sig)  # count=1 -> True
        for _ in range(48):
            should_log_preflight_warning(sig)  # counts 2-49 -> False
        assert should_log_preflight_warning(sig) is True  # count=50 -> True

    def test_reset_clears_state(self):
        should_log_preflight_warning("disk_space: Low disk")
        should_log_preflight_warning("disk_space: Low disk")
        reset_preflight_rate_limit()
        assert should_log_preflight_warning("disk_space: Low disk") is True

    @patch("pokepoke.utils.preflight_health.run_preflight_checks")
    @patch("pokepoke.config.get_config")
    def test_passing_checks_reset_rate_limit(self, mock_get_config, mock_run):
        """When checks pass, the rate-limit counter resets."""
        cfg = MagicMock()
        cfg.preflight_health.enabled = True
        cfg.preflight_health.fail_on_critical_errors = True
        cfg.preflight_health.fail_on_environmental_errors = True
        cfg.preflight_health.graceful_shutdown_on_failure = True
        cfg.preflight_health.min_disk_space_gb = 5
        cfg.preflight_health.lock_timeout_seconds = 30
        cfg.preflight_health.worktree_test_timeout = 60
        cfg.preflight_health.max_orphan_worktrees = 10
        cfg.preflight_health.git_operation_timeout = 60
        cfg.preflight_health.enable_self_repair = False
        cfg.preflight_health.max_repair_attempts = 3
        mock_get_config.return_value = cfg

        # Set up some rate-limit state
        should_log_preflight_warning("some error")
        should_log_preflight_warning("some error")

        # Now a passing check should reset
        result = MagicMock()
        result.passed = True
        result.warnings = []
        mock_run.return_value = result

        handle_preflight_checks("/repo", MagicMock())

        # After reset, first new failure should be logged
        assert should_log_preflight_warning("some error") is True

    @patch("pokepoke.utils.preflight_health.run_preflight_checks")
    @patch("pokepoke.config.get_config")
    def test_warning_includes_error_details(self, mock_get_config, mock_run):
        """The log message includes specific error details, not just counts."""
        # Reset rate limiting state to ensure first call is logged
        reset_preflight_rate_limit()

        cfg = MagicMock()
        cfg.preflight_health.enabled = True
        cfg.preflight_health.fail_on_critical_errors = True
        cfg.preflight_health.fail_on_environmental_errors = True
        cfg.preflight_health.graceful_shutdown_on_failure = True
        cfg.preflight_health.min_disk_space_gb = 5
        cfg.preflight_health.lock_timeout_seconds = 30
        cfg.preflight_health.worktree_test_timeout = 60
        cfg.preflight_health.max_orphan_worktrees = 10
        cfg.preflight_health.git_operation_timeout = 60
        cfg.preflight_health.enable_self_repair = False
        cfg.preflight_health.max_repair_attempts = 3
        mock_get_config.return_value = cfg

        err = MagicMock()
        err.check_name = "disk_space"
        err.message = "Only 500MB free"
        result = MagicMock()
        result.passed = False
        result.errors = [err]
        result.warnings = []
        result.self_repair_attempted = False
        result.has_critical_errors.return_value = False
        result.has_environmental_errors.return_value = False
        mock_run.return_value = result

        run_logger = MagicMock()

        # First call: should log with details
        handle_preflight_checks("/repo", run_logger)
        first_warning_calls = [
            c for c in run_logger.log_orchestrator.call_args_list
            if c[1].get("level") == "WARNING"
        ]
        assert len(first_warning_calls) > 0
        # The warning message should contain the error signature
        # Message is passed as positional arg (call[0][0]), not keyword arg
        found_detail = False
        for call in first_warning_calls:
            msg = call[0][0] if call[0] else ""
            if "disk_space: Only 500MB free" in msg:
                found_detail = True
                break
        assert found_detail

        run_logger.reset_mock()

        # Second call: should NOT log (suppressed)
        handle_preflight_checks("/repo", run_logger)
        second_warning_count = sum(
            1 for c in run_logger.log_orchestrator.call_args_list
            if c[1].get("level") == "WARNING"
        )
        assert second_warning_count == 0
