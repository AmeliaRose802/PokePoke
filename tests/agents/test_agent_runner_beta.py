"""Unit tests for agent_runner module."""

from unittest.mock import MagicMock, Mock, patch

from pokepoke.types import AgentStats


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


class TestRunBetaTester:
    """Test run_beta_tester function."""

    @patch('pokepoke.agents.beta_tester.terminal_ui')
    @patch('pokepoke.agents.beta_tester.get_config')
    @patch('pokepoke.agents.agent_runner._run_worktree_agent')
    @patch('pokepoke.agents.beta_tester.get_pokepoke_prompts_dir')
    @patch('pokepoke.agents.beta_tester.subprocess.run')
    @patch('pathlib.Path.exists')
    @patch('pathlib.Path.read_text')
    def test_beta_tester_success(  # noqa: PLR0913
        self,
        mock_read: Mock,
        mock_exists: Mock,
        mock_run: Mock,
        mock_get_prompts: Mock,
        mock_worktree_agent: Mock,
        mock_get_config: Mock,
        mock_ui: Mock,
    ) -> None:
        """Test successful beta tester run."""
        mock_get_config.return_value = _mcp_enabled_config()
        # First exists() at line 47 → False (skip resolve(strict=True)),
        # second exists() at line 54 → True (enter else → subprocess.run called)
        mock_exists.side_effect = [False, True]
        mock_read.return_value = "Beta test prompt"
        mock_run.return_value = Mock(returncode=0)

        mock_worktree_agent.return_value = AgentStats(
            wall_duration=10.0,
            api_duration=5.0,
            input_tokens=100,
            output_tokens=50,
            lines_added=10,
            lines_removed=5,
            premium_requests=1
        )

        # Mock prompts dir
        mock_dir = MagicMock()
        mock_get_prompts.return_value = mock_dir
        mock_file = Mock()
        mock_file.exists.return_value = True
        mock_file.read_text.return_value = "Beta test prompt"
        mock_dir.__truediv__.return_value = mock_file

        from pokepoke.agents.agent_runner import run_beta_tester
        stats = run_beta_tester()

        assert stats is not None
        assert stats.wall_duration == 10.0
        mock_worktree_agent.assert_called_once()
        # Verify call args have merge_changes=False
        _args, kwargs = mock_worktree_agent.call_args
        assert kwargs.get('merge_changes') is False
        mock_run.assert_called()  # Restart script

    @patch('pokepoke.agents.beta_tester.terminal_ui')
    @patch('pokepoke.agents.beta_tester.get_config')
    @patch('pokepoke.agents.agent_runner._run_worktree_agent')
    @patch('pokepoke.agents.beta_tester.get_pokepoke_prompts_dir')
    @patch('pokepoke.agents.beta_tester.subprocess.run')
    @patch('pathlib.Path.exists')
    @patch('pathlib.Path.read_text')
    def test_beta_tester_restart_missing_keeps_going(  # noqa: PLR0913
        self,
        mock_read: Mock,
        mock_exists: Mock,
        mock_run: Mock,
        mock_get_prompts: Mock,
        mock_worktree_agent: Mock,
        mock_get_config: Mock,
        mock_ui: Mock,
    ) -> None:
        """Test restart script missing but proceeds."""
        mock_get_config.return_value = _mcp_enabled_config()
        # restart_script.exists() -> False both times (script missing)
        # prompt_path.exists() comes from the Mock object, not patched Path.exists
        mock_exists.side_effect = [False, False]
        mock_read.return_value = "prompt"

        mock_worktree_agent.return_value = AgentStats(
            wall_duration=10.0,
            api_duration=5.0,
            input_tokens=100,
            output_tokens=50,
            lines_added=10,
            lines_removed=5,
            premium_requests=1
        )

        mock_dir = MagicMock()
        mock_get_prompts.return_value = mock_dir
        mock_file = Mock()
        mock_file.exists.return_value = True
        mock_file.read_text.return_value = "prompt"
        mock_dir.__truediv__.return_value = mock_file

        from pokepoke.agents.agent_runner import run_beta_tester
        stats = run_beta_tester()

        assert stats is not None # It proceeded!
        mock_run.assert_not_called() # Did not run restart

    @patch('pokepoke.agents.beta_tester.terminal_ui')
    @patch('pokepoke.agents.beta_tester.get_config')
    @patch('pokepoke.agents.beta_tester.get_pokepoke_prompts_dir')
    @patch('pokepoke.agents.beta_tester.subprocess.run')
    @patch('pathlib.Path.exists')
    def test_beta_tester_prompt_missing(
        self,
        mock_exists: Mock,
        mock_run: Mock,
        mock_get_prompts: Mock,
        mock_get_config: Mock,
        mock_ui: Mock,
    ) -> None:
        """Test prompt file missing returns None."""
        mock_get_config.return_value = _mcp_enabled_config()
        # restart_script.exists() -> True
        # prompt_path.exists() -> False
        mock_exists.side_effect = [True, False]
        mock_run.return_value = Mock(returncode=0)

        mock_dir = MagicMock()
        mock_get_prompts.return_value = mock_dir
        mock_file = Mock()
        mock_file.exists.return_value = False # Explicitly false here too
        mock_dir.__truediv__.return_value = mock_file

        from pokepoke.agents.agent_runner import run_beta_tester
        stats = run_beta_tester()
        assert stats is None

    @patch('pokepoke.agents.beta_tester.terminal_ui')
    @patch('pokepoke.agents.beta_tester.get_config')
    @patch('pokepoke.agents.agent_runner._run_worktree_agent')
    @patch('pokepoke.agents.beta_tester.get_pokepoke_prompts_dir')
    @patch('pokepoke.agents.beta_tester.subprocess.run')
    @patch('pathlib.Path.exists')
    @patch('pathlib.Path.read_text')
    def test_beta_tester_invoke_failure(  # noqa: PLR0913
        self,
        mock_read: Mock,
        mock_exists: Mock,
        mock_run: Mock,
        mock_get_prompts: Mock,
        mock_worktree_agent: Mock,
        mock_get_config: Mock,
        mock_ui: Mock,
    ) -> None:
        """Test beta tester returns None on invocation failure."""
        mock_get_config.return_value = _mcp_enabled_config()
        mock_exists.return_value = True
        mock_read.return_value = "prompt"
        mock_run.return_value = Mock(returncode=0)

        # Mock prompts dir
        mock_dir = MagicMock()
        mock_get_prompts.return_value = mock_dir
        mock_file = Mock()
        mock_file.exists.return_value = True
        mock_file.read_text.return_value = "prompt"
        mock_dir.__truediv__.return_value = mock_file

        mock_worktree_agent.return_value = None

        from pokepoke.agents.agent_runner import run_beta_tester
        stats = run_beta_tester()
        assert stats is None

    @patch('pokepoke.agents.beta_tester.terminal_ui')
    @patch('pokepoke.agents.beta_tester.get_config')
    @patch('pokepoke.agents.agent_runner._run_worktree_agent')
    @patch('pokepoke.agents.beta_tester.get_pokepoke_prompts_dir')
    @patch('pokepoke.agents.beta_tester.subprocess.run')
    @patch('pathlib.Path.exists')
    @patch('pathlib.Path.read_text')
    def test_beta_tester_restart_failure_keeps_going(  # noqa: PLR0913
        self,
        mock_read: Mock,
        mock_exists: Mock,
        mock_run: Mock,
        mock_get_prompts: Mock,
        mock_worktree_agent: Mock,
        mock_get_config: Mock,
        mock_ui: Mock,
    ) -> None:
        """Test restart script execution failure but proceeds."""
        mock_get_config.return_value = _mcp_enabled_config()
        # First exists() at line 47 → False (skip resolve(strict=True)),
        # second exists() at line 54 → True (enter else → subprocess.run called)
        mock_exists.side_effect = [False, True]
        mock_read.return_value = "prompt"

        # Restart fails
        mock_run.return_value = Mock(returncode=1, stdout="Error")

        mock_worktree_agent.return_value = AgentStats(
            wall_duration=10.0,
            api_duration=5.0,
            input_tokens=100,
            output_tokens=50,
            lines_added=10,
            lines_removed=5,
            premium_requests=1
        )

        mock_dir = MagicMock()
        mock_get_prompts.return_value = mock_dir
        mock_file = Mock()
        mock_file.exists.return_value = True
        mock_file.read_text.return_value = "prompt"
        mock_dir.__truediv__.return_value = mock_file

        from pokepoke.agents.agent_runner import run_beta_tester
        stats = run_beta_tester()

        assert stats is not None
        mock_run.assert_called_once()
