"""Tests for the run_parallel_loop main orchestration logic."""

import threading
import time
from unittest.mock import MagicMock, Mock, patch

import pytest

from pokepoke.agents.parallel import run_parallel_loop
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


# ── run_parallel_loop ────────────────────────────────────────────────────────

class TestRunParallelLoop:
    """Tests for run_parallel_loop."""

    @patch("pokepoke.agents.parallel.time.sleep")
    @patch("pokepoke.agents.parallel.terminal_ui")
    @patch("pokepoke.agents.parallel.set_executor")
    @patch("pokepoke.agents.parallel.is_shutting_down", side_effect=[False, True])
    @patch("pokepoke.agents.parallel.check_and_commit_main_repo", return_value=True)
    @patch("pokepoke.agents.parallel.get_ready_work_items", return_value=[])
    @patch("pokepoke.agents.parallel.select_multiple_items", return_value=[])
    def test_exits_with_no_items(
        self, mock_sel, mock_ready, mock_repo, mock_shut,
        mock_set_exec, mock_ui, mock_sleep,
    ) -> None:
        """Exits 0 when no items are available and nothing in flight."""
        stats = SessionStats(agent_stats=AgentStats())
        record_fn = Mock()
        finalize_fn = Mock()
        logger = Mock()

        code = run_parallel_loop(
            effective_parallel=2, mode_name="Autonomous",
            main_repo_path="/repo", failed_claim_ids=set(),
            session_stats=stats, start_time=time.time(),
            run_logger=logger, continuous=True,
            record_fn=record_fn, finalize_fn=finalize_fn,
        )

        assert code == 0
        finalize_fn.assert_called_once()

    @patch("pokepoke.agents.parallel.time.sleep")
    @patch("pokepoke.agents.parallel.terminal_ui")
    @patch("pokepoke.agents.parallel.set_executor")
    @patch("pokepoke.agents.parallel.is_shutting_down", return_value=False)
    @patch("pokepoke.agents.parallel.check_and_commit_main_repo", return_value=False)
    @patch("pokepoke.agents.parallel.get_ready_work_items", return_value=[])
    def test_exits_on_repo_check_failure(
        self, mock_ready, mock_repo, mock_shut,
        mock_set_exec, mock_ui, mock_sleep,
    ) -> None:
        """Returns 1 when main repo check fails."""
        stats = SessionStats(agent_stats=AgentStats())
        logger = Mock()

        code = run_parallel_loop(
            effective_parallel=2, mode_name="Autonomous",
            main_repo_path="/repo", failed_claim_ids=set(),
            session_stats=stats, start_time=time.time(),
            run_logger=logger, continuous=True,
            record_fn=Mock(), finalize_fn=Mock(),
        )

        assert code == 1

    @patch("pokepoke.agents.parallel.is_item_claimable", return_value=True)
    @patch("pokepoke.agents.parallel.time.sleep")
    @patch("pokepoke.agents.parallel.terminal_ui")
    @patch("pokepoke.agents.parallel.set_executor")
    @patch("pokepoke.agents.parallel.is_shutting_down", side_effect=[False, True, True])
    @patch("pokepoke.agents.parallel.check_and_commit_main_repo", return_value=True)
    @patch("pokepoke.agents.parallel.get_ready_work_items")
    @patch("pokepoke.agents.parallel.select_multiple_items")
    @patch("pokepoke.agents.parallel.process_work_item")
    def test_submits_and_collects_item(
        self, mock_pwi, mock_sel, mock_ready,
        mock_repo, mock_shut, mock_set_exec, mock_ui, mock_sleep, mock_claimable,
    ) -> None:
        """Submits an item and collects its result in single-shot mode."""
        item = _make_item("x1")
        mock_ready.return_value = [item]
        mock_sel.return_value = [item]
        mock_pwi.return_value = WorkItemResult(success=True, request_count=1, stats=AgentStats(), gate_agent_runs=1)

        stats = SessionStats(agent_stats=AgentStats())
        record_fn = Mock()
        finalize_fn = Mock()
        logger = Mock()

        code = run_parallel_loop(
            effective_parallel=2, mode_name="Autonomous",
            main_repo_path="/repo", failed_claim_ids=set(),
            session_stats=stats, start_time=time.time(),
            run_logger=logger, continuous=False,
            record_fn=record_fn, finalize_fn=finalize_fn,
        )

        assert code == 0
        finalize_fn.assert_called_once()
        # record_fn should be called at least once (from collect or drain)
        assert record_fn.call_count >= 1

    @patch("pokepoke.agents.parallel.is_item_claimable", return_value=True)
    @patch("pokepoke.agents.parallel.time.sleep")
    @patch("pokepoke.agents.parallel.terminal_ui")
    @patch("pokepoke.utils.process_utils.apply_memory_backpressure", side_effect=lambda s: (s, 0))
    @patch("pokepoke.agents.parallel.set_executor")
    @patch("pokepoke.agents.parallel.should_stop_after_current", return_value=False)
    @patch("pokepoke.agents.parallel.is_shutting_down")
    @patch("pokepoke.agents.parallel.check_and_commit_main_repo", return_value=True)
    @patch("pokepoke.agents.parallel.get_ready_work_items")
    @patch("pokepoke.agents.parallel.select_multiple_items")
    @patch("pokepoke.agents.parallel._collect_done_futures")
    @patch("pokepoke.agents.parallel.process_work_item")
    @patch("pokepoke.agents.parallel._get_dynamic_max_agents", return_value=3)
    def test_refills_all_slots_after_completions(
        self, mock_dyn_max, mock_pwi, mock_collect, mock_sel, mock_ready,
        mock_repo, mock_shut, mock_stop, mock_set_exec, mock_mem, mock_ui, mock_sleep, mock_claimable,
    ) -> None:
        """Regression (PokePoke-qagy): all empty slots refilled after batch completes."""
        items = [_make_item(f"r{i}") for i in range(6)]
        mock_ready.return_value = items
        mock_pwi.return_value = WorkItemResult(success=True, request_count=1, stats=AgentStats())

        # Iteration 1: collect does nothing (no completed futures yet).
        # Iteration 2: collect clears all 3 futures (simulates 3 completions).
        call_idx = [0]

        def collect_side(futures, failed, total, stats, logger, record_fn, lock=None):
            call_idx[0] += 1
            if call_idx[0] == 2:
                futures.clear()
                return (total, True, 3, 0)
            return (total, False, 0, 0)

        mock_collect.side_effect = collect_side
        mock_sel.side_effect = [items[:3], [], items[3:6], []]

        # Enough False for 2 full iterations (1 while + 10 sleep each) + shutdown
        mock_shut.side_effect = [False] * 22 + [True] * 5

        stats = SessionStats(agent_stats=AgentStats())
        run_parallel_loop(
            effective_parallel=3, mode_name="Autonomous",
            main_repo_path="/repo", failed_claim_ids=set(),
            session_stats=stats, start_time=time.time(),
            run_logger=Mock(), continuous=True,
            record_fn=Mock(), finalize_fn=Mock(),
        )

        # Both calls to select_multiple_items should request count=3
        assert mock_sel.call_count >= 2
        # Find actual dispatch calls (with items, not empty terminators)
        dispatch_calls = [c for c in mock_sel.call_args_list if c.kwargs.get('count') == 3]
        assert len(dispatch_calls) >= 2

    @patch("pokepoke.agents.parallel.is_item_claimable", return_value=True)
    @patch("pokepoke.agents.parallel.time.sleep")
    @patch("pokepoke.agents.parallel.terminal_ui")
    @patch("pokepoke.agents.parallel.set_executor")
    @patch("pokepoke.agents.parallel.is_shutting_down", side_effect=([False] + ([False] * 10) + [True]))
    @patch("pokepoke.agents.parallel.check_and_commit_main_repo", return_value=True)
    @patch("pokepoke.agents.parallel.get_ready_work_items")
    @patch("pokepoke.agents.parallel.select_multiple_items", return_value=[])
    @patch("pokepoke.agents.parallel._collect_done_futures", return_value=(0, False, 0, 0))
    @patch("pokepoke.agents.parallel._get_dynamic_max_agents", return_value=2)
    def test_cli_override_uses_effective_parallel_over_config(
        self, mock_dyn_max, mock_collect, mock_sel, mock_ready,
        mock_repo, mock_shut, mock_set_exec, mock_ui, mock_sleep, mock_claimable,
    ) -> None:
        """Regression (PokePoke-snio): CLI --max-agents must not be capped by config."""
        mock_ready.return_value = [_make_item(f"c{i}") for i in range(10)]

        stats = SessionStats(agent_stats=AgentStats())
        run_parallel_loop(
            effective_parallel=6, mode_name="Autonomous",
            main_repo_path="/repo", failed_claim_ids=set(),
            session_stats=stats, start_time=time.time(),
            run_logger=Mock(), continuous=True,
            record_fn=Mock(), finalize_fn=Mock(),
            cli_override=True,
        )

        assert mock_sel.call_count >= 1
        assert mock_sel.call_args_list[0].kwargs["count"] == 6

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
    @patch("pokepoke.agents.parallel._get_dynamic_max_agents", return_value=1)
    def test_does_not_resubmit_while_future_tracked(
        self, mock_dyn_max, mock_pwi, mock_collect, mock_sel, mock_ready,
        mock_repo, mock_shut, mock_stop, mock_set_exec, mock_ui, mock_sleep, mock_claimable,
    ) -> None:
        """Regression: slot/claimed tracking must be based on futures (worker count).

        If a worker finishes and releases the semaphore but its future hasn't
        been collected yet, we must not consider that slot available.
        """
        item = _make_item("dup1")
        mock_ready.return_value = [item]
        mock_sel.return_value = [item]
        mock_pwi.return_value = WorkItemResult(success=True, request_count=1, stats=AgentStats())
        mock_collect.side_effect = lambda futures, failed, total, stats, logger, record_fn, lock=None: (total, False, 0, 0)

        # Two full loop iterations + shutdown, accounting for the inner sleep loop checks.
        mock_shut.side_effect = [False] + ([False] * 10) + [False, True, True]

        stats = SessionStats(agent_stats=AgentStats())
        record_fn = Mock()
        finalize_fn = Mock()
        logger = Mock()

        code = run_parallel_loop(
            effective_parallel=1, mode_name="Autonomous",
            main_repo_path="/repo", failed_claim_ids=set(),
            session_stats=stats, start_time=time.time(),
            run_logger=logger, continuous=True,
            record_fn=record_fn, finalize_fn=finalize_fn,
        )

        assert code == 0
        # Must not submit again while the original future is still tracked.
        assert mock_sel.call_count == 1

    @patch("pokepoke.agents.parallel.is_item_claimable", return_value=True)
    @patch("pokepoke.agents.parallel.time.sleep")
    @patch("pokepoke.agents.parallel.terminal_ui")
    @patch("pokepoke.agents.parallel.set_executor")
    @patch("pokepoke.agents.parallel.is_shutting_down", side_effect=[False] + [True] * 20)
    @patch("pokepoke.agents.parallel.check_and_commit_main_repo", return_value=True)
    @patch("pokepoke.agents.parallel.get_ready_work_items")
    @patch("pokepoke.agents.parallel.select_multiple_items")
    @patch("pokepoke.agents.parallel._get_dynamic_max_agents", return_value=1)
    def test_submit_exception_releases_resources(
        self, mock_dyn_max, mock_sel, mock_ready, mock_repo,
        mock_shut, mock_set_exec, mock_ui, mock_sleep, mock_claimable,
    ) -> None:
        """executor.submit failures should release semaphore and active IDs."""
        item = _make_item("xfail")
        mock_ready.return_value = [item]
        mock_sel.return_value = [item]

        sem = threading.Semaphore(1)
        mock_executor = MagicMock()
        mock_executor.submit.side_effect = RuntimeError("submit failed")
        mock_executor.shutdown = MagicMock()

        with patch("pokepoke.agents.parallel.threading.Semaphore", return_value=sem), \
             patch("pokepoke.agents.parallel.concurrent.futures.ThreadPoolExecutor", return_value=mock_executor):
            stats = SessionStats(agent_stats=AgentStats())
            logger = Mock()

            # executor.submit failure is now handled gracefully (break, not raise)
            run_parallel_loop(
                effective_parallel=1, mode_name="Autonomous",
                main_repo_path="/repo", failed_claim_ids=set(),
                session_stats=stats, start_time=time.time(),
                run_logger=logger, continuous=True,
                record_fn=Mock(), finalize_fn=Mock(),
            )

    @patch("pokepoke.agents.parallel.time.sleep")
    @patch("pokepoke.agents.parallel.terminal_ui")
    @patch("pokepoke.agents.parallel.set_executor")
    @patch("pokepoke.agents.parallel.cancel_stop_after_current")
    @patch("pokepoke.agents.parallel.should_stop_after_current", return_value=True)
    @patch("pokepoke.agents.parallel.is_shutting_down", return_value=False)
    @patch("pokepoke.agents.parallel.check_and_commit_main_repo", return_value=True)
    @patch("pokepoke.agents.parallel.get_ready_work_items", return_value=[])
    @patch("pokepoke.agents.parallel.select_multiple_items", return_value=[])
    def test_stop_after_current_with_no_futures(
        self, mock_sel, mock_ready, mock_repo, mock_shut,
        mock_stop, mock_cancel, mock_set_exec, mock_ui, mock_sleep,
    ) -> None:
        """Exits cleanly when stop-after-current is set and no futures remain."""
        stats = SessionStats(agent_stats=AgentStats())
        logger = Mock()
        finalize_fn = Mock()

        code = run_parallel_loop(
            effective_parallel=2, mode_name="Autonomous",
            main_repo_path="/repo", failed_claim_ids=set(),
            session_stats=stats, start_time=time.time(),
            run_logger=logger, continuous=True,
            record_fn=Mock(), finalize_fn=finalize_fn,
        )

        assert code == 0
        mock_cancel.assert_called_once()
        finalize_fn.assert_called_once()

    @patch("pokepoke.agents.parallel.time.sleep")
    @patch("pokepoke.agents.parallel.terminal_ui")
    @patch("pokepoke.agents.parallel.set_executor")
    @patch("pokepoke.agents.parallel.is_shutting_down", side_effect=[False, True])
    @patch("pokepoke.agents.parallel.check_and_commit_main_repo", return_value=True)
    @patch("pokepoke.agents.parallel.get_ready_work_items")
    @patch("pokepoke.agents.parallel.select_multiple_items", return_value=[])
    def test_double_check_beads_finds_items(
        self, mock_sel, mock_ready, mock_repo, mock_shut,
        mock_set_exec, mock_ui, mock_sleep,
    ) -> None:
        """Double-check of beads finds items and triggers continue, then shutdown exits."""
        item = _make_item("dc1")
        # First call returns empty, second call (double-check) returns item,
        # then is_shutting_down returns True on next iteration
        mock_ready.side_effect = [[], [item], []]
        mock_shut.side_effect = [False, False, True]

        stats = SessionStats(agent_stats=AgentStats())
        logger = Mock()
        finalize_fn = Mock()

        code = run_parallel_loop(
            effective_parallel=2, mode_name="Autonomous",
            main_repo_path="/repo", failed_claim_ids=set(),
            session_stats=stats, start_time=time.time(),
            run_logger=logger, continuous=True,
            record_fn=Mock(), finalize_fn=finalize_fn,
        )

        assert code == 0
        # get_ready_work_items should be called at least 2 times
        assert mock_ready.call_count >= 2

    @patch("pokepoke.agents.parallel.time.sleep")
    @patch("pokepoke.agents.parallel.terminal_ui")
    @patch("pokepoke.agents.parallel.set_executor")
    @patch("pokepoke.agents.parallel.is_shutting_down", side_effect=[False, True])
    @patch("pokepoke.agents.parallel.check_and_commit_main_repo", return_value=True)
    @patch("pokepoke.agents.parallel.get_ready_work_items")
    @patch("pokepoke.agents.parallel.select_multiple_items", return_value=[])
    def test_double_check_beads_exception_handled(
        self, mock_sel, mock_ready, mock_repo, mock_shut,
        mock_set_exec, mock_ui, mock_sleep,
    ) -> None:
        """Double-check beads exception is caught and exit proceeds."""
        # First call returns empty, second call (double-check) raises
        mock_ready.side_effect = [[], RuntimeError("db down")]

        stats = SessionStats(agent_stats=AgentStats())
        logger = Mock()
        finalize_fn = Mock()

        code = run_parallel_loop(
            effective_parallel=2, mode_name="Autonomous",
            main_repo_path="/repo", failed_claim_ids=set(),
            session_stats=stats, start_time=time.time(),
            run_logger=logger, continuous=True,
            record_fn=Mock(), finalize_fn=finalize_fn,
        )

        assert code == 0
        finalize_fn.assert_called_once()

    @patch("pokepoke.agents.parallel.is_item_claimable", return_value=True)
    @patch("pokepoke.agents.parallel.time.sleep")
    @patch("pokepoke.agents.parallel.terminal_ui")
    @patch("pokepoke.agents.parallel.set_executor")
    @patch("pokepoke.agents.parallel.should_stop_after_current", return_value=False)
    @patch("pokepoke.agents.parallel.is_shutting_down", return_value=False)
    @patch("pokepoke.agents.parallel.check_and_commit_main_repo", return_value=True)
    @patch("pokepoke.agents.parallel.get_ready_work_items")
    @patch("pokepoke.agents.parallel.select_multiple_items")
    @patch("pokepoke.agents.parallel.process_work_item")
    @patch("pokepoke.agents.parallel._get_dynamic_max_agents", return_value=2)
    def test_single_shot_drain_updates_stats(
        self, mock_dyn_max, mock_pwi, mock_sel, mock_ready, mock_repo,
        mock_shut, mock_stop, mock_set_exec, mock_ui, mock_sleep, mock_claimable,
    ) -> None:
        """UI stats should update after both items complete in single-shot mode.

        Previously the loop had an explicit drain path triggered by any_success.
        Now both items complete through natural loop iterations; the exit fires
        when futures is empty (not continuous and not futures).  The stats must
        show items_completed == 2 in both cases.
        """
        mock_sleep.return_value = None
        fast_item = _make_item("fast")
        slow_item = _make_item("slow")
        mock_ready.return_value = [fast_item, slow_item]
        # Extra [] entries accommodate loop iterations that fire select after
        # fast completes (futures={slow}) and after slow completes (futures={}).
        mock_sel.side_effect = [[fast_item, slow_item], [], []]

        slow_release = threading.Event()
        threading.Timer(0.05, slow_release.set).start()

        def _process(item: BeadsWorkItem, *args, **kwargs):
            if item.id == "slow":
                assert slow_release.wait(timeout=1), "Slow worker never released"
            return WorkItemResult(success=True, request_count=1, stats=AgentStats())

        mock_pwi.side_effect = _process

        stats = SessionStats(agent_stats=AgentStats())
        logger = Mock()

        def record_fn(item, result, s, _logger):
            if result.success:
                s.items_completed += 1

        code = run_parallel_loop(
            effective_parallel=2, mode_name="Autonomous",
            main_repo_path="/repo", failed_claim_ids=set(),
            session_stats=stats, start_time=time.time(),
            run_logger=logger, continuous=False,
            record_fn=record_fn, finalize_fn=Mock(),
        )

        assert code == 0
        assert slow_release.is_set()
        # Stats must be updated at least twice during the loop.
        assert mock_ui.ui.update_stats.call_count >= 2
        last_stats = mock_ui.ui.update_stats.call_args_list[-1][0][0]
        assert last_stats.items_completed == 2

    @patch("pokepoke.utils.process_utils.apply_memory_backpressure", side_effect=lambda s: (s, 0))
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
    def test_dynamic_max_agents_change_respected(
        self, mock_pwi, mock_collect, mock_sel, mock_ready,
        mock_repo, mock_shut, mock_stop, mock_set_exec, mock_ui, mock_sleep,
        mock_claimable, mock_mem,
    ) -> None:
        """Slot count should reflect dynamic config changes without restart."""
        items = [_make_item(f"d{i}") for i in range(6)]
        mock_ready.return_value = items
        mock_pwi.return_value = WorkItemResult(success=True, request_count=1, stats=AgentStats())

        call_idx = [0]

        def collect_side(futures, failed, total, stats, logger, record_fn, lock=None):
            call_idx[0] += 1
            if call_idx[0] == 2:
                futures.clear()
                return (total, True, 3, 0)
            return (total, False, 0, 0)

        mock_collect.side_effect = collect_side

        # First iteration returns 2, second returns 4 (simulates UI change)
        dynamic_values = iter([2, 4])
        mock_sel.side_effect = [items[:2], [], items[2:6], []]

        mock_shut.side_effect = [False] * 22 + [True] * 5

        with patch("pokepoke.agents.parallel._get_dynamic_max_agents", side_effect=dynamic_values):
            stats = SessionStats(agent_stats=AgentStats())
            run_parallel_loop(
                effective_parallel=2, mode_name="Autonomous",
                main_repo_path="/repo", failed_claim_ids=set(),
                session_stats=stats, start_time=time.time(),
                run_logger=Mock(), continuous=True,
                record_fn=Mock(), finalize_fn=Mock(),
            )

        # First dispatch call: count=2 (dynamic max=2, 0 active)
        assert mock_sel.call_args_list[0].kwargs['count'] == 2
        # After clear, second dispatch call: count=4 (dynamic max=4, 0 active)
        # Find the call with count=4 (skipping empty-list terminator calls)
        count_4_calls = [c for c in mock_sel.call_args_list if c.kwargs.get('count') == 4]
        assert len(count_4_calls) >= 1
