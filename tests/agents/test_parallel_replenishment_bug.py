"""Tests for parallel replenishment bug fixes (PokePoke-8o4o).

When multiple agents exit together (or over a short window), the loop must
replenish UP TO the configured maximum, not just one agent per iteration.
"""

import time
from unittest.mock import MagicMock, Mock, patch

import pytest

from pokepoke.agents.parallel import _collect_done_futures, run_parallel_loop
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
    monkeypatch.setattr("pokepoke.agents.parallel_support.terminal_ui", MagicMock())


class TestParallelReplenishmentBug:
    """Regression tests for PokePoke-8o4o: batch replenishment fills all slots.

    When multiple agents exit together (or over a short window), the loop must
    replenish UP TO the configured maximum, not just one agent per iteration.
    """

    @patch("pokepoke.agents.parallel.is_item_claimable", return_value=True)
    @patch("pokepoke.agents.parallel.time.sleep")
    @patch("pokepoke.agents.parallel.terminal_ui")
    @patch("pokepoke.agents.parallel.set_executor")
    @patch("pokepoke.agents.parallel.should_stop_after_current", return_value=False)
    @patch("pokepoke.agents.parallel.is_shutting_down")
    @patch("pokepoke.agents.parallel.check_and_commit_main_repo", return_value=True)
    @patch("pokepoke.agents.parallel.get_ready_work_items")
    @patch("pokepoke.agents.parallel.select_multiple_items")
    @patch("pokepoke.agents.parallel._collect_done_futures")
    @patch("pokepoke.agents.parallel.process_work_item")
    @patch("pokepoke.agents.parallel._get_dynamic_max_agents", return_value=10)
    def test_all_agents_exit_replenishes_to_limit(
        self, mock_dyn_max, mock_pwi, mock_collect, mock_sel, mock_ready,
        mock_repo, mock_shut, mock_stop, mock_set_exec, mock_ui, mock_sleep, mock_claimable,
    ) -> None:
        """When all N agents exit, the next iteration must request N replacements.

        Regression for PokePoke-8o4o: the replacement count was 1 instead of
        (max_parallel - currently_active).
        """
        items = [_make_item(f"item-{i}") for i in range(20)]
        mock_ready.return_value = items

        call_idx = [0]

        def collect_side(futures, failed, total, stats, logger, record_fn, lock=None):
            call_idx[0] += 1
            if call_idx[0] == 2:
                # Simulate all 10 agents completing simultaneously.
                # Use success_count=1 to avoid tripping the circuit breaker
                # (which triggers at _MAX_CONSECUTIVE_FAILURES=10).
                futures.clear()
                return (total, False, 1, 9)
            return (total, False, 0, 0)

        mock_collect.side_effect = collect_side
        mock_sel.side_effect = [items[:10], items[10:20]]
        # 2 full iterations (each: 1 while check + up to 10 inner sleep checks)
        mock_shut.side_effect = [False] * 22 + [True] * 5
        mock_pwi.return_value = WorkItemResult(success=False, request_count=0, stats=AgentStats())

        stats = SessionStats(agent_stats=AgentStats())
        run_parallel_loop(
            effective_parallel=10, mode_name="Autonomous",
            main_repo_path="/repo", failed_claim_ids=set(),
            session_stats=stats, start_time=time.time(),
            run_logger=Mock(), continuous=True,
            record_fn=Mock(), finalize_fn=Mock(),
        )

        # Both select calls must request count=10 (fill all slots, not just 1).
        assert mock_sel.call_count >= 2
        first_count = mock_sel.call_args_list[0].kwargs["count"]
        second_count = mock_sel.call_args_list[1].kwargs["count"]
        assert first_count == 10, f"First select should request 10 slots, got {first_count}"
        assert second_count == 10, f"Second select should request 10 slots after all exit, got {second_count}"

    @patch("pokepoke.agents.parallel.is_item_claimable", return_value=True)
    @patch("pokepoke.agents.parallel.time.sleep")
    @patch("pokepoke.agents.parallel.terminal_ui")
    @patch("pokepoke.agents.parallel.set_executor")
    @patch("pokepoke.agents.parallel.should_stop_after_current", return_value=False)
    @patch("pokepoke.agents.parallel.is_shutting_down")
    @patch("pokepoke.agents.parallel.check_and_commit_main_repo", return_value=True)
    @patch("pokepoke.agents.parallel.get_ready_work_items")
    @patch("pokepoke.agents.parallel.select_multiple_items")
    @patch("pokepoke.agents.parallel._collect_done_futures")
    @patch("pokepoke.agents.parallel.process_work_item")
    @patch("pokepoke.agents.parallel._get_dynamic_max_agents", return_value=10)
    def test_success_does_not_block_replenishment_continuous(
        self, mock_dyn_max, mock_pwi, mock_collect, mock_sel, mock_ready,
        mock_repo, mock_shut, mock_stop, mock_set_exec, mock_ui, mock_sleep, mock_claimable,
    ) -> None:
        """A successful agent must not prevent other slots from being filled in continuous mode.

        Regression for PokePoke-8o4o: when any_success=True the loop used to
        break before replenishing the remaining (max - active) empty slots.
        """
        items = [_make_item(f"item-{i}") for i in range(20)]
        mock_ready.return_value = items

        call_idx = [0]

        def collect_side(futures, failed, total, stats, logger, record_fn, lock=None):
            call_idx[0] += 1
            if call_idx[0] == 2:
                # 9 failures + 1 success; all slots freed.
                futures.clear()
                return (total, True, 1, 9)  # any_success=True
            return (total, False, 0, 0)

        mock_collect.side_effect = collect_side
        mock_sel.side_effect = [items[:10], items[10:20]]
        mock_shut.side_effect = [False] * 22 + [True] * 5
        mock_pwi.return_value = WorkItemResult(success=True, request_count=1, stats=AgentStats())

        stats = SessionStats(agent_stats=AgentStats())
        run_parallel_loop(
            effective_parallel=10, mode_name="Autonomous",
            main_repo_path="/repo", failed_claim_ids=set(),
            session_stats=stats, start_time=time.time(),
            run_logger=Mock(), continuous=True,
            record_fn=Mock(), finalize_fn=Mock(),
        )

        # Even with any_success=True, replenishment must still request 10 slots.
        assert mock_sel.call_count >= 2
        second_count = mock_sel.call_args_list[1].kwargs["count"]
        assert second_count == 10, (
            f"Replenishment count should be 10 even after success, got {second_count}"
        )

    @patch("pokepoke.agents.parallel.is_item_claimable", return_value=True)
    @patch("pokepoke.agents.parallel.time.sleep")
    @patch("pokepoke.agents.parallel.terminal_ui")
    @patch("pokepoke.agents.parallel.set_executor")
    @patch("pokepoke.agents.parallel.should_stop_after_current", return_value=False)
    @patch("pokepoke.agents.parallel.is_shutting_down")
    @patch("pokepoke.agents.parallel.check_and_commit_main_repo", return_value=True)
    @patch("pokepoke.agents.parallel.get_ready_work_items")
    @patch("pokepoke.agents.parallel.select_multiple_items")
    @patch("pokepoke.agents.parallel._collect_done_futures")
    @patch("pokepoke.agents.parallel.process_work_item")
    @patch("pokepoke.agents.parallel._get_dynamic_max_agents", return_value=2)
    def test_single_shot_stops_replenishing_after_success(
        self, mock_dyn_max, mock_pwi, mock_collect, mock_sel, mock_ready,
        mock_repo, mock_shut, mock_stop, mock_set_exec, mock_ui, mock_sleep, mock_claimable,
    ) -> None:
        """Non-continuous runs stop launching new work after the first success.

        Once any worker succeeds, the parallel loop should refrain from
        replenishing additional items and instead drain the remaining
        in-flight workers before exiting.
        """
        items = [_make_item(f"item-{i}") for i in range(3)]
        mock_ready.return_value = items

        call_idx = [0]

        def collect_side(futures, failed, total, stats, logger, record_fn, lock=None):
            call_idx[0] += 1
            if call_idx[0] == 1:
                # First iteration: no completions yet.
                return (total, False, 0, 0)
            if call_idx[0] == 2:
                # Second iteration: both active workers complete and at least
                # one succeeds; all slots are now free.
                futures.clear()
                return (total + 2, True, 1, 1)
            return (total, False, 0, 0)

        mock_collect.side_effect = collect_side
        mock_sel.side_effect = [items[:2], items[2:3]]
        # Provide enough values: the wait loop (lines 358-362) calls
        # is_shutting_down() up to 10 times per iteration.
        mock_shut.side_effect = [False] * 22 + [True] * 5
        mock_pwi.return_value = WorkItemResult(success=True, request_count=1, stats=AgentStats())

        stats = SessionStats(agent_stats=AgentStats())
        code = run_parallel_loop(
            effective_parallel=2, mode_name="Autonomous",
            main_repo_path="/repo", failed_claim_ids=set(),
            session_stats=stats, start_time=time.time(),
            run_logger=Mock(), continuous=False,
            record_fn=Mock(), finalize_fn=Mock(),
        )

        assert code == 0
        # Only the initial replenishment should occur; after success, no new
        # items should be selected even though slots are available.
        assert mock_sel.call_count == 1

    def test_collect_done_futures_second_sweep_catches_concurrent_completions(
        self,
    ) -> None:
        """Second sweep after FIRST_COMPLETED collects all concurrently finished futures.

        Regression for PokePoke-8o4o: without the second sweep, only the first
        completed future was detected, leaving (N-1) slots unclaimed and forcing
        the loop to add only 1 replacement instead of N.
        """
        import concurrent.futures as cf

        # Three futures all complete at approximately the same time.
        with cf.ThreadPoolExecutor(max_workers=3) as pool:
            futs = [
                pool.submit(lambda: WorkItemResult(success=True, request_count=1))
                for _ in range(3)
            ]
            items = [_make_item(f"concurrent-{i}") for i in range(3)]
            futures_dict: dict[cf.Future, BeadsWorkItem] = dict(zip(futs, items, strict=False))  # type: ignore[type-arg]

            # Wait for all to finish so they are all "done" at call time.
            cf.wait(futs, timeout=5)

            failed: set[str] = set()
            stats = SessionStats(agent_stats=AgentStats())
            record_fn = Mock()

            from pokepoke.agents.parallel import _collect_done_futures
            _total, any_ok, successes, failures = _collect_done_futures(
                futures_dict, failed, 0, stats, Mock(), record_fn,
            )

        # All three must be collected in a single call — none left in futures_dict.
        assert len(futures_dict) == 0, (
            f"{len(futures_dict)} future(s) were NOT collected; "
            "replenishment would under-count available slots"
        )
        assert record_fn.call_count == 3
        assert any_ok is True
        assert successes == 3
        assert failures == 0

    def test_exception_crashed_items_not_blacklisted(self) -> None:
        """Workers that crash with exceptions must NOT be added to failed_claim_ids.

        Regression for PokePoke-8o4o: the exception handler in _collect_done_futures
        created WorkItemResult(request_count=0) which incorrectly added crashed items
        to failed_claim_ids, permanently preventing replacement agents from being
        launched for those items.
        """
        import concurrent.futures as cf

        # Simulate 3 workers that all crash with exceptions.
        futs = [cf.Future() for _ in range(3)]
        for fut in futs:
            fut.set_exception(RuntimeError("worker crashed"))
        items = [_make_item(f"crash-{i}") for i in range(3)]
        futures_dict: dict[cf.Future, BeadsWorkItem] = dict(zip(futs, items, strict=False))  # type: ignore[type-arg]

        failed: set[str] = set()
        stats = SessionStats(agent_stats=AgentStats())
        record_fn = Mock()

        _collect_done_futures(futures_dict, failed, 0, stats, Mock(), record_fn)

        # No crashed items should be in failed_claim_ids — they must remain
        # eligible for retry so replacement agents can pick them up.
        assert len(failed) == 0, (
            f"Exception-crashed items were blacklisted: {failed}; "
            "this prevents replacement agents from being launched"
        )
        assert len(futures_dict) == 0  # all collected
        assert record_fn.call_count == 3
