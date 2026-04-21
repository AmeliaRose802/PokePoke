"""Unit tests for orchestrator statistics tracking."""

from unittest.mock import Mock, patch

from pokepoke.orchestration.orchestrator import run_orchestrator
from pokepoke.types import WorkItemResult
from pokepoke.types_beads import BeadsWorkItem
from pokepoke.types_stats import AgentStats, ModelCompletionRecord
from tests.orchestration.conftest import make_orchestrator_mocks, make_work_item


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

    @patch('pokepoke.orchestration.session_lifecycle.run_periodic_maintenance')
    @patch('pokepoke.orchestration.session_lifecycle.increment_items_completed', return_value=1)
    @patch('pokepoke.orchestration.session_lifecycle.append_model_history_entry')
    @patch('pokepoke.orchestration.session_lifecycle.record_completion')
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

    @patch('pokepoke.orchestration.session_lifecycle.run_periodic_maintenance')
    @patch('pokepoke.orchestration.session_lifecycle.increment_items_completed')
    @patch('pokepoke.orchestration.session_lifecycle.append_model_history_entry')
    @patch('pokepoke.orchestration.session_lifecycle.record_completion')
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

    @patch('pokepoke.orchestration.session_lifecycle.run_periodic_maintenance')
    @patch('pokepoke.orchestration.session_lifecycle.increment_items_completed', return_value=1)
    @patch('pokepoke.orchestration.session_lifecycle.append_model_history_entry')
    @patch('pokepoke.orchestration.session_lifecycle.record_completion')
    def test_records_retries(self, mock_record, mock_hist, mock_inc, mock_maint):
        from pokepoke.orchestration.orchestrator import _record_item_result
        from pokepoke.types_stats import SessionStats

        stats = SessionStats(agent_stats=AgentStats())
        item = BeadsWorkItem(id="t1", title="T1", status="open", priority=1, issue_type="task")
        logger = Mock()

        _record_item_result(item, WorkItemResult(success=True, request_count=3, stats=AgentStats(), cleanup_agent_runs=2, gate_agent_runs=1), stats, logger)
        # 3 requests => 2 retries recorded
        assert stats.agent_stats.retries == 2
