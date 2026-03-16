"""Comprehensive unit tests for core worktree functions.

Tests for create_worktree, merge_worktree, list_worktrees, and error handling.
"""

import subprocess
from pathlib import Path
from unittest.mock import Mock, patch
import pytest

from pokepoke.worktrees.worktrees import (
    create_worktree,
    is_worktree_merged,
    merge_worktree,
    list_worktrees,
    cleanup_worktree,
    _run_git,
)


class TestRunGit:
    """Tests for _run_git helper."""

    def test_run_git_success(self) -> None:
        """_run_git returns subprocess result on success."""
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = Mock(
                stdout='branch info',
                stderr='',
                returncode=0,
                args=['git', 'branch']
            )
            result = _run_git(['git', 'branch'])
            assert result.stdout == 'branch info'
            assert result.returncode == 0

    def test_run_git_sets_encoding_and_timeout(self) -> None:
        """_run_git uses UTF-8 encoding and default timeout."""
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = Mock(returncode=0)
            _run_git(['git', 'status'])

            call_kwargs = mock_run.call_args[1]
            assert call_kwargs['text'] is True
            assert call_kwargs['encoding'] == 'utf-8'
            assert call_kwargs['timeout'] == 30
            assert call_kwargs['capture_output'] is True

    def test_run_git_custom_timeout(self) -> None:
        """_run_git respects custom timeout."""
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = Mock(returncode=0)
            _run_git(['git', 'status'], timeout=60)

            assert mock_run.call_args[1]['timeout'] == 60

    def test_run_git_check_false(self) -> None:
        """_run_git always passes check=True (not configurable)."""
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = Mock(returncode=0)
            _run_git(['git', 'status'])

            assert mock_run.call_args[1]['check'] is True

    def test_run_git_timeout_expired(self) -> None:
        """_run_git propagates TimeoutExpired."""
        with patch('subprocess.run') as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired(cmd='git', timeout=30)

            with pytest.raises(subprocess.TimeoutExpired):
                _run_git(['git', 'slow-command'])


class TestCreateWorktree:
    """Tests for create_worktree function."""

    @patch('pokepoke.worktrees.worktrees.get_default_branch')
    @patch('pokepoke.worktrees.worktrees.list_worktrees')
    @patch('pokepoke.worktrees.worktrees.with_worktree_lock')
    @patch('pokepoke.worktrees.worktrees._run_git')
    @patch('pathlib.Path.mkdir')
    @patch('pokepoke.worktrees.worktrees._validate_worktree_integrity')
    def test_create_worktree_new_success(
        self,
        mock_validate,
        mock_mkdir,
        mock_run_git,
        mock_lock,
        mock_list,
        mock_default_branch,
    ) -> None:
        """Successfully create a new worktree."""
        mock_default_branch.return_value = 'main'
        mock_list.return_value = []
        mock_lock.return_value.__enter__ = Mock(return_value=None)
        mock_lock.return_value.__exit__ = Mock(return_value=None)
        mock_run_git.return_value = Mock(returncode=0, stdout='')

        result = create_worktree('task-123')

        assert result == (Path('worktrees') / 'task-task-123').resolve()
        mock_run_git.assert_called_once()
        call_args = mock_run_git.call_args[0][0]
        assert 'git' in call_args
        assert 'worktree' in call_args
        assert 'add' in call_args

    @patch('pokepoke.worktrees.worktrees.list_worktrees')
    def test_create_worktree_reuses_existing(self, mock_list) -> None:
        """Reuse existing worktree if already created."""
        existing_path = Path('/repo/worktrees/task-task-123')
        mock_list.return_value = [
            {'path': str(existing_path.resolve()), 'branch': 'refs/heads/task/task-123'}
        ]

        result = create_worktree('task-123')

        assert result == existing_path.resolve()

    @patch('pokepoke.worktrees.worktrees.get_default_branch')
    @patch('pokepoke.worktrees.worktrees.list_worktrees')
    @patch('pokepoke.worktrees.worktrees.with_worktree_lock')
    @patch('pokepoke.worktrees.worktrees._run_git')
    @patch('pathlib.Path.mkdir')
    def test_create_worktree_git_error_branch_exists(
        self,
        mock_mkdir,
        mock_run_git,
        mock_lock,
        mock_list,
        mock_default_branch,
    ) -> None:
        """Handle 'branch already exists' error."""
        mock_default_branch.return_value = 'main'
        mock_list.side_effect = [
            [],  # First call: no existing worktrees
            [{'path': '/repo/worktrees/task-123', 'branch': 'refs/heads/task/task-123'}]  # After error
        ]
        mock_lock.return_value.__enter__ = Mock(return_value=None)
        mock_lock.return_value.__exit__ = Mock(return_value=None)

        error = subprocess.CalledProcessError(1, 'git', stderr='fatal: already exists')
        mock_run_git.side_effect = error

        result = create_worktree('task-123')

        assert result == Path('/repo/worktrees/task-123')

    @patch('pokepoke.worktrees.worktrees.get_default_branch')
    @patch('pokepoke.worktrees.worktrees.list_worktrees')
    @patch('pokepoke.worktrees.worktrees.with_worktree_lock')
    @patch('pokepoke.worktrees.worktrees._run_git')
    @patch('pathlib.Path.mkdir')
    def test_create_worktree_git_error_invalid_base_branch(
        self,
        mock_mkdir,
        mock_run_git,
        mock_lock,
        mock_list,
        mock_default_branch,
    ) -> None:
        """Raise error when base branch doesn't exist."""
        mock_default_branch.return_value = 'nonexistent'
        mock_list.return_value = []
        mock_lock.return_value.__enter__ = Mock(return_value=None)
        mock_lock.return_value.__exit__ = Mock(return_value=None)

        error = subprocess.CalledProcessError(
            128, 'git', stderr='fatal: invalid reference: nonexistent'
        )
        mock_run_git.side_effect = error

        with pytest.raises(RuntimeError, match="Base branch 'nonexistent' does not exist"):
            create_worktree('task-123')

    @patch('pokepoke.worktrees.worktrees.get_default_branch')
    @patch('pokepoke.worktrees.worktrees.list_worktrees')
    @patch('pokepoke.worktrees.worktrees.with_worktree_lock')
    @patch('pokepoke.worktrees.worktrees._run_git')
    @patch('pathlib.Path.mkdir')
    def test_create_worktree_git_timeout(
        self,
        mock_mkdir,
        mock_run_git,
        mock_lock,
        mock_list,
        mock_default_branch,
    ) -> None:
        """Raise error on git timeout."""
        mock_default_branch.return_value = 'main'
        mock_list.return_value = []
        mock_lock.return_value.__enter__ = Mock(return_value=None)
        mock_lock.return_value.__exit__ = Mock(return_value=None)

        mock_run_git.side_effect = subprocess.TimeoutExpired(cmd='git', timeout=30)

        with pytest.raises(RuntimeError, match="Timed out creating worktree"):
            create_worktree('task-123')

    @patch('pokepoke.worktrees.worktrees.get_default_branch')
    @patch('pokepoke.worktrees.worktrees.list_worktrees')
    @patch('pokepoke.worktrees.worktrees.with_worktree_lock')
    @patch('pokepoke.worktrees.worktrees._run_git')
    @patch('pathlib.Path.mkdir')
    def test_create_worktree_lock_timeout(
        self,
        mock_mkdir,
        mock_run_git,
        mock_lock,
        mock_list,
        mock_default_branch,
    ) -> None:
        """Raise error on lock timeout."""
        from filelock import Timeout

        mock_default_branch.return_value = 'main'
        mock_list.return_value = []

        class TimeoutContext:
            def __enter__(self):
                raise Timeout("lock_file")
            def __exit__(self, *args):
                pass

        mock_lock.return_value = TimeoutContext()

        with pytest.raises(RuntimeError, match="file lock|Timed out"):
            create_worktree('task-123')

    @patch('pokepoke.worktrees.worktrees.get_default_branch')
    @patch('pokepoke.worktrees.worktrees.list_worktrees')
    @patch('pokepoke.worktrees.worktrees.with_worktree_lock')
    @patch('pokepoke.worktrees.worktrees._run_git')
    @patch('pathlib.Path.mkdir')
    def test_create_worktree_unexpected_error(
        self,
        mock_mkdir,
        mock_run_git,
        mock_lock,
        mock_list,
        mock_default_branch,
    ) -> None:
        """Raise error on unexpected exception."""
        mock_default_branch.return_value = 'main'
        mock_list.return_value = []
        mock_lock.return_value.__enter__ = Mock(return_value=None)
        mock_lock.return_value.__exit__ = Mock(return_value=None)

        mock_run_git.side_effect = ValueError("unexpected error")

        with pytest.raises(RuntimeError, match="Unexpected error creating worktree"):
            create_worktree('task-123')

    @patch('pokepoke.worktrees.worktrees.get_default_branch')
    @patch('pokepoke.worktrees.worktrees.list_worktrees')
    @patch('pokepoke.worktrees.worktrees.with_worktree_lock')
    @patch('pokepoke.worktrees.worktrees._run_git')
    @patch('pathlib.Path.mkdir')
    def test_create_worktree_double_check_after_lock(
        self,
        mock_mkdir,
        mock_run_git,
        mock_lock,
        mock_list,
        mock_default_branch,
    ) -> None:
        """Worktree created by another agent is reused (double-check after lock)."""
        mock_default_branch.return_value = 'main'
        existing_path = Path('/repo/worktrees/task-task-456')
        mock_list.side_effect = [
            [],  # First call before lock
            [{'path': str(existing_path.resolve()), 'branch': 'refs/heads/task/task-456'}]  # After lock
        ]
        mock_lock.return_value.__enter__ = Mock(return_value=None)
        mock_lock.return_value.__exit__ = Mock(return_value=None)

        result = create_worktree('task-456')

        assert result == existing_path.resolve()
        mock_run_git.assert_not_called()

    def test_create_worktree_custom_base_branch(self) -> None:
        """Create worktree with custom base branch."""
        with patch('pokepoke.worktrees.worktrees.list_worktrees') as mock_list, \
             patch('pokepoke.worktrees.worktrees.with_worktree_lock') as mock_lock, \
             patch('pokepoke.worktrees.worktrees._run_git') as mock_run_git, \
             patch('pathlib.Path.mkdir'), \
             patch('pokepoke.worktrees.worktrees._validate_worktree_integrity'):

            mock_list.return_value = []
            mock_lock.return_value.__enter__ = Mock(return_value=None)
            mock_lock.return_value.__exit__ = Mock(return_value=None)
            mock_run_git.return_value = Mock(returncode=0, stdout='')

            create_worktree('task-789', base_branch='develop')

            call_args = mock_run_git.call_args[0][0]
            assert 'develop' in call_args


class TestIsWorktreeMerged:
    """Tests for is_worktree_merged function."""

    @patch('pokepoke.worktrees.worktrees.get_default_branch')
    @patch('pokepoke.worktrees.worktrees._run_git')
    def test_is_worktree_merged_true(self, mock_run_git, mock_default_branch) -> None:
        """Return True when branch is merged."""
        mock_default_branch.return_value = 'main'
        mock_run_git.return_value = Mock(
            stdout='  task/item-1\n  task/item-2\n* main\n',
            returncode=0
        )

        result = is_worktree_merged('item-1')

        assert result is True

    @patch('pokepoke.worktrees.worktrees.get_default_branch')
    @patch('pokepoke.worktrees.worktrees._run_git')
    def test_is_worktree_merged_false(self, mock_run_git, mock_default_branch) -> None:
        """Return False when branch is not merged."""
        mock_default_branch.return_value = 'main'
        mock_run_git.return_value = Mock(
            stdout='  task/other\n* main\n',
            returncode=0
        )

        result = is_worktree_merged('item-1')

        assert result is False

    @patch('pokepoke.worktrees.worktrees.get_default_branch')
    @patch('pokepoke.worktrees.worktrees._run_git')
    def test_is_worktree_merged_git_error(self, mock_run_git, mock_default_branch) -> None:
        """Return False on git error."""
        mock_default_branch.return_value = 'main'
        mock_run_git.side_effect = subprocess.CalledProcessError(1, 'git')

        result = is_worktree_merged('item-1')

        assert result is False

    @patch('pokepoke.worktrees.worktrees._run_git')
    def test_is_worktree_merged_custom_target_branch(self, mock_run_git) -> None:
        """Use custom target branch if provided."""
        mock_run_git.return_value = Mock(stdout='', returncode=0)

        is_worktree_merged('item-1', target_branch='develop')

        call_args = mock_run_git.call_args[0][0]
        assert 'develop' in call_args


class TestMergeWorktree:
    """Tests for merge_worktree function."""

    @patch('pokepoke.worktrees.worktrees.cleanup_after_merge')
    @patch('pokepoke.worktrees.worktrees.is_worktree_merged')
    @patch('pokepoke.worktrees.worktrees._run_git')
    @patch('pokepoke.worktrees.worktrees.validate_post_merge')
    @patch('pokepoke.worktrees.worktrees.get_default_branch')
    @patch('pokepoke.worktrees.worktrees.is_worktree_clean')
    @patch('pokepoke.worktrees.worktrees._sync_and_ensure_clean_main_repo')
    @patch('pokepoke.worktrees.worktrees.execute_merge_sequence')
    def test_merge_worktree_success(
        self,
        mock_execute,
        mock_sync,
        mock_is_clean,
        mock_default_branch,
        mock_validate,
        mock_run_git,
        mock_is_merged,
        mock_cleanup,
    ) -> None:
        """Successfully merge worktree."""
        mock_default_branch.return_value = 'main'
        mock_is_clean.return_value = True
        mock_sync.return_value = True
        mock_execute.return_value = (True, '', [])
        mock_validate.return_value = True
        mock_run_git.return_value = Mock(returncode=0, stdout='')
        mock_is_merged.return_value = True
        mock_cleanup.return_value = None

        success, conflicts = merge_worktree('item-1')

        assert success is True
        assert conflicts == []

    @patch('pokepoke.worktrees.worktrees.is_worktree_clean')
    def test_merge_worktree_dirty_worktree(self, mock_is_clean) -> None:
        """Fail when worktree has uncommitted changes."""
        mock_is_clean.return_value = False

        success, conflicts = merge_worktree('item-1')

        assert success is False
        assert conflicts == []

    @patch('pokepoke.worktrees.worktrees.get_default_branch')
    @patch('pokepoke.worktrees.worktrees.is_worktree_clean')
    @patch('pokepoke.worktrees.worktrees._sync_and_ensure_clean_main_repo')
    @patch('pokepoke.worktrees.worktrees.execute_merge_sequence')
    def test_merge_worktree_sync_fails(
        self,
        mock_execute,
        mock_sync,
        mock_is_clean,
        mock_default_branch,
    ) -> None:
        """Fail when sync_and_ensure fails."""
        mock_default_branch.return_value = 'main'
        mock_is_clean.return_value = True
        mock_sync.return_value = False

        success, conflicts = merge_worktree('item-1')

        assert success is False
        assert conflicts == []

    @patch('pokepoke.worktrees.worktrees.get_default_branch')
    @patch('pokepoke.worktrees.worktrees.is_worktree_clean')
    @patch('pokepoke.worktrees.worktrees._sync_and_ensure_clean_main_repo')
    @patch('pokepoke.worktrees.worktrees.execute_merge_sequence')
    def test_merge_worktree_conflict_files(
        self,
        mock_execute,
        mock_sync,
        mock_is_clean,
        mock_default_branch,
    ) -> None:
        """Return conflicted files when merge fails."""
        mock_default_branch.return_value = 'main'
        mock_is_clean.return_value = True
        mock_sync.return_value = True
        conflict_files = ['src/a.py', 'src/b.py']
        mock_execute.return_value = (False, 'Merge conflict', conflict_files)

        success, conflicts = merge_worktree('item-1')

        assert success is False
        assert conflicts == conflict_files

    @patch('pokepoke.worktrees.worktrees.cleanup_after_merge')
    @patch('pokepoke.worktrees.worktrees.is_worktree_merged')
    @patch('pokepoke.worktrees.worktrees._run_git')
    @patch('pokepoke.worktrees.worktrees.validate_post_merge')
    @patch('pokepoke.worktrees.worktrees.get_default_branch')
    @patch('pokepoke.worktrees.worktrees.is_worktree_clean')
    @patch('pokepoke.worktrees.worktrees._sync_and_ensure_clean_main_repo')
    @patch('pokepoke.worktrees.worktrees.execute_merge_sequence')
    def test_merge_worktree_cleanup(
        self,
        mock_execute,
        mock_sync,
        mock_is_clean,
        mock_default_branch,
        mock_validate,
        mock_run_git,
        mock_is_merged,
        mock_cleanup,
    ) -> None:
        """Call cleanup_after_merge when cleanup=True."""
        mock_default_branch.return_value = 'main'
        mock_is_clean.return_value = True
        mock_sync.return_value = True
        mock_execute.return_value = (True, '', [])
        mock_validate.return_value = True
        mock_run_git.return_value = Mock(returncode=0, stdout='')
        mock_is_merged.return_value = True
        mock_cleanup.return_value = None

        success, _ = merge_worktree('item-1', cleanup=True)

        assert success is True
        mock_cleanup.assert_called_once()


class TestListWorktrees:
    """Tests for list_worktrees function."""

    @patch('subprocess.run')
    def test_list_worktrees_empty(self, mock_run) -> None:
        """Return empty list when no worktrees exist."""
        mock_run.return_value = Mock(stdout='', returncode=0)

        result = list_worktrees()

        assert result == []

    @patch('subprocess.run')
    def test_list_worktrees_parsing(self, mock_run) -> None:
        """Parse git worktree list output correctly."""
        # git worktree list --porcelain format
        mock_run.return_value = Mock(
            stdout='worktree /repo/main\n'
                   'branch refs/heads/main\n'
                   'HEAD abcd1234\n'
                   '\n'
                   'worktree /repo/worktrees/task-1\n'
                   'branch refs/heads/task/task-1\n'
                   'HEAD efgh5678\n',
            returncode=0
        )

        result = list_worktrees()

        assert len(result) == 2
        assert result[0]['path'] == '/repo/main'
        assert result[1]['branch'] == 'refs/heads/task/task-1'

    @patch('subprocess.run')
    def test_list_worktrees_git_error(self, mock_run) -> None:
        """Return empty list on git error."""
        mock_run.side_effect = subprocess.CalledProcessError(1, 'git')

        result = list_worktrees()

        assert result == []


class TestCleanupWorktree:
    """Tests for cleanup_worktree function."""

    @patch('pokepoke.worktrees.worktree_cleanup.remove_from_manifest')
    @patch('pokepoke.worktrees.worktrees.list_worktrees')
    @patch('subprocess.run')
    def test_cleanup_worktree_success(
        self, mock_run, mock_list, mock_remove_manifest
    ) -> None:
        """Successfully cleanup a worktree."""
        mock_list.return_value = []
        mock_run.return_value = Mock(returncode=0, stdout='', stderr='')

        result = cleanup_worktree('item-1')

        assert result is True
        mock_remove_manifest.assert_not_called()
        mock_run.assert_called_once()
        assert mock_run.call_args[0][0] == ['git', 'branch', '-d', 'task/item-1']

    @patch('pokepoke.worktrees.worktree_cleanup._run_git')
    @patch('pokepoke.worktrees.worktrees._run_git')
    @patch('pokepoke.worktrees.worktrees.list_worktrees')
    def test_cleanup_worktree_not_found(self, mock_list, mock_run_git, mock_cleanup_run_git) -> None:
        """Handle cleanup when worktree doesn't exist."""
        mock_run_git.side_effect = subprocess.CalledProcessError(
            1, 'git', stderr='not a working tree'
        )
        mock_cleanup_run_git.side_effect = subprocess.CalledProcessError(
            1, 'git', stderr='error: branch not found'
        )
        mock_list.return_value = []

        # Should handle gracefully and return True (worktree already gone)
        result = cleanup_worktree('nonexistent')
        assert result is True
