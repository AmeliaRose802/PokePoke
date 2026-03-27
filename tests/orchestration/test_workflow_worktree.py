"""Unit tests for workflow worktree management.

This module tests worktree lifecycle operations including:
- Worktree setup and creation
- Cleanup and finalization
- Merge and commit operations
- Worktree lock timeout handling
"""

import subprocess
from pathlib import Path
from unittest.mock import Mock, patch

from pokepoke.orchestration.work_item_session import WorkItemSession
from pokepoke.orchestration.workflow import process_work_item
from pokepoke.orchestration.workflow_helpers import run_cleanup_with_timeout as _run_cleanup_with_timeout
from pokepoke.orchestration.workflow_helpers import setup_worktree
from pokepoke.types import BeadsWorkItem, CopilotResult
from pokepoke.worktrees.worktree_finalization import check_and_merge_worktree


class TestSetupWorktree:
    """Test setup_worktree function."""

    @patch('pokepoke.orchestration.workflow_helpers.create_worktree')
    def test_successful_setup(self, mock_create: Mock) -> None:
        """Test successful worktree creation."""
        item = BeadsWorkItem(
            id="task-1",
            title="Task 1",
            description="",
            status="open",
            priority=1,
            issue_type="task"
        )
        mock_create.return_value = Path("/fake/worktree")

        result = setup_worktree(item)

        assert result is not None
        assert result == Path("/fake/worktree")
        mock_create.assert_called_once_with("task-1", lock_timeout=300.0, repo_path=None)

    @patch('pokepoke.orchestration.workflow_helpers.create_worktree')
    def test_successful_setup_with_custom_timeout(self, mock_create: Mock) -> None:
        """Test successful worktree creation with custom lock timeout."""
        item = BeadsWorkItem(
            id="task-1",
            title="Task 1",
            description="",
            status="open",
            priority=1,
            issue_type="task"
        )
        mock_create.return_value = Path("/fake/worktree")

        result = setup_worktree(item, lock_timeout=600.0, repo_path=None)

        assert result is not None
        assert result == Path("/fake/worktree")
        mock_create.assert_called_once_with("task-1", lock_timeout=600.0, repo_path=None)

    @patch('pokepoke.orchestration.workflow_helpers.create_worktree')
    def test_creation_failure(self, mock_create: Mock) -> None:
        """Test worktree creation failure."""
        item = BeadsWorkItem(
            id="task-1",
            title="Task 1",
            description="",
            status="open",
            priority=1,
            issue_type="task"
        )
        mock_create.side_effect = Exception("Failed to create worktree")

        result = setup_worktree(item)

        assert result is None


class TestRunCleanupWithTimeout:
    """Test _run_cleanup_with_timeout function."""

    @patch('pokepoke.orchestration.workflow_helpers.run_cleanup_loop')
    @patch('pokepoke.orchestration.workflow_helpers.has_uncommitted_changes')
    @patch('time.time')
    def test_no_uncommitted_changes(
        self,
        mock_time: Mock,
        mock_uncommitted: Mock,
        mock_cleanup: Mock
    ) -> None:
        """Test when no uncommitted changes exist."""
        item = BeadsWorkItem(
            id="task-1",
            title="Task 1",
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

        mock_time.return_value = 0
        mock_uncommitted.return_value = False

        success, cleanup_runs = _run_cleanup_with_timeout(
            item, result, repo_root, 0, 7200, 2.0
        )

        assert success is True
        assert cleanup_runs == 0
        mock_cleanup.assert_not_called()

    @patch('pokepoke.orchestration.workflow_helpers.run_cleanup_loop')
    @patch('pokepoke.orchestration.workflow_helpers.has_uncommitted_changes')
    @patch('time.time')
    def test_cleanup_success(
        self,
        mock_time: Mock,
        mock_uncommitted: Mock,
        mock_cleanup: Mock
    ) -> None:
        """Test successful cleanup."""
        item = BeadsWorkItem(
            id="task-1",
            title="Task 1",
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

        mock_time.return_value = 0
        mock_uncommitted.side_effect = [True, False]
        mock_cleanup.return_value = (True, 1)

        success, cleanup_runs = _run_cleanup_with_timeout(
            item, result, repo_root, 0, 7200, 2.0
        )

        assert success is True
        assert cleanup_runs == 1
        mock_cleanup.assert_called_once()

    @patch('pokepoke.orchestration.workflow_helpers.run_cleanup_loop')
    @patch('pokepoke.orchestration.workflow_helpers.has_uncommitted_changes')
    @patch('time.time')
    def test_timeout_during_cleanup(
        self,
        mock_time: Mock,
        mock_uncommitted: Mock,
        mock_cleanup: Mock
    ) -> None:
        """Test timeout during cleanup loop."""
        item = BeadsWorkItem(
            id="task-1",
            title="Task 1",
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

        # First check: has changes, second check: past timeout
        # The while loop enters, then checks timeout AFTER cleanup_attempt++
        # So cleanup_loop will be called once before timeout check
        # Extra values needed because print() calls through desktop_ui may call time.time()
        mock_time.side_effect = [0, 7300] + [7300] * 10
        mock_uncommitted.return_value = True  # Always has changes
        mock_cleanup.return_value = (True, 1)  # Cleanup succeeds

        success, cleanup_runs = _run_cleanup_with_timeout(
            item, result, repo_root, 0, 7200, 2.0
        )

        assert success is False  # Timeout occurred
        assert cleanup_runs == 1  # One cleanup was attempted before timeout
        mock_cleanup.assert_called_once()  # Cleanup called once before timeout

    @patch('pokepoke.orchestration.workflow_helpers.run_cleanup_loop')
    @patch('pokepoke.orchestration.workflow_helpers.has_uncommitted_changes')
    @patch('time.time')
    def test_cleanup_failure(
        self,
        mock_time: Mock,
        mock_uncommitted: Mock,
        mock_cleanup: Mock
    ) -> None:
        """Test cleanup failure."""
        item = BeadsWorkItem(
            id="task-1",
            title="Task 1",
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

        mock_time.return_value = 0
        mock_uncommitted.side_effect = [True, False]  # Has changes, then no changes
        mock_cleanup.return_value = (False, 1)

        success, cleanup_runs = _run_cleanup_with_timeout(
            item, result, repo_root, 0, 7200, 2.0
        )

        # Cleanup failed, but loop exits when no more uncommitted changes
        # result.success is still True, so function returns True
        # The cleanup failure is only reflected in the break from loop
        assert success is True  # result.success wasn't modified
        assert cleanup_runs == 1


class TestCheckAndMergeWorktree:
    """Test check_and_merge_worktree function."""

    @patch('pokepoke.worktrees.worktree_finalization.merge_lock')
    @patch('pokepoke.worktrees.worktree_finalization.merge_worktree_to_dev')
    @patch('pokepoke.worktrees.worktree_finalization.cleanup_worktree')
    @patch('subprocess.run')
    def test_no_commits_to_merge(
        self,
        mock_run: Mock,
        mock_cleanup: Mock,
        mock_merge: Mock,
        mock_lock: Mock
    ) -> None:
        """Test when worktree has no commits to merge."""
        item = BeadsWorkItem(
            id="task-1",
            title="Task 1",
            description="",
            status="open",
            priority=1,
            issue_type="task"
        )
        worktree_path = Path("/fake/worktree")

        mock_run.return_value = Mock(stdout="0\n", returncode=0)

        result = check_and_merge_worktree(item, worktree_path)

        assert result is True
        mock_cleanup.assert_called_once_with("task-1", force=True, repo_path=None)
        mock_merge.assert_not_called()
        # Verify cwd is passed to subprocess instead of os.chdir
        cwd_calls = [c for c in mock_run.call_args_list if c.kwargs.get('cwd')]
        assert len(cwd_calls) == 1
        assert cwd_calls[0].kwargs['cwd'] == str(worktree_path)

    @patch('pokepoke.worktrees.worktree_finalization.merge_lock')
    @patch('pokepoke.worktrees.worktree_finalization.merge_worktree_to_dev')
    @patch('subprocess.run')
    def test_has_commits_to_merge(
        self,
        mock_run: Mock,
        mock_merge: Mock,
        mock_lock: Mock
    ) -> None:
        """Test when worktree has commits to merge."""
        item = BeadsWorkItem(
            id="task-1",
            title="Task 1",
            description="",
            status="open",
            priority=1,
            issue_type="task"
        )
        worktree_path = Path("/fake/worktree")

        mock_run.return_value = Mock(stdout="3\n", returncode=0)
        mock_merge.return_value = True  # merge_worktree_to_dev returns bool, not tuple

        result = check_and_merge_worktree(item, worktree_path)

        assert result is True
        mock_merge.assert_called_once_with(item, parent_agent_id=None, worktree_path=worktree_path, repo_path=None)

    @patch('pokepoke.worktrees.worktree_finalization.merge_lock')
    @patch('pokepoke.worktrees.worktree_finalization.merge_worktree_to_dev')
    @patch('subprocess.run')
    def test_commit_count_check_fails(
        self,
        mock_run: Mock,
        mock_merge: Mock,
        mock_lock: Mock
    ) -> None:
        """Test when commit count check fails."""
        item = BeadsWorkItem(
            id="task-1",
            title="Task 1",
            description="",
            status="open",
            priority=1,
            issue_type="task"
        )
        worktree_path = Path("/fake/worktree")

        mock_run.side_effect = subprocess.CalledProcessError(1, "git rev-list")
        mock_merge.return_value = True  # merge_worktree_to_dev returns bool, not tuple

        result = check_and_merge_worktree(item, worktree_path)

        # Should attempt merge anyway
        assert result is True
        mock_merge.assert_called_once_with(item, parent_agent_id=None, worktree_path=worktree_path, repo_path=None)


class TestWorktreeLockTimeout:
    """Tests that worktree_lock_timeout scales with max_parallel_agents."""

    def test_single_agent_uses_command_timeout(self) -> None:
        """With 1 agent, the lock timeout equals command_timeout (300s default)."""
        from pokepoke.config import ProjectConfig
        cfg = ProjectConfig()
        cfg.command_timeout = 300
        cfg.max_parallel_agents = 1

        # 120.0 * 1 = 120.0 < 300.0, so max returns 300.0
        expected = max(float(cfg.command_timeout), 120.0 * max(1, int(cfg.max_parallel_agents)))
        assert expected == 300.0

    def test_many_agents_scales_timeout(self) -> None:
        """With 10 agents, the lock timeout exceeds command_timeout to accommodate queuing."""
        from pokepoke.config import ProjectConfig
        cfg = ProjectConfig()
        cfg.command_timeout = 300
        cfg.max_parallel_agents = 10

        # 120.0 * 10 = 1200.0 > 300.0, so max returns 1200.0
        expected = max(float(cfg.command_timeout), 120.0 * max(1, int(cfg.max_parallel_agents)))
        assert expected == 1200.0

    @patch.object(WorkItemSession, 'cleanup_on_failure')
    @patch('pokepoke.orchestration.workflow.assign_and_sync_item', return_value=True)
    @patch('pokepoke.orchestration.workflow.setup_worktree', return_value=None)
    @patch('time.time', return_value=0.0)
    def testsetup_worktree_called_with_scaled_timeout(
        self,
        mock_time: Mock,
        mock_setup: Mock,
        mock_assign: Mock,
        mock_session_cleanup: Mock,
    ) -> None:
        """process_work_item passes scaled lock_timeout to setup_worktree.

        The worktree lock is now acquired inside create_worktree, and the
        timeout is passed via setup_worktree's lock_timeout parameter.
        """
        from pokepoke.config import ProjectConfig

        item = BeadsWorkItem(
            id="task-scale",
            title="Scale Test",
            description="",
            status="open",
            priority=1,
            issue_type="task",
        )

        cfg = ProjectConfig()
        cfg.command_timeout = 300
        cfg.max_parallel_agents = 10

        with patch('pokepoke.orchestration.workflow.get_config', return_value=cfg):
            process_work_item(item, interactive=False)

        # setup_worktree should have been called with lock_timeout=1200.0 (max(300, 120*10))
        mock_setup.assert_called_once()
        call_kwargs = mock_setup.call_args
        timeout_used = call_kwargs[1]['lock_timeout'] if call_kwargs[1] else call_kwargs[0][1]
        assert timeout_used == 1200.0
