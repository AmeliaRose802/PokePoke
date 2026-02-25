"""Integration-style tests for orchestrator.py.

Exercises real code paths in orchestrator.py, mocking only external I/O
(beads CLI, process_work_item, terminal_ui, filesystem, git operations).
"""

import time
from unittest.mock import patch, MagicMock


from pokepoke.types import (
    BeadsWorkItem, AgentStats, SessionStats, WorkItemResult,
    ModelCompletionRecord, BeadsStats,
)
from pokepoke.orchestrator import (
    _finalize_session,
    _record_item_result,
    run_orchestrator,
)


def _item(id: str = "orch-1") -> BeadsWorkItem:
    return BeadsWorkItem(id=id, title=f"Item {id}", status="ready",
                         priority=1, issue_type="task")


def _success_result(count: int = 1, stats: AgentStats | None = None,
                    model_completion: ModelCompletionRecord | None = None) -> WorkItemResult:
    return WorkItemResult(success=True, request_count=count, stats=stats,
                          model_completion=model_completion)


def _fail_result(count: int = 0) -> WorkItemResult:
    return WorkItemResult(success=False, request_count=count)


# ── _finalize_session ──────────────────────────────────────────────

class TestFinalizeSession:
    @patch("pokepoke.orchestrator.clear_terminal_banner")
    @patch("pokepoke.orchestrator.print_stats")
    @patch("pokepoke.orchestrator.terminal_ui")
    @patch("pokepoke.orchestrator.is_shutting_down", return_value=False)
    @patch("pokepoke.orchestrator.get_beads_stats")
    def test_collects_stats(self, mock_beads_stats, mock_shutdown,
                            mock_ui, mock_print_stats, mock_clear_banner):
        mock_beads_stats.return_value = BeadsStats(total_issues=10)
        stats = SessionStats(agent_stats=AgentStats())
        run_logger = MagicMock()

        _finalize_session(stats, time.time() - 100, 5, 10, run_logger)

        mock_print_stats.assert_called_once()
        run_logger.finalize.assert_called_once()
        mock_clear_banner.assert_called_once()
        assert stats.ending_beads_stats is not None

    @patch("pokepoke.orchestrator.clear_terminal_banner")
    @patch("pokepoke.orchestrator.print_stats")
    @patch("pokepoke.orchestrator.terminal_ui")
    @patch("pokepoke.orchestrator.is_shutting_down", return_value=True)
    def test_skips_stats_on_shutdown(self, mock_shutdown, mock_ui,
                                    mock_print_stats, mock_clear_banner):
        stats = SessionStats(agent_stats=AgentStats())
        run_logger = MagicMock()

        _finalize_session(stats, time.time(), 0, 0, run_logger)

        mock_print_stats.assert_called_once()
        assert stats.ending_beads_stats is None  # Skipped due to shutdown

    @patch("pokepoke.orchestrator.clear_terminal_banner")
    @patch("pokepoke.orchestrator.print_stats")
    @patch("pokepoke.orchestrator.terminal_ui")
    @patch("pokepoke.orchestrator.is_shutting_down", return_value=False)
    @patch("pokepoke.orchestrator.get_beads_stats", side_effect=KeyboardInterrupt)
    def test_handles_keyboard_interrupt(self, mock_beads_stats, mock_shutdown,
                                        mock_ui, mock_print_stats, mock_clear_banner):
        stats = SessionStats(agent_stats=AgentStats())
        run_logger = MagicMock()

        _finalize_session(stats, time.time(), 0, 0, run_logger)
        assert stats.ending_beads_stats is None


# ── _record_item_result ────────────────────────────────────────────

class TestRecordItemResult:
    @patch("pokepoke.orchestrator.run_periodic_maintenance")
    @patch("pokepoke.orchestrator.increment_items_completed", return_value=5)
    @patch("pokepoke.orchestrator.append_model_history_entry")
    @patch("pokepoke.orchestrator.record_completion")
    def test_successful_result(self, mock_record, mock_append,
                               mock_increment, mock_maintenance):
        stats = SessionStats(agent_stats=AgentStats())
        run_logger = MagicMock()
        item = _item()

        with patch("pokepoke.beads_item_stats_store.record_item_completed",
                    return_value={"total_created": 10, "total_completed": 5}):
            success, completed = _record_item_result(
                item, _success_result(), stats, run_logger,
            )

        assert success is True
        assert completed == 1  # items_completed incremented
        assert stats.work_agent_runs == 1

    @patch("pokepoke.orchestrator.run_periodic_maintenance")
    @patch("pokepoke.orchestrator.increment_items_completed", return_value=3)
    @patch("pokepoke.orchestrator.append_model_history_entry")
    @patch("pokepoke.orchestrator.record_completion")
    def test_result_with_model_completion(self, mock_record, mock_append,
                                          mock_increment, mock_maintenance):
        stats = SessionStats(agent_stats=AgentStats())
        run_logger = MagicMock()
        item = _item()
        mc = ModelCompletionRecord(item_id="orch-1", model="gpt-4",
                                    duration_seconds=60.0)
        result = _success_result(model_completion=mc)

        with patch("pokepoke.beads_item_stats_store.record_item_completed",
                    return_value={"total_created": 0, "total_completed": 0}):
            _record_item_result(item, result, stats, run_logger)

        mock_record.assert_called_once_with(mc)
        mock_append.assert_called_once()
        assert len(stats.model_completions) == 1

    def test_failed_result(self):
        stats = SessionStats(agent_stats=AgentStats())
        run_logger = MagicMock()
        item = _item()

        success, completed = _record_item_result(
            item, _fail_result(), stats, run_logger,
        )

        assert success is False
        assert completed == 0

    def test_retries_recorded(self):
        stats = SessionStats(agent_stats=AgentStats())
        run_logger = MagicMock()
        item = _item()
        result = WorkItemResult(success=False, request_count=3)

        _record_item_result(item, result, stats, run_logger)
        assert stats.agent_stats.retries == 2  # request_count - 1

    def test_agent_stats_accumulated(self):
        stats = SessionStats(agent_stats=AgentStats())
        run_logger = MagicMock()
        item = _item()
        agent_stats = AgentStats(input_tokens=500, output_tokens=200)

        with (
            patch("pokepoke.beads_item_stats_store.record_item_completed",
                  return_value={"total_created": 0, "total_completed": 0}),
            patch("pokepoke.orchestrator.increment_items_completed", return_value=1),
            patch("pokepoke.orchestrator.run_periodic_maintenance"),
        ):
            _record_item_result(
                item, _success_result(stats=agent_stats), stats, run_logger,
            )

        assert stats.agent_stats.input_tokens == 500
        assert stats.agent_stats.output_tokens == 200

    def test_cleanup_and_gate_runs_recorded(self):
        stats = SessionStats(agent_stats=AgentStats())
        run_logger = MagicMock()
        item = _item()
        result = WorkItemResult(success=False, request_count=1,
                                cleanup_agent_runs=3, gate_agent_runs=2)

        _record_item_result(item, result, stats, run_logger)
        assert stats.cleanup_agent_runs == 3
        assert stats.gate_agent_runs == 2


# ── run_orchestrator (sequential path) ─────────────────────────────

class TestRunOrchestrator:
    """Test run_orchestrator exercising real sequential loop logic."""

    @patch("pokepoke.orchestrator.unregister_shutdown_handlers")
    @patch("pokepoke.orchestrator.register_shutdown_handlers")
    @patch("pokepoke.orchestrator.terminal_ui")
    @patch("pokepoke.orchestrator.set_terminal_banner")
    @patch("pokepoke.orchestrator.clear_terminal_banner")
    @patch("pokepoke.orchestrator.format_work_item_banner", return_value="banner")
    @patch("pokepoke.orchestrator.initialize_agent_name", return_value="test-agent")
    @patch("pokepoke.orchestrator.get_agent_name", return_value="test-agent")
    @patch("pokepoke.orchestrator.load_config")
    @patch("pokepoke.orchestrator.get_beads_stats", return_value=BeadsStats())
    @patch("pokepoke.beads.get_failed_unassign_count", return_value=0)
    @patch("pokepoke.orchestrator.check_and_commit_main_repo", return_value=True)
    @patch("pokepoke.orchestrator.get_ready_work_items", return_value=[])
    @patch("pokepoke.orchestrator.select_work_item", return_value=None)
    @patch("pokepoke.orchestrator.is_shutting_down", return_value=False)
    @patch("pokepoke.orchestrator.print_stats")
    def test_no_work_items_exits_zero(
        self, mock_print, mock_shutdown, mock_select, mock_ready,
        mock_repo, mock_unassign_count, mock_beads_stats,
        mock_config, mock_agent, mock_init_agent,
        mock_banner_fmt, mock_clear_banner, mock_set_banner, mock_ui,
        mock_register, mock_unregister,
    ):
        mock_config.return_value = MagicMock(max_parallel_agents=1)
        with patch("pokepoke.beads_item_stats_backfill.backfill_from_beads_db",
                    return_value={"backfilled": 0}), patch("pokepoke.beads_item_stats_store.get_summary",
                    return_value={"total_created": 0, "total_completed": 0}):
            exit_code = run_orchestrator(interactive=False, continuous=False)
        assert exit_code == 0

    @patch("pokepoke.orchestrator.unregister_shutdown_handlers")
    @patch("pokepoke.orchestrator.register_shutdown_handlers")
    @patch("pokepoke.orchestrator.terminal_ui")
    @patch("pokepoke.orchestrator.set_terminal_banner")
    @patch("pokepoke.orchestrator.clear_terminal_banner")
    @patch("pokepoke.orchestrator.format_work_item_banner", return_value="banner")
    @patch("pokepoke.orchestrator.initialize_agent_name", return_value="test-agent")
    @patch("pokepoke.orchestrator.get_agent_name", return_value="test-agent")
    @patch("pokepoke.orchestrator.load_config")
    @patch("pokepoke.orchestrator.get_beads_stats", return_value=BeadsStats())
    @patch("pokepoke.beads.get_failed_unassign_count", return_value=0)
    @patch("pokepoke.orchestrator.check_and_commit_main_repo", return_value=False)
    @patch("pokepoke.orchestrator.is_shutting_down", return_value=False)
    @patch("pokepoke.orchestrator.print_stats")
    def test_repo_check_failure_returns_one(
        self, mock_print, mock_shutdown, mock_repo,
        mock_unassign_count, mock_beads_stats,
        mock_config, mock_agent, mock_init_agent,
        mock_banner_fmt, mock_clear_banner, mock_set_banner, mock_ui,
        mock_register, mock_unregister,
    ):
        mock_config.return_value = MagicMock(max_parallel_agents=1)
        with patch("pokepoke.beads_item_stats_backfill.backfill_from_beads_db",
                    return_value={"backfilled": 0}), patch("pokepoke.beads_item_stats_store.get_summary",
                    return_value={"total_created": 0, "total_completed": 0}):
            exit_code = run_orchestrator(interactive=False, continuous=False)
        assert exit_code == 1

    @patch("pokepoke.orchestrator.unregister_shutdown_handlers")
    @patch("pokepoke.orchestrator.register_shutdown_handlers")
    @patch("pokepoke.orchestrator.terminal_ui")
    @patch("pokepoke.orchestrator.set_terminal_banner")
    @patch("pokepoke.orchestrator.clear_terminal_banner")
    @patch("pokepoke.orchestrator.format_work_item_banner", return_value="banner")
    @patch("pokepoke.orchestrator.initialize_agent_name", return_value="test-agent")
    @patch("pokepoke.orchestrator.get_agent_name", return_value="test-agent")
    @patch("pokepoke.orchestrator.load_config")
    @patch("pokepoke.orchestrator.get_beads_stats", return_value=BeadsStats())
    @patch("pokepoke.beads.get_failed_unassign_count", return_value=0)
    @patch("pokepoke.orchestrator.check_and_commit_main_repo", return_value=True)
    @patch("pokepoke.orchestrator.get_ready_work_items")
    @patch("pokepoke.orchestrator.select_work_item")
    @patch("pokepoke.orchestrator.process_work_item")
    @patch("pokepoke.orchestrator.is_shutting_down", return_value=False)
    @patch("pokepoke.orchestrator.should_stop_after_current", return_value=False)
    @patch("pokepoke.orchestrator.print_stats")
    @patch("pokepoke.orchestrator.run_periodic_maintenance")
    @patch("pokepoke.orchestrator.increment_items_completed", return_value=1)
    def test_single_item_success(
        self, mock_increment, mock_maintenance, mock_print,
        mock_stop, mock_shutdown, mock_process, mock_select, mock_ready,
        mock_repo, mock_unassign_count, mock_beads_stats,
        mock_config, mock_agent, mock_init_agent,
        mock_banner_fmt, mock_clear_banner, mock_set_banner, mock_ui,
        mock_register, mock_unregister,
    ):
        item = _item()
        mock_config.return_value = MagicMock(max_parallel_agents=1)
        mock_ready.return_value = [item]
        mock_select.return_value = item
        mock_process.return_value = _success_result()

        with (
            patch("pokepoke.beads_item_stats_backfill.backfill_from_beads_db",
                  return_value={"backfilled": 0}),
            patch("pokepoke.beads_item_stats_store.get_summary",
                  return_value={"total_created": 0, "total_completed": 0}),
            patch("pokepoke.beads_item_stats_store.record_item_completed",
                  return_value={"total_created": 0, "total_completed": 1}),
        ):
            exit_code = run_orchestrator(interactive=False, continuous=False)
        assert exit_code == 0

    @patch("pokepoke.orchestrator.unregister_shutdown_handlers")
    @patch("pokepoke.orchestrator.register_shutdown_handlers")
    @patch("pokepoke.orchestrator.terminal_ui")
    @patch("pokepoke.orchestrator.set_terminal_banner")
    @patch("pokepoke.orchestrator.clear_terminal_banner")
    @patch("pokepoke.orchestrator.format_work_item_banner", return_value="banner")
    @patch("pokepoke.orchestrator.initialize_agent_name", return_value="test-agent")
    @patch("pokepoke.orchestrator.get_agent_name", return_value="test-agent")
    @patch("pokepoke.orchestrator.load_config")
    @patch("pokepoke.orchestrator.get_beads_stats", return_value=BeadsStats())
    @patch("pokepoke.beads.get_failed_unassign_count", return_value=0)
    @patch("pokepoke.orchestrator.check_and_commit_main_repo", return_value=True)
    @patch("pokepoke.orchestrator.get_ready_work_items")
    @patch("pokepoke.orchestrator.select_work_item")
    @patch("pokepoke.orchestrator.process_work_item")
    @patch("pokepoke.orchestrator.is_shutting_down", return_value=False)
    @patch("pokepoke.orchestrator.should_stop_after_current", return_value=False)
    @patch("pokepoke.orchestrator.print_stats")
    def test_single_item_failure(
        self, mock_print, mock_stop, mock_shutdown, mock_process,
        mock_select, mock_ready, mock_repo,
        mock_unassign_count, mock_beads_stats,
        mock_config, mock_agent, mock_init_agent,
        mock_banner_fmt, mock_clear_banner, mock_set_banner, mock_ui,
        mock_register, mock_unregister,
    ):
        item = _item()
        mock_config.return_value = MagicMock(max_parallel_agents=1)
        mock_ready.return_value = [item]
        mock_select.return_value = item
        mock_process.return_value = _fail_result()

        with patch("pokepoke.beads_item_stats_backfill.backfill_from_beads_db",
                    return_value={"backfilled": 0}), patch("pokepoke.beads_item_stats_store.get_summary",
                    return_value={"total_created": 0, "total_completed": 0}):
            exit_code = run_orchestrator(interactive=False, continuous=False)
        assert exit_code == 1

    @patch("pokepoke.orchestrator.unregister_shutdown_handlers")
    @patch("pokepoke.orchestrator.register_shutdown_handlers")
    @patch("pokepoke.orchestrator.terminal_ui")
    @patch("pokepoke.orchestrator.set_terminal_banner")
    @patch("pokepoke.orchestrator.clear_terminal_banner")
    @patch("pokepoke.orchestrator.format_work_item_banner", return_value="banner")
    @patch("pokepoke.orchestrator.initialize_agent_name", return_value="test-agent")
    @patch("pokepoke.orchestrator.get_agent_name", return_value="test-agent")
    @patch("pokepoke.orchestrator.load_config")
    @patch("pokepoke.orchestrator.get_beads_stats", return_value=BeadsStats())
    @patch("pokepoke.beads.get_failed_unassign_count", return_value=0)
    @patch("pokepoke.orchestrator.check_and_commit_main_repo", return_value=True)
    @patch("pokepoke.orchestrator.get_ready_work_items")
    @patch("pokepoke.orchestrator.select_work_item")
    @patch("pokepoke.orchestrator.process_work_item")
    @patch("pokepoke.orchestrator.is_shutting_down", return_value=False)
    @patch("pokepoke.orchestrator.should_stop_after_current", return_value=False)
    @patch("pokepoke.orchestrator.print_stats")
    def test_claim_failure_adds_to_skip(
        self, mock_print, mock_stop, mock_shutdown, mock_process,
        mock_select, mock_ready, mock_repo,
        mock_unassign_count, mock_beads_stats,
        mock_config, mock_agent, mock_init_agent,
        mock_banner_fmt, mock_clear_banner, mock_set_banner, mock_ui,
        mock_register, mock_unregister,
    ):
        item = _item()
        mock_config.return_value = MagicMock(max_parallel_agents=1)
        mock_ready.return_value = [item]
        mock_select.return_value = item
        # request_count=0 means claim failure
        mock_process.return_value = WorkItemResult(success=False, request_count=0)

        with patch("pokepoke.beads_item_stats_backfill.backfill_from_beads_db",
                    return_value={"backfilled": 0}), patch("pokepoke.beads_item_stats_store.get_summary",
                    return_value={"total_created": 0, "total_completed": 0}):
            exit_code = run_orchestrator(interactive=False, continuous=False)
        # Single-shot, failure -> exit 1
        assert exit_code == 1

    @patch("pokepoke.orchestrator.unregister_shutdown_handlers")
    @patch("pokepoke.orchestrator.register_shutdown_handlers")
    @patch("pokepoke.orchestrator.terminal_ui")
    @patch("pokepoke.orchestrator.set_terminal_banner")
    @patch("pokepoke.orchestrator.clear_terminal_banner")
    @patch("pokepoke.orchestrator.format_work_item_banner", return_value="banner")
    @patch("pokepoke.orchestrator.initialize_agent_name", return_value="test-agent")
    @patch("pokepoke.orchestrator.get_agent_name", return_value="test-agent")
    @patch("pokepoke.orchestrator.load_config")
    @patch("pokepoke.orchestrator.get_beads_stats", return_value=BeadsStats())
    @patch("pokepoke.beads.get_failed_unassign_count", return_value=2)
    @patch("pokepoke.beads.retry_failed_unassigns", return_value=2)
    @patch("pokepoke.orchestrator.check_and_commit_main_repo", return_value=True)
    @patch("pokepoke.orchestrator.get_ready_work_items", return_value=[])
    @patch("pokepoke.orchestrator.select_work_item", return_value=None)
    @patch("pokepoke.orchestrator.is_shutting_down", return_value=False)
    @patch("pokepoke.orchestrator.print_stats")
    def test_recovery_of_stuck_items(
        self, mock_print, mock_shutdown, mock_select, mock_ready,
        mock_repo, mock_retry, mock_unassign_count, mock_beads_stats,
        mock_config, mock_agent, mock_init_agent,
        mock_banner_fmt, mock_clear_banner, mock_set_banner, mock_ui,
        mock_register, mock_unregister,
    ):
        mock_config.return_value = MagicMock(max_parallel_agents=1)
        with patch("pokepoke.beads_item_stats_backfill.backfill_from_beads_db",
                    return_value={"backfilled": 0}), patch("pokepoke.beads_item_stats_store.get_summary",
                    return_value={"total_created": 0, "total_completed": 0}):
            exit_code = run_orchestrator(interactive=False, continuous=False)
        assert exit_code == 0
        mock_retry.assert_called_once()
