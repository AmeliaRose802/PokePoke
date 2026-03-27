"""Tests for the pre-flight health check system."""

import os
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from pokepoke.utils.preflight_health import (
    ErrorSeverity,
    HealthCheckError,
    HealthCheckResult,
    PreflightChecker,
    attempt_self_repair,
    run_preflight_checks,
)


@pytest.fixture
def temp_repo(monkeypatch):
    """Create a temporary git repository for testing."""
    # Strip GIT_* env vars so git commands target the temp repo, not the
    # host repo (pre-commit hooks set GIT_DIR / GIT_INDEX_FILE which
    # cause 'git init' to fail with exit 128 inside xdist workers and
    # make git status report the host repo's changes instead of the temp repo's).
    for key in [k for k in os.environ if k.startswith('GIT_')]:
        monkeypatch.delenv(key, raising=False)

    with tempfile.TemporaryDirectory() as temp_dir:
        repo_path = Path(temp_dir).resolve()

        # Initialize git repo with explicit environment to avoid inheriting
        # GIT_DIR or other vars that interfere with temp repo creation.
        git_env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
        subprocess.run(['git', 'init'], cwd=str(repo_path), check=True, capture_output=True, env=git_env)
        subprocess.run(['git', 'config', 'user.name', 'Test User'], cwd=str(repo_path), check=True, capture_output=True, env=git_env)
        subprocess.run(['git', 'config', 'user.email', 'test@example.com'], cwd=str(repo_path), check=True, capture_output=True, env=git_env)

        # Create initial commit
        (repo_path / 'README.md').write_text('# Test Repo')
        subprocess.run(['git', 'add', 'README.md'], cwd=str(repo_path), check=True, capture_output=True, env=git_env)
        subprocess.run(['git', 'commit', '-m', 'Initial commit'], cwd=str(repo_path), check=True, capture_output=True, env=git_env)

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
        # Make repo dirty with a tracked (staged) change
        dirty_file = temp_repo / 'dirty_file.txt'
        dirty_file.write_text('dirty content')
        subprocess.run(['git', 'add', 'dirty_file.txt'], cwd=str(temp_repo), check=True, capture_output=True)

        checker = PreflightChecker(temp_repo, health_config)
        errors, _warnings = checker._check_git_status()

        # Should detect uncommitted changes
        assert len(errors) == 1
        assert errors[0].check_name == 'git_status_check'
        assert errors[0].severity == ErrorSeverity.RECOVERABLE

    def test_git_status_check_not_git_repo(self, health_config):
        with tempfile.TemporaryDirectory() as temp_dir:
            non_git_path = Path(temp_dir)
            checker = PreflightChecker(non_git_path, health_config)
            errors, _warnings = checker._check_git_status()

            assert len(errors) == 1
            assert errors[0].check_name == 'git_status_check'
            assert errors[0].severity == ErrorSeverity.CRITICAL

    def test_worktree_creation_check_success(self, temp_repo, health_config):
        """Test worktree creation check with mocked git operations.

        Real git worktree operations are flaky under parallel xdist execution
        on Windows due to file locking and index contention, so we mock subprocess.
        """
        checker = PreflightChecker(temp_repo, health_config)

        def mock_subprocess_run(cmd, **kwargs):
            """Mock git worktree add by actually creating the directory."""
            result = MagicMock(returncode=0, stdout='', stderr='')
            # If it's a worktree add command, create the directory so exists() passes
            if 'worktree' in cmd and 'add' in cmd:
                path = Path(cmd[3])  # The worktree path argument
                path.mkdir(parents=True, exist_ok=True)
            return result

        with patch('subprocess.run', side_effect=mock_subprocess_run):
            errors, _warnings = checker._check_worktree_creation()

        # Should succeed
        assert len(errors) == 0

    def test_disk_space_check(self, temp_repo, health_config):
        checker = PreflightChecker(temp_repo, health_config)
        errors, _warnings = checker._check_disk_space()

        # Should pass with very low threshold
        assert len(errors) == 0

    def test_disk_space_check_insufficient(self, temp_repo, health_config):
        # Set unreasonably high disk space requirement
        health_config['min_disk_space_gb'] = 999999999.0

        checker = PreflightChecker(temp_repo, health_config)
        errors, _warnings = checker._check_disk_space()

        assert len(errors) == 1
        assert errors[0].check_name == 'disk_space_check'
        assert errors[0].severity == ErrorSeverity.ENVIRONMENTAL

    def test_lock_availability_check_no_locks(self, temp_repo, health_config):
        checker = PreflightChecker(temp_repo, health_config)
        errors, _warnings = checker._check_lock_availability()

        # Should pass when no locks exist
        assert len(errors) == 0

    def test_repository_integrity_check_clean(self, temp_repo, health_config):
        checker = PreflightChecker(temp_repo, health_config)
        errors, _warnings = checker._check_repository_integrity()

        # Should pass in clean repo
        assert len(errors) == 0

    def test_repository_integrity_check_orphaned_worktrees(self, temp_repo, health_config):
        # Create fake orphaned worktree directories
        worktrees_dir = temp_repo / 'worktrees'
        for i in range(5):  # More than max_orphan_worktrees (2)
            (worktrees_dir / f'orphan-{i}').mkdir()

        checker = PreflightChecker(temp_repo, health_config)
        errors, _warnings = checker._check_repository_integrity()

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

    @patch('pokepoke.utils.preflight_checks.is_process_running')
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

    @pytest.mark.allow_git_repair
    @patch('subprocess.run')
    def test_repair_git_status_auto_commit_success(self, mock_run, temp_repo, health_config):
        # Mock successful git add -u and commit
        mock_run.side_effect = [
            MagicMock(returncode=0),  # git add -u
            MagicMock(returncode=0),  # git commit
        ]

        checker = PreflightChecker(temp_repo, health_config)
        error = HealthCheckError('git_status_check', 'test', ErrorSeverity.RECOVERABLE)

        success = checker._repair_git_status(error)

        assert success
        assert mock_run.call_count == 2
        # Verify targeted staging (git add -u, not git add -A)
        add_call = mock_run.call_args_list[0]
        assert add_call[0][0] == ['git', 'add', '-u']

    @pytest.mark.allow_git_repair
    @patch('pokepoke.utils.preflight_repair._invoke_preflight_cleanup', return_value=True)
    @patch('subprocess.run')
    def test_repair_git_status_cleanup_agent_on_commit_failure(
        self, mock_run, mock_cleanup, temp_repo, health_config
    ):
        """When commit fails, cleanup agent is invoked instead of stashing."""
        mock_run.side_effect = [
            MagicMock(returncode=0),  # git add -u
            MagicMock(returncode=1, stderr='hook failed'),  # git commit fails
        ]

        checker = PreflightChecker(temp_repo, health_config)
        error = HealthCheckError('git_status_check', 'test', ErrorSeverity.RECOVERABLE)

        success = checker._repair_git_status(error)

        assert success
        assert mock_run.call_count == 2
        mock_cleanup.assert_called_once_with(temp_repo, 'hook failed')

    @pytest.mark.allow_git_repair
    @patch('pokepoke.utils.preflight_repair._invoke_preflight_cleanup', return_value=False)
    @patch('subprocess.run')
    def test_repair_git_status_cleanup_agent_failure(
        self, mock_run, mock_cleanup, temp_repo, health_config
    ):
        """When cleanup agent fails, repair returns False (never stashes)."""
        mock_run.side_effect = [
            MagicMock(returncode=0),  # git add -u
            MagicMock(returncode=1, stderr='hook failed'),  # git commit fails
        ]

        checker = PreflightChecker(temp_repo, health_config)
        error = HealthCheckError('git_status_check', 'test', ErrorSeverity.RECOVERABLE)

        success = checker._repair_git_status(error)

        assert not success
        mock_cleanup.assert_called_once()

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

    @patch('pokepoke.utils.preflight_health.PreflightChecker._check_worktree_creation', return_value=([], []))
    def test_run_preflight_checks(self, mock_wt_check, temp_repo, health_config):
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
        # Mock worktree creation to avoid flaky git operations under parallel xdist
        with patch.object(checker, '_check_worktree_creation', return_value=([], [])):
            result = checker.run_all_checks()

        assert result.passed
        assert len(result.errors) == 0
        assert len(result.checks_run) > 0
        assert result.duration_seconds > 0

    def test_full_health_check_with_issues_and_repair(self, temp_repo, health_config):
        """Test health checks with issues that can be auto-repaired."""
        # Create a staged (tracked) change so git_status_check detects it as 'other'
        dirty_file = temp_repo / 'dirty_file.txt'
        dirty_file.write_text('uncommitted content')
        subprocess.run(['git', 'add', 'dirty_file.txt'], cwd=str(temp_repo), check=True, capture_output=True)

        # Create orphaned worktree directories (more than threshold)
        worktrees_dir = temp_repo / 'worktrees'
        for i in range(3):  # More than max_orphan_worktrees=2
            (worktrees_dir / f'orphan-{i}').mkdir()

        # Mock list_worktrees to return empty list so orphan detection works
        # (list_worktrees() runs without cwd so it checks the wrong repo otherwise)
        # Mock worktree creation to avoid flaky git operations under parallel xdist
        # Mock repair_git_status to prevent real git add -A / git commit against
        # the host repo (was causing auto-commits of unrelated staged files)
        with patch('pokepoke.utils.preflight_checks.list_worktrees', return_value=[]), \
             patch('pokepoke.utils.preflight_repair.repair_git_status', return_value=True):
            checker = PreflightChecker(temp_repo, health_config)
            with patch.object(checker, '_check_worktree_creation', return_value=([], [])):
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
        # Mock worktree creation to avoid flaky git operations under parallel xdist
        with patch.object(checker, '_check_worktree_creation', return_value=([], [])):
            result = checker.run_all_checks()

        # Should not attempt self-repair when disabled
        assert not result.self_repair_attempted

    def test_health_check_critical_error_no_git(self, health_config):
        """Test critical error handling when not in a git repository."""
        with tempfile.TemporaryDirectory() as temp_dir:
            non_git_path = Path(temp_dir)

            checker = PreflightChecker(non_git_path, health_config)
            # Mock worktree creation to avoid flaky git operations under parallel xdist
            with patch.object(checker, '_check_worktree_creation', return_value=([], [])):
                result = checker.run_all_checks()

            assert not result.passed
            assert result.has_critical_errors()
            assert not result.self_repair_attempted  # Can't repair critical errors

    @patch('shutil.disk_usage')
    def test_health_check_disk_space_error(self, mock_disk_usage, temp_repo, health_config):
        """Test disk space error detection."""
        # Mock very low disk space using namedtuple to match shutil.disk_usage return type
        from collections import namedtuple
        DiskUsage = namedtuple('usage', ['total', 'used', 'free'])
        mock_disk_usage.return_value = DiskUsage(total=1000000, used=999000, free=1000)  # 1KB free

        checker = PreflightChecker(temp_repo, health_config)
        # Mock worktree creation to avoid flaky git operations under parallel xdist
        with patch.object(checker, '_check_worktree_creation', return_value=([], [])):
            result = checker.run_all_checks()

        assert not result.passed
        assert result.has_environmental_errors()

        # Find the disk space error
        disk_errors = [e for e in result.errors if e.check_name == 'disk_space_check']
        assert len(disk_errors) == 1
        assert 'insufficient disk space' in disk_errors[0].message.lower()


class TestGitStatusEdgeCases:
    """Test git status check edge cases for CalledProcessError, TimeoutExpired, beads changes."""

    def test_git_status_called_process_error(self, temp_repo, health_config):
        """Test that CalledProcessError during git status is handled."""
        checker = PreflightChecker(temp_repo, health_config)

        with patch('pokepoke.utils.preflight_checks.has_uncommitted_changes', return_value=True), \
             patch('subprocess.run', side_effect=subprocess.CalledProcessError(1, 'git', stderr='bad')):
            errors, _warnings = checker._check_git_status()

        assert len(errors) == 1
        assert errors[0].severity == ErrorSeverity.ENVIRONMENTAL
        assert 'Failed to check git status' in errors[0].message

    def test_git_status_timeout(self, temp_repo, health_config):
        """Test that TimeoutExpired during git status is handled."""
        checker = PreflightChecker(temp_repo, health_config)

        with patch('pokepoke.utils.preflight_checks.has_uncommitted_changes', return_value=True), \
             patch('subprocess.run', side_effect=subprocess.TimeoutExpired('git', 10)):
            errors, _warnings = checker._check_git_status()

        assert len(errors) == 1
        assert errors[0].severity == ErrorSeverity.ENVIRONMENTAL
        assert 'timed out' in errors[0].message.lower()

    def test_git_status_beads_and_worktree_changes(self, temp_repo, health_config):
        """Test that beads and worktree changes produce warnings."""
        checker = PreflightChecker(temp_repo, health_config)

        mock_result = MagicMock(returncode=0, stdout='.beads/issues.jsonl\nworktrees/foo/bar.txt\n')
        with patch('pokepoke.utils.preflight_checks.has_uncommitted_changes', return_value=True), \
             patch('subprocess.run', return_value=mock_result), \
             patch('pokepoke.utils.preflight_checks.categorize_git_changes', return_value={
                 'other': [], 'beads': ['.beads/issues.jsonl'], 'worktree': ['worktrees/foo/bar.txt'], 'untracked': []
             }):
            errors, warnings = checker._check_git_status()

        assert len(errors) == 0
        assert any('Beads database' in w for w in warnings)
        assert any('Worktree cleanup' in w for w in warnings)


class TestWorktreeCreationEdgeCases:
    """Test worktree creation error paths."""

    def test_worktree_creation_not_created(self, temp_repo, health_config):
        """Test error when worktree directory doesn't exist after creation."""
        checker = PreflightChecker(temp_repo, health_config)

        # Mock subprocess to succeed but don't create the directory
        mock_result = MagicMock(returncode=0, stdout='', stderr='')
        with patch('subprocess.run', return_value=mock_result):
            errors, _warnings = checker._check_worktree_creation()

        assert len(errors) == 1
        assert 'not created' in errors[0].message.lower()

    def test_worktree_creation_called_process_error(self, temp_repo, health_config):
        """Test CalledProcessError during worktree creation."""
        checker = PreflightChecker(temp_repo, health_config)

        with patch('subprocess.run', side_effect=subprocess.CalledProcessError(1, 'git', stderr='fatal error')):
            errors, _warnings = checker._check_worktree_creation()

        assert len(errors) == 1
        assert 'Failed to create test worktree' in errors[0].message

    def test_worktree_creation_timeout(self, temp_repo, health_config):
        """Test TimeoutExpired during worktree creation."""
        checker = PreflightChecker(temp_repo, health_config)

        with patch('subprocess.run', side_effect=subprocess.TimeoutExpired('git', 10)):
            errors, _warnings = checker._check_worktree_creation()

        assert len(errors) == 1
        assert 'timed out' in errors[0].message.lower()


class TestLockAvailabilityEdgeCases:
    """Test lock availability check edge cases."""

    def test_lock_stale_detected(self, temp_repo, health_config):
        """Test detection of a stale lock file."""
        lock_dir = temp_repo / '.pokepoke'
        lock_dir.mkdir(exist_ok=True)
        lock_file = lock_dir / 'orchestrator.lock'
        lock_file.write_text('')
        os.utime(str(lock_file), (0, 0))  # Very old

        checker = PreflightChecker(temp_repo, health_config)
        errors, warnings = checker._check_lock_availability()

        assert any('Stale lock' in w for w in warnings)
        assert len(errors) == 0  # Stale lock = warning, not error (self-repair enabled)

    def test_lock_active_detected(self, temp_repo, health_config):
        """Test detection of an active (non-stale) lock file."""
        lock_dir = temp_repo / '.pokepoke'
        lock_dir.mkdir(exist_ok=True)
        lock_file = lock_dir / 'orchestrator.lock'
        lock_file.write_text(str(os.getpid()))  # Current PID = active

        checker = PreflightChecker(temp_repo, health_config)
        errors, _warnings = checker._check_lock_availability()

        assert len(errors) == 1
        assert errors[0].check_name == 'lock_availability_check'

    @patch('pokepoke.utils.preflight_checks.is_process_running')
    def test_is_lock_stale_process_running(self, mock_is_running, temp_repo):
        """Test _is_lock_stale when process is still running."""
        mock_is_running.return_value = True

        lock_dir = temp_repo / '.pokepoke'
        lock_dir.mkdir(exist_ok=True)
        lock_file = lock_dir / 'test.lock'
        lock_file.write_text('99999')

        checker = PreflightChecker(temp_repo)
        is_stale, details = checker._is_lock_stale(lock_file)

        assert not is_stale
        assert details['reason'] == 'process_still_running'


class TestRepairEdgeCases:
    """Test repair edge cases."""

    def test_repair_lock_availability_not_stale(self, temp_repo, health_config):
        """Test lock repair when lock is not actually stale."""
        lock_dir = temp_repo / '.pokepoke'
        lock_dir.mkdir(exist_ok=True)
        lock_file = lock_dir / 'test.lock'
        lock_file.write_text('')

        checker = PreflightChecker(temp_repo, health_config)
        error = HealthCheckError(
            'lock_availability_check', 'test', ErrorSeverity.RECOVERABLE,
            details={'lock_file': str(lock_file)}
        )

        # Lock is not stale (just created), so repair should fail
        success = checker._repair_lock_availability(error)
        assert not success

    def test_repair_lock_availability_no_lock_file(self, temp_repo, health_config):
        """Test lock repair when lock_file key missing."""
        checker = PreflightChecker(temp_repo, health_config)
        error = HealthCheckError(
            'lock_availability_check', 'test', ErrorSeverity.RECOVERABLE,
            details={}
        )
        success = checker._repair_lock_availability(error)
        assert not success

    def test_repair_lock_availability_already_gone(self, temp_repo, health_config):
        """Test lock repair when lock file doesn't exist."""
        checker = PreflightChecker(temp_repo, health_config)
        error = HealthCheckError(
            'lock_availability_check', 'test', ErrorSeverity.RECOVERABLE,
            details={'lock_file': str(temp_repo / '.pokepoke' / 'nonexistent.lock')}
        )
        success = checker._repair_lock_availability(error)
        assert success  # Already gone = success

    @pytest.mark.allow_git_repair
    @patch('subprocess.run')
    def test_repair_git_status_called_process_error(self, mock_run, temp_repo, health_config):
        """Test git status repair when subprocess raises CalledProcessError."""
        mock_run.side_effect = subprocess.CalledProcessError(1, 'git', stderr='fail')

        checker = PreflightChecker(temp_repo, health_config)
        error = HealthCheckError('git_status_check', 'test', ErrorSeverity.RECOVERABLE)

        success = checker._repair_git_status(error)
        assert not success

    def test_check_raises_exception_in_run_all_checks(self, temp_repo, health_config):
        """Test that an exception in a check function is handled gracefully."""
        checker = PreflightChecker(temp_repo, health_config)

        with patch.object(checker, '_check_git_status', side_effect=RuntimeError('boom')), \
             patch.object(checker, '_check_worktree_creation', return_value=([], [])):
            result = checker.run_all_checks()

        assert not result.passed
        env_errors = [e for e in result.errors if e.severity == ErrorSeverity.ENVIRONMENTAL]
        assert any('exception' in e.message.lower() for e in env_errors)

    def test_rerun_failed_checks(self, temp_repo, health_config):
        """Test _rerun_failed_checks disables self-repair and re-enables after."""
        checker = PreflightChecker(temp_repo, health_config)
        original_result = HealthCheckResult()

        with patch.object(checker, '_check_worktree_creation', return_value=([], [])):
            rerun_result = checker._rerun_failed_checks(original_result)

        assert isinstance(rerun_result, HealthCheckResult)
        # Config should be restored
        assert checker.config['enable_self_repair'] is True

    def test_disk_space_check_exception(self, temp_repo, health_config):
        """Test disk space check when shutil.disk_usage raises."""
        checker = PreflightChecker(temp_repo, health_config)

        with patch('shutil.disk_usage', side_effect=OSError('disk error')):
            errors, _warnings = checker._check_disk_space()

        assert len(errors) == 1
        assert 'Failed to check disk space' in errors[0].message

    def test_repository_integrity_small_orphan_count(self, temp_repo, health_config):
        """Test that small orphan count produces warning, not error."""
        worktrees_dir = temp_repo / 'worktrees'
        # Create 1 orphan (below max_orphan_worktrees=2)
        (worktrees_dir / 'orphan-single').mkdir()

        checker = PreflightChecker(temp_repo, health_config)
        errors, warnings = checker._check_repository_integrity()

        assert len(errors) == 0
        assert any('orphaned' in w.lower() for w in warnings)

    def test_repair_lock_availability_stale_lock_removed(self, temp_repo, health_config):
        """Test successful removal of a stale lock file."""
        lock_dir = temp_repo / '.pokepoke'
        lock_dir.mkdir(exist_ok=True)
        lock_file = lock_dir / 'test.lock'
        lock_file.write_text('')
        # Make it old so is_lock_stale returns True
        os.utime(str(lock_file), (0, 0))

        checker = PreflightChecker(temp_repo, health_config)
        error = HealthCheckError(
            'lock_availability_check', 'test', ErrorSeverity.RECOVERABLE,
            details={'lock_file': str(lock_file)}
        )
        success = checker._repair_lock_availability(error)
        assert success
        assert not lock_file.exists()

    def test_repair_lock_availability_exception(self, temp_repo, health_config):
        """Test lock repair when an unexpected exception occurs."""
        checker = PreflightChecker(temp_repo, health_config)
        error = HealthCheckError(
            'lock_availability_check', 'test', ErrorSeverity.RECOVERABLE,
            details={'lock_file': str(temp_repo / '.pokepoke' / 'test.lock')}
        )
        with patch('pokepoke.utils.preflight_repair.is_lock_stale', side_effect=RuntimeError('boom')):
            # File exists check passes, but is_lock_stale raises
            lock_dir = temp_repo / '.pokepoke'
            lock_dir.mkdir(exist_ok=True)
            (lock_dir / 'test.lock').write_text('')
            success = checker._repair_lock_availability(error)
        assert not success

    @pytest.mark.allow_git_repair
    @patch('subprocess.run')
    def test_repair_git_status_generic_exception(self, mock_run, temp_repo, health_config):
        """Test git status repair when a generic exception occurs."""
        mock_run.side_effect = RuntimeError('unexpected error')
        checker = PreflightChecker(temp_repo, health_config)
        error = HealthCheckError('git_status_check', 'test', ErrorSeverity.RECOVERABLE)
        success = checker._repair_git_status(error)
        assert not success

    @pytest.mark.allow_git_repair
    @patch('pokepoke.agents.cleanup_agents.invoke_cleanup_agent', return_value=(True, None))
    def test_invoke_preflight_cleanup_success(self, mock_agent, temp_repo, health_config):
        """Test _invoke_preflight_cleanup delegates to cleanup agent."""
        from pokepoke.utils.preflight_repair import _invoke_preflight_cleanup
        success = _invoke_preflight_cleanup(temp_repo, 'hook failed')
        assert success
        mock_agent.assert_called_once()
        call_kwargs = mock_agent.call_args
        # Verify synthetic work item was created with commit error context
        item = call_kwargs[0][0]
        assert item.id == 'preflight-repair'
        assert 'hook failed' in item.description

    @pytest.mark.allow_git_repair
    @patch('pokepoke.agents.cleanup_agents.invoke_cleanup_agent',
           side_effect=RuntimeError('agent crash'))
    def test_invoke_preflight_cleanup_agent_exception(self, mock_agent, temp_repo, health_config):
        """Test _invoke_preflight_cleanup when cleanup agent raises exception."""
        from pokepoke.utils.preflight_repair import _invoke_preflight_cleanup
        success = _invoke_preflight_cleanup(temp_repo, 'hook failed')
        assert not success

    def test_repair_repository_integrity_rmtree_fails(self, temp_repo, health_config):
        """Test repository integrity repair when removal fails."""
        worktrees_dir = temp_repo / 'worktrees'
        orphan = worktrees_dir / 'orphan-stubborn'
        orphan.mkdir()

        checker = PreflightChecker(temp_repo, health_config)
        error = HealthCheckError(
            'repository_integrity_check', 'test', ErrorSeverity.RECOVERABLE,
            details={'orphaned_paths': [str(orphan)]}
        )
        # Mock rmtree to do nothing so path still exists after "removal"
        with patch('pokepoke.utils.preflight_repair.shutil.rmtree'):
            success = checker._repair_repository_integrity(error)
        assert not success

    def test_repair_repository_integrity_exception(self, temp_repo, health_config):
        """Test repository integrity repair when exception occurs."""
        checker = PreflightChecker(temp_repo, health_config)
        error = HealthCheckError(
            'repository_integrity_check', 'test', ErrorSeverity.RECOVERABLE,
            details={'orphaned_paths': ['nonexistent']}
        )
        with patch('pokepoke.utils.preflight_repair.Path.exists', side_effect=RuntimeError('boom')):
            success = checker._repair_repository_integrity(error)
        assert not success

    def test_attempt_self_repair_retry_and_failure(self, temp_repo, health_config):
        """Test attempt_self_repair retries on failure and eventually fails."""
        health_config['max_repair_attempts'] = 2
        checker = PreflightChecker(temp_repo, health_config)

        result = HealthCheckResult()
        result.errors = [
            HealthCheckError('git_status_check', 'test', ErrorSeverity.RECOVERABLE)
        ]

        # All repair attempts fail
        with patch('pokepoke.utils.preflight_repair.repair_git_status', return_value=False), \
             patch('pokepoke.utils.preflight_repair.time.sleep'):
            success = checker.attempt_self_repair(result)

        assert not success
        assert result.errors[0].recovery_attempted
        assert not result.errors[0].recovery_successful

    def test_attempt_self_repair_exception_in_repair(self, temp_repo, health_config):
        """Test attempt_self_repair when repair function raises exception."""
        health_config['max_repair_attempts'] = 1
        checker = PreflightChecker(temp_repo, health_config)

        result = HealthCheckResult()
        result.errors = [
            HealthCheckError('git_status_check', 'test', ErrorSeverity.RECOVERABLE)
        ]

        with patch('pokepoke.utils.preflight_repair.repair_git_status', side_effect=RuntimeError('boom')):
            success = checker.attempt_self_repair(result)

        assert not success

    def test_attempt_self_repair_unknown_check_name(self, temp_repo, health_config):
        """Test attempt_self_repair with unknown check name."""
        health_config['max_repair_attempts'] = 1
        checker = PreflightChecker(temp_repo, health_config)

        result = HealthCheckResult()
        result.errors = [
            HealthCheckError('unknown_check', 'test', ErrorSeverity.RECOVERABLE)
        ]

        success = checker.attempt_self_repair(result)
        assert not success


if __name__ == '__main__':
    pytest.main([__file__])
