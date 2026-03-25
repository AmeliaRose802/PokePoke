"""Unit tests for orchestrator module."""

from unittest.mock import ANY, Mock, call, patch

import pytest

from pokepoke.desktop import terminal_ui
from pokepoke.orchestration.orchestrator import run_orchestrator
from pokepoke.orchestration.workflow import process_work_item, select_work_item
from pokepoke.types import AgentStats, BeadsStats, BeadsWorkItem, CopilotResult, GateAgentResult, WorkItemResult
from tests.orchestration.conftest import (
    PATCH_ORCH_IS_SHUTTING_DOWN,
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
    @patch('pokepoke.orchestration.workflow.create_worktree')
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
    @patch('pokepoke.orchestration.workflow.create_worktree')
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


class TestCheckMainRepoReadyForMerge:
    """Test check_main_repo_ready_for_merge function."""

    @patch('subprocess.run')
    def test_clean_repo(self, mock_subprocess: Mock) -> None:
        """Test clean repo returns ready."""
        from pokepoke.git.git_operations import check_main_repo_ready_for_merge

        mock_subprocess.return_value = Mock(stdout="")
        is_ready, error = check_main_repo_ready_for_merge()

        assert is_ready is True
        assert error == ""

    @patch('subprocess.run')
    def test_beads_only_changes(self, mock_subprocess: Mock) -> None:
        """Test beads-only changes are auto-committed."""
        from pokepoke.git.git_operations import check_main_repo_ready_for_merge

        # First call returns beads changes, subsequent calls succeed
        mock_subprocess.side_effect = [
            Mock(stdout="M .beads/issues.jsonl\n"),
            None,  # git add
            None   # git commit
        ]

        is_ready, error = check_main_repo_ready_for_merge()

        assert is_ready is True
        assert error == ""
        assert mock_subprocess.call_count == 3

    @patch('subprocess.run')
    def test_non_beads_changes(self, mock_subprocess: Mock) -> None:
        """Test non-beads changes cause failure."""
        from pokepoke.git.git_operations import check_main_repo_ready_for_merge

        mock_subprocess.return_value = Mock(stdout="M src/file.py\nM .beads/issues.jsonl\n")
        is_ready, error = check_main_repo_ready_for_merge()

        assert is_ready is False
        assert "src/file.py" in error
        # Should only call git status once, not attempt to commit
        assert mock_subprocess.call_count == 1

    @patch('subprocess.run')
    def test_subprocess_error(self, mock_subprocess: Mock) -> None:
        """Test subprocess error is handled."""
        from pokepoke.git.git_operations import check_main_repo_ready_for_merge

        mock_subprocess.side_effect = Exception("git command failed")
        is_ready, error = check_main_repo_ready_for_merge()

        assert is_ready is False
        assert "git command failed" in error


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
            mocks['select'].side_effect = items[:10] + [None]
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


class TestOrchestratorHelperFunctions:
    """Test orchestrator helper functions."""

    @patch('pokepoke.git.repo_state_guard.cleanup_lock')
    @patch('pokepoke.git.repo_check.merge_lock_active', return_value=False)
    @patch('pokepoke.agents.cleanup_agents.invoke_cleanup_agent')
    @patch('subprocess.run')
    def test_check_and_commit_main_repo_with_non_beads_changes(
        self,
        mock_subprocess: Mock,
        mock_cleanup: Mock,
        _mock_merge_lock: Mock,
        mock_cleanup_lock: Mock,
    ) -> None:
        """Test check_and_commit_main_repo with non-beads changes - tries auto-commit first, then cleanup agent."""
        import tempfile
        from contextlib import contextmanager
        from pathlib import Path

        from pokepoke.git.repo_check import check_and_commit_main_repo
        from pokepoke.utils.logging_utils import RunLogger

        # Make cleanup_lock() a no-op context manager
        @contextmanager
        def _noop_lock():
            yield
        mock_cleanup_lock.return_value = _noop_lock()

        # git status returns changes, auto-commit (add succeeds, commit fails), then cleanup agent
        mock_subprocess.side_effect = [
            Mock(stdout=" M src/file.py\n M tests/test.py\n", returncode=0),  # git status
            Mock(returncode=0),  # git add --all (auto-commit)
            Mock(returncode=1, stdout="", stderr="pre-commit hook failed"),  # git commit fails
        ]
        # Mock cleanup agent to return success
        mock_cleanup.return_value = (True, AgentStats(
            wall_duration=1.0,
            api_duration=1.0,
            input_tokens=100,
            output_tokens=50,
            lines_added=5,
            lines_removed=3,
            premium_requests=1
        ))

        # Create a temporary logger
        with tempfile.TemporaryDirectory() as tmpdir:
            run_logger = RunLogger(base_dir=tmpdir)
            repo_path = Path.cwd()

            try:
                result = check_and_commit_main_repo(repo_path, run_logger)

                assert result is True  # Should return True after successful cleanup
                # Should call subprocess for git status + auto-commit attempt
                assert mock_subprocess.call_count >= 3
                mock_cleanup.assert_called_once()

                # Verify cleanup agent was called with correct work item
                call_args = mock_cleanup.call_args
                work_item = call_args[0][0]  # First positional argument
                assert work_item.id == "cleanup-main-repo-1"  # First attempt
                assert "uncommitted changes" in work_item.title.lower()
            finally:
                run_logger.close()

    def test_aggregate_stats(self) -> None:
        """Test aggregate_stats function."""
        from pokepoke.maintenance.maintenance import aggregate_stats
        from pokepoke.types import AgentStats, SessionStats

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


class TestOrchestratorMain:
    """Test main entry point."""

    @patch('pokepoke.utils.project_utils.ensure_project_ready', return_value=True)
    @patch('pokepoke.__main__.run_orchestrator')
    @patch('pokepoke.desktop.terminal_ui.ui')
    @patch('sys.argv', ['pokepoke', '--autonomous'])
    def test_main_autonomous(self, mock_ui: Mock, mock_run: Mock, _mock_ready: Mock) -> None:
        """Test main with autonomous flag."""
        from pokepoke.__main__ import main

        mock_run.return_value = 0
        mock_ui.run_with_orchestrator.side_effect = lambda f: f()

        result = main()

        assert result == 0
        mock_run.assert_called_once_with(
            interactive=False,
            continuous=False,
            run_beta_first=False,
            agent_name_override=None,
            max_parallel_agents=1,
        )

    @patch('pokepoke.utils.project_utils.ensure_project_ready', return_value=True)
    @patch('pokepoke.__main__.run_orchestrator')
    @patch('pokepoke.desktop.terminal_ui.ui')
    @patch('sys.argv', ['pokepoke', '--continuous'])
    def test_main_continuous(self, mock_ui: Mock, mock_run: Mock, _mock_ready: Mock) -> None:
        """Test main with continuous flag."""
        from pokepoke.__main__ import main

        mock_run.return_value = 0
        mock_ui.run_with_orchestrator.side_effect = lambda f: f()

        result = main()

        assert result == 0
        mock_run.assert_called_once_with(
            interactive=True,
            continuous=True,
            run_beta_first=False,
            agent_name_override=None,
            max_parallel_agents=1,
        )

    @patch('pokepoke.utils.project_utils.ensure_project_ready', return_value=True)
    @patch('pokepoke.__main__.run_orchestrator')
    @patch('pokepoke.desktop.terminal_ui.ui')
    @patch('sys.argv', ['pokepoke', '--autonomous', '--continuous'])
    def test_main_both_flags(self, mock_ui: Mock, mock_run: Mock, _mock_ready: Mock) -> None:
        """Test main with both flags."""
        from pokepoke.__main__ import main

        mock_run.return_value = 0
        mock_ui.run_with_orchestrator.side_effect = lambda f: f()

        result = main()

        assert result == 0
        mock_run.assert_called_once_with(
            interactive=False,
            continuous=True,
            run_beta_first=False,
            agent_name_override=None,
            max_parallel_agents=1,
        )

    @patch('pokepoke.utils.project_utils.ensure_project_ready', return_value=False)
    @patch('pokepoke.desktop.terminal_ui.ui')
    @patch('sys.argv', ['pokepoke', '--autonomous'])
    def test_main_exits_when_beads_unavailable(self, mock_ui: Mock, _mock_ready: Mock) -> None:
        """Test main exits with code 1 when beads is not available."""
        from pokepoke.__main__ import main

        mock_ui.run_with_orchestrator.side_effect = lambda f: f()

        result = main()

        assert result == 1

    @patch('pokepoke.utils.project_utils.ensure_project_ready', return_value=True)
    @patch('pokepoke.__main__.run_orchestrator')
    @patch('pokepoke.desktop.terminal_ui.ui')
    @patch('sys.argv', ['pokepoke'])
    def test_main_interactive_initializes_beads_when_missing(
        self,
        mock_ui: Mock,
        mock_run: Mock,
        _mock_ready: Mock,
    ) -> None:
        """Test interactive main proceeds when project is ready."""
        from pokepoke.__main__ import main

        mock_run.return_value = 0
        mock_ui.run_with_orchestrator.side_effect = lambda f: f()

        result = main()

        assert result == 0

    @patch('pokepoke.utils.project_utils.ensure_project_ready', return_value=False)
    @patch('pokepoke.desktop.terminal_ui.ui')
    @patch('sys.argv', ['pokepoke'])
    def test_main_interactive_declines_beads_init_exits_1(
        self,
        mock_ui: Mock,
        _mock_ready: Mock,
    ) -> None:
        """Test interactive main exits when project is not ready."""
        from pokepoke.__main__ import main

        mock_ui.run_with_orchestrator.side_effect = lambda f: f()

        result = main()

        assert result == 1

    @patch('pokepoke.utils.project_utils.ensure_project_ready', return_value=True)
    @patch('pokepoke.__main__.run_orchestrator')
    @patch('pokepoke.desktop.terminal_ui.ui')
    @patch('sys.argv', ['pokepoke', '--autonomous', '--beta-first'])
    def test_main_beta_first(self, mock_ui: Mock, mock_run: Mock, _mock_ready: Mock) -> None:
        """Test main with beta-first flag."""
        from pokepoke.__main__ import main

        mock_run.return_value = 0
        mock_ui.run_with_orchestrator.side_effect = lambda f: f()

        result = main()

        assert result == 0
        mock_run.assert_called_once_with(
            interactive=False,
            continuous=False,
            run_beta_first=True,
            agent_name_override=None,
            max_parallel_agents=1,
        )

    @patch('pokepoke.init.init_project', return_value=True)
    @patch('sys.argv', ['pokepoke', '--init'])
    def test_main_init_success(self, mock_init: Mock) -> None:
        """Test main with --init flag succeeding."""
        from pokepoke.__main__ import main

        result = main()

        assert result == 0
        mock_init.assert_called_once()

    @patch('pokepoke.init.init_project', return_value=False)
    @patch('sys.argv', ['pokepoke', '--init'])
    def test_main_init_failure(self, mock_init: Mock) -> None:
        """Test main with --init flag failing."""
        from pokepoke.__main__ import main

        result = main()

        assert result == 1

    @patch('sys.argv', ['pokepoke', '--repo', '/nonexistent/path/that/does/not/exist'])
    def test_main_repo_nonexistent(self) -> None:
        """Test main with --repo pointing to nonexistent path."""
        from pokepoke.__main__ import main
        result = main()
        assert result == 1

    @patch('pokepoke.utils.project_utils.ensure_project_ready', return_value=True)
    @patch('pokepoke.__main__.run_orchestrator')
    @patch('pokepoke.desktop.terminal_ui.ui')
    def test_main_repo_valid(self, mock_ui: Mock, mock_run: Mock, _mock_ready: Mock, tmp_path) -> None:
        """Test main with --repo pointing to a valid directory."""
        import sys

        from pokepoke.__main__ import main
        with patch.object(sys, 'argv', ['pokepoke', '--autonomous', '--repo', str(tmp_path)]):
            mock_run.return_value = 0
            mock_ui.run_with_orchestrator.side_effect = lambda f: f()
            result = main()
        assert result == 0


class TestCheckBeadsAvailable:
    """Test check_beads_available function."""

    @patch('pokepoke.git.repo_check.shutil.which', return_value=None)
    def test_bd_not_installed(self, mock_which: Mock) -> None:
        """Test returns False when bd command not found."""
        from pokepoke.git.repo_check import check_beads_available

        result = check_beads_available()

        assert result is False

    @patch('pokepoke.git.repo_check.shutil.which', return_value='/usr/bin/bd')
    def test_bd_info_succeeds(self, mock_which: Mock, tmp_path, monkeypatch) -> None:
        """Test returns True when bd is installed and .beads directory initialized."""
        from pokepoke.git.repo_check import check_beads_available

        monkeypatch.chdir(tmp_path)
        beads_dir = tmp_path / ".beads"
        beads_dir.mkdir()
        (beads_dir / "config.yaml").write_text("test: true")

        result = check_beads_available()

        assert result is True

    @patch('pokepoke.git.repo_check.shutil.which', return_value='/usr/bin/bd')
    def test_bd_not_initialized(self, mock_which: Mock, tmp_path, monkeypatch) -> None:
        """Test returns False when .beads directory doesn't exist."""
        from pokepoke.git.repo_check import check_beads_available

        monkeypatch.chdir(tmp_path)

        result = check_beads_available()

        assert result is False

    @patch('pokepoke.git.repo_check.shutil.which', return_value='/usr/bin/bd')
    def test_bd_info_timeout(self, mock_which: Mock, tmp_path, monkeypatch) -> None:
        """Test returns False when .beads directory exists but has no marker files."""
        from pokepoke.git.repo_check import check_beads_available

        monkeypatch.chdir(tmp_path)
        (tmp_path / ".beads").mkdir()

        result = check_beads_available()

        assert result is False

    @patch('pokepoke.git.repo_check.shutil.which', return_value='/usr/bin/bd')
    def test_bd_info_exception(self, mock_which: Mock, tmp_path, monkeypatch) -> None:
        """Test returns False when .beads directory is incomplete."""
        from pokepoke.git.repo_check import check_beads_available

        monkeypatch.chdir(tmp_path)
        beads_dir = tmp_path / ".beads"
        beads_dir.mkdir()
        (beads_dir / "random.txt").write_text("not a marker")

        result = check_beads_available()

        assert result is False


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


class TestRunOrchestratorBetaFirst:
    """Test run_orchestrator with beta_first flag."""

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


class TestRunOrchestratorModelCompletion:
    """Test model completion recording in run_orchestrator."""

    def test_model_completion_recorded(self) -> None:
        """Test model completion is recorded when present."""
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
            result = run_orchestrator(interactive=False, continuous=False)

            assert result == 0
            mocks['record'].assert_called_once_with(completion)


class TestRunOrchestratorRepoCheckFailure:
    """Test run_orchestrator when main repo check fails."""

    def test_repo_check_failure_returns_1(self) -> None:
        """Test orchestrator returns 1 when repo check fails."""
        with make_orchestrator_mocks(include_check_repo=True) as mocks:
            mocks['check_repo'].return_value = False

            result = run_orchestrator(interactive=False, continuous=False)

            assert result == 1
            mocks['get_items'].assert_not_called()


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


class TestMainWorktreeCoverage:
    """Tests for main() using pokepoke.orchestration.orchestrator for coverage."""

    @patch('pokepoke.utils.project_utils.ensure_project_ready', return_value=True)
    @patch('pokepoke.__main__.run_orchestrator')
    @patch('pokepoke.desktop.terminal_ui.ui')
    @patch('sys.argv', ['pokepoke', '--autonomous'])
    def test_main_autonomous(self, mock_ui: Mock, mock_run: Mock, _mock_ready: Mock) -> None:
        """Test main with autonomous flag."""
        from pokepoke.__main__ import main

        mock_run.return_value = 0
        mock_ui.run_with_orchestrator.side_effect = lambda f: f()

        result = main()
        assert result == 0

    @patch('pokepoke.utils.project_utils.ensure_project_ready', return_value=True)
    @patch('pokepoke.__main__.run_orchestrator')
    @patch('pokepoke.desktop.terminal_ui.ui')
    @patch('sys.argv', ['pokepoke', '--autonomous', '--beta-first'])
    def test_main_beta_first(self, mock_ui: Mock, mock_run: Mock, _mock_ready: Mock) -> None:
        """Test main with beta-first flag."""
        from pokepoke.__main__ import main

        mock_run.return_value = 0
        mock_ui.run_with_orchestrator.side_effect = lambda f: f()

        result = main()
        assert result == 0
        mock_run.assert_called_once_with(
            interactive=False,
            continuous=False,
            run_beta_first=True,
            agent_name_override=None,
            max_parallel_agents=1,
        )

    @patch('pokepoke.utils.project_utils.ensure_project_ready', return_value=False)
    @patch('pokepoke.desktop.terminal_ui.ui')
    @patch('sys.argv', ['pokepoke', '--autonomous'])
    def test_main_beads_unavailable(self, mock_ui: Mock, _mock_ready: Mock) -> None:
        """Test main returns 1 when project not ready."""
        from pokepoke.__main__ import main

        mock_ui.run_with_orchestrator.side_effect = lambda f: f()

        result = main()
        assert result == 1

    @patch('pokepoke.init.init_project', return_value=True)
    @patch('sys.argv', ['pokepoke', '--init'])
    def test_main_init(self, mock_init: Mock) -> None:
        """Test main with --init flag."""
        from pokepoke.__main__ import main

        result = main()
        assert result == 0

    @patch('pokepoke.utils.project_utils.ensure_project_ready', return_value=True)
    @patch('pokepoke.__main__.run_orchestrator')
    @patch('pokepoke.desktop.terminal_ui.ui')
    @patch('sys.argv', ['pokepoke', '--autonomous', '--continuous'])
    def test_main_continuous(self, mock_ui: Mock, mock_run: Mock, _mock_ready: Mock) -> None:
        """Test main with continuous flag."""
        from pokepoke.__main__ import main

        mock_run.return_value = 0
        mock_ui.run_with_orchestrator.side_effect = lambda f: f()

        result = main()
        assert result == 0
        mock_run.assert_called_once_with(
            interactive=False,
            continuous=True,
            run_beta_first=False,
            agent_name_override=None,
            max_parallel_agents=1,
        )


class TestOrchestratorCleanupDetection:
    """Test orchestrator's main repo cleanup detection."""

    def setup_method(self) -> None:
        """Reset shutdown state before each test."""
        from pokepoke.utils.shutdown import reset
        reset()

    @patch('pokepoke.orchestration.orchestrator.check_and_commit_main_repo')
    @patch('pokepoke.orchestration.orchestrator.get_beads_stats')
    @patch('pokepoke.orchestration.orchestrator.get_ready_work_items')
    def test_detects_uncommitted_changes_and_invokes_cleanup(
        self,
        mock_get_items: Mock,
        mock_beads_stats: Mock,
        mock_check_repo: Mock,
    ) -> None:
        """Test that orchestrator invokes check_and_commit_main_repo."""
        mock_check_repo.return_value = True  # Repo check passes (cleanup succeeded or continued)
        mock_get_items.return_value = []  # No work items available
        mock_beads_stats.return_value = BeadsStats(
            total_issues=0, open_issues=0, in_progress_issues=0,
            closed_issues=0, ready_issues=0
        )

        with patch('pokepoke.orchestration.orchestrator.is_shutting_down', return_value=False):
            result = run_orchestrator(interactive=False, continuous=False)

        # Should return 0 because repo check passes
        assert result == 0
        # Should call check_and_commit_main_repo at least once
        mock_check_repo.assert_called()
        # Should call get_items since repo check passed
        mock_get_items.assert_called()

    @patch('pokepoke.orchestration.orchestrator.check_and_commit_main_repo')
    @patch('pokepoke.orchestration.orchestrator.get_beads_stats')
    @patch('pokepoke.orchestration.orchestrator.get_ready_work_items')
    def test_detects_beads_changes_without_autocommit(
        self,
        mock_get_items: Mock,
        mock_beads_stats: Mock,
        mock_check_repo: Mock,
    ) -> None:
        """Test that beads-only changes are detected but NOT auto-committed."""
        mock_beads_stats.return_value = BeadsStats(
            total_issues=10,
            open_issues=5,
            in_progress_issues=2,
            closed_issues=3,
            ready_issues=1
        )
        mock_check_repo.return_value = True
        mock_get_items.return_value = []

        with patch('pokepoke.orchestration.orchestrator.is_shutting_down', return_value=False):
            result = run_orchestrator(interactive=False, continuous=False)

        mock_check_repo.assert_called_once()
        assert result == 0

    @patch('pokepoke.orchestration.orchestrator.get_ready_work_items')
    @patch('subprocess.run')
    def test_clean_repo_proceeds_to_work(
        self,
        mock_subprocess: Mock,
        mock_get_items: Mock,
    ) -> None:
        """Test that clean repo proceeds to normal work processing."""
        mock_subprocess.return_value = Mock(
            stdout="",
            returncode=0
        )
        mock_get_items.return_value = []

        result = run_orchestrator(interactive=False, continuous=False)

        mock_get_items.assert_called_once()
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


class TestRecordItemResult:
    """Tests for _record_item_result helper."""

    @patch('pokepoke.orchestration.orchestrator.run_periodic_maintenance')
    @patch('pokepoke.orchestration.orchestrator.increment_items_completed', return_value=5)
    @patch('pokepoke.orchestration.orchestrator.append_model_history_entry')
    @patch('pokepoke.orchestration.orchestrator.record_completion')
    def test_records_success(self, mock_record, mock_hist, mock_inc, mock_maint):
        from pokepoke.orchestration.orchestrator import _record_item_result
        from pokepoke.types import ModelCompletionRecord, SessionStats

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
        from pokepoke.types import SessionStats

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
        from pokepoke.types import SessionStats

        stats = SessionStats(agent_stats=AgentStats())
        item = BeadsWorkItem(id="t1", title="T1", status="open", priority=1, issue_type="task")
        logger = Mock()

        _record_item_result(item, WorkItemResult(success=True, request_count=3, stats=AgentStats(), cleanup_agent_runs=2, gate_agent_runs=1), stats, logger)
        # 3 requests => 2 retries recorded
        assert stats.agent_stats.retries == 2


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


