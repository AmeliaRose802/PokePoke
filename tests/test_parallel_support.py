"""Tests for parallel_support helper functions."""

import concurrent.futures
import time
from unittest.mock import MagicMock, Mock, patch


from pokepoke.parallel_support import handle_preflight_checks, finalize_workers
from pokepoke.types import AgentStats, BeadsWorkItem, SessionStats, WorkItemResult


def _make_item(item_id: str = "t1") -> BeadsWorkItem:
    return BeadsWorkItem(
        id=item_id, title=f"Title-{item_id}", status="open",
        priority=1, issue_type="task",
    )


# ── handle_preflight_checks ──────────────────────────────────────────


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

    def _mock_health_result(self, *, passed: bool = True, errors=None,
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

    @patch("pokepoke.preflight_health.run_preflight_checks")
    @patch("pokepoke.config.get_config")
    def test_passed_returns_true(self, mock_get_config, mock_run):
        mock_get_config.return_value = self._mock_config()
        mock_run.return_value = self._mock_health_result(passed=True, warnings=["low disk"])
        run_logger = MagicMock()
        should_continue, is_critical = handle_preflight_checks("/repo", run_logger)
        assert should_continue is True
        assert is_critical is False

    @patch("pokepoke.preflight_health.run_preflight_checks")
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

    @patch("pokepoke.preflight_health.run_preflight_checks")
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

    @patch("pokepoke.preflight_health.run_preflight_checks")
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

    @patch("pokepoke.preflight_health.run_preflight_checks")
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

    @patch("pokepoke.preflight_health.run_preflight_checks")
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

    @patch("pokepoke.preflight_health.run_preflight_checks")
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


# ── finalize_workers ──────────────────────────────────────────────────


class TestFinalizeWorkers:
    """Tests for finalize_workers."""

    @patch("pokepoke.parallel_support.terminal_ui")
    @patch("pokepoke.parallel_support.kill_orphaned_copilot_processes")
    def test_empty_futures(self, mock_kill, mock_tui):
        stats = SessionStats(agent_stats=AgentStats())
        run_logger = MagicMock()
        total, timeout = finalize_workers({}, stats, time.time(), 0, run_logger, Mock())
        assert total == 0
        assert timeout is False
        mock_kill.assert_not_called()

    @patch("pokepoke.parallel_support.terminal_ui")
    @patch("pokepoke.parallel_support.kill_orphaned_copilot_processes")
    def test_successful_worker(self, mock_kill, mock_tui):
        item = _make_item("s1")
        result = WorkItemResult(success=True, request_count=3)
        fut = concurrent.futures.Future()
        fut.set_result(result)
        stats = SessionStats(agent_stats=AgentStats())
        run_logger = MagicMock()
        record_fn = Mock()
        total, timeout = finalize_workers({fut: item}, stats, time.time(), 5, run_logger, record_fn)
        assert total == 8  # 5 + 3
        assert timeout is False
        record_fn.assert_called_once()
        mock_kill.assert_called_once()

    @patch("pokepoke.parallel_support.terminal_ui")
    @patch("pokepoke.parallel_support.kill_orphaned_copilot_processes")
    def test_failed_worker(self, mock_kill, mock_tui):
        item = _make_item("f1")
        fut = concurrent.futures.Future()
        fut.set_exception(RuntimeError("boom"))
        stats = SessionStats(agent_stats=AgentStats())
        run_logger = MagicMock()
        record_fn = Mock()
        total, timeout = finalize_workers({fut: item}, stats, time.time(), 2, run_logger, record_fn)
        assert total == 2  # no request_count added from failed result
        assert timeout is False
        record_fn.assert_called_once()

    @patch("pokepoke.parallel_support.terminal_ui")
    @patch("pokepoke.parallel_support.kill_orphaned_copilot_processes")
    def test_record_fn_exception(self, mock_kill, mock_tui):
        """record_fn raising doesn't crash finalize_workers."""
        item = _make_item("r1")
        result = WorkItemResult(success=True, request_count=1)
        fut = concurrent.futures.Future()
        fut.set_result(result)
        stats = SessionStats(agent_stats=AgentStats())
        run_logger = MagicMock()
        record_fn = Mock(side_effect=ValueError("record error"))
        total, timeout = finalize_workers({fut: item}, stats, time.time(), 0, run_logger, record_fn)
        assert total == 1
        assert timeout is False
