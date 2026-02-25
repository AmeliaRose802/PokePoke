"""Tests for the pre-flight health check system."""

import os
import tempfile
import shutil
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from pokepoke.preflight_health import (
    PreflightChecker, HealthCheckResult, HealthCheckError, ErrorSeverity,
    run_preflight_checks, attempt_self_repair
)


@pytest.fixture
def temp_repo():
    """Create a temporary git repository for testing."""
    with tempfile.TemporaryDirectory() as temp_dir:
        repo_path = Path(temp_dir)
        
        # Initialize git repo
        subprocess.run(['git', 'init'], cwd=str(repo_path), check=True, capture_output=True)
        subprocess.run(['git', 'config', 'user.name', 'Test User'], cwd=str(repo_path), check=True)
        subprocess.run(['git', 'config', 'user.email', 'test@example.com'], cwd=str(repo_path), check=True)
        
        # Create initial commit
        (repo_path / 'README.md').write_text('# Test Repo')
        subprocess.run(['git', 'add', 'README.md'], cwd=str(repo_path), check=True, capture_output=True)
        subprocess.run(['git', 'commit', '-m', 'Initial commit'], cwd=str(repo_path), check=True, capture_output=True)
        
        # Create worktrees directory
        (repo_path / 'worktrees').mkdir(exist_ok=True)
        
        yield repo_path


@pytest.fixture
def health_config():
    """Standard health check configuration for testing."""
    return {
        'min_disk_space_gb': 0.1,  # Very low for testing
        'lock_timeout_seconds': 5.0,
        'worktree_test_timeout': 10.0,
        'max_orphan_worktrees': 2,
        'git_operation_timeout': 10.0,
        'enable_self_repair': True,
        'max_repair_attempts': 2,
    }


class TestHealthCheckError:
    """Test HealthCheckError data class."""
    
    def test_error_creation(self):
        error = HealthCheckError(
            check_name='test_check',
            message='Test error message',
            severity=ErrorSeverity.ENVIRONMENTAL,
            details={'key': 'value'}
        )
        
        assert error.check_name == 'test_check'
        assert error.message == 'Test error message'
        assert error.severity == ErrorSeverity.ENVIRONMENTAL
        assert error.details == {'key': 'value'}
        assert not error.recovery_attempted
        assert not error.recovery_successful


class TestHealthCheckResult:
    """Test HealthCheckResult data class and methods."""
    
    def test_result_creation(self):
        result = HealthCheckResult()
        assert not result.passed
        assert len(result.errors) == 0
        assert len(result.warnings) == 0
        assert len(result.checks_run) == 0
    
    def test_has_environmental_errors(self):
        result = HealthCheckResult()
        result.errors = [
            HealthCheckError('check1', 'msg1', ErrorSeverity.RECOVERABLE),
            HealthCheckError('check2', 'msg2', ErrorSeverity.ENVIRONMENTAL),
        ]
        
        assert result.has_environmental_errors()
    
    def test_has_critical_errors(self):
        result = HealthCheckResult()
        result.errors = [
            HealthCheckError('check1', 'msg1', ErrorSeverity.RECOVERABLE),
            HealthCheckError('check2', 'msg2', ErrorSeverity.CRITICAL),
        ]
        
        assert result.has_critical_errors()
    
    def test_get_recoverable_errors(self):
        result = HealthCheckResult()
        result.errors = [
            HealthCheckError('check1', 'msg1', ErrorSeverity.RECOVERABLE),
            HealthCheckError('check2', 'msg2', ErrorSeverity.ENVIRONMENTAL),
            HealthCheckError('check3', 'msg3', ErrorSeverity.RECOVERABLE),
        ]
        
        recoverable = result.get_recoverable_errors()
        assert len(recoverable) == 2
        assert all(error.severity == ErrorSeverity.RECOVERABLE for error in recoverable)


class TestPreflightChecker:
    """Test the main PreflightChecker class."""
    
    def test_checker_creation(self, temp_repo, health_config):
        checker = PreflightChecker(temp_repo, health_config)
        assert checker.repo_path == temp_repo
        assert checker.config['min_disk_space_gb'] == 0.1
    
    def test_setup_defaults(self):
        checker = PreflightChecker()
        assert 'min_disk_space_gb' in checker.config
        assert 'enable_self_repair' in checker.config
        assert checker.config['enable_self_repair'] is True
    
    def test_git_status_check_clean_repo(self, temp_repo, health_config):
        checker = PreflightChecker(temp_repo, health_config)
        errors, warnings = checker._check_git_status()
        
        assert len(errors) == 0
        assert isinstance(warnings, list)
    
    def test_git_status_check_dirty_repo(self, temp_repo, health_config):
        # Make repo dirty
        (temp_repo / 'dirty_file.txt').write_text('dirty content')
        
        checker = PreflightChecker(temp_repo, health_config)
        errors, warnings = checker._check_git_status()
        
        # Should detect uncommitted changes
        assert len(errors) == 1
        assert errors[0].check_name == 'git_status_check'
        assert errors[0].severity == ErrorSeverity.RECOVERABLE
    
    def test_git_status_check_not_git_repo(self, health_config):
        with tempfile.TemporaryDirectory() as temp_dir:
            non_git_path = Path(temp_dir)
            checker = PreflightChecker(non_git_path, health_config)
            errors, warnings = checker._check_git_status()
            
            assert len(errors) == 1
            assert errors[0].check_name == 'git_status_check'
            assert errors[0].severity == ErrorSeverity.CRITICAL
    
    def test_worktree_creation_check_success(self, temp_repo, health_config):
        checker = PreflightChecker(temp_repo, health_config)
        errors, warnings = checker._check_worktree_creation()
        
        # Should succeed in clean repo
        assert len(errors) == 0
    
    def test_disk_space_check(self, temp_repo, health_config):
        checker = PreflightChecker(temp_repo, health_config)
        errors, warnings = checker._check_disk_space()
        
        # Should pass with very low threshold
        assert len(errors) == 0
    
    def test_disk_space_check_insufficient(self, temp_repo, health_config):
        # Set unreasonably high disk space requirement
        health_config['min_disk_space_gb'] = 999999999.0
        
        checker = PreflightChecker(temp_repo, health_config)
        errors, warnings = checker._check_disk_space()
        
        assert len(errors) == 1
        assert errors[0].check_name == 'disk_space_check'
        assert errors[0].severity == ErrorSeverity.ENVIRONMENTAL
    
    def test_lock_availability_check_no_locks(self, temp_repo, health_config):
        checker = PreflightChecker(temp_repo, health_config)
        errors, warnings = checker._check_lock_availability()
        
        # Should pass when no locks exist
        assert len(errors) == 0
    
    def test_repository_integrity_check_clean(self, temp_repo, health_config):
        checker = PreflightChecker(temp_repo, health_config)
        errors, warnings = checker._check_repository_integrity()
        
        # Should pass in clean repo
        assert len(errors) == 0
    
    def test_repository_integrity_check_orphaned_worktrees(self, temp_repo, health_config):
        # Create fake orphaned worktree directories
        worktrees_dir = temp_repo / 'worktrees'
        for i in range(5):  # More than max_orphan_worktrees (2)
            (worktrees_dir / f'orphan-{i}').mkdir()
        
        checker = PreflightChecker(temp_repo, health_config)
        errors, warnings = checker._check_repository_integrity()
        
        assert len(errors) == 1
        assert errors[0].check_name == 'repository_integrity_check'
        assert errors[0].severity == ErrorSeverity.RECOVERABLE
    
    def test_is_lock_stale_old_lock(self, temp_repo):
        # Create old lock file
        lock_dir = temp_repo / '.pokepoke'
        lock_dir.mkdir(exist_ok=True)
        lock_file = lock_dir / 'test.lock'
        lock_file.write_text('')
        
        # Set modification time to very old
        old_time = 0  # 1970-01-01
        os.utime(str(lock_file), (old_time, old_time))
        
        checker = PreflightChecker(temp_repo)
        is_stale, details = checker._is_lock_stale(lock_file)
        
        assert is_stale
        assert details['reason'] == 'lock_too_old'
    
    @patch('pokepoke.preflight_health.is_process_running')
    def test_is_lock_stale_dead_pid(self, mock_is_running, temp_repo):
        mock_is_running.return_value = False
        
        # Create lock file with PID
        lock_dir = temp_repo / '.pokepoke'
        lock_dir.mkdir(exist_ok=True)
        lock_file = lock_dir / 'test.lock'
        lock_file.write_text('12345')  # Non-existent PID
        
        checker = PreflightChecker(temp_repo)
        is_stale, details = checker._is_lock_stale(lock_file)
        
        assert is_stale
        assert details['reason'] == 'process_not_running'
        assert details['pid'] == 12345
        
        mock_is_running.assert_called_once_with(12345)


class TestSelfRepair:
    """Test self-repair functionality."""
    
    @patch('subprocess.run')
    def test_repair_git_status_auto_commit_success(self, mock_run, temp_repo, health_config):
        # Mock successful git add and commit
        mock_run.side_effect = [
            MagicMock(returncode=0),  # git add
            MagicMock(returncode=0),  # git commit
        ]
        
        checker = PreflightChecker(temp_repo, health_config)
        error = HealthCheckError('git_status_check', 'test', ErrorSeverity.RECOVERABLE)
        
        success = checker._repair_git_status(error)
        
        assert success
        assert mock_run.call_count == 2
    
    @patch('subprocess.run')
    def test_repair_git_status_stash_fallback(self, mock_run, temp_repo, health_config):
        # Mock failed commit but successful stash
        mock_run.side_effect = [
            MagicMock(returncode=0),  # git add
            MagicMock(returncode=1),  # git commit fails
            MagicMock(returncode=0),  # git stash succeeds
        ]
        
        checker = PreflightChecker(temp_repo, health_config)
        error = HealthCheckError('git_status_check', 'test', ErrorSeverity.RECOVERABLE)
        
        success = checker._repair_git_status(error)
        
        assert success
        assert mock_run.call_count == 3
    
    def test_repair_repository_integrity_orphaned_worktrees(self, temp_repo, health_config):
        # Create orphaned worktree directories
        worktrees_dir = temp_repo / 'worktrees'
        orphan1 = worktrees_dir / 'orphan-1'
        orphan2 = worktrees_dir / 'orphan-2'
        orphan1.mkdir()
        orphan2.mkdir()
        
        checker = PreflightChecker(temp_repo, health_config)
        error = HealthCheckError(
            'repository_integrity_check', 'test', ErrorSeverity.RECOVERABLE,
            details={'orphaned_paths': [str(orphan1), str(orphan2)]}
        )
        
        success = checker._repair_repository_integrity(error)
        
        assert success
        assert not orphan1.exists()
        assert not orphan2.exists()
    
    def test_attempt_self_repair_success(self, temp_repo, health_config):
        checker = PreflightChecker(temp_repo, health_config)
        
        # Create a result with recoverable errors
        result = HealthCheckResult()
        result.errors = [
            HealthCheckError('repository_integrity_check', 'test', ErrorSeverity.RECOVERABLE,
                           details={'orphaned_paths': []})  # Empty list - will succeed
        ]
        
        success = checker.attempt_self_repair(result)
        
        assert success
        assert result.errors[0].recovery_attempted
        assert result.errors[0].recovery_successful
    
    def test_attempt_self_repair_no_recoverable_errors(self, temp_repo, health_config):
        checker = PreflightChecker(temp_repo, health_config)
        
        # Create a result with no recoverable errors
        result = HealthCheckResult()
        result.errors = [
            HealthCheckError('test', 'test', ErrorSeverity.ENVIRONMENTAL)
        ]
        
        success = checker.attempt_self_repair(result)
        
        assert success  # Returns True when no recoverable errors


class TestConvenienceFunctions:
    """Test convenience functions."""
    
    def test_run_preflight_checks(self, temp_repo, health_config):
        result = run_preflight_checks(temp_repo, health_config)
        
        assert isinstance(result, HealthCheckResult)
        assert len(result.checks_run) > 0
    
    def test_attempt_self_repair_function(self, temp_repo, health_config):
        # Create a result that needs repair
        result = HealthCheckResult()
        result.errors = [
            HealthCheckError('repository_integrity_check', 'test', ErrorSeverity.RECOVERABLE,
                           details={'orphaned_paths': []})
        ]
        
        success = attempt_self_repair(result, temp_repo, health_config)
        
        assert success


class TestIntegrationScenarios:
    """Test integration scenarios that simulate real-world issues."""
    
    def test_full_health_check_clean_environment(self, temp_repo, health_config):
        """Test health checks in a clean environment."""
        checker = PreflightChecker(temp_repo, health_config)
        result = checker.run_all_checks()
        
        assert result.passed
        assert len(result.errors) == 0
        assert len(result.checks_run) > 0
        assert result.duration_seconds > 0
    
    def test_full_health_check_with_issues_and_repair(self, temp_repo, health_config):
        """Test health checks with issues that can be auto-repaired."""
        # Create issues that can be repaired
        (temp_repo / 'dirty_file.txt').write_text('uncommitted content')
        
        # Create orphaned worktree directories
        worktrees_dir = temp_repo / 'worktrees'
        for i in range(3):  # More than threshold
            (worktrees_dir / f'orphan-{i}').mkdir()
        
        checker = PreflightChecker(temp_repo, health_config)
        result = checker.run_all_checks()
        
        # Should detect issues but potentially repair them
        assert result.self_repair_attempted
        
        # Check that orphaned worktrees were cleaned up
        remaining_dirs = [d for d in worktrees_dir.iterdir() if d.is_dir()]
        assert len(remaining_dirs) <= health_config['max_orphan_worktrees']
    
    def test_health_check_disabled_via_config(self, temp_repo):
        """Test that health checks can be disabled."""
        config = {'enable_self_repair': False}
        
        # Make repo dirty
        (temp_repo / 'dirty_file.txt').write_text('uncommitted content')
        
        checker = PreflightChecker(temp_repo, config)
        result = checker.run_all_checks()
        
        # Should not attempt self-repair when disabled
        assert not result.self_repair_attempted
    
    def test_health_check_critical_error_no_git(self, health_config):
        """Test critical error handling when not in a git repository."""
        with tempfile.TemporaryDirectory() as temp_dir:
            non_git_path = Path(temp_dir)
            
            checker = PreflightChecker(non_git_path, health_config)
            result = checker.run_all_checks()
            
            assert not result.passed
            assert result.has_critical_errors()
            assert not result.self_repair_attempted  # Can't repair critical errors
    
    @patch('shutil.disk_usage')
    def test_health_check_disk_space_error(self, mock_disk_usage, temp_repo, health_config):
        """Test disk space error detection."""
        # Mock very low disk space
        mock_disk_usage.return_value = (1000000, 999000, 1000)  # total, used, free (1KB free)
        
        checker = PreflightChecker(temp_repo, health_config)
        result = checker.run_all_checks()
        
        assert not result.passed
        assert result.has_environmental_errors()
        
        # Find the disk space error
        disk_errors = [e for e in result.errors if e.check_name == 'disk_space_check']
        assert len(disk_errors) == 1
        assert 'insufficient disk space' in disk_errors[0].message.lower()


if __name__ == '__main__':
    pytest.main([__file__])