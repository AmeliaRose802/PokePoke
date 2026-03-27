"""Integration-style tests for parallel.py.

Exercises real code paths in parallel.py, mocking only external I/O
(process_work_item, beads CLI, shutdown, terminal_ui).
"""

import concurrent.futures
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from pokepoke.agents.parallel import (
    _SNAKE_TYPES,
    _build_worker_name,
    _collect_done_futures,
    _finalize_workers,
    _hash_string,
    _parallel_process_item,
    _snake_for_work_item,
    request_spawn_agent,
    run_parallel_loop,
)
from pokepoke.types import AgentStats, BeadsWorkItem, SessionStats, WorkItemResult


@pytest.fixture(autouse=True)
def _disable_preflight_health(monkeypatch):
    """Disable preflight health checks and mock beads operations."""
    mock_cfg = MagicMock()
    mock_cfg.preflight_health.enabled = False
    mock_cfg.max_parallel_agents = 10
    monkeypatch.setattr("pokepoke.config.get_config", lambda: mock_cfg)
    monkeypatch.setattr("pokepoke.agents.parallel.assign_and_sync_item", lambda *a, **kw: True)
    monkeypatch.setattr("pokepoke.agents.parallel.unassign_with_retry", lambda *a, **kw: None)


def _item(id: str = "par-1") -> BeadsWorkItem:
    return BeadsWorkItem(id=id, title=f"Item {id}", status="ready",
                         priority=1, issue_type="task")


def _success_result(count: int = 1) -> WorkItemResult:
    return WorkItemResult(success=True, request_count=count)


def _fail_result(count: int = 0) -> WorkItemResult:
    return WorkItemResult(success=False, request_count=count)


# ── Pure functions ─────────────────────────────────────────────────

class TestHashString:
    def test_deterministic(self):
        assert _hash_string("abc") == _hash_string("abc")

    def test_different_inputs(self):
        assert _hash_string("abc") != _hash_string("xyz")

    def test_empty_string(self):
        assert _hash_string("") == 0

    def test_returns_non_negative(self):
        # Test multiple inputs to ensure abs() is working
        for s in ["test", "PokePoke-123", "x" * 100, "🐍"]:
            assert _hash_string(s) >= 0


class TestSnakeForWorkItem:
    def test_deterministic(self):
        assert _snake_for_work_item("item-1") == _snake_for_work_item("item-1")

    def test_returns_valid_snake(self):
        for item_id in ["a", "b", "c", "test-123", "PokePoke-xyz"]:
            assert _snake_for_work_item(item_id) in _SNAKE_TYPES


class TestBuildWorkerName:
    def test_format(self):
        name = _build_worker_name("agent", "item-1", 3)
        assert name.startswith("agent-")
        assert name.endswith("-worker-3")
        assert "-worker-3" in name

    def test_includes_snake(self):
        name = _build_worker_name("agent", "item-1", 1)
        # The snake type should be in the name
        snake = _snake_for_work_item("item-1")
        assert snake in name


# ── request_spawn_agent ────────────────────────────────────────────

class TestRequestSpawnAgent:
    def test_sets_wakeup_event(self):
        from pokepoke.agents.parallel import _spawn_wakeup
        _spawn_wakeup.clear()
        request_spawn_agent()
        assert _spawn_wakeup.is_set()
        _spawn_wakeup.clear()


# ── _parallel_process_item ─────────────────────────────────────────

class TestParallelProcessItem:
    @patch("pokepoke.agents.parallel.terminal_ui")
    @patch("pokepoke.agents.parallel.process_work_item")
    def test_success(self, mock_process, mock_ui):
        mock_process.return_value = _success_result()
        sem = threading.Semaphore(1)
        sem.acquire()  # Pre-acquire so release in finally restores it
        result = _parallel_process_item(_item(), MagicMock(), sem, "worker-1")
        assert result.success is True
        # Semaphore should be released
        assert sem.acquire(blocking=False)  # Can acquire again

    @patch("pokepoke.agents.parallel.terminal_ui")
    @patch("pokepoke.agents.parallel.process_work_item")
    def test_failure(self, mock_process, mock_ui):
        mock_process.return_value = _fail_result()
        sem = threading.Semaphore(1)
        sem.acquire()
        result = _parallel_process_item(_item(), MagicMock(), sem)
        assert result.success is False

    @patch("pokepoke.agents.parallel.terminal_ui")
    @patch("pokepoke.agents.parallel.process_work_item", side_effect=RuntimeError("boom"))
    def test_exception_releases_semaphore(self, mock_process, mock_ui):
        sem = threading.Semaphore(1)
        sem.acquire()
        with pytest.raises(RuntimeError, match="boom"):
            _parallel_process_item(_item(), MagicMock(), sem, "worker-1")
        # Semaphore should still be released
        assert sem.acquire(blocking=False)


# ── _collect_done_futures ──────────────────────────────────────────

class TestCollectDoneFutures:
    def test_collects_completed_futures(self):
        item = _item("c-1")
        fut: concurrent.futures.Future[WorkItemResult] = concurrent.futures.Future()
        fut.set_result(_success_result())
        futures = {fut: item}
        record_fn = MagicMock()
        stats = SessionStats(agent_stats=AgentStats())
        logger = MagicMock()

        total, any_success, _s, _f = _collect_done_futures(
            futures, set(), 0, stats, logger, record_fn,
        )
        assert any_success is True
        assert total == 1
        assert len(futures) == 0  # Future was popped
        record_fn.assert_called_once()

    def test_handles_exception_future(self):
        item = _item("c-2")
        fut: concurrent.futures.Future[WorkItemResult] = concurrent.futures.Future()
        fut.set_exception(RuntimeError("agent crashed"))
        futures = {fut: item}
        record_fn = MagicMock()
        stats = SessionStats(agent_stats=AgentStats())
        logger = MagicMock()

        _total, any_success, _s, _f = _collect_done_futures(
            futures, set(), 0, stats, logger, record_fn,
        )
        assert any_success is False
        assert len(futures) == 0

    def test_blacklists_claim_failure(self):
        item = _item("c-3")
        fut: concurrent.futures.Future[WorkItemResult] = concurrent.futures.Future()
        fut.set_result(_fail_result(0))  # request_count=0 -> claim failure
        futures = {fut: item}
        failed_ids: set[str] = set()
        record_fn = MagicMock()
        stats = SessionStats(agent_stats=AgentStats())
        logger = MagicMock()

        _collect_done_futures(futures, failed_ids, 0, stats, logger, record_fn)
        assert "c-3" in failed_ids

    def test_clears_failed_on_success(self):
        item = _item("c-4")
        fut: concurrent.futures.Future[WorkItemResult] = concurrent.futures.Future()
        fut.set_result(_success_result())
        futures = {fut: item}
        failed_ids = {"c-4"}
        record_fn = MagicMock()
        stats = SessionStats(agent_stats=AgentStats())
        logger = MagicMock()

        _collect_done_futures(futures, failed_ids, 0, stats, logger, record_fn)
        assert "c-4" not in failed_ids

    def test_empty_futures(self):
        total, any_success, _s, _f = _collect_done_futures(
            {}, set(), 5, SessionStats(agent_stats=AgentStats()),
            MagicMock(), MagicMock(),
        )
        assert total == 5
        assert any_success is False

    def test_record_fn_exception_handled(self):
        item = _item("c-5")
        fut: concurrent.futures.Future[WorkItemResult] = concurrent.futures.Future()
        fut.set_result(_success_result())
        futures = {fut: item}
        record_fn = MagicMock(side_effect=RuntimeError("record failed"))
        stats = SessionStats(agent_stats=AgentStats())
        logger = MagicMock()

        # Should not raise despite record_fn failure
        _total, any_success, _s, _f = _collect_done_futures(
            futures, set(), 0, stats, logger, record_fn,
        )
        assert any_success is True


# ── _finalize_workers ──────────────────────────────────────────────

class TestFinalizeWorkers:
    def test_empty_futures(self):
        stats = SessionStats(agent_stats=AgentStats())
        logger = MagicMock()
        total, timeout = _finalize_workers({}, stats, 0.0, 0, logger, MagicMock())
        assert total == 0
        assert timeout is False

    def test_completes_remaining(self):
        item = _item("f-1")
        fut: concurrent.futures.Future[WorkItemResult] = concurrent.futures.Future()
        fut.set_result(_success_result(2))
        futures = {fut: item}
        stats = SessionStats(agent_stats=AgentStats())
        logger = MagicMock()
        record_fn = MagicMock()

        total, timeout = _finalize_workers(futures, stats, 0.0, 5, logger, record_fn)
        assert total == 7  # 5 + 2
        assert timeout is False
        record_fn.assert_called_once()

    def test_exception_in_future(self):
        item = _item("f-2")
        fut: concurrent.futures.Future[WorkItemResult] = concurrent.futures.Future()
        fut.set_exception(RuntimeError("worker crashed"))
        futures = {fut: item}
        stats = SessionStats(agent_stats=AgentStats())
        logger = MagicMock()
        record_fn = MagicMock()

        total, _timeout = _finalize_workers(futures, stats, 0.0, 0, logger, record_fn)
        assert total == 0  # Failed result has request_count=0
        record_fn.assert_called_once()


# ── run_parallel_loop ──────────────────────────────────────────────

class TestRunParallelLoop:
    """Test run_parallel_loop with minimal mocking."""

    @patch("pokepoke.agents.parallel.clear_runtime_parallel_limits")
    @patch("pokepoke.agents.parallel.set_runtime_parallel_limits")
    @patch("pokepoke.agents.parallel.set_executor")
    @patch("pokepoke.agents.parallel.terminal_ui")
    @patch("pokepoke.agents.parallel.is_shutting_down", return_value=False)
    @patch("pokepoke.agents.parallel.check_and_commit_main_repo", return_value=True)
    @patch("pokepoke.agents.parallel.get_ready_work_items", return_value=[])
    @patch("pokepoke.agents.parallel.select_multiple_items", return_value=[])
    @patch("pokepoke.agents.parallel.time.sleep")
    def test_no_items_exits(self, mock_sleep, mock_select, mock_ready,
                            mock_repo, mock_shutdown, mock_ui,
                            mock_set_exec, mock_set_limits, mock_clear_limits):
        # No ready items and no futures -> exit
        mock_ready.side_effect = [[], []]  # First call + re-check
        stats = SessionStats(agent_stats=AgentStats())
        logger = MagicMock()
        finalize_fn = MagicMock()
        record_fn = MagicMock()

        exit_code = run_parallel_loop(
            effective_parallel=2, mode_name="Autonomous",
            main_repo_path=Path("."), failed_claim_ids=set(),
            session_stats=stats, start_time=0.0, run_logger=logger,
            continuous=False, record_fn=record_fn, finalize_fn=finalize_fn,
        )
        assert exit_code == 0
        finalize_fn.assert_called_once()

    @patch("pokepoke.agents.parallel.clear_runtime_parallel_limits")
    @patch("pokepoke.agents.parallel.set_runtime_parallel_limits")
    @patch("pokepoke.agents.parallel.set_executor")
    @patch("pokepoke.agents.parallel.terminal_ui")
    @patch("pokepoke.agents.parallel.check_and_commit_main_repo", return_value=False)
    @patch("pokepoke.agents.parallel.is_shutting_down", return_value=False)
    def test_repo_check_failure(self, mock_shutdown, mock_repo, mock_ui,
                                mock_set_exec, mock_set_limits, mock_clear_limits):
        stats = SessionStats(agent_stats=AgentStats())
        logger = MagicMock()
        finalize_fn = MagicMock()

        exit_code = run_parallel_loop(
            effective_parallel=2, mode_name="Autonomous",
            main_repo_path=Path("."), failed_claim_ids=set(),
            session_stats=stats, start_time=0.0, run_logger=logger,
            continuous=False, record_fn=MagicMock(), finalize_fn=finalize_fn,
        )
        assert exit_code == 1

    @patch("pokepoke.agents.parallel.clear_runtime_parallel_limits")
    @patch("pokepoke.agents.parallel.set_runtime_parallel_limits")
    @patch("pokepoke.agents.parallel.set_executor")
    @patch("pokepoke.agents.parallel.terminal_ui")
    @patch("pokepoke.agents.parallel.is_shutting_down", return_value=False)
    @patch("pokepoke.agents.parallel.should_stop_after_current", return_value=False)
    @patch("pokepoke.agents.parallel.check_and_commit_main_repo", return_value=True)
    @patch("pokepoke.agents.parallel.get_ready_work_items")
    @patch("pokepoke.agents.parallel.select_multiple_items")
    @patch("pokepoke.agents.parallel.is_item_claimable", return_value=True)
    @patch("pokepoke.agents.parallel.process_work_item")
    @patch("pokepoke.agents.parallel.time.sleep")
    @patch("pokepoke.agents.parallel.get_effective_max_agents", return_value=2)
    def test_processes_item_and_exits(
        self, mock_max, mock_sleep, mock_process, mock_claimable,
        mock_select, mock_ready, mock_repo, mock_stop,
        mock_shutdown, mock_ui, mock_set_exec, mock_set_limits,
        mock_clear_limits,
    ):
        item = _item("loop-1")
        mock_ready.return_value = [item]
        mock_select.return_value = [item]
        mock_process.return_value = _success_result()

        stats = SessionStats(agent_stats=AgentStats())
        logger = MagicMock()
        finalize_fn = MagicMock()
        record_fn = MagicMock()

        # After first iteration with work, second iteration has no items
        call_count = [0]

        def ready_side_effect():
            call_count[0] += 1
            if call_count[0] == 1:
                return [item]
            return []

        mock_ready.side_effect = ready_side_effect
        mock_select.side_effect = [[item], []]

        exit_code = run_parallel_loop(
            effective_parallel=2, mode_name="Autonomous",
            main_repo_path=Path("."), failed_claim_ids=set(),
            session_stats=stats, start_time=0.0, run_logger=logger,
            continuous=False, record_fn=record_fn, finalize_fn=finalize_fn,
        )
        # Non-continuous mode exits after work is done
        assert exit_code == 0
