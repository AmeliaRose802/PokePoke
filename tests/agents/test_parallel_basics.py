"""Tests for basic parallel processing functions.

This module contains unit tests for the core parallel execution functions:
- _parallel_process_item: Worker function that processes individual work items
- _collect_done_futures: Helper that collects completed futures and updates stats

These tests focus on resource management, status tracking, and error handling
for individual work items without testing the full orchestrator loop.
"""

import concurrent.futures
import os
import threading
from unittest.mock import MagicMock, Mock, patch

import pytest

from pokepoke.agents.parallel import (
    _collect_done_futures,
    _parallel_process_item,
)
from pokepoke.types import AgentStats, BeadsWorkItem, SessionStats, WorkItemResult


def _make_item(item_id: str = "t1") -> BeadsWorkItem:
    return BeadsWorkItem(
        id=item_id, title=f"Title-{item_id}", status="open",
        priority=1, issue_type="task",
    )


@pytest.fixture(autouse=True)
def _disable_preflight_health(monkeypatch):
    """Disable preflight health checks and mock beads claim for all parallel tests.

    The preflight system uses a lazy import inside run_parallel_loop.
    We mock get_config to return a config with preflight disabled so that
    tests do not need real git repos / disk space checks.
    We also mock assign_and_sync_item since tests use fake item IDs.
    """
    mock_cfg = MagicMock()
    mock_cfg.preflight_health.enabled = False
    mock_cfg.max_parallel_agents = 10
    monkeypatch.setattr("pokepoke.config.get_config", lambda: mock_cfg)
    monkeypatch.setattr("pokepoke.agents.parallel.assign_and_sync_item", lambda *a, **kw: True)
    monkeypatch.setattr("pokepoke.agents.parallel.unassign_with_retry", lambda *a, **kw: None)
    # Mock parallel_support dependencies so _finalize_workers doesn't call real processes
    monkeypatch.setattr("pokepoke.agents.parallel_support.kill_orphaned_copilot_processes", lambda **kw: None)
    monkeypatch.setattr("pokepoke.agents.parallel_support.terminal_ui", MagicMock())


# ── _parallel_process_item ──────────────────────────────────────────────────

class TestParallelProcessItem:
    """Tests for _parallel_process_item wrapper."""

    @patch.dict(os.environ, {"AGENT_NAME": ""}, clear=False)
    @patch("pokepoke.agents.parallel.terminal_ui")
    @patch("pokepoke.agents.parallel.process_work_item")
    def test_success_releases_resources(self, mock_pwi: Mock, mock_ui: Mock) -> None:
        mock_pwi.return_value = WorkItemResult(success=True, request_count=1)
        sem = threading.Semaphore(0)

        result = _parallel_process_item(_make_item(), Mock(), sem)

        assert result == WorkItemResult(success=True, request_count=1)
        assert sem.acquire(blocking=False)
        # Agent status should be registered and updated (agent_id is item.id
        # when no worker_agent_name is provided)
        mock_ui.ui.push_agent_status.assert_any_call(
            "t1",
            "pokepoke",
            iteration=1,
            status="running",
            work_item_id="t1",
            work_item_title="Title-t1",
            agent_type="work",
        )
        mock_ui.ui.push_agent_status.assert_any_call(
            "t1",
            "pokepoke",
            iteration=1,
            status="success",
            work_item_id="t1",
            work_item_title="Title-t1",
            agent_type="work",
        )

    @patch.dict(os.environ, {"AGENT_NAME": ""}, clear=False)
    @patch("pokepoke.agents.parallel.terminal_ui")
    @patch("pokepoke.agents.parallel.process_work_item", side_effect=RuntimeError("boom"))
    def test_exception_releases_resources(self, mock_pwi: Mock, mock_ui: Mock) -> None:
        sem = threading.Semaphore(0)

        with pytest.raises(RuntimeError):
            _parallel_process_item(_make_item(), Mock(), sem)

        assert sem.acquire(blocking=False)
        # Agent status should be set to failed on exception
        mock_ui.ui.push_agent_status.assert_any_call(
            "t1",
            "pokepoke",
            iteration=1,
            status="failed",
            work_item_id="t1",
            work_item_title="Title-t1",
            agent_type="work",
        )

    @patch.dict(os.environ, {"AGENT_NAME": ""}, clear=False)
    @patch("pokepoke.agents.parallel.terminal_ui")
    @patch("pokepoke.agents.parallel.process_work_item")
    def test_failure_sets_agent_failed_status(self, mock_pwi: Mock, mock_ui: Mock) -> None:
        """A work item that returns success=False should set agent status to failed."""
        mock_pwi.return_value = WorkItemResult(success=False, request_count=1)
        sem = threading.Semaphore(0)

        result = _parallel_process_item(_make_item(), Mock(), sem)

        assert result.success is False
        mock_ui.ui.push_agent_status.assert_any_call(
            "t1",
            "pokepoke",
            iteration=1,
            status="failed",
            work_item_id="t1",
            work_item_title="Title-t1",
            agent_type="work",
        )

    @patch("pokepoke.agents.parallel.terminal_ui")
    @patch("pokepoke.agents.parallel.process_work_item")
    def test_output_routed_via_agent_output_for(self, mock_pwi: Mock, mock_ui: Mock) -> None:
        """Verify that agent_output_for context manager is used for output routing."""
        mock_pwi.return_value = WorkItemResult(success=True, request_count=1)
        sem = threading.Semaphore(0)

        _parallel_process_item(_make_item(), Mock(), sem)

        # Should use agent_output_for to route output
        mock_ui.ui.agent_output_for.assert_called_once_with("t1")

    @patch("pokepoke.agents.parallel.terminal_ui")
    @patch("pokepoke.agents.parallel.process_work_item")
    def test_same_item_different_workers_get_unique_agent_ids(
        self, mock_pwi: Mock, mock_ui: Mock,
    ) -> None:
        """Two workers on the same item must use distinct agent_ids (PokePoke-kluq)."""
        mock_pwi.return_value = WorkItemResult(success=True, request_count=1)

        item = _make_item("dup-item")
        sem1 = threading.Semaphore(0)
        sem2 = threading.Semaphore(0)

        _parallel_process_item(item, Mock(), sem1, worker_agent_name="worker-1")
        _parallel_process_item(item, Mock(), sem2, worker_agent_name="worker-2")

        # Collect all agent_ids passed to push_agent_status
        agent_ids = {
            call.args[0] for call in mock_ui.ui.push_agent_status.call_args_list
        }
        # Must have two distinct agent_ids for the two workers
        assert len(agent_ids) == 2
        assert "dup-item:worker-1" in agent_ids
        assert "dup-item:worker-2" in agent_ids

    @patch("pokepoke.agents.parallel.terminal_ui")
    @patch("pokepoke.agents.parallel.process_work_item")
    def test_process_work_item_receives_agent_id(
        self, mock_pwi: Mock, mock_ui: Mock,
    ) -> None:
        """process_work_item should receive the derived agent_id for gating."""
        mock_pwi.return_value = WorkItemResult(success=True, request_count=1)
        sem = threading.Semaphore(0)
        item = _make_item("gate-1")

        _parallel_process_item(item, Mock(), sem, worker_agent_name="worker-A")

        assert mock_pwi.call_args
        _, kwargs = mock_pwi.call_args
        assert kwargs["agent_id"] == "gate-1:worker-A"


# ── _collect_done_futures ───────────────────────────────────────────────────

class TestCollectDoneFutures:
    """Tests for _collect_done_futures helper."""

    def test_collects_done_future(self) -> None:
        """A completed future is collected and record_fn is called."""
        fut: concurrent.futures.Future = concurrent.futures.Future()
        fut.set_result(WorkItemResult(success=True, request_count=2, stats=AgentStats(), cleanup_agent_runs=1, gate_agent_runs=1))
        item = _make_item()
        futures = {fut: item}
        failed: set[str] = set()
        stats = SessionStats(agent_stats=AgentStats())
        logger = Mock()
        record_fn = Mock()

        total, any_ok, successes, failures = _collect_done_futures(
            futures, failed, 0, stats, logger, record_fn,
        )

        assert total == 2
        assert any_ok is True
        assert successes == 1
        assert failures == 0
        assert len(futures) == 0
        record_fn.assert_called_once()

    def test_records_failed_claim(self) -> None:
        """A failure with 0 requests adds item to failed_claim_ids."""
        fut: concurrent.futures.Future = concurrent.futures.Future()
        fut.set_result(WorkItemResult(success=False, request_count=0))
        item = _make_item("fail1")
        futures = {fut: item}
        failed: set[str] = set()
        stats = SessionStats(agent_stats=AgentStats())
        logger = Mock()
        record_fn = Mock()

        _collect_done_futures(futures, failed, 0, stats, logger, record_fn)

        assert "fail1" in failed

    def test_exception_in_future(self) -> None:
        """An exception in a future is handled gracefully.

        Crashed workers must NOT be added to failed_claim_ids so they
        remain eligible for retry (fixes PokePoke-8o4o).
        """
        fut: concurrent.futures.Future = concurrent.futures.Future()
        fut.set_exception(RuntimeError("kaboom"))
        item = _make_item("err1")
        futures = {fut: item}
        failed: set[str] = set()
        stats = SessionStats(agent_stats=AgentStats())
        logger = Mock()
        record_fn = Mock()

        total, any_ok, successes, failures = _collect_done_futures(
            futures, failed, 5, stats, logger, record_fn,
        )

        assert total == 5  # no requests added
        assert any_ok is False
        assert successes == 0
        assert failures == 1
        # Exception-crashed items must NOT be blacklisted (PokePoke-8o4o fix)
        assert "err1" not in failed
        logger.log_orchestrator.assert_called()
        record_fn.assert_called_once()

    def test_claim_failure_is_blacklisted(self) -> None:
        """A returned claim failure (request_count=0, no exception) IS blacklisted."""
        fut: concurrent.futures.Future = concurrent.futures.Future()
        fut.set_result(WorkItemResult(success=False, request_count=0))
        item = _make_item("claim-fail")
        futures = {fut: item}
        failed: set[str] = set()
        stats = SessionStats(agent_stats=AgentStats())
        record_fn = Mock()

        _collect_done_futures(futures, failed, 0, stats, Mock(), record_fn)

        assert "claim-fail" in failed

    def test_no_done_futures_returns_zero(self) -> None:
        """When no futures are done, returns unchanged totals."""
        stats = SessionStats(agent_stats=AgentStats())
        record_fn = Mock()
        # Empty dict
        total, any_ok, successes, failures = _collect_done_futures(
            {}, set(), 3, stats, Mock(), record_fn,
        )
        assert total == 3
        assert any_ok is False
        assert successes == 0
        assert failures == 0
        record_fn.assert_not_called()


class TestCollectDoneFuturesWait:
    """Tests for _collect_done_futures wait fallback path."""

    def test_waits_for_not_done_futures(self) -> None:
        """When no futures are immediately done, falls back to wait()."""
        # Create a future that is not immediately done but completes during wait
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            import time as _time
            fut = pool.submit(lambda: (_time.sleep(0.1), WorkItemResult(success=True, request_count=1))[1])
            item = _make_item("w1")
            futures = {fut: item}
            failed: set[str] = set()
            stats = SessionStats(agent_stats=AgentStats())
            record_fn = Mock()

            _total, any_ok, _successes, _failures = _collect_done_futures(
                futures, failed, 0, stats, Mock(), record_fn,
            )

            assert any_ok is True
            assert record_fn.call_count == 1


class TestCollectDoneFuturesSuccessFailureCounts:
    """Tests that _collect_done_futures returns correct success/failure counts."""

    def test_mixed_results_counts(self) -> None:
        """Mixed successes and failures return correct counts."""
        futs = []
        items = []
        for i in range(3):
            fut = concurrent.futures.Future()
            fut.set_result(WorkItemResult(success=True, request_count=1))
            futs.append(fut)
            items.append(_make_item(f"s{i}"))
        for i in range(2):
            fut = concurrent.futures.Future()
            fut.set_result(WorkItemResult(success=False, request_count=1))
            futs.append(fut)
            items.append(_make_item(f"f{i}"))

        futures_dict = dict(zip(futs, items, strict=False))
        stats = SessionStats(agent_stats=AgentStats())

        total, any_ok, successes, failures = _collect_done_futures(
            futures_dict, set(), 0, stats, Mock(), Mock(),
        )

        assert successes == 3
        assert failures == 2
        assert any_ok is True
        assert total == 5
