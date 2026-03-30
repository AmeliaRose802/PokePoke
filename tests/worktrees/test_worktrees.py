"""Tests for git worktree management."""
import json
import subprocess
import unittest.mock
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

# Import the module to ensure coverage tracking works
from pokepoke.git.git_helpers import verify_branch_pushed
from pokepoke.git.git_operations import get_default_branch, get_main_repo_root, is_worktree_clean, sanitize_branch_name
from pokepoke.worktrees.worktree_cleanup import (
    _is_windows_lock_error,
    add_uncleaned_worktree,
    force_remove_directory,
    get_uncleaned_worktree_count,
    load_worktree_manifest,
    remove_from_manifest,
    retry_failed_cleanups,
    save_worktree_manifest,
)
from pokepoke.worktrees.worktrees import (
    cleanup_worktree,
    create_worktree,
    is_worktree_merged,
    list_worktrees,
    merge_worktree,
)


@pytest.mark.allow_real_bd
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


@pytest.mark.allow_real_bd
class TestDefaultBranchResolution:
    """Tests for default branch resolution helpers."""

    def test_get_default_branch_prefers_config_branch(self):
        """Test get_default_branch returns config-preferred branch when it exists."""
        with patch('pokepoke.git.git_operations.branch_exists', return_value=True), \
             patch('pokepoke.config._cached_config', None), \
             patch('pokepoke.config._find_repo_root') as mock_root:
            mock_root.return_value = Path('/fake/root')
            # Config auto-detects username from git, so pass preferred explicitly
            assert get_default_branch(preferred='ameliapayne/dev') == 'ameliapayne/dev'

    def test_get_default_branch_uses_origin_head(self):
        """Test get_default_branch falls back to origin/HEAD when preferred missing."""
        with patch('pokepoke.git.git_operations.branch_exists', return_value=False), \
             patch('subprocess.run') as mock_run:
            mock_run.return_value = Mock(returncode=0, stdout='origin/master\n', stderr='')

            assert get_default_branch(preferred='') == 'master'

    def test_get_default_branch_uses_current_branch(self):
        """Test get_default_branch falls back to current branch when origin/HEAD fails."""
        with patch('pokepoke.git.git_operations.branch_exists', return_value=False), \
             patch('subprocess.run') as mock_run:
            mock_run.side_effect = [
                subprocess.CalledProcessError(1, ['git']),
                Mock(returncode=0, stdout='task/PokePoke-6g1\n', stderr='')
            ]

            assert get_default_branch(preferred='') == 'task/PokePoke-6g1'


@pytest.mark.allow_real_bd
class TestGetMainRepoRoot:
    """Tests for get_main_repo_root function."""

    def test_get_main_repo_root_in_main_repo(self):
        """Test getting main repo root when in main repository."""
        with patch('pokepoke.git.git_operations.run_git') as mock_run_git:
            mock_run_git.return_value = Mock(
                stdout='/home/user/repo/.git\n',
                returncode=0
            )

            result = get_main_repo_root()

            assert result == Path('/home/user/repo')
            mock_run_git.assert_called_once_with(
                ['git', 'rev-parse', '--git-common-dir'],
            )

    def test_get_main_repo_root_in_worktree(self):
        """Test getting main repo root when in a worktree."""
        with patch('pokepoke.git.git_operations.run_git') as mock_run_git:
            mock_run_git.return_value = Mock(
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


@pytest.mark.allow_real_bd
class TestIsWorktreeClean:
    """Tests for is_worktree_clean function."""

    def test_is_worktree_clean_true(self):
        """Test worktree with no uncommitted changes."""
        worktree_path = Path('/home/user/repo/worktrees/task-123')

        with patch('pokepoke.git.git_operations.run_git') as mock_run_git:
            mock_run_git.return_value = Mock(
                stdout='',
                returncode=0
            )

            result = is_worktree_clean(worktree_path)

            assert result is True
            mock_run_git.assert_called_once_with(
                ['git', '-C', str(worktree_path), 'status', '--porcelain'],
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


@pytest.mark.allow_real_bd
class TestVerifyBranchPushed:
    """Tests for verify_branch_pushed function."""

    def test_verify_branch_pushed_exists(self):
        """Test verification when branch exists on remote."""
        with patch('pokepoke.git.git_helpers.subprocess.run') as mock_run:
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
                errors='replace',
                check=True,
                timeout=120,
                cwd=None
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


@pytest.mark.allow_real_bd
class TestCreateWorktree:
    """Tests for create_worktree function."""

    def test_create_worktree_success(self):
        """Test successful worktree creation."""
        with patch('subprocess.run') as mock_run, \
             patch('pokepoke.worktrees.worktrees.list_worktrees', return_value=[]), \
             patch('pokepoke.worktrees.worktrees.get_default_branch', return_value='ameliapayne/dev'), \
             patch('pathlib.Path.mkdir') as mock_mkdir, \
             patch('pokepoke.worktrees.worktrees._validate_worktree_integrity'):

            mock_run.return_value = Mock(returncode=0, stderr='', stdout='')

            result = create_worktree('incredible_icm-42')

            assert result == Path('worktrees/task-incredible_icm-42').resolve()
            # mkdir is called for: worktrees/, .pokepoke/locks/, and .pokepoke/stats/
            assert mock_mkdir.call_count >= 1
            # Verify worktrees directory creation was called
            assert any(call[1].get('exist_ok') for call in mock_mkdir.call_args_list)
            # Verify the git call was made (path separator may vary by OS)
            assert mock_run.call_count == 1
            call_args = mock_run.call_args[0][0]
            assert call_args[0:3] == ['git', 'worktree', 'add']
            assert call_args[4:7] == ['-b', 'task/incredible_icm-42', 'ameliapayne/dev']

    def test_create_worktree_with_custom_base_branch(self):
        """Test worktree creation with custom base branch."""
        with patch('subprocess.run') as mock_run, \
             patch('pokepoke.worktrees.worktrees.list_worktrees', return_value=[]), \
             patch('pathlib.Path.mkdir'), \
             patch('pokepoke.worktrees.worktrees._validate_worktree_integrity'):

            mock_run.return_value = Mock(returncode=0, stderr='', stdout='')

            result = create_worktree('incredible_icm-42', base_branch='develop')

            assert result == Path('worktrees/task-incredible_icm-42').resolve()
            # Verify the call was made with custom base branch
            assert mock_run.call_count == 1
            call_args = mock_run.call_args[0][0]
            assert call_args[0:3] == ['git', 'worktree', 'add']
            assert call_args[-1] == 'develop'

    def test_create_worktree_already_exists_by_path(self):
        """Test when worktree already exists at the target path."""
        existing_path = Path('worktrees/task-incredible_icm-42').resolve()

        with patch('pokepoke.worktrees.worktrees.list_worktrees') as mock_list, \
             patch('pathlib.Path.mkdir'), \
             patch('builtins.print') as mock_print:

            mock_list.return_value = [
                {'path': str(existing_path), 'branch': 'refs/heads/task/incredible_icm-42'}
            ]

            result = create_worktree('incredible_icm-42')

            assert result == existing_path
            assert mock_print.called
            assert 'Reusing existing worktree' in mock_print.call_args[0][0]

    def test_create_worktree_already_exists_by_branch(self):
        """Test when worktree already exists with the same branch."""
        with patch('pokepoke.worktrees.worktrees.list_worktrees') as mock_list, \
             patch('pathlib.Path.mkdir'), \
             patch('builtins.print') as mock_print:

            mock_list.return_value = [
                {'path': '/some/other/path', 'branch': 'refs/heads/task/incredible_icm-42'}
            ]

            result = create_worktree('incredible_icm-42')

            assert result == Path('/some/other/path')
            assert mock_print.called
            assert 'Reusing existing worktree' in mock_print.call_args[0][0]

    def test_create_worktree_directory_exists_valid(self):
        """Test when worktree directory exists and is a valid git worktree."""
        existing_path = Path('worktrees/task-incredible_icm-42')

        with patch('pokepoke.worktrees.worktrees.list_worktrees', return_value=[]), \
             patch('pathlib.Path.mkdir'), \
             patch('pathlib.Path.exists', return_value=True), \
             patch('pokepoke.worktrees.worktrees._run_git') as mock_run_git, \
             patch('pokepoke.worktrees.worktrees.get_default_branch', return_value='master'), \
             patch('builtins.print') as mock_print:

            # Mock git rev-parse --is-inside-work-tree to return true
            mock_run_git.return_value = Mock(stdout="true\n", returncode=0)

            result = create_worktree('incredible_icm-42')

            assert result == existing_path.resolve()
            assert mock_print.called
            assert 'Reusing existing worktree directory' in mock_print.call_args[0][0]
            mock_run_git.assert_called_once_with(
                ["git", "rev-parse", "--is-inside-work-tree"],
                cwd=str(existing_path.resolve()),
                timeout=10,
                check=False,
            )

    def test_create_worktree_directory_exists_invalid(self):
        """Test when worktree directory exists but is not a valid git worktree."""
        existing_path = Path('worktrees/task-incredible_icm-42')

        with patch('pokepoke.worktrees.worktrees.list_worktrees', return_value=[]), \
             patch('pathlib.Path.mkdir'), \
             patch('pathlib.Path.exists', return_value=True), \
             patch('pokepoke.worktrees.worktrees.force_remove_directory', return_value=True) as mock_remove, \
             patch('pokepoke.worktrees.worktrees._run_git') as mock_run_git, \
             patch('pokepoke.worktrees.worktrees.get_default_branch', return_value='master'), \
             patch('builtins.print'), \
             patch('pokepoke.worktrees.worktrees._validate_worktree_integrity'):

            # First call (rev-parse) fails, subsequent calls succeed
            mock_run_git.side_effect = [
                subprocess.CalledProcessError(128, "git"),  # rev-parse fails
                Mock(returncode=0),  # worktree prune
                Mock(returncode=0),  # worktree add
            ]

            result = create_worktree('incredible_icm-42')

            assert result == existing_path.resolve()
            mock_remove.assert_called_once_with(existing_path.resolve())
            # Should have called rev-parse, git worktree prune, and git worktree add
            assert mock_run_git.call_count == 3
            assert mock_run_git.call_args_list[1][0][0] == ["git", "worktree", "prune"]
            assert mock_run_git.call_args_list[2][0][0] == ["git", "worktree", "add", str(existing_path.resolve()), "-b", "task/incredible_icm-42", "master"]

    def test_create_worktree_branch_already_exists_error_recovery(self):
        """Test recovery when branch already exists."""
        with patch('subprocess.run') as mock_run, \
             patch('pokepoke.worktrees.worktrees.list_worktrees') as mock_list, \
             patch('pokepoke.worktrees.worktrees.get_default_branch', return_value='ameliapayne/dev'), \
             patch('pathlib.Path.mkdir'), \
             patch('builtins.print') as mock_print:

            # First call: list_worktrees returns empty
            # Second call (inside lock): double-check returns empty
            # Subprocess raises error
            # Third call: list_worktrees returns the existing worktree
            mock_list.side_effect = [
                [],  # First check
                [],  # Double-check inside lock
                [{'path': '/existing/path', 'branch': 'refs/heads/task/incredible_icm-42'}]  # Recovery check
            ]

            error = subprocess.CalledProcessError(
                1, ['git'], stderr="fatal: 'task/incredible_icm-42' already exists"
            )
            mock_run.side_effect = error

            result = create_worktree('incredible_icm-42')

            assert result == Path('/existing/path')
            # Should print at least once for error and once for reusing
            assert mock_print.call_count >= 1
            # Check that the reuse message was printed
            assert any('Reusing' in str(call) for call in mock_print.call_args_list)

    def test_create_worktree_unrecoverable_error(self):
        """Test when worktree creation fails with unrecoverable error."""
        with patch('subprocess.run') as mock_run, \
             patch('pokepoke.worktrees.worktrees.list_worktrees', return_value=[]), \
             patch('pokepoke.worktrees.worktrees.get_default_branch', return_value='ameliapayne/dev'), \
             patch('pathlib.Path.mkdir'), \
             patch('builtins.print'):

            error = subprocess.CalledProcessError(
                1, ['git'], stderr='fatal: some other error'
            )
            mock_run.side_effect = error

            with pytest.raises(RuntimeError, match="Failed to create worktree"):
                create_worktree('incredible_icm-42')


@pytest.mark.allow_real_bd
class TestIsWorktreeMerged:
    """Tests for is_worktree_merged function."""

    def test_is_worktree_merged_true(self):
        """Test when branch is merged."""
        with patch('subprocess.run') as mock_run, \
             patch('pokepoke.worktrees.worktrees.get_default_branch', return_value='ameliapayne/dev'):
            mock_run.return_value = Mock(
                stdout='  main\n* task/incredible_icm-42\n  develop\n',
                returncode=0
            )

            result = is_worktree_merged('incredible_icm-42')

            assert result is True
            mock_run.assert_called_once()
            call_args = mock_run.call_args
            assert call_args[0][0] == ['git', 'branch', '--merged', 'ameliapayne/dev']

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
            mock_run.assert_called_once()
            call_args = mock_run.call_args
            assert call_args[0][0] == ['git', 'branch', '--merged', 'develop']

    def test_is_worktree_merged_subprocess_error(self):
        """Test error handling when git command fails."""
        with patch('subprocess.run') as mock_run:
            mock_run.side_effect = subprocess.CalledProcessError(
                1, ['git'], stderr='error'
            )

            result = is_worktree_merged('incredible_icm-42')

            assert result is False


@pytest.mark.allow_real_bd
class TestMergeWorktree:
    """Tests for merge_worktree function."""

    def test_merge_worktree_dirty_worktree(self):
        """Test merge fails when worktree has uncommitted changes."""
        with patch('pokepoke.worktrees.worktrees.is_worktree_clean', return_value=False), \
             patch('pokepoke.worktrees.worktrees.get_default_branch', return_value='ameliapayne/dev'), \
             patch('builtins.print') as mock_print:

            success, unmerged_files = merge_worktree('incredible_icm-42')

            assert success is False
            assert unmerged_files == []
            assert any('Pre-merge validation failed' in str(call) for call in mock_print.call_args_list)

    def test_merge_worktree_success(self):
        """Test successful worktree merge with cleanup."""
        exists_state = {'present': True}

        def exists_side_effect(self: Path) -> bool:
            normalized = str(self).replace('\\', '/')
            if normalized.endswith('worktrees/task-incredible_icm-42'):
                return exists_state['present']
            return True

        with patch('pokepoke.worktrees.worktrees.is_worktree_clean', return_value=True), \
             patch('subprocess.run') as mock_run, \
             patch('pokepoke.worktrees.worktrees.get_default_branch', return_value='ameliapayne/dev'), \
             patch('pokepoke.worktrees.worktrees.is_worktree_merged', return_value=True), \
             patch('pathlib.Path.exists', new=exists_side_effect), \
             patch('builtins.print'):

            # Configure subprocess.run to return appropriate values for each command
            def run_side_effect(*args, **kwargs):
                cmd = args[0]
                # Handle each command type
                if 'branch' in cmd and '--show-current' in cmd:
                    return Mock(stdout='ameliapayne/dev\n', returncode=0)
                elif 'status' in cmd and '--porcelain' in cmd:
                    return Mock(stdout='', returncode=0)
                elif 'worktree' in cmd and 'remove' in cmd:
                    exists_state['present'] = False
                    return Mock(stdout='', stderr='', returncode=0)
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
        with patch('pokepoke.worktrees.worktrees.is_worktree_clean', return_value=True), \
             patch('subprocess.run') as mock_run, \
             patch('pokepoke.worktrees.worktrees.get_default_branch', return_value='ameliapayne/dev'), \
             patch('pokepoke.worktrees.worktrees.is_worktree_merged', return_value=True), \
             patch('pathlib.Path.exists', return_value=True), \
             patch('pokepoke.worktrees.worktree_cleanup.force_remove_directory', return_value=False), \
             patch('builtins.print') as mock_print:

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
            assert any('Skipping branch deletion' in call for call in print_calls), \
                "Should skip branch deletion when worktree still exists"

            # Verify helpful message about non-critical failure
            assert any('Merge successful' in call for call in print_calls), \
                "Should clarify that merge succeeded despite cleanup failure"

    def test_merge_worktree_success_no_cleanup(self):
        """Test successful merge without cleanup."""
        with patch('pokepoke.worktrees.worktrees.is_worktree_clean', return_value=True), \
             patch('subprocess.run') as mock_run, \
             patch('pokepoke.worktrees.worktrees.get_default_branch', return_value='ameliapayne/dev'), \
             patch('pokepoke.worktrees.worktrees.is_worktree_merged', return_value=True), \
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
        with patch('pokepoke.worktrees.worktrees.is_worktree_clean', return_value=True), \
             patch('subprocess.run') as mock_run, \
             patch('pokepoke.worktrees.worktrees.get_default_branch', return_value='ameliapayne/dev'), \
             patch('pokepoke.worktrees.worktrees.is_worktree_merged', return_value=True), \
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
        with patch('pokepoke.worktrees.worktrees.is_worktree_clean', return_value=True), \
             patch('subprocess.run') as mock_run, \
             patch('pokepoke.worktrees.worktrees.get_default_branch', return_value='ameliapayne/dev'), \
             patch('pokepoke.worktrees.worktrees.is_worktree_merged', return_value=True), \
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
            mock_sleep.assert_any_call(0.5)
            assert any('retrying in' in str(call) for call in mock_print.call_args_list)

    def test_merge_worktree_with_beads_changes(self):
        """Test merge with uncommitted beads changes in main repo."""
        with patch('pokepoke.worktrees.worktrees.is_worktree_clean', return_value=True), \
             patch('subprocess.run') as mock_run, \
             patch('pokepoke.worktrees.worktrees.get_default_branch', return_value='ameliapayne/dev'), \
             patch('pokepoke.worktrees.worktrees.is_worktree_merged', return_value=True), \
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

    def test_merge_worktree_with_non_beads_changes_commit_fails(self):
        """Test merge fails when non-beads uncommitted changes cannot be committed."""
        with patch('pokepoke.worktrees.worktrees.is_worktree_clean', return_value=True), \
             patch('pokepoke.worktrees.worktree_helpers.run_bd_sync_with_retry') as mock_sync, \
             patch('pokepoke.worktrees.worktrees._run_git') as mock_git, \
             patch('pokepoke.worktrees.worktree_helpers.run_git') as mock_helper_git, \
             patch('pokepoke.worktrees.worktree_helpers.commit_all_changes', return_value=(False, 'pre-commit hooks failed')) as mock_commit, \
             patch('pokepoke.worktrees.worktrees.get_default_branch', return_value='ameliapayne/dev'), \
             patch('builtins.print') as mock_print:

            mock_sync.return_value = Mock(returncode=0)
            # worktree_helpers._run_git: status shows non-beads changes
            mock_helper_git.return_value = Mock(stdout=' M src/file.py\n', returncode=0)
            mock_git.return_value = Mock(stdout=' M src/file.py\n', returncode=0)

            success, unmerged_files = merge_worktree('incredible_icm-42')

            assert success is False
            assert unmerged_files == []
            mock_commit.assert_called_once()
            assert any('Cannot merge: failed to commit pending changes' in str(call)
                      for call in mock_print.call_args_list)

    def test_merge_worktree_with_non_beads_changes_commit_succeeds(self):
        """Test merge proceeds when non-beads changes are successfully committed before merge."""
        with patch('pokepoke.worktrees.worktrees.is_worktree_clean', return_value=True), \
             patch('pokepoke.worktrees.worktree_helpers.run_bd_sync_with_retry') as mock_sync, \
             patch('pokepoke.worktrees.worktrees._run_git') as mock_git, \
             patch('pokepoke.worktrees.worktree_helpers.run_git') as mock_helper_git, \
             patch('pokepoke.worktrees.worktree_helpers.commit_all_changes', return_value=(True, '')), \
             patch('pokepoke.worktrees.worktrees._sync_and_ensure_clean_main_repo', return_value=True), \
             patch('pokepoke.worktrees.worktrees.execute_merge_sequence', return_value=(True, '', [])), \
             patch('pokepoke.worktrees.worktrees.validate_post_merge', return_value=True), \
             patch('pokepoke.worktrees.worktrees.cleanup_after_merge'), \
             patch('pokepoke.worktrees.worktrees.get_default_branch', return_value='ameliapayne/dev'), \
             patch('pokepoke.worktrees.worktrees.is_worktree_merged', return_value=True), \
             patch('builtins.print'):

            mock_sync.return_value = Mock(returncode=0)
            # worktree_helpers._run_git: status shows non-beads changes only
            mock_helper_git.return_value = Mock(stdout=' M src/file.py\n', returncode=0)
            # worktrees._run_git: push call returns success
            mock_git.return_value = Mock(stdout='', stderr='', returncode=0)

            success, unmerged_files = merge_worktree('incredible_icm-42')

            assert success is True
            assert unmerged_files == []

    def test_merge_worktree_wrong_branch_after_merge(self):
        """Test post-merge validation fails if not on target branch."""
        with patch('pokepoke.worktrees.worktrees.is_worktree_clean', return_value=True), \
             patch('subprocess.run') as mock_run, \
             patch('pokepoke.worktrees.worktrees.get_default_branch', return_value='ameliapayne/dev'), \
             patch('builtins.print') as mock_print:

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
        with patch('pokepoke.worktrees.worktrees.is_worktree_clean', return_value=True), \
             patch('subprocess.run') as mock_run, \
             patch('pokepoke.worktrees.worktrees.get_default_branch', return_value='ameliapayne/dev'), \
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

    def test_merge_worktree_verification_fails_after_push_succeeds(self):
        """Test that merge succeeds with warning when verification fails after successful push."""
        with patch('pokepoke.worktrees.worktrees.is_worktree_clean', return_value=True), \
             patch('subprocess.run') as mock_run, \
             patch('pokepoke.worktrees.worktrees.get_default_branch', return_value='ameliapayne/dev'), \
             patch('pokepoke.worktrees.worktrees.is_worktree_merged') as mock_merged, \
             patch('builtins.print') as mock_print:

            def run_side_effect(*args, **kwargs):
                cmd = args[0]
                if 'branch' in cmd and '--show-current' in cmd:
                    return Mock(stdout='ameliapayne/dev\n', returncode=0)
                elif 'status' in cmd and '--porcelain' in cmd:
                    return Mock(stdout='', returncode=0)
                else:
                    return Mock(stdout='', stderr='', returncode=0)

            mock_run.side_effect = run_side_effect
            # This is the bug scenario: push succeeds but verification fails
            mock_merged.return_value = False

            success, unmerged_files = merge_worktree('incredible_icm-42')

            # After fix: should succeed with warning, not fail
            assert success is True, "Merge should succeed even when verification fails after push"
            assert unmerged_files == []

            # Verify warning message was printed instead of error
            print_calls = [str(call) for call in mock_print.call_args_list]
            assert any('Post-push merge verification failed' in call and 'but push succeeded' in call
                      for call in print_calls), "Should print warning about verification failure"

            # Verify push command was called (confirming push succeeded)
            run_calls = [str(call) for call in mock_run.call_args_list]
            assert any('push' in call for call in run_calls), "Should have attempted git push"

    def test_merge_worktree_push_failure_still_fails(self):
        """Test that merge correctly fails when git push fails."""
        with patch('pokepoke.worktrees.worktrees.is_worktree_clean', return_value=True), \
             patch('subprocess.run') as mock_run, \
             patch('pokepoke.worktrees.worktrees.get_default_branch', return_value='ameliapayne/dev'), \
             patch('builtins.print') as mock_print:

            def run_side_effect(*args, **kwargs):
                cmd = args[0]
                if 'push' in cmd:
                    # Push fails
                    raise subprocess.CalledProcessError(1, cmd, stderr='push failed: network error')
                elif 'branch' in cmd and '--show-current' in cmd:
                    return Mock(stdout='ameliapayne/dev\n', returncode=0)
                elif 'status' in cmd and '--porcelain' in cmd:
                    return Mock(stdout='', returncode=0)
                else:
                    return Mock(stdout='', stderr='', returncode=0)

            mock_run.side_effect = run_side_effect

            success, unmerged_files = merge_worktree('incredible_icm-42')

            # Push failure should still cause overall failure
            assert success is False, "Merge should fail when push fails"
            assert unmerged_files == []

            # Verify push failure message was printed
            print_calls = [str(call) for call in mock_print.call_args_list]
            assert any('Push failed' in call for call in print_calls), "Should print push failure message"

    def test_merge_worktree_subprocess_error(self):
        """Test merge fails on subprocess error."""
        with patch('pokepoke.worktrees.worktrees.is_worktree_clean', return_value=True), \
             patch('subprocess.run') as mock_run, \
             patch('pokepoke.worktrees.worktrees.get_default_branch', return_value='ameliapayne/dev'), \
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


@pytest.mark.allow_real_bd
class TestCleanupWorktree:
    """Tests for cleanup_worktree function."""

    def test_cleanup_worktree_success(self):
        """Test successful worktree cleanup."""
        exists_state = {'present': True}

        def exists_side_effect(self: Path) -> bool:
            normalized = str(self).replace('\\', '/')
            if normalized.endswith('worktrees/task-incredible_icm-42'):
                return exists_state['present']
            return True

        with patch('subprocess.run') as mock_run, \
             patch('pokepoke.worktrees.worktrees.list_worktrees') as mock_list, \
             patch('pokepoke.worktrees.worktree_cleanup.remove_from_manifest') as mock_rm_manifest, \
             patch('pathlib.Path.exists', new=exists_side_effect):

            mock_list.return_value = [
                {'path': 'worktrees/task-incredible_icm-42', 'branch': 'refs/heads/task/incredible_icm-42'}
            ]

            def run_side_effect(*args, **kwargs):
                cmd = args[0]
                if cmd[0:3] == ['git', 'worktree', 'remove']:
                    exists_state['present'] = False
                return Mock(returncode=0, stderr='', stdout='')

            mock_run.side_effect = run_side_effect

            result = cleanup_worktree('incredible_icm-42')

            assert result is True
            mock_rm_manifest.assert_called_once_with('incredible_icm-42')
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
        exists_state = {'present': True}

        def exists_side_effect(self: Path) -> bool:
            normalized = str(self).replace('\\', '/')
            if normalized.endswith('worktrees/task-incredible_icm-42'):
                return exists_state['present']
            return True

        with patch('subprocess.run') as mock_run, \
             patch('pokepoke.worktrees.worktrees.list_worktrees') as mock_list, \
             patch('pokepoke.worktrees.worktree_cleanup.remove_from_manifest') as mock_rm_manifest, \
             patch('pathlib.Path.exists', new=exists_side_effect):

            mock_list.return_value = [
                {'path': 'worktrees/task-incredible_icm-42', 'branch': 'refs/heads/task/incredible_icm-42'}
            ]

            def run_side_effect(*args, **kwargs):
                cmd = args[0]
                if cmd[0:3] == ['git', 'worktree', 'remove']:
                    exists_state['present'] = False
                return Mock(returncode=0, stderr='', stdout='')

            mock_run.side_effect = run_side_effect

            result = cleanup_worktree('incredible_icm-42', force=True)

            assert result is True
            mock_rm_manifest.assert_called_once_with('incredible_icm-42')

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
             patch('pokepoke.worktrees.worktrees.list_worktrees', return_value=[]), \
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
        exists_state = {'present': True}

        def exists_side_effect(self: Path) -> bool:
            normalized = str(self).replace('\\', '/')
            if normalized.endswith('worktrees/task-incredible_icm-42'):
                return exists_state['present']
            return True

        with patch('subprocess.run') as mock_run, \
             patch('pokepoke.worktrees.worktrees.list_worktrees') as mock_list, \
             patch('pathlib.Path.exists', new=exists_side_effect), \
             patch('builtins.print') as mock_print:

            mock_list.return_value = [
                {'path': 'worktrees/task-incredible_icm-42', 'branch': 'refs/heads/task/incredible_icm-42'}
            ]

            # Worktree removal succeeds
            def run_side_effect(*args, **kwargs):
                cmd = args[0]
                if 'worktree' in cmd and 'remove' in cmd:
                    exists_state['present'] = False
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
        exists_state = {'present': True}

        def exists_side_effect(self: Path) -> bool:
            normalized = str(self).replace('\\', '/')
            if normalized.endswith('worktrees/task-incredible_icm-42'):
                return exists_state['present']
            return True

        def force_side_effect(*args, **kwargs):
            exists_state['present'] = False
            return True

        with patch('subprocess.run') as mock_run, \
             patch('pokepoke.worktrees.worktrees.list_worktrees') as mock_list, \
             patch('pathlib.Path.exists', new=exists_side_effect), \
             patch('pokepoke.worktrees.worktree_cleanup.force_remove_directory', side_effect=force_side_effect) as mock_force, \
             patch('pokepoke.worktrees.worktree_cleanup.remove_from_manifest'), \
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

    def test_cleanup_worktree_invalid_argument_does_not_force_remove(self):
        """Test that 'invalid argument' still triggers force_remove_directory.

        Even non-lock errors now attempt force removal so that transient
        failures (e.g. directory-not-empty from a locked inner file) aren't
        silently skipped.  The error is NOT classified as a lock error, but
        the retry still fires.
        """
        def exists_side_effect(self: Path) -> bool:
            normalized = str(self).replace('\\', '/')
            if normalized.endswith('worktrees/task-incredible_icm-42'):
                return True
            return True

        with patch('subprocess.run') as mock_run, \
             patch('pokepoke.worktrees.worktrees.list_worktrees') as mock_list, \
             patch('pathlib.Path.exists', new=exists_side_effect), \
             patch('pokepoke.worktrees.worktree_cleanup.force_remove_directory', return_value=False) as mock_force, \
             patch('pokepoke.worktrees.worktree_cleanup.add_uncleaned_worktree') as mock_add_uncleaned, \
             patch('builtins.print'):

            mock_list.return_value = [
                {'path': 'worktrees/task-incredible_icm-42', 'branch': 'refs/heads/task/incredible_icm-42'}
            ]

            def run_side_effect(*args, **kwargs):
                cmd = args[0]
                if 'worktree' in cmd and 'remove' in cmd:
                    raise subprocess.CalledProcessError(
                        1, cmd,
                        stderr="error: failed to delete 'worktrees/task-xyz': Invalid argument"
                    )
                return Mock(returncode=0, stderr='', stdout='')

            mock_run.side_effect = run_side_effect

            result = cleanup_worktree('incredible_icm-42')

            assert result is False
            mock_force.assert_called_once()
            mock_add_uncleaned.assert_called_once()

    def test_cleanup_worktree_being_used_by_another_process(self):
        """Test that 'being used by another process' triggers force removal."""
        def exists_side_effect(self: Path) -> bool:
            normalized = str(self).replace('\\', '/')
            if normalized.endswith('worktrees/task-incredible_icm-42'):
                return True
            return True

        with patch('subprocess.run') as mock_run, \
             patch('pokepoke.worktrees.worktrees.list_worktrees') as mock_list, \
             patch('pathlib.Path.exists', new=exists_side_effect), \
             patch('pokepoke.worktrees.worktree_cleanup.force_remove_directory', return_value=False) as mock_force, \
             patch('pokepoke.worktrees.worktree_cleanup.add_uncleaned_worktree') as mock_manifest, \
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

            assert result is False
            mock_force.assert_called_once()
            mock_manifest.assert_called_once()
            assert mock_run.call_count == 1
            print_calls = [str(c) for c in mock_print.call_args_list]
            assert any('Could not remove worktree directory after retries' in c for c in print_calls)


@pytest.mark.allow_real_bd
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
        """Test fallback to _safe_rmtree when git worktree remove --force fails."""
        with patch('subprocess.run') as mock_run, \
             patch('pokepoke.worktrees.worktree_cleanup._safe_rmtree') as mock_safe_rmtree:

            def run_side_effect(*args, **kwargs):
                cmd = args[0]
                if 'prune' in cmd:
                    return Mock(returncode=0, stderr='', stdout='')
                raise subprocess.CalledProcessError(1, cmd, stderr='failed')

            mock_run.side_effect = run_side_effect
            mock_safe_rmtree.return_value = None

            result = force_remove_directory(Path("worktrees/task-test"), repo_root=Path("."))

            assert result is True
            mock_safe_rmtree.assert_called_once()

    def test_force_remove_retries_on_permission_error(self):
        """Test retry logic when both git and _safe_rmtree fail."""
        with patch('subprocess.run') as mock_run, \
             patch('pokepoke.worktrees.worktree_cleanup._safe_rmtree') as mock_safe_rmtree, \
             patch('time.sleep') as mock_sleep, \
             patch('pokepoke.utils.process_utils.wait_for_process_cleanup'):

            def run_side_effect(*args, **kwargs):
                cmd = args[0]
                if 'prune' in cmd:
                    return Mock(returncode=0, stderr='', stdout='')
                raise subprocess.CalledProcessError(1, cmd, stderr='failed')

            mock_run.side_effect = run_side_effect
            # Fail twice, succeed on third attempt
            mock_safe_rmtree.side_effect = [PermissionError("locked"), PermissionError("locked"), None]

            result = force_remove_directory(Path("worktrees/task-test"), repo_root=Path("."))

            assert result is True
            assert mock_sleep.call_count == 2

    def test_force_remove_returns_false_after_all_retries_exhausted(self):
        """Test that False is returned when all retries are exhausted."""
        with patch('subprocess.run') as mock_run, \
             patch('pokepoke.worktrees.worktree_cleanup._safe_rmtree') as mock_safe_rmtree, \
             patch('time.sleep'):

            def run_side_effect(*args, **kwargs):
                cmd = args[0]
                if 'prune' in cmd:
                    return Mock(returncode=0, stderr='', stdout='')
                raise subprocess.CalledProcessError(1, cmd, stderr='failed')

            mock_run.side_effect = run_side_effect
            mock_safe_rmtree.side_effect = PermissionError("locked")

            result = force_remove_directory(Path("worktrees/task-test"), repo_root=Path("."))

            assert result is False



@pytest.mark.allow_real_bd
class TestWorktreeManifest:
    """Tests for worktree cleanup manifest helpers."""

    def test_load_manifest_returns_empty_for_missing_file(self, tmp_path: Path) -> None:
        """Missing manifest file should return empty dict."""
        manifest_path = tmp_path / "uncleaned_worktrees.json"
        with patch(
            "pokepoke.worktrees.worktree_cleanup.get_worktree_manifest_path",
            return_value=manifest_path,
        ):
            assert load_worktree_manifest() == {}

    def test_load_manifest_returns_empty_for_non_dict(self, tmp_path: Path) -> None:
        """Non-dict manifest data should be treated as empty."""
        manifest_path = tmp_path / "uncleaned_worktrees.json"
        manifest_path.write_text(json.dumps(["not", "a", "dict"]), encoding="utf-8")
        with patch(
            "pokepoke.worktrees.worktree_cleanup.get_worktree_manifest_path",
            return_value=manifest_path,
        ):
            assert load_worktree_manifest() == {}

    def test_add_and_remove_manifest_entry(self, tmp_path: Path) -> None:
        """Add/remove should update manifest on disk."""
        manifest_path = tmp_path / "uncleaned_worktrees.json"
        with patch(
            "pokepoke.worktrees.worktree_cleanup.get_worktree_manifest_path",
            return_value=manifest_path,
        ):
            add_uncleaned_worktree("task-1", "worktrees/task-1", "reason")
            data = load_worktree_manifest()
            assert data["task-1"]["path"] == "worktrees/task-1"
            remove_from_manifest("task-1")
            assert load_worktree_manifest() == {}

    def test_save_manifest_writes_data(self, tmp_path: Path) -> None:
        """save_worktree_manifest should persist JSON."""
        manifest_path = tmp_path / "uncleaned_worktrees.json"
        manifest = {
            "task-2": {
                "path": "worktrees/task-2",
                "reason": "cleanup",
                "timestamp": "2026-02-14T00:00:00",
            }
        }
        with patch(
            "pokepoke.worktrees.worktree_cleanup.get_worktree_manifest_path",
            return_value=manifest_path,
        ):
            save_worktree_manifest(manifest)
            raw = json.loads(manifest_path.read_text(encoding="utf-8"))
            assert raw["task-2"]["reason"] == "cleanup"

    def test_save_manifest_logs_oserror(self, tmp_path: Path, caplog) -> None:
        """save_worktree_manifest should log OSError instead of silently failing."""
        import logging
        manifest_path = tmp_path / "nonexistent_dir" / "uncleaned_worktrees.json"
        manifest = {
            "task-3": {
                "path": "worktrees/task-3",
                "reason": "test",
                "timestamp": "2026-02-14T00:00:00",
            }
        }

        # Make parent.mkdir() raise OSError
        with patch(
            "pokepoke.worktrees.worktree_cleanup.get_worktree_manifest_path",
            return_value=manifest_path,
        ), patch("pathlib.Path.mkdir", side_effect=OSError("Permission denied")), \
           caplog.at_level(logging.WARNING):
            save_worktree_manifest(manifest)

            # Verify warning was logged (message comes from manifest_utils)
            assert "Failed to save manifest" in caplog.text
            assert "Permission denied" in caplog.text
            assert "worktrees/task-3" in caplog.text
            assert "may become orphaned" in caplog.text



@pytest.mark.allow_real_bd
class TestCleanupAfterMergePermissionDenied:
    """Tests for cleanup_after_merge with permission denied errors."""

    def test_cleanup_after_merge_permission_denied_force_removes(self):
        """Test that permission denied in cleanup_after_merge triggers force removal."""
        from pokepoke.worktrees.worktree_cleanup import cleanup_after_merge

        with patch('subprocess.run') as mock_run, \
             patch('pathlib.Path.exists', return_value=True), \
             patch('pokepoke.worktrees.worktree_cleanup.force_remove_directory', return_value=True) as mock_force, \
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

            cleanup_after_merge(Path("worktrees/task-test"), "task/test-branch")

            mock_force.assert_called_once()
            print_calls = [str(c) for c in mock_print.call_args_list]
            assert any('Force-removed worktree' in c for c in print_calls)

    def test_cleanup_after_merge_permission_denied_force_fails(self):
        """Test fallback message when force removal also fails."""
        from pokepoke.worktrees.worktree_cleanup import cleanup_after_merge

        with patch('subprocess.run') as mock_run, \
             patch('pathlib.Path.exists', return_value=True), \
             patch('pokepoke.worktrees.worktree_cleanup.force_remove_directory', return_value=False) as mock_force, \
             patch('pokepoke.worktrees.worktree_cleanup.add_uncleaned_worktree') as mock_manifest, \
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

            cleanup_after_merge(Path("worktrees/task-test"), "task/test-branch")

            mock_force.assert_called_once()
            mock_manifest.assert_called_once()
            print_calls = [str(c) for c in mock_print.call_args_list]
            assert any('Could not remove worktree after retries' in c for c in print_calls)
            assert any('Merge successful' in c for c in print_calls)


@pytest.mark.allow_real_bd
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
                encoding='utf-8',
                errors='replace',
                timeout=30,
                cwd=None,
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


@pytest.mark.allow_real_bd
class TestIsWindowsLockError:
    """Tests for _is_windows_lock_error."""

    def test_empty_string_returns_false(self) -> None:
        assert _is_windows_lock_error("") is False

    def test_permission_denied(self) -> None:
        assert _is_windows_lock_error("Permission denied") is False

    def test_access_is_denied(self) -> None:
        assert _is_windows_lock_error("Access is denied") is False

    def test_unrelated_error_returns_false(self) -> None:
        assert _is_windows_lock_error("File not found") is False


@pytest.mark.allow_real_bd
class TestRetryFailedCleanups:
    """Tests for retry_failed_cleanups."""

    def test_empty_manifest_returns_zero(self, tmp_path: Path) -> None:
        manifest_path = tmp_path / "uncleaned_worktrees.json"
        with patch(
            "pokepoke.worktrees.worktree_cleanup.get_worktree_manifest_path",
            return_value=manifest_path,
        ):
            assert retry_failed_cleanups() == 0

    def test_directory_already_removed(self, tmp_path: Path) -> None:
        """Worktree dir no longer exists - should count as cleaned."""
        manifest_path = tmp_path / "uncleaned_worktrees.json"
        manifest = {
            "task-gone": {
                "path": str(tmp_path / "nonexistent"),
                "reason": "failed",
                "timestamp": "2026-01-01T00:00:00",
            }
        }
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

        with patch(
            "pokepoke.worktrees.worktree_cleanup.get_worktree_manifest_path",
            return_value=manifest_path,
        ):
            result = retry_failed_cleanups()
            assert result == 1
            assert load_worktree_manifest() == {}

    def test_force_remove_succeeds(self, tmp_path: Path) -> None:
        """force_remove_directory succeeds on retry."""
        manifest_path = tmp_path / "uncleaned_worktrees.json"
        wt_dir = tmp_path / "wt"
        wt_dir.mkdir()
        manifest = {
            "task-retry": {
                "path": str(wt_dir),
                "reason": "locked",
                "timestamp": "2026-01-01T00:00:00",
            }
        }
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

        with patch(
            "pokepoke.worktrees.worktree_cleanup.get_worktree_manifest_path",
            return_value=manifest_path,
        ), patch(
            "pokepoke.worktrees.worktree_cleanup.force_remove_directory",
            return_value=True,
        ):
            result = retry_failed_cleanups()
            assert result == 1

    def test_force_remove_fails(self, tmp_path: Path) -> None:
        """force_remove_directory fails - count stays zero."""
        manifest_path = tmp_path / "uncleaned_worktrees.json"
        wt_dir = tmp_path / "wt"
        wt_dir.mkdir()
        manifest = {
            "task-stuck": {
                "path": str(wt_dir),
                "reason": "locked",
                "timestamp": "2026-01-01T00:00:00",
            }
        }
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

        with patch(
            "pokepoke.worktrees.worktree_cleanup.get_worktree_manifest_path",
            return_value=manifest_path,
        ), patch(
            "pokepoke.worktrees.worktree_cleanup.force_remove_directory",
            return_value=False,
        ):
            result = retry_failed_cleanups()
            assert result == 0


@pytest.mark.allow_real_bd
class TestGetUncleanedWorktreeCount:
    """Tests for get_uncleaned_worktree_count."""

    def test_returns_zero_for_empty_manifest(self, tmp_path: Path) -> None:
        manifest_path = tmp_path / "uncleaned_worktrees.json"
        with patch(
            "pokepoke.worktrees.worktree_cleanup.get_worktree_manifest_path",
            return_value=manifest_path,
        ):
            assert get_uncleaned_worktree_count() == 0

    def test_returns_count(self, tmp_path: Path) -> None:
        manifest_path = tmp_path / "uncleaned_worktrees.json"
        manifest = {
            "a": {"path": "a", "reason": "r", "timestamp": "t"},
            "b": {"path": "b", "reason": "r", "timestamp": "t"},
        }
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        with patch(
            "pokepoke.worktrees.worktree_cleanup.get_worktree_manifest_path",
            return_value=manifest_path,
        ):
            assert get_uncleaned_worktree_count() == 2


@pytest.mark.allow_real_bd
class TestLoadManifestCorrupt:
    """Test load_worktree_manifest with corrupt JSON."""

    def test_corrupt_json_returns_empty(self, tmp_path: Path) -> None:
        manifest_path = tmp_path / "uncleaned_worktrees.json"
        manifest_path.write_text("{invalid json", encoding="utf-8")
        with patch(
            "pokepoke.worktrees.worktree_cleanup.get_worktree_manifest_path",
            return_value=manifest_path,
        ):
            assert load_worktree_manifest() == {}


@pytest.mark.allow_real_bd
class TestCleanupAfterMergeNonLockError:
    """Test cleanup_after_merge with non-lock errors."""

    def test_non_lock_error_adds_to_manifest(self) -> None:
        """Non-lock CalledProcessError should attempt force removal, then add to manifest on failure."""
        from pokepoke.worktrees.worktree_cleanup import cleanup_after_merge

        with patch('subprocess.run') as mock_run, \
             patch('pathlib.Path.exists', return_value=True), \
             patch('pokepoke.worktrees.worktree_cleanup.force_remove_directory', return_value=False) as mock_force, \
             patch('pokepoke.worktrees.worktree_cleanup.add_uncleaned_worktree') as mock_add:

            def run_side_effect(*args, **kwargs):
                cmd = args[0]
                if 'worktree' in cmd and 'remove' in cmd:
                    raise subprocess.CalledProcessError(1, cmd, stderr="fatal: some other error")
                return Mock(returncode=0, stderr='', stdout='')

            mock_run.side_effect = run_side_effect

            cleanup_after_merge(Path("worktrees/task-x"), "task/x-branch")

            mock_force.assert_called_once()
            mock_add.assert_called_once()
            call_args = mock_add.call_args
            assert call_args[0][0] == "x-branch"


@pytest.mark.allow_real_bd
class TestForceRemoveTimeoutBranch:
    """Test force_remove_directory timeout handling."""

    def test_git_worktree_remove_timeout(self) -> None:
        """TimeoutExpired during git worktree remove should be handled."""
        with patch('subprocess.run') as mock_run, \
             patch('pokepoke.worktrees.worktree_cleanup._safe_rmtree') as mock_safe_rmtree, \
             patch('pokepoke.utils.process_utils.wait_for_process_cleanup'), \
             patch('time.sleep'), \
             patch('pokepoke.worktrees.worktree_cleanup._validate_within_worktrees_dir'):

            # First call (git worktree remove) times out, second call (rmtree fallback prune) succeeds
            mock_run.side_effect = [
                subprocess.TimeoutExpired("git", 30),
                Mock(returncode=0),  # git worktree prune
            ]
            mock_safe_rmtree.return_value = None

            result = force_remove_directory(Path("/fake/path"), repo_root=Path("/"))
            assert result is True

    def test_lock_error_on_direct_removal(self) -> None:
        """Windows lock error on _safe_rmtree should be reported."""
        with patch('subprocess.run') as mock_run, \
             patch('pokepoke.worktrees.worktree_cleanup._safe_rmtree') as mock_safe_rmtree, \
             patch('pokepoke.utils.process_utils.wait_for_process_cleanup'), \
             patch('time.sleep'), \
             patch('pokepoke.worktrees.worktree_cleanup._CLEANUP_MAX_RETRIES', 1), \
             patch('pokepoke.worktrees.worktree_cleanup._validate_within_worktrees_dir'):

            mock_run.side_effect = subprocess.CalledProcessError(1, "git", stderr="other error")
            mock_safe_rmtree.side_effect = PermissionError("Access is denied")

            result = force_remove_directory(Path("/fake/path"), repo_root=Path("/"))
            assert result is False


@pytest.mark.allow_real_bd
class TestCreateWorktreeLockAndEdgeCases:
    """Tests for create_worktree lock contention and edge cases."""

    def test_create_worktree_lock_wait_logging(self):
        """Test that long lock wait times are logged (line 78)."""
        import time as _time

        call_count = [0]
        original_time = _time.time

        def fake_time():
            call_count[0] += 1
            # Make lock_start = 0, then lock_wait = 1.0 (> 0.1)
            if call_count[0] == 1:
                return 0.0  # lock_start
            elif call_count[0] == 2:
                return 1.0  # after lock acquired
            return original_time()

        with patch('subprocess.run') as mock_run, \
             patch('pokepoke.worktrees.worktrees.list_worktrees') as mock_list, \
             patch('pokepoke.worktrees.worktrees.get_default_branch', return_value='main'), \
             patch('pathlib.Path.mkdir'), \
             patch('pokepoke.worktrees.worktrees.time.time', side_effect=fake_time), \
             patch('pokepoke.worktrees.worktrees._validate_worktree_integrity'):

            mock_list.side_effect = [
                [],  # First check (before lock)
                [],  # Double-check (inside lock)
            ]
            mock_run.return_value = Mock(returncode=0, stderr='', stdout='')

            result = create_worktree('test-item')
            assert result == Path('worktrees/task-test-item').resolve()

    def test_create_worktree_race_condition_double_check(self):
        """Test that worktree found during double-check inside lock is reused (lines 83-87)."""
        resolved_path = Path('worktrees/task-test-item').resolve()

        with patch('pokepoke.worktrees.worktrees.list_worktrees') as mock_list, \
             patch('pokepoke.worktrees.worktrees.get_default_branch', return_value='main'), \
             patch('pathlib.Path.mkdir'), \
             patch('builtins.print') as mock_print:

            mock_list.side_effect = [
                [],  # First check outside lock
                [{'path': str(resolved_path), 'branch': 'refs/heads/task/test-item'}],  # Inside lock
            ]

            result = create_worktree('test-item')

            assert result == resolved_path
            assert any('another agent' in str(c) for c in mock_print.call_args_list)

    def test_create_worktree_invalid_base_branch(self):
        """Test error when base branch doesn't exist (lines 123-124)."""
        with patch('subprocess.run') as mock_run, \
             patch('pokepoke.worktrees.worktrees.list_worktrees', return_value=[]), \
             patch('pathlib.Path.mkdir'):

            error = subprocess.CalledProcessError(
                128, ['git'], stderr="fatal: not a valid object name: 'nonexistent'"
            )
            mock_run.side_effect = error

            with pytest.raises(RuntimeError, match="does not exist"):
                create_worktree('test-item', base_branch='nonexistent')

    def test_create_worktree_timeout(self):
        """Test timeout during worktree creation (lines 132-135)."""
        with patch('subprocess.run') as mock_run, \
             patch('pokepoke.worktrees.worktrees.list_worktrees', return_value=[]), \
             patch('pokepoke.worktrees.worktrees.get_default_branch', return_value='main'), \
             patch('pathlib.Path.mkdir'):

            mock_run.side_effect = subprocess.TimeoutExpired('git', 30)

            with pytest.raises(RuntimeError, match="Timed out creating worktree"):
                create_worktree('test-item')

    def test_create_worktree_unexpected_exception(self):
        """Test unexpected exception during worktree creation (lines 140-142)."""
        with patch('pokepoke.worktrees.worktrees.list_worktrees', return_value=[]), \
             patch('pokepoke.worktrees.worktrees.get_default_branch', return_value='main'), \
             patch('pathlib.Path.mkdir'), \
             patch('pokepoke.worktrees.worktrees.with_worktree_lock', side_effect=OSError("disk full")), \
             pytest.raises(RuntimeError, match="Unexpected error creating worktree"):
            create_worktree('test-item')


@pytest.mark.allow_real_bd
class TestMergeWorktreeConflicts:
    """Tests for merge_worktree conflict reporting."""

    def test_merge_worktree_many_unmerged_files(self):
        """Test conflict reporting with >10 unmerged files (lines 192-196)."""

        unmerged = [f"file{i}.py" for i in range(15)]

        with patch('pokepoke.worktrees.worktrees.is_worktree_clean', return_value=True), \
             patch('pokepoke.worktrees.worktrees._sync_and_ensure_clean_main_repo', return_value=True), \
             patch('pokepoke.worktrees.worktree_helpers.sync_and_ensure_clean_main_repo', return_value=True), \
             patch('pokepoke.worktrees.worktrees.execute_merge_sequence', return_value=(False, "conflicts", unmerged)), \
             patch('pokepoke.worktrees.worktrees.get_default_branch', return_value='main'), \
             patch('builtins.print') as mock_print:

            success, files = merge_worktree('test-item')

            assert success is False
            assert len(files) == 15
            print_calls = [str(c) for c in mock_print.call_args_list]
            assert any('15 file(s)' in c for c in print_calls)
            assert any('and 5 more' in c for c in print_calls)


@pytest.mark.allow_real_bd
class TestMergeWorktreeRollback:
    """Tests for merge_worktree rollback on push and validation failures."""

    def test_push_failure_triggers_reset_hard(self):
        """git reset --hard HEAD~1 is called when push fails."""
        reset_called = []

        with patch('pokepoke.worktrees.worktrees.is_worktree_clean', return_value=True), \
             patch('pokepoke.worktrees.worktrees._sync_and_ensure_clean_main_repo', return_value=True), \
             patch('pokepoke.worktrees.worktree_helpers.sync_and_ensure_clean_main_repo', return_value=True), \
             patch('pokepoke.worktrees.worktrees.execute_merge_sequence', return_value=(True, '', [])), \
             patch('pokepoke.worktrees.worktrees.validate_post_merge', return_value=True), \
             patch('pokepoke.worktrees.worktrees.get_default_branch', return_value='main'), \
             patch('pokepoke.worktrees.worktrees._run_git') as mock_run_git, \
             patch('builtins.print'):

            def run_git_side_effect(cmd, **kwargs):
                if 'push' in cmd:
                    raise subprocess.CalledProcessError(1, cmd, stderr='push failed')
                if cmd == ["git", "reset", "--hard", "HEAD~1"]:
                    reset_called.append(True)
                    return Mock(returncode=0)
                return Mock(returncode=0)

            mock_run_git.side_effect = run_git_side_effect

            success, unmerged = merge_worktree('test-item')

            assert success is False
            assert reset_called, "git reset --hard HEAD~1 should have been called on push failure"

    def test_push_failure_reset_failure_does_not_raise(self):
        """If git reset --hard fails after push failure, error is logged but not raised."""
        with patch('pokepoke.worktrees.worktrees.is_worktree_clean', return_value=True), \
             patch('pokepoke.worktrees.worktrees._sync_and_ensure_clean_main_repo', return_value=True), \
             patch('pokepoke.worktrees.worktree_helpers.sync_and_ensure_clean_main_repo', return_value=True), \
             patch('pokepoke.worktrees.worktrees.execute_merge_sequence', return_value=(True, '', [])), \
             patch('pokepoke.worktrees.worktrees.validate_post_merge', return_value=True), \
             patch('pokepoke.worktrees.worktrees.get_default_branch', return_value='main'), \
             patch('pokepoke.worktrees.worktrees._run_git') as mock_run_git, \
             patch('builtins.print'):

            def run_git_side_effect(cmd, **kwargs):
                if 'push' in cmd:
                    raise subprocess.CalledProcessError(1, cmd, stderr='push failed')
                if cmd == ["git", "reset", "--hard", "HEAD~1"]:
                    raise subprocess.CalledProcessError(1, cmd, stderr='reset failed')
                return Mock(returncode=0)

            mock_run_git.side_effect = run_git_side_effect

            # Should not raise, even though both push and reset fail
            success, unmerged = merge_worktree('test-item')
            assert success is False

    def test_post_merge_validation_failure_triggers_reset_hard(self):
        """git reset --hard HEAD~1 is called when post-merge validation fails."""
        reset_called = []

        with patch('pokepoke.worktrees.worktrees.is_worktree_clean', return_value=True), \
             patch('pokepoke.worktrees.worktrees._sync_and_ensure_clean_main_repo', return_value=True), \
             patch('pokepoke.worktrees.worktree_helpers.sync_and_ensure_clean_main_repo', return_value=True), \
             patch('pokepoke.worktrees.worktrees.execute_merge_sequence', return_value=(True, '', [])), \
             patch('pokepoke.worktrees.worktrees.validate_post_merge', return_value=False), \
             patch('pokepoke.worktrees.worktrees.get_default_branch', return_value='main'), \
             patch('pokepoke.worktrees.worktrees._run_git') as mock_run_git, \
             patch('builtins.print'):

            def run_git_side_effect(cmd, **kwargs):
                if cmd == ["git", "reset", "--hard", "HEAD~1"]:
                    reset_called.append(True)
                    return Mock(returncode=0)
                return Mock(returncode=0)

            mock_run_git.side_effect = run_git_side_effect

            success, unmerged = merge_worktree('test-item')

            assert success is False
            assert reset_called, "git reset --hard HEAD~1 should have been called on validation failure"

    def test_post_merge_validation_exception_triggers_reset_hard(self):
        """git reset --hard HEAD~1 is called when validate_post_merge raises."""
        reset_called = []

        with patch('pokepoke.worktrees.worktrees.is_worktree_clean', return_value=True), \
             patch('pokepoke.worktrees.worktrees._sync_and_ensure_clean_main_repo', return_value=True), \
             patch('pokepoke.worktrees.worktree_helpers.sync_and_ensure_clean_main_repo', return_value=True), \
             patch('pokepoke.worktrees.worktrees.execute_merge_sequence', return_value=(True, '', [])), \
             patch('pokepoke.worktrees.worktrees.validate_post_merge', side_effect=subprocess.CalledProcessError(1, 'git', stderr='error')), \
             patch('pokepoke.worktrees.worktrees.get_default_branch', return_value='main'), \
             patch('pokepoke.worktrees.worktrees._run_git') as mock_run_git, \
             patch('builtins.print'):

            def run_git_side_effect(cmd, **kwargs):
                if cmd == ["git", "reset", "--hard", "HEAD~1"]:
                    reset_called.append(True)
                    return Mock(returncode=0)
                return Mock(returncode=0)

            mock_run_git.side_effect = run_git_side_effect

            success, unmerged = merge_worktree('test-item')

            assert success is False
            assert reset_called, "git reset --hard HEAD~1 should have been called on validation exception"


@pytest.mark.allow_real_bd
class TestCleanupWorktreeEdgeCases:
    """Tests for cleanup_worktree edge cases."""

    def test_cleanup_worktree_found_by_expected_path(self):
        """Test worktree found by expected path not by branch (line 256)."""
        def exists_side_effect(self: Path) -> bool:
            normalized = str(self).replace('\\', '/')
            if 'task-test-item' in normalized:
                return True
            return False

        with patch('pokepoke.worktrees.worktrees.list_worktrees', return_value=[]), \
             patch('subprocess.run') as mock_run, \
             patch('pathlib.Path.exists', new=exists_side_effect), \
             patch('pokepoke.worktrees.worktree_cleanup.remove_from_manifest'):

            exists_state = {'present': True}

            def run_and_remove(*args, **kwargs):
                cmd = args[0]
                if 'worktree' in cmd and 'remove' in cmd:
                    exists_state['present'] = False
                    # Now make exists return False for the worktree path
                    return Mock(returncode=0, stderr='', stdout='')
                return Mock(returncode=0, stderr='', stdout='')

            # Override the exists side effect to use state
            def stateful_exists(self: Path) -> bool:
                normalized = str(self).replace('\\', '/')
                if 'task-test-item' in normalized:
                    return exists_state['present']
                return False

            with patch('pathlib.Path.exists', new=stateful_exists):
                mock_run.side_effect = run_and_remove
                result = cleanup_worktree('test-item')

            assert result is True

    def test_cleanup_worktree_found_by_unsanitized_path(self):
        """Test backwards-compatible unsanitized path lookup (line 262)."""
        exists_state = {'present': True}

        def exists_side_effect(self: Path) -> bool:
            normalized = str(self).replace('\\', '/')
            # The unsanitized path for item "c#-item" is task-c#-item
            if 'task-c-item' in normalized:
                return False  # sanitized path doesn't exist
            if 'task-c#-item' in normalized:
                return exists_state['present']
            return False

        with patch('pokepoke.worktrees.worktrees.list_worktrees', return_value=[]), \
             patch('subprocess.run') as mock_run, \
             patch('pathlib.Path.exists', new=exists_side_effect), \
             patch('pokepoke.worktrees.worktree_cleanup.remove_from_manifest'):

            def run_and_remove(*args, **kwargs):
                cmd = args[0]
                if 'worktree' in cmd and 'remove' in cmd:
                    exists_state['present'] = False
                    return Mock(returncode=0, stderr='', stdout='')
                return Mock(returncode=0, stderr='', stdout='')

            mock_run.side_effect = run_and_remove

            result = cleanup_worktree('c#-item')
            assert result is True

    def test_cleanup_worktree_not_a_working_tree_error(self):
        """Test 'not a working tree' error is silently handled (line 280)."""
        exists_state = {'present': True}

        def exists_side_effect(self: Path) -> bool:
            normalized = str(self).replace('\\', '/')
            if 'task-test-item' in normalized:
                return exists_state['present']
            return True

        with patch('subprocess.run') as mock_run, \
             patch('pokepoke.worktrees.worktrees.list_worktrees') as mock_list, \
             patch('pathlib.Path.exists', new=exists_side_effect), \
             patch('pokepoke.worktrees.worktree_cleanup.remove_from_manifest'):

            mock_list.return_value = [
                {'path': 'worktrees/task-test-item', 'branch': 'refs/heads/task/test-item'}
            ]

            def run_side_effect(*args, **kwargs):
                cmd = args[0]
                if 'worktree' in cmd and 'remove' in cmd:
                    exists_state['present'] = False
                    raise subprocess.CalledProcessError(
                        1, cmd, stderr="fatal: 'worktrees/task-test-item' is not a working tree"
                    )
                return Mock(returncode=0, stderr='', stdout='')

            mock_run.side_effect = run_side_effect

            result = cleanup_worktree('test-item')
            assert result is True

    def test_cleanup_worktree_other_removal_error_with_existing_dir(self):
        """Test other removal error triggers force removal and adds to manifest when dir still exists."""
        with patch('subprocess.run') as mock_run, \
             patch('pokepoke.worktrees.worktrees.list_worktrees') as mock_list, \
             patch('pathlib.Path.exists', return_value=True), \
             patch('pokepoke.worktrees.worktree_cleanup.force_remove_directory', return_value=False) as mock_force, \
             patch('pokepoke.worktrees.worktree_cleanup.add_uncleaned_worktree') as mock_add, \
             patch('builtins.print'):

            mock_list.return_value = [
                {'path': 'worktrees/task-test-item', 'branch': 'refs/heads/task/test-item'}
            ]

            mock_run.side_effect = subprocess.CalledProcessError(
                1, ['git'], stderr="fatal: unexpected internal error"
            )

            result = cleanup_worktree('test-item')

            # Should return False because dir still exists after error
            assert result is False
            mock_force.assert_called_once()
            mock_add.assert_called_once()
            assert 'test-item' in mock_add.call_args[0][0]


@pytest.mark.allow_real_bd
class TestSyncAndEnsureCleanMainRepo:
    """Tests for _sync_and_ensure_clean_main_repo edge cases."""

    def test_bd_sync_timeout(self):
        """Test bd sync timeout is handled gracefully (lines 361-362)."""
        from pokepoke.worktrees.worktrees import _sync_and_ensure_clean_main_repo

        with patch('pokepoke.worktrees.worktree_helpers.run_bd_sync_with_retry', side_effect=subprocess.TimeoutExpired('bd', 30)), \
             patch('pokepoke.worktrees.worktree_helpers.subprocess.run') as mock_run, \
             patch('builtins.print') as mock_print:

            mock_run.return_value = Mock(stdout='', returncode=0)

            result = _sync_and_ensure_clean_main_repo('task/test-branch')

            assert result is True
            assert any('bd sync timed out' in str(c) for c in mock_print.call_args_list)

    def test_many_other_changes(self):
        """Test reporting when >10 non-beads changes exist - tries commit, blocks if it fails."""
        from pokepoke.worktrees.worktrees import _sync_and_ensure_clean_main_repo

        lines = '\n'.join(f' M src/file{i}.py' for i in range(15))

        with patch('pokepoke.worktrees.worktree_helpers.run_bd_sync_with_retry') as mock_sync, \
             patch('pokepoke.worktrees.worktree_helpers.subprocess.run') as mock_run, \
             patch('pokepoke.worktrees.worktree_helpers.commit_all_changes', return_value=(False, 'hooks failed')) as mock_commit, \
             patch('builtins.print') as mock_print:

            mock_sync.return_value = Mock(returncode=0)
            mock_run.return_value = Mock(stdout=lines, returncode=0)

            result = _sync_and_ensure_clean_main_repo('task/test-branch')

            assert result is False
            mock_commit.assert_called_once()
            # Verify tracked_only=True is passed for main repo safety
            assert mock_commit.call_args == unittest.mock.call(
                'chore: commit pending changes before merge of task/test-branch',
                cwd=None, tracked_only=True,
            )
            print_calls = [str(c) for c in mock_print.call_args_list]
            assert any('and 5 more' in c for c in print_calls)

    def test_worktree_changes_committed(self):
        """Test worktree cleanup changes are auto-committed (lines 389-392)."""
        from pokepoke.worktrees.worktrees import _sync_and_ensure_clean_main_repo

        with patch('pokepoke.worktrees.worktree_helpers.run_bd_sync_with_retry') as mock_sync, \
             patch('pokepoke.worktrees.worktree_helpers.subprocess.run') as mock_run, \
             patch('builtins.print') as mock_print:

            mock_sync.return_value = Mock(returncode=0)
            mock_run.side_effect = [
                Mock(stdout=' D worktrees/task-old/.git\n', returncode=0),  # status
                Mock(stdout='', returncode=0),  # git add worktrees/
                Mock(stdout='', returncode=0),  # git commit
            ]

            result = _sync_and_ensure_clean_main_repo('task/test-branch')

            assert result is True
            print_calls = [str(c) for c in mock_print.call_args_list]
            assert any('Committing worktree cleanup' in c for c in print_calls)

    def test_main_repo_check_fails(self):
        """Test CalledProcessError during main repo check (lines 395-397)."""
        from pokepoke.worktrees.worktrees import _sync_and_ensure_clean_main_repo

        with patch('pokepoke.worktrees.worktree_helpers.run_bd_sync_with_retry') as mock_sync, \
             patch('pokepoke.worktrees.worktree_helpers.subprocess.run', side_effect=subprocess.CalledProcessError(1, ['git'])), \
             patch('builtins.print') as mock_print:

            mock_sync.return_value = Mock(returncode=0)

            result = _sync_and_ensure_clean_main_repo('task/test-branch')

            assert result is False
            print_calls = [str(c) for c in mock_print.call_args_list]
            assert any('Failed to check/clean main repo' in c for c in print_calls)


# ── Worktree Integrity Validation ────────────────────────────────────────────


@pytest.mark.allow_real_bd
class TestValidateWorktreeIntegrity:
    """Tests for _validate_worktree_integrity post-creation check."""

    def test_nonexistent_directory_raises(self, tmp_path: Path) -> None:
        """Raises RuntimeError if worktree directory doesn't exist."""
        from pokepoke.worktrees.worktrees import _validate_worktree_integrity

        fake_path = tmp_path / "nonexistent"
        with pytest.raises(RuntimeError, match="does not exist"):
            _validate_worktree_integrity(fake_path, "test-item")

    def test_empty_directory_raises(self, tmp_path: Path) -> None:
        """Raises RuntimeError if worktree directory is empty (0 files)."""
        from pokepoke.worktrees.worktrees import _validate_worktree_integrity

        empty_dir = tmp_path / "empty-worktree"
        empty_dir.mkdir()
        with pytest.raises(RuntimeError, match="empty.*0 files"):
            _validate_worktree_integrity(empty_dir, "test-item")

    def test_valid_directory_passes(self, tmp_path: Path) -> None:
        """Non-empty directory with valid git checkout passes."""
        from pokepoke.worktrees.worktrees import _validate_worktree_integrity

        wt_dir = tmp_path / "good-worktree"
        wt_dir.mkdir()
        (wt_dir / "file.txt").touch()

        # Mock subprocess.run to simulate git rev-parse returning "true"
        with patch("pokepoke.worktrees.worktrees.subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=0, stdout="true\n", stderr="")
            _validate_worktree_integrity(wt_dir, "test-item")

        mock_run.assert_called_once()

    def test_git_not_work_tree_raises(self, tmp_path: Path) -> None:
        """Raises RuntimeError if git doesn't recognize directory as work tree."""
        from pokepoke.worktrees.worktrees import _validate_worktree_integrity

        wt_dir = tmp_path / "bad-worktree"
        wt_dir.mkdir()
        (wt_dir / "file.txt").touch()

        with patch("pokepoke.worktrees.worktrees.subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=128, stdout="", stderr="fatal: not a git repo")
            with pytest.raises(RuntimeError, match="not recognized by git"):
                _validate_worktree_integrity(wt_dir, "test-item")

    def test_git_timeout_raises(self, tmp_path: Path) -> None:
        """Raises RuntimeError if git rev-parse times out."""
        from pokepoke.worktrees.worktrees import _validate_worktree_integrity

        wt_dir = tmp_path / "slow-worktree"
        wt_dir.mkdir()
        (wt_dir / "file.txt").touch()

        with patch("pokepoke.worktrees.worktrees.subprocess.run", side_effect=subprocess.TimeoutExpired("git", 10)), \
             pytest.raises(RuntimeError, match="timed out"):
            _validate_worktree_integrity(wt_dir, "test-item")


@pytest.mark.allow_real_bd
class TestCreateWorktreeStaleBranchCleanup:
    """Tests for stale branch cleanup during worktree creation."""

    @patch("pokepoke.worktrees.worktrees._validate_worktree_integrity")
    @patch("pokepoke.worktrees.worktrees.with_worktree_lock")
    @patch("pokepoke.worktrees.worktrees.list_worktrees", return_value=[])
    @patch("pokepoke.worktrees.worktrees._run_git")
    @patch("pokepoke.worktrees.worktrees.get_default_branch", return_value="main")
    def test_stale_branch_deleted_and_retried(
        self, mock_default, mock_git, mock_list, mock_lock, mock_validate,
    ) -> None:
        """When 'already exists' error occurs with no matching worktree, branch is deleted and retried."""
        error = subprocess.CalledProcessError(128, "git")
        error.stderr = "fatal: a branch named 'task/test-123' already exists"

        # First call fails (worktree add), second deletes branch (git branch -D), third succeeds (retry worktree add)
        mock_git.side_effect = [error, None, None]

        create_worktree("test-123")

        # Verify git branch -D was called
        delete_call = mock_git.call_args_list[1]
        assert "branch" in delete_call[0][0]
        assert "-D" in delete_call[0][0]

    @patch("pokepoke.worktrees.worktrees.with_worktree_lock")
    @patch("pokepoke.worktrees.worktrees.list_worktrees")
    @patch("pokepoke.worktrees.worktrees._run_git")
    @patch("pokepoke.worktrees.worktrees.get_default_branch", return_value="main")
    def test_existing_worktree_reused_when_branch_exists(
        self, mock_default, mock_git, mock_list, mock_lock,
    ) -> None:
        """When branch already exists and a worktree uses it, the existing worktree path is returned."""
        error = subprocess.CalledProcessError(128, "git")
        error.stderr = "fatal: a branch named 'task/test-456' already exists"
        mock_git.side_effect = [error]

        # First call returns [] (pre-lock check), second call returns the matching worktree (inside lock)
        mock_list.side_effect = [
            [],  # pre-lock check
            [],  # double-check inside lock
            [{"path": "/repo/worktrees/task-test-456", "branch": "refs/heads/task/test-456"}],  # error recovery
        ]

        result = create_worktree("test-456")
        assert result == Path("/repo/worktrees/task-test-456")
