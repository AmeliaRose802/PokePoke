"""Tests for cleanup agents."""

from pathlib import Path
from unittest.mock import Mock, MagicMock, patch

import pytest
from pokepoke.cleanup_agents import (
    get_pokepoke_prompts_dir,
    _get_current_git_context,
    invoke_cleanup_agent,
    invoke_merge_conflict_cleanup_agent,
    aggregate_cleanup_stats,
    run_cleanup_loop
)
from pokepoke.types import BeadsWorkItem, CopilotResult, AgentStats


class TestCleanupAgents:
    """Test cleanup agent functions."""

    @patch('pathlib.Path.exists')
    @patch('pathlib.Path.parent', new_callable=Mock)
    def test_get_prompts_dir(self, mock_parent, mock_exists):
        """Test finding prompts directory."""
        mock_exists.return_value = True

        with patch('pokepoke.cleanup_agents.Path') as mock_path:
             mock_path.return_value.parent.parent.parent = Path('/root')
             get_pokepoke_prompts_dir()
             # Logic is Path(__file__).parent.parent.parent / ".pokepoke" / "prompts"
             # Since it returns a path, validation passes if no exception

    def test_get_prompts_dir_not_found(self):
        """Test error when prompts directory not found."""
        with patch('pokepoke.cleanup_agents.Path') as mock_path:
             # Make exists return False
             mock_dir = Mock()
             mock_dir.exists.return_value = False
             mock_path.return_value.parent.parent.parent.__truediv__.return_value.__truediv__.return_value = mock_dir

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

        cwd, branch, is_worktree = _get_current_git_context()

        assert branch == "unknown"
        assert is_worktree is False

    @patch('pokepoke.cleanup_agents.merge_lock_active', return_value=False)
    @patch('pokepoke.cleanup_agents.get_pokepoke_prompts_dir')
    @patch('pokepoke.cleanup_agents._get_current_git_context')
    @patch('pokepoke.cleanup_agents.invoke_copilot')
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

        success, stats = invoke_cleanup_agent(item, Path("/repo"))

        assert success is True
        mock_invoke.assert_called_once()
        args = mock_invoke.call_args
        prompt = args[1]['prompt']
        assert "/cur/dir" in prompt
        assert "feature" in prompt
        assert "True" in prompt

    @patch('pokepoke.cleanup_agents.merge_lock_active', return_value=False)
    @patch('pokepoke.cleanup_agents.get_pokepoke_prompts_dir')
    def test_invoke_cleanup_agent_no_prompt(self, mock_get_dir, mock_merge_active):
        """Test invoking cleanup agent failing due to missing prompt."""
        mock_get_dir.side_effect = FileNotFoundError("Not found")

        item = BeadsWorkItem(id="1", title="T", description="D", status="open", priority=1, issue_type="task")
        success, stats = invoke_cleanup_agent(item, Path("/repo"))

        assert success is False
        assert stats is None

    @patch('pokepoke.cleanup_agents.merge_lock_active', return_value=False)
    @patch('pokepoke.cleanup_agents.get_pokepoke_prompts_dir')
    @patch('pokepoke.cleanup_agents._get_current_git_context')
    @patch('pokepoke.cleanup_agents.invoke_copilot')
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

        success, stats = invoke_merge_conflict_cleanup_agent(item, Path("/repo"), "Merge error")

        assert success is True
        mock_invoke.assert_called_once()
        args = mock_invoke.call_args
        prompt = args[1]['prompt']
        assert "Merge error" in prompt

    @patch('pokepoke.cleanup_agents.merge_lock_active', return_value=False)
    @patch('pokepoke.cleanup_agents.get_pokepoke_prompts_dir')
    @patch('pokepoke.cleanup_agents.invoke_cleanup_agent')
    def test_invoke_merge_conflict_fallback(self, mock_invoke_cleanup, mock_get_dir, mock_merge_active):
        """Test fallback to standard cleanup if merge prompt missing."""
        mock_dir = MagicMock()
        mock_file = Mock()
        mock_file.exists.return_value = False
        mock_dir.__truediv__.return_value = mock_file
        mock_get_dir.return_value = mock_dir

        mock_invoke_cleanup.return_value = (True, None)

        item = BeadsWorkItem(id="1", title="T", description="D", status="open", priority=1, issue_type="task")
        success, stats = invoke_merge_conflict_cleanup_agent(item, Path("/repo"), "Error")

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

    @patch('pokepoke.cleanup_agents.invoke_cleanup_agent')
    @patch('pokepoke.cleanup_agents.commit_all_changes')
    @patch('pokepoke.cleanup_agents.verify_main_repo_clean')
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
        repo_root = Path("/fake/repo")

        # is_clean=True, no uncommitted output, no non-beads changes
        mock_verify.return_value = (True, "", [])

        success, cleanup_runs = run_cleanup_loop(item, result, repo_root)

        assert success is True
        assert cleanup_runs == 0
        mock_commit.assert_not_called()
        mock_invoke.assert_not_called()

    @patch('pokepoke.cleanup_agents.invoke_cleanup_agent')
    @patch('pokepoke.cleanup_agents.commit_all_changes')
    @patch('pokepoke.cleanup_agents.verify_main_repo_clean')
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
        repo_root = Path("/fake/repo")

        # is_clean=False (has non-beads changes), then True after commit
        mock_verify.return_value = (False, " M file.py\n", [" M file.py"])
        mock_commit.return_value = (True, "")

        success, cleanup_runs = run_cleanup_loop(item, result, repo_root)

        assert success is True
        assert cleanup_runs == 0
        mock_commit.assert_called_once()
        mock_invoke.assert_not_called()

    @patch('pokepoke.cleanup_agents.invoke_cleanup_agent')
    @patch('pokepoke.cleanup_agents.commit_all_changes')
    @patch('pokepoke.cleanup_agents.verify_main_repo_clean')
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
        repo_root = Path("/fake/repo")

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

        success, cleanup_runs = run_cleanup_loop(item, result, repo_root)

        assert success is True
        assert cleanup_runs == 1
        mock_commit.assert_called_once()
        mock_invoke.assert_called_once()
        # Stats should be aggregated
        assert result.stats.wall_duration == 15.0

    @patch('pokepoke.cleanup_agents.invoke_cleanup_agent')
    @patch('pokepoke.cleanup_agents.commit_all_changes')
    @patch('pokepoke.cleanup_agents.verify_main_repo_clean')
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
        repo_root = Path("/fake/repo")

        # is_clean=False (has non-beads changes)
        mock_verify.return_value = (False, " M file.py\n", [" M file.py"])
        mock_commit.return_value = (False, "Tests failed")
        mock_invoke.return_value = (False, None)

        success, cleanup_runs = run_cleanup_loop(item, result, repo_root)

        assert success is False
        assert cleanup_runs == 1
        assert result.success is False
        assert "Cleanup agent failed" in result.error


class TestRunCleanupLoopErrorHandling:
    """Test error handling paths in run_cleanup_loop."""

    @patch('pokepoke.cleanup_agents.verify_main_repo_clean')
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

        success, cleanup_runs = run_cleanup_loop(item, result, Path("/repo"))

        assert success is True
        assert cleanup_runs == 0

    @patch('pokepoke.cleanup_agents.invoke_cleanup_agent')
    @patch('pokepoke.cleanup_agents.commit_all_changes')
    @patch('pokepoke.cleanup_agents.verify_main_repo_clean')
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

        success, cleanup_runs = run_cleanup_loop(item, result, Path("/repo"))

        assert success is False
        assert cleanup_runs == 1
        assert "Git status check failed" in result.error


class TestRunAgentWithUiException:
    """Test exception handling in _run_agent_with_ui."""

    @patch('pokepoke.cleanup_agents.terminal_ui')
    @patch('pokepoke.cleanup_agents.invoke_copilot')
    def test_run_agent_with_ui_exception_reraises(self, mock_invoke, mock_ui):
        """Test that _run_agent_with_ui re-raises exceptions after logging."""
        from pokepoke.cleanup_agents import _run_agent_with_ui

        mock_invoke.side_effect = RuntimeError("Copilot crashed")

        item = BeadsWorkItem(
            id="test-1", title="T", description="D",
            status="in_progress", priority=1, issue_type="task"
        )

        with patch('pokepoke.cleanup_agents.agent_type_context', create=True), \
             pytest.raises(RuntimeError, match="Copilot crashed"):
            _run_agent_with_ui(
                "test-1", "Test Agent", "cleanup",
                item, "prompt", None, None,
            )


class TestMergeWaitLogic:
    """Test merge wait logic in invoke_cleanup_agent and invoke_merge_conflict_cleanup_agent."""

    @patch('pokepoke.cleanup_agents.merge_lock_active')
    @patch('pokepoke.cleanup_agents.load_prompt_file')
    @patch('pokepoke.cleanup_agents._get_current_git_context')
    @patch('pokepoke.cleanup_agents.invoke_copilot')
    @patch('pokepoke.cleanup_agents.terminal_ui')
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

        with patch('pokepoke.cleanup_agents.time.sleep'):
            success, stats = invoke_cleanup_agent(item, Path("/repo"), wait_for_merge=True)

        assert success is True

    @patch('pokepoke.cleanup_agents.merge_lock_active')
    @patch('pokepoke.cleanup_agents.load_prompt_file')
    @patch('pokepoke.cleanup_agents._get_current_git_context')
    @patch('pokepoke.cleanup_agents.invoke_copilot')
    @patch('pokepoke.cleanup_agents.terminal_ui')
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

        with patch('pokepoke.cleanup_agents.time.sleep'):
            success, stats = invoke_cleanup_agent(item, Path("/repo"), wait_for_merge=True)

        assert success is True

    @patch('pokepoke.cleanup_agents.merge_lock_active')
    @patch('pokepoke.cleanup_agents.load_prompt_file')
    @patch('pokepoke.cleanup_agents._get_current_git_context')
    @patch('pokepoke.cleanup_agents.invoke_copilot')
    @patch('pokepoke.cleanup_agents.terminal_ui')
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

        success, stats = invoke_cleanup_agent(item, Path("/repo"), wait_for_merge=False)

        assert success is True
        mock_merge_active.assert_not_called()

    @patch('pokepoke.cleanup_agents.merge_lock_active')
    @patch('pokepoke.cleanup_agents.load_prompt_file')
    @patch('pokepoke.cleanup_agents._get_current_git_context')
    @patch('pokepoke.cleanup_agents.invoke_copilot')
    @patch('pokepoke.cleanup_agents.terminal_ui')
    @patch('pokepoke.git_operations.is_merge_in_progress', return_value=False)
    @patch('pokepoke.git_operations.get_unmerged_files', return_value=[])
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

        with patch('pokepoke.cleanup_agents.time.sleep'):
            success, stats = invoke_merge_conflict_cleanup_agent(
                item, Path("/repo"), "Merge error", wait_for_merge=True
            )

        assert success is True

    @patch('pokepoke.cleanup_agents.merge_lock_active')
    @patch('pokepoke.cleanup_agents.load_prompt_file')
    @patch('pokepoke.cleanup_agents._get_current_git_context')
    @patch('pokepoke.cleanup_agents.invoke_copilot')
    @patch('pokepoke.cleanup_agents.terminal_ui')
    @patch('pokepoke.git_operations.is_merge_in_progress', return_value=False)
    @patch('pokepoke.git_operations.get_unmerged_files', return_value=[])
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

        with patch('pokepoke.cleanup_agents.time.sleep'):
            success, stats = invoke_merge_conflict_cleanup_agent(
                item, Path("/repo"), "Merge error", wait_for_merge=True
            )

        assert success is True

    @patch('pokepoke.cleanup_agents.merge_lock_active')
    @patch('pokepoke.cleanup_agents.load_prompt_file')
    @patch('pokepoke.cleanup_agents._get_current_git_context')
    @patch('pokepoke.cleanup_agents.invoke_copilot')
    @patch('pokepoke.cleanup_agents.terminal_ui')
    @patch('pokepoke.git_operations.is_merge_in_progress', return_value=True)
    @patch('pokepoke.git_operations.get_unmerged_files', return_value=["file1.py", "file2.py", "file3.py", "file4.py", "file5.py", "file6.py"])
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

        success, stats = invoke_merge_conflict_cleanup_agent(
            item, Path("/repo"), "Merge error",
            unmerged_files=["f1.py", "f2.py", "f3.py", "f4.py", "f5.py", "f6.py"],
            wait_for_merge=False,
        )

        assert success is True


class TestWorktreeCleanupPromptSafety:
    """Tests to verify the worktree cleanup prompt prohibits process killing."""

    def test_prompt_prohibits_stop_process(self):
        """The worktree-cleanup prompt must explicitly forbid Stop-Process."""
        prompt_path = Path(__file__).parent.parent / "src" / "pokepoke" / "builtin_prompts" / "worktree-cleanup.md"
        content = prompt_path.read_text(encoding='utf-8')
        assert "Stop-Process" in content, "Prompt must explicitly mention Stop-Process as forbidden"

    def test_prompt_prohibits_kill(self):
        """The worktree-cleanup prompt must explicitly forbid kill commands."""
        prompt_path = Path(__file__).parent.parent / "src" / "pokepoke" / "builtin_prompts" / "worktree-cleanup.md"
        content = prompt_path.read_text(encoding='utf-8')
        assert "taskkill" in content, "Prompt must explicitly mention taskkill as forbidden"

    def test_prompt_prohibits_process_killing_section(self):
        """The worktree-cleanup prompt must have a NEVER kill processes section."""
        prompt_path = Path(__file__).parent.parent / "src" / "pokepoke" / "builtin_prompts" / "worktree-cleanup.md"
        content = prompt_path.read_text(encoding='utf-8')
        assert "NEVER Kill or Stop Any Running Processes" in content

    def test_prompt_forbids_stale_process_cleanup(self):
        """The worktree-cleanup prompt must forbid killing 'stale' processes."""
        prompt_path = Path(__file__).parent.parent / "src" / "pokepoke" / "builtin_prompts" / "worktree-cleanup.md"
        content = prompt_path.read_text(encoding='utf-8')
        # Must mention stale processes as forbidden
        assert "stale" in content.lower()
        assert "zombie" in content.lower() or "orphan" in content.lower()

    @patch('pokepoke.agent_runner.has_unmerged_worktrees', return_value=True)
    @patch('pokepoke.agent_runner.get_pokepoke_prompts_dir')
    @patch('pokepoke.agent_runner._run_main_repo_agent')
    @patch('pokepoke.agent_runner.terminal_ui')
    def test_worktree_cleanup_injects_orchestrator_pid(
        self, mock_ui, mock_run_agent, mock_prompts_dir, mock_has_unmerged, tmp_path
    ):
        """run_worktree_cleanup must inject the orchestrator PID into the prompt."""
        import os
        from pokepoke.agent_runner import run_worktree_cleanup

        # Create a minimal prompt file
        prompt_file = tmp_path / "worktree-cleanup.md"
        prompt_file.write_text("# Cleanup\nDo stuff.", encoding='utf-8')
        mock_prompts_dir.return_value = tmp_path

        # Mock the retry/count functions at their source module (they are locally imported)
        with patch('pokepoke.worktree_cleanup.retry_failed_cleanups', return_value=0), \
             patch('pokepoke.worktree_cleanup.get_uncleaned_worktree_count', return_value=0):
            mock_run_agent.return_value = None
            run_worktree_cleanup()

        # Verify the prompt passed to _run_main_repo_agent includes the PID
        call_args = mock_run_agent.call_args
        prompt_passed = call_args[1].get('agent_prompt') or call_args[0][2]
        assert str(os.getpid()) in prompt_passed, "Orchestrator PID must be injected into cleanup prompt"
        assert "DO NOT TOUCH" in prompt_passed
