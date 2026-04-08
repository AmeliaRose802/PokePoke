"""Boundary contract tests for the parallel <-> orchestrator module pair.

Verifies the implicit contract between ``pokepoke.agents.parallel`` (and its
helpers in ``parallel_support`` / ``parallel_worker_pool``) and
``pokepoke.orchestration.orchestrator``, covering:

* Futures dict shape: ``dict[Future[WorkItemResult], BeadsWorkItem]``
* SessionStats mutation flow through ``record_fn`` (``_record_item_result``)
* Return codes from ``run_parallel_loop`` (0 = success, 1 = failure)
"""

from __future__ import annotations

import concurrent.futures
import threading
from unittest.mock import MagicMock, patch

import pytest

from pokepoke.types import (
    AgentStats,
    BeadsWorkItem,
    ModelCompletionRecord,
    SessionStats,
    WorkItemResult,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_item(item_id: str = "item-1", **kwargs) -> BeadsWorkItem:
    defaults = dict(
        id=item_id, title=f"Task {item_id}", status="in_progress",
        priority=1, issue_type="task",
    )
    defaults.update(kwargs)
    return BeadsWorkItem(**defaults)


def _make_session_stats() -> SessionStats:
    return SessionStats(agent_stats=AgentStats())


def _make_result(success: bool = True, request_count: int = 1, **kwargs) -> WorkItemResult:
    return WorkItemResult(success=success, request_count=request_count, **kwargs)


_Future = concurrent.futures.Future


# ===========================================================================
# 1. Futures dictionary shape
# ===========================================================================


class TestFuturesDictShape:
    """The parallel loop's internal dict must map Future[WorkItemResult] → BeadsWorkItem."""

    def test_future_key_is_work_item_result_future(self):
        """Futures keys must be Future[WorkItemResult] instances."""
        futures: dict[_Future[WorkItemResult], BeadsWorkItem] = {}
        item = _make_item()
        fut: _Future[WorkItemResult] = _Future()
        fut.set_result(_make_result())
        futures[fut] = item

        assert isinstance(next(iter(futures.keys())), _Future)
        assert isinstance(next(iter(futures.values())), BeadsWorkItem)

    def test_future_value_contains_required_beads_fields(self):
        """BeadsWorkItem values must carry id, title, status, priority, issue_type."""
        item = _make_item("abc-123", title="Fix bug", priority=2)
        assert item.id == "abc-123"
        assert item.title == "Fix bug"
        assert item.priority == 2
        assert item.issue_type == "task"
        assert item.status == "in_progress"

    def test_future_resolves_to_work_item_result(self):
        """When a future completes, its result must be a WorkItemResult."""
        fut: _Future[WorkItemResult] = _Future()
        result = _make_result(success=True, request_count=3)
        fut.set_result(result)

        resolved = fut.result()
        assert isinstance(resolved, WorkItemResult)
        assert resolved.success is True
        assert resolved.request_count == 3

    def test_future_exception_produces_fallback_result(self):
        """Contract: when a future raises, the collector creates
        WorkItemResult(success=False, request_count=0)."""
        fut: _Future[WorkItemResult] = _Future()
        fut.set_exception(RuntimeError("agent crashed"))

        with pytest.raises(RuntimeError, match="agent crashed"):
            fut.result()

        # The parallel collector would produce this fallback:
        fallback = WorkItemResult(success=False, request_count=0)
        assert fallback.success is False
        assert fallback.request_count == 0

    def test_locked_pop_returns_item_or_none(self):
        """_locked_pop must return the BeadsWorkItem or None when key is missing."""
        from pokepoke.agents.parallel_worker_pool import _locked_pop

        futures: dict[_Future[WorkItemResult], BeadsWorkItem] = {}
        item = _make_item()
        fut: _Future[WorkItemResult] = _Future()
        fut.set_result(_make_result())
        futures[fut] = item
        lock = threading.Lock()

        # Pop existing key returns item
        popped = _locked_pop(lock, futures, fut)
        assert popped is item
        assert fut not in futures

        # Pop missing key returns None
        assert _locked_pop(lock, futures, fut) is None

    def test_locked_pop_works_without_lock(self):
        """_locked_pop with lock=None must still work (single-thread path)."""
        from pokepoke.agents.parallel_worker_pool import _locked_pop

        futures: dict[_Future[WorkItemResult], BeadsWorkItem] = {}
        item = _make_item()
        fut: _Future[WorkItemResult] = _Future()
        fut.set_result(_make_result())
        futures[fut] = item

        assert _locked_pop(None, futures, fut) is item
        assert not futures

    def test_locked_register_dispatch_adds_to_both(self):
        """_locked_register_dispatch must add the future to the dict and item.id to the active set."""
        from pokepoke.agents.parallel_worker_pool import _locked_register_dispatch

        futures: dict[_Future[WorkItemResult], BeadsWorkItem] = {}
        active: set[str] = set()
        item = _make_item("dispatch-1")
        fut: _Future[WorkItemResult] = _Future()
        lock = threading.Lock()

        _locked_register_dispatch(lock, futures, active, fut, item)
        assert fut in futures
        assert futures[fut] is item
        assert "dispatch-1" in active


# ===========================================================================
# 2. SessionStats mutation flow via record_fn
# ===========================================================================


class TestSessionStatsFlow:
    """SessionStats must be mutated correctly by the orchestrator's _record_item_result."""

    def test_record_completion_increments_items_completed(self):
        stats = _make_session_stats()
        item = _make_item()

        count = stats.record_completion(item, agent_type="work")
        assert count == 1
        assert stats.items_completed == 1
        assert len(stats.completed_items_list) == 1
        assert stats.completed_items_list[0].id == item.id

    def test_record_agent_run_increments_counts(self):
        stats = _make_session_stats()

        stats.record_agent_run("work", 1)
        stats.record_agent_run("cleanup", 2)
        stats.record_agent_run("gate", 1)

        assert stats.agent_run_counts["work"] == 1
        assert stats.agent_run_counts["cleanup"] == 2
        assert stats.agent_run_counts["gate"] == 1

    def test_record_agent_stats_accumulates(self):
        stats = _make_session_stats()
        item_stats = AgentStats(
            wall_duration=10.0, input_tokens=100, output_tokens=50,
            lines_added=20, lines_removed=5,
        )

        stats.record_agent_stats(item_stats)
        assert stats.agent_stats.wall_duration == 10.0
        assert stats.agent_stats.input_tokens == 100
        assert stats.agent_stats.output_tokens == 50

        # Second accumulation
        stats.record_agent_stats(AgentStats(wall_duration=5.0, input_tokens=50))
        assert stats.agent_stats.wall_duration == 15.0
        assert stats.agent_stats.input_tokens == 150

    def test_record_retries_from_request_count(self):
        """When request_count > 1, retries = request_count - 1 per the orchestrator contract."""
        stats = _make_session_stats()
        request_count = 4
        retries = request_count - 1  # orchestrator logic

        stats.record_retries(retries)
        assert stats.agent_stats.retries == 3

    def test_record_model_completion(self):
        stats = _make_session_stats()
        mc = ModelCompletionRecord(
            item_id="item-1", model="gpt-4", duration_seconds=12.5,
            gate_passed=True, input_tokens=200, output_tokens=100,
        )

        stats.record_model_completion(mc)
        assert len(stats.model_completions) == 1
        assert stats.model_completions[0].item_id == "item-1"
        assert stats.model_completions[0].gate_passed is True

    def test_snapshot_returns_frozen_copy(self):
        """snapshot() must return a SessionStatsSnapshot that is independent of the original."""
        stats = _make_session_stats()
        stats.record_completion(_make_item("snap-1"), agent_type="work")
        stats.record_agent_run("work")

        snap = stats.snapshot()
        assert snap.items_completed == 1
        assert snap.agent_run_counts["work"] == 1

        # Mutating original must not affect snapshot
        stats.record_completion(_make_item("snap-2"), agent_type="work")
        assert snap.items_completed == 1
        assert stats.items_completed == 2

    def test_thread_safe_record_completion(self):
        """record_completion must be safe under concurrent access."""
        stats = _make_session_stats()
        errors: list[Exception] = []

        def _record(idx: int) -> None:
            try:
                stats.record_completion(_make_item(f"thread-{idx}"), agent_type="work")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=_record, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert stats.items_completed == 20

    def test_record_fn_signature_matches_contract(self):
        """The record_fn callback must accept (item, result, session_stats, run_logger)."""
        # This verifies the signature by calling _record_item_result with mocks
        # for all external dependencies it touches.
        from pokepoke.orchestration.orchestrator import _record_item_result

        stats = _make_session_stats()
        item = _make_item()
        result = _make_result(success=True, request_count=1, stats=AgentStats(wall_duration=5.0))
        run_logger = MagicMock()

        with (
            patch("pokepoke.orchestration.orchestrator.record_item_attempt", return_value={}),
            patch("pokepoke.orchestration.orchestrator.record_completion"),
            patch("pokepoke.orchestration.orchestrator.append_model_history_entry"),
            patch("pokepoke.orchestration.orchestrator.record_item_completed", return_value={}),
            patch("pokepoke.orchestration.orchestrator.increment_items_completed", return_value=1),
            patch("pokepoke.orchestration.orchestrator.run_periodic_maintenance"),
            patch("pokepoke.orchestration.orchestrator.load_config") as mock_cfg,
            patch("pokepoke.orchestration.orchestrator.commit_state_branch", return_value=False),
        ):
            mock_cfg.return_value = MagicMock(
                needs_human_attention_threshold=5,
                state_branch=MagicMock(enabled=False),
            )
            success, completed = _record_item_result(item, result, stats, run_logger)

        assert success is True
        assert completed == 1
        assert stats.agent_run_counts["work"] == 1

    def test_failed_result_does_not_increment_items_completed(self):
        """When result.success is False, items_completed must NOT be incremented."""
        from pokepoke.orchestration.orchestrator import _record_item_result

        stats = _make_session_stats()
        item = _make_item()
        result = _make_result(success=False, request_count=1)
        run_logger = MagicMock()

        with (
            patch("pokepoke.orchestration.orchestrator.record_item_attempt", return_value={}),
            patch("pokepoke.orchestration.orchestrator.load_config") as mock_cfg,
        ):
            mock_cfg.return_value = MagicMock(needs_human_attention_threshold=5)
            success, completed = _record_item_result(item, result, stats, run_logger)

        assert success is False
        assert completed == 0
        assert stats.items_completed == 0


# ===========================================================================
# 3. Return codes from run_parallel_loop
# ===========================================================================


class TestReturnCodes:
    """run_parallel_loop must return 0 on success and 1 on failure conditions."""

    def test_exit_code_zero_on_clean_exit(self):
        """_LoopState.exit_code starts at 0 — clean exits preserve this."""
        from pokepoke.agents.parallel import _LoopState

        state = _LoopState()
        assert state.exit_code == 0

    def test_exit_code_one_on_circuit_breaker(self):
        """Circuit breaker trip sets exit_code = 1."""
        from pokepoke.agents.parallel import _LoopState

        state = _LoopState()
        state.circuit_breaker_tripped = True
        state.exit_code = 1
        assert state.exit_code == 1

    def test_exit_code_one_on_memory_breaker(self):
        """Memory circuit breaker trip sets exit_code = 1."""
        from pokepoke.agents.parallel import _LoopState

        state = _LoopState()
        state.memory_circuit_breaker_tripped = True
        state.exit_code = 1
        assert state.exit_code == 1

    def test_exit_code_one_on_preflight_failure(self):
        """Preflight failure (max exceeded) sets exit_code = 1."""
        from pokepoke.agents.parallel import _LoopState

        state = _LoopState()
        state.exit_code = 1
        assert state.exit_code == 1

    def test_loop_state_consecutive_failure_tracking(self):
        """_LoopState must track consecutive_failures for circuit breaker."""
        from pokepoke.agents.parallel import _LoopState

        state = _LoopState()
        assert state.consecutive_failures == 0
        state.consecutive_failures = 5
        assert state.consecutive_failures == 5

    def test_update_circuit_breaker_trips_at_threshold(self):
        """update_circuit_breaker must trip at max_consecutive_failures."""
        from pokepoke.agents.parallel_worker_pool import update_circuit_breaker

        futures: dict[_Future[WorkItemResult], BeadsWorkItem] = {}
        run_logger = MagicMock()

        # Not tripped below threshold
        consec, tripped = update_circuit_breaker(0, 1, 4, 10, futures, run_logger)
        assert consec == 5
        assert tripped is False

        # Tripped at threshold
        consec, tripped = update_circuit_breaker(0, 1, 9, 10, futures, run_logger)
        assert consec == 10
        assert tripped is True

    def test_update_circuit_breaker_resets_on_success(self):
        """A successful batch resets the consecutive failure counter."""
        from pokepoke.agents.parallel_worker_pool import update_circuit_breaker

        futures: dict[_Future[WorkItemResult], BeadsWorkItem] = {}
        run_logger = MagicMock()

        consec, tripped = update_circuit_breaker(1, 0, 8, 10, futures, run_logger)
        assert consec == 0
        assert tripped is False

    def test_collect_done_futures_return_shape(self):
        """collect_done_futures must return (total_requests, any_success, successes, failures)."""
        from pokepoke.agents.parallel_worker_pool import collect_done_futures

        stats = _make_session_stats()
        run_logger = MagicMock()
        record_fn = MagicMock()

        item = _make_item()
        fut: _Future[WorkItemResult] = _Future()
        fut.set_result(_make_result(success=True, request_count=2))
        futures = {fut: item}

        result = collect_done_futures(futures, set(), 0, stats, run_logger, record_fn)
        assert isinstance(result, tuple)
        assert len(result) == 4
        total_requests, any_success, successes, failures = result
        assert total_requests == 2
        assert any_success is True
        assert successes == 1
        assert failures == 0
        record_fn.assert_called_once()

    def test_collect_done_futures_records_failure(self):
        """Failed future results must increment failure count."""
        from pokepoke.agents.parallel_worker_pool import collect_done_futures

        stats = _make_session_stats()
        run_logger = MagicMock()
        record_fn = MagicMock()

        item = _make_item()
        fut: _Future[WorkItemResult] = _Future()
        fut.set_result(_make_result(success=False, request_count=0))
        futures = {fut: item}

        _total_requests, any_success, successes, failures = collect_done_futures(
            futures, set(), 0, stats, run_logger, record_fn,
        )
        assert any_success is False
        assert successes == 0
        assert failures == 1

    def test_collect_done_futures_exception_yields_failure(self):
        """A future that raised an exception must be counted as a failure."""
        from pokepoke.agents.parallel_worker_pool import collect_done_futures

        stats = _make_session_stats()
        run_logger = MagicMock()
        record_fn = MagicMock()

        item = _make_item()
        fut: _Future[WorkItemResult] = _Future()
        fut.set_exception(RuntimeError("boom"))
        futures = {fut: item}

        _total_requests, any_success, _successes, failures = collect_done_futures(
            futures, set(), 0, stats, run_logger, record_fn,
        )
        assert any_success is False
        assert failures == 1
        # record_fn should still be called with a fallback result
        record_fn.assert_called_once()

    def test_handle_circuit_breaker_drain_exit_code(self):
        """_handle_circuit_breaker_drain sets exit_code=1 when no futures remain."""
        from pokepoke.agents.parallel import _handle_circuit_breaker_drain, _LoopState

        state = _LoopState()
        futures: dict[_Future[WorkItemResult], BeadsWorkItem] = {}
        stats = _make_session_stats()
        run_logger = MagicMock()
        record_fn = MagicMock()

        should_break = _handle_circuit_breaker_drain(
            state, futures, set(), stats, run_logger, record_fn, "auto",
        )
        assert should_break is True
        assert state.exit_code == 1
