"""Unit tests for agent_runner module."""

import logging
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

from pokepoke.agents.agent_runner import (
    run_maintenance_agent,
)
from pokepoke.types import AgentStats


class TestRunMaintenanceAgent:
    """Test run_maintenance_agent function."""

    @patch('pokepoke.agents.agent_runner._run_beads_only_agent')
    @patch('pathlib.Path.read_text')
    @patch('pathlib.Path.exists')
    @patch('pathlib.Path.cwd')
    def test_beads_only_agent(
        self,
        mock_cwd: Mock,
        mock_exists: Mock,
        mock_read: Mock,
        mock_run_beads: Mock
    ) -> None:
        """Test running beads-only maintenance agent."""
        mock_cwd.return_value = Path("/fake/repo")
        mock_exists.return_value = True
        mock_read.return_value = "Agent instructions"
        mock_run_beads.return_value = AgentStats(
            wall_duration=10.0,
            api_duration=5.0,
            input_tokens=100,
            output_tokens=50,
            lines_added=0,
            lines_removed=0,
            premium_requests=1
        )

        stats = run_maintenance_agent(
            "TestAgent",
            "test.md",
            needs_worktree=False
        )

        assert stats is not None
        assert stats.wall_duration == 10.0
        mock_run_beads.assert_called_once()

    @patch('pokepoke.agents.agent_runner._run_worktree_agent')
    @patch('pathlib.Path.read_text')
    @patch('pathlib.Path.exists')
    @patch('pathlib.Path.cwd')
    def test_worktree_agent(
        self,
        mock_cwd: Mock,
        mock_exists: Mock,
        mock_read: Mock,
        mock_run_wt: Mock
    ) -> None:
        """Test running worktree maintenance agent."""
        mock_cwd.return_value = Path("/fake/repo")
        mock_exists.return_value = True
        mock_read.return_value = "Agent instructions"
        mock_run_wt.return_value = AgentStats(
            wall_duration=20.0,
            api_duration=10.0,
            input_tokens=200,
            output_tokens=100,
            lines_added=10,
            lines_removed=5,
            premium_requests=2
        )

        stats = run_maintenance_agent(
            "TestAgent",
            "test.md",
            needs_worktree=True
        )

        assert stats is not None
        assert stats.wall_duration == 20.0
        mock_run_wt.assert_called_once()

    @patch('pathlib.Path.exists')
    @patch('pathlib.Path.cwd')
    def test_missing_prompt_file(self, mock_cwd: Mock, mock_exists: Mock) -> None:
        """Test maintenance agent with missing prompt file."""
        mock_cwd.return_value = Path("/fake/repo")
        mock_exists.return_value = False

        stats = run_maintenance_agent("TestAgent", "missing.md")

        assert stats is None

    @patch('pokepoke.agents.agent_runner.get_pokepoke_prompts_dir')
    def test_prompts_dir_not_found(self, mock_get_dir: Mock) -> None:
        """Test maintenance agent when prompts directory not found."""
        mock_get_dir.side_effect = FileNotFoundError("Prompts directory not found")

        stats = run_maintenance_agent("TestAgent", "test.md")

        assert stats is None

    @patch('pokepoke.agents.agent_runner.get_pokepoke_prompts_dir')
    def test_missing_prompt_shows_agent_name_in_error(self, mock_get_dir: Mock, caplog) -> None:
        """Test that missing prompt error includes agent name and available prompts."""
        fake_dir = Path(__file__).parent
        mock_get_dir.return_value = fake_dir

        with caplog.at_level(logging.DEBUG, logger="pokepoke.agents.agent_runner"):
            stats = run_maintenance_agent("Backlog Cleanup", "nonexistent-prompt.md")

        assert stats is None
        assert "Backlog Cleanup" in caplog.text
        assert "nonexistent-prompt.md" in caplog.text
        assert "failed to start" in caplog.text

    @patch('pokepoke.agents.agent_runner.get_pokepoke_prompts_dir')
    def test_prompts_dir_not_found_shows_agent_name(self, mock_get_dir: Mock, caplog) -> None:
        """Test that prompts dir not found error includes agent name."""
        mock_get_dir.side_effect = FileNotFoundError("Prompts directory not found")

        with caplog.at_level(logging.DEBUG, logger="pokepoke.agents.agent_runner"):
            stats = run_maintenance_agent("Code Review", "code-reviewer.md")

        assert stats is None
        assert "Code Review" in caplog.text
        assert "failed to start" in caplog.text


class TestMaintenanceAgentPromptMissing:
    """Test run_maintenance_agent prompt file not found (lines 139-140)."""

    @patch('pokepoke.agents.agent_runner.get_pokepoke_prompts_dir')
    def test_prompt_file_doesnt_exist(self, mock_get_dir: Mock) -> None:
        mock_dir = MagicMock()
        mock_prompt_path = MagicMock()
        mock_prompt_path.exists.return_value = False
        mock_dir.__truediv__ = Mock(return_value=mock_prompt_path)
        mock_get_dir.return_value = mock_dir
        stats = run_maintenance_agent("TestAgent", "missing.md", needs_worktree=False)
        assert stats is None
