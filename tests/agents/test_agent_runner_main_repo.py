"""Unit tests for agent_runner module."""

from pathlib import Path
from unittest.mock import Mock, patch

from pokepoke.agents.agent_runner import AgentRunnerConfig
from pokepoke.types import AgentStats, BeadsWorkItem
from pokepoke.types_agent import CopilotResult


class TestRunMainRepoAgent:
    """Test _run_main_repo_agent function."""

    @patch('pokepoke.agents.simple_runners.parse_agent_stats')
    @patch('pokepoke.agents.simple_runners.invoke_copilot')
    def test_successful_main_repo_agent(
        self,
        mock_invoke: Mock,
        mock_parse: Mock
    ) -> None:
        """Test successful main repo agent with write access."""
        from pokepoke.agents.agent_runner import _run_main_repo_agent

        agent_item = BeadsWorkItem(
            id="worktree-cleanup",
            title="Worktree Cleanup",
            description="Clean up worktrees",
            status="in_progress",
            priority=0,
            issue_type="task",
            labels=["maintenance"]
        )

        config = AgentRunnerConfig(
            agent_name="Worktree Cleanup",
            agent_id="worktree-cleanup",
            agent_item=agent_item,
            repo_root=Path.cwd(),
            worktree_path=Path.cwd(),
            model=None,
            item_logger=None,
        )

        mock_invoke.return_value = CopilotResult(
            work_item_id="worktree-cleanup",
            success=True,
            output="Completed cleanup",
            attempt_count=1
        )
        mock_parse.return_value = AgentStats(
            wall_duration=15.0,
            api_duration=8.0,
            input_tokens=200,
            output_tokens=100,
            lines_added=0,
            lines_removed=0,
            premium_requests=1
        )

        stats = _run_main_repo_agent(config, "cleanup prompt")

        assert stats is not None
        assert stats.wall_duration == 15.0
        # Verify deny_write=False (write access enabled)
        mock_invoke.assert_called_once_with(
            agent_item, prompt="cleanup prompt", deny_write=False, model=None, cwd=None, item_logger=None, add_parent_dir=False
        )

    @patch('pokepoke.agents.simple_runners.invoke_copilot')
    def test_failed_main_repo_agent(self, mock_invoke: Mock) -> None:
        """Test failed main repo agent returns None."""
        from pokepoke.agents.agent_runner import _run_main_repo_agent

        agent_item = BeadsWorkItem(
            id="worktree-cleanup",
            title="Worktree Cleanup",
            description="Clean up worktrees",
            status="in_progress",
            priority=0,
            issue_type="task",
            labels=["maintenance"]
        )

        config = AgentRunnerConfig(
            agent_name="Worktree Cleanup",
            agent_id="worktree-cleanup",
            agent_item=agent_item,
            repo_root=Path.cwd(),
            worktree_path=Path.cwd(),
            model=None,
            item_logger=None,
        )

        mock_invoke.return_value = CopilotResult(
            work_item_id="worktree-cleanup",
            success=False,
            output="",
            error="Agent crashed",
            attempt_count=1
        )

        stats = _run_main_repo_agent(config, "cleanup prompt")
        assert stats is None

    @patch('pokepoke.agents.simple_runners.parse_agent_stats')
    @patch('pokepoke.agents.simple_runners.invoke_copilot')
    def test_main_repo_agent_write_access_not_denied(
        self,
        mock_invoke: Mock,
        mock_parse: Mock
    ) -> None:
        """Verify main repo agent does NOT use deny_write=True."""
        from pokepoke.agents.agent_runner import _run_main_repo_agent

        agent_item = BeadsWorkItem(
            id="test-agent",
            title="Test",
            description="Test",
            status="in_progress",
            priority=0,
            issue_type="task",
            labels=[]
        )

        config = AgentRunnerConfig(
            agent_name="Test",
            agent_id="test-agent",
            agent_item=agent_item,
            repo_root=Path.cwd(),
            worktree_path=Path.cwd(),
            model=None,
            item_logger=None,
        )

        mock_invoke.return_value = CopilotResult(
            work_item_id="test-agent",
            success=True,
            output="Done",
            attempt_count=1
        )
        mock_parse.return_value = None

        _run_main_repo_agent(config, "prompt")

        _, kwargs = mock_invoke.call_args
        assert kwargs['deny_write'] is False

    @patch('pokepoke.agents.simple_runners.parse_agent_stats')
    @patch('pokepoke.agents.simple_runners.invoke_copilot')
    def test_main_repo_agent_with_model(
        self,
        mock_invoke: Mock,
        mock_parse: Mock
    ) -> None:
        """Test main repo agent passes model parameter."""
        from pokepoke.agents.agent_runner import _run_main_repo_agent

        agent_item = BeadsWorkItem(
            id="test",
            title="Test",
            description="Test",
            status="in_progress",
            priority=0,
            issue_type="task",
            labels=[]
        )

        config = AgentRunnerConfig(
            agent_name="Test",
            agent_id="test",
            agent_item=agent_item,
            repo_root=Path.cwd(),
            worktree_path=Path.cwd(),
            model="gpt-5.1-codex",
            item_logger=None,
        )

        mock_invoke.return_value = CopilotResult(
            work_item_id="test",
            success=True,
            output="Done",
            attempt_count=1
        )
        mock_parse.return_value = None

        _run_main_repo_agent(config, "prompt")

        _, kwargs = mock_invoke.call_args
        assert kwargs['model'] == "gpt-5.1-codex"
