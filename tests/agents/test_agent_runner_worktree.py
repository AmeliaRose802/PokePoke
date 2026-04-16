"""Unit tests for agent_runner module."""

import subprocess
from pathlib import Path
from unittest.mock import Mock, patch

from pokepoke.agents.agent_runner import (
    AgentRunnerConfig,
    _reconcile_worktree_branch,
)
from pokepoke.types import AgentStats, BeadsWorkItem
from pokepoke.types_agent import CopilotResult

# Import compat wrapper and alias it to _run_worktree_agent for backwards compatibility
from .conftest_agent_runner import run_worktree_agent_compat as _run_worktree_agent


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

        mock_create.side_effect = RuntimeError("Failed to create worktree")

        stats = _run_worktree_agent(
            "Test",
            "maintenance-test",
            agent_item,
            "Test prompt",
            Path("/fake/repo")
        )

        assert stats is None

    @patch('pokepoke.agents.agent_runner.worktree_branch_has_commits')
    @patch('pokepoke.agents.agent_runner.cleanup_worktree')
    @patch('pokepoke.agents.agent_runner.run_cleanup_loop')
    @patch('pokepoke.agents.agent_runner.invoke_copilot')
    @patch('pokepoke.agents.agent_runner.create_worktree')
    @patch('os.getcwd')
    @patch('os.chdir')
    def test_invoke_copilot_exception(
        self, mock_chdir: Mock, mock_getcwd: Mock,
        mock_create: Mock, mock_invoke: Mock, mock_cleanup_loop: Mock,
        mock_cleanup: Mock, mock_branch_has_commits: Mock,
    ) -> None:
        """Test exception handling when invoke_copilot raises."""
        mock_create.return_value = Path("/tmp/wt")
        mock_invoke.side_effect = RuntimeError("Boom")
        mock_cleanup_loop.return_value = (False, 0)
        mock_branch_has_commits.return_value = False
        mock_getcwd.return_value = "/tmp"

        item = BeadsWorkItem(
            id="1", title="T", description="D",
            status="open", priority=1, issue_type="task"
        )

        res = _run_worktree_agent("Agent", "1", item, "Prompt", Path("/repo"))

        assert res is None
        mock_cleanup.assert_not_called()

    @patch('pokepoke.agents.agent_runner.worktree_branch_has_commits')
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
        mock_cleanup: Mock,
        mock_branch_has_commits: Mock,
    ) -> None:
        """Test worktree agent when agent fails with no commits on branch."""
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
        mock_branch_has_commits.return_value = False

        stats = _run_worktree_agent(
            "Test",
            "maintenance-test",
            agent_item,
            "Test prompt",
            Path("/fake/repo")
        )

        assert stats is None
        mock_cleanup.assert_not_called()
        mock_branch_has_commits.assert_called_once()

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
        mock_cleanup.side_effect = RuntimeError("Cannot remove worktree")
        stats = _run_worktree_agent(
            "Test", "maint-test", agent_item, "Prompt",
            Path("/fake/repo"), merge_changes=False
        )
        assert stats is None
        mock_add_uncleaned.assert_called_once()


class TestWorktreeAgentCleanupFailureSetsResultFalse:
    """Test that cleanup failure sets result.success=False (line 344)."""

    @patch('pokepoke.agents.agent_runner.worktree_branch_has_commits')
    @patch('pokepoke.agents.agent_runner.handle_worktree_merge')
    @patch('pokepoke.agents.agent_runner.cleanup_worktree')
    @patch('pokepoke.agents.agent_runner.parse_agent_stats')
    @patch('pokepoke.agents.agent_runner.run_cleanup_loop')
    @patch('pokepoke.agents.agent_runner.invoke_copilot')
    @patch('pokepoke.agents.agent_runner.create_worktree')
    def test_cleanup_loop_failure_forces_result_false(
        self, mock_create: Mock, mock_invoke: Mock, mock_cleanup_loop: Mock,
        mock_parse: Mock, mock_cleanup: Mock, mock_handle_merge: Mock,
        mock_branch_has_commits: Mock,
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
        mock_branch_has_commits.return_value = False

        _run_worktree_agent(
            "Test", "test-item", agent_item, "Prompt",
            Path("/fake/repo"),
        )

        # Despite invoke_copilot returning success=True, the cleanup failure
        # should have set result.success=False, so no merge is attempted
        mock_handle_merge.assert_not_called()


class TestReconcileWorktreeBranch:
    """Tests for _reconcile_worktree_branch helper."""

    def _make_item(self, item_id: str = "test-item") -> BeadsWorkItem:
        return BeadsWorkItem(
            id=item_id, title="Test", description="Test",
            status="in_progress", priority=0, issue_type="task",
            labels=["maintenance"],
        )

    def _make_result(self, success: bool = False, output: str = "") -> CopilotResult:
        return CopilotResult(
            work_item_id="test-item", success=success,
            output=output, error="budget exhausted" if not success else "",
            attempt_count=1,
        )

    @patch('pokepoke.agents.agent_runner.handle_worktree_merge')
    @patch('pokepoke.agents.agent_runner.worktree_branch_has_commits')
    def test_no_commits_returns_none(
        self, mock_has_commits: Mock, mock_merge: Mock,
    ) -> None:
        """No commits on branch → returns None without attempting merge."""
        mock_has_commits.return_value = False

        config = AgentRunnerConfig(
            agent_name="Janitor",
            agent_id="agent-1",
            agent_item=self._make_item(),
            repo_root=Path("/repo"),
            worktree_path=Path("/wt"),
        )
        result = _reconcile_worktree_branch(config, self._make_result(), "parent")

        assert result is None
        mock_merge.assert_not_called()

    @patch('pokepoke.agents.agent_runner.handle_worktree_merge')
    @patch('pokepoke.agents.agent_runner.worktree_branch_has_commits')
    def test_commits_exist_merge_succeeds(
        self, mock_has_commits: Mock, mock_merge: Mock,
    ) -> None:
        """Commits on branch + merge succeeds → returns AgentStats."""
        mock_has_commits.return_value = True
        mock_merge.return_value = (True, True)

        config = AgentRunnerConfig(
            agent_name="Janitor",
            agent_id="agent-1",
            agent_item=self._make_item(),
            repo_root=Path("/repo"),
            worktree_path=Path("/wt"),
        )
        result = _reconcile_worktree_branch(config, self._make_result(), "parent")

        assert result is not None
        assert isinstance(result, AgentStats)
        mock_merge.assert_called_once()

    @patch('pokepoke.agents.agent_runner.handle_worktree_merge')
    @patch('pokepoke.agents.agent_runner.worktree_branch_has_commits')
    def test_commits_exist_merge_fails(
        self, mock_has_commits: Mock, mock_merge: Mock,
    ) -> None:
        """Commits on branch but merge fails → returns None."""
        mock_has_commits.return_value = True
        mock_merge.return_value = (False, False)

        config = AgentRunnerConfig(
            agent_name="Janitor",
            agent_id="agent-1",
            agent_item=self._make_item(),
            repo_root=Path("/repo"),
            worktree_path=Path("/wt"),
        )
        result = _reconcile_worktree_branch(config, self._make_result(), "parent")

        assert result is None
        mock_merge.assert_called_once()

    @patch('pokepoke.agents.agent_runner.handle_worktree_merge')
    @patch('pokepoke.agents.agent_runner.worktree_branch_has_commits')
    def test_commits_exist_with_output_parses_stats(
        self, mock_has_commits: Mock, mock_merge: Mock,
    ) -> None:
        """When output contains parseable stats, they are returned."""
        mock_has_commits.return_value = True
        mock_merge.return_value = (True, True)

        result_with_output = self._make_result(
            output='{"wall_duration": 42.0, "input_tokens": 500}'
        )

        config = AgentRunnerConfig(
            agent_name="Janitor",
            agent_id="agent-1",
            agent_item=self._make_item(),
            repo_root=Path("/repo"),
            worktree_path=Path("/wt"),
        )
        result = _reconcile_worktree_branch(config, result_with_output, "parent")

        assert result is not None

    @patch('pokepoke.agents.agent_runner.handle_worktree_merge')
    @patch('pokepoke.agents.agent_runner.worktree_branch_has_commits')
    def test_branch_check_exception_returns_none(
        self, mock_has_commits: Mock, mock_merge: Mock,
    ) -> None:
        """Exception in worktree_branch_has_commits → returns None safely."""
        mock_has_commits.side_effect = subprocess.CalledProcessError(1, "git")

        config = AgentRunnerConfig(
            agent_name="Janitor",
            agent_id="agent-1",
            agent_item=self._make_item(),
            repo_root=Path("/repo"),
            worktree_path=Path("/wt"),
        )
        result = _reconcile_worktree_branch(config, self._make_result(), "parent")

        assert result is None
        mock_merge.assert_not_called()


class TestWorktreeAgentFailureReconciliation:
    """Integration tests for reconciliation within _run_worktree_agent."""

    @patch('pokepoke.agents.agent_runner.handle_worktree_merge')
    @patch('pokepoke.agents.agent_runner.worktree_branch_has_commits')
    @patch('pokepoke.agents.agent_runner.run_cleanup_loop')
    @patch('pokepoke.agents.agent_runner.invoke_copilot')
    @patch('pokepoke.agents.agent_runner.create_worktree')
    def test_failure_with_commits_merges_partial_work(
        self, mock_create: Mock, mock_invoke: Mock,
        mock_cleanup_loop: Mock, mock_branch_has_commits: Mock,
        mock_merge: Mock,
    ) -> None:
        """Agent fails but branch has commits → reconciliation merges them."""
        agent_item = BeadsWorkItem(
            id="maint-1", title="Janitor", description="Cleanup",
            status="in_progress", priority=0, issue_type="task",
            labels=["maintenance"],
        )
        mock_create.return_value = Path("/fake/worktree")
        mock_invoke.return_value = CopilotResult(
            work_item_id="maint-1", success=False,
            output="", error="Budget exhausted", attempt_count=1,
        )
        mock_cleanup_loop.return_value = (True, 0)
        mock_branch_has_commits.return_value = True
        mock_merge.return_value = (True, True)

        stats = _run_worktree_agent(
            "Janitor", "maint-1", agent_item, "Prompt", Path("/repo"),
        )

        assert stats is not None
        assert isinstance(stats, AgentStats)
        mock_merge.assert_called_once()

    @patch('pokepoke.agents.agent_runner.handle_worktree_merge')
    @patch('pokepoke.agents.agent_runner.worktree_branch_has_commits')
    @patch('pokepoke.agents.agent_runner.run_cleanup_loop')
    @patch('pokepoke.agents.agent_runner.invoke_copilot')
    @patch('pokepoke.agents.agent_runner.create_worktree')
    def test_failure_with_commits_merge_fails_returns_none(
        self, mock_create: Mock, mock_invoke: Mock,
        mock_cleanup_loop: Mock, mock_branch_has_commits: Mock,
        mock_merge: Mock,
    ) -> None:
        """Agent fails, branch has commits, but merge also fails → None."""
        agent_item = BeadsWorkItem(
            id="maint-1", title="Janitor", description="Cleanup",
            status="in_progress", priority=0, issue_type="task",
            labels=["maintenance"],
        )
        mock_create.return_value = Path("/fake/worktree")
        mock_invoke.return_value = CopilotResult(
            work_item_id="maint-1", success=False,
            output="", error="Budget exhausted", attempt_count=1,
        )
        mock_cleanup_loop.return_value = (True, 0)
        mock_branch_has_commits.return_value = True
        mock_merge.return_value = (False, False)

        stats = _run_worktree_agent(
            "Janitor", "maint-1", agent_item, "Prompt", Path("/repo"),
        )

        assert stats is None

    @patch('pokepoke.agents.agent_runner.worktree_branch_has_commits')
    @patch('pokepoke.agents.agent_runner.run_cleanup_loop')
    @patch('pokepoke.agents.agent_runner.invoke_copilot')
    @patch('pokepoke.agents.agent_runner.create_worktree')
    def test_failure_merge_changes_false_skips_reconciliation(
        self, mock_create: Mock, mock_invoke: Mock,
        mock_cleanup_loop: Mock, mock_branch_has_commits: Mock,
    ) -> None:
        """With merge_changes=False, reconciliation is skipped even if commits exist."""
        agent_item = BeadsWorkItem(
            id="maint-1", title="Janitor", description="Cleanup",
            status="in_progress", priority=0, issue_type="task",
            labels=["maintenance"],
        )
        mock_create.return_value = Path("/fake/worktree")
        mock_invoke.return_value = CopilotResult(
            work_item_id="maint-1", success=False,
            output="", error="Budget exhausted", attempt_count=1,
        )
        mock_cleanup_loop.return_value = (True, 0)

        stats = _run_worktree_agent(
            "Janitor", "maint-1", agent_item, "Prompt",
            Path("/repo"), merge_changes=False,
        )

        assert stats is None
        mock_branch_has_commits.assert_not_called()


class TestWorktreeAgentSandbox:
    """Test that work agents are sandboxed without --add-dir parent repo access."""

    @patch('pokepoke.agents.agent_runner.handle_worktree_merge')
    @patch('pokepoke.agents.agent_runner.parse_agent_stats')
    @patch('pokepoke.agents.agent_runner.run_cleanup_loop')
    @patch('pokepoke.agents.agent_runner.invoke_copilot')
    @patch('pokepoke.agents.agent_runner.create_worktree')
    def test_worktree_agent_does_not_pass_add_parent_dir(
        self,
        mock_create: Mock,
        mock_invoke: Mock,
        mock_cleanup_loop: Mock,
        mock_parse: Mock,
        mock_handle_merge: Mock,
    ) -> None:
        """Work agents should NOT receive add_parent_dir — sandboxed to worktree only."""
        agent_item = BeadsWorkItem(
            id="work-1", title="Work", description="Work task",
            status="in_progress", priority=1, issue_type="task",
            labels=["orchestrator"],
        )

        mock_create.return_value = Path("/repo/worktrees/task-work-1")
        mock_invoke.return_value = CopilotResult(
            work_item_id="work-1", success=True, output="Done", attempt_count=1,
        )
        mock_cleanup_loop.return_value = (True, 0)
        mock_parse.return_value = AgentStats()
        mock_handle_merge.return_value = (True, True)

        _run_worktree_agent(
            "Work", "work-1", agent_item, "Prompt", Path("/repo"),
        )

        _, kwargs = mock_invoke.call_args
        # Work agents must not get add_parent_dir — the parameter should not be
        # passed (i.e. it uses the default False on invoke_copilot).
        assert kwargs.get("add_parent_dir", False) is False
