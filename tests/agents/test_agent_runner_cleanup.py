"""Unit tests for agent_runner module."""

from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

from pokepoke.types import AgentStats


class TestRunWorktreeCleanup:
    """Test run_worktree_cleanup function."""

    @patch('pokepoke.agents.agent_runner.get_uncleaned_worktree_count', return_value=0)
    @patch('pokepoke.agents.agent_runner.has_unmerged_worktrees', return_value=True)
    @patch('pokepoke.agents.agent_runner._run_main_repo_agent')
    @patch('pokepoke.agents.agent_runner.get_pokepoke_prompts_dir')
    def test_worktree_cleanup_success(
        self,
        mock_get_prompts: Mock,
        mock_main_repo_agent: Mock,
        mock_has_worktrees: Mock,
        mock_uncleaned_count: Mock
    ) -> None:
        """Test successful worktree cleanup run."""
        mock_dir = MagicMock()
        mock_get_prompts.return_value = mock_dir
        mock_file = Mock()
        mock_file.exists.return_value = True
        mock_file.read_text.return_value = "Worktree cleanup prompt"
        mock_dir.__truediv__.return_value = mock_file

        mock_main_repo_agent.return_value = AgentStats(
            wall_duration=30.0,
            api_duration=15.0,
            input_tokens=500,
            output_tokens=200,
            lines_added=0,
            lines_removed=0,
            premium_requests=2
        )

        from pokepoke.agents.agent_runner import run_worktree_cleanup
        stats = run_worktree_cleanup()

        assert stats is not None
        assert stats.wall_duration == 30.0
        mock_main_repo_agent.assert_called_once()
        # Verify it uses _run_main_repo_agent (not worktree or beads-only)
        args, _ = mock_main_repo_agent.call_args
        # First arg is now AgentRunnerConfig
        assert args[0].agent_name == "Worktree Cleanup"

    @patch('pokepoke.agents.agent_runner.get_uncleaned_worktree_count', return_value=0)
    @patch('pokepoke.agents.agent_runner.has_unmerged_worktrees', return_value=True)
    @patch('pokepoke.agents.agent_runner._run_main_repo_agent')
    @patch('pokepoke.agents.agent_runner.get_pokepoke_prompts_dir')
    def test_worktree_cleanup_failure(
        self,
        mock_get_prompts: Mock,
        mock_main_repo_agent: Mock,
        mock_has_worktrees: Mock,
        mock_uncleaned_count: Mock
    ) -> None:
        """Test worktree cleanup returns None on failure."""
        mock_dir = MagicMock()
        mock_get_prompts.return_value = mock_dir
        mock_file = Mock()
        mock_file.exists.return_value = True
        mock_file.read_text.return_value = "prompt"
        mock_dir.__truediv__.return_value = mock_file

        mock_main_repo_agent.return_value = None

        from pokepoke.agents.agent_runner import run_worktree_cleanup
        stats = run_worktree_cleanup()
        assert stats is None

    @patch('pokepoke.agents.agent_runner.get_uncleaned_worktree_count', return_value=0)
    @patch('pokepoke.agents.agent_runner.has_unmerged_worktrees', return_value=True)
    @patch('pokepoke.agents.agent_runner.get_pokepoke_prompts_dir')
    def test_worktree_cleanup_prompt_missing(
        self,
        mock_get_prompts: Mock,
        mock_has_worktrees: Mock,
        mock_uncleaned_count: Mock
    ) -> None:
        """Test worktree cleanup when prompt file is missing."""
        mock_dir = MagicMock()
        mock_get_prompts.return_value = mock_dir
        mock_file = Mock()
        mock_file.exists.return_value = False
        mock_dir.__truediv__.return_value = mock_file

        from pokepoke.agents.agent_runner import run_worktree_cleanup
        stats = run_worktree_cleanup()
        assert stats is None

    @patch('pokepoke.agents.agent_runner.get_uncleaned_worktree_count', return_value=0)
    @patch('pokepoke.agents.agent_runner.has_unmerged_worktrees', return_value=True)
    @patch('pokepoke.agents.agent_runner.get_pokepoke_prompts_dir')
    def test_worktree_cleanup_prompts_dir_not_found(
        self,
        mock_get_prompts: Mock,
        mock_has_worktrees: Mock,
        mock_uncleaned_count: Mock
    ) -> None:
        """Test worktree cleanup when prompts directory not found."""
        mock_get_prompts.side_effect = FileNotFoundError("Prompts not found")

        from pokepoke.agents.agent_runner import run_worktree_cleanup
        stats = run_worktree_cleanup()
        assert stats is None

    @patch('pokepoke.agents.agent_runner.get_uncleaned_worktree_count', return_value=0)
    @patch('pokepoke.agents.agent_runner.has_unmerged_worktrees', return_value=True)
    @patch('pokepoke.agents.agent_runner._run_main_repo_agent')
    @patch('pokepoke.agents.agent_runner.get_pokepoke_prompts_dir')
    def test_worktree_cleanup_with_repo_root_passes_cwd(
        self,
        mock_get_prompts: Mock,
        mock_main_repo_agent: Mock,
        mock_has_worktrees: Mock,
        mock_uncleaned_count: Mock
    ) -> None:
        """Test worktree cleanup passes repo_root as cwd instead of chdir."""
        mock_dir = MagicMock()
        mock_get_prompts.return_value = mock_dir
        mock_file = Mock()
        mock_file.exists.return_value = True
        mock_file.read_text.return_value = "prompt"
        mock_dir.__truediv__.return_value = mock_file

        mock_main_repo_agent.return_value = None

        from pokepoke.agents.agent_runner import run_worktree_cleanup
        run_worktree_cleanup(repo_root=Path("/main/repo"))

        # Should pass cwd to _run_main_repo_agent instead of using os.chdir
        mock_main_repo_agent.assert_called_once()
        _, kwargs = mock_main_repo_agent.call_args
        assert kwargs.get("cwd") == str(Path("/main/repo"))

    @patch('pokepoke.agents.agent_runner.get_uncleaned_worktree_count', return_value=0)
    @patch('pokepoke.agents.agent_runner.has_unmerged_worktrees', return_value=True)
    @patch('pokepoke.agents.agent_runner._run_main_repo_agent')
    @patch('pokepoke.agents.agent_runner.get_pokepoke_prompts_dir')
    def test_worktree_cleanup_error_returns_none(
        self,
        mock_get_prompts: Mock,
        mock_main_repo_agent: Mock,
        mock_has_worktrees: Mock,
        mock_uncleaned_count: Mock
    ) -> None:
        """Worktree cleanup swallows agent exceptions and returns None (PokePoke-5arw).

        Previously the exception was re-raised, causing the orchestrator to crash
        with exit code 1. Now it is logged and None is returned so the orchestrator
        can continue processing items.
        """
        mock_dir = MagicMock()
        mock_get_prompts.return_value = mock_dir
        mock_file = Mock()
        mock_file.exists.return_value = True
        mock_file.read_text.return_value = "prompt"
        mock_dir.__truediv__.return_value = mock_file

        mock_main_repo_agent.side_effect = RuntimeError("Agent exploded")

        from pokepoke.agents.agent_runner import run_worktree_cleanup
        result = run_worktree_cleanup(repo_root=Path("/main/repo"))

        # Must NOT raise; must return None so the orchestrator keeps running.
        assert result is None

    @patch('pokepoke.agents.agent_runner.get_uncleaned_worktree_count', return_value=0)
    @patch('pokepoke.agents.agent_runner.has_unmerged_worktrees', return_value=True)
    @patch('pokepoke.agents.agent_runner._run_main_repo_agent')
    @patch('pokepoke.agents.agent_runner.get_pokepoke_prompts_dir')
    def test_worktree_cleanup_no_repo_root_no_chdir(
        self,
        mock_get_prompts: Mock,
        mock_main_repo_agent: Mock,
        mock_has_worktrees: Mock,
        mock_uncleaned_count: Mock
    ) -> None:
        """Test worktree cleanup without repo_root doesn't change directory."""
        mock_dir = MagicMock()
        mock_get_prompts.return_value = mock_dir
        mock_file = Mock()
        mock_file.exists.return_value = True
        mock_file.read_text.return_value = "prompt"
        mock_dir.__truediv__.return_value = mock_file

        mock_main_repo_agent.return_value = None

        with patch('os.chdir') as mock_chdir:
            from pokepoke.agents.agent_runner import run_worktree_cleanup
            run_worktree_cleanup()  # No repo_root
            mock_chdir.assert_not_called()

    @patch('pokepoke.agents.agent_runner.get_uncleaned_worktree_count', return_value=0)
    @patch('pokepoke.agents.agent_runner.has_unmerged_worktrees', return_value=True)
    @patch('pokepoke.agents.agent_runner._run_main_repo_agent')
    @patch('pokepoke.agents.agent_runner.get_pokepoke_prompts_dir')
    def test_worktree_cleanup_loads_correct_prompt_file(
        self,
        mock_get_prompts: Mock,
        mock_main_repo_agent: Mock,
        mock_has_worktrees: Mock,
        mock_uncleaned_count: Mock
    ) -> None:
        """Test worktree cleanup loads worktree-cleanup.md prompt."""
        mock_dir = MagicMock()
        mock_get_prompts.return_value = mock_dir
        mock_file = Mock()
        mock_file.exists.return_value = True
        mock_file.read_text.return_value = "Worktree cleanup instructions"
        mock_dir.__truediv__.return_value = mock_file

        mock_main_repo_agent.return_value = None

        from pokepoke.agents.agent_runner import run_worktree_cleanup
        run_worktree_cleanup()

        # Verify it loads worktree-cleanup.md
        mock_dir.__truediv__.assert_called_with("worktree-cleanup.md")

    @patch('pokepoke.agents.agent_runner.has_unmerged_worktrees', return_value=False)
    def test_worktree_cleanup_skipped_when_no_worktrees(
        self,
        mock_has_worktrees: Mock
    ) -> None:
        """Test worktree cleanup is skipped when no unmerged worktrees detected."""
        from pokepoke.agents.agent_runner import run_worktree_cleanup
        stats = run_worktree_cleanup()
        assert stats is None

    @patch('pokepoke.worktrees.worktree_cleanup.load_worktree_manifest', return_value={})
    @patch('pokepoke.git.git_operations.list_worktrees')
    def test_has_unmerged_worktrees_with_task_worktree(
        self,
        mock_list: Mock,
        mock_manifest: Mock
    ) -> None:
        """Test has_unmerged_worktrees returns True when task worktrees exist."""
        mock_list.return_value = [
            {"path": "/repo", "branch": "refs/heads/main"},
            {"path": "/repo/worktrees/task-abc", "branch": "refs/heads/task/abc"},
        ]
        from pokepoke.worktrees.worktree_cleanup import has_unmerged_worktrees
        assert has_unmerged_worktrees() is True

    @patch('pokepoke.worktrees.worktree_cleanup.load_worktree_manifest')
    @patch('pokepoke.git.git_operations.list_worktrees', return_value=[
        {"path": "/repo", "branch": "refs/heads/main"}
    ])
    def test_has_unmerged_worktrees_manifest_only(
        self,
        mock_list: Mock,
        mock_manifest: Mock
    ) -> None:
        """Test has_unmerged_worktrees returns True when manifest has entries."""
        mock_manifest.return_value = {"old-task": {"path": "/repo/worktrees/task-old", "reason": "failed"}}
        from pokepoke.worktrees.worktree_cleanup import has_unmerged_worktrees
        assert has_unmerged_worktrees() is True

    @patch('pokepoke.worktrees.worktree_cleanup.load_worktree_manifest', return_value={})
    @patch('pokepoke.git.git_operations.list_worktrees', return_value=[
        {"path": "/repo", "branch": "refs/heads/main"}
    ])
    def test_has_unmerged_worktrees_none_found(
        self,
        mock_list: Mock,
        mock_manifest: Mock
    ) -> None:
        """Test has_unmerged_worktrees returns False when nothing to clean."""
        from pokepoke.worktrees.worktree_cleanup import has_unmerged_worktrees
        assert has_unmerged_worktrees() is False


class TestWorktreeCleanupPreCleanupRetry:
    """Test run_worktree_cleanup pre-cleanup retry logic (lines 234-236)."""

    @patch('pokepoke.agents.agent_runner.retry_failed_cleanups', return_value=2)
    @patch('pokepoke.agents.agent_runner.get_uncleaned_worktree_count', return_value=3)
    @patch('pokepoke.agents.agent_runner.has_unmerged_worktrees', return_value=True)
    @patch('pokepoke.agents.agent_runner._run_main_repo_agent')
    @patch('pokepoke.agents.agent_runner.get_pokepoke_prompts_dir')
    def test_pre_cleanup_retries_failed_worktrees(
        self, mock_get_prompts: Mock, mock_main_repo: Mock,
        mock_has_worktrees: Mock, mock_uncleaned: Mock,
        mock_retry: Mock,
    ) -> None:
        """Pre-cleanup should retry failed worktree removals before running agent."""
        mock_dir = MagicMock()
        mock_get_prompts.return_value = mock_dir
        mock_file = Mock()
        mock_file.exists.return_value = True
        mock_file.read_text.return_value = "Cleanup prompt"
        mock_dir.__truediv__.return_value = mock_file
        mock_main_repo.return_value = None

        from pokepoke.agents.agent_runner import run_worktree_cleanup
        run_worktree_cleanup()

        mock_retry.assert_called_once()
        mock_uncleaned.assert_called_once()

    @patch('pokepoke.agents.agent_runner.get_uncleaned_worktree_count', return_value=0)
    @patch('pokepoke.agents.agent_runner.has_unmerged_worktrees', return_value=True)
    @patch('pokepoke.agents.agent_runner._run_main_repo_agent')
    @patch('pokepoke.agents.agent_runner.get_pokepoke_prompts_dir')
    def test_worktree_cleanup_passes_add_parent_dir(
        self,
        mock_get_prompts: Mock,
        mock_main_repo_agent: Mock,
        mock_has_worktrees: Mock,
        mock_uncleaned_count: Mock,
    ) -> None:
        """Cleanup agent should pass add_parent_dir=True for parent repo visibility."""
        mock_dir = MagicMock()
        mock_get_prompts.return_value = mock_dir
        mock_file = Mock()
        mock_file.exists.return_value = True
        mock_file.read_text.return_value = "Cleanup prompt"
        mock_dir.__truediv__.return_value = mock_file
        mock_main_repo_agent.return_value = None

        from pokepoke.agents.agent_runner import run_worktree_cleanup
        run_worktree_cleanup()

        _, kwargs = mock_main_repo_agent.call_args
        assert kwargs.get("add_parent_dir") is True
