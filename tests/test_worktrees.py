"""Tests for git worktree management."""
import subprocess
from pathlib import Path
from unittest.mock import Mock, patch, call

import pytest

# Import the module to ensure coverage tracking works
import pokepoke.worktrees
import pokepoke.git_operations

from pokepoke.git_operations import (
    get_main_repo_root,
    is_worktree_clean,
    verify_branch_pushed,
    sanitize_branch_name,
    get_default_branch
)

from pokepoke.worktrees import (
    create_worktree,
    is_worktree_merged,
    merge_worktree,
    cleanup_worktree,
    list_worktrees,
)
from pokepoke.worktree_cleanup import (
    force_remove_directory,
    _handle_remove_readonly,
)


class TestSanitizeBranchName:
    """Tests for sanitize_branch_name function."""
    
    def test_sanitize_hash_symbol(self):
        """Test that # is replaced with hyphen."""
        assert sanitize_branch_name("icm_queue_c#-j1ly") == "icm_queue_c-j1ly"
    
    def test_sanitize_multiple_invalid_chars(self):
        """Test that multiple invalid characters are sanitized."""
        assert sanitize_branch_name("feat:add*feature?now") == "feat-add-feature-now"
    
    def test_sanitize_spaces(self):
        """Test that spaces are replaced with hyphens."""
        assert sanitize_branch_name("my feature branch") == "my-feature-branch"
    
    def test_sanitize_consecutive_dots(self):
        """Test that consecutive dots are collapsed."""
        assert sanitize_branch_name("branch..name...here") == "branch.name.here"
    
    def test_sanitize_leading_trailing_chars(self):
        """Test that leading/trailing hyphens and dots are removed."""
        assert sanitize_branch_name("-branch-name-") == "branch-name"
        assert sanitize_branch_name(".branch.name.") == "branch.name"
    
    def test_sanitize_already_valid(self):
        """Test that valid branch names are unchanged."""
        assert sanitize_branch_name("valid-branch-name") == "valid-branch-name"
        assert sanitize_branch_name("task/PokePoke-123") == "task/PokePoke-123"
    
    def test_sanitize_multiple_invalid_sequences(self):
        """Test handling of multiple invalid character sequences."""
        assert sanitize_branch_name("a~b^c:d?e*f[g]h") == "a-b-c-d-e-f-g-h"


class TestDefaultBranchResolution:
    """Tests for default branch resolution helpers."""

    def test_get_default_branch_prefers_config_branch(self):
        """Test get_default_branch returns config-preferred branch when it exists."""
        with patch('pokepoke.git_operations.branch_exists', return_value=True), \
             patch('pokepoke.config._cached_config', None), \
             patch('pokepoke.config._find_repo_root') as mock_root:
            mock_root.return_value = Path('/fake/root')
            # Config auto-detects username from git, so pass preferred explicitly
            assert get_default_branch(preferred='ameliapayne/dev') == 'ameliapayne/dev'

    def test_get_default_branch_uses_origin_head(self):
        """Test get_default_branch falls back to origin/HEAD when preferred missing."""
        with patch('pokepoke.git_operations.branch_exists', return_value=False), \
             patch('subprocess.run') as mock_run:
            mock_run.return_value = Mock(returncode=0, stdout='origin/master\n', stderr='')

            assert get_default_branch(preferred='') == 'master'

    def test_get_default_branch_uses_current_branch(self):
        """Test get_default_branch falls back to current branch when origin/HEAD fails."""
        with patch('pokepoke.git_operations.branch_exists', return_value=False), \
             patch('subprocess.run') as mock_run:
            mock_run.side_effect = [
                subprocess.CalledProcessError(1, ['git']),
                Mock(returncode=0, stdout='task/PokePoke-6g1\n', stderr='')
            ]

            assert get_default_branch(preferred='') == 'task/PokePoke-6g1'


class TestGetMainRepoRoot:
    """Tests for get_main_repo_root function."""
    
    def test_get_main_repo_root_in_main_repo(self):
        """Test getting main repo root when in main repository."""
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = Mock(
                stdout='/home/user/repo/.git\n',
                returncode=0
            )
            
            result = get_main_repo_root()
            
            assert result == Path('/home/user/repo')
            mock_run.assert_called_once_with(
                ['git', 'rev-parse', '--git-common-dir'],
                capture_output=True,
                text=True,
                encoding='utf-8',
                check=True
            )
    
    def test_get_main_repo_root_in_worktree(self):
        """Test getting main repo root when in a worktree."""
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = Mock(
                stdout='/home/user/repo/.git/worktrees/task-123\n',
                returncode=0
            )
            
            result = get_main_repo_root()
            
            # The parent of the worktrees directory is what we get
            assert result == Path('/home/user/repo/.git/worktrees')
    
    def test_get_main_repo_root_not_in_git_repo(self):
        """Test error when not in a git repository."""
        with patch('subprocess.run') as mock_run:
            mock_run.side_effect = subprocess.CalledProcessError(
                128, ['git'], stderr='Not a git repository'
            )
            
            with pytest.raises(RuntimeError, match="Not in a git repository"):
                get_main_repo_root()


class TestIsWorktreeClean:
    """Tests for is_worktree_clean function."""
    
    def test_is_worktree_clean_true(self):
        """Test worktree with no uncommitted changes."""
        worktree_path = Path('/home/user/repo/worktrees/task-123')
        
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = Mock(
                stdout='',
                returncode=0
            )
            
            result = is_worktree_clean(worktree_path)
            
            assert result is True
            mock_run.assert_called_once_with(
                ['git', '-C', str(worktree_path), 'status', '--porcelain'],
                capture_output=True,
                text=True,
                encoding='utf-8',
                check=True
            )
    
    def test_is_worktree_clean_false(self):
        """Test worktree with uncommitted changes."""
        worktree_path = Path('/home/user/repo/worktrees/task-123')
        
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = Mock(
                stdout=' M file.txt\n',
                returncode=0
            )
            
            result = is_worktree_clean(worktree_path)
            
            assert result is False
    
    def test_is_worktree_clean_subprocess_error(self):
        """Test error handling when git command fails."""
        worktree_path = Path('/home/user/repo/worktrees/task-123')
        
        with patch('subprocess.run') as mock_run:
            mock_run.side_effect = subprocess.CalledProcessError(
                1, ['git'], stderr='Not a git repository'
            )
            
            result = is_worktree_clean(worktree_path)
            
            assert result is False


class TestVerifyBranchPushed:
    """Tests for verify_branch_pushed function."""
    
    def test_verify_branch_pushed_exists(self):
        """Test verification when branch exists on remote."""
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = Mock(
                stdout='abc123\trefs/heads/main\n',
                returncode=0
            )
            
            result = verify_branch_pushed('main')
            
            assert result is True
            mock_run.assert_called_once_with(
                ['git', 'ls-remote', '--heads', 'origin', 'main'],
                capture_output=True,
                text=True,
                encoding='utf-8',
                check=True
            )
    
    def test_verify_branch_pushed_not_exists(self):
        """Test verification when branch does not exist on remote."""
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = Mock(
                stdout='',
                returncode=0
            )
            
            result = verify_branch_pushed('feature/nonexistent')
            
            assert result is False
    
    def test_verify_branch_pushed_subprocess_error(self):
        """Test error handling when git command fails."""
        with patch('subprocess.run') as mock_run:
            mock_run.side_effect = subprocess.CalledProcessError(
                1, ['git'], stderr='Could not read from remote'
            )
            
            result = verify_branch_pushed('main')
            
            assert result is False


class TestCreateWorktree:
    """Tests for create_worktree function."""
    
    def test_create_worktree_success(self):
        """Test successful worktree creation."""
        with patch('subprocess.run') as mock_run, \
             patch('pokepoke.worktrees.list_worktrees', return_value=[]), \
             patch('pokepoke.worktrees.get_default_branch', return_value='ameliapayne/dev'), \
             patch('pathlib.Path.mkdir') as mock_mkdir:
            
            mock_run.return_value = Mock(returncode=0, stderr='', stdout='')
            
            result = create_worktree('incredible_icm-42')
            
            assert result == Path('worktrees/task-incredible_icm-42')
            mock_mkdir.assert_called_once_with(exist_ok=True)
            # Verify the call was made (path separator may vary by OS)
            assert mock_run.call_count == 1
            call_args = mock_run.call_args[0][0]
            assert call_args[0:3] == ['git', 'worktree', 'add']
            assert call_args[4:7] == ['-b', 'task/incredible_icm-42', 'ameliapayne/dev']
    
    def test_create_worktree_with_custom_base_branch(self):
        """Test worktree creation with custom base branch."""
        with patch('subprocess.run') as mock_run, \
             patch('pokepoke.worktrees.list_worktrees', return_value=[]), \
             patch('pathlib.Path.mkdir'):
            
            mock_run.return_value = Mock(returncode=0, stderr='', stdout='')
            
            result = create_worktree('incredible_icm-42', base_branch='develop')
            
            assert result == Path('worktrees/task-incredible_icm-42')
            # Verify the call was made with custom base branch
            assert mock_run.call_count == 1
            call_args = mock_run.call_args[0][0]
            assert call_args[0:3] == ['git', 'worktree', 'add']
            assert call_args[-1] == 'develop'
    
    def test_create_worktree_already_exists_by_path(self):
        """Test when worktree already exists at the target path."""
        existing_path = Path('worktrees/task-incredible_icm-42').resolve()
        
        with patch('pokepoke.worktrees.list_worktrees') as mock_list, \
             patch('pathlib.Path.mkdir'), \
             patch('builtins.print') as mock_print:
            
            mock_list.return_value = [
                {'path': str(existing_path), 'branch': 'refs/heads/task/incredible_icm-42'}
            ]
            
            result = create_worktree('incredible_icm-42')
            
            assert result == existing_path
            mock_print.assert_called_once()
            assert 'Reusing existing worktree' in mock_print.call_args[0][0]
    
    def test_create_worktree_already_exists_by_branch(self):
        """Test when worktree already exists with the same branch."""
        with patch('pokepoke.worktrees.list_worktrees') as mock_list, \
             patch('pathlib.Path.mkdir'), \
             patch('builtins.print') as mock_print:
            
            mock_list.return_value = [
                {'path': '/some/other/path', 'branch': 'refs/heads/task/incredible_icm-42'}
            ]
            
            result = create_worktree('incredible_icm-42')
            
            assert result == Path('/some/other/path')
            mock_print.assert_called_once()
            assert 'Reusing existing worktree' in mock_print.call_args[0][0]
    
    def test_create_worktree_branch_already_exists_error_recovery(self):
        """Test recovery when branch already exists."""
        with patch('subprocess.run') as mock_run, \
             patch('pokepoke.worktrees.list_worktrees') as mock_list, \
             patch('pokepoke.worktrees.get_default_branch', return_value='ameliapayne/dev'), \
             patch('pathlib.Path.mkdir'), \
             patch('builtins.print') as mock_print:
            
            # First call: list_worktrees returns empty
            # Second call: subprocess raises error
            # Third call: list_worktrees returns the existing worktree
            mock_list.side_effect = [
                [],  # First check
                [{'path': '/existing/path', 'branch': 'refs/heads/task/incredible_icm-42'}]  # Recovery check
            ]
            
            error = subprocess.CalledProcessError(
                1, ['git'], stderr="fatal: 'task/incredible_icm-42' already exists"
            )
            mock_run.side_effect = error
            
            result = create_worktree('incredible_icm-42')
            
            assert result == Path('/existing/path')
            # Should be called twice: once for error message, once for reusing
            assert mock_print.call_count == 2
            assert 'Reusing existing worktree' in mock_print.call_args[0][0]
    
    def test_create_worktree_unrecoverable_error(self):
        """Test when worktree creation fails with unrecoverable error."""
        with patch('subprocess.run') as mock_run, \
             patch('pokepoke.worktrees.list_worktrees', return_value=[]), \
             patch('pokepoke.worktrees.get_default_branch', return_value='ameliapayne/dev'), \
             patch('pathlib.Path.mkdir'), \
             patch('builtins.print'):
            
            error = subprocess.CalledProcessError(
                1, ['git'], stderr='fatal: some other error'
            )
            mock_run.side_effect = error
            
            with pytest.raises(RuntimeError, match="Failed to create worktree"):
                create_worktree('incredible_icm-42')


class TestIsWorktreeMerged:
    """Tests for is_worktree_merged function."""
    
    def test_is_worktree_merged_true(self):
        """Test when branch is merged."""
        with patch('subprocess.run') as mock_run, \
             patch('pokepoke.worktrees.get_default_branch', return_value='ameliapayne/dev'):
            mock_run.return_value = Mock(
                stdout='  main\n* task/incredible_icm-42\n  develop\n',
                returncode=0
            )
            
            result = is_worktree_merged('incredible_icm-42')
            
            assert result is True
            mock_run.assert_called_once_with(
                ['git', 'branch', '--merged', 'ameliapayne/dev'],
                check=True,
                capture_output=True,
                text=True,
                encoding='utf-8'
            )
    
    def test_is_worktree_merged_false(self):
        """Test when branch is not merged."""
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = Mock(
                stdout='  main\n  develop\n',
                returncode=0
            )
            
            result = is_worktree_merged('incredible_icm-42')
            
            assert result is False
    
    def test_is_worktree_merged_with_custom_target(self):
        """Test with custom target branch."""
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = Mock(
                stdout='  develop\n  task/incredible_icm-42\n',
                returncode=0
            )
            
            result = is_worktree_merged('incredible_icm-42', target_branch='develop')
            
            assert result is True
            mock_run.assert_called_once_with(
                ['git', 'branch', '--merged', 'develop'],
                check=True,
                capture_output=True,
                text=True,
                encoding='utf-8'
            )
    
    def test_is_worktree_merged_subprocess_error(self):
        """Test error handling when git command fails."""
        with patch('subprocess.run') as mock_run:
            mock_run.side_effect = subprocess.CalledProcessError(
                1, ['git'], stderr='error'
            )
            
            result = is_worktree_merged('incredible_icm-42')
            
            assert result is False


class TestMergeWorktree:
    """Tests for merge_worktree function."""
    
    def test_merge_worktree_dirty_worktree(self):
        """Test merge fails when worktree has uncommitted changes."""
        with patch('pokepoke.worktrees.is_worktree_clean', return_value=False), \
             patch('pokepoke.worktrees.get_default_branch', return_value='ameliapayne/dev'), \
             patch('builtins.print') as mock_print:
            
            success, unmerged_files = merge_worktree('incredible_icm-42')
            
            assert success is False
            assert unmerged_files == []
            assert any('Pre-merge validation failed' in str(call) for call in mock_print.call_args_list)
    
    def test_merge_worktree_success(self):
        """Test successful worktree merge with cleanup."""
        with patch('pokepoke.worktrees.is_worktree_clean', return_value=True), \
             patch('subprocess.run') as mock_run, \
             patch('pokepoke.worktrees.get_default_branch', return_value='ameliapayne/dev'), \
             patch('pokepoke.worktrees.is_worktree_merged', return_value=True), \
             patch('pathlib.Path.exists', return_value=True), \
             patch('builtins.print'):
            
            # Configure subprocess.run to return appropriate values for each command
            def run_side_effect(*args, **kwargs):
                cmd = args[0]
                # Handle each command type
                if 'branch' in cmd and '--show-current' in cmd:
                    return Mock(stdout='ameliapayne/dev\n', returncode=0)
                elif 'status' in cmd and '--porcelain' in cmd:
                    return Mock(stdout='', returncode=0)
                else:
                    return Mock(stdout='', stderr='', returncode=0)
            
            mock_run.side_effect = run_side_effect
            
            success, unmerged_files = merge_worktree('incredible_icm-42')
            
            assert success is True
            assert unmerged_files == []
            
            # Verify key commands were called
            calls = [str(call) for call in mock_run.call_args_list]
            assert any('bd' in call and 'sync' in call for call in calls)
            assert any('checkout' in call and 'ameliapayne/dev' in call for call in calls)
            assert any('merge' in call for call in calls)
            assert any('push' in call for call in calls)
            assert any('worktree' in call and 'remove' in call for call in calls)
            assert any('branch' in call and '-d' in call for call in calls)
    
    def test_merge_worktree_cleanup_failure_non_critical(self):
        """Test that cleanup failures don't fail the merge - merge already succeeded."""
        with patch('pokepoke.worktrees.is_worktree_clean', return_value=True), \
             patch('subprocess.run') as mock_run, \
             patch('pokepoke.worktrees.get_default_branch', return_value='ameliapayne/dev'), \
             patch('pokepoke.worktrees.is_worktree_merged', return_value=True), \
             patch('pathlib.Path.exists', return_value=True), \
             patch('builtins.print') as mock_print:
            
            call_count = [0]
            
            def run_side_effect(*args, **kwargs):
                cmd = args[0]
                # Handle each command type
                if 'branch' in cmd and '--show-current' in cmd:
                    return Mock(stdout='ameliapayne/dev\n', returncode=0)
                elif 'status' in cmd and '--porcelain' in cmd:
                    return Mock(stdout='', returncode=0)
                elif 'worktree' in cmd and 'remove' in cmd:
                    # Simulate worktree removal failure (permission denied)
                    raise subprocess.CalledProcessError(
                        1, cmd, 
                        stderr="error: failed to delete 'worktrees/task-xyz': Permission denied"
                    )
                elif 'branch' in cmd and '-d' in cmd:
                    # Branch deletion also fails
                    raise subprocess.CalledProcessError(
                        1, cmd,
                        stderr="error: unable to delete branch"
                    )
                else:
                    return Mock(stdout='', stderr='', returncode=0)
            
            mock_run.side_effect = run_side_effect
            
            # CRITICAL: Merge should succeed even though cleanup failed
            success, unmerged_files = merge_worktree('incredible_icm-42')
            
            assert success is True, "Merge should succeed even when cleanup fails"
            assert unmerged_files == []
            
            # Verify merge was confirmed
            print_calls = [str(call) for call in mock_print.call_args_list]
            assert any('Merge confirmed' in call for call in print_calls), \
                "Should print merge confirmation"
            
            # Verify cleanup warnings were printed
            assert any('Could not remove worktree' in call for call in print_calls), \
                "Should warn about worktree removal failure"
            assert any('Could not delete branch' in call for call in print_calls), \
                "Should warn about branch deletion failure"
            
            # Verify helpful message about non-critical failure
            assert any('Merge successful' in call for call in print_calls), \
                "Should clarify that merge succeeded despite cleanup failure"
    
    def test_merge_worktree_success_no_cleanup(self):
        """Test successful merge without cleanup."""
        with patch('pokepoke.worktrees.is_worktree_clean', return_value=True), \
             patch('subprocess.run') as mock_run, \
             patch('pokepoke.worktrees.get_default_branch', return_value='ameliapayne/dev'), \
             patch('pokepoke.worktrees.is_worktree_merged', return_value=True), \
             patch('builtins.print'):
            
            def run_side_effect(*args, **kwargs):
                cmd = args[0]
                if 'branch' in cmd and '--show-current' in cmd:
                    return Mock(stdout='ameliapayne/dev\n', returncode=0)
                elif 'status' in cmd and '--porcelain' in cmd:
                    return Mock(stdout='', returncode=0)
                else:
                    return Mock(stdout='', stderr='', returncode=0)
            
            mock_run.side_effect = run_side_effect
            
            success, unmerged_files = merge_worktree('incredible_icm-42', cleanup=False)
            
            assert success is True
            assert unmerged_files == []
            
            # Verify worktree removal and branch deletion were NOT called
            calls = [str(call) for call in mock_run.call_args_list]
            assert not any('worktree' in call and 'remove' in call for call in calls)
            assert not any('branch' in call and '-d' in call for call in calls)
    
    def test_merge_worktree_bd_sync_failure(self):
        """Test that merge continues even if bd sync fails."""
        with patch('pokepoke.worktrees.is_worktree_clean', return_value=True), \
             patch('subprocess.run') as mock_run, \
             patch('pokepoke.worktrees.get_default_branch', return_value='ameliapayne/dev'), \
             patch('pokepoke.worktrees.is_worktree_merged', return_value=True), \
             patch('pathlib.Path.exists', return_value=True), \
             patch('builtins.print') as mock_print:
            
            # bd sync fails, other commands succeed
            def run_side_effect(*args, **kwargs):
                cmd = args[0]
                if 'bd' in cmd and 'sync' in cmd:
                    return Mock(stdout='', stderr='error', returncode=1)
                elif 'branch' in cmd and '--show-current' in cmd:
                    return Mock(stdout='ameliapayne/dev\n', returncode=0)
                elif 'status' in cmd and '--porcelain' in cmd:
                    return Mock(stdout='', returncode=0)
                else:
                    return Mock(stdout='', stderr='', returncode=0)
            
            mock_run.side_effect = run_side_effect
            
            success, unmerged_files = merge_worktree('incredible_icm-42')
            
            assert success is True
            assert unmerged_files == []
            assert any('bd sync returned non-zero' in str(call) for call in mock_print.call_args_list)

    def test_merge_worktree_bd_sync_retries_on_access_denied(self):
        """Test that bd sync retries when JSONL file is locked."""
        with patch('pokepoke.worktrees.is_worktree_clean', return_value=True), \
             patch('subprocess.run') as mock_run, \
             patch('pokepoke.worktrees.get_default_branch', return_value='ameliapayne/dev'), \
             patch('pokepoke.worktrees.is_worktree_merged', return_value=True), \
             patch('pathlib.Path.exists', return_value=True), \
             patch('time.sleep') as mock_sleep, \
             patch('builtins.print') as mock_print:

            sync_calls = {'count': 0}

            def run_side_effect(*args, **kwargs):
                cmd = args[0]
                if cmd[:2] == ['bd', 'sync']:
                    sync_calls['count'] += 1
                    if sync_calls['count'] == 1:
                        return Mock(stdout='', stderr='Access is denied while replacing issues.jsonl', returncode=1)
                    return Mock(stdout='', stderr='', returncode=0)
                elif 'branch' in cmd and '--show-current' in cmd:
                    return Mock(stdout='ameliapayne/dev\n', returncode=0)
                elif 'status' in cmd and '--porcelain' in cmd:
                    return Mock(stdout='', returncode=0)
                else:
                    return Mock(stdout='', stderr='', returncode=0)

            mock_run.side_effect = run_side_effect

            success, unmerged_files = merge_worktree('incredible_icm-42')

            assert success is True
            assert unmerged_files == []
            assert sync_calls['count'] == 2
            mock_sleep.assert_called_once()
            assert any('retrying in' in str(call) for call in mock_print.call_args_list)
    
    def test_merge_worktree_with_beads_changes(self):
        """Test merge with uncommitted beads changes in main repo."""
        with patch('pokepoke.worktrees.is_worktree_clean', return_value=True), \
             patch('subprocess.run') as mock_run, \
             patch('pokepoke.worktrees.get_default_branch', return_value='ameliapayne/dev'), \
             patch('pokepoke.worktrees.is_worktree_merged', return_value=True), \
             patch('pathlib.Path.exists', return_value=True), \
             patch('builtins.print') as mock_print:
            
            call_count = [0]
            
            def run_side_effect(*args, **kwargs):
                cmd = args[0]
                # First status check shows beads changes
                if 'status' in cmd and '--porcelain' in cmd and call_count[0] == 1:
                    call_count[0] += 1
                    return Mock(stdout=' M .beads/issues.jsonl\n', returncode=0)
                # Second status check (post-merge) shows clean
                elif 'status' in cmd and '--porcelain' in cmd and call_count[0] == 2:
                    call_count[0] += 1
                    return Mock(stdout='', returncode=0)
                elif 'branch' in cmd and '--show-current' in cmd:
                    return Mock(stdout='ameliapayne/dev\n', returncode=0)
                else:
                    call_count[0] += 1
                    return Mock(stdout='', stderr='', returncode=0)
            
            mock_run.side_effect = run_side_effect
            
            success, unmerged_files = merge_worktree('incredible_icm-42')
            
            assert success is True
            assert unmerged_files == []
            assert any('Committing beads database changes' in str(call) for call in mock_print.call_args_list)
    
    def test_merge_worktree_with_non_beads_changes(self):
        """Test merge fails with non-beads uncommitted changes in main repo."""
        with patch('pokepoke.worktrees.is_worktree_clean', return_value=True), \
             patch('subprocess.run') as mock_run, \
             patch('pokepoke.worktrees.get_default_branch', return_value='ameliapayne/dev'), \
             patch('builtins.print') as mock_print:
            
            call_count = [0]
            
            def run_side_effect(*args, **kwargs):
                cmd = args[0]
                if 'status' in cmd and '--porcelain' in cmd:
                    call_count[0] += 1
                    return Mock(stdout=' M src/file.py\n', returncode=0)
                else:
                    return Mock(stdout='', stderr='', returncode=0)
            
            mock_run.side_effect = run_side_effect
            
            success, unmerged_files = merge_worktree('incredible_icm-42')
            
            assert success is False
            assert unmerged_files == []
            assert any('Cannot merge: main repo has uncommitted non-beads changes' in str(call) 
                      for call in mock_print.call_args_list)
    
    def test_merge_worktree_wrong_branch_after_merge(self):
        """Test post-merge validation fails if not on target branch."""
        with patch('pokepoke.worktrees.is_worktree_clean', return_value=True), \
             patch('subprocess.run') as mock_run, \
             patch('pokepoke.worktrees.get_default_branch', return_value='ameliapayne/dev'), \
             patch('builtins.print') as mock_print:
            
            call_count = [0]
            
            def run_side_effect(*args, **kwargs):
                cmd = args[0]
                if 'branch' in cmd and '--show-current' in cmd:
                    return Mock(stdout='wrong-branch\n', returncode=0)
                elif 'status' in cmd and '--porcelain' in cmd:
                    return Mock(stdout='', returncode=0)
                else:
                    return Mock(stdout='', stderr='', returncode=0)
            
            mock_run.side_effect = run_side_effect
            
            success, unmerged_files = merge_worktree('incredible_icm-42')
            
            assert success is False
            assert unmerged_files == []
            assert any('Post-merge validation failed: Not on ameliapayne/dev' in str(call) 
                      for call in mock_print.call_args_list)
    
    def test_merge_worktree_dirty_after_merge(self):
        """Test post-merge validation fails if target branch is dirty."""
        with patch('pokepoke.worktrees.is_worktree_clean', return_value=True), \
             patch('subprocess.run') as mock_run, \
             patch('pokepoke.worktrees.get_default_branch', return_value='ameliapayne/dev'), \
             patch('builtins.print') as mock_print:
            
            call_count = [0]
            
            def run_side_effect(*args, **kwargs):
                cmd = args[0]
                if 'branch' in cmd and '--show-current' in cmd:
                    return Mock(stdout='master\n', returncode=0)
                elif 'status' in cmd and '--porcelain' in cmd:
                    call_count[0] += 1
                    # First status check is clean, second shows dirty
                    if call_count[0] >= 2:
                        return Mock(stdout=' M file.txt\n', returncode=0)
                    else:
                        return Mock(stdout='', returncode=0)
                else:
                    return Mock(stdout='', stderr='', returncode=0)
            
            mock_run.side_effect = run_side_effect
            
            success, unmerged_files = merge_worktree('incredible_icm-42')
            
            assert success is False
            assert unmerged_files == []
            # Check that the validation failure message was printed
            print_calls = [str(call) for call in mock_print.call_args_list]
            assert any('Post-merge validation failed' in call for call in print_calls)
    
    def test_merge_worktree_not_merged_after_merge(self):
        """Test merge confirmation fails if branch not showing as merged."""
        with patch('pokepoke.worktrees.is_worktree_clean', return_value=True), \
             patch('subprocess.run') as mock_run, \
             patch('pokepoke.worktrees.get_default_branch', return_value='ameliapayne/dev'), \
             patch('pokepoke.worktrees.is_worktree_merged') as mock_merged, \
             patch('builtins.print') as mock_print:
            
            call_count = [0]
            
            def run_side_effect(*args, **kwargs):
                cmd = args[0]
                if 'branch' in cmd and '--show-current' in cmd:
                    return Mock(stdout='ameliapayne/dev\n', returncode=0)
                elif 'status' in cmd and '--porcelain' in cmd:
                    return Mock(stdout='', returncode=0)
                else:
                    return Mock(stdout='', stderr='', returncode=0)
            
            mock_run.side_effect = run_side_effect
            mock_merged.return_value = False
            
            success, unmerged_files = merge_worktree('incredible_icm-42')
            
            assert success is False
            assert unmerged_files == []
            assert any('Merge confirmation failed' in str(call) for call in mock_print.call_args_list)
    
    def test_merge_worktree_subprocess_error(self):
        """Test merge fails on subprocess error."""
        with patch('pokepoke.worktrees.is_worktree_clean', return_value=True), \
             patch('subprocess.run') as mock_run, \
             patch('pokepoke.worktrees.get_default_branch', return_value='ameliapayne/dev'), \
             patch('builtins.print') as mock_print:
            
            # bd sync succeeds, checkout fails
            call_count = [0]
            
            def run_side_effect(*args, **kwargs):
                cmd = args[0]
                if call_count[0] == 0:  # bd sync
                    call_count[0] += 1
                    return Mock(stdout='', stderr='', returncode=0)
                elif call_count[0] == 1:  # git status (main repo check)
                    call_count[0] += 1
                    return Mock(stdout='', returncode=0)
                else:  # checkout fails
                    raise subprocess.CalledProcessError(1, cmd, stderr='checkout error')
            
            mock_run.side_effect = run_side_effect
            
            success, unmerged_files = merge_worktree('incredible_icm-42')
            
            assert success is False
            # unmerged_files might be empty on general merge failure
            assert any('Merge failed' in str(call) or 'checkout' in str(call) for call in mock_print.call_args_list)


class TestCleanupWorktree:
    """Tests for cleanup_worktree function."""
    
    def test_cleanup_worktree_success(self):
        """Test successful worktree cleanup."""
        with patch('subprocess.run') as mock_run, \
             patch('pokepoke.worktrees.list_worktrees') as mock_list, \
             patch('pathlib.Path.exists', return_value=True):
            
            mock_list.return_value = [
                {'path': 'worktrees/task-incredible_icm-42', 'branch': 'refs/heads/task/incredible_icm-42'}
            ]
            mock_run.return_value = Mock(returncode=0, stderr='', stdout='')
            
            result = cleanup_worktree('incredible_icm-42')
            
            assert result is True
            # Should call: list_worktrees, worktree remove, branch delete
            assert mock_run.call_count == 2
            
            # Check worktree removal call
            call_args = mock_run.call_args_list[0][0][0]
            assert call_args[0:3] == ['git', 'worktree', 'remove']
            assert 'task-incredible_icm-42' in call_args[3]
            
            # Check branch deletion call
            assert mock_run.call_args_list[1][0][0] == [
                'git', 'branch', '-d', 'task/incredible_icm-42'
            ]
    
    def test_cleanup_worktree_force(self):
        """Test forced worktree cleanup."""
        with patch('subprocess.run') as mock_run, \
             patch('pokepoke.worktrees.list_worktrees') as mock_list, \
             patch('pathlib.Path.exists', return_value=True):
            
            mock_list.return_value = [
                {'path': 'worktrees/task-incredible_icm-42', 'branch': 'refs/heads/task/incredible_icm-42'}
            ]
            mock_run.return_value = Mock(returncode=0, stderr='', stdout='')
            
            result = cleanup_worktree('incredible_icm-42', force=True)
            
            assert result is True
            
            # Check worktree removal includes --force
            call_args = mock_run.call_args_list[0][0][0]
            assert call_args[0:3] == ['git', 'worktree', 'remove']
            assert 'task-incredible_icm-42' in call_args[3]
            assert '--force' in call_args
            
            # Check branch deletion uses -D
            assert mock_run.call_args_list[1][0][0] == [
                'git', 'branch', '-D', 'task/incredible_icm-42'
            ]
    
    def test_cleanup_worktree_not_exists(self):
        """Test cleanup when worktree path doesn't exist."""
        with patch('subprocess.run') as mock_run, \
             patch('pokepoke.worktrees.list_worktrees', return_value=[]), \
             patch('pathlib.Path.exists', return_value=False):
            
            # Branch deletion fails because it doesn't exist
            mock_run.side_effect = subprocess.CalledProcessError(
                1, ['git'], stderr='error: branch not found'
            )
            
            result = cleanup_worktree('incredible_icm-42')
            
            # Should succeed even if branch doesn't exist
            assert result is True
            # Should try to delete branch (twice: sanitized and unsanitized)
            assert mock_run.call_count == 2
    
    def test_cleanup_worktree_subprocess_error(self):
        """Test cleanup continues despite subprocess errors for non-existent items."""
        with patch('subprocess.run') as mock_run, \
             patch('pokepoke.worktrees.list_worktrees') as mock_list, \
             patch('pathlib.Path.exists', return_value=True), \
             patch('builtins.print') as mock_print:
            
            mock_list.return_value = [
                {'path': 'worktrees/task-incredible_icm-42', 'branch': 'refs/heads/task/incredible_icm-42'}
            ]
            
            # Worktree removal succeeds
            def run_side_effect(*args, **kwargs):
                cmd = args[0]
                if 'worktree' in cmd and 'remove' in cmd:
                    return Mock(returncode=0, stderr='', stdout='')
                else:
                    # Branch deletion fails with real error
                    raise subprocess.CalledProcessError(
                        1, cmd, stderr='fatal: some other error'
                    )
            
            mock_run.side_effect = run_side_effect
            
            result = cleanup_worktree('incredible_icm-42')
            
            # Should fail if branch deletion fails with non-ignorable error
            assert result is False
            mock_print.assert_called()
            assert 'Branch deletion warning' in mock_print.call_args[0][0]

    def test_cleanup_worktree_permission_denied_retries_with_force(self):
        """Test that permission denied triggers force_remove_directory fallback."""
        with patch('subprocess.run') as mock_run, \
             patch('pokepoke.worktrees.list_worktrees') as mock_list, \
             patch('pathlib.Path.exists', return_value=True), \
             patch('pokepoke.worktrees.force_remove_directory', return_value=True) as mock_force, \
             patch('builtins.print'):
            
            mock_list.return_value = [
                {'path': 'worktrees/task-incredible_icm-42', 'branch': 'refs/heads/task/incredible_icm-42'}
            ]
            
            def run_side_effect(*args, **kwargs):
                cmd = args[0]
                if 'worktree' in cmd and 'remove' in cmd:
                    raise subprocess.CalledProcessError(
                        1, cmd,
                        stderr="error: failed to delete 'worktrees/task-xyz': Permission denied"
                    )
                else:
                    return Mock(returncode=0, stderr='', stdout='')
            
            mock_run.side_effect = run_side_effect
            
            result = cleanup_worktree('incredible_icm-42')
            
            assert result is True
            mock_force.assert_called_once()

    def test_cleanup_worktree_being_used_by_another_process(self):
        """Test that 'being used by another process' triggers force removal."""
        with patch('subprocess.run') as mock_run, \
             patch('pokepoke.worktrees.list_worktrees') as mock_list, \
             patch('pathlib.Path.exists', return_value=True), \
             patch('pokepoke.worktrees.force_remove_directory', return_value=False) as mock_force, \
             patch('builtins.print') as mock_print:
            
            mock_list.return_value = [
                {'path': 'worktrees/task-incredible_icm-42', 'branch': 'refs/heads/task/incredible_icm-42'}
            ]
            
            def run_side_effect(*args, **kwargs):
                cmd = args[0]
                if 'worktree' in cmd and 'remove' in cmd:
                    raise subprocess.CalledProcessError(
                        1, cmd,
                        stderr="error: The process cannot access the file because it is being used by another process"
                    )
                elif 'branch' in cmd:
                    return Mock(returncode=0, stderr='', stdout='')
                return Mock(returncode=0, stderr='', stdout='')
            
            mock_run.side_effect = run_side_effect
            
            result = cleanup_worktree('incredible_icm-42')
            
            # Should still return True because branch deletion succeeded
            assert result is True
            mock_force.assert_called_once()
            print_calls = [str(c) for c in mock_print.call_args_list]
            assert any('Could not remove worktree directory after retries' in c for c in print_calls)


class TestForceRemoveDirectory:
    """Tests for force_remove_directory helper."""

    def test_force_remove_git_worktree_force_succeeds(self):
        """Test that git worktree remove --force succeeds on first attempt."""
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = Mock(returncode=0, stderr='', stdout='')
            
            result = force_remove_directory(Path("worktrees/task-test"))
            
            assert result is True
            call_args = mock_run.call_args_list[0][0][0]
            assert call_args[:4] == ['git', 'worktree', 'remove', '--force']
            assert 'task-test' in call_args[4]

    def test_force_remove_falls_back_to_shutil(self):
        """Test fallback to shutil.rmtree when git worktree remove --force fails."""
        with patch('subprocess.run') as mock_run, \
             patch('shutil.rmtree') as mock_rmtree:
            
            def run_side_effect(*args, **kwargs):
                cmd = args[0]
                if 'prune' in cmd:
                    return Mock(returncode=0, stderr='', stdout='')
                raise subprocess.CalledProcessError(1, cmd, stderr='failed')
            
            mock_run.side_effect = run_side_effect
            mock_rmtree.return_value = None
            
            result = force_remove_directory(Path("worktrees/task-test"))
            
            assert result is True
            mock_rmtree.assert_called_once()

    def test_force_remove_retries_on_permission_error(self):
        """Test retry logic when both git and shutil fail."""
        with patch('subprocess.run') as mock_run, \
             patch('shutil.rmtree') as mock_rmtree, \
             patch('time.sleep') as mock_sleep:
            
            def run_side_effect(*args, **kwargs):
                cmd = args[0]
                if 'prune' in cmd:
                    return Mock(returncode=0, stderr='', stdout='')
                raise subprocess.CalledProcessError(1, cmd, stderr='failed')
            
            mock_run.side_effect = run_side_effect
            # Fail twice, succeed on third attempt
            mock_rmtree.side_effect = [PermissionError("locked"), PermissionError("locked"), None]
            
            result = force_remove_directory(Path("worktrees/task-test"))
            
            assert result is True
            assert mock_sleep.call_count == 2

    def test_force_remove_returns_false_after_all_retries_exhausted(self):
        """Test that False is returned when all retries are exhausted."""
        with patch('subprocess.run') as mock_run, \
             patch('shutil.rmtree') as mock_rmtree, \
             patch('time.sleep'):
            
            def run_side_effect(*args, **kwargs):
                cmd = args[0]
                if 'prune' in cmd:
                    return Mock(returncode=0, stderr='', stdout='')
                raise subprocess.CalledProcessError(1, cmd, stderr='failed')
            
            mock_run.side_effect = run_side_effect
            mock_rmtree.side_effect = PermissionError("locked")
            
            result = force_remove_directory(Path("worktrees/task-test"))
            
            assert result is False

    def test_handle_remove_readonly(self):
        """Test that _handle_remove_readonly clears read-only and retries."""
        with patch('os.chmod') as mock_chmod:
            mock_func = Mock()
            _handle_remove_readonly(mock_func, '/some/path', None)
            
            mock_chmod.assert_called_once_with('/some/path', 0o200)
            mock_func.assert_called_once_with('/some/path')


class TestCleanupAfterMergePermissionDenied:
    """Tests for _cleanup_after_merge with permission denied errors."""

    def test_cleanup_after_merge_permission_denied_force_removes(self):
        """Test that permission denied in _cleanup_after_merge triggers force removal."""
        from pokepoke.worktrees import _cleanup_after_merge
        
        with patch('subprocess.run') as mock_run, \
             patch('pathlib.Path.exists', return_value=True), \
             patch('pokepoke.worktrees.force_remove_directory', return_value=True) as mock_force, \
             patch('builtins.print') as mock_print:
            
            def run_side_effect(*args, **kwargs):
                cmd = args[0]
                if 'worktree' in cmd and 'remove' in cmd:
                    raise subprocess.CalledProcessError(
                        1, cmd,
                        stderr="Permission denied"
                    )
                return Mock(returncode=0, stderr='', stdout='')
            
            mock_run.side_effect = run_side_effect
            
            _cleanup_after_merge(Path("worktrees/task-test"), "task/test-branch")
            
            mock_force.assert_called_once()
            print_calls = [str(c) for c in mock_print.call_args_list]
            assert any('Force-removed worktree' in c for c in print_calls)

    def test_cleanup_after_merge_permission_denied_force_fails(self):
        """Test fallback message when force removal also fails."""
        from pokepoke.worktrees import _cleanup_after_merge
        
        with patch('subprocess.run') as mock_run, \
             patch('pathlib.Path.exists', return_value=True), \
             patch('pokepoke.worktrees.force_remove_directory', return_value=False) as mock_force, \
             patch('builtins.print') as mock_print:
            
            def run_side_effect(*args, **kwargs):
                cmd = args[0]
                if 'worktree' in cmd and 'remove' in cmd:
                    raise subprocess.CalledProcessError(
                        1, cmd,
                        stderr="Permission denied"
                    )
                return Mock(returncode=0, stderr='', stdout='')
            
            mock_run.side_effect = run_side_effect
            
            _cleanup_after_merge(Path("worktrees/task-test"), "task/test-branch")
            
            mock_force.assert_called_once()
            print_calls = [str(c) for c in mock_print.call_args_list]
            assert any('Could not remove worktree after retries' in c for c in print_calls)
            assert any('Merge successful' in c for c in print_calls)


class TestListWorktrees:
    """Tests for list_worktrees function."""
    
    def test_list_worktrees_success(self):
        """Test listing worktrees successfully."""
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = Mock(
                stdout=(
                    'worktree /home/user/repo\n'
                    'HEAD abc123\n'
                    'branch refs/heads/ameliapayne/dev\n'
                    '\n'
                    'worktree /home/user/repo/worktrees/task-42\n'
                    'HEAD def456\n'
                    'branch refs/heads/task/incredible_icm-42\n'
                ),
                returncode=0
            )
            
            result = list_worktrees()
            
            assert len(result) == 2
            assert result[0] == {
                'path': '/home/user/repo',
                'commit': 'abc123',
                'branch': 'refs/heads/ameliapayne/dev'
            }
            assert result[1] == {
                'path': '/home/user/repo/worktrees/task-42',
                'commit': 'def456',
                'branch': 'refs/heads/task/incredible_icm-42'
            }
            
            mock_run.assert_called_once_with(
                ['git', 'worktree', 'list', '--porcelain'],
                check=True,
                capture_output=True,
                text=True,
                encoding='utf-8'
            )
    
    def test_list_worktrees_empty(self):
        """Test listing worktrees when there are none."""
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = Mock(
                stdout='',
                returncode=0
            )
            
            result = list_worktrees()
            
            assert result == []
    
    def test_list_worktrees_subprocess_error(self):
        """Test error handling when git command fails."""
        with patch('subprocess.run') as mock_run:
            mock_run.side_effect = subprocess.CalledProcessError(
                1, ['git'], stderr='error'
            )
            
            result = list_worktrees()
            
            assert result == []
    
    def test_list_worktrees_partial_info(self):
        """Test listing worktrees with partial information."""
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = Mock(
                stdout=(
                    'worktree /home/user/repo\n'
                    'HEAD abc123\n'
                    '\n'
                    'worktree /home/user/repo/worktrees/task-42\n'
                    'branch refs/heads/task/incredible_icm-42\n'
                ),
                returncode=0
            )
            
            result = list_worktrees()
            
            assert len(result) == 2
            # First worktree has no branch
            assert 'branch' not in result[0]
            assert result[0]['path'] == '/home/user/repo'
            assert result[0]['commit'] == 'abc123'
            
            # Second worktree has no commit
            assert 'commit' not in result[1]
            assert result[1]['path'] == '/home/user/repo/worktrees/task-42'
            assert result[1]['branch'] == 'refs/heads/task/incredible_icm-42'
