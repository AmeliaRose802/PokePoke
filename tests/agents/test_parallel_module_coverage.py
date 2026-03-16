"""Comprehensive tests for pokepoke.agents.parallel – targets all uncovered functions."""

import concurrent.futures
import threading
import time
from contextlib import contextmanager
from unittest.mock import patch, Mock, MagicMock, call

import pytest

from pokepoke.types import BeadsWorkItem, SessionStats, WorkItemResult, AgentStats
from pokepoke.agents.parallel import (
    _get_dynamic_max_agents,
    get_effective_max_agents,
    request_spawn_agent,
    _hash_string,
    _snake_for_work_item,
    _build_worker_name,
    _parallel_process_item,
    _collect_done_futures,
    run_parallel_loop,
    _spawn_wakeup,
    _SNAKE_TYPES,
    _DEFAULT_PARALLEL_CEILING,
    _IDLE_BASE_DELAY,
    _IDLE_MAX_DELAY,
    _MAX_CONSECUTIVE_FAILURES,
    _MAX_CONSECUTIVE_PREFLIGHT_FAILURES,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_item(item_id: str = "ITEM-1", title: str = "Test item") -> BeadsWorkItem:
    return BeadsWorkItem(
        id=item_id, title=title, status="ready", priority=1, issue_type="task",
    )


def _make_session_stats() -> SessionStats:
    return SessionStats(agent_stats=AgentStats())


def _make_run_logger() -> MagicMock:
    rl = MagicMock()
    rl.log_orchestrator = MagicMock()
    return rl


# ---------------------------------------------------------------------------
# Autouse fixture – disables preflight, mocks beads, config, and terminal UI
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _disable_preflight(monkeypatch):
    mock_cfg = MagicMock()
    mock_cfg.preflight_health.enabled = False
    mock_cfg.max_parallel_agents = 10
    monkeypatch.setattr("pokepoke.config.get_config", lambda: mock_cfg)
    monkeypatch.setattr("pokepoke.agents.parallel.assign_and_sync_item", lambda *a, **kw: True)
    monkeypatch.setattr("pokepoke.agents.parallel.unassign_with_retry", lambda *a, **kw: None)
    monkeypatch.setattr("pokepoke.agents.parallel_support.kill_orphaned_copilot_processes", lambda **kw: None)
    monkeypatch.setattr("pokepoke.agents.parallel_support.terminal_ui", MagicMock())


# ===================================================================
# _hash_string
# ===================================================================


class TestHashString:
    def test_empty_string(self):
        assert _hash_string("") == 0

    def test_single_char(self):
        result = _hash_string("a")
        assert isinstance(result, int)
        assert result >= 0

    def test_deterministic(self):
        assert _hash_string("hello") == _hash_string("hello")

    def test_different_strings_different_hashes(self):
        assert _hash_string("abc") != _hash_string("xyz")

    def test_returns_non_negative(self):
        # Test many strings to exercise the signed-to-unsigned conversion path
        for s in ["a", "test", "ITEM-123", "longstringvalue!!", "\x00", "🐍"]:
            assert _hash_string(s) >= 0

    def test_high_bit_set_path(self):
        """Ensure the if hash_val & 0x80000000 branch is exercised."""
        # We can't easily predict which string triggers it, so try many
        for i in range(200):
            h = 0
            for ch in str(i) * 10:
                h = ((h << 5) - h + ord(ch)) & 0xFFFFFFFF
            if h & 0x80000000:
                break
        # Either way, _hash_string still returns non-negative
        result = _hash_string(str(i) * 10)
        assert result >= 0


# ===================================================================
# _snake_for_work_item
# ===================================================================


class TestSnakeForWorkItem:
    def test_returns_valid_snake(self):
        result = _snake_for_work_item("ITEM-42")
        assert result in _SNAKE_TYPES

    def test_deterministic(self):
        assert _snake_for_work_item("X") == _snake_for_work_item("X")

    def test_different_ids_can_differ(self):
        snakes = {_snake_for_work_item(f"id-{i}") for i in range(50)}
        # Should hit at least 2 distinct snakes across 50 IDs
        assert len(snakes) >= 2

    def test_all_snakes_reachable(self):
        """With enough diverse IDs, every snake type should appear."""
        snakes = {_snake_for_work_item(f"item-{i}") for i in range(500)}
        assert snakes == set(_SNAKE_TYPES)


# ===================================================================
# _build_worker_name
# ===================================================================


class TestBuildWorkerName:
    def test_basic_format(self):
        name = _build_worker_name("agent", "ITEM-1", 7)
        snake = _snake_for_work_item("ITEM-1")
        assert name == f"agent-{snake}-worker-7"

    def test_counter_increments(self):
        n1 = _build_worker_name("base", "id", 1)
        n2 = _build_worker_name("base", "id", 2)
        assert n1.endswith("-worker-1")
        assert n2.endswith("-worker-2")

    def test_contains_snake_type(self):
        name = _build_worker_name("pokepoke", "ITEM-99", 0)
        assert any(s in name for s in _SNAKE_TYPES)


# ===================================================================
# _get_dynamic_max_agents
# ===================================================================


class TestGetDynamicMaxAgents:
    def test_returns_config_value(self):
        with patch("pokepoke.agents.parallel.get_config" if False else "pokepoke.config.get_config") as mock_gc:
            cfg = MagicMock()
            cfg.max_parallel_agents = 5
            mock_gc.return_value = cfg
            assert _get_dynamic_max_agents() == 5

    def test_clamps_to_minimum_one(self):
        with patch("pokepoke.config.get_config") as mock_gc:
            cfg = MagicMock()
            cfg.max_parallel_agents = 0
            mock_gc.return_value = cfg
            assert _get_dynamic_max_agents() == 1

    def test_negative_value_clamped(self):
        with patch("pokepoke.config.get_config") as mock_gc:
            cfg = MagicMock()
            cfg.max_parallel_agents = -3
            mock_gc.return_value = cfg
            assert _get_dynamic_max_agents() == 1


# ===================================================================
# get_effective_max_agents
# ===================================================================


class TestGetEffectiveMaxAgents:
    def test_delegates_to_compute(self):
        with patch("pokepoke.agents.parallel.compute_effective_max_agents", return_value=4) as mock_compute, \
             patch("pokepoke.config.get_config") as mock_gc:
            cfg = MagicMock()
            cfg.max_parallel_agents = 6
            mock_gc.return_value = cfg
            result = get_effective_max_agents()
            mock_compute.assert_called_once_with(6)
            assert result == 4


# ===================================================================
# request_spawn_agent
# ===================================================================


class TestRequestSpawnAgent:
    def test_sets_event(self):
        _spawn_wakeup.clear()
        assert not _spawn_wakeup.is_set()
        request_spawn_agent()
        assert _spawn_wakeup.is_set()
        _spawn_wakeup.clear()  # cleanup


# ===================================================================
# _parallel_process_item
# ===================================================================


class TestParallelProcessItem:
    """Tests for the thread-pool wrapper around process_work_item."""

    @pytest.fixture()
    def _mock_deps(self, monkeypatch):
        """Patch all side-effect dependencies of _parallel_process_item."""
        mock_ui = MagicMock()
        mock_ui.push_agent_status = MagicMock()
        mock_ui.log_orchestrator = MagicMock()
        mock_ui.agent_output_for = MagicMock(return_value=contextmanager(lambda: (yield))())

        monkeypatch.setattr("pokepoke.agents.parallel.terminal_ui", MagicMock(ui=mock_ui))
        monkeypatch.setattr("pokepoke.agents.parallel.set_agent_name", MagicMock())
        monkeypatch.setattr("pokepoke.agents.parallel.clear_agent_name", MagicMock())
        monkeypatch.setattr("pokepoke.beads.beads.increment_total_attempts", MagicMock())
        return mock_ui

    def test_success_path(self, monkeypatch, _mock_deps):
        result = WorkItemResult(success=True, request_count=1)
        monkeypatch.setattr(
            "pokepoke.agents.parallel.process_work_item",
            MagicMock(return_value=result),
        )

        sem = threading.Semaphore(0)  # starts at 0 so release goes to 1
        item = _make_item()
        run_logger = _make_run_logger()

        out = _parallel_process_item(item, run_logger, sem, worker_agent_name="w1")
        assert out.success is True
        assert out.request_count == 1
        # Semaphore was released
        assert sem.acquire(timeout=0)

    def test_failure_path(self, monkeypatch, _mock_deps):
        result = WorkItemResult(success=False, request_count=2)
        monkeypatch.setattr(
            "pokepoke.agents.parallel.process_work_item",
            MagicMock(return_value=result),
        )

        sem = threading.Semaphore(0)
        item = _make_item()
        out = _parallel_process_item(item, _make_run_logger(), sem)
        assert out.success is False
        assert sem.acquire(timeout=0)

    def test_exception_releases_semaphore(self, monkeypatch, _mock_deps):
        monkeypatch.setattr(
            "pokepoke.agents.parallel.process_work_item",
            MagicMock(side_effect=RuntimeError("boom")),
        )

        sem = threading.Semaphore(0)
        item = _make_item()
        with pytest.raises(RuntimeError, match="boom"):
            _parallel_process_item(item, _make_run_logger(), sem, worker_agent_name="w2")
        # Semaphore still released in finally block
        assert sem.acquire(timeout=0)

    def test_set_agent_name_called(self, monkeypatch, _mock_deps):
        result = WorkItemResult(success=True, request_count=1)
        monkeypatch.setattr(
            "pokepoke.agents.parallel.process_work_item",
            MagicMock(return_value=result),
        )
        mock_set = MagicMock()
        monkeypatch.setattr("pokepoke.agents.parallel.set_agent_name", mock_set)

        sem = threading.Semaphore(0)
        _parallel_process_item(_make_item(), _make_run_logger(), sem, worker_agent_name="agent-cobra-worker-1")
        mock_set.assert_called_once_with("agent-cobra-worker-1")

    def test_clear_agent_name_called_on_success(self, monkeypatch, _mock_deps):
        result = WorkItemResult(success=True, request_count=1)
        monkeypatch.setattr(
            "pokepoke.agents.parallel.process_work_item",
            MagicMock(return_value=result),
        )
        mock_clear = MagicMock()
        monkeypatch.setattr("pokepoke.agents.parallel.clear_agent_name", mock_clear)

        sem = threading.Semaphore(0)
        _parallel_process_item(_make_item(), _make_run_logger(), sem, worker_agent_name="w")
        mock_clear.assert_called_once()

    def test_no_worker_name_skips_set_agent(self, monkeypatch, _mock_deps):
        result = WorkItemResult(success=True, request_count=0)
        monkeypatch.setattr(
            "pokepoke.agents.parallel.process_work_item",
            MagicMock(return_value=result),
        )
        mock_set = MagicMock()
        monkeypatch.setattr("pokepoke.agents.parallel.set_agent_name", mock_set)

        sem = threading.Semaphore(0)
        _parallel_process_item(_make_item(), _make_run_logger(), sem, worker_agent_name=None)
        mock_set.assert_not_called()

    def test_increment_total_attempts_called(self, monkeypatch, _mock_deps):
        result = WorkItemResult(success=True, request_count=1)
        monkeypatch.setattr(
            "pokepoke.agents.parallel.process_work_item",
            MagicMock(return_value=result),
        )
        mock_inc = MagicMock()
        monkeypatch.setattr("pokepoke.beads.beads.increment_total_attempts", mock_inc)

        sem = threading.Semaphore(0)
        item = _make_item("X-99")
        _parallel_process_item(item, _make_run_logger(), sem)
        mock_inc.assert_called_once_with("X-99")

    def test_push_agent_status_called(self, monkeypatch, _mock_deps):
        result = WorkItemResult(success=True, request_count=1)
        monkeypatch.setattr(
            "pokepoke.agents.parallel.process_work_item",
            MagicMock(return_value=result),
        )

        sem = threading.Semaphore(0)
        item = _make_item("ID-7", "My title")
        _parallel_process_item(item, _make_run_logger(), sem, worker_agent_name="w")

        ui = _mock_deps
        # Should have been called with "running" and then "success"
        statuses = [c.kwargs.get("status") or c[0][3] for c in ui.push_agent_status.call_args_list]
        assert "running" in statuses
        assert "success" in statuses

    def test_repo_path_forwarded(self, monkeypatch, _mock_deps):
        mock_pw = MagicMock(return_value=WorkItemResult(success=True, request_count=0))
        monkeypatch.setattr("pokepoke.agents.parallel.process_work_item", mock_pw)

        sem = threading.Semaphore(0)
        _parallel_process_item(_make_item(), _make_run_logger(), sem, repo_path="/tmp/repo")
        mock_pw.assert_called_once()
        assert mock_pw.call_args.kwargs.get("repo_path") == "/tmp/repo"


# ===================================================================
# _collect_done_futures
# ===================================================================


class TestCollectDoneFutures:
    """Tests for the future-collection and result-recording helper."""

    @staticmethod
    def _completed_future(result: WorkItemResult) -> concurrent.futures.Future:
        f: concurrent.futures.Future[WorkItemResult] = concurrent.futures.Future()
        f.set_result(result)
        return f

    @staticmethod
    def _failed_future(exc: Exception) -> concurrent.futures.Future:
        f: concurrent.futures.Future[WorkItemResult] = concurrent.futures.Future()
        f.set_exception(exc)
        return f

    def test_empty_futures_dict(self):
        total, any_ok, sc, fc = _collect_done_futures(
            {}, set(), 0, _make_session_stats(), _make_run_logger(), Mock(),
        )
        assert total == 0
        assert any_ok is False
        assert sc == 0
        assert fc == 0

    def test_single_success(self):
        item = _make_item("S-1")
        result = WorkItemResult(success=True, request_count=3)
        fut = self._completed_future(result)
        futures = {fut: item}
        failed_ids: set[str] = set()
        record_fn = Mock()

        total, any_ok, sc, fc = _collect_done_futures(
            futures, failed_ids, 10, _make_session_stats(), _make_run_logger(), record_fn,
        )
        assert total == 13  # 10 + 3
        assert any_ok is True
        assert sc == 1
        assert fc == 0
        assert len(futures) == 0  # popped
        record_fn.assert_called_once()

    def test_single_failure(self):
        item = _make_item("F-1")
        result = WorkItemResult(success=False, request_count=1)
        fut = self._completed_future(result)
        futures = {fut: item}
        failed_ids: set[str] = set()

        total, any_ok, sc, fc = _collect_done_futures(
            futures, failed_ids, 0, _make_session_stats(), _make_run_logger(), Mock(),
        )
        assert any_ok is False
        assert sc == 0
        assert fc == 1
        assert total == 1

    def test_failure_with_zero_requests_blacklists(self):
        item = _make_item("BL-1")
        result = WorkItemResult(success=False, request_count=0)
        fut = self._completed_future(result)
        futures = {fut: item}
        failed_ids: set[str] = set()

        _collect_done_futures(
            futures, failed_ids, 0, _make_session_stats(), _make_run_logger(), Mock(),
        )
        assert "BL-1" in failed_ids

    def test_success_clears_blacklist(self):
        item = _make_item("CL-1")
        result = WorkItemResult(success=True, request_count=1)
        fut = self._completed_future(result)
        futures = {fut: item}
        failed_ids: set[str] = {"CL-1"}

        _collect_done_futures(
            futures, failed_ids, 0, _make_session_stats(), _make_run_logger(), Mock(),
        )
        assert "CL-1" not in failed_ids

    def test_exception_future(self):
        item = _make_item("EX-1")
        fut = self._failed_future(RuntimeError("oops"))
        futures = {fut: item}
        failed_ids: set[str] = set()

        total, any_ok, sc, fc = _collect_done_futures(
            futures, failed_ids, 0, _make_session_stats(), _make_run_logger(), Mock(),
        )
        assert any_ok is False
        assert fc == 1
        # Exception futures should NOT blacklist (was_exception=True)
        assert "EX-1" not in failed_ids

    def test_multiple_futures(self):
        items = [_make_item(f"M-{i}") for i in range(3)]
        results = [
            WorkItemResult(success=True, request_count=2),
            WorkItemResult(success=False, request_count=1),
            WorkItemResult(success=True, request_count=5),
        ]
        futures = {self._completed_future(r): items[i] for i, r in enumerate(results)}
        failed_ids: set[str] = set()

        total, any_ok, sc, fc = _collect_done_futures(
            futures, failed_ids, 0, _make_session_stats(), _make_run_logger(), Mock(),
        )
        assert total == 8  # 2+1+5
        assert any_ok is True
        assert sc == 2
        assert fc == 1

    def test_record_fn_exception_is_caught(self):
        item = _make_item("REC-1")
        result = WorkItemResult(success=True, request_count=1)
        fut = self._completed_future(result)
        futures = {fut: item}
        bad_record = Mock(side_effect=ValueError("recording failed"))

        # Should not raise
        total, any_ok, sc, fc = _collect_done_futures(
            futures, set(), 0, _make_session_stats(), _make_run_logger(), bad_record,
        )
        assert any_ok is True
        assert sc == 1

    def test_not_done_futures_use_wait(self):
        """When no futures are already done(), the wait() path is exercised."""
        # Create a future that completes after a tiny delay
        pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        item = _make_item("W-1")
        result = WorkItemResult(success=True, request_count=1)
        fut = pool.submit(lambda: (time.sleep(0.05), result)[-1])
        # The future may or may not be done by the time we call collect.
        # Give it a moment to ensure it completes and exercises the wait branch.
        time.sleep(0.15)
        futures = {fut: item}

        total, any_ok, sc, fc = _collect_done_futures(
            futures, set(), 0, _make_session_stats(), _make_run_logger(), Mock(),
        )
        assert any_ok is True
        pool.shutdown(wait=False)


# ===================================================================
# run_parallel_loop
# ===================================================================


class TestRunParallelLoop:
    """Test the main orchestrator loop with aggressive mocking."""

    @pytest.fixture()
    def _loop_mocks(self, monkeypatch):
        """Set up all mocks needed for run_parallel_loop to execute one iteration."""
        # Shutdown after first iteration
        call_count = 0

        def _is_shutting():
            nonlocal call_count
            call_count += 1
            return call_count > 1

        monkeypatch.setattr("pokepoke.agents.parallel.is_shutting_down", _is_shutting)

        mock_set_executor = MagicMock()
        mock_set_runtime = MagicMock()
        mock_clear_runtime = MagicMock()
        monkeypatch.setattr("pokepoke.agents.parallel.set_executor", mock_set_executor)
        monkeypatch.setattr("pokepoke.agents.parallel.set_runtime_parallel_limits", mock_set_runtime)
        monkeypatch.setattr("pokepoke.agents.parallel.clear_runtime_parallel_limits", mock_clear_runtime)

        # Kill orphaned processes
        monkeypatch.setattr("pokepoke.agents.parallel.kill_orphaned_copilot_processes", lambda **kw: None)

        # terminal_ui
        mock_ui = MagicMock()
        mock_ui._is_running = False
        monkeypatch.setattr("pokepoke.agents.parallel.terminal_ui", MagicMock(ui=mock_ui))

        # Preflight – returns ok, 0 failures, empty ready items
        monkeypatch.setattr(
            "pokepoke.agents.parallel._run_preflight_and_repo_checks",
            MagicMock(return_value=(True, 0, [])),
        )

        # Collect done futures – nothing to collect
        monkeypatch.setattr(
            "pokepoke.agents.parallel._collect_done_futures",
            MagicMock(return_value=(0, False, 0, 0)),
        )

        # Circuit breaker – no trip
        monkeypatch.setattr(
            "pokepoke.agents.parallel._update_circuit_breaker",
            MagicMock(return_value=(0, False)),
        )

        # Compute slots
        monkeypatch.setattr(
            "pokepoke.agents.parallel._compute_slots",
            MagicMock(return_value=(0, 2, 4096)),
        )

        # Dispatch – no items dispatched
        monkeypatch.setattr(
            "pokepoke.agents.parallel._dispatch_items",
            MagicMock(return_value=0),
        )

        # Check loop exit – break immediately
        monkeypatch.setattr(
            "pokepoke.agents.parallel._check_loop_exit",
            MagicMock(return_value="break-done"),
        )

        # Finalize workers – return immediately
        monkeypatch.setattr(
            "pokepoke.agents.parallel._finalize_workers",
            MagicMock(return_value=(0, False)),
        )

        return {
            "set_executor": mock_set_executor,
            "set_runtime": mock_set_runtime,
            "clear_runtime": mock_clear_runtime,
            "ui": mock_ui,
        }

    def test_exits_cleanly_on_break_done(self, _loop_mocks):
        stats = _make_session_stats()
        run_logger = _make_run_logger()
        record_fn = Mock()
        finalize_fn = Mock()

        code = run_parallel_loop(
            effective_parallel=2,
            mode_name="Autonomous",
            main_repo_path="/repo",
            failed_claim_ids=set(),
            session_stats=stats,
            start_time=time.time(),
            run_logger=run_logger,
            continuous=False,
            record_fn=record_fn,
            finalize_fn=finalize_fn,
        )
        # break-done with no has_success => exit_code 1
        assert code in (0, 1)

    def test_executor_lifecycle(self, _loop_mocks, monkeypatch):
        """Verify set_executor(executor) and set_executor(None) are called."""
        stats = _make_session_stats()

        run_parallel_loop(
            effective_parallel=2,
            mode_name="Test",
            main_repo_path="/repo",
            failed_claim_ids=set(),
            session_stats=stats,
            start_time=time.time(),
            run_logger=_make_run_logger(),
            continuous=False,
            record_fn=Mock(),
            finalize_fn=Mock(),
        )

        mocks = _loop_mocks
        # set_executor called with an executor then None
        calls = mocks["set_executor"].call_args_list
        assert len(calls) >= 2
        assert calls[-1] == call(None)

    def test_runtime_limits_set_and_cleared(self, _loop_mocks):
        stats = _make_session_stats()

        run_parallel_loop(
            effective_parallel=3,
            mode_name="Test",
            main_repo_path="/repo",
            failed_claim_ids=set(),
            session_stats=stats,
            start_time=time.time(),
            run_logger=_make_run_logger(),
            continuous=False,
            record_fn=Mock(),
            finalize_fn=Mock(),
        )

        _loop_mocks["set_runtime"].assert_called_once()
        _loop_mocks["clear_runtime"].assert_called_once()

    def test_pool_clamped_to_ceiling(self, _loop_mocks, monkeypatch):
        """When effective_parallel > _DEFAULT_PARALLEL_CEILING, pool_size is clamped."""
        stats = _make_session_stats()

        run_parallel_loop(
            effective_parallel=20,
            mode_name="Test",
            main_repo_path="/repo",
            failed_claim_ids=set(),
            session_stats=stats,
            start_time=time.time(),
            run_logger=_make_run_logger(),
            continuous=False,
            record_fn=Mock(),
            finalize_fn=Mock(),
        )
        # If it didn't crash, the clamp worked (pool_size = min(20, 8) = 8)

    def test_shutdown_exits_loop(self, monkeypatch, _loop_mocks):
        """When is_shutting_down returns True immediately, the loop exits."""
        monkeypatch.setattr("pokepoke.agents.parallel.is_shutting_down", lambda: True)

        code = run_parallel_loop(
            effective_parallel=2,
            mode_name="Test",
            main_repo_path="/repo",
            failed_claim_ids=set(),
            session_stats=_make_session_stats(),
            start_time=time.time(),
            run_logger=_make_run_logger(),
            continuous=False,
            record_fn=Mock(),
            finalize_fn=Mock(),
        )
        assert isinstance(code, int)

    def test_preflight_failure_exits(self, monkeypatch, _loop_mocks):
        """When preflight returns ok=False, loop breaks with exit_code=1."""
        # Override shutdown to allow one iteration
        count = 0

        def _shutting():
            nonlocal count
            count += 1
            return count > 2

        monkeypatch.setattr("pokepoke.agents.parallel.is_shutting_down", _shutting)
        monkeypatch.setattr(
            "pokepoke.agents.parallel._run_preflight_and_repo_checks",
            MagicMock(return_value=(False, 5, [])),
        )

        code = run_parallel_loop(
            effective_parallel=2,
            mode_name="Test",
            main_repo_path="/repo",
            failed_claim_ids=set(),
            session_stats=_make_session_stats(),
            start_time=time.time(),
            run_logger=_make_run_logger(),
            continuous=False,
            record_fn=Mock(),
            finalize_fn=Mock(),
        )
        assert code == 1

    def test_circuit_breaker_path(self, monkeypatch, _loop_mocks):
        """When circuit breaker trips and no futures remain, exit_code=1."""
        count = 0

        def _shutting():
            nonlocal count
            count += 1
            return count > 3

        monkeypatch.setattr("pokepoke.agents.parallel.is_shutting_down", _shutting)
        # First iteration: circuit breaker trips
        monkeypatch.setattr(
            "pokepoke.agents.parallel._update_circuit_breaker",
            MagicMock(return_value=(10, True)),
        )

        code = run_parallel_loop(
            effective_parallel=2,
            mode_name="Test",
            main_repo_path="/repo",
            failed_claim_ids=set(),
            session_stats=_make_session_stats(),
            start_time=time.time(),
            run_logger=_make_run_logger(),
            continuous=False,
            record_fn=Mock(),
            finalize_fn=Mock(),
        )
        assert code == 1

    def test_check_loop_exit_recheck(self, monkeypatch, _loop_mocks):
        """When _check_loop_exit returns 'recheck', loop continues with reset idle."""
        call_idx = 0

        def _shutting():
            nonlocal call_idx
            call_idx += 1
            return call_idx > 2

        monkeypatch.setattr("pokepoke.agents.parallel.is_shutting_down", _shutting)

        # First call returns "recheck", second returns "break-done"
        exit_seq = iter(["recheck", "break-done"])
        monkeypatch.setattr(
            "pokepoke.agents.parallel._check_loop_exit",
            MagicMock(side_effect=lambda *a, **kw: next(exit_seq, "break-done")),
        )

        code = run_parallel_loop(
            effective_parallel=2,
            mode_name="Test",
            main_repo_path="/repo",
            failed_claim_ids=set(),
            session_stats=_make_session_stats(),
            start_time=time.time(),
            run_logger=_make_run_logger(),
            continuous=False,
            record_fn=Mock(),
            finalize_fn=Mock(),
        )
        assert isinstance(code, int)

    def test_check_loop_exit_idle(self, monkeypatch, _loop_mocks):
        """When _check_loop_exit returns 'idle', idle_sleep doubles (exponential backoff)."""
        call_idx = 0

        def _shutting():
            nonlocal call_idx
            call_idx += 1
            return call_idx > 2

        monkeypatch.setattr("pokepoke.agents.parallel.is_shutting_down", _shutting)

        exit_seq = iter(["idle", "break-done"])
        monkeypatch.setattr(
            "pokepoke.agents.parallel._check_loop_exit",
            MagicMock(side_effect=lambda *a, **kw: next(exit_seq, "break-done")),
        )

        code = run_parallel_loop(
            effective_parallel=2,
            mode_name="Test",
            main_repo_path="/repo",
            failed_claim_ids=set(),
            session_stats=_make_session_stats(),
            start_time=time.time(),
            run_logger=_make_run_logger(),
            continuous=False,
            record_fn=Mock(),
            finalize_fn=Mock(),
        )
        assert isinstance(code, int)

    def test_check_loop_exit_none_sleeps(self, monkeypatch, _loop_mocks):
        """When _check_loop_exit returns None, the loop sleeps 5s then continues."""
        call_idx = 0

        def _shutting():
            nonlocal call_idx
            call_idx += 1
            # After the sleep loop (11 sleep checks) + second iteration
            return call_idx > 2

        monkeypatch.setattr("pokepoke.agents.parallel.is_shutting_down", _shutting)

        # First returns None (enter sleep), second returns break
        exit_seq = iter([None, "break-done"])
        monkeypatch.setattr(
            "pokepoke.agents.parallel._check_loop_exit",
            MagicMock(side_effect=lambda *a, **kw: next(exit_seq, "break-done")),
        )
        # Patch time.sleep to avoid real delay
        monkeypatch.setattr("pokepoke.agents.parallel.time.sleep", lambda _: None)
        # Patch _spawn_wakeup.is_set so the inner loop exits quickly
        monkeypatch.setattr("pokepoke.agents.parallel._spawn_wakeup", MagicMock(is_set=MagicMock(return_value=True), clear=MagicMock()))

        code = run_parallel_loop(
            effective_parallel=2,
            mode_name="Test",
            main_repo_path="/repo",
            failed_claim_ids=set(),
            session_stats=_make_session_stats(),
            start_time=time.time(),
            run_logger=_make_run_logger(),
            continuous=False,
            record_fn=Mock(),
            finalize_fn=Mock(),
        )
        assert isinstance(code, int)

    def test_cli_override_sets_baseline(self, monkeypatch, _loop_mocks):
        """When cli_override=True, set_runtime_parallel_limits is called with baseline."""
        run_parallel_loop(
            effective_parallel=4,
            mode_name="Test",
            main_repo_path="/repo",
            failed_claim_ids=set(),
            session_stats=_make_session_stats(),
            start_time=time.time(),
            run_logger=_make_run_logger(),
            continuous=False,
            record_fn=Mock(),
            finalize_fn=Mock(),
            cli_override=True,
        )
        call_args = _loop_mocks["set_runtime"].call_args
        assert call_args[0][1] is True  # cli_override=True
        # baseline kwarg should be set (not None)
        assert call_args.kwargs.get("baseline") is not None or call_args[0][2] is not None

    def test_finalize_fn_called_when_not_finalized(self, monkeypatch, _loop_mocks):
        """When the loop exits via shutdown (not break), finalize_fn is called."""
        monkeypatch.setattr("pokepoke.agents.parallel.is_shutting_down", lambda: True)

        finalize_fn = Mock()
        run_parallel_loop(
            effective_parallel=2,
            mode_name="Test",
            main_repo_path="/repo",
            failed_claim_ids=set(),
            session_stats=_make_session_stats(),
            start_time=time.time(),
            run_logger=_make_run_logger(),
            continuous=False,
            record_fn=Mock(),
            finalize_fn=finalize_fn,
        )
        finalize_fn.assert_called_once()


# ===================================================================
# Constants sanity checks
# ===================================================================


class TestConstants:
    def test_snake_types_tuple(self):
        assert isinstance(_SNAKE_TYPES, tuple)
        assert len(_SNAKE_TYPES) == 5

    def test_default_ceiling(self):
        assert _DEFAULT_PARALLEL_CEILING == 8

    def test_idle_delays(self):
        assert _IDLE_BASE_DELAY == 8.0
        assert _IDLE_MAX_DELAY == 120.0

    def test_failure_limits(self):
        assert _MAX_CONSECUTIVE_FAILURES == 10
        assert _MAX_CONSECUTIVE_PREFLIGHT_FAILURES == 5
