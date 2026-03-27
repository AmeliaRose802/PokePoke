"""Unit tests for gated agents and parallel execution."""

from unittest.mock import ANY, Mock, call, patch

import pytest

from pokepoke.desktop import terminal_ui
from pokepoke.orchestration.orchestrator import run_orchestrator
from pokepoke.types import AgentStats, BeadsWorkItem, WorkItemResult
from tests.orchestration.conftest import PATCH_ORCH_IS_SHUTTING_DOWN, make_orchestrator_mocks, make_work_item


class TestRunOrchestratorBetaFirst:
    """Test beta_first flag in run_orchestrator."""

    def test_beta_first_runs_beta_tester(self) -> None:
        """Test beta tester runs at startup when run_beta_first=True."""
        with make_orchestrator_mocks() as mocks:
            beta_stats = AgentStats(
                wall_duration=10.0, api_duration=5.0,
                input_tokens=100, output_tokens=50,
                premium_requests=1
            )
            mocks['beta'].return_value = beta_stats

            result = run_orchestrator(interactive=False, continuous=False, run_beta_first=True)

            assert result == 0
            mocks['beta'].assert_called_once()

    def test_beta_first_none_stats(self) -> None:
        """Test beta tester returning None stats is handled."""
        with make_orchestrator_mocks():
            result = run_orchestrator(interactive=False, continuous=False, run_beta_first=True)

            assert result == 0

    def test_beta_first_with_stats(self) -> None:
        """Test beta_first flag runs beta tester and aggregates stats."""
        from pokepoke.orchestration.orchestrator import run_orchestrator as run_orch

        with make_orchestrator_mocks() as mocks:
            beta_stats = AgentStats(
                wall_duration=10.0, api_duration=5.0,
                input_tokens=100, output_tokens=50, premium_requests=1
            )
            mocks['beta'].return_value = beta_stats

            result = run_orch(interactive=False, continuous=False, run_beta_first=True)
            assert result == 0
            mocks['beta'].assert_called_once()


class TestParallelProcessItem:
    """Tests for _parallel_process_item."""

    @patch('pokepoke.agents.parallel.process_work_item')
    def test_releases_semaphore_on_success(self, mock_pwi):
        import threading

        from pokepoke.agents.parallel import _parallel_process_item

        mock_pwi.return_value = WorkItemResult(success=True, request_count=1)
        sem = threading.Semaphore(0)
        item = BeadsWorkItem(id="t1", title="T", status="o", priority=1, issue_type="task")
        logger = Mock()

        result = _parallel_process_item(item, logger, sem)

        assert result == WorkItemResult(success=True, request_count=1)
        # Semaphore should have been released (can acquire again)
        assert sem.acquire(blocking=False)

    @patch('pokepoke.agents.parallel.process_work_item', side_effect=RuntimeError("boom"))
    def test_releases_semaphore_on_exception(self, mock_pwi):
        import threading

        from pokepoke.agents.parallel import _parallel_process_item

        sem = threading.Semaphore(0)
        item = BeadsWorkItem(id="t1", title="T", status="o", priority=1, issue_type="task")
        logger = Mock()

        with pytest.raises(RuntimeError):
            _parallel_process_item(item, logger, sem)

        assert sem.acquire(blocking=False)


class TestMaxParallelAgentsConfig:
    """Tests for max_parallel_agents in ProjectConfig."""

    def test_default_value(self):
        from pokepoke.config import ProjectConfig
        config = ProjectConfig()
        assert config.max_parallel_agents == 1

    def test_from_dict_explicit(self):
        from pokepoke.config import ProjectConfig
        config = ProjectConfig.from_dict({"max_parallel_agents": 4})
        assert config.max_parallel_agents == 4

    def test_from_dict_missing(self):
        from pokepoke.config import ProjectConfig
        config = ProjectConfig.from_dict({})
        assert config.max_parallel_agents == 1

    def test_from_dict_clamped_to_one(self):
        from pokepoke.config import ProjectConfig
        config = ProjectConfig.from_dict({"max_parallel_agents": 0})
        assert config.max_parallel_agents == 1

    def test_from_dict_negative_clamped(self):
        from pokepoke.config import ProjectConfig
        config = ProjectConfig.from_dict({"max_parallel_agents": -5})
        assert config.max_parallel_agents == 1


class TestSingleAgentPanelRegistration:
    """Test that the single-agent orchestrator path registers agents in the panel."""

    def test_single_agent_registers_in_agents_panel(self) -> None:
        """Single-agent mode should call push_agent_status and agent_output_for."""
        item = make_work_item(id="task-42", title="Fix bug")

        with make_orchestrator_mocks(
            items=[item], selected=item, include_maintenance=True,
            process_result=WorkItemResult(success=True, request_count=1, stats=AgentStats()),
        ), patch.object(terminal_ui.ui, 'push_agent_status') as mock_push, \
                 patch.object(terminal_ui.ui, 'agent_output_for') as mock_output_for:
            mock_output_for.return_value.__enter__ = Mock(return_value=None)
            mock_output_for.return_value.__exit__ = Mock(return_value=False)

            with patch(PATCH_ORCH_IS_SHUTTING_DOWN, return_value=False):
                run_orchestrator(interactive=False, continuous=False)

            assert mock_push.call_count == 2
            assert mock_push.call_args_list[0] == call(
                "task-42", ANY, iteration=1, status="running",
                work_item_id="task-42", work_item_title="Fix bug", agent_type="work",
            )
            assert mock_push.call_args_list[1] == call(
                "task-42", ANY, iteration=1, status="success",
                work_item_id="task-42", work_item_title="Fix bug", agent_type="work",
            )
            mock_output_for.assert_called_once_with("task-42")

    def test_single_agent_registers_failed_status(self) -> None:
        """Single-agent mode should set 'failed' status when processing fails."""
        item = make_work_item(id="task-99", title="Failing task")

        with make_orchestrator_mocks(
            items=[item], selected=item, include_maintenance=True,
            process_result=WorkItemResult(success=False, request_count=1),
        ), patch.object(terminal_ui.ui, 'push_agent_status') as mock_push, \
                 patch.object(terminal_ui.ui, 'agent_output_for') as mock_output_for:
            mock_output_for.return_value.__enter__ = Mock(return_value=None)
            mock_output_for.return_value.__exit__ = Mock(return_value=False)

            with patch(PATCH_ORCH_IS_SHUTTING_DOWN, return_value=False):
                run_orchestrator(interactive=False, continuous=False)

            assert mock_push.call_count == 2
            assert mock_push.call_args_list[0] == call(
                "task-99", ANY, iteration=1, status="running",
                work_item_id="task-99", work_item_title="Failing task", agent_type="work",
            )
            assert mock_push.call_args_list[1] == call(
                "task-99", ANY, iteration=1, status="failed",
                work_item_id="task-99", work_item_title="Failing task", agent_type="work",
            )


class TestOrchestratorBackfillException:
    """Tests for backfill exception handling in orchestrator."""

    def test_backfill_exception_does_not_crash(self) -> None:
        """Covers lines 137-139: backfill_from_beads_db exception is caught."""
        with make_orchestrator_mocks():
            with patch('pokepoke.orchestration.orchestrator.backfill_from_beads_db',
                       side_effect=RuntimeError("backfill failed")):
                result = run_orchestrator(interactive=False, continuous=False)

            assert result == 0


class TestOrchestratorParallelModeForced:
    """Tests for parallel mode in interactive forcing sequential."""

    def test_interactive_parallel_forces_sequential(self) -> None:
        """Covers lines 174-175: parallel mode forced to 1 in interactive mode."""
        with make_orchestrator_mocks():
            result = run_orchestrator(
                interactive=True, continuous=False, max_parallel_agents=4
            )
            assert result == 0
