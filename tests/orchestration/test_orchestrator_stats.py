"""Unit tests for orchestrator statistics tracking."""

from unittest.mock import Mock, patch

from pokepoke.orchestration.orchestrator import run_orchestrator
from pokepoke.types import WorkItemResult
from pokepoke.types_beads import BeadsWorkItem
from pokepoke.types_stats import AgentStats, ModelCompletionRecord
from tests.orchestration.conftest import make_orchestrator_mocks, make_work_item


class TestAggregateStats:
    """Test aggregate_stats function."""

    def test_aggregate_stats(self) -> None:
        """Test aggregate_stats function."""
        from pokepoke.maintenance.maintenance import aggregate_stats
        from pokepoke.types_stats import AgentStats, SessionStats

        session_stats = SessionStats(agent_stats=AgentStats(
            wall_duration=10.0,
            api_duration=5.0,
            input_tokens=100,
            output_tokens=50,
            lines_added=10,
            lines_removed=5,
            premium_requests=1
        ))

        item_stats = AgentStats(
            wall_duration=5.0,
            api_duration=2.0,
            input_tokens=50,
            output_tokens=25,
            lines_added=5,
            lines_removed=2,
            premium_requests=1
        )

        aggregate_stats(session_stats, item_stats)

        assert session_stats.agent_stats.wall_duration == 15.0
        assert session_stats.agent_stats.api_duration == 7.0
        assert session_stats.agent_stats.input_tokens == 150
        assert session_stats.agent_stats.output_tokens == 75
        assert session_stats.agent_stats.lines_added == 15
        assert session_stats.agent_stats.lines_removed == 7
        assert session_stats.agent_stats.premium_requests == 2


class TestRunOrchestratorStatsTracking:
    """Test statistics tracking in run_orchestrator."""

    def test_model_completion_recorded(self) -> None:
        """Test model completion is recorded when present."""

        item = make_work_item()
        completion = ModelCompletionRecord(
            model="claude-opus-4.6",
            item_id="task-1",
            duration_seconds=10.0,
            gate_passed=True,
        )

        with make_orchestrator_mocks(
            items=[item], selected=item,
            include_maintenance=True, include_record=True,
            process_result=WorkItemResult(
                success=True, request_count=1, stats=AgentStats(),
                model_completion=completion,
            ),
        ) as mocks:
            result = run_orchestrator(interactive=False, continuous=False)

            assert result == 0
            mocks['record'].assert_called_once_with(completion)


class TestRunOrchestratorModelCompletion:
    """Test model completion recording in run_orchestrator."""

    def test_model_completion_recorded(self) -> None:
        """Test model completion is recorded when present."""
        from pokepoke.orchestration.orchestrator import run_orchestrator as run_orch

        item = make_work_item()
        completion = ModelCompletionRecord(
            model="claude-opus-4.6",
            item_id="task-1",
            duration_seconds=10.0,
            gate_passed=True,
        )

        with make_orchestrator_mocks(
            items=[item], selected=item,
            include_maintenance=True, include_record=True,
            process_result=WorkItemResult(
                success=True, request_count=1, stats=AgentStats(),
                model_completion=completion,
            ),
        ) as mocks:
            result = run_orch(interactive=False, continuous=False)
            assert result == 0
            mocks['record'].assert_called_once_with(completion)


class TestRecordItemResult:
    """Tests for _record_item_result function."""

    @patch('pokepoke.orchestration.orchestrator.run_periodic_maintenance')
    @patch('pokepoke.orchestration.orchestrator.increment_items_completed', return_value=1)
    @patch('pokepoke.orchestration.orchestrator.append_model_history_entry')
    @patch('pokepoke.orchestration.orchestrator.record_completion')
    def test_records_success(self, mock_record, mock_hist, mock_inc, mock_maint):
        from pokepoke.orchestration.orchestrator import _record_item_result
        from pokepoke.types_stats import SessionStats

        stats = SessionStats(agent_stats=AgentStats())
        item = BeadsWorkItem(id="t1", title="T1", status="open", priority=1, issue_type="task")
        logger = Mock()
        mc = ModelCompletionRecord(
            item_id="t1",
            model="m",
            duration_seconds=1.0,
        )

        success, completed = _record_item_result(
            item, WorkItemResult(success=True, request_count=1, stats=AgentStats(), gate_agent_runs=1, model_completion=mc), stats, logger,
        )

        assert success is True
        assert completed == 1
        mock_record.assert_called_once_with(mc)
        mock_maint.assert_called_once()

    @patch('pokepoke.orchestration.orchestrator.run_periodic_maintenance')
    @patch('pokepoke.orchestration.orchestrator.increment_items_completed')
    @patch('pokepoke.orchestration.orchestrator.append_model_history_entry')
    @patch('pokepoke.orchestration.orchestrator.record_completion')
    def test_records_failure(self, mock_record, mock_hist, mock_inc, mock_maint):
        from pokepoke.orchestration.orchestrator import _record_item_result
        from pokepoke.types_stats import SessionStats

        stats = SessionStats(agent_stats=AgentStats())
        item = BeadsWorkItem(id="t1", title="T1", status="open", priority=1, issue_type="task")
        logger = Mock()

        success, completed = _record_item_result(
            item, WorkItemResult(success=False, request_count=0), stats, logger,
        )

        assert success is False
        assert completed == 0
        mock_maint.assert_not_called()

    @patch('pokepoke.orchestration.orchestrator.run_periodic_maintenance')
    @patch('pokepoke.orchestration.orchestrator.increment_items_completed', return_value=1)
    @patch('pokepoke.orchestration.orchestrator.append_model_history_entry')
    @patch('pokepoke.orchestration.orchestrator.record_completion')
    def test_records_retries(self, mock_record, mock_hist, mock_inc, mock_maint):
        from pokepoke.orchestration.orchestrator import _record_item_result
        from pokepoke.types_stats import SessionStats

        stats = SessionStats(agent_stats=AgentStats())
        item = BeadsWorkItem(id="t1", title="T1", status="open", priority=1, issue_type="task")
        logger = Mock()

        _record_item_result(item, WorkItemResult(success=True, request_count=3, stats=AgentStats(), cleanup_agent_runs=2, gate_agent_runs=1), stats, logger)
        # 3 requests => 2 retries recorded
        assert stats.agent_stats.retries == 2
