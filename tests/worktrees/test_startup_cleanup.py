"""Tests for startup cleanup of stale worktrees."""

from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from pokepoke.config import GitConfig, ProjectConfig
from pokepoke.worktrees.startup_cleanup import cleanup_stale_worktrees_at_startup


@pytest.fixture
def mock_config():
    """Create a mock configuration for testing."""
    return ProjectConfig(
        startup_cleanup_enabled=True,
        stale_worktree_commit_threshold=20,
        git=GitConfig(default_branch="main", fallback_branch="master")
    )


@pytest.fixture
def disabled_config():
    """Create a configuration with cleanup disabled."""
    return ProjectConfig(
        startup_cleanup_enabled=False,
        stale_worktree_commit_threshold=20,
        git=GitConfig(default_branch="main", fallback_branch="master")
    )


@pytest.fixture
def mock_worktrees():
    """Mock worktree list for testing."""
    return [
        {"path": "/repo", "branch": None},  # Main repo - should be skipped
        {"path": "/repo/worktrees/task-item1", "branch": "task/item1", "commit": "abc123"},
        {"path": "/repo/worktrees/task-item2", "branch": "task/item2", "commit": "def456"},
        {"path": "/repo/worktrees/task-item3", "branch": "task/item3", "commit": "ghi789"},
    ]


class TestStartupCleanup:
    """Test the startup cleanup functionality."""

    def test_cleanup_disabled_returns_empty_stats(self, disabled_config):
        """Test that cleanup returns empty stats when disabled."""
        stats = cleanup_stale_worktrees_at_startup(cfg=disabled_config)

        expected = {
            'stale_removed': 0,
            'merged_removed': 0,
            'total_removed': 0,
            'errors': 0,
            'checked': 0,
        }
        assert stats == expected

    @patch('pokepoke.worktrees.startup_cleanup.list_worktrees')
    @patch('pokepoke.worktrees.startup_cleanup.is_worktree_merged')
    @patch('pokepoke.worktrees.startup_cleanup.get_commits_behind')
    @patch('pokepoke.worktrees.startup_cleanup._cleanup_worktree_safe')
    def test_cleanup_stale_worktrees(self, mock_cleanup, mock_commits_behind,
                                   mock_is_merged, mock_list_worktrees,
                                   mock_config, mock_worktrees):
        """Test cleanup of stale worktrees that are far behind."""
        # Setup mocks
        mock_list_worktrees.return_value = mock_worktrees
        mock_is_merged.return_value = False

        # item1: 5 commits behind (keep)
        # item2: 25 commits behind (remove)
        # item3: 50 commits behind (remove)
        mock_commits_behind.side_effect = [5, 25, 50]

        stats = cleanup_stale_worktrees_at_startup(repo_path="/repo", cfg=mock_config)

        # Should remove 2 stale worktrees (item2, item3)
        assert stats['stale_removed'] == 2
        assert stats['merged_removed'] == 0
        assert stats['total_removed'] == 2
        assert stats['errors'] == 0
        assert stats['checked'] == 3  # 3 worktrees checked (excluding main repo)

        # Verify cleanup was called for the right branches
        expected_calls = [
            (("task/item2", "/repo/worktrees/task-item2", "/repo"), {}),
            (("task/item3", "/repo/worktrees/task-item3", "/repo"), {}),
        ]
        assert mock_cleanup.call_args_list == expected_calls

    @patch('pokepoke.worktrees.startup_cleanup.list_worktrees')
    @patch('pokepoke.worktrees.startup_cleanup.is_worktree_merged')
    @patch('pokepoke.worktrees.startup_cleanup.get_commits_behind')
    @patch('pokepoke.worktrees.startup_cleanup._cleanup_worktree_safe')
    def test_cleanup_merged_worktrees(self, mock_cleanup, mock_commits_behind,
                                    mock_is_merged, mock_list_worktrees,
                                    mock_config, mock_worktrees):
        """Test cleanup of merged worktrees regardless of distance."""
        # Setup mocks
        mock_list_worktrees.return_value = mock_worktrees

        # item1: merged (remove)
        # item2: not merged, 5 commits behind (keep)
        # item3: not merged, 10 commits behind (keep)
        mock_is_merged.side_effect = [True, False, False]
        mock_commits_behind.side_effect = [None, 5, 10]  # merged branches don't need commit count

        stats = cleanup_stale_worktrees_at_startup(repo_path="/repo", cfg=mock_config)

        # Should remove 1 merged worktree (item1)
        assert stats['stale_removed'] == 0
        assert stats['merged_removed'] == 1
        assert stats['total_removed'] == 1
        assert stats['errors'] == 0
        assert stats['checked'] == 3

        # Verify cleanup was called only for merged branch
        mock_cleanup.assert_called_once_with("task/item1", "/repo/worktrees/task-item1", "/repo")

        # Verify is_worktree_merged was called with item_id (not full branch name)
        expected_calls = [
            (("item1", "main", "/repo"), {}),  # item_id extracted from "task/item1"
            (("item2", "main", "/repo"), {}),  # item_id extracted from "task/item2"
            (("item3", "main", "/repo"), {}),  # item_id extracted from "task/item3"
        ]
        assert mock_is_merged.call_args_list == expected_calls

    @patch('pokepoke.worktrees.startup_cleanup.list_worktrees')
    @patch('pokepoke.worktrees.startup_cleanup.is_worktree_merged')
    @patch('pokepoke.worktrees.startup_cleanup._cleanup_worktree_safe')
    def test_merged_detection_with_item_id_extraction(self, mock_cleanup, mock_is_merged,
                                                     mock_list_worktrees, mock_config):
        """Test that item_id is correctly extracted from branch name for merged detection."""
        # Test worktree with standard task/ prefix
        worktrees = [
            {"path": "/repo", "branch": None},  # Main repo - should be skipped
            {"path": "/repo/worktrees/task-my-feature", "branch": "task/my-feature"},
            {"path": "/repo/worktrees/custom-branch", "branch": "custom-branch"},
        ]
        mock_list_worktrees.return_value = worktrees

        # Both worktrees are merged
        mock_is_merged.return_value = True

        stats = cleanup_stale_worktrees_at_startup(repo_path="/repo", cfg=mock_config)

        # Should remove both merged worktrees
        assert stats['merged_removed'] == 2
        assert stats['total_removed'] == 2
        assert stats['checked'] == 2

        # Verify is_worktree_merged was called with correct item_ids
        expected_calls = [
            (("my-feature", "main", "/repo"), {}),      # "task/" prefix removed
            (("custom-branch", "main", "/repo"), {}),   # Non-task branch used as-is
        ]
        assert mock_is_merged.call_args_list == expected_calls

    @patch('pokepoke.worktrees.startup_cleanup.list_worktrees')
    @patch('pokepoke.worktrees.startup_cleanup.is_worktree_merged')
    @patch('pokepoke.worktrees.startup_cleanup.get_commits_behind')
    @patch('pokepoke.worktrees.startup_cleanup._cleanup_worktree_safe')
    def test_cleanup_handles_git_errors_gracefully(self, mock_cleanup, mock_commits_behind,
                                                  mock_is_merged, mock_list_worktrees,
                                                  mock_config, mock_worktrees):
        """Test that git command failures don't crash the cleanup."""
        # Setup mocks
        mock_list_worktrees.return_value = mock_worktrees
        mock_is_merged.return_value = False

        # First call succeeds (5 commits), second fails, third succeeds (30 commits)
        mock_commits_behind.side_effect = [5, None, 30]

        stats = cleanup_stale_worktrees_at_startup(repo_path="/repo", cfg=mock_config)

        # Should remove 1 stale worktree (item3), skip item2 due to git error
        assert stats['stale_removed'] == 1
        assert stats['merged_removed'] == 0
        assert stats['total_removed'] == 1
        assert stats['errors'] == 0  # Git errors don't count as processing errors
        assert stats['checked'] == 3

        # Verify cleanup was called only for item3
        mock_cleanup.assert_called_once_with("task/item3", "/repo/worktrees/task-item3", "/repo")

    @patch('pokepoke.worktrees.startup_cleanup.list_worktrees')
    @patch('pokepoke.worktrees.startup_cleanup.is_worktree_merged')
    @patch('pokepoke.worktrees.startup_cleanup._cleanup_worktree_safe')
    def test_cleanup_handles_cleanup_errors(self, mock_cleanup, mock_is_merged,
                                          mock_list_worktrees, mock_config, mock_worktrees):
        """Test that cleanup errors are counted but don't stop processing."""
        # Setup mocks - only first two worktrees are merged, third is not merged
        mock_list_worktrees.return_value = mock_worktrees[:3]  # Only use first 3 worktrees
        mock_is_merged.side_effect = [True, True]  # First two are merged
        mock_cleanup.side_effect = [Exception("Cleanup failed"), None]  # First cleanup fails

        stats = cleanup_stale_worktrees_at_startup(repo_path="/repo", cfg=mock_config)

        # Should attempt to remove 2 merged worktrees, one fails
        assert stats['merged_removed'] == 1  # Only second cleanup succeeded
        assert stats['errors'] == 1  # First cleanup failure
        assert stats['total_removed'] == 1
        assert stats['checked'] == 2  # Only checked first 2 non-main worktrees

    def test_config_validation(self, caplog):
        """Test that configuration values are properly validated."""
        import logging
        # Test minimum threshold is enforced with warning
        with caplog.at_level(logging.WARNING, logger="pokepoke.config"):
            config = ProjectConfig(stale_worktree_commit_threshold=0)
        assert config.stale_worktree_commit_threshold == 1  # Clamped to minimum
        assert "stale_worktree_commit_threshold" in caplog.text

    @patch('pokepoke.worktrees.startup_cleanup.list_worktrees')
    def test_no_worktrees_to_process(self, mock_list_worktrees, mock_config):
        """Test behavior when there are no worktrees to process."""
        mock_list_worktrees.return_value = [{"path": "/repo", "branch": None}]  # Only main repo

        stats = cleanup_stale_worktrees_at_startup(repo_path="/repo", cfg=mock_config)

        assert stats['checked'] == 0
        assert stats['total_removed'] == 0
        assert stats['errors'] == 0

    @patch('pokepoke.worktrees.startup_cleanup.list_worktrees')
    def test_empty_worktree_list(self, mock_list_worktrees, mock_config):
        """Test behavior when git worktree list returns empty."""
        mock_list_worktrees.return_value = []

        stats = cleanup_stale_worktrees_at_startup(repo_path="/repo", cfg=mock_config)

        assert stats['checked'] == 0
        assert stats['total_removed'] == 0
        assert stats['errors'] == 0

    @patch('pokepoke.worktrees.startup_cleanup.list_worktrees')
    def test_list_worktrees_failure(self, mock_list_worktrees, mock_config):
        """Test handling of list_worktrees failure."""
        mock_list_worktrees.side_effect = Exception("Git command failed")

        stats = cleanup_stale_worktrees_at_startup(repo_path="/repo", cfg=mock_config)

        # Should handle error gracefully
        assert stats['errors'] == 1
        assert stats['checked'] == 0
        assert stats['total_removed'] == 0


class TestCleanupWorktreeSafe:
    """Test the safe worktree cleanup function."""

    @patch('pokepoke.worktrees.startup_cleanup.with_worktree_lock')
    @patch('pokepoke.worktrees.startup_cleanup.cleanup_worktree_and_branch')
    def test_cleanup_with_task_branch(self, mock_cleanup_func, mock_lock):
        """Test cleanup of worktree with task/ branch prefix."""
        from pokepoke.worktrees.startup_cleanup import _cleanup_worktree_safe

        mock_lock.return_value.__enter__ = Mock()
        mock_lock.return_value.__exit__ = Mock(return_value=None)

        _cleanup_worktree_safe("task/my-feature", "/path/to/worktree", "/repo")

        mock_cleanup_func.assert_called_once_with(
            worktree_path=Path("/path/to/worktree"),
            branch_name="task/my-feature",
            worktree_id="my-feature",
            cwd="/repo"
        )

    @patch('pokepoke.worktrees.startup_cleanup.with_worktree_lock')
    @patch('pokepoke.worktrees.startup_cleanup.cleanup_worktree_and_branch')
    def test_cleanup_with_non_task_branch(self, mock_cleanup_func, mock_lock):
        """Test cleanup of worktree without task/ prefix."""
        from pokepoke.worktrees.startup_cleanup import _cleanup_worktree_safe

        mock_lock.return_value.__enter__ = Mock()
        mock_lock.return_value.__exit__ = Mock(return_value=None)

        _cleanup_worktree_safe("feature-branch", "/path/to/worktree", "/repo")

        mock_cleanup_func.assert_called_once_with(
            worktree_path=Path("/path/to/worktree"),
            branch_name="feature-branch",
            worktree_id="feature-branch",
            cwd="/repo"
        )

    @patch('pokepoke.worktrees.startup_cleanup.with_worktree_lock')
    @patch('pokepoke.worktrees.startup_cleanup.cleanup_worktree_and_branch')
    def test_cleanup_error_handling(self, mock_cleanup_func, mock_lock):
        """Test that cleanup errors are properly propagated."""
        from pokepoke.worktrees.startup_cleanup import _cleanup_worktree_safe

        mock_lock.return_value.__enter__ = Mock()
        mock_lock.return_value.__exit__ = Mock(return_value=None)
        mock_cleanup_func.side_effect = Exception("Cleanup failed")

        with pytest.raises(Exception, match="Cleanup failed"):
            _cleanup_worktree_safe("task/feature", "/path/to/worktree", "/repo")
