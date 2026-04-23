"""Comprehensive unit tests for core worktree functions.

Tests for create_worktree, merge_worktree, list_worktrees, and error handling.
"""

import subprocess
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from pokepoke.worktrees.worktrees import (
    MergeResult,
    _check_existing_directory,
    _run_git,
    cleanup_worktree,
    create_worktree,
    is_worktree_merged,
    list_worktrees,
    merge_worktree,
)


class TestRunGit:
    """Tests for _run_git helper."""

    def test_run_git_success(self, monkeypatch) -> None:
        """_run_git returns subprocess result on success."""
        mock_result = Mock(
            stdout='branch info',
            stderr='',
            returncode=0,
            args=['git', 'branch']
        )
        monkeypatch.setattr('subprocess.run', lambda *a, **kw: mock_result)
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

        with pytest.raises(RuntimeError, match=r"file lock|Timed out"):
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

    @patch('pokepoke.worktrees.worktrees.get_default_branch')
    @patch('pokepoke.worktrees.worktrees.list_worktrees')
    @patch('pokepoke.worktrees.worktrees.with_worktree_lock')
    @patch('pokepoke.worktrees.worktrees._run_git')
    @patch('pathlib.Path.mkdir')
    @patch('pokepoke.worktrees.worktrees._validate_worktree_integrity')
    @patch('pokepoke.git.repo_state_guard.cleanup_lock_active')
    def test_create_worktree_waits_for_cleanup_agent(
        self,
        mock_cleanup_active,
        mock_validate,
        mock_mkdir,
        mock_run_git,
        mock_lock,
        mock_list,
        mock_default_branch,
    ) -> None:
        """Block worktree creation while cleanup agent is active."""
        mock_default_branch.return_value = 'main'
        mock_list.return_value = []
        mock_lock.return_value.__enter__ = Mock(return_value=None)
        mock_lock.return_value.__exit__ = Mock(return_value=None)
        mock_run_git.return_value = Mock(returncode=0, stdout='')
        
        # Simulate cleanup agent releasing lock after 2 checks
        call_count = 0
        def cleanup_active_side_effect():
            nonlocal call_count
            call_count += 1
            return call_count <= 2
        
        mock_cleanup_active.side_effect = cleanup_active_side_effect

        result = create_worktree('task-blocked')

        # Should have waited for cleanup (called cleanup_lock_active multiple times)
        assert mock_cleanup_active.call_count >= 2
        # Should eventually create the worktree
        assert result == (Path('worktrees') / 'task-task-blocked').resolve()
        mock_run_git.assert_called_once()

    @patch('pokepoke.worktrees.worktrees.get_default_branch')
    @patch('pokepoke.worktrees.worktrees.list_worktrees')
    @patch('pokepoke.worktrees.worktrees.with_worktree_lock')
    @patch('pokepoke.worktrees.worktrees._run_git')
    @patch('pathlib.Path.mkdir')
    @patch('pokepoke.worktrees.worktrees._validate_worktree_integrity')
    @patch('pokepoke.git.repo_state_guard.cleanup_lock_active')
    @patch('time.sleep')  # Speed up the test
    @patch('time.time')
    def test_create_worktree_proceeds_after_cleanup_timeout(
        self,
        mock_time,
        mock_sleep,
        mock_cleanup_active,
        mock_validate,
        mock_mkdir,
        mock_run_git,
        mock_lock,
        mock_list,
        mock_default_branch,
    ) -> None:
        """Proceed with worktree creation after cleanup timeout."""
        mock_default_branch.return_value = 'main'
        mock_list.return_value = []
        mock_lock.return_value.__enter__ = Mock(return_value=None)
        mock_lock.return_value.__exit__ = Mock(return_value=None)
        mock_run_git.return_value = Mock(returncode=0, stdout='')
        
        # Simulate cleanup agent still active (never releases)
        mock_cleanup_active.return_value = True
        
        # Mock time to simulate timeout - return increasing values
        call_count = [0]
        def time_side_effect():
            call_count[0] += 1
            if call_count[0] <= 3:
                return 0.0  # Initial calls
            else:
                return 601.0  # After initial, simulate timeout exceeded
        
        mock_time.side_effect = time_side_effect
        
        result = create_worktree('task-timeout')

        # Should have created the worktree despite active cleanup
        assert result == (Path('worktrees') / 'task-task-timeout').resolve()
        mock_run_git.assert_called_once()


class TestIsWorktreeMerged:
    """Tests for is_worktree_merged function."""

    @patch('pokepoke.worktrees.merge_helpers.get_default_branch')
    @patch('pokepoke.worktrees.merge_helpers._run_git')
    def test_is_worktree_merged_true(self, mock_run_git, mock_default_branch) -> None:
        """Return True when branch is merged."""
        mock_default_branch.return_value = 'main'
        mock_run_git.return_value = Mock(
            stdout='  task/item-1\n  task/item-2\n* main\n',
            returncode=0
        )

        result = is_worktree_merged('item-1')

        assert result is True

    @patch('pokepoke.worktrees.merge_helpers.get_default_branch')
    @patch('pokepoke.worktrees.merge_helpers._run_git')
    def test_is_worktree_merged_false(self, mock_run_git, mock_default_branch) -> None:
        """Return False when branch is not merged."""
        mock_default_branch.return_value = 'main'
        mock_run_git.return_value = Mock(
            stdout='  task/other\n* main\n',
            returncode=0
        )

        result = is_worktree_merged('item-1')

        assert result is False

    @patch('pokepoke.worktrees.merge_helpers.get_default_branch')
    @patch('pokepoke.worktrees.merge_helpers._run_git')
    def test_is_worktree_merged_git_error(self, mock_run_git, mock_default_branch) -> None:
        """Return False on git error."""
        mock_default_branch.return_value = 'main'
        mock_run_git.side_effect = subprocess.CalledProcessError(1, 'git')

        result = is_worktree_merged('item-1')

        assert result is False

    @patch('pokepoke.worktrees.merge_helpers._run_git')
    def test_is_worktree_merged_custom_target_branch(self, mock_run_git) -> None:
        """Use custom target branch if provided."""
        mock_run_git.return_value = Mock(stdout='', returncode=0)

        is_worktree_merged('item-1', target_branch='develop')

        call_args = mock_run_git.call_args[0][0]
        assert 'develop' in call_args


class TestMergeWorktree:
    """Tests for merge_worktree function."""

    @patch('pokepoke.worktrees.worktrees.cleanup_after_merge')
    @patch('pokepoke.worktrees.merge_helpers.validate_post_merge')
    @patch('pokepoke.worktrees.worktrees.get_default_branch')
    @patch('pokepoke.worktrees.worktrees.is_worktree_clean')
    @patch('pokepoke.worktrees.worktrees._sync_and_ensure_clean_main_repo')
    @patch('pokepoke.worktrees.worktrees.integrate_target_into_worktree')
    @patch('pokepoke.worktrees.worktrees.execute_merge_sequence')
    def test_merge_worktree_success(
        self,
        mock_execute,
        mock_integrate,
        mock_sync,
        mock_is_clean,
        mock_default_branch,
        mock_validate,
        mock_cleanup,
    ) -> None:
        """Successfully merge worktree."""
        mock_default_branch.return_value = 'main'
        mock_is_clean.return_value = True
        mock_sync.return_value = True
        mock_integrate.return_value = MergeResult(success=True)
        mock_execute.return_value = (True, '', [])
        mock_validate.return_value = True
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
    @patch('pokepoke.worktrees.worktrees.integrate_target_into_worktree')
    def test_merge_worktree_conflict_files(
        self,
        mock_integrate,
        mock_sync,
        mock_is_clean,
        mock_default_branch,
    ) -> None:
        """Return conflicted files when pre-merge integration fails."""
        mock_default_branch.return_value = 'main'
        mock_is_clean.return_value = True
        mock_sync.return_value = True
        conflict_files = ['src/a.py', 'src/b.py']
        mock_integrate.return_value = MergeResult(success=False, unmerged_files=conflict_files)

        success, conflicts = merge_worktree('item-1')

        assert success is False
        assert conflicts == conflict_files

    @patch('pokepoke.worktrees.worktrees.cleanup_after_merge')
    @patch('pokepoke.worktrees.merge_helpers.validate_post_merge')
    @patch('pokepoke.worktrees.worktrees.get_default_branch')
    @patch('pokepoke.worktrees.worktrees.is_worktree_clean')
    @patch('pokepoke.worktrees.worktrees._sync_and_ensure_clean_main_repo')
    @patch('pokepoke.worktrees.worktrees.integrate_target_into_worktree')
    @patch('pokepoke.worktrees.worktrees.execute_merge_sequence')
    def test_merge_worktree_cleanup(
        self,
        mock_execute,
        mock_integrate,
        mock_sync,
        mock_is_clean,
        mock_default_branch,
        mock_validate,
        mock_cleanup,
    ) -> None:
        """Call cleanup_after_merge when cleanup=True."""
        mock_default_branch.return_value = 'main'
        mock_is_clean.return_value = True
        mock_sync.return_value = True
        mock_integrate.return_value = MergeResult(success=True)
        mock_execute.return_value = (True, '', [])
        mock_validate.return_value = True
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


class TestCheckExistingDirectory:
    """Tests for _check_existing_directory function."""

    @patch('pokepoke.worktrees.worktrees._run_git')
    @patch('pokepoke.worktrees.worktrees.force_remove_directory')
    def test_wrong_branch_worktree_halts_with_error(
        self, mock_force_remove, mock_run_git, tmp_path: Path
    ) -> None:
        """Wrong-branch worktree raises RuntimeError instead of repairing.

        A worktree on the wrong branch is evidence of a prior bug (incomplete cleanup,
        race condition, or git corruption). The system must halt to prevent associating
        wrong commits with the wrong work item.
        """
        from pokepoke.worktrees.worktrees import _check_existing_directory

        # Create a fake worktree directory
        worktree_path = tmp_path / "worktrees" / "task-test-item"
        worktree_path.mkdir(parents=True)

        # Create .git file (not directory) to make it look like a valid worktree
        git_file = worktree_path / ".git"
        git_file.write_text("gitdir: /repo/.git/worktrees/task-test-item")

        # Mock git commands to simulate wrong branch
        def git_side_effect(cmd, **kwargs):
            if 'rev-parse' in cmd and '--is-inside-work-tree' in cmd:
                return Mock(stdout='true', returncode=0)
            if 'branch' in cmd and '--show-current' in cmd:
                return Mock(stdout='wrong-branch', returncode=0)  # Wrong branch!
            return Mock(stdout='', returncode=0)

        mock_run_git.side_effect = git_side_effect

        # Expect RuntimeError instead of silent repair
        with pytest.raises(RuntimeError, match=r"Wrong-branch worktree detected"):
            _check_existing_directory(worktree_path, repo_path=str(tmp_path))

        # Verify repair was NOT attempted (force_remove_directory should not be called for repair)
        # The function should raise immediately upon detecting wrong branch

    @patch('pokepoke.worktrees.worktrees._run_git')
    @patch('pokepoke.worktrees.worktrees.force_remove_directory')
    def test_wrong_branch_error_includes_context(
        self, mock_force_remove, mock_run_git, tmp_path: Path
    ) -> None:
        """Wrong-branch error includes branch names for debugging."""
        from pokepoke.worktrees.worktrees import _check_existing_directory

        worktree_path = tmp_path / "worktrees" / "task-my-item"
        worktree_path.mkdir(parents=True)
        (worktree_path / ".git").write_text("gitdir: /repo/.git/worktrees/task-my-item")

        def git_side_effect(cmd, **kwargs):
            if 'rev-parse' in cmd and '--is-inside-work-tree' in cmd:
                return Mock(stdout='true', returncode=0)
            if 'branch' in cmd and '--show-current' in cmd:
                return Mock(stdout='feature/other-work', returncode=0)
            return Mock(stdout='', returncode=0)

        mock_run_git.side_effect = git_side_effect

        with pytest.raises(RuntimeError) as exc_info:
            _check_existing_directory(worktree_path, repo_path=str(tmp_path))

        error_msg = str(exc_info.value)
        assert 'feature/other-work' in error_msg  # current branch
        assert 'task/my-item' in error_msg  # expected branch
        assert 'manual investigation' in error_msg.lower()

    @patch('pokepoke.worktrees.worktrees._run_git')
    def test_correct_branch_worktree_reused(self, mock_run_git, tmp_path: Path) -> None:
        """Worktree on correct branch is reused without error."""
        from pokepoke.worktrees.worktrees import _check_existing_directory

        worktree_path = tmp_path / "worktrees" / "task-good-item"
        worktree_path.mkdir(parents=True)
        (worktree_path / ".git").write_text("gitdir: /repo/.git/worktrees/task-good-item")

        def git_side_effect(cmd, **kwargs):
            if 'rev-parse' in cmd and '--is-inside-work-tree' in cmd:
                return Mock(stdout='true', returncode=0)
            if 'branch' in cmd and '--show-current' in cmd:
                return Mock(stdout='task/good-item', returncode=0)  # Correct branch
            return Mock(stdout='', returncode=0)

        mock_run_git.side_effect = git_side_effect

        result = _check_existing_directory(worktree_path, repo_path=str(tmp_path))

        assert result == worktree_path
