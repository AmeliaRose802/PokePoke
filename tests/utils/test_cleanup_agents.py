"""Tests for cleanup agents."""

import unittest.mock
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

from pokepoke.agents.cleanup_agents import (
    _apply_base_template_vars,
    _build_work_item_context,
    _get_current_git_context,
    _git_output,
    aggregate_cleanup_stats,
    get_pokepoke_prompts_dir,
    invoke_cleanup_agent,
    invoke_merge_conflict_cleanup_agent,
    load_prompt_file,
    run_cleanup_loop,
)
from pokepoke.types import AgentStats, BeadsWorkItem
from pokepoke.types_agent import CopilotResult


class TestCleanupAgents:
    """Test cleanup agent functions."""

    def test_get_prompts_dir(self):
        """Test finding prompts directory."""
        # The real .pokepoke/prompts/ directory exists in the repo
        result = get_pokepoke_prompts_dir()
        assert result.exists()
        assert result.name == "prompts"

    def test_get_prompts_dir_not_found(self, monkeypatch):
        """Test error when prompts directory not found."""
        import pokepoke.agents.cleanup_agents as mod
        # Use a path outside the repo tree so the walk-up won't find .pokepoke/prompts
        monkeypatch.setattr(mod, '__file__', r'C:\nonexistent\a\b\c\dummy.py')
        with pytest.raises(FileNotFoundError):
            get_pokepoke_prompts_dir()

    @patch('subprocess.run')
    @patch('os.getcwd')
    def test_get_current_git_context(self, mock_getcwd, mock_run):
        """Test getting git context."""
        mock_getcwd.return_value = "/test/dir"

        # Mock branch
        mock_branch = Mock()
        mock_branch.returncode = 0
        mock_branch.stdout = "main"

        # Mock worktree
        mock_worktree = Mock()
        mock_worktree.returncode = 0
        mock_worktree.stdout = "true"

        mock_run.side_effect = [mock_branch, mock_worktree]

        cwd, branch, is_worktree = _get_current_git_context()

        assert cwd == "/test/dir"
        assert branch == "main"
        assert is_worktree is True

    @patch('subprocess.run')
    def test_get_current_git_context_failure(self, mock_run):
        """Test getting git context when commands fail."""
        mock_run.side_effect = Exception("Git error")

        _cwd, branch, is_worktree = _get_current_git_context()

        assert branch == "unknown"
        assert is_worktree is False

    @patch('pokepoke.agents.cleanup_agents.merge_lock_active', return_value=False)
    @patch('pokepoke.agents.cleanup_agents.get_pokepoke_prompts_dir')
    @patch('pokepoke.agents.cleanup_agents._get_current_git_context')
    @patch('pokepoke.agents.cleanup_agents.invoke_copilot')
    def test_invoke_cleanup_agent(self, mock_invoke, mock_context, mock_get_dir, mock_merge_active):
        """Test invoking cleanup agent."""
        mock_dir = MagicMock()
        mock_file = Mock()
        mock_file.exists.return_value = True
        mock_file.read_text.return_value = "Instructions {cwd} {branch} {is_worktree}"
        mock_dir.__truediv__.return_value = mock_file
        mock_get_dir.return_value = mock_dir

        mock_context.return_value = ("/cur/dir", "feature", True)

        mock_invoke.return_value = CopilotResult(
            work_item_id="task-1",
            success=True,
            output="Done",
            attempt_count=1
        )

        item = BeadsWorkItem(
            id="123",
            title="Test",
            description="Desc",
            issue_type="task",
            priority=1,
            status="in_progress",
            labels=["test"]
        )

        success, _stats = invoke_cleanup_agent(item)

        assert success is True
        mock_invoke.assert_called_once()
        args = mock_invoke.call_args
        prompt = args[1]['prompt']
        assert "/cur/dir" in prompt
        assert "feature" in prompt
        assert "True" in prompt
        # Verify the cleanup item passed to invoke_copilot is marked ephemeral
        cleanup_item = args[0][0]
        assert cleanup_item.is_ephemeral is True
        assert cleanup_item.id == "123-cleanup"

    @patch('pokepoke.agents.cleanup_agents.merge_lock_active', return_value=False)
    @patch('pokepoke.agents.cleanup_agents.get_pokepoke_prompts_dir')
    @patch('pokepoke.agents.cleanup_agents._get_current_git_context')
    @patch('pokepoke.agents.cleanup_agents.invoke_copilot')
    def test_ephemeral_item_adds_warning_to_prompt(self, mock_invoke, mock_context, mock_get_dir, mock_merge_active):
        """Test that ephemeral items include a warning in the prompt not to use bd commands."""
        mock_dir = MagicMock()
        mock_file = Mock()
        mock_file.exists.return_value = True
        mock_file.read_text.return_value = "Instructions {cwd} {branch} {is_worktree}"
        mock_dir.__truediv__.return_value = mock_file
        mock_get_dir.return_value = mock_dir

        mock_context.return_value = ("/cur/dir", "feature", True)

        mock_invoke.return_value = CopilotResult(
            work_item_id="task-1",
            success=True,
            output="Done",
            attempt_count=1
        )

        # Create an ephemeral maintenance item
        item = BeadsWorkItem(
            id="maintenance-janitor-20260318",
            title="Janitor Maintenance",
            description="Cleanup",
            issue_type="task",
            priority=0,
            status="in_progress",
            is_ephemeral=True,
        )

        invoke_cleanup_agent(item)

        mock_invoke.assert_called_once()
        prompt = mock_invoke.call_args[1]['prompt']
        assert "does NOT exist in the beads database" in prompt
        assert "Do NOT run any `bd` commands" in prompt

    @patch('pokepoke.agents.cleanup_agents.merge_lock_active', return_value=False)
    @patch('pokepoke.agents.cleanup_agents.get_pokepoke_prompts_dir')
    def test_invoke_cleanup_agent_no_prompt(self, mock_get_dir, mock_merge_active):
        """Test invoking cleanup agent failing due to missing prompt."""
        mock_get_dir.side_effect = FileNotFoundError("Not found")

        item = BeadsWorkItem(id="1", title="T", description="D", status="open", priority=1, issue_type="task")
        success, stats = invoke_cleanup_agent(item)

        assert success is False
        assert stats is None

    @patch('pokepoke.agents.cleanup_agents.merge_lock_active', return_value=False)
    @patch('pokepoke.agents.cleanup_agents.get_pokepoke_prompts_dir')
    @patch('pokepoke.agents.cleanup_agents._get_current_git_context')
    @patch('pokepoke.agents.cleanup_agents.invoke_copilot')
    def test_invoke_merge_conflict_cleanup_agent(self, mock_invoke, mock_context, mock_get_dir, mock_merge_active):
        """Test invoking merge conflict cleanup agent."""
        mock_dir = MagicMock()
        mock_file = Mock()
        mock_file.exists.return_value = True
        mock_file.read_text.return_value = "Merge fix {merge_error}"
        mock_dir.__truediv__.return_value = mock_file
        mock_get_dir.return_value = mock_dir

        mock_context.return_value = ("/cur/dir", "feature", True)

        mock_invoke.return_value = CopilotResult(
            work_item_id="task-1",
            success=True,
            output="Fixed",
            attempt_count=1
        )

        item = BeadsWorkItem(
            id="123",
            title="Test",
            description="Desc",
            issue_type="task",
            priority=1,
            status="in_progress"
        )

        success, _stats = invoke_merge_conflict_cleanup_agent(item, "Merge error")

        assert success is True
        mock_invoke.assert_called_once()
        args = mock_invoke.call_args
        prompt = args[1]['prompt']
        assert "Merge error" in prompt

    @patch('pokepoke.agents.cleanup_agents.merge_lock_active', return_value=False)
    @patch('pokepoke.agents.cleanup_agents.get_pokepoke_prompts_dir')
    @patch('pokepoke.agents.cleanup_agents.invoke_cleanup_agent')
    def test_invoke_merge_conflict_fallback(self, mock_invoke_cleanup, mock_get_dir, mock_merge_active):
        """Test fallback to standard cleanup if merge prompt missing."""
        mock_dir = MagicMock()
        mock_file = Mock()
        mock_file.exists.return_value = False
        mock_dir.__truediv__.return_value = mock_file
        mock_get_dir.return_value = mock_dir

        mock_invoke_cleanup.return_value = (True, None)

        item = BeadsWorkItem(id="1", title="T", description="D", status="open", priority=1, issue_type="task")
        success, _stats = invoke_merge_conflict_cleanup_agent(item, "Error")

        assert success is True
        mock_invoke_cleanup.assert_called_once()


class TestAggregateCleanupStats:
    """Test aggregate_cleanup_stats function."""

    def test_aggregate_with_both_stats(self) -> None:
        """Test aggregating cleanup stats into result stats."""
        result_stats = AgentStats(
            wall_duration=10.0,
            api_duration=5.0,
            input_tokens=100,
            output_tokens=50,
            lines_added=10,
            lines_removed=5,
            premium_requests=1
        )
        cleanup_stats = AgentStats(
            wall_duration=5.0,
            api_duration=2.0,
            input_tokens=50,
            output_tokens=25,
            lines_added=5,
            lines_removed=2,
            premium_requests=1
        )

        aggregate_cleanup_stats(result_stats, cleanup_stats)

        assert result_stats.wall_duration == 15.0
        assert result_stats.api_duration == 7.0
        assert result_stats.input_tokens == 150
        assert result_stats.output_tokens == 75
        assert result_stats.lines_added == 15
        assert result_stats.lines_removed == 7
        assert result_stats.premium_requests == 2

    def test_aggregate_with_none_cleanup_stats(self) -> None:
        """Test aggregating when cleanup stats is None."""
        result_stats = AgentStats(
            wall_duration=10.0,
            api_duration=5.0,
            input_tokens=100,
            output_tokens=50,
            lines_added=10,
            lines_removed=5,
            premium_requests=1
        )

        aggregate_cleanup_stats(result_stats, None)

        # Should remain unchanged
        assert result_stats.wall_duration == 10.0
        assert result_stats.input_tokens == 100

    def test_aggregate_with_none_result_stats(self) -> None:
        """Test aggregating when result stats is None."""
        cleanup_stats = AgentStats(
            wall_duration=5.0,
            api_duration=2.0,
            input_tokens=50,
            output_tokens=25,
            lines_added=5,
            lines_removed=2,
            premium_requests=1
        )

        # Should not raise exception
        aggregate_cleanup_stats(None, cleanup_stats)


class TestRunCleanupLoop:
    """Test run_cleanup_loop function."""

    @patch('pokepoke.agents.cleanup_agents.invoke_cleanup_agent')
    @patch('pokepoke.agents.cleanup_agents.commit_all_changes')
    @patch('pokepoke.agents.cleanup_agents.verify_main_repo_clean')
    def test_no_uncommitted_changes(
        self,
        mock_verify: Mock,
        mock_commit: Mock,
        mock_invoke: Mock
    ) -> None:
        """Test cleanup loop when no uncommitted changes."""
        item = BeadsWorkItem(
            id="task-1",
            title="Test",
            description="",
            status="in_progress",
            priority=1,
            issue_type="task"
        )
        result = CopilotResult(
            work_item_id="task-1",
            success=True,
            output="",
            attempt_count=1
        )

        # is_clean=True, no uncommitted output, no non-beads changes
        mock_verify.return_value = (True, "", [])

        success, cleanup_runs = run_cleanup_loop(item, result)

        assert success is True
        assert cleanup_runs == 0
        mock_commit.assert_not_called()
        mock_invoke.assert_not_called()

    @patch('pokepoke.agents.cleanup_agents.invoke_cleanup_agent')
    @patch('pokepoke.agents.cleanup_agents.commit_all_changes')
    @patch('pokepoke.agents.cleanup_agents.verify_main_repo_clean')
    def test_successful_commit_first_try(
        self,
        mock_verify: Mock,
        mock_commit: Mock,
        mock_invoke: Mock
    ) -> None:
        """Test cleanup loop with successful commit on first try."""
        item = BeadsWorkItem(
            id="task-1",
            title="Test",
            description="",
            status="in_progress",
            priority=1,
            issue_type="task"
        )
        result = CopilotResult(
            work_item_id="task-1",
            success=True,
            output="",
            attempt_count=1
        )

        # is_clean=False (has non-beads changes), then True after commit
        mock_verify.return_value = (False, " M file.py\n", [" M file.py"])
        mock_commit.return_value = (True, "")

        success, cleanup_runs = run_cleanup_loop(item, result)

        assert success is True
        assert cleanup_runs == 0
        mock_commit.assert_called_once()
        # Verify tracked_only=True is passed for main repo safety
        call_kwargs = mock_commit.call_args
        assert call_kwargs == unittest.mock.call(
            "Work on task-1", cwd=None, tracked_only=True
        )
        mock_invoke.assert_not_called()

    @patch('pokepoke.agents.cleanup_agents.invoke_cleanup_agent')
    @patch('pokepoke.agents.cleanup_agents.commit_all_changes')
    @patch('pokepoke.agents.cleanup_agents.verify_main_repo_clean')
    def test_commit_fails_cleanup_succeeds(
        self,
        mock_verify: Mock,
        mock_commit: Mock,
        mock_invoke: Mock
    ) -> None:
        """Test cleanup loop with commit failure then cleanup success."""
        item = BeadsWorkItem(
            id="task-1",
            title="Test",
            description="",
            status="in_progress",
            priority=1,
            issue_type="task"
        )
        result = CopilotResult(
            work_item_id="task-1",
            success=True,
            output="",
            attempt_count=1,
            stats=AgentStats(
                wall_duration=10.0,
                api_duration=5.0,
                input_tokens=100,
                output_tokens=50,
                lines_added=10,
                lines_removed=5,
                premium_requests=1
            )
        )

        # First call: has non-beads changes, second call: clean after cleanup
        mock_verify.side_effect = [
            (False, " M file.py\n", [" M file.py"]),  # Initial state
            (True, "", [])  # After cleanup
        ]
        mock_commit.return_value = (False, "Tests failed")
        mock_invoke.return_value = (
            True,
            AgentStats(
                wall_duration=5.0,
                api_duration=2.0,
                input_tokens=50,
                output_tokens=25,
                lines_added=5,
                lines_removed=2,
                premium_requests=1
            )
        )

        success, cleanup_runs = run_cleanup_loop(item, result)

        assert success is True
        assert cleanup_runs == 1
        mock_commit.assert_called_once()
        mock_invoke.assert_called_once()
        # Stats should be aggregated
        assert result.stats.wall_duration == 15.0

    @patch('pokepoke.agents.cleanup_agents.invoke_cleanup_agent')
    @patch('pokepoke.agents.cleanup_agents.commit_all_changes')
    @patch('pokepoke.agents.cleanup_agents.verify_main_repo_clean')
    def test_cleanup_agent_fails(
        self,
        mock_verify: Mock,
        mock_commit: Mock,
        mock_invoke: Mock
    ) -> None:
        """Test cleanup loop when cleanup agent fails."""
        item = BeadsWorkItem(
            id="task-1",
            title="Test",
            description="",
            status="in_progress",
            priority=1,
            issue_type="task"
        )
        result = CopilotResult(
            work_item_id="task-1",
            success=True,
            output="",
            attempt_count=1
        )

        # is_clean=False (has non-beads changes)
        mock_verify.return_value = (False, " M file.py\n", [" M file.py"])
        mock_commit.return_value = (False, "Tests failed")
        mock_invoke.return_value = (False, None)

        success, cleanup_runs = run_cleanup_loop(item, result)

        assert success is False
        assert cleanup_runs == 1
        assert result.success is False
        assert "Cleanup agent failed" in result.error


class TestRunCleanupLoopErrorHandling:
    """Test error handling paths in run_cleanup_loop."""

    @patch('pokepoke.agents.cleanup_agents.verify_main_repo_clean')
    def test_verify_clean_exception_treats_as_clean(self, mock_verify: Mock) -> None:
        """Test cleanup loop when verify_main_repo_clean raises an exception on first call.

        Transient git contention (e.g. concurrent git operations across worktrees) should
        not abort successful work. Treat as clean and return success=True.
        """
        mock_verify.side_effect = Exception("git error")

        item = BeadsWorkItem(
            id="task-1", title="Test", description="",
            status="in_progress", priority=1, issue_type="task"
        )
        result = CopilotResult(
            work_item_id="task-1", success=True, output="", attempt_count=1
        )

        success, cleanup_runs = run_cleanup_loop(item, result)

        assert success is True
        assert cleanup_runs == 0

    @patch('pokepoke.agents.cleanup_agents.invoke_cleanup_agent')
    @patch('pokepoke.agents.cleanup_agents.commit_all_changes')
    @patch('pokepoke.agents.cleanup_agents.verify_main_repo_clean')
    def test_recheck_exception_after_cleanup(
        self, mock_verify: Mock, mock_commit: Mock, mock_invoke: Mock
    ) -> None:
        """Test cleanup loop when re-check after cleanup raises an exception."""
        mock_verify.side_effect = [
            (False, " M file.py\n", [" M file.py"]),
            Exception("git status failed after cleanup"),
        ]
        mock_commit.return_value = (False, "Tests failed")
        mock_invoke.return_value = (True, None)

        item = BeadsWorkItem(
            id="task-1", title="Test", description="",
            status="in_progress", priority=1, issue_type="task"
        )
        result = CopilotResult(
            work_item_id="task-1", success=True, output="", attempt_count=1
        )

        success, cleanup_runs = run_cleanup_loop(item, result)

        assert success is False
        assert cleanup_runs == 1
        assert "Git status check failed" in result.error


class TestRunAgentWithUiException:
    """Test exception handling in _run_agent_with_ui."""

    @patch('pokepoke.agents.cleanup_agents.terminal_ui')
    @patch('pokepoke.agents.cleanup_agents.invoke_copilot')
    def test_run_agent_with_ui_exception_reraises(self, mock_invoke, mock_ui):
        """Test that _run_agent_with_ui re-raises exceptions after logging."""
        from pokepoke.agents.cleanup_agents import _run_agent_with_ui

        mock_invoke.side_effect = RuntimeError("Copilot crashed")

        item = BeadsWorkItem(
            id="test-1", title="T", description="D",
            status="in_progress", priority=1, issue_type="task"
        )

        with patch('pokepoke.agents.cleanup_agents.agent_type_context', create=True), \
             pytest.raises(RuntimeError, match="Copilot crashed"):
            _run_agent_with_ui(
                "test-1", "Test Agent", "cleanup",
                item, "prompt", None, None,
            )


class TestMergeWaitLogic:
    """Test merge wait logic in invoke_cleanup_agent and invoke_merge_conflict_cleanup_agent."""

    @patch('pokepoke.agents.cleanup_agents.merge_lock_active')
    @patch('pokepoke.agents.cleanup_agents.load_prompt_file')
    @patch('pokepoke.agents.cleanup_agents._get_current_git_context')
    @patch('pokepoke.agents.cleanup_agents.invoke_copilot')
    @patch('pokepoke.agents.cleanup_agents.terminal_ui')
    def test_cleanup_agent_waits_for_merge_then_proceeds(
        self, mock_ui, mock_invoke, mock_context, mock_load_prompt, mock_merge_active
    ):
        """Test cleanup agent waits when merge is active, then proceeds when it clears."""
        # Call 1 (if guard): True, Call 2 (while check): False, Call 3 (post-while check): False
        mock_merge_active.side_effect = [True, False, False]
        mock_load_prompt.return_value = "Instructions {cwd} {branch} {is_worktree}"
        mock_context.return_value = ("/dir", "main", False)
        mock_invoke.return_value = CopilotResult(
            work_item_id="t-1", success=True, output="Done", attempt_count=1
        )

        item = BeadsWorkItem(
            id="t-1", title="T", description="D",
            status="in_progress", priority=1, issue_type="task"
        )

        with patch('pokepoke.agents.cleanup_agents.time.sleep'):
            success, _stats = invoke_cleanup_agent(item, wait_for_merge=True)

        assert success is True

    @patch('pokepoke.agents.cleanup_agents.merge_lock_active')
    @patch('pokepoke.agents.cleanup_agents.load_prompt_file')
    @patch('pokepoke.agents.cleanup_agents._get_current_git_context')
    @patch('pokepoke.agents.cleanup_agents.invoke_copilot')
    @patch('pokepoke.agents.cleanup_agents.terminal_ui')
    def test_cleanup_agent_merge_timeout_proceeds_anyway(
        self, mock_ui, mock_invoke, mock_context, mock_load_prompt, mock_merge_active
    ):
        """Test cleanup agent proceeds after merge wait timeout."""
        # Always active (times out)
        mock_merge_active.return_value = True
        mock_load_prompt.return_value = "Instructions {cwd} {branch} {is_worktree}"
        mock_context.return_value = ("/dir", "main", False)
        mock_invoke.return_value = CopilotResult(
            work_item_id="t-1", success=True, output="Done", attempt_count=1
        )

        item = BeadsWorkItem(
            id="t-1", title="T", description="D",
            status="in_progress", priority=1, issue_type="task"
        )

        with patch('pokepoke.agents.cleanup_agents.time.sleep'):
            success, _stats = invoke_cleanup_agent(item, wait_for_merge=True)

        assert success is True

    @patch('pokepoke.agents.cleanup_agents.merge_lock_active')
    @patch('pokepoke.agents.cleanup_agents.load_prompt_file')
    @patch('pokepoke.agents.cleanup_agents._get_current_git_context')
    @patch('pokepoke.agents.cleanup_agents.invoke_copilot')
    @patch('pokepoke.agents.cleanup_agents.terminal_ui')
    def test_cleanup_agent_skips_wait_when_false(
        self, mock_ui, mock_invoke, mock_context, mock_load_prompt, mock_merge_active
    ):
        """Test cleanup agent skips merge wait when wait_for_merge=False."""
        mock_load_prompt.return_value = "Instructions {cwd} {branch} {is_worktree}"
        mock_context.return_value = ("/dir", "main", False)
        mock_invoke.return_value = CopilotResult(
            work_item_id="t-1", success=True, output="Done", attempt_count=1
        )

        item = BeadsWorkItem(
            id="t-1", title="T", description="D",
            status="in_progress", priority=1, issue_type="task"
        )

        success, _stats = invoke_cleanup_agent(item, wait_for_merge=False)

        assert success is True
        mock_merge_active.assert_not_called()

    @patch('pokepoke.agents.cleanup_agents.merge_lock_active')
    @patch('pokepoke.agents.cleanup_agents.load_prompt_file')
    @patch('pokepoke.agents.cleanup_agents._get_current_git_context')
    @patch('pokepoke.agents.cleanup_agents.invoke_copilot')
    @patch('pokepoke.agents.cleanup_agents.terminal_ui')
    @patch('pokepoke.git.merge_conflict.is_merge_in_progress', return_value=False)
    @patch('pokepoke.git.merge_conflict.get_unmerged_files', return_value=[])
    def test_merge_conflict_agent_waits_for_merge(
        self, mock_get_unmerged, mock_is_merging,
        mock_ui, mock_invoke, mock_context, mock_load_prompt, mock_merge_active
    ):
        """Test merge conflict cleanup agent waits when merge is active."""
        # Call 1 (if guard): True, Call 2 (while check): False, Call 3 (post-while check): False
        mock_merge_active.side_effect = [True, False, False]
        mock_load_prompt.return_value = "Fix {merge_error} {cwd} {branch} {is_worktree} {worktree_path} {is_merge_in_progress} {conflict_files} {conflict_count}"
        mock_context.return_value = ("/dir", "main", False)
        mock_invoke.return_value = CopilotResult(
            work_item_id="t-1", success=True, output="Fixed", attempt_count=1
        )

        item = BeadsWorkItem(
            id="t-1", title="T", description="D",
            status="in_progress", priority=1, issue_type="task"
        )

        with patch('pokepoke.agents.cleanup_agents.time.sleep'):
            success, _stats = invoke_merge_conflict_cleanup_agent(
                item, "Merge error", wait_for_merge=True
            )

        assert success is True

    @patch('pokepoke.agents.cleanup_agents.merge_lock_active')
    @patch('pokepoke.agents.cleanup_agents.load_prompt_file')
    @patch('pokepoke.agents.cleanup_agents._get_current_git_context')
    @patch('pokepoke.agents.cleanup_agents.invoke_copilot')
    @patch('pokepoke.agents.cleanup_agents.terminal_ui')
    @patch('pokepoke.git.merge_conflict.is_merge_in_progress', return_value=False)
    @patch('pokepoke.git.merge_conflict.get_unmerged_files', return_value=[])
    def test_merge_conflict_agent_timeout_proceeds(
        self, mock_get_unmerged, mock_is_merging,
        mock_ui, mock_invoke, mock_context, mock_load_prompt, mock_merge_active
    ):
        """Test merge conflict cleanup agent proceeds after timeout."""
        mock_merge_active.return_value = True
        mock_load_prompt.return_value = "Fix {merge_error} {cwd} {branch} {is_worktree} {worktree_path} {is_merge_in_progress} {conflict_files} {conflict_count}"
        mock_context.return_value = ("/dir", "main", False)
        mock_invoke.return_value = CopilotResult(
            work_item_id="t-1", success=True, output="Fixed", attempt_count=1
        )

        item = BeadsWorkItem(
            id="t-1", title="T", description="D",
            status="in_progress", priority=1, issue_type="task"
        )

        with patch('pokepoke.agents.cleanup_agents.time.sleep'):
            success, _stats = invoke_merge_conflict_cleanup_agent(
                item, "Merge error", wait_for_merge=True
            )

        assert success is True

    @patch('pokepoke.agents.cleanup_agents.merge_lock_active')
    @patch('pokepoke.agents.cleanup_agents.load_prompt_file')
    @patch('pokepoke.agents.cleanup_agents._get_current_git_context')
    @patch('pokepoke.agents.cleanup_agents.invoke_copilot')
    @patch('pokepoke.agents.cleanup_agents.terminal_ui')
    @patch('pokepoke.git.merge_conflict.is_merge_in_progress', return_value=True)
    @patch('pokepoke.git.merge_conflict.get_unmerged_files', return_value=["file1.py", "file2.py", "file3.py", "file4.py", "file5.py", "file6.py"])
    def test_merge_conflict_agent_with_many_conflict_files(
        self, mock_get_unmerged, mock_is_merging,
        mock_ui, mock_invoke, mock_context, mock_load_prompt, mock_merge_active
    ):
        """Test merge conflict cleanup agent displays conflict files (including truncation)."""
        mock_merge_active.return_value = False
        mock_load_prompt.return_value = "Fix {merge_error} {cwd} {branch} {is_worktree} {worktree_path} {is_merge_in_progress} {conflict_files} {conflict_count}"
        mock_context.return_value = ("/dir", "main", False)
        mock_invoke.return_value = CopilotResult(
            work_item_id="t-1", success=True, output="Fixed", attempt_count=1
        )

        item = BeadsWorkItem(
            id="t-1", title="T", description="D",
            status="in_progress", priority=1, issue_type="task"
        )

        success, _stats = invoke_merge_conflict_cleanup_agent(
            item, "Merge error",
            unmerged_files=["f1.py", "f2.py", "f3.py", "f4.py", "f5.py", "f6.py"],
            wait_for_merge=False,
        )

        assert success is True


class TestCleanupAgentTimeout:
    """Test per-invocation timeout and aggregate timeout behavior."""

    @patch('pokepoke.agents.cleanup_agents.merge_lock_active', return_value=False)
    @patch('pokepoke.agents.cleanup_agents.get_pokepoke_prompts_dir')
    @patch('pokepoke.agents.cleanup_agents._get_current_git_context')
    @patch('pokepoke.agents.cleanup_agents.invoke_copilot')
    def test_cleanup_agent_passes_timeout(self, mock_invoke, mock_context, mock_get_dir, mock_merge_active):
        """Test that invoke_cleanup_agent passes CLEANUP_AGENT_TIMEOUT to invoke_copilot."""
        from pokepoke.utils.constants import CLEANUP_AGENT_TIMEOUT

        mock_dir = MagicMock()
        mock_file = Mock()
        mock_file.exists.return_value = True
        mock_file.read_text.return_value = "Instructions {cwd} {branch} {is_worktree}"
        mock_dir.__truediv__.return_value = mock_file
        mock_get_dir.return_value = mock_dir
        mock_context.return_value = ("/cur/dir", "feature", True)
        mock_invoke.return_value = CopilotResult(
            work_item_id="task-1", success=True, output="Done", attempt_count=1
        )

        item = BeadsWorkItem(
            id="123", title="Test", description="Desc",
            issue_type="task", priority=1, status="in_progress", labels=["test"]
        )

        success, _stats = invoke_cleanup_agent(item)

        assert success is True
        mock_invoke.assert_called_once()
        call_kwargs = mock_invoke.call_args[1]
        assert call_kwargs['timeout'] == CLEANUP_AGENT_TIMEOUT

    @patch('pokepoke.agents.cleanup_agents.merge_lock_active', return_value=False)
    @patch('pokepoke.agents.cleanup_agents.load_prompt_file')
    @patch('pokepoke.agents.cleanup_agents._get_current_git_context')
    @patch('pokepoke.agents.cleanup_agents.invoke_copilot')
    @patch('pokepoke.agents.cleanup_agents.terminal_ui')
    @patch('pokepoke.git.merge_conflict.is_merge_in_progress', return_value=False)
    @patch('pokepoke.git.merge_conflict.get_unmerged_files', return_value=[])
    def test_merge_conflict_agent_passes_timeout(
        self, mock_get_unmerged, mock_is_merging,
        mock_ui, mock_invoke, mock_context, mock_load_prompt, mock_merge_active
    ):
        """Test that invoke_merge_conflict_cleanup_agent passes CLEANUP_AGENT_TIMEOUT."""
        from pokepoke.utils.constants import CLEANUP_AGENT_TIMEOUT

        mock_load_prompt.return_value = "Fix {merge_error} {cwd} {branch} {is_worktree} {worktree_path} {is_merge_in_progress} {conflict_files} {conflict_count}"
        mock_context.return_value = ("/dir", "main", False)
        mock_invoke.return_value = CopilotResult(
            work_item_id="t-1", success=True, output="Fixed", attempt_count=1
        )

        item = BeadsWorkItem(
            id="t-1", title="T", description="D",
            status="in_progress", priority=1, issue_type="task"
        )

        success, _stats = invoke_merge_conflict_cleanup_agent(
            item, "Merge error", wait_for_merge=False
        )

        assert success is True
        mock_invoke.assert_called_once()
        call_kwargs = mock_invoke.call_args[1]
        assert call_kwargs['timeout'] == CLEANUP_AGENT_TIMEOUT

    @patch('pokepoke.agents.cleanup_agents.invoke_cleanup_agent')
    @patch('pokepoke.agents.cleanup_agents.commit_all_changes')
    @patch('pokepoke.agents.cleanup_agents.verify_main_repo_clean')
    @patch('pokepoke.agents.cleanup_agents.time.monotonic')
    def test_aggregate_timeout_aborts_cleanup_loop(
        self, mock_monotonic, mock_verify, mock_commit, mock_invoke
    ):
        """Test that run_cleanup_loop aborts when aggregate timeout is exceeded."""
        from pokepoke.utils.constants import CLEANUP_AGGREGATE_TIMEOUT

        # First call returns 0 (start), second call returns beyond timeout
        mock_monotonic.side_effect = [0.0, CLEANUP_AGGREGATE_TIMEOUT + 1.0]

        mock_verify.return_value = (False, " M file.py\n", [" M file.py"])

        item = BeadsWorkItem(
            id="task-1", title="Test", description="",
            status="in_progress", priority=1, issue_type="task"
        )
        result = CopilotResult(
            work_item_id="task-1", success=True, output="", attempt_count=1
        )

        success, _cleanup_runs = run_cleanup_loop(item, result)

        assert success is False
        assert "aggregate timeout" in result.error.lower()
        # Should NOT have called commit or cleanup agent
        mock_commit.assert_not_called()
        mock_invoke.assert_not_called()

    @patch('pokepoke.agents.cleanup_agents.invoke_cleanup_agent')
    @patch('pokepoke.agents.cleanup_agents.commit_all_changes')
    @patch('pokepoke.agents.cleanup_agents.verify_main_repo_clean')
    @patch('pokepoke.agents.cleanup_agents.time.monotonic')
    def test_recurring_error_short_circuits_cleanup_loop(
        self, mock_monotonic, mock_verify, mock_commit, mock_invoke
    ):
        """Test that run_cleanup_loop short-circuits on recurring commit errors."""
        # Ensure monotonic never hits aggregate timeout
        mock_monotonic.return_value = 0.0

        same_error = "Permission denied: .beads/daemon.lock"
        # First: dirty, Second: still dirty after cleanup
        mock_verify.side_effect = [
            (False, " M file.py\n", [" M file.py"]),
            (False, " M file.py\n", [" M file.py"]),
        ]
        # Commit always fails with the same error
        mock_commit.return_value = (False, same_error)
        # Cleanup agent succeeds (but can't fix the underlying issue)
        mock_invoke.return_value = (True, None)

        item = BeadsWorkItem(
            id="task-1", title="Test", description="",
            status="in_progress", priority=1, issue_type="task"
        )
        result = CopilotResult(
            work_item_id="task-1", success=True, output="", attempt_count=1
        )

        success, cleanup_runs = run_cleanup_loop(item, result)

        assert success is False
        assert "recurring" in result.error.lower()
        # Should have run cleanup once (first error triggers cleanup, second triggers short-circuit)
        assert cleanup_runs == 1


class TestWorktreeCleanupPromptSafety:
    """Tests to verify the worktree cleanup prompt prohibits process killing."""

    def _prompt_path(self) -> Path:
        return Path(__file__).resolve().parent.parent.parent / "src" / "pokepoke" / "builtin_prompts" / "worktree-cleanup.md"

    def test_prompt_prohibits_stop_process(self):
        """The worktree-cleanup prompt must explicitly forbid Stop-Process."""
        content = self._prompt_path().read_text(encoding='utf-8')
        assert "Stop-Process" in content, "Prompt must explicitly mention Stop-Process as forbidden"

    def test_prompt_prohibits_kill(self):
        """The worktree-cleanup prompt must explicitly forbid kill commands."""
        content = self._prompt_path().read_text(encoding='utf-8')
        assert "taskkill" in content, "Prompt must explicitly mention taskkill as forbidden"

    def test_prompt_prohibits_process_killing_section(self):
        """The worktree-cleanup prompt must have a NEVER kill processes section."""
        content = self._prompt_path().read_text(encoding='utf-8')
        assert "NEVER Kill or Stop Any Running Processes" in content

    def test_prompt_forbids_stale_process_cleanup(self):
        """The worktree-cleanup prompt must forbid killing 'stale' processes."""
        content = self._prompt_path().read_text(encoding='utf-8')
        # Must mention stale processes as forbidden
        assert "stale" in content.lower()
        assert "zombie" in content.lower() or "orphan" in content.lower()

    @patch('pokepoke.agents.agent_runner.has_unmerged_worktrees', return_value=True)
    @patch('pokepoke.agents.agent_runner.get_pokepoke_prompts_dir')
    @patch('pokepoke.agents.agent_runner._run_main_repo_agent')
    @patch('pokepoke.agents.agent_runner.terminal_ui')
    def test_worktree_cleanup_injects_orchestrator_pid(
        self, mock_ui, mock_run_agent, mock_prompts_dir, mock_has_unmerged, tmp_path
    ):
        """run_worktree_cleanup must inject the orchestrator PID into the prompt."""
        import os

        from pokepoke.agents.agent_runner import run_worktree_cleanup

        # Create a minimal prompt file
        prompt_file = tmp_path / "worktree-cleanup.md"
        prompt_file.write_text("# Cleanup\nDo stuff.", encoding='utf-8')
        mock_prompts_dir.return_value = tmp_path

        # Mock the retry/count functions where they are used (imported at top of agent_runner)
        with patch('pokepoke.agents.agent_runner.retry_failed_cleanups', return_value=0), \
             patch('pokepoke.agents.agent_runner.get_uncleaned_worktree_count', return_value=0):
            mock_run_agent.return_value = None
            run_worktree_cleanup()

        # Verify the prompt passed to _run_main_repo_agent includes the PID
        call_args = mock_run_agent.call_args
        # _run_main_repo_agent signature: (config: AgentRunnerConfig, agent_prompt: str, cwd: str | None = None, add_parent_dir: bool = False)
        # The prompt is the second positional argument (index 1)
        prompt_passed = call_args[0][1]
        assert str(os.getpid()) in prompt_passed, "Orchestrator PID must be injected into cleanup prompt"
        assert "DO NOT TOUCH" in prompt_passed


class TestApplyBaseTemplateVars:
    """Tests for _apply_base_template_vars helper."""

    def test_replaces_all_placeholders(self) -> None:
        template = "dir={cwd} branch={branch} wt={is_worktree}"
        result = _apply_base_template_vars(template, "/my/dir", "feature-x", True)
        assert result == "dir=/my/dir branch=feature-x wt=True"

    def test_handles_false_worktree(self) -> None:
        template = "{is_worktree}"
        result = _apply_base_template_vars(template, "/d", "main", False)
        assert result == "False"

    def test_no_placeholders_returns_unchanged(self) -> None:
        template = "No placeholders here"
        result = _apply_base_template_vars(template, "/d", "b", True)
        assert result == "No placeholders here"

    def test_multiple_occurrences_replaced(self) -> None:
        template = "{cwd} then {cwd} again"
        result = _apply_base_template_vars(template, "/x", "b", False)
        assert result == "/x then /x again"


class TestBuildWorkItemContext:
    """Tests for _build_work_item_context helper."""

    def test_basic_context_fields(self) -> None:
        item = BeadsWorkItem(
            id="task-1", title="Fix Bug", description="Fix the bug",
            status="open", priority=2, issue_type="bug",
        )
        context = _build_work_item_context(item, "Work Item")
        assert "**ID:** task-1" in context
        assert "**Title:** Fix Bug" in context
        assert "**Type:** bug" in context
        assert "**Priority:** 2" in context
        assert "Fix the bug" in context
        assert "# Work Item" in context

    def test_labels_included(self) -> None:
        item = BeadsWorkItem(
            id="t-1", title="T", description="D",
            status="open", priority=1, issue_type="task",
            labels=["cleanup", "automated"],
        )
        context = _build_work_item_context(item, "Heading")
        assert "cleanup, automated" in context

    def test_no_labels_omits_section(self) -> None:
        item = BeadsWorkItem(
            id="t-1", title="T", description="D",
            status="open", priority=1, issue_type="task",
        )
        context = _build_work_item_context(item, "Heading")
        assert "**Labels:**" not in context

    def test_ephemeral_adds_warning(self) -> None:
        item = BeadsWorkItem(
            id="t-1", title="T", description="D",
            status="open", priority=1, issue_type="task",
            is_ephemeral=True,
        )
        context = _build_work_item_context(item, "Heading")
        assert "does NOT exist in the beads database" in context
        assert "Do NOT run any `bd` commands" in context

    def test_extra_text_appended(self) -> None:
        item = BeadsWorkItem(
            id="t-1", title="T", description="D",
            status="open", priority=1, issue_type="task",
        )
        context = _build_work_item_context(item, "H", extra="\n**Extra:** data\n")
        assert "**Extra:** data" in context


class TestLoadPromptFile:
    """Tests for load_prompt_file helper."""

    def test_returns_content_when_file_exists(self, tmp_path: Path) -> None:
        prompt_file = tmp_path / "prompts" / "test.md"
        prompt_file.parent.mkdir(parents=True)
        prompt_file.write_text("Hello prompt", encoding="utf-8")

        with patch("pokepoke.agents.cleanup_agents.get_pokepoke_prompts_dir", return_value=prompt_file.parent):
            result = load_prompt_file("test.md")
        assert result == "Hello prompt"

    def test_returns_none_when_dir_not_found(self) -> None:
        with patch("pokepoke.agents.cleanup_agents.get_pokepoke_prompts_dir",
                    side_effect=FileNotFoundError("no dir")):
            result = load_prompt_file("missing.md")
        assert result is None

    def test_returns_none_when_file_missing_in_dir(self, tmp_path: Path) -> None:
        """Prompt directory exists but the specific file does not."""
        with patch("pokepoke.agents.cleanup_agents.get_pokepoke_prompts_dir", return_value=tmp_path):
            result = load_prompt_file("nonexistent.md")
        assert result is None


class TestGitOutput:
    """Tests for _git_output helper."""

    @patch("pokepoke.agents.cleanup_agents.run_git")
    def test_returns_stdout_on_success(self, mock_run: Mock) -> None:
        mock_run.return_value = Mock(returncode=0, stdout="  main  ")
        result = _git_output(["git", "branch", "--show-current"], None)
        assert result == "main"

    @patch("pokepoke.agents.cleanup_agents.run_git")
    def test_returns_none_on_nonzero_exit(self, mock_run: Mock) -> None:
        mock_run.return_value = Mock(returncode=1, stdout="error")
        result = _git_output(["git", "bad-cmd"], None)
        assert result is None

    @patch("pokepoke.agents.cleanup_agents.run_git")
    def test_returns_none_on_exception(self, mock_run: Mock) -> None:
        mock_run.side_effect = Exception("git not found")
        result = _git_output(["git", "status"], None)
        assert result is None

    @patch("pokepoke.agents.cleanup_agents.run_git")
    def test_passes_cwd(self, mock_run: Mock) -> None:
        mock_run.return_value = Mock(returncode=0, stdout="ok")
        _git_output(["git", "status"], "/my/cwd")
        mock_run.assert_called_once_with(["git", "status"], timeout=10, cwd="/my/cwd", check=False)


class TestRunCleanupLoopMultipleAttempts:
    """Test multi-iteration cleanup loop behavior."""

    @patch('pokepoke.agents.cleanup_agents.invoke_cleanup_agent')
    @patch('pokepoke.agents.cleanup_agents.commit_all_changes')
    @patch('pokepoke.agents.cleanup_agents.verify_main_repo_clean')
    def test_commit_succeeds_on_second_attempt_after_cleanup(
        self, mock_verify: Mock, mock_commit: Mock, mock_invoke: Mock
    ) -> None:
        """Cleanup agent fixes the issue and second commit attempt succeeds."""
        item = BeadsWorkItem(
            id="task-1", title="Test", description="",
            status="in_progress", priority=1, issue_type="task"
        )
        result = CopilotResult(
            work_item_id="task-1", success=True, output="", attempt_count=1
        )

        # Initial: dirty, after cleanup: still dirty, loop re-checks and commits
        mock_verify.side_effect = [
            (False, " M file.py\n", [" M file.py"]),
            (False, " M file.py\n", [" M file.py"]),
        ]
        mock_commit.side_effect = [
            (False, "Tests failed"),
            (True, ""),
        ]
        mock_invoke.return_value = (True, None)

        success, cleanup_runs = run_cleanup_loop(item, result)

        assert success is True
        assert cleanup_runs == 1
        assert mock_commit.call_count == 2

    @patch('pokepoke.agents.cleanup_agents.invoke_cleanup_agent')
    @patch('pokepoke.agents.cleanup_agents.commit_all_changes')
    @patch('pokepoke.agents.cleanup_agents.verify_main_repo_clean')
    def test_result_not_success_skips_loop(
        self, mock_verify: Mock, mock_commit: Mock, mock_invoke: Mock
    ) -> None:
        """When result.success is False, cleanup loop should not enter the while."""
        item = BeadsWorkItem(
            id="task-1", title="Test", description="",
            status="in_progress", priority=1, issue_type="task"
        )
        result = CopilotResult(
            work_item_id="task-1", success=False, output="", attempt_count=1
        )

        mock_verify.return_value = (False, " M file.py\n", [" M file.py"])

        success, cleanup_runs = run_cleanup_loop(item, result)

        assert success is False
        assert cleanup_runs == 0
        mock_commit.assert_not_called()

    @patch('pokepoke.agents.cleanup_agents.invoke_cleanup_agent')
    @patch('pokepoke.agents.cleanup_agents.commit_all_changes')
    @patch('pokepoke.agents.cleanup_agents.verify_main_repo_clean')
    def test_file_paths_extracted_for_cleanup_agent(
        self, mock_verify: Mock, mock_commit: Mock, mock_invoke: Mock
    ) -> None:
        """Verify file paths are correctly extracted from git status output."""
        item = BeadsWorkItem(
            id="task-1", title="Test", description="",
            status="in_progress", priority=1, issue_type="task"
        )
        result = CopilotResult(
            work_item_id="task-1", success=True, output="", attempt_count=1
        )

        mock_verify.return_value = (False, " M src/foo.py\n", [" M src/foo.py"])
        mock_commit.return_value = (False, "Tests failed")
        mock_invoke.return_value = (False, None)

        run_cleanup_loop(item, result)

        call_kwargs = mock_invoke.call_args[1]
        assert call_kwargs['modified_files'] == ["src/foo.py"]
