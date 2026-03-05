"""Tests for parallel_support helper functions."""

import concurrent.futures
import threading
import time
from unittest.mock import MagicMock, Mock, patch


from pokepoke.parallel_support import (
    handle_preflight_checks,
    finalize_workers,
    _drain_orphaned_futures,
    drain_circuit_breaker,
    dispatch_items,
    run_preflight_and_repo_checks,
    check_loop_exit,
    update_circuit_breaker,
    compute_slots,
)
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

    @patch("pokepoke.parallel_support.terminal_ui")
    @patch("pokepoke.parallel_support.kill_orphaned_copilot_processes")
    @patch("pokepoke.parallel_support._drain_orphaned_futures")
    @patch("pokepoke.parallel_support.concurrent.futures.as_completed")
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

    @patch("pokepoke.parallel_support.terminal_ui")
    @patch("pokepoke.parallel.unassign_with_retry")
    def test_empty_futures_noop(self, mock_unassign, mock_tui):
        """Empty futures dict is a no-op."""
        futures: dict = {}
        run_logger = MagicMock()
        _drain_orphaned_futures(futures, SessionStats(agent_stats=AgentStats()), time.time(), run_logger, Mock())
        mock_unassign.assert_not_called()

    @patch("pokepoke.parallel_support.terminal_ui")
    @patch("pokepoke.parallel.unassign_with_retry")
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

    @patch("pokepoke.parallel_support.terminal_ui")
    @patch("pokepoke.parallel.unassign_with_retry")
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

    @patch("pokepoke.parallel_support.terminal_ui")
    @patch("pokepoke.parallel.unassign_with_retry", side_effect=RuntimeError("unassign boom"))
    def test_unassign_exception_handled(self, mock_unassign, mock_tui):
        """unassign_with_retry raising doesn't crash the drain."""
        item = _make_item("u1")
        fut = concurrent.futures.Future()
        futures = {fut: item}
        run_logger = MagicMock()
        record_fn = Mock()

        _drain_orphaned_futures(futures, SessionStats(agent_stats=AgentStats()), time.time(), run_logger, record_fn)

        record_fn.assert_called_once()
        mock_unassign.assert_called_once_with("u1")

    @patch("pokepoke.parallel_support.terminal_ui")
    @patch("pokepoke.parallel.unassign_with_retry")
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

    @patch("pokepoke.parallel_support.time.sleep")
    @patch("pokepoke.parallel_support.is_shutting_down", return_value=False)
    @patch("pokepoke.parallel_support.terminal_ui")
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

    @patch("pokepoke.parallel_support.time.sleep")
    @patch("pokepoke.parallel_support.is_shutting_down", return_value=True)
    @patch("pokepoke.parallel_support.terminal_ui")
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

    @patch("pokepoke.parallel.should_stop_after_current", return_value=False)
    @patch("pokepoke.parallel.select_multiple_items", return_value=[])
    @patch("pokepoke.parallel.is_item_claimable", return_value=True)
    @patch("pokepoke.parallel.assign_and_sync_item", return_value=True)
    @patch("pokepoke.agent_context.get_agent_name", return_value="agent")
    def test_zero_slots_returns_immediately(self, *_mocks):
        run_logger = MagicMock()
        result = dispatch_items(
            [], 0, True, False, 0, 10, set(), set(), {},
            threading.Semaphore(1), MagicMock(), run_logger, 0, Mock(), Mock(),
        )
        assert result == 0

    @patch("pokepoke.parallel.should_stop_after_current", return_value=False)
    @patch("pokepoke.parallel.select_multiple_items")
    @patch("pokepoke.parallel.is_item_claimable", return_value=True)
    @patch("pokepoke.parallel.assign_and_sync_item", return_value=True)
    @patch("pokepoke.agent_context.get_agent_name", return_value="agent")
    def test_submits_item_to_executor(self, _name, _assign, _claim, mock_select, _stop):
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

    @patch("pokepoke.parallel.should_stop_after_current", return_value=False)
    @patch("pokepoke.parallel.select_multiple_items")
    @patch("pokepoke.parallel.is_item_claimable", return_value=False)
    @patch("pokepoke.agent_context.get_agent_name", return_value="agent")
    def test_skips_unclaimed_item(self, _name, _claim, mock_select, _stop):
        item = _make_item("skip1")
        mock_select.return_value = [item]
        run_logger = MagicMock()
        executor = MagicMock()
        futures: dict = {}

        counter = dispatch_items(
            [item], 1, True, False, 0, 10, set(), set(), futures,
            threading.Semaphore(1), executor, run_logger, 0, Mock(), Mock(),
        )
        assert counter == 0
        executor.submit.assert_not_called()

    @patch("pokepoke.parallel.should_stop_after_current", return_value=False)
    @patch("pokepoke.parallel.select_multiple_items")
    @patch("pokepoke.parallel.is_item_claimable", return_value=True)
    @patch("pokepoke.parallel.assign_and_sync_item", return_value=False)
    @patch("pokepoke.agent_context.get_agent_name", return_value="agent")
    def test_failed_assign_adds_to_failed_ids(self, _name, _assign, _claim, mock_select, _stop):
        item = _make_item("fa1")
        mock_select.return_value = [item]
        run_logger = MagicMock()
        failed_ids: set[str] = set()

        dispatch_items(
            [item], 1, True, False, 0, 10, failed_ids, set(), {},
            threading.Semaphore(1), MagicMock(), run_logger, 0, Mock(return_value="w"), Mock(),
        )
        assert "fa1" in failed_ids

    @patch("pokepoke.parallel.should_stop_after_current", return_value=False)
    @patch("pokepoke.parallel.select_multiple_items")
    @patch("pokepoke.parallel.is_item_claimable", return_value=True)
    @patch("pokepoke.parallel.assign_and_sync_item", return_value=True)
    @patch("pokepoke.parallel.unassign_with_retry")
    @patch("pokepoke.agent_context.get_agent_name", return_value="agent")
    def test_executor_submit_failure_unassigns(self, _name, mock_unassign, _assign, _claim, mock_select, _stop):
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


# ── run_preflight_and_repo_checks ────────────────────────────────────


class TestRunPreflightAndRepoChecks:
    """Tests for run_preflight_and_repo_checks."""

    @patch("pokepoke.parallel_support.handle_preflight_checks", return_value=(True, False))
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

    @patch("pokepoke.parallel_support.handle_preflight_checks", return_value=(False, True))
    def test_critical_preflight_failure_increments(self, _preflight):
        run_logger = MagicMock()
        ok, failures, result = run_preflight_and_repo_checks(
            "/repo", run_logger, 2, 5, Mock(), Mock(),
        )
        assert ok is False
        assert failures == 3
        assert result == []

    @patch("pokepoke.parallel_support.handle_preflight_checks", return_value=(False, False))
    def test_non_critical_preflight_failure(self, _preflight):
        run_logger = MagicMock()
        ok, failures, result = run_preflight_and_repo_checks(
            "/repo", run_logger, 1, 5, Mock(), Mock(),
        )
        assert ok is False
        assert failures == 1

    @patch("pokepoke.parallel_support.handle_preflight_checks", return_value=(True, False))
    def test_repo_check_failure(self, _preflight):
        run_logger = MagicMock()
        repo_fn = Mock(return_value=False)
        ok, failures, result = run_preflight_and_repo_checks(
            "/repo", run_logger, 0, 5, repo_fn, Mock(),
        )
        assert ok is False
        assert result == []

    @patch("pokepoke.parallel_support.handle_preflight_checks", return_value=(True, False))
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

    @patch("pokepoke.parallel.should_stop_after_current", return_value=True)
    @patch("pokepoke.parallel.cancel_stop_after_current")
    @patch("pokepoke.parallel_support.terminal_ui")
    def test_stop_after_current_no_futures(self, mock_tui, _cancel, _stop):
        stats = SessionStats(agent_stats=AgentStats())
        finalize_fn = Mock()
        result = check_loop_exit(
            {}, [], False, False, 1, 0, stats, time.time(), 8.0, "Auto",
            MagicMock(), finalize_fn,
        )
        assert result == "break-success"
        finalize_fn.assert_called_once()

    @patch("pokepoke.parallel.should_stop_after_current", return_value=False)
    @patch("pokepoke.parallel_support.terminal_ui")
    def test_non_continuous_done(self, mock_tui, _stop):
        stats = SessionStats(agent_stats=AgentStats())
        finalize_fn = Mock()
        result = check_loop_exit(
            {}, [], False, True, 5, 1, stats, time.time(), 8.0, "Auto",
            MagicMock(), finalize_fn,
        )
        assert result == "break-done"

    @patch("pokepoke.parallel.should_stop_after_current", return_value=False)
    @patch("pokepoke.parallel_support.terminal_ui")
    def test_no_futures_no_items_recheck_finds_items(self, mock_tui, _stop):
        ready_fn = Mock(return_value=[_make_item("rc1")])
        result = check_loop_exit(
            {}, [], False, False, 0, 0, SessionStats(agent_stats=AgentStats()),
            time.time(), 8.0, "Auto", MagicMock(), Mock(), ready_fn,
        )
        assert result == "recheck"

    @patch("pokepoke.parallel.should_stop_after_current", return_value=False)
    @patch("pokepoke.parallel_support.terminal_ui")
    def test_no_futures_no_items_not_continuous(self, mock_tui, _stop):
        ready_fn = Mock(return_value=[])
        finalize_fn = Mock()
        result = check_loop_exit(
            {}, [], False, False, 0, 0, SessionStats(agent_stats=AgentStats()),
            time.time(), 8.0, "Auto", MagicMock(), finalize_fn, ready_fn,
        )
        assert result == "break-empty"
        finalize_fn.assert_called_once()

    @patch("pokepoke.parallel_support.time.sleep")
    @patch("pokepoke.parallel.should_stop_after_current", return_value=False)
    @patch("pokepoke.parallel_support.terminal_ui")
    def test_continuous_idle_sleep(self, mock_tui, _stop, mock_sleep):
        ready_fn = Mock(return_value=[])
        result = check_loop_exit(
            {}, [], True, False, 0, 0, SessionStats(agent_stats=AgentStats()),
            time.time(), 8.0, "Auto", MagicMock(), Mock(), ready_fn,
        )
        assert result == "idle-continue"
        mock_sleep.assert_called_once_with(8.0)

    @patch("pokepoke.parallel.should_stop_after_current", return_value=False)
    @patch("pokepoke.parallel_support.terminal_ui")
    def test_futures_still_active_returns_none(self, mock_tui, _stop):
        fut = concurrent.futures.Future()
        item = _make_item("active1")
        result = check_loop_exit(
            {fut: item}, [_make_item("r1")], True, False, 0, 0,
            SessionStats(agent_stats=AgentStats()), time.time(), 8.0, "Auto",
            MagicMock(), Mock(),
        )
        assert result is None

    @patch("pokepoke.parallel.should_stop_after_current", return_value=False)
    @patch("pokepoke.parallel_support.terminal_ui")
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

    @patch("pokepoke.parallel_support.apply_memory_backpressure", return_value=(2, 8000))
    @patch("pokepoke.parallel.get_effective_max_agents", return_value=4)
    def test_basic_slot_computation(self, _max, _mem):
        item = _make_item("cs1")
        fut = concurrent.futures.Future()
        futures = {fut: item}
        run_logger = MagicMock()
        active, slots, avail_mb = compute_slots(futures, run_logger)
        assert "cs1" in active
        assert slots == 2
        assert avail_mb == 8000

    @patch("pokepoke.parallel_support.apply_memory_backpressure", return_value=(0, 500))
    @patch("pokepoke.parallel.get_effective_max_agents", return_value=4)
    def test_memory_low_blocks_slots(self, _max, _mem):
        item = _make_item("ml1")
        fut = concurrent.futures.Future()
        futures = {fut: item}
        run_logger = MagicMock()
        active, slots, avail_mb = compute_slots(futures, run_logger)
        assert slots == 0
        assert avail_mb == 500

    @patch("pokepoke.parallel_support.apply_memory_backpressure", return_value=(1, 2000))
    @patch("pokepoke.parallel.get_effective_max_agents", return_value=4)
    def test_memory_pressure_reduces_slots(self, _max, _mem):
        """Memory pressure: backpressure returns fewer slots than available."""
        run_logger = MagicMock()
        active, slots, avail_mb = compute_slots({}, run_logger)
        assert slots == 1
        assert avail_mb == 2000
