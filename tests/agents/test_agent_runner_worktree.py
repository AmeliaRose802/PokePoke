"""Unit tests for agent_runner module."""

from pathlib import Path
from unittest.mock import Mock, patch

from pokepoke.agents.agent_runner import (
    _run_worktree_agent,
)
from pokepoke.types import AgentStats, BeadsWorkItem, CopilotResult


class TestRunWorktreeAgent:
    """Test _run_worktree_agent function."""

    @patch('pokepoke.agents.agent_runner.handle_worktree_merge')  # Mock the extracted function
    @patch('pokepoke.git.git_operations.check_main_repo_ready_for_merge')  # Patch at module level
    @patch('pokepoke.agents.agent_runner.cleanup_worktree')
    @patch('pokepoke.agents.agent_runner.parse_agent_stats')
    @patch('pokepoke.agents.agent_runner.run_cleanup_loop')
    @patch('os.chdir')
    @patch('os.getcwd')
    @patch('pokepoke.agents.agent_runner.invoke_copilot')
    @patch('pokepoke.agents.agent_runner.create_worktree')
    def test_successful_worktree_agent(
        self,
        mock_create: Mock,
        mock_invoke: Mock,
        mock_getcwd: Mock,
        mock_chdir: Mock,
        mock_cleanup_loop: Mock,
        mock_parse: Mock,
        mock_cleanup: Mock,
        mock_check_ready: Mock,
        mock_handle_merge: Mock
    ) -> None:
        """Test successful worktree agent."""
        agent_item = BeadsWorkItem(
            id="maintenance-test",
            title="Test Maintenance",
            description="Test",
            status="in_progress",
            priority=0,
            issue_type="task",
            labels=["maintenance"]
        )

        mock_create.return_value = Path("/fake/worktree")
        mock_getcwd.return_value = "/original"
        mock_invoke.return_value = CopilotResult(
            work_item_id="maintenance-test",
            success=True,
            output="Completed",
            attempt_count=1
        )
        mock_cleanup_loop.return_value = (True, 0)
        mock_parse.return_value = AgentStats(
            wall_duration=10.0,
            api_duration=5.0,
            input_tokens=100,
            output_tokens=50,
            lines_added=10,
            lines_removed=5,
            premium_requests=1
        )
        mock_check_ready.return_value = (True, "")
        mock_handle_merge.return_value = (True, True)  # Mock successful merge

        stats = _run_worktree_agent(
            "Test",
            "maintenance-test",
            agent_item,
            "Test prompt",
            Path("/fake/repo")
        )

        assert stats is not None
        mock_create.assert_called_once()
        mock_handle_merge.assert_called_once()  # Verify merge handler was called
        mock_cleanup.assert_not_called()

    @patch('pokepoke.agents.agent_runner.create_worktree')
    def test_worktree_creation_failure(self, mock_create: Mock) -> None:
        """Test worktree agent when worktree creation fails."""
        agent_item = BeadsWorkItem(
            id="maintenance-test",
            title="Test Maintenance",
            description="Test",
            status="in_progress",
            priority=0,
            issue_type="task",
            labels=["maintenance"]
        )

        mock_create.side_effect = Exception("Failed to create worktree")

        stats = _run_worktree_agent(
            "Test",
            "maintenance-test",
            agent_item,
            "Test prompt",
            Path("/fake/repo")
        )

        assert stats is None

    @patch('pokepoke.agents.agent_runner.cleanup_worktree')
    @patch('pokepoke.agents.agent_runner.run_cleanup_loop')
    @patch('pokepoke.agents.agent_runner.invoke_copilot')
    @patch('pokepoke.agents.agent_runner.create_worktree')
    @patch('os.getcwd')
    @patch('os.chdir')
    def test_invoke_copilot_exception(
        self, mock_chdir: Mock, mock_getcwd: Mock,
        mock_create: Mock, mock_invoke: Mock, mock_cleanup_loop: Mock, mock_cleanup: Mock
    ) -> None:
        """Test exception handling when invoke_copilot raises."""
        mock_create.return_value = Path("/tmp/wt")
        mock_invoke.side_effect = Exception("Boom")
        mock_cleanup_loop.return_value = (False, 0)

        item = BeadsWorkItem(
            id="1", title="T", description="D",
            status="open", priority=1, issue_type="task"
        )

        res = _run_worktree_agent("Agent", "1", item, "Prompt", Path("/repo"))

        assert res is None
        mock_cleanup.assert_not_called()

    @patch('pokepoke.agents.agent_runner.cleanup_worktree')
    @patch('os.chdir')
    @patch('os.getcwd')
    @patch('pokepoke.agents.agent_runner.run_cleanup_loop')
    @patch('pokepoke.agents.agent_runner.invoke_copilot')
    @patch('pokepoke.agents.agent_runner.create_worktree')
    def test_worktree_agent_failure(
        self,
        mock_create: Mock,
        mock_invoke: Mock,
        mock_cleanup_loop: Mock,
        mock_getcwd: Mock,
        mock_chdir: Mock,
        mock_cleanup: Mock
    ) -> None:
        """Test worktree agent when agent fails."""
        agent_item = BeadsWorkItem(
            id="maintenance-test",
            title="Test Maintenance",
            description="Test",
            status="in_progress",
            priority=0,
            issue_type="task",
            labels=["maintenance"]
        )

        mock_create.return_value = Path("/fake/worktree")
        mock_getcwd.return_value = "/original"
        mock_invoke.return_value = CopilotResult(
            work_item_id="maintenance-test",
            success=False,
            output="",
            error="Agent failed",
            attempt_count=1
        )
        mock_cleanup_loop.return_value = (True, 0)

        stats = _run_worktree_agent(
            "Test",
            "maintenance-test",
            agent_item,
            "Test prompt",
            Path("/fake/repo")
        )

        assert stats is None
        mock_cleanup.assert_not_called()

    @patch('pokepoke.agents.agent_runner.handle_worktree_merge')
    @patch('pokepoke.agents.agent_runner.invoke_merge_conflict_cleanup_agent')
    @patch('pokepoke.agents.agent_runner.cleanup_worktree')
    @patch('pokepoke.git.git_operations.check_main_repo_ready_for_merge')
    @patch('os.chdir')
    @patch('os.getcwd')
    @patch('pokepoke.agents.agent_runner.run_cleanup_loop')
    @patch('pokepoke.agents.agent_runner.invoke_copilot')
    @patch('pokepoke.agents.agent_runner.create_worktree')
    def test_worktree_merge_failure(
        self,
        mock_create: Mock,
        mock_invoke: Mock,
        mock_cleanup_loop: Mock,
        mock_getcwd: Mock,
        mock_chdir: Mock,
        mock_check_ready: Mock,
        mock_cleanup: Mock,
        mock_invoke_merge_cleanup: Mock,
        mock_handle_merge: Mock
    ) -> None:
        """Test worktree agent when merge fails."""
        agent_item = BeadsWorkItem(
            id="maintenance-test",
            title="Test Maintenance",
            description="Test",
            status="in_progress",
            priority=0,
            issue_type="task",
            labels=["maintenance"]
        )

        mock_create.return_value = Path("/fake/worktree")
        mock_getcwd.return_value = "/original"
        # Mock successful agent run
        mock_invoke.return_value = CopilotResult(
            work_item_id="maintenance-test",
            success=True,
            output='{"wall_duration": 10.0, "input_tokens": 100, "output_tokens": 50}',
            error="",
            attempt_count=1
        )
        mock_cleanup_loop.return_value = (True, 0)

        # Mock merge failure
        mock_handle_merge.return_value = (False, False)  # Merge failed

        stats = _run_worktree_agent(
            "Test",
            "maintenance-test",
            agent_item,
            "Test prompt",
            Path("/fake/repo")
        )

        assert stats is None
        mock_cleanup.assert_not_called()

    @patch('pokepoke.agents.agent_runner.handle_worktree_merge')
    @patch('pokepoke.git.merge_conflict.is_merge_in_progress')
    @patch('pokepoke.agents.agent_runner.invoke_merge_conflict_cleanup_agent')
    @patch('pokepoke.agents.agent_runner.cleanup_worktree')
    @patch('pokepoke.git.git_operations.check_main_repo_ready_for_merge')
    @patch('pokepoke.agents.agent_runner.parse_agent_stats')
    @patch('os.chdir')
    @patch('os.getcwd')
    @patch('pokepoke.agents.agent_runner.run_cleanup_loop')
    @patch('pokepoke.agents.agent_runner.invoke_copilot')
    @patch('pokepoke.agents.agent_runner.create_worktree')
    def test_merge_cleanup_success_then_retry_succeeds(
        self,
        mock_create: Mock,
        mock_invoke: Mock,
        mock_cleanup_loop: Mock,
        mock_getcwd: Mock,
        mock_chdir: Mock,
        mock_parse: Mock,
        mock_check_ready: Mock,
        mock_cleanup: Mock,
        mock_invoke_merge_cleanup: Mock,
        mock_is_merge: Mock,
        mock_handle_merge: Mock
    ) -> None:
        """Test merge conflict cleanup succeeds and retry works."""
        agent_item = BeadsWorkItem(
            id="maintenance-test",
            title="Test Maintenance",
            description="Test",
            status="in_progress",
            priority=0,
            issue_type="task",
            labels=["maintenance"]
        )

        mock_create.return_value = Path("/fake/worktree")
        mock_getcwd.return_value = "/original"
        mock_invoke.return_value = CopilotResult(
            work_item_id="maintenance-test",
            success=True,
            output="Completed",
            attempt_count=1
        )
        mock_cleanup_loop.return_value = (True, 0)
        mock_parse.return_value = AgentStats(
            wall_duration=10.0, api_duration=5.0, input_tokens=100,
            output_tokens=50, lines_added=10, lines_removed=5, premium_requests=1
        )
        mock_handle_merge.return_value = (True, True)  # Mock successful merge

        stats = _run_worktree_agent(
            "Test",
            "maintenance-test",
            agent_item,
            "Test prompt",
            Path("/fake/repo")
        )

        assert stats is not None

    @patch('pokepoke.agents.agent_runner.handle_worktree_merge')
    @patch('pokepoke.git.merge_conflict.abort_merge')
    @patch('pokepoke.git.merge_conflict.is_merge_in_progress')
    @patch('pokepoke.agents.agent_runner.invoke_merge_conflict_cleanup_agent')
    @patch('pokepoke.agents.agent_runner.cleanup_worktree')
    @patch('pokepoke.git.git_operations.check_main_repo_ready_for_merge')
    @patch('pokepoke.agents.agent_runner.parse_agent_stats')
    @patch('os.chdir')
    @patch('os.getcwd')
    @patch('pokepoke.agents.agent_runner.run_cleanup_loop')
    @patch('pokepoke.agents.agent_runner.invoke_copilot')
    @patch('pokepoke.agents.agent_runner.create_worktree')
    def test_merge_still_in_progress_after_cleanup_aborts(
        self,
        mock_create: Mock,
        mock_invoke: Mock,
        mock_cleanup_loop: Mock,
        mock_getcwd: Mock,
        mock_chdir: Mock,
        mock_parse: Mock,
        mock_check_ready: Mock,
        mock_cleanup: Mock,
        mock_invoke_merge_cleanup: Mock,
        mock_is_merge: Mock,
        mock_abort: Mock,
        mock_handle_merge: Mock
    ) -> None:
        """Test merge is aborted when still in progress after cleanup."""
        agent_item = BeadsWorkItem(
            id="maintenance-test",
            title="Test Maintenance",
            description="Test",
            status="in_progress",
            priority=0,
            issue_type="task",
            labels=["maintenance"]
        )

        mock_create.return_value = Path("/fake/worktree")
        mock_getcwd.return_value = "/original"
        mock_invoke.return_value = CopilotResult(
            work_item_id="maintenance-test",
            success=True,
            output="Completed",
            attempt_count=1
        )
        mock_cleanup_loop.return_value = (True, 0)
        mock_parse.return_value = AgentStats(
            wall_duration=10.0, api_duration=5.0, input_tokens=100,
            output_tokens=50, lines_added=10, lines_removed=5, premium_requests=1
        )
        mock_handle_merge.return_value = (True, True)  # Mock successful merge

        stats = _run_worktree_agent(
            "Test",
            "maintenance-test",
            agent_item,
            "Test prompt",
            Path("/fake/repo")
        )

        assert stats is not None

    @patch('pokepoke.agents.agent_runner.handle_worktree_merge')
    @patch('pokepoke.agents.agent_runner.invoke_cleanup_agent')
    @patch('pokepoke.git.git_operations.check_main_repo_ready_for_merge')
    @patch('os.chdir')
    @patch('os.getcwd')
    @patch('pokepoke.agents.agent_runner.run_cleanup_loop')
    @patch('pokepoke.agents.agent_runner.invoke_copilot')
    @patch('pokepoke.agents.agent_runner.create_worktree')
    def test_main_repo_not_ready_cleanup_fails(
        self,
        mock_create: Mock,
        mock_invoke: Mock,
        mock_cleanup_loop: Mock,
        mock_getcwd: Mock,
        mock_chdir: Mock,
        mock_check_ready: Mock,
        mock_invoke_cleanup: Mock,
        mock_handle_merge: Mock
    ) -> None:
        """Test when main repo not ready for merge and cleanup fails."""
        agent_item = BeadsWorkItem(
            id="maintenance-test",
            title="Test Maintenance",
            description="Test",
            status="in_progress",
            priority=0,
            issue_type="task",
            labels=["maintenance"]
        )

        mock_create.return_value = Path("/fake/worktree")
        mock_getcwd.return_value = "/original"
        mock_invoke.return_value = CopilotResult(
            work_item_id="maintenance-test",
            success=True,
            output="Completed",
            attempt_count=1
        )
        mock_cleanup_loop.return_value = (True, 0)
        mock_handle_merge.return_value = (False, False)  # Mock failed merge

        stats = _run_worktree_agent(
            "Test",
            "maintenance-test",
            agent_item,
            "Test prompt",
            Path("/fake/repo")
        )

        assert stats is None

    @patch('pokepoke.agents.agent_runner.handle_worktree_merge')
    @patch('pokepoke.agents.agent_runner.invoke_cleanup_agent')
    @patch('pokepoke.git.git_operations.check_main_repo_ready_for_merge')
    @patch('pokepoke.agents.agent_runner.parse_agent_stats')
    @patch('os.chdir')
    @patch('os.getcwd')
    @patch('pokepoke.agents.agent_runner.run_cleanup_loop')
    @patch('pokepoke.agents.agent_runner.invoke_copilot')
    @patch('pokepoke.agents.agent_runner.create_worktree')
    def test_main_repo_not_ready_cleanup_succeeds_but_still_fails(
        self,
        mock_create: Mock,
        mock_invoke: Mock,
        mock_cleanup_loop: Mock,
        mock_getcwd: Mock,
        mock_chdir: Mock,
        mock_parse: Mock,
        mock_check_ready: Mock,
        mock_invoke_cleanup: Mock,
        mock_handle_merge: Mock
    ) -> None:
        """Test when main repo not ready, cleanup succeeds, but still fails."""
        agent_item = BeadsWorkItem(
            id="maintenance-test",
            title="Test Maintenance",
            description="Test",
            status="in_progress",
            priority=0,
            issue_type="task",
            labels=["maintenance"]
        )

        mock_create.return_value = Path("/fake/worktree")
        mock_getcwd.return_value = "/original"
        mock_invoke.return_value = CopilotResult(
            work_item_id="maintenance-test",
            success=True,
            output="Completed",
            attempt_count=1
        )
        mock_cleanup_loop.return_value = (True, 0)
        mock_parse.return_value = None
        mock_handle_merge.return_value = (False, False)  # Mock failed merge

        stats = _run_worktree_agent(
            "Test",
            "maintenance-test",
            agent_item,
            "Test prompt",
            Path("/fake/repo")
        )

        assert stats is None


def _mcp_enabled_config() -> Mock:
    """Create a mock config with MCP server enabled."""
    cfg = Mock()
    cfg.mcp_server.enabled = True
    cfg.mcp_server.restart_script = "scripts/Restart-MCPServer.ps1"
    cfg.mcp_server.name = "Test MCP"
    return cfg


def _mcp_disabled_config() -> Mock:
    """Create a mock config with MCP server disabled."""
    cfg = Mock()
    cfg.mcp_server.enabled = False
    cfg.mcp_server.restart_script = None
    cfg.mcp_server.name = None
    return cfg


class TestWorktreeAgentMergeChangeFalse:
    """Test _run_worktree_agent with merge_changes=False (lines 281-284)."""

    @patch('pokepoke.agents.agent_runner.cleanup_worktree')
    @patch('pokepoke.agents.agent_runner.parse_agent_stats')
    @patch('pokepoke.agents.agent_runner.run_cleanup_loop')
    @patch('pokepoke.agents.agent_runner.invoke_copilot')
    @patch('pokepoke.agents.agent_runner.create_worktree')
    def test_discards_worktree(
        self, mock_create: Mock, mock_invoke: Mock, mock_cleanup_loop: Mock,
        mock_parse: Mock, mock_cleanup: Mock
    ) -> None:
        agent_item = BeadsWorkItem(
            id="maint-test", title="Test", description="Test",
            status="in_progress", priority=0, issue_type="task", labels=["maintenance"]
        )
        mock_create.return_value = Path("/fake/worktree")
        mock_invoke.return_value = CopilotResult(
            work_item_id="maint-test", success=True,
            output="Completed", attempt_count=1
        )
        mock_cleanup_loop.return_value = (True, 0)
        mock_parse.return_value = AgentStats(
            wall_duration=10.0, api_duration=5.0, input_tokens=100,
            output_tokens=50, lines_added=10, lines_removed=5, premium_requests=1
        )
        stats = _run_worktree_agent(
            "Test", "maint-test", agent_item, "Prompt",
            Path("/fake/repo"), merge_changes=False
        )
        assert stats is not None
        mock_cleanup.assert_called_once_with("maint-test", force=True)

    @patch('pokepoke.agents.agent_runner.cleanup_worktree')
    @patch('pokepoke.agents.agent_runner.parse_agent_stats')
    @patch('pokepoke.agents.agent_runner.run_cleanup_loop')
    @patch('pokepoke.agents.agent_runner.invoke_copilot')
    @patch('pokepoke.agents.agent_runner.create_worktree')
    def test_with_model_prints_model(
        self, mock_create: Mock, mock_invoke: Mock, mock_cleanup_loop: Mock,
        mock_parse: Mock, mock_cleanup: Mock
    ) -> None:
        """Covers line 254: model print."""
        agent_item = BeadsWorkItem(
            id="maint-test", title="Test", description="Test",
            status="in_progress", priority=0, issue_type="task", labels=["maintenance"]
        )
        mock_create.return_value = Path("/fake/worktree")
        mock_invoke.return_value = CopilotResult(
            work_item_id="maint-test", success=True,
            output="Completed", attempt_count=1
        )
        mock_cleanup_loop.return_value = (True, 0)
        mock_parse.return_value = None
        stats = _run_worktree_agent(
            "Test", "maint-test", agent_item, "Prompt",
            Path("/fake/repo"), merge_changes=False, model="gpt-4"
        )
        assert stats is None  # parse returns None


class TestWorktreeAgentFinallyCleanupException:
    """Test _run_worktree_agent finally block cleanup exception (lines 317-321)."""

    @patch('pokepoke.agents.agent_runner.add_uncleaned_worktree')
    @patch('pokepoke.agents.agent_runner.cleanup_worktree')
    @patch('pokepoke.agents.agent_runner.parse_agent_stats')
    @patch('pokepoke.agents.agent_runner.run_cleanup_loop')
    @patch('pokepoke.agents.agent_runner.invoke_copilot')
    @patch('pokepoke.agents.agent_runner.create_worktree')
    def test_cleanup_raises_adds_uncleaned(
        self, mock_create: Mock, mock_invoke: Mock, mock_cleanup_loop: Mock,
        mock_parse: Mock, mock_cleanup: Mock,
        mock_add_uncleaned: Mock
    ) -> None:
        agent_item = BeadsWorkItem(
            id="maint-test", title="Test", description="Test",
            status="in_progress", priority=0, issue_type="task", labels=["maintenance"]
        )
        mock_create.return_value = Path("/fake/worktree")
        mock_invoke.return_value = CopilotResult(
            work_item_id="maint-test", success=True,
            output="Completed", attempt_count=1
        )
        mock_cleanup_loop.return_value = (True, 0)
        mock_parse.return_value = None
        mock_cleanup.side_effect = Exception("Cannot remove worktree")
        stats = _run_worktree_agent(
            "Test", "maint-test", agent_item, "Prompt",
            Path("/fake/repo"), merge_changes=False
        )
        assert stats is None
        mock_add_uncleaned.assert_called_once()


class TestWorktreeAgentCleanupFailureSetsResultFalse:
    """Test that cleanup failure sets result.success=False (line 344)."""

    @patch('pokepoke.agents.agent_runner.handle_worktree_merge')
    @patch('pokepoke.agents.agent_runner.cleanup_worktree')
    @patch('pokepoke.agents.agent_runner.parse_agent_stats')
    @patch('pokepoke.agents.agent_runner.run_cleanup_loop')
    @patch('pokepoke.agents.agent_runner.invoke_copilot')
    @patch('pokepoke.agents.agent_runner.create_worktree')
    def test_cleanup_loop_failure_forces_result_false(
        self, mock_create: Mock, mock_invoke: Mock, mock_cleanup_loop: Mock,
        mock_parse: Mock, mock_cleanup: Mock, mock_handle_merge: Mock,
    ) -> None:
        """If cleanup loop returns success=False, overall result should be False."""
        agent_item = BeadsWorkItem(
            id="test-item", title="Test", description="Test",
            status="in_progress", priority=0, issue_type="task",
            labels=["maintenance"],
        )

        mock_create.return_value = Path("/fake/worktree")
        mock_invoke.return_value = CopilotResult(
            work_item_id="test-item", success=True,
            output="Completed", attempt_count=1,
        )
        # Cleanup loop fails — line 343-344 should set result.success = False
        mock_cleanup_loop.return_value = (False, 0)
        mock_parse.return_value = None
        mock_handle_merge.return_value = (False, False)
        mock_cleanup.return_value = True

        _run_worktree_agent(
            "Test", "test-item", agent_item, "Prompt",
            Path("/fake/repo"),
        )

        # Despite invoke_copilot returning success=True, the cleanup failure
        # should have set result.success=False, so no merge is attempted
        mock_handle_merge.assert_not_called()
