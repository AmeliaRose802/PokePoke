"""Unit tests for agent_runner module."""

from pathlib import Path
from unittest.mock import Mock, patch

from pokepoke.agents.agent_runner import (
    AgentRunnerConfig,
    _run_beads_only_agent,
)
from pokepoke.types import AgentStats, BeadsWorkItem, CopilotResult


class TestRunBeadsOnlyAgent:
    """Test _run_beads_only_agent function."""

    @patch('pokepoke.agents.agent_runner.parse_agent_stats')
    @patch('pokepoke.agents.agent_runner.invoke_copilot')
    def test_successful_beads_agent(
        self,
        mock_invoke: Mock,
        mock_parse: Mock
    ) -> None:
        """Test successful beads-only agent."""
        agent_item = BeadsWorkItem(
            id="maintenance-test",
            title="Test Maintenance",
            description="Test",
            status="in_progress",
            priority=0,
            issue_type="task",
            labels=["maintenance"]
        )

        config = AgentRunnerConfig(
            agent_name="Test",
            agent_id="maintenance-test",
            agent_item=agent_item,
            repo_root=Path.cwd(),
            worktree_path=Path.cwd(),
            model=None,
            item_logger=None,
        )

        mock_invoke.return_value = CopilotResult(
            work_item_id="maintenance-test",
            success=True,
            output="Completed",
            attempt_count=1
        )
        mock_parse.return_value = AgentStats(
            wall_duration=10.0,
            api_duration=5.0,
            input_tokens=100,
            output_tokens=50,
            lines_added=0,
            lines_removed=0,
            premium_requests=1
        )

        stats = _run_beads_only_agent(config, "Test prompt")

        assert stats is not None
        mock_invoke.assert_called_once_with(
            agent_item,
            prompt="Test prompt",
            deny_write=True,
            model=None,
            cwd=None,
            item_logger=None,
            add_parent_dir=False,
        )

    @patch('pokepoke.agents.agent_runner.invoke_copilot')
    def test_failed_beads_agent(self, mock_invoke: Mock) -> None:
        """Test failed beads-only agent."""
        agent_item = BeadsWorkItem(
            id="maintenance-test",
            title="Test Maintenance",
            description="Test",
            status="in_progress",
            priority=0,
            issue_type="task",
            labels=["maintenance"]
        )

        config = AgentRunnerConfig(
            agent_name="Test",
            agent_id="maintenance-test",
            agent_item=agent_item,
            repo_root=Path.cwd(),
            worktree_path=Path.cwd(),
            model=None,
            item_logger=None,
        )

        mock_invoke.return_value = CopilotResult(
            work_item_id="maintenance-test",
            success=False,
            output="",
            error="Agent failed",
            attempt_count=1
        )

        stats = _run_beads_only_agent(config, "Test prompt")

        assert stats is None

    @patch('pokepoke.agents.agent_runner.invoke_copilot')
    def test_successful_agent_no_parseable_stats_returns_default_stats(self, mock_invoke: Mock) -> None:
        """Test that a successful agent with no parseable stats returns default AgentStats, not None.

        Regression test for PokePoke-tl06: maintenance scheduler marked agents as
        FAILURE when they succeeded but produced no parseable stats output.
        """
        agent_item = BeadsWorkItem(
            id="maintenance-test",
            title="Test Maintenance",
            description="Test",
            status="in_progress",
            priority=0,
            issue_type="task",
            labels=["maintenance"]
        )

        config = AgentRunnerConfig(
            agent_name="Test",
            agent_id="maintenance-test",
            agent_item=agent_item,
            repo_root=Path.cwd(),
            worktree_path=Path.cwd(),
            model=None,
            item_logger=None,
        )

        mock_invoke.return_value = CopilotResult(
            work_item_id="maintenance-test",
            success=True,
            output="Agent completed all tasks successfully. No stats block.",
            attempt_count=1
        )

        stats = _run_beads_only_agent(config, "Test prompt")

        # Should return a default AgentStats (not None) so the scheduler
        # correctly identifies this as a success.
        assert stats is not None
        assert isinstance(stats, AgentStats)
        assert stats.wall_duration == 0.0
