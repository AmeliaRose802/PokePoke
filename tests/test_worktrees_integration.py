"""Integration tests for worktree lifecycle management.

These tests exercise the actual code paths in worktrees.py, worktree_merge_handler.py,
and related modules to improve coverage of critical data-integrity paths.
"""

import subprocess
from pathlib import Path
from unittest.mock import patch, Mock
import pytest

from pokepoke.worktrees import (
    create_worktree,
    is_worktree_merged,
    merge_worktree,
    cleanup_worktree,
    list_worktrees,
    _sync_and_ensure_clean_main_repo,
)


class TestCreateWorktreeIntegration:
    """Integration tests for create_worktree that exercise real code paths."""

    @patch('pokepoke.worktrees.list_worktrees')
    @patch('pokepoke.worktrees.get_default_branch')
    @patch('subprocess.run')
    @patch('pathlib.Path.mkdir')
    @patch('pokepoke.worktrees.sanitize_branch_name', side_effect=lambda x: x)
    @patch('pokepoke.worktrees._validate_worktree_integrity')
    def test_create_new_worktree_success(
        self, mock_validate, mock_sanitize, mock_mkdir, mock_run, mock_get_branch, mock_list
    ):
        """Test creating a new worktree executes real code path."""
        # Setup mocks
        mock_list.return_value = []
        mock_get_branch.return_value = 'dev'
        mock_run.return_value = Mock(returncode=0, stdout='', stderr='')

        # Execute
        result = create_worktree('test-123')

        # Verify
        assert result == Path('worktrees/task-test-123')
        # mkdir is called for: worktrees/, .pokepoke/locks/, and .pokepoke/stats/
        assert mock_mkdir.call_count >= 1
        # Verify at least one call had exist_ok=True
        assert any(call[1].get('exist_ok') for call in mock_mkdir.call_args_list)
        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        assert args[0:2] == ['git', 'worktree']

    @patch('pokepoke.worktrees.list_worktrees')
    def test_create_worktree_reuses_existing_by_path(self, mock_list):
        """Test that existing worktree is reused when path matches."""
        # Mock existing worktree
        mock_list.return_value = [{
            'path': str(Path('worktrees/task-test-123').resolve()),
            'branch': 'refs/heads/task/test-123'
        }]

        # Execute
        result = create_worktree('test-123')

        # Verify - should return existing path without creating new
        assert result == Path('worktrees/task-test-123').resolve()

    @patch('pokepoke.worktrees.list_worktrees')
    def test_create_worktree_reuses_existing_by_branch(self, mock_list):
        """Test that existing worktree is reused when branch name matches."""
        existing_path = Path('C:/repos/worktrees/task-test-456')
        mock_list.return_value = [{
            'path': str(existing_path),
            'branch': 'refs/heads/task/test-456'
        }]

        # Execute
        result = create_worktree('test-456')

        # Verify
        assert result == existing_path

    @patch('pokepoke.worktrees.list_worktrees')
    @patch('pokepoke.worktrees.get_default_branch')
    @patch('subprocess.run')
    @patch('pathlib.Path.mkdir')
    def test_create_worktree_handles_branch_exists_error(
        self, mock_mkdir, mock_run, mock_get_branch, mock_list
    ):
        """Test recovery when branch already exists."""
        # First call returns empty, second call returns existing worktree
        mock_list.side_effect = [
            [],  # Initial check
            [{  # After error, find existing
                'path': 'C:/repos/worktrees/task-test-789',
                'branch': 'refs/heads/task/test-789'
            }]
        ]
        mock_get_branch.return_value = 'dev'

        # Simulate branch already exists error
        error = subprocess.CalledProcessError(
            1, ['git'], stderr="fatal: a branch named 'task/test-789' already exists"
        )
        mock_run.side_effect = error

        # Execute
        result = create_worktree('test-789')

        # Verify recovery
        assert result == Path('C:/repos/worktrees/task-test-789')

    @patch('pokepoke.worktrees.list_worktrees')
    @patch('pokepoke.worktrees.get_default_branch')
    @patch('subprocess.run')
    @patch('pathlib.Path.mkdir')
    def test_create_worktree_invalid_base_branch_error(
        self, mock_mkdir, mock_run, mock_get_branch, mock_list
    ):
        """Test error when base branch doesn't exist."""
        mock_list.return_value = []
        mock_get_branch.return_value = 'nonexistent-branch'

        # Simulate invalid reference error
        error = subprocess.CalledProcessError(
            1, ['git'], stderr="fatal: invalid reference: nonexistent-branch"
        )
        mock_run.side_effect = error

        # Execute and verify
        with pytest.raises(RuntimeError, match="Base branch .* does not exist"):
            create_worktree('test-999')

    @patch('pokepoke.worktrees.list_worktrees')
    @patch('pokepoke.worktrees.get_default_branch')
    @patch('subprocess.run')
    @patch('pathlib.Path.mkdir')
    def test_create_worktree_timeout_error(
        self, mock_mkdir, mock_run, mock_get_branch, mock_list
    ):
        """Test timeout handling during worktree creation."""
        mock_list.return_value = []
        mock_get_branch.return_value = 'dev'

        # Simulate timeout
        mock_run.side_effect = subprocess.TimeoutExpired(['git'], 30)

        # Execute and verify
        with pytest.raises(RuntimeError, match="Timed out creating worktree"):
            create_worktree('test-timeout')


class TestIsWorktreeMergedIntegration:
    """Integration tests for is_worktree_merged."""

    @patch('pokepoke.worktrees.get_default_branch')
    @patch('subprocess.run')
    def test_is_merged_returns_true_when_branch_in_list(
        self, mock_run, mock_get_branch
    ):
        """Test that is_worktree_merged returns True when branch is merged."""
        mock_get_branch.return_value = 'dev'
        mock_run.return_value = Mock(
            returncode=0,
            stdout='  task/test-123\n  task/other-456\n'
        )

        result = is_worktree_merged('test-123')

        assert result is True
        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        assert args == ['git', 'branch', '--merged', 'dev']

    @patch('pokepoke.worktrees.get_default_branch')
    @patch('subprocess.run')
    def test_is_merged_returns_false_when_branch_not_in_list(
        self, mock_run, mock_get_branch
    ):
        """Test that is_worktree_merged returns False when branch not merged."""
        mock_get_branch.return_value = 'dev'
        mock_run.return_value = Mock(
            returncode=0,
            stdout='  task/other-456\n  task/another-789\n'
        )

        result = is_worktree_merged('test-123')

        assert result is False

    @patch('subprocess.run')
    def test_is_merged_handles_subprocess_error(self, mock_run):
        """Test error handling in is_worktree_merged."""
        mock_run.side_effect = subprocess.CalledProcessError(1, ['git'])

        result = is_worktree_merged('test-123', 'dev')

        assert result is False


class TestMergeWorktreeIntegration:
    """Integration tests for merge_worktree."""

    @patch('pokepoke.worktrees._sync_and_ensure_clean_main_repo')
    @patch('pokepoke.worktrees.is_worktree_merged')
    @patch('pokepoke.worktrees.execute_merge_sequence')
    @patch('pokepoke.worktrees.validate_post_merge')
    @patch('pokepoke.worktrees.is_worktree_clean')
    @patch('pokepoke.worktrees.get_default_branch')
    @patch('pokepoke.worktrees.cleanup_after_merge')
    @patch('subprocess.run')
    def test_merge_worktree_full_success_path(
        self,
        mock_run,
        mock_cleanup,
        mock_get_branch,
        mock_is_clean,
        mock_validate,
        mock_execute,
        mock_is_merged,
        mock_sync
    ):
        """Test full successful merge sequence."""
        # Setup
        mock_get_branch.return_value = 'dev'
        mock_is_clean.return_value = True
        mock_sync.return_value = True
        mock_execute.return_value = (True, '', [])
        mock_validate.return_value = True
        mock_run.return_value = Mock(returncode=0)
        mock_is_merged.return_value = True

        # Execute
        success, conflicts = merge_worktree('test-123')

        # Verify
        assert success is True
        assert conflicts == []
        mock_is_clean.assert_called_once()
        mock_sync.assert_called_once()
        mock_execute.assert_called_once_with('task/test-123', 'dev')
        mock_validate.assert_called_once()
        mock_cleanup.assert_called_once()

    @patch('pokepoke.worktrees.is_worktree_clean')
    @patch('pokepoke.worktrees.get_default_branch')
    def test_merge_worktree_fails_on_dirty_worktree(
        self, mock_get_branch, mock_is_clean
    ):
        """Test that merge fails if worktree has uncommitted changes."""
        mock_get_branch.return_value = 'dev'
        mock_is_clean.return_value = False

        success, conflicts = merge_worktree('test-123')

        assert success is False
        assert conflicts == []

    @patch('pokepoke.worktrees._sync_and_ensure_clean_main_repo')
    @patch('pokepoke.worktrees.is_worktree_clean')
    @patch('pokepoke.worktrees.get_default_branch')
    def test_merge_worktree_fails_on_unclean_main_repo(
        self, mock_get_branch, mock_is_clean, mock_sync
    ):
        """Test that merge fails if main repo sync fails."""
        mock_get_branch.return_value = 'dev'
        mock_is_clean.return_value = True
        mock_sync.return_value = False

        success, conflicts = merge_worktree('test-123')

        assert success is False
        assert conflicts == []

    @patch('pokepoke.worktrees._sync_and_ensure_clean_main_repo')
    @patch('pokepoke.worktrees.execute_merge_sequence')
    @patch('pokepoke.worktrees.is_worktree_clean')
    @patch('pokepoke.worktrees.get_default_branch')
    def test_merge_worktree_returns_conflicts_on_merge_failure(
        self, mock_get_branch, mock_is_clean, mock_execute, mock_sync
    ):
        """Test that conflicts are returned when merge has conflicts."""
        mock_get_branch.return_value = 'dev'
        mock_is_clean.return_value = True
        mock_sync.return_value = True
        mock_execute.return_value = (False, 'Conflict error', ['file1.py', 'file2.py'])

        success, conflicts = merge_worktree('test-123')

        assert success is False
        assert conflicts == ['file1.py', 'file2.py']

    @patch('pokepoke.worktrees._sync_and_ensure_clean_main_repo')
    @patch('pokepoke.worktrees.is_worktree_merged')
    @patch('pokepoke.worktrees.execute_merge_sequence')
    @patch('pokepoke.worktrees.validate_post_merge')
    @patch('pokepoke.worktrees.is_worktree_clean')
    @patch('pokepoke.worktrees.get_default_branch')
    @patch('subprocess.run')
    def test_merge_worktree_fails_on_push_error(
        self,
        mock_run,
        mock_get_branch,
        mock_is_clean,
        mock_validate,
        mock_execute,
        mock_is_merged,
        mock_sync
    ):
        """Test that merge fails if push to remote fails."""
        mock_get_branch.return_value = 'dev'
        mock_is_clean.return_value = True
        mock_sync.return_value = True
        mock_execute.return_value = (True, '', [])
        mock_validate.return_value = True
        mock_run.side_effect = subprocess.CalledProcessError(
            1, ['git'], stderr='Push failed'
        )

        success, conflicts = merge_worktree('test-123')

        assert success is False
        assert conflicts == []

    @patch('pokepoke.worktrees._sync_and_ensure_clean_main_repo')
    @patch('pokepoke.worktrees.is_worktree_merged')
    @patch('pokepoke.worktrees.execute_merge_sequence')
    @patch('pokepoke.worktrees.validate_post_merge')
    @patch('pokepoke.worktrees.is_worktree_clean')
    @patch('pokepoke.worktrees.get_default_branch')
    @patch('subprocess.run')
    def test_merge_worktree_succeeds_with_warning_if_not_merged_after_push(
        self,
        mock_run,
        mock_get_branch,
        mock_is_clean,
        mock_validate,
        mock_execute,
        mock_is_merged,
        mock_sync
    ):
        """Test that merge succeeds with warning if branch doesn't show as merged after push."""
        mock_get_branch.return_value = 'dev'
        mock_is_clean.return_value = True
        mock_sync.return_value = True
        mock_execute.return_value = (True, '', [])
        mock_validate.return_value = True
        mock_run.return_value = Mock(returncode=0)
        mock_is_merged.return_value = False  # Verification fails, but push succeeded

        success, conflicts = merge_worktree('test-123')

        # After fix: should succeed with warning, not fail
        assert success is True, "Merge should succeed even when verification fails after successful push"
        assert conflicts == []

    @patch('pokepoke.worktrees._sync_and_ensure_clean_main_repo')
    @patch('pokepoke.worktrees.is_worktree_merged')
    @patch('pokepoke.worktrees.execute_merge_sequence')
    @patch('pokepoke.worktrees.validate_post_merge')
    @patch('pokepoke.worktrees.is_worktree_clean')
    @patch('pokepoke.worktrees.get_default_branch')
    @patch('pokepoke.worktrees.cleanup_after_merge')
    @patch('subprocess.run')
    def test_merge_worktree_with_cleanup_disabled(
        self,
        mock_run,
        mock_cleanup,
        mock_get_branch,
        mock_is_clean,
        mock_validate,
        mock_execute,
        mock_is_merged,
        mock_sync
    ):
        """Test merge without cleanup when cleanup=False."""
        mock_get_branch.return_value = 'dev'
        mock_is_clean.return_value = True
        mock_sync.return_value = True
        mock_execute.return_value = (True, '', [])
        mock_validate.return_value = True
        mock_run.return_value = Mock(returncode=0)
        mock_is_merged.return_value = True

        success, conflicts = merge_worktree('test-123', cleanup=False)

        assert success is True
        mock_cleanup.assert_not_called()


class TestCleanupWorktreeIntegration:
    """Integration tests for cleanup_worktree."""

    @patch('pokepoke.worktrees.list_worktrees')
    @patch('pokepoke.worktree_cleanup.remove_from_manifest')
    @patch('subprocess.run')
    def test_cleanup_success_by_branch_name(
        self, mock_run, mock_remove, mock_list
    ):
        """Test successful cleanup when worktree found by branch."""
        worktree_path = Path('C:/repos/worktrees/task-test-123')
        mock_list.return_value = [{
            'path': str(worktree_path),
            'branch': 'refs/heads/task/test-123'
        }]
        mock_run.return_value = Mock(returncode=0)

        with patch.object(Path, 'exists', side_effect=[True, False]):
            result = cleanup_worktree('test-123')

        assert result is True
        # Should call git worktree remove
        assert mock_run.call_count >= 1
        mock_remove.assert_called_once_with('test-123')

    @patch('pokepoke.worktrees.list_worktrees')
    @patch('subprocess.run')
    def test_cleanup_with_force_flag(self, mock_run, mock_list):
        """Test cleanup with force flag."""
        worktree_path = Path('C:/repos/worktrees/task-test-456')
        mock_list.return_value = [{
            'path': str(worktree_path),
            'branch': 'refs/heads/task/test-456'
        }]
        mock_run.return_value = Mock(returncode=0)

        with patch.object(Path, 'exists', side_effect=[True, False]), \
             patch('pokepoke.worktree_cleanup.remove_from_manifest'):
            result = cleanup_worktree('test-456', force=True)

        assert result is True
        # Verify force flag was passed to git worktree remove
        worktree_remove_args = mock_run.call_args_list[0][0][0]
        assert worktree_remove_args[0:3] == ['git', 'worktree', 'remove']
        assert '--force' in worktree_remove_args

    @patch('pokepoke.worktrees.list_worktrees')
    @patch('pokepoke.worktree_cleanup.add_uncleaned_worktree')
    @patch('pokepoke.worktree_cleanup.force_remove_directory')
    @patch('subprocess.run')
    @patch('time.sleep')  # Mock sleep to avoid timeout
    def test_cleanup_handles_windows_lock_error(
        self, mock_sleep, mock_run, mock_force_remove, mock_add_uncleaned, mock_list
    ):
        """Test cleanup retry on Windows lock error."""
        worktree_path = Path('C:/repos/worktrees/task-test-789')
        mock_list.return_value = [{
            'path': str(worktree_path),
            'branch': 'refs/heads/task/test-789'
        }]

        # Simulate Windows lock error
        error = subprocess.CalledProcessError(
            1, ['git'], stderr='Permission denied'
        )
        mock_run.side_effect = error
        mock_force_remove.return_value = True  # Force remove succeeds

        with patch.object(Path, 'exists', side_effect=[True, False]), \
             patch('pokepoke.worktree_cleanup.remove_from_manifest'):
            cleanup_worktree('test-789')

        # Should call force remove as fallback
        mock_force_remove.assert_called_once()

    @patch('pokepoke.worktrees.list_worktrees')
    @patch('subprocess.run')
    def test_cleanup_returns_false_if_worktree_dir_still_exists(
        self, mock_run, mock_list
    ):
        """Test that branch deletion is skipped if worktree directory exists."""
        worktree_path = Path('C:/repos/worktrees/task-test-999')
        mock_list.return_value = [{
            'path': str(worktree_path),
            'branch': 'refs/heads/task/test-999'
        }]
        mock_run.return_value = Mock(returncode=0)

        # Worktree directory still exists after removal attempt
        with patch.object(Path, 'exists', return_value=True):
            result = cleanup_worktree('test-999')

        assert result is False


class TestListWorktreesIntegration:
    """Integration tests for list_worktrees."""

    @patch('subprocess.run')
    def test_list_worktrees_parses_porcelain_output(self, mock_run):
        """Test parsing of git worktree list --porcelain output."""
        mock_run.return_value = Mock(
            returncode=0,
            stdout="""worktree C:/repos/main
HEAD abc123def456
branch refs/heads/main

worktree C:/repos/worktrees/task-123
HEAD def789ghi012
branch refs/heads/task/test-123

worktree C:/repos/worktrees/task-456
HEAD ghi345jkl678
branch refs/heads/task/test-456
"""
        )

        result = list_worktrees()

        assert len(result) == 3
        assert result[0]['path'] == 'C:/repos/main'
        assert result[0]['branch'] == 'refs/heads/main'
        assert result[0]['commit'] == 'abc123def456'
        assert result[1]['path'] == 'C:/repos/worktrees/task-123'
        assert result[2]['branch'] == 'refs/heads/task/test-456'

    @patch('subprocess.run')
    def test_list_worktrees_returns_empty_on_error(self, mock_run):
        """Test that empty list is returned on subprocess error."""
        mock_run.side_effect = subprocess.CalledProcessError(1, ['git'])

        result = list_worktrees()

        assert result == []

    @patch('subprocess.run')
    def test_list_worktrees_handles_timeout(self, mock_run):
        """Test handling of timeout."""
        mock_run.side_effect = subprocess.TimeoutExpired(['git'], 30)

        result = list_worktrees()

        assert result == []


class TestSyncAndEnsureCleanMainRepoIntegration:
    """Integration tests for _sync_and_ensure_clean_main_repo."""

    @patch('pokepoke.worktree_helpers.run_bd_sync_with_retry')
    @patch('subprocess.run')
    def test_sync_succeeds_when_main_repo_clean(
        self, mock_run, mock_bd_sync
    ):
        """Test successful sync when main repo is clean."""
        mock_bd_sync.return_value = Mock(returncode=0, stdout='', stderr='')
        mock_run.return_value = Mock(returncode=0, stdout='')

        result = _sync_and_ensure_clean_main_repo('task/test-123')

        assert result is True
        mock_bd_sync.assert_called_once()

    @patch('pokepoke.worktree_helpers.run_bd_sync_with_retry')
    @patch('pokepoke.worktree_helpers.categorize_git_changes')
    @patch('subprocess.run')
    def test_sync_commits_beads_changes(
        self, mock_run, mock_categorize, mock_bd_sync
    ):
        """Test that beads changes are automatically committed."""
        mock_bd_sync.return_value = Mock(returncode=0, stdout='', stderr='')

        # First call: status shows beads changes
        # Subsequent calls: git add, git commit
        mock_run.side_effect = [
            Mock(returncode=0, stdout=' M .beads/database.db\n'),  # status
            Mock(returncode=0),  # git add
            Mock(returncode=0),  # git commit
        ]

        mock_categorize.return_value = {
            'beads': [' M .beads/database.db'],
            'worktree': [],
            'other': []
        }

        result = _sync_and_ensure_clean_main_repo('task/test-123')

        assert result is True
        # Verify git add and commit were called
        assert mock_run.call_count == 3

    @patch('pokepoke.worktree_helpers.run_bd_sync_with_retry')
    @patch('pokepoke.worktree_helpers.categorize_git_changes')
    @patch('pokepoke.worktree_helpers.commit_all_changes')
    @patch('subprocess.run')
    def test_sync_fails_on_non_beads_changes(
        self, mock_run, mock_commit, mock_categorize, mock_bd_sync
    ):
        """Test that sync fails if main repo has non-beads uncommitted changes that cannot be committed."""
        mock_bd_sync.return_value = Mock(returncode=0, stdout='', stderr='')
        mock_run.return_value = Mock(
            returncode=0,
            stdout=' M src/somefile.py\n'
        )
        mock_commit.return_value = (False, 'pre-commit hooks rejected changes')

        mock_categorize.return_value = {
            'beads': [],
            'worktree': [],
            'other': [' M src/somefile.py']
        }

        result = _sync_and_ensure_clean_main_repo('task/test-123')

        assert result is False
        mock_commit.assert_called_once()

    @patch('pokepoke.worktree_helpers.run_bd_sync_with_retry')
    @patch('subprocess.run')
    def test_sync_handles_bd_sync_timeout(
        self, mock_run, mock_bd_sync
    ):
        """Test handling of bd sync timeout."""
        mock_bd_sync.side_effect = subprocess.TimeoutExpired(['bd'], 30)
        mock_run.return_value = Mock(returncode=0, stdout='')

        # Should continue despite timeout
        result = _sync_and_ensure_clean_main_repo('task/test-123')

        # Should still return True if repo is clean
        assert result is True

    @patch('pokepoke.worktree_helpers.run_bd_sync_with_retry')
    @patch('subprocess.run')
    def test_sync_handles_git_status_error(
        self, mock_run, mock_bd_sync
    ):
        """Test handling of git status error."""
        mock_bd_sync.return_value = Mock(returncode=0, stdout='', stderr='')
        mock_run.side_effect = subprocess.CalledProcessError(
            1, ['git'], stderr='Git error'
        )

        result = _sync_and_ensure_clean_main_repo('task/test-123')

        assert result is False
