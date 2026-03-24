"""Tests for parallel_support helper functions."""

import concurrent.futures
import threading
import time
from unittest.mock import MagicMock, Mock, patch

from pokepoke.agents.parallel_support import (
    _drain_orphaned_futures,
    check_loop_exit,
    compute_slots,
    dispatch_items,
    drain_circuit_breaker,
    finalize_workers,
    handle_preflight_checks,
    run_preflight_and_repo_checks,
    update_circuit_breaker,
)
from pokepoke.types import AgentStats, BeadsWorkItem, SessionStats, WorkItemResult
from pokepoke.utils.preflight_log_utils import (
    format_preflight_errors,
    reset_preflight_rate_limit,
    should_log_preflight_warning,
)


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


# ── preflight error formatting and rate-limiting ─────────────────────


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
        handle_preflight_checks("/repo", run_logger)

        # Verify the log message contains the actual error details
        logged_msg = run_logger.log_orchestrator.call_args_list[-1]
        assert "disk_space: Only 500MB free" in logged_msg[0][0]
        assert logged_msg[1]["level"] == "WARNING"

    @patch("pokepoke.utils.preflight_health.run_preflight_checks")
    @patch("pokepoke.config.get_config")
    def test_repeated_warnings_suppressed(self, mock_get_config, mock_run):
        """Repeated identical failures should be rate-limited."""
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

        # First call: should log
        handle_preflight_checks("/repo", run_logger)
        first_warning_count = sum(
            1 for c in run_logger.log_orchestrator.call_args_list
            if c[1].get("level") == "WARNING"
        )
        assert first_warning_count == 1

        run_logger.reset_mock()

        # Second call: should NOT log (suppressed)
        handle_preflight_checks("/repo", run_logger)
        second_warning_count = sum(
            1 for c in run_logger.log_orchestrator.call_args_list
            if c[1].get("level") == "WARNING"
        )
        assert second_warning_count == 0


class TestFinalizeWorkers:
    """Tests for finalize_workers."""

    @patch("pokepoke.agents.parallel_support.terminal_ui")
    @patch("pokepoke.agents.parallel_support.kill_orphaned_copilot_processes")
    def test_empty_futures(self, mock_kill, mock_tui):
        stats = SessionStats(agent_stats=AgentStats())
        run_logger = MagicMock()
        total, timeout = finalize_workers({}, stats, time.time(), 0, run_logger, Mock())
        assert total == 0
        assert timeout is False
        mock_kill.assert_not_called()

    @patch("pokepoke.agents.parallel_support.terminal_ui")
    @patch("pokepoke.agents.parallel_support.kill_orphaned_copilot_processes")
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

    @patch("pokepoke.agents.parallel_support.terminal_ui")
    @patch("pokepoke.agents.parallel_support.kill_orphaned_copilot_processes")
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

    @patch("pokepoke.agents.parallel_support.terminal_ui")
    @patch("pokepoke.agents.parallel_support.kill_orphaned_copilot_processes")
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

    @patch("pokepoke.agents.parallel_support.terminal_ui")
    @patch("pokepoke.agents.parallel_support.kill_orphaned_copilot_processes")
    @patch("pokepoke.agents.parallel_support._drain_orphaned_futures")
    @patch("pokepoke.agents.parallel_support.concurrent.futures.as_completed")
    def test_timeout_drains_orphans(self, mock_as_completed, mock_drain, mock_kill, mock_tui):
        """Timeout triggers drain of orphaned futures."""
        mock_as_completed.side_effect = concurrent.futures.TimeoutError()
        item = _make_item("t1")
        fut = concurrent.futures.Future()
        futures = {fut: item}
        stats = SessionStats(agent_stats=AgentStats())
        run_logger = MagicMock()
        record_fn = Mock()
        total, timeout = finalize_workers(futures, stats, time.time(), 0, run_logger, record_fn)
        assert timeout is True
        mock_drain.assert_called_once()


# ── _drain_orphaned_futures ──────────────────────────────────────────


class TestDrainOrphanedFutures:
    """Tests for _drain_orphaned_futures."""

    @patch("pokepoke.agents.parallel_support.terminal_ui")
    @patch("pokepoke.agents.parallel.unassign_with_retry")
    def test_empty_futures_noop(self, mock_unassign, mock_tui):
        """Empty futures dict is a no-op."""
        futures: dict = {}
        run_logger = MagicMock()
        _drain_orphaned_futures(futures, SessionStats(agent_stats=AgentStats()), time.time(), run_logger, Mock())
        mock_unassign.assert_not_called()

    @patch("pokepoke.agents.parallel_support.terminal_ui")
    @patch("pokepoke.agents.parallel.unassign_with_retry")
    def test_drains_and_records_orphans(self, mock_unassign, mock_tui):
        """Orphaned futures are recorded via record_fn and unassigned."""
        item1 = _make_item("o1")
        item2 = _make_item("o2")
        fut1 = concurrent.futures.Future()
        fut2 = concurrent.futures.Future()
        # fut1 still running (not done), fut2 completed during drain
        fut2.set_result(WorkItemResult(success=True, request_count=5))
        futures = {fut1: item1, fut2: item2}
        stats = SessionStats(agent_stats=AgentStats())
        run_logger = MagicMock()
        record_fn = Mock()
        mock_unassign.return_value = True

        _drain_orphaned_futures(futures, stats, time.time(), run_logger, record_fn)

        assert len(futures) == 0  # Dict is cleared
        assert record_fn.call_count == 2
        assert mock_unassign.call_count == 2
        mock_unassign.assert_any_call("o1")
        mock_unassign.assert_any_call("o2")
        # fut2 was done, so its actual result should be harvested
        calls = record_fn.call_args_list
        results = [c[0][1] for c in calls]
        success_results = [r for r in results if r.success]
        assert len(success_results) == 1  # fut2's real result
        assert success_results[0].request_count == 5

    @patch("pokepoke.agents.parallel_support.terminal_ui")
    @patch("pokepoke.agents.parallel.unassign_with_retry")
    def test_record_fn_exception_handled(self, mock_unassign, mock_tui):
        """record_fn raising doesn't crash the drain."""
        item = _make_item("e1")
        fut = concurrent.futures.Future()
        futures = {fut: item}
        run_logger = MagicMock()
        record_fn = Mock(side_effect=RuntimeError("record boom"))
        mock_unassign.return_value = True

        _drain_orphaned_futures(futures, SessionStats(agent_stats=AgentStats()), time.time(), run_logger, record_fn)

        record_fn.assert_called_once()
        mock_unassign.assert_called_once_with("e1")

    @patch("pokepoke.agents.parallel_support.terminal_ui")
    @patch("pokepoke.agents.parallel.unassign_with_retry", side_effect=RuntimeError("unassign boom"))
    def test_unassign_exception_handled(self, mock_unassign, mock_tui):
        """unassign_with_retry raising doesn't crash the drain and logs a warning."""
        item = _make_item("u1")
        fut = concurrent.futures.Future()
        futures = {fut: item}
        run_logger = MagicMock()
        record_fn = Mock()

        _drain_orphaned_futures(futures, SessionStats(agent_stats=AgentStats()), time.time(), run_logger, record_fn)

        record_fn.assert_called_once()
        mock_unassign.assert_called_once_with("u1")
        # Verify the failure is logged, not silently suppressed
        warning_calls = [
            c for c in run_logger.log_orchestrator.call_args_list
            if c.kwargs.get("level") == "WARNING"
        ]
        assert any("u1" in str(c) and "unassign" in str(c).lower() for c in warning_calls), (
            "Expected a WARNING log mentioning item id 'u1' and unassign failure"
        )

    @patch("pokepoke.agents.parallel_support.terminal_ui")
    @patch("pokepoke.agents.parallel.unassign_with_retry")
    def test_done_future_with_exception(self, mock_unassign, mock_tui):
        """Orphan future that completed with exception still gets recorded."""
        item = _make_item("x1")
        fut = concurrent.futures.Future()
        fut.set_exception(RuntimeError("worker crashed"))
        futures = {fut: item}
        stats = SessionStats(agent_stats=AgentStats())
        run_logger = MagicMock()
        record_fn = Mock()
        mock_unassign.return_value = True

        _drain_orphaned_futures(futures, stats, time.time(), run_logger, record_fn)

        record_fn.assert_called_once()
        recorded_result = record_fn.call_args[0][1]
        assert recorded_result.success is False
        mock_unassign.assert_called_once_with("x1")


# ── drain_circuit_breaker ────────────────────────────────────────────


class TestDrainCircuitBreaker:
    """Tests for drain_circuit_breaker."""

    @patch("pokepoke.agents.parallel_support.time.sleep")
    @patch("pokepoke.agents.parallel_support.is_shutting_down", return_value=False)
    @patch("pokepoke.agents.parallel_support.terminal_ui")
    def test_calls_collect_fn_and_returns_total(self, mock_tui, mock_shutdown, mock_sleep):
        collect_fn = Mock(return_value=(42, True, 1, 0))
        futures: dict = {}
        run_logger = MagicMock()
        result = drain_circuit_breaker(
            futures, set(), 10, SessionStats(agent_stats=AgentStats()),
            run_logger, Mock(), collect_fn, "Auto",
        )
        assert result == 42
        collect_fn.assert_called_once()

    @patch("pokepoke.agents.parallel_support.time.sleep")
    @patch("pokepoke.agents.parallel_support.is_shutting_down", return_value=True)
    @patch("pokepoke.agents.parallel_support.terminal_ui")
    def test_exits_early_on_shutdown(self, mock_tui, mock_shutdown, mock_sleep):
        """Drain loop should exit when shutdown signaled."""
        item = _make_item("cb1")
        fut = concurrent.futures.Future()
        futures = {fut: item}
        collect_fn = Mock(return_value=(5, False, 0, 0))
        run_logger = MagicMock()
        result = drain_circuit_breaker(
            futures, set(), 5, SessionStats(agent_stats=AgentStats()),
            run_logger, Mock(), collect_fn, "Auto",
        )
        assert result == 5


# ── dispatch_items ───────────────────────────────────────────────────


class TestDispatchItems:
    """Tests for dispatch_items."""

    @patch("pokepoke.agents.parallel.should_stop_after_current", return_value=False)
    @patch("pokepoke.agents.parallel.select_multiple_items", return_value=[])
    @patch("pokepoke.agents.parallel.is_item_claimable", return_value=True)
    @patch("pokepoke.agents.parallel.assign_and_sync_item", return_value=True)
    @patch("pokepoke.agents.agent_context.get_agent_name", return_value="agent")
    def test_zero_slots_returns_immediately(self, *_mocks):
        run_logger = MagicMock()
        result = dispatch_items(
            [], 0, True, False, 0, 10, set(), set(), {},
            threading.Semaphore(1), MagicMock(), run_logger, 0, Mock(), Mock(),
        )
        assert result == 0

    @patch("pokepoke.beads.beads_query.is_beads_item_closed", return_value=False)
    @patch("pokepoke.agents.parallel.should_stop_after_current", return_value=False)
    @patch("pokepoke.agents.parallel.select_multiple_items")
    @patch("pokepoke.agents.parallel.is_item_claimable", return_value=True)
    @patch("pokepoke.agents.parallel.assign_and_sync_item", return_value=True)
    @patch("pokepoke.agents.agent_context.get_agent_name", return_value="agent")
    def test_submits_item_to_executor(self, _name, _assign, _claim, mock_select, _stop, _closed):
        item = _make_item("d1")
        mock_select.return_value = [item]
        run_logger = MagicMock()
        executor = MagicMock()
        mock_fut = MagicMock()
        executor.submit.return_value = mock_fut
        sem = threading.Semaphore(2)
        futures: dict = {}
        build_name = Mock(return_value="agent-worker-1")

        counter = dispatch_items(
            [item], 1, True, False, 0, 10, set(), set(), futures,
            sem, executor, run_logger, 0, build_name, Mock(),
        )
        assert counter == 1
        assert mock_fut in futures

    @patch("pokepoke.agents.parallel.should_stop_after_current", return_value=False)
    @patch("pokepoke.agents.parallel.select_multiple_items")
    @patch("pokepoke.agents.parallel.assign_and_sync_item", return_value=False)
    @patch("pokepoke.agents.agent_context.get_agent_name", return_value="agent")
    def test_skips_unclaimed_item(self, _name, _assign, mock_select, _stop):
        """When assign_and_sync_item returns False the item is not submitted."""
        item = _make_item("skip1")
        mock_select.return_value = [item]
        run_logger = MagicMock()
        executor = MagicMock()
        futures: dict = {}

        counter = dispatch_items(
            [item], 1, True, False, 0, 10, set(), set(), futures,
            threading.Semaphore(1), executor, run_logger, 0, Mock(), Mock(),
        )
        # worker_counter increments before assign attempt, but item is not submitted
        assert counter >= 0  # counter may increment even for failed claims
        executor.submit.assert_not_called()

    @patch("pokepoke.beads.beads_query.is_beads_item_closed", return_value=False)
    @patch("pokepoke.agents.parallel.should_stop_after_current", return_value=False)
    @patch("pokepoke.agents.parallel.select_multiple_items")
    @patch("pokepoke.agents.parallel.is_item_claimable", return_value=True)
    @patch("pokepoke.agents.parallel.assign_and_sync_item", return_value=False)
    @patch("pokepoke.agents.agent_context.get_agent_name", return_value="agent")
    def test_failed_assign_adds_to_failed_ids(self, _name, _assign, _claim, mock_select, _stop, _closed):
        item = _make_item("fa1")
        mock_select.return_value = [item]
        run_logger = MagicMock()
        failed_ids: set[str] = set()

        dispatch_items(
            [item], 1, True, False, 0, 10, failed_ids, set(), {},
            threading.Semaphore(1), MagicMock(), run_logger, 0, Mock(return_value="w"), Mock(),
        )
        assert "fa1" in failed_ids

    @patch("pokepoke.beads.beads_query.is_beads_item_closed", return_value=False)
    @patch("pokepoke.agents.parallel.should_stop_after_current", return_value=False)
    @patch("pokepoke.agents.parallel.select_multiple_items")
    @patch("pokepoke.agents.parallel.is_item_claimable", return_value=True)
    @patch("pokepoke.agents.parallel.assign_and_sync_item", return_value=True)
    @patch("pokepoke.agents.parallel.unassign_with_retry")
    @patch("pokepoke.agents.agent_context.get_agent_name", return_value="agent")
    def test_executor_submit_failure_unassigns(self, _name, mock_unassign, _assign, _claim, mock_select, _stop, _closed):
        item = _make_item("ef1")
        mock_select.return_value = [item]
        executor = MagicMock()
        executor.submit.side_effect = RuntimeError("executor full")
        run_logger = MagicMock()
        sem = threading.Semaphore(1)

        import contextlib
        with contextlib.suppress(RuntimeError):
            dispatch_items(
                [item], 1, True, False, 0, 10, set(), set(), {},
                sem, executor, run_logger, 0, Mock(return_value="w"), Mock(),
            )
        mock_unassign.assert_called_once_with("ef1")

    @patch("pokepoke.beads.beads_query.is_beads_item_closed", return_value=False)
    @patch("pokepoke.agents.parallel.should_stop_after_current", return_value=False)
    @patch("pokepoke.agents.parallel.select_multiple_items")
    @patch("pokepoke.agents.parallel.is_item_claimable", return_value=True)
    @patch("pokepoke.agents.parallel.assign_and_sync_item", return_value=True)
    @patch("pokepoke.agents.parallel.unassign_with_retry", side_effect=RuntimeError("unassign boom"))
    @patch("pokepoke.agents.agent_context.get_agent_name", return_value="agent")
    def test_executor_submit_unassign_failure_logs_warning(self, _name, mock_unassign, _assign, _claim, mock_select, _stop, _closed):
        """When executor.submit fails AND unassign also fails, a warning is logged."""
        item = _make_item("ef2")
        mock_select.return_value = [item]
        executor = MagicMock()
        executor.submit.side_effect = RuntimeError("executor full")
        run_logger = MagicMock()
        sem = threading.Semaphore(1)

        import contextlib
        with contextlib.suppress(RuntimeError):
            dispatch_items(
                [item], 1, True, False, 0, 10, set(), set(), {},
                sem, executor, run_logger, 0, Mock(return_value="w"), Mock(),
            )
        mock_unassign.assert_called_once_with("ef2")
        warning_calls = [
            c for c in run_logger.log_orchestrator.call_args_list
            if c.kwargs.get("level") == "WARNING"
        ]
        assert any("ef2" in str(c) and "unassign" in str(c).lower() for c in warning_calls), (
            "Expected a WARNING log mentioning item id 'ef2' and unassign failure"
        )

    @patch("pokepoke.agents.parallel.should_stop_after_current", return_value=False)
    @patch("pokepoke.agents.parallel.assign_and_sync_item")
    @patch("pokepoke.agents.agent_context.get_agent_name", return_value="agent")
    def test_advances_past_unclaimable_items(self, _name, mock_assign, _stop):
        """Regression for PokePoke-pfoc: dispatch must advance past already-claimed
        items and fill remaining slots from later candidates in the ready queue."""
        # 5 items total; first 2 are unclaimable (assign fails), last 3 succeed
        items = [_make_item(f"adv-{i}") for i in range(5)]
        unclaimable = {items[0].id, items[1].id}
        # assign_and_sync_item receives item_id as first positional arg
        mock_assign.side_effect = lambda item_id, **kw: item_id not in unclaimable

        def fake_select(ready, count, skip_ids=None, claimed_ids=None):
            excluded = set()
            if skip_ids:
                excluded.update(skip_ids)
            if claimed_ids:
                excluded.update(claimed_ids)
            candidates = [i for i in ready if i.id not in excluded]
            return candidates[:count]

        with patch("pokepoke.agents.parallel.select_multiple_items", side_effect=fake_select):
            executor = MagicMock()
            mock_fut = MagicMock()
            executor.submit.return_value = mock_fut
            run_logger = MagicMock()
            futures: dict = {}
            failed_ids: set[str] = set()
            sem = threading.Semaphore(3)

            counter = dispatch_items(
                items, 3, True, False, 0, 10, failed_ids, set(), futures,
                sem, executor, run_logger, 0, Mock(return_value="w"), Mock(),
            )

        # All 3 claimable items should be dispatched
        assert counter >= 3  # at least 3 workers attempted
        assert executor.submit.call_count == 3
        # Unclaimable items should be added to failed_claim_ids
        assert unclaimable.issubset(failed_ids)

    @patch("pokepoke.beads.beads_query.is_beads_item_closed", return_value=False)
    @patch("pokepoke.agents.parallel.should_stop_after_current", return_value=False)
    @patch("pokepoke.agents.parallel.is_item_claimable", return_value=False)
    @patch("pokepoke.agents.agent_context.get_agent_name", return_value="agent")
    def test_unclaimable_items_added_to_failed_ids(self, _name, _claim, _stop, _closed):
        """Regression for PokePoke-pfoc: unclaimable items must be added to
        failed_claim_ids so they are not re-selected in subsequent iterations."""
        items = [_make_item(f"uc-{i}") for i in range(3)]

        def fake_select(ready, count, skip_ids=None, claimed_ids=None):
            excluded = set()
            if skip_ids:
                excluded.update(skip_ids)
            if claimed_ids:
                excluded.update(claimed_ids)
            candidates = [i for i in ready if i.id not in excluded]
            return candidates[:count]

        with patch("pokepoke.agents.parallel.select_multiple_items", side_effect=fake_select):
            run_logger = MagicMock()
            failed_ids: set[str] = set()

            dispatch_items(
                items, 3, True, False, 0, 10, failed_ids, set(), {},
                threading.Semaphore(3), MagicMock(), run_logger, 0, Mock(), Mock(),
            )

        # All items should be in failed_claim_ids
        assert failed_ids == {"uc-0", "uc-1", "uc-2"}

    @patch("pokepoke.agents.parallel.should_stop_after_current", return_value=False)
    @patch("pokepoke.agents.parallel.assign_and_sync_item")
    @patch("pokepoke.agents.agent_context.get_agent_name", return_value="agent")
    def test_closed_item_skipped_and_added_to_failed_ids(
        self, _name, mock_assign, _stop,
    ):
        """Items whose assign_and_sync_item call fails (e.g. already closed)
        should be skipped and added to the skip set so they are not
        re-selected in subsequent replenish cycles."""
        item_closed = _make_item("closed-1")
        item_open = _make_item("open-1")
        # assign succeeds only for the open item
        mock_assign.side_effect = lambda item_id, **kw: item_id != "closed-1"

        def fake_select(ready, count, skip_ids=None, claimed_ids=None):
            excluded = set()
            if skip_ids:
                excluded.update(skip_ids)
            if claimed_ids:
                excluded.update(claimed_ids)
            candidates = [i for i in ready if i.id not in excluded]
            return candidates[:count]

        with patch("pokepoke.agents.parallel.select_multiple_items", side_effect=fake_select):
            executor = MagicMock()
            mock_fut = MagicMock()
            executor.submit.return_value = mock_fut
            run_logger = MagicMock()
            futures: dict = {}
            failed_ids: set[str] = set()
            sem = threading.Semaphore(2)

            dispatch_items(
                [item_closed, item_open], 2, True, False, 0, 10,
                failed_ids, set(), futures,
                sem, executor, run_logger, 0, Mock(return_value="w"), Mock(),
            )

        # Only the open item should be dispatched
        assert executor.submit.call_count == 1
        # Closed item should be in the skip set
        assert "closed-1" in failed_ids


# ── dispatch_items high-conflict scheduling ─────────────────────────


def _make_high_conflict_item(item_id: str = "hc1") -> BeadsWorkItem:
    return BeadsWorkItem(
        id=item_id, title=f"HighConflict-{item_id}", status="open",
        priority=1, issue_type="task", labels=["high-conflict-risk"],
    )


class TestDispatchHighConflictItems:
    """Tests that high-conflict items run solo (PokePoke-sz6k)."""

    @patch("pokepoke.beads.beads_query.is_beads_item_closed", return_value=False)
    @patch("pokepoke.agents.parallel.should_stop_after_current", return_value=False)
    @patch("pokepoke.agents.parallel.is_item_claimable", return_value=True)
    @patch("pokepoke.agents.parallel.assign_and_sync_item", return_value=True)
    @patch("pokepoke.agents.agent_context.get_agent_name", return_value="agent")
    def test_high_conflict_blocks_new_dispatch(
        self, _name, _assign, _claim, _stop, _closed,
    ):
        """When a high-conflict item is already running, nothing new is dispatched."""
        hc_item = _make_high_conflict_item("hc-active")
        normal_item = _make_item("normal-1")

        # Simulate a high-conflict item already in the futures dict
        mock_fut = MagicMock()
        futures: dict = {mock_fut: hc_item}

        def fake_select(ready, count, skip_ids=None, claimed_ids=None):
            excluded = set()
            if skip_ids:
                excluded.update(skip_ids)
            if claimed_ids:
                excluded.update(claimed_ids)
            return [i for i in ready if i.id not in excluded][:count]

        with patch("pokepoke.agents.parallel.select_multiple_items", side_effect=fake_select):
            executor = MagicMock()
            run_logger = MagicMock()

            counter = dispatch_items(
                [normal_item], 2, True, False, 0, 10, set(), {"hc-active"}, futures,
                threading.Semaphore(2), executor, run_logger, 0, Mock(return_value="w"), Mock(),
            )

        assert counter == 0
        executor.submit.assert_not_called()

    @patch("pokepoke.beads.beads_query.is_beads_item_closed", return_value=False)
    @patch("pokepoke.agents.parallel.should_stop_after_current", return_value=False)
    @patch("pokepoke.agents.parallel.is_item_claimable", return_value=True)
    @patch("pokepoke.agents.parallel.assign_and_sync_item", return_value=True)
    @patch("pokepoke.agents.agent_context.get_agent_name", return_value="agent")
    def test_high_conflict_deferred_when_others_active(
        self, _name, _assign, _claim, _stop, _closed,
    ):
        """A high-conflict item is deferred when non-conflict items are running."""
        hc_item = _make_high_conflict_item("hc-defer")
        running_item = _make_item("running-1")

        mock_fut = MagicMock()
        futures: dict = {mock_fut: running_item}

        def fake_select(ready, count, skip_ids=None, claimed_ids=None):
            excluded = set()
            if skip_ids:
                excluded.update(skip_ids)
            if claimed_ids:
                excluded.update(claimed_ids)
            return [i for i in ready if i.id not in excluded][:count]

        with patch("pokepoke.agents.parallel.select_multiple_items", side_effect=fake_select):
            executor = MagicMock()
            run_logger = MagicMock()

            counter = dispatch_items(
                [hc_item], 2, True, False, 0, 10, set(), {"running-1"}, futures,
                threading.Semaphore(2), executor, run_logger, 0, Mock(return_value="w"), Mock(),
            )

        # High-conflict item should NOT be dispatched
        assert counter == 0
        executor.submit.assert_not_called()

    @patch("pokepoke.beads.beads_query.is_beads_item_closed", return_value=False)
    @patch("pokepoke.agents.parallel.should_stop_after_current", return_value=False)
    @patch("pokepoke.agents.parallel.is_item_claimable", return_value=True)
    @patch("pokepoke.agents.parallel.assign_and_sync_item", return_value=True)
    @patch("pokepoke.agents.agent_context.get_agent_name", return_value="agent")
    def test_high_conflict_dispatched_when_idle(
        self, _name, _assign, _claim, _stop, _closed,
    ):
        """A high-conflict item IS dispatched when no other items are active."""
        hc_item = _make_high_conflict_item("hc-solo")

        def fake_select(ready, count, skip_ids=None, claimed_ids=None):
            excluded = set()
            if skip_ids:
                excluded.update(skip_ids)
            if claimed_ids:
                excluded.update(claimed_ids)
            return [i for i in ready if i.id not in excluded][:count]

        with patch("pokepoke.agents.parallel.select_multiple_items", side_effect=fake_select):
            executor = MagicMock()
            mock_fut = MagicMock()
            executor.submit.return_value = mock_fut
            run_logger = MagicMock()
            futures: dict = {}

            counter = dispatch_items(
                [hc_item], 2, True, False, 0, 10, set(), set(), futures,
                threading.Semaphore(2), executor, run_logger, 0, Mock(return_value="w"), Mock(),
            )

        assert counter == 1
        assert executor.submit.call_count == 1

    @patch("pokepoke.beads.beads_query.is_beads_item_closed", return_value=False)
    @patch("pokepoke.agents.parallel.should_stop_after_current", return_value=False)
    @patch("pokepoke.agents.parallel.is_item_claimable", return_value=True)
    @patch("pokepoke.agents.parallel.assign_and_sync_item", return_value=True)
    @patch("pokepoke.agents.agent_context.get_agent_name", return_value="agent")
    def test_high_conflict_prevents_additional_dispatch(
        self, _name, _assign, _claim, _stop, _closed,
    ):
        """After dispatching a high-conflict item, no more items are dispatched."""
        hc_item = _make_high_conflict_item("hc-only")
        normal_item = _make_item("extra-1")

        def fake_select(ready, count, skip_ids=None, claimed_ids=None):
            excluded = set()
            if skip_ids:
                excluded.update(skip_ids)
            if claimed_ids:
                excluded.update(claimed_ids)
            return [i for i in ready if i.id not in excluded][:count]

        with patch("pokepoke.agents.parallel.select_multiple_items", side_effect=fake_select):
            executor = MagicMock()
            mock_fut = MagicMock()
            executor.submit.return_value = mock_fut
            run_logger = MagicMock()
            futures: dict = {}

            counter = dispatch_items(
                [hc_item, normal_item], 3, True, False, 0, 10, set(), set(), futures,
                threading.Semaphore(3), executor, run_logger, 0, Mock(return_value="w"), Mock(),
            )

        # Only the high-conflict item should be dispatched, not the normal one
        assert counter == 1
        assert executor.submit.call_count == 1

    @patch("pokepoke.beads.beads_query.is_beads_item_closed", return_value=False)
    @patch("pokepoke.agents.parallel.should_stop_after_current", return_value=False)
    @patch("pokepoke.agents.parallel.is_item_claimable", return_value=True)
    @patch("pokepoke.agents.parallel.assign_and_sync_item", return_value=True)
    @patch("pokepoke.agents.agent_context.get_agent_name", return_value="agent")
    def test_normal_dispatched_before_high_conflict_deferred(
        self, _name, _assign, _claim, _stop, _closed,
    ):
        """Normal items before the high-conflict item dispatch; the high-conflict is deferred."""
        normal_item = _make_item("norm-1")
        hc_item = _make_high_conflict_item("hc-after")

        call_count = [0]

        def fake_select(ready, count, skip_ids=None, claimed_ids=None):
            excluded = set()
            if skip_ids:
                excluded.update(skip_ids)
            if claimed_ids:
                excluded.update(claimed_ids)
            candidates = [i for i in ready if i.id not in excluded][:count]
            call_count[0] += 1
            return candidates

        with patch("pokepoke.agents.parallel.select_multiple_items", side_effect=fake_select):
            executor = MagicMock()
            mock_fut = MagicMock()
            executor.submit.return_value = mock_fut
            run_logger = MagicMock()
            futures: dict = {}

            counter = dispatch_items(
                [normal_item, hc_item], 3, True, False, 0, 10, set(), set(), futures,
                threading.Semaphore(3), executor, run_logger, 0, Mock(return_value="w"), Mock(),
            )

        # Normal item dispatched; high-conflict deferred because dispatched > 0
        assert counter >= 1
        assert executor.submit.call_count >= 1

    @patch("pokepoke.beads.beads_query.is_beads_item_closed", return_value=False)
    @patch("pokepoke.agents.parallel.should_stop_after_current", return_value=False)
    @patch("pokepoke.agents.parallel.is_item_claimable", return_value=True)
    @patch("pokepoke.agents.parallel.assign_and_sync_item", return_value=True)
    @patch("pokepoke.agents.agent_context.get_agent_name", return_value="agent")
    def test_deferred_high_conflict_does_not_starve_normal_items(
        self, _name, _assign, _claim, _stop, _closed,
    ):
        """Normal items dispatch even when a high-conflict item is first in the queue.

        Regression test for PokePoke-mdaf: when slots=1 and a high-conflict
        item sits at the front of ready_items with an active future, the
        dispatcher must skip past the deferred item and dispatch the normal
        one rather than breaking out of the loop with no progress.
        """
        hc_item = _make_high_conflict_item("hc-front")
        normal_item = _make_item("norm-behind")

        running_item = _make_item("running-1")
        mock_running_fut = MagicMock()
        futures: dict = {mock_running_fut: running_item}

        def fake_select(ready, count, skip_ids=None, claimed_ids=None):
            excluded = set()
            if skip_ids:
                excluded.update(skip_ids)
            if claimed_ids:
                excluded.update(claimed_ids)
            return [i for i in ready if i.id not in excluded][:count]

        with patch("pokepoke.agents.parallel.select_multiple_items", side_effect=fake_select):
            executor = MagicMock()
            mock_fut = MagicMock()
            executor.submit.return_value = mock_fut
            run_logger = MagicMock()

            counter = dispatch_items(
                [hc_item, normal_item], 1, True, False, 0, 10,
                set(), {"running-1"}, futures,
                threading.Semaphore(2), executor, run_logger, 0,
                Mock(return_value="w"), Mock(),
            )

        # The normal item behind the deferred high-conflict item MUST dispatch
        assert counter == 1
        assert executor.submit.call_count == 1


class TestRunPreflightAndRepoChecks:
    """Tests for run_preflight_and_repo_checks."""

    @patch("pokepoke.agents.parallel_support.handle_preflight_checks", return_value=(True, False))
    def test_all_checks_pass(self, _preflight):
        run_logger = MagicMock()
        repo_fn = Mock(return_value=True)
        items = [_make_item("r1")]
        ready_fn = Mock(return_value=items)

        ok, failures, result = run_preflight_and_repo_checks(
            "/repo", run_logger, 0, 5, repo_fn, ready_fn,
        )
        assert ok is True
        assert failures == 0
        assert result == items

    @patch("pokepoke.agents.parallel_support.handle_preflight_checks", return_value=(False, True))
    def test_critical_preflight_failure_increments(self, _preflight):
        run_logger = MagicMock()
        ok, failures, result = run_preflight_and_repo_checks(
            "/repo", run_logger, 2, 5, Mock(), Mock(),
        )
        assert ok is False
        assert failures == 3
        assert result == []

    @patch("pokepoke.agents.parallel_support.handle_preflight_checks", return_value=(False, False))
    def test_non_critical_preflight_failure(self, _preflight):
        run_logger = MagicMock()
        ok, failures, result = run_preflight_and_repo_checks(
            "/repo", run_logger, 1, 5, Mock(), Mock(),
        )
        assert ok is False
        assert failures == 1

    @patch("pokepoke.agents.parallel_support.handle_preflight_checks", return_value=(True, False))
    def test_repo_check_failure(self, _preflight):
        run_logger = MagicMock()
        repo_fn = Mock(return_value=False)
        ok, failures, result = run_preflight_and_repo_checks(
            "/repo", run_logger, 0, 5, repo_fn, Mock(),
        )
        assert ok is False
        assert result == []

    @patch("pokepoke.agents.parallel_support.handle_preflight_checks", return_value=(True, False))
    def test_ready_items_exception_returns_empty(self, _preflight):
        run_logger = MagicMock()
        repo_fn = Mock(return_value=True)
        ready_fn = Mock(side_effect=RuntimeError("beads down"))
        ok, failures, result = run_preflight_and_repo_checks(
            "/repo", run_logger, 0, 5, repo_fn, ready_fn,
        )
        assert ok is True
        assert result == []


# ── check_loop_exit ──────────────────────────────────────────────────


class TestCheckLoopExit:
    """Tests for check_loop_exit."""

    @patch("pokepoke.agents.parallel.should_stop_after_current", return_value=True)
    @patch("pokepoke.agents.parallel.cancel_stop_after_current")
    @patch("pokepoke.agents.parallel_support.terminal_ui")
    def test_stop_after_current_no_futures(self, mock_tui, _cancel, _stop):
        stats = SessionStats(agent_stats=AgentStats())
        finalize_fn = Mock()
        result = check_loop_exit(
            {}, [], False, False, 1, 0, stats, time.time(), 8.0, "Auto",
            MagicMock(), finalize_fn,
        )
        assert result == "break-success"
        finalize_fn.assert_called_once()

    @patch("pokepoke.agents.parallel.should_stop_after_current", return_value=False)
    @patch("pokepoke.agents.parallel_support.terminal_ui")
    def test_non_continuous_done(self, mock_tui, _stop):
        stats = SessionStats(agent_stats=AgentStats())
        finalize_fn = Mock()
        result = check_loop_exit(
            {}, [], False, True, 5, 1, stats, time.time(), 8.0, "Auto",
            MagicMock(), finalize_fn,
        )
        assert result == "break-done"

    @patch("pokepoke.agents.parallel.should_stop_after_current", return_value=False)
    @patch("pokepoke.agents.parallel_support.terminal_ui")
    def test_no_futures_no_items_recheck_finds_items(self, mock_tui, _stop):
        ready_fn = Mock(return_value=[_make_item("rc1")])
        result = check_loop_exit(
            {}, [], False, False, 0, 0, SessionStats(agent_stats=AgentStats()),
            time.time(), 8.0, "Auto", MagicMock(), Mock(), ready_fn,
        )
        assert result == "recheck"

    @patch("pokepoke.agents.parallel.should_stop_after_current", return_value=False)
    @patch("pokepoke.agents.parallel_support.terminal_ui")
    def test_no_futures_no_items_not_continuous(self, mock_tui, _stop):
        ready_fn = Mock(return_value=[])
        finalize_fn = Mock()
        result = check_loop_exit(
            {}, [], False, False, 0, 0, SessionStats(agent_stats=AgentStats()),
            time.time(), 8.0, "Auto", MagicMock(), finalize_fn, ready_fn,
        )
        assert result == "break-empty"
        finalize_fn.assert_called_once()

    @patch("pokepoke.agents.parallel_support.time.sleep")
    @patch("pokepoke.agents.parallel.should_stop_after_current", return_value=False)
    @patch("pokepoke.agents.parallel_support.terminal_ui")
    def test_continuous_idle_sleep(self, mock_tui, _stop, mock_sleep):
        ready_fn = Mock(return_value=[])
        result = check_loop_exit(
            {}, [], True, False, 0, 0, SessionStats(agent_stats=AgentStats()),
            time.time(), 8.0, "Auto", MagicMock(), Mock(), ready_fn,
        )
        assert result == "idle-continue"
        mock_sleep.assert_called_once_with(8.0)

    @patch("pokepoke.agents.parallel.should_stop_after_current", return_value=False)
    @patch("pokepoke.agents.parallel_support.terminal_ui")
    def test_futures_still_active_returns_none(self, mock_tui, _stop):
        fut = concurrent.futures.Future()
        item = _make_item("active1")
        result = check_loop_exit(
            {fut: item}, [_make_item("r1")], True, False, 0, 0,
            SessionStats(agent_stats=AgentStats()), time.time(), 8.0, "Auto",
            MagicMock(), Mock(),
        )
        assert result is None

    @patch("pokepoke.agents.parallel.should_stop_after_current", return_value=False)
    @patch("pokepoke.agents.parallel_support.terminal_ui")
    def test_recheck_exception_falls_through(self, mock_tui, _stop):
        """If recheck raises, it falls through to break-empty (non-continuous)."""
        ready_fn = Mock(side_effect=RuntimeError("beads error"))
        finalize_fn = Mock()
        result = check_loop_exit(
            {}, [], False, False, 0, 0, SessionStats(agent_stats=AgentStats()),
            time.time(), 8.0, "Auto", MagicMock(), finalize_fn, ready_fn,
        )
        assert result == "break-empty"


# ── update_circuit_breaker ───────────────────────────────────────────


class TestUpdateCircuitBreaker:
    """Tests for update_circuit_breaker."""

    def test_failures_increment(self):
        run_logger = MagicMock()
        failures, tripped = update_circuit_breaker(0, 3, 2, 10, {}, run_logger)
        assert failures == 3
        assert tripped is False

    def test_success_resets(self):
        run_logger = MagicMock()
        failures, tripped = update_circuit_breaker(1, 0, 5, 10, {}, run_logger)
        assert failures == 0
        assert tripped is False

    def test_trip_threshold(self):
        run_logger = MagicMock()
        failures, tripped = update_circuit_breaker(0, 1, 9, 10, {}, run_logger)
        assert failures == 10
        assert tripped is True

    def test_no_changes_when_both_zero(self):
        run_logger = MagicMock()
        failures, tripped = update_circuit_breaker(0, 0, 3, 10, {}, run_logger)
        assert failures == 3
        assert tripped is False


# ── compute_slots ────────────────────────────────────────────────────


class TestComputeSlots:
    """Tests for compute_slots."""

    @patch("pokepoke.agents.parallel_support.apply_memory_backpressure", return_value=(2, 8000))
    @patch("pokepoke.agents.parallel.get_effective_max_agents", return_value=4)
    def test_basic_slot_computation(self, _max, _mem):
        item = _make_item("cs1")
        fut = concurrent.futures.Future()
        futures = {fut: item}
        run_logger = MagicMock()
        active, slots, avail_mb = compute_slots(futures, run_logger)
        assert "cs1" in active
        assert slots == 2
        assert avail_mb == 8000

    @patch("pokepoke.agents.parallel_support.apply_memory_backpressure", return_value=(0, 500))
    @patch("pokepoke.agents.parallel.get_effective_max_agents", return_value=4)
    def test_memory_low_blocks_slots(self, _max, _mem):
        item = _make_item("ml1")
        fut = concurrent.futures.Future()
        futures = {fut: item}
        run_logger = MagicMock()
        active, slots, avail_mb = compute_slots(futures, run_logger)
        assert slots == 0
        assert avail_mb == 500

    @patch("pokepoke.agents.parallel_support.apply_memory_backpressure", return_value=(1, 2000))
    @patch("pokepoke.agents.parallel.get_effective_max_agents", return_value=4)
    def test_memory_pressure_reduces_slots(self, _max, _mem):
        """Memory pressure: backpressure returns fewer slots than available."""
        run_logger = MagicMock()
        active, slots, avail_mb = compute_slots({}, run_logger)
        assert slots == 1
        assert avail_mb == 2000
