"""Unit tests for orchestrator module."""

from unittest.mock import Mock, patch

from pokepoke.orchestration.orchestrator import run_orchestrator
from pokepoke.orchestration.workflow import process_work_item, select_work_item
from pokepoke.types import AgentStats, BeadsWorkItem, CopilotResult, GateAgentResult, WorkItemResult
from tests.orchestration.conftest import (
    make_orchestrator_mocks,
    make_selection_mocks,
    make_work_item,
    make_workflow_mocks,
)


class TestSelectWorkItem:
    """Test work item selection logic."""

    def test_select_work_item_empty_list(self) -> None:
        """Test selecting from empty list returns None."""
        result = select_work_item([], interactive=False)

        assert result is None

    def test_select_work_item_autonomous_mode(self) -> None:
        """Test autonomous mode uses hierarchical selection."""
        item = make_work_item(id="task-1", title="Task")

        with make_selection_mocks(selected_item=item) as mocks:
            result = select_work_item([item], interactive=False)

            assert result is not None
            assert result.id == "task-1"
            mocks['select'].assert_called_once_with([item])

    @patch('builtins.input')
    def test_select_work_item_interactive_quit(self, mock_input: Mock) -> None:
        """Test interactive mode quit option."""
        item = make_work_item()
        mock_input.return_value = 'q'

        result = select_work_item([item], interactive=True)

        assert result is None

    @patch('builtins.input')
    def test_select_work_item_interactive_valid_selection(
        self,
        mock_input: Mock
    ) -> None:
        """Test interactive mode valid item selection."""
        item = make_work_item()
        mock_input.return_value = '1'

        result = select_work_item([item], interactive=True)

        assert result is not None
        assert result.id == "task-1"

    @patch('builtins.input')
    def test_select_work_item_interactive_invalid_then_valid(
        self,
        mock_input: Mock
    ) -> None:
        """Test interactive mode with invalid then valid input."""
        item = make_work_item()
        mock_input.side_effect = ['invalid', '1']

        result = select_work_item([item], interactive=True)

        assert result is not None
        assert result.id == "task-1"

    @patch('builtins.input')
    def test_select_work_item_interactive_out_of_range(
        self,
        mock_input: Mock
    ) -> None:
        """Test interactive mode with out of range input."""
        item = make_work_item()
        mock_input.side_effect = ['99', '1']

        result = select_work_item([item], interactive=True)

        assert result is not None
        assert result.id == "task-1"


class TestProcessWorkItem:
    """Test work item processing logic."""

    def test_process_work_item_success_no_parent(self) -> None:
        """Test successful processing without parent.

        Focus on behavior: successful work item should have success=True,
        request_count=1, and close_item should be called with the right args.
        Uses mock factory instead of 14 @patch decorators.
        """
        item = make_work_item(id="task-1", title="Task")

        with make_workflow_mocks(
            gate_success=True,
            copilot_success=True,
            has_parent=False,
            merge_success=True,
            close_success=True
        ) as mocks:
            result = process_work_item(item, interactive=True)

            # Assert on business logic outcomes, not internal function calls
            assert result.success is True
            assert result.request_count == 1
            assert result.cleanup_agent_runs == 0
            # Still verify close was called with correct args (this is important behavior)
            mocks['close'].assert_called_once_with("task-1", "Completed by PokePoke orchestrator (agent did not close)")

    def test_process_work_item_success_with_parent(self) -> None:
        """Test successful processing with parent closure.

        When an item has a parent, the parent should also be checked for closure.
        """
        item = make_work_item(id="task-1", title="Task")

        with make_workflow_mocks(
            gate_success=True,
            copilot_success=True,
            has_parent=True,
            merge_success=True,
            close_success=True
        ) as mocks:
            result = process_work_item(item, interactive=True)

            assert result.success is True
            mocks['close_parent'].assert_called_once()

    @patch('pokepoke.orchestration.workflow.run_gate_agent')
    @patch('subprocess.run')
    @patch('pokepoke.orchestration.workflow.cleanup_worktree')
    @patch('pokepoke.worktrees.worktree_merge_handler.perform_worktree_merge')
    @patch('pokepoke.git.git_operations.has_uncommitted_changes')
    @patch('os.chdir')
    @patch('os.getcwd')
    @patch('pokepoke.orchestration.workflow.setup_worktree')
    @patch('pokepoke.orchestration.workflow.assign_and_sync_item', return_value=True)
    @patch('pokepoke.orchestration.workflow.invoke_copilot')
    def test_process_work_item_failure(
        self,
        mock_invoke: Mock,
        mock_assign: Mock,
        mock_create_wt: Mock,
        mock_getcwd: Mock,
        mock_chdir: Mock,
        mock_uncommitted: Mock,
        mock_perform: Mock,
        mock_cleanup: Mock,
        mock_subprocess: Mock,
        mock_gate_agent: Mock
    ) -> None:
        """Test processing failure - copilot fails and worktree is cleaned up."""
        item = BeadsWorkItem(
            id="task-1",
            title="Task",
            description="",
            status="open",
            priority=1,
            issue_type="task"
        )
        mock_create_wt.return_value = '/tmp/worktree'
        mock_getcwd.return_value = '/original'
        mock_uncommitted.return_value = False
        mock_perform.return_value = (True, True)
        mock_gate_agent.return_value = GateAgentResult(success=True, reason="Gate passed")

        # Copilot fails
        mock_invoke.return_value = CopilotResult(
            work_item_id="task-1",
            success=False,
            error="Something went wrong",
            attempt_count=1
        )

        # Mock subprocess for git and bd commands
        def subprocess_side_effect(*args, **kwargs):
            cmd = args[0] if args else kwargs.get('args', [])
            if isinstance(cmd, list) and len(cmd) > 0:
                if 'rev-list' in cmd:
                    return Mock(stdout="1\n", returncode=0)
                elif 'status' in cmd and '--porcelain' in cmd:
                    return Mock(stdout="", returncode=0)
                elif cmd[0] == 'bd':
                    if 'show' in cmd:
                        return Mock(stdout='[{"id": "task-1", "title": "Test", "status": "open", "priority": 1, "issue_type": "task"}]', returncode=0)
                    elif 'sync' in cmd or 'update' in cmd:
                        return Mock(stdout="", stderr="", returncode=0)
            return Mock(stdout="", returncode=0)
        mock_subprocess.side_effect = subprocess_side_effect

        result = process_work_item(item, interactive=False)

        assert result.success is False
        # Default max_copilot_failure_retries=2, so 3 total attempts
        assert result.request_count == 3  # 1 initial + 2 retries
        assert result.stats is not None
        assert result.model_completion is not None
        assert result.model_completion.cost == 0.0
        assert result.cleanup_agent_runs == 0
        assert mock_invoke.call_count == 3

    @patch('pokepoke.orchestration.workflow.run_gate_agent')
    @patch('subprocess.run')
    @patch('pokepoke.worktrees.worktrees.cleanup_worktree')
    @patch('pokepoke.orchestration.workflow.invoke_copilot')
    @patch('pokepoke.orchestration.workflow.assign_and_sync_item', return_value=True)
    @patch('pokepoke.orchestration.workflow.setup_worktree')
    def test_process_work_item_preserves_worktree_on_unhandled_exception(
        self,
        mock_create_wt: Mock,
        mock_assign: Mock,
        mock_invoke: Mock,
        mock_cleanup: Mock,
        mock_subprocess: Mock,
        mock_gate_agent: Mock
    ) -> None:
        """Test that worktree is preserved when an unhandled exception occurs."""
        item = BeadsWorkItem(
            id="task-1",
            title="Task",
            description="",
            status="open",
            priority=1,
            issue_type="task"
        )
        mock_create_wt.return_value = '/tmp/worktree'

        # Mock subprocess for bd assign/sync
        def subprocess_side_effect(*args, **kwargs):
            cmd = args[0] if args else kwargs.get('args', [])
            if isinstance(cmd, list) and len(cmd) > 0 and cmd[0] == 'bd':
                if 'show' in cmd:
                    return Mock(stdout='[{"id": "task-1", "title": "Test", "status": "open", "priority": 1, "issue_type": "task"}]', returncode=0)
                elif 'sync' in cmd or 'update' in cmd:
                    return Mock(stdout="", stderr="", returncode=0)
            return Mock(stdout="", returncode=0)
        mock_subprocess.side_effect = subprocess_side_effect

        # Copilot raises an unhandled exception
        mock_invoke.side_effect = RuntimeError("Unexpected crash")

        import contextlib

        with contextlib.suppress(RuntimeError):
            process_work_item(item, interactive=False)

        # Worktree should NOT be cleaned up — preserved for retry reuse
        mock_cleanup.assert_not_called()


class TestRunOrchestrator:
    """Test orchestrator main loop."""

    def test_run_orchestrator_sets_agent_name(self) -> None:
        """Test that orchestrator initializes and sets AGENT_NAME env var."""
        import os

        with make_orchestrator_mocks(include_agent_name=True) as mocks:
            test_agent_name = "pokepoke_test_agent_1234"
            mocks['init_agent_name'].return_value = test_agent_name

            result = run_orchestrator(interactive=False, continuous=False)

            mocks['init_agent_name'].assert_called_once_with(custom_name=None)
            assert os.environ.get('AGENT_NAME') == test_agent_name
            assert result == 0

    def test_run_orchestrator_respects_custom_agent_name(self) -> None:
        """Test that orchestrator uses custom agent name when provided."""
        import os

        custom_agent_name = "Janitor"

        with make_orchestrator_mocks(include_agent_name=True) as mocks:
            mocks['init_agent_name'].return_value = custom_agent_name

            result = run_orchestrator(
                interactive=False,
                continuous=False,
                agent_name_override=custom_agent_name
            )

            mocks['init_agent_name'].assert_called_once_with(custom_name=custom_agent_name)
            assert os.environ.get('AGENT_NAME') == custom_agent_name
            assert result == 0

    def test_run_orchestrator_no_items(self) -> None:
        """Test orchestrator with no ready items."""
        with make_orchestrator_mocks() as mocks:
            result = run_orchestrator(interactive=False, continuous=False)

            assert result == 0
            mocks['process'].assert_not_called()

    def test_run_orchestrator_single_shot_success(self) -> None:
        """Test single-shot mode with successful processing."""
        item = make_work_item()

        with make_orchestrator_mocks(
            items=[item], selected=item, include_maintenance=True,
        ) as mocks:
            result = run_orchestrator(interactive=False, continuous=False)

            assert result == 0
            mocks['process'].assert_called_once()

    def test_run_orchestrator_single_shot_failure(self) -> None:
        """Test single-shot mode with processing failure."""
        item = make_work_item()

        with make_orchestrator_mocks(
            items=[item], selected=item,
            process_result=WorkItemResult(success=False, request_count=1, stats=AgentStats()),
        ):
            result = run_orchestrator(interactive=False, continuous=False)

            assert result == 1

    def test_run_orchestrator_continuous_quit(self) -> None:
        """Test continuous interactive mode with user quit."""
        item = make_work_item()

        with make_orchestrator_mocks(
            items=[item], selected=item,
            include_maintenance=True, include_input=True,
        ) as mocks:
            mocks['input'].return_value = 'n'  # Don't continue

            result = run_orchestrator(interactive=True, continuous=True)

            assert result == 0
            mocks['process'].assert_called_once()

    def test_run_orchestrator_exception_handling(self) -> None:
        """Test orchestrator handles exceptions."""
        with make_orchestrator_mocks() as mocks:
            mocks['get_items'].side_effect = Exception("Database error")

            result = run_orchestrator(interactive=False, continuous=False)

            assert result == 1

    def test_run_orchestrator_shutdown_exit(self) -> None:
        """Test orchestrator exits cleanly when shutdown is requested."""
        from pokepoke.utils.shutdown import request_shutdown, reset

        with make_orchestrator_mocks():
            request_shutdown()
            try:
                result = run_orchestrator(interactive=False, continuous=True)
                assert result == 0
            finally:
                reset()


class TestRunOrchestratorContinuousMode:
    """Test continuous mode scenarios."""

    def test_continuous_autonomous_multiple_items(self) -> None:
        """Test continuous autonomous mode processes multiple items."""
        from pokepoke.orchestration.orchestrator import run_orchestrator

        item1 = make_work_item(id="task-1", title="Task 1")
        item2 = make_work_item(id="task-2", title="Task 2")

        with make_orchestrator_mocks(
            include_check_repo=True, include_stats=True,
            include_sleep=True, include_maintenance=True,
        ) as mocks:
            mocks['get_items'].side_effect = [[item1], [item2], []]
            mocks['select'].side_effect = [item1, item2, None]
            mocks['process'].side_effect = [
                WorkItemResult(success=True, request_count=1, stats=AgentStats()),
                WorkItemResult(success=True, request_count=1, stats=AgentStats())
            ]

            result = run_orchestrator(interactive=False, continuous=True)

            assert result == 0
            assert mocks['process'].call_count == 2

    def test_maintenance_agents_triggered(self) -> None:
        """Test maintenance agents are triggered at correct intervals."""
        from pokepoke.orchestration.orchestrator import run_orchestrator

        items = [make_work_item(id=f"task-{i}", title=f"Task {i}") for i in range(11)]

        with make_orchestrator_mocks(
            include_check_repo=True, include_stats=True,
            include_sleep=True, include_maintenance=True,
        ) as mocks:
            mocks['get_items'].side_effect = [[items[i]] for i in range(10)] + [[]]
            mocks['select'].side_effect = [*items[:10], None]
            mocks['process'].return_value = WorkItemResult(success=True, request_count=1, stats=AgentStats())

            result = run_orchestrator(interactive=False, continuous=True)

            assert result == 0
            # run_periodic_maintenance is called once per successful item
            assert mocks['maintenance'].call_count == 10  # Called once per item

    def test_continuous_interactive_loop(self) -> None:
        """Test continuous interactive mode with user continuation prompt."""
        from pokepoke.orchestration.orchestrator import run_orchestrator

        item = make_work_item(id="task-1", title="Task 1")

        with make_orchestrator_mocks(
            items=[item], selected=item,
            include_check_repo=True, include_stats=True,
            include_input=True, include_maintenance=True,
        ) as mocks:
            mocks['input'].return_value = 'n'  # Don't continue

            result = run_orchestrator(interactive=True, continuous=True)

            assert result == 0
            mocks['input'].assert_called_once()


class TestFinalizeSession:
    """Test _finalize_session function."""

    @patch('pokepoke.orchestration.orchestrator.clear_terminal_banner')
    @patch('pokepoke.orchestration.orchestrator.print_stats')
    @patch('pokepoke.orchestration.orchestrator.get_beads_stats')
    @patch('pokepoke.orchestration.orchestrator.time')
    def test_finalize_session_success(
        self, mock_time: Mock, mock_stats: Mock,
        mock_print: Mock, mock_clear: Mock
    ) -> None:
        """Test finalize collects stats, prints, and clears banner."""
        import tempfile

        from pokepoke.orchestration.orchestrator import _finalize_session
        from pokepoke.types import AgentStats, SessionStats
        from pokepoke.utils.logging_utils import RunLogger

        mock_time.time.return_value = 100.0
        mock_stats.return_value = {"items": 5}

        session = SessionStats(agent_stats=AgentStats())
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = RunLogger(base_dir=tmpdir)
            try:
                _finalize_session(session, 90.0, 3, 5, logger)
            finally:
                logger.close()

        assert session.ending_beads_stats == {"items": 5}
        assert mock_print.called
        mock_clear.assert_called_once()

    @patch('pokepoke.orchestration.orchestrator.clear_terminal_banner')
    @patch('pokepoke.orchestration.orchestrator.print_stats')
    @patch('pokepoke.orchestration.orchestrator.get_beads_stats')
    @patch('pokepoke.orchestration.orchestrator.time')
    def test_finalize_session_keyboard_interrupt(
        self, mock_time: Mock, mock_stats: Mock,
        mock_print: Mock, mock_clear: Mock
    ) -> None:
        """Test finalize handles KeyboardInterrupt during stats collection."""
        import tempfile

        from pokepoke.orchestration.orchestrator import _finalize_session
        from pokepoke.types import AgentStats, SessionStats
        from pokepoke.utils.logging_utils import RunLogger

        mock_time.time.return_value = 100.0
        mock_stats.side_effect = KeyboardInterrupt

        session = SessionStats(agent_stats=AgentStats())
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = RunLogger(base_dir=tmpdir)
            try:
                _finalize_session(session, 90.0, 0, 0, logger)
            finally:
                logger.close()

        assert session.ending_beads_stats is None
        assert mock_print.called
        mock_clear.assert_called_once()

    @patch('pokepoke.orchestration.orchestrator.is_shutting_down', return_value=True)
    @patch('pokepoke.orchestration.orchestrator.clear_terminal_banner')
    @patch('pokepoke.orchestration.orchestrator.print_stats')
    @patch('pokepoke.orchestration.orchestrator.get_beads_stats')
    @patch('pokepoke.orchestration.orchestrator.time')
    def test_finalize_session_skips_stats_collection_during_shutdown(
        self, mock_time: Mock, mock_stats: Mock,
        mock_print: Mock, mock_clear: Mock,
        _mock_is_shutting_down: Mock,
    ) -> None:
        """During shutdown, finalize should avoid stats collection to exit promptly."""
        import tempfile

        from pokepoke.orchestration.orchestrator import _finalize_session
        from pokepoke.types import AgentStats, SessionStats
        from pokepoke.utils.logging_utils import RunLogger

        mock_time.time.return_value = 100.0
        mock_stats.return_value = {"items": 5}

        session = SessionStats(agent_stats=AgentStats())
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = RunLogger(base_dir=tmpdir)
            try:
                _finalize_session(session, 90.0, 0, 0, logger)
            finally:
                logger.close()

        assert session.ending_beads_stats is None
        mock_stats.assert_not_called()
        assert mock_print.called
        mock_clear.assert_called_once()


class TestRunOrchestratorFailedClaims:
    """Test failed claim tracking in run_orchestrator."""

    def test_failed_claim_added_to_skip_list(self) -> None:
        """Test failed claims (0 requests) are tracked to avoid retrying."""
        item = make_work_item(id="task-1", title="Task 1")

        with make_orchestrator_mocks(
            include_check_repo=True, include_stats=True,
            include_sleep=True, include_maintenance=True,
        ) as mocks:
            # First iteration: claim fails (success=False, requests=0)
            # Second iteration: no items available
            mocks['get_items'].side_effect = [[item], []]
            mocks['select'].side_effect = [item, None]
            mocks['process'].return_value = WorkItemResult(success=False, request_count=0)

            result = run_orchestrator(interactive=False, continuous=True)

            assert result == 0
            # Verify skip_ids was passed with the failed item
            second_select_call = mocks['select'].call_args_list[1]
            assert 'task-1' in second_select_call[1].get('skip_ids', set())

    def test_success_clears_skip_list(self) -> None:
        """Test successful processing clears the skip list."""
        item1 = make_work_item(id="task-1", title="Task 1")
        item2 = make_work_item(id="task-2", title="Task 2")

        with make_orchestrator_mocks(
            include_check_repo=True, include_stats=True,
            include_sleep=True, include_maintenance=True,
        ) as mocks:
            mocks['get_items'].side_effect = [[item1], [item2], []]
            mocks['select'].side_effect = [item1, item2, None]
            # First fails claim, second succeeds
            mocks['process'].side_effect = [
                WorkItemResult(success=False, request_count=0),
                WorkItemResult(success=True, request_count=1, stats=AgentStats())
            ]

            result = run_orchestrator(interactive=False, continuous=True)

            assert result == 0


class TestRunOrchestratorContinuousAutonomousSleep:
    """Test continuous autonomous mode sleep behavior."""

    def test_autonomous_continuous_sleeps_between_items(self) -> None:
        """Test autonomous continuous mode sleeps 5s between items."""
        item = make_work_item(id="task-1", title="Task 1")

        with make_orchestrator_mocks(
            include_check_repo=True, include_stats=True,
            include_sleep=True, include_maintenance=True,
        ) as mocks:
            mocks['get_items'].side_effect = [[item], []]
            mocks['select'].side_effect = [item, None]

            result = run_orchestrator(interactive=False, continuous=True)

            assert result == 0
            # Sleep is called in 0.5s increments (10 times for 5s total)
            assert mocks['sleep'].call_count >= 1


class TestRunOrchestratorRetries:
    """Test retry counting and stats aggregation."""

    def test_retries_tracked_when_multiple_requests(self) -> None:
        """Test retries are counted when request_count > 1."""
        item = make_work_item()

        with make_orchestrator_mocks(
            items=[item], selected=item, include_maintenance=True,
            process_result=WorkItemResult(
                success=True, request_count=3, stats=AgentStats(),
                cleanup_agent_runs=1, gate_agent_runs=2,
            ),
        ):
            result = run_orchestrator(interactive=False, continuous=False)

            assert result == 0


class TestRunOrchestratorKeyboardInterrupt:
    """Test KeyboardInterrupt handling in run_orchestrator."""

    def test_keyboard_interrupt_during_loop(self) -> None:
        """Test graceful shutdown on KeyboardInterrupt."""
        with make_orchestrator_mocks(include_check_repo=True) as mocks:
            mocks['get_items'].side_effect = KeyboardInterrupt

            result = run_orchestrator(interactive=False, continuous=False)

            assert result == 0


# ============================================================================
# Tests using pokepoke.orchestration.orchestrator for worktree coverage
# ============================================================================

class TestRunOrchestratorWorktreeCoverage:
    """Tests that import from pokepoke.orchestration.orchestrator to contribute to worktree coverage."""

    def setup_method(self) -> None:
        """Reset shutdown state before each test."""
        from pokepoke.utils.shutdown import reset
        reset()

    def test_no_items_returns_zero(self) -> None:
        """Test orchestrator returns 0 when no items available."""
        from pokepoke.orchestration.orchestrator import run_orchestrator as run_orch

        with make_orchestrator_mocks():
            result = run_orch(interactive=False, continuous=False)
            assert result == 0

    def test_single_shot_success(self) -> None:
        """Test single-shot success returns 0."""
        from pokepoke.orchestration.orchestrator import run_orchestrator as run_orch

        item = make_work_item()

        with make_orchestrator_mocks(
            items=[item], selected=item, include_maintenance=True,
        ):
            result = run_orch(interactive=False, continuous=False)
            assert result == 0

    def test_single_shot_failure_returns_one(self) -> None:
        """Test single-shot failure returns 1."""
        from pokepoke.orchestration.orchestrator import run_orchestrator as run_orch

        item = make_work_item()

        with make_orchestrator_mocks(
            items=[item], selected=item,
            process_result=WorkItemResult(success=False, request_count=1),
        ):
            result = run_orch(interactive=False, continuous=False)
            assert result == 1

    def test_model_completion_recorded(self) -> None:
        """Test model completion is recorded when present."""
        from pokepoke.orchestration.orchestrator import run_orchestrator as run_orch
        from pokepoke.types import ModelCompletionRecord

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

    def test_retries_counted(self) -> None:
        """Test that multiple requests are tracked as retries."""
        from pokepoke.orchestration.orchestrator import run_orchestrator as run_orch

        item = make_work_item()

        with make_orchestrator_mocks(
            items=[item], selected=item, include_maintenance=True,
            process_result=WorkItemResult(
                success=True, request_count=3, stats=AgentStats(),
                cleanup_agent_runs=1, gate_agent_runs=2,
            ),
        ):
            result = run_orch(interactive=False, continuous=False)
            assert result == 0

    def test_exception_returns_one(self) -> None:
        """Test exception handling returns 1."""
        from pokepoke.orchestration.orchestrator import run_orchestrator as run_orch

        with make_orchestrator_mocks(include_check_repo=True) as mocks:
            mocks['get_items'].side_effect = RuntimeError("DB error")

            result = run_orch(interactive=False, continuous=False)
            assert result == 1

    def test_keyboard_interrupt_returns_zero(self) -> None:
        """Test KeyboardInterrupt returns 0."""
        from pokepoke.orchestration.orchestrator import run_orchestrator as run_orch

        with make_orchestrator_mocks(include_check_repo=True) as mocks:
            mocks['get_items'].side_effect = KeyboardInterrupt

            result = run_orch(interactive=False, continuous=False)
            assert result == 0

    def test_repo_check_failure(self) -> None:
        """Test repo check failure returns 1."""
        from pokepoke.orchestration.orchestrator import run_orchestrator as run_orch

        with make_orchestrator_mocks(include_check_repo=True) as mocks:
            mocks['check_repo'].return_value = False

            result = run_orch(interactive=False, continuous=False)
            assert result == 1

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

    def test_beta_first_none_stats(self) -> None:
        """Test beta_first with None stats is handled."""
        from pokepoke.orchestration.orchestrator import run_orchestrator as run_orch

        with make_orchestrator_mocks():
            result = run_orch(interactive=False, continuous=False, run_beta_first=True)
            assert result == 0

    def test_continuous_autonomous_processes_multiple_items(self) -> None:
        """Test continuous autonomous mode processes multiple items."""
        from pokepoke.orchestration.orchestrator import run_orchestrator as run_orch

        item1 = make_work_item(id="task-1", title="Task 1")
        item2 = make_work_item(id="task-2", title="Task 2")

        with make_orchestrator_mocks(
            include_check_repo=True, include_stats=True,
            include_sleep=True, include_maintenance=True,
        ) as mocks:
            mocks['get_items'].side_effect = [[item1], [item2], []]
            mocks['select'].side_effect = [item1, item2, None]
            mocks['process'].side_effect = [
                WorkItemResult(success=True, request_count=1, stats=AgentStats()),
                WorkItemResult(success=True, request_count=1, stats=AgentStats())
            ]

            result = run_orch(interactive=False, continuous=True)
            assert result == 0
            assert mocks['process'].call_count == 2

    def test_failed_claim_tracked(self) -> None:
        """Test failed claims are added to skip list."""
        from pokepoke.orchestration.orchestrator import run_orchestrator as run_orch

        item = make_work_item(id="task-1", title="Task 1")

        with make_orchestrator_mocks(
            include_check_repo=True, include_stats=True,
            include_sleep=True, include_maintenance=True,
        ) as mocks:
            mocks['get_items'].side_effect = [[item], []]
            mocks['select'].side_effect = [item, None]
            mocks['process'].return_value = WorkItemResult(success=False, request_count=0)

            result = run_orch(interactive=False, continuous=True)
            assert result == 0

    @patch('pokepoke.agents.agent_runner.run_worktree_cleanup')
    @patch('pokepoke.orchestration.orchestrator.run_beta_tester')
    @patch('pokepoke.orchestration.orchestrator.run_periodic_maintenance')
    @patch('builtins.input')
    @patch('pokepoke.orchestration.orchestrator.get_beads_stats')
    @patch('pokepoke.orchestration.orchestrator.process_work_item')
    @patch('pokepoke.orchestration.orchestrator.select_work_item')
    @patch('pokepoke.orchestration.orchestrator.get_ready_work_items')
    @patch('pokepoke.orchestration.orchestrator.check_and_commit_main_repo')
    def test_interactive_continuous_quit(
        self, mock_check_repo: Mock, mock_get_items: Mock,
        mock_select: Mock, mock_process: Mock,
        mock_stats: Mock, mock_input: Mock,
        mock_maintenance: Mock, mock_beta: Mock,
        mock_cleanup: Mock
    ) -> None:
        """Test interactive continuous mode with user quitting."""
        from pokepoke.orchestration.orchestrator import run_orchestrator as run_orch

        mock_check_repo.return_value = True
        mock_stats.return_value = {}
        mock_maintenance.return_value = None
        mock_beta.return_value = None

        item = BeadsWorkItem(
            id="task-1", title="Task 1", description="",
            status="open", priority=1, issue_type="task"
        )

        mock_get_items.return_value = [item]
        mock_select.return_value = item
        mock_process.return_value = WorkItemResult(success=True, request_count=1, stats=AgentStats())
        mock_input.return_value = 'n'

        result = run_orch(interactive=True, continuous=True)
        assert result == 0

    @patch('subprocess.run')
    @patch('pokepoke.agents.agent_runner.run_worktree_cleanup')
    @patch('pokepoke.orchestration.orchestrator.run_beta_tester')
    @patch('pokepoke.orchestration.orchestrator.is_shutting_down', return_value=True)
    def test_shutdown_during_loop(
        self, mock_shutdown: Mock,
        mock_beta: Mock, mock_cleanup: Mock, mock_subprocess: Mock
    ) -> None:
        """Test shutdown during loop returns 0."""
        from pokepoke.orchestration.orchestrator import run_orchestrator as run_orch

        mock_subprocess.return_value = Mock(stdout="", returncode=0)
        mock_beta.return_value = None

        result = run_orch(interactive=False, continuous=True)
        assert result == 0


class TestSelectMultipleItems:
    """Tests for select_multiple_items helper."""

    @patch('pokepoke.orchestration.work_item_selection.select_next_hierarchical_item')
    def test_returns_up_to_count_items(self, mock_hier):
        from pokepoke.orchestration.work_item_selection import select_multiple_items

        items = [
            BeadsWorkItem(id="t1", title="T1", status="open", priority=1, issue_type="task"),
            BeadsWorkItem(id="t2", title="T2", status="open", priority=2, issue_type="task"),
            BeadsWorkItem(id="t3", title="T3", status="open", priority=3, issue_type="task"),
        ]
        # hierarchical selection returns first available each call
        mock_hier.side_effect = lambda lst: lst[0] if lst else None

        result = select_multiple_items(items, count=2)
        assert len(result) == 2
        assert result[0].id == "t1"
        assert result[1].id == "t2"

    def test_returns_empty_for_empty_list(self):
        from pokepoke.orchestration.work_item_selection import select_multiple_items

        assert select_multiple_items([], count=3) == []

    def test_returns_empty_for_zero_count(self):
        from pokepoke.orchestration.work_item_selection import select_multiple_items

        items = [BeadsWorkItem(id="t1", title="T1", status="open", priority=1, issue_type="task")]
        assert select_multiple_items(items, count=0) == []

    @patch('pokepoke.orchestration.work_item_selection.select_next_hierarchical_item')
    def test_skips_claimed_ids(self, mock_hier):
        from pokepoke.orchestration.work_item_selection import select_multiple_items

        items = [
            BeadsWorkItem(id="t1", title="T1", status="open", priority=1, issue_type="task"),
            BeadsWorkItem(id="t2", title="T2", status="open", priority=2, issue_type="task"),
        ]
        mock_hier.side_effect = lambda lst: lst[0] if lst else None

        result = select_multiple_items(items, count=2, claimed_ids={"t1"})
        assert len(result) == 1
        assert result[0].id == "t2"

    @patch('pokepoke.orchestration.work_item_selection.select_next_hierarchical_item')
    def test_skips_failed_ids(self, mock_hier):
        from pokepoke.orchestration.work_item_selection import select_multiple_items

        items = [
            BeadsWorkItem(id="t1", title="T1", status="open", priority=1, issue_type="task"),
            BeadsWorkItem(id="t2", title="T2", status="open", priority=2, issue_type="task"),
        ]
        mock_hier.side_effect = lambda lst: lst[0] if lst else None

        result = select_multiple_items(items, count=5, skip_ids={"t1"})
        assert len(result) == 1
        assert result[0].id == "t2"


class TestOrchestratorStopAfterCurrent:
    """Tests for stop-after-current in orchestrator loop."""

    def test_stop_after_current_exits_loop(self) -> None:
        """Covers lines 271-276: orchestrator exits when stop_after_current is set."""
        item = make_work_item(id="task-stop", title="Stop Task")

        with make_orchestrator_mocks(
            items=[item], selected=item, include_maintenance=True,
            process_result=WorkItemResult(success=True, request_count=1, stats=AgentStats()),
        ):
            from pokepoke.utils.shutdown import cancel_stop_after_current, request_stop_after_current, reset
            reset()
            request_stop_after_current()

            result = run_orchestrator(interactive=False, continuous=True)

            assert result == 0
            cancel_stop_after_current()
            reset()


class TestOrchestratorMergeQueueCleanup:
    """Tests for merge queue cleanup in finally block."""

    def test_merge_queue_shutdown_exception_handled(self) -> None:
        """Covers lines 330-332: merge queue shutdown exception in finally."""
        with make_orchestrator_mocks():
            mock_mq = Mock()
            mock_mq.is_running = True
            mock_mq.shutdown.side_effect = RuntimeError("shutdown failed")

            with patch('pokepoke.orchestration.orchestrator.get_merge_queue', return_value=mock_mq):
                result = run_orchestrator(interactive=False, continuous=False)

            assert result == 0


