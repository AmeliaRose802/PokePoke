"""Pre-flight health checks and self-repair system for PokePoke.

This module implements comprehensive health checks that run before work batch processing
to prevent submission to broken environments. It includes automatic self-repair
capabilities and graceful shutdown with diagnostics on unrecoverable failures.

The system addresses the issue where broken environments (stale locks, dirty git state)
caused silent failures with 0 agent requests by implementing proactive health gates.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pokepoke.git_operations import has_uncommitted_changes, categorize_git_changes
from pokepoke.worktrees import list_worktrees
from pokepoke.coordination import check_lock_status, clear_lock_if_stale
from pokepoke.process_utils import is_process_running

logger = logging.getLogger(__name__)

__all__ = [
    'HealthCheckResult', 'HealthCheckError', 'ErrorSeverity',
    'PreflightChecker', 'run_preflight_checks', 'attempt_self_repair'
]


class ErrorSeverity:
    """Classification of error severity for proper handling."""
    ENVIRONMENTAL = "environmental"  # Stop all work
    ITEM_SPECIFIC = "item_specific"  # Skip item, continue
    RECOVERABLE = "recoverable"      # Attempt self-repair
    CRITICAL = "critical"            # Immediate shutdown


@dataclass
class HealthCheckError:
    """Represents a health check failure with context."""
    check_name: str
    message: str
    severity: str
    details: dict[str, Any] = field(default_factory=dict)
    recovery_attempted: bool = False
    recovery_successful: bool = False


@dataclass
class HealthCheckResult:
    """Result of running pre-flight health checks."""
    passed: bool
    errors: list[HealthCheckError] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    duration_seconds: float = 0.0
    checks_run: list[str] = field(default_factory=list)
    self_repair_attempted: bool = False
    self_repair_successful: bool = False
    
    def has_environmental_errors(self) -> bool:
        """Check if there are any environmental errors that should stop all work."""
        return any(error.severity == ErrorSeverity.ENVIRONMENTAL for error in self.errors)
    
    def has_critical_errors(self) -> bool:
        """Check if there are any critical errors requiring immediate shutdown."""
        return any(error.severity == ErrorSeverity.CRITICAL for error in self.errors)
    
    def get_recoverable_errors(self) -> list[HealthCheckError]:
        """Get list of errors that may be recoverable through self-repair."""
        return [error for error in self.errors if error.severity == ErrorSeverity.RECOVERABLE]


class PreflightChecker:
    """Main class for running pre-flight health checks and self-repair."""
    
    def __init__(self, repo_path: Path | None = None, config: dict[str, Any] | None = None):
        """Initialize the preflight checker.
        
        Args:
            repo_path: Path to the repository root (defaults to current directory)
            config: Configuration dict for health check parameters
        """
        self.repo_path = repo_path or Path.cwd()
        self.config = config or {}
        self._setup_defaults()
    
    def _setup_defaults(self) -> None:
        """Set up default configuration values."""
        defaults = {
            'min_disk_space_gb': 1.0,
            'lock_timeout_seconds': 30.0,
            'worktree_test_timeout': 60.0,
            'max_orphan_worktrees': 10,
            'git_operation_timeout': 30.0,
            'enable_self_repair': True,
            'max_repair_attempts': 3,
        }
        
        for key, value in defaults.items():
            if key not in self.config:
                self.config[key] = value
    
    def run_all_checks(self) -> HealthCheckResult:
        """Run all pre-flight health checks.
        
        Returns:
            HealthCheckResult with overall status and any issues found
        """
        start_time = time.time()
        result = HealthCheckResult(passed=False)  # Fix: provide required parameter
        
        checks = [
            ('git_status_check', self._check_git_status),
            ('worktree_creation_check', self._check_worktree_creation),
            ('lock_availability_check', self._check_lock_availability),
            ('disk_space_check', self._check_disk_space),
            ('repository_integrity_check', self._check_repository_integrity),
        ]
        
        logger.info(f"Starting pre-flight health checks in {self.repo_path}")
        
        for check_name, check_func in checks:
            result.checks_run.append(check_name)
            try:
                check_errors, check_warnings = check_func()
                result.errors.extend(check_errors)
                result.warnings.extend(check_warnings)
            except Exception as e:
                logger.exception(f"Health check {check_name} raised exception: {e}")
                result.errors.append(HealthCheckError(
                    check_name=check_name,
                    message=f"Health check failed with exception: {str(e)}",
                    severity=ErrorSeverity.ENVIRONMENTAL,
                    details={'exception': str(e)}
                ))
        
        result.duration_seconds = time.time() - start_time
        result.passed = len(result.errors) == 0
        
        if not result.passed and self.config.get('enable_self_repair', True):
            logger.info("Health checks failed, attempting self-repair")
            result.self_repair_attempted = True
            result.self_repair_successful = self.attempt_self_repair(result)
            
            if result.self_repair_successful:
                # Re-run failed checks to verify repair
                logger.info("Self-repair completed, re-running failed checks")
                result = self._rerun_failed_checks(result)
        
        logger.info(f"Pre-flight health checks completed in {result.duration_seconds:.2f}s - "
                   f"{'PASSED' if result.passed else 'FAILED'}")
        
        return result
    
    def _check_git_status(self) -> tuple[list[HealthCheckError], list[str]]:
        """Check that git repository is in a clean state."""
        errors: list[HealthCheckError] = []
        warnings: list[str] = []  # Fix: add type annotation
        
        try:
            # Check if we're in a git repository
            if not (self.repo_path / '.git').exists():
                errors.append(HealthCheckError(
                    check_name='git_status_check',
                    message=f"Not a git repository: {self.repo_path}",
                    severity=ErrorSeverity.CRITICAL,
                    details={'repo_path': str(self.repo_path)}
                ))
                return errors, warnings
            
            # Check for uncommitted changes
            if has_uncommitted_changes(cwd=str(self.repo_path)):
                try:
                    result = subprocess.run(
                        ['git', 'status', '--porcelain'],
                        capture_output=True, text=True, check=True,
                        cwd=str(self.repo_path), timeout=self.config['git_operation_timeout']
                    )
                    
                    lines = result.stdout.strip().split('\n') if result.stdout.strip() else []
                    changes = categorize_git_changes(lines)
                    
                    # Classify different types of changes
                    if changes['other']:  # Non-beads, non-worktree changes
                        errors.append(HealthCheckError(
                            check_name='git_status_check',
                            message=f"Repository has uncommitted changes: {len(changes['other'])} files",
                            severity=ErrorSeverity.RECOVERABLE,
                            details={
                                'uncommitted_files': changes['other'][:10],  # Limit for logging
                                'total_count': len(changes['other'])
                            }
                        ))
                    
                    if changes['beads']:
                        warnings.append(f"Beads database changes detected ({len(changes['beads'])} files)")
                    
                    if changes['worktree']:
                        warnings.append(f"Worktree cleanup changes detected ({len(changes['worktree'])} files)")
                    
                except subprocess.CalledProcessError as e:
                    errors.append(HealthCheckError(
                        check_name='git_status_check',
                        message=f"Failed to check git status: {e.stderr or str(e)}",
                        severity=ErrorSeverity.ENVIRONMENTAL,
                        details={'returncode': e.returncode, 'stderr': e.stderr}
                    ))
                except subprocess.TimeoutExpired:
                    errors.append(HealthCheckError(
                        check_name='git_status_check',
                        message="Git status check timed out",
                        severity=ErrorSeverity.ENVIRONMENTAL,
                        details={'timeout': self.config['git_operation_timeout']}
                    ))
            
        except Exception as e:
            errors.append(HealthCheckError(
                check_name='git_status_check',
                message=f"Git status check failed: {str(e)}",
                severity=ErrorSeverity.ENVIRONMENTAL,
                details={'exception': str(e)}
            ))
        
        return errors, warnings
    
    def _check_worktree_creation(self) -> tuple[list[HealthCheckError], list[str]]:
        """Test that worktrees can be created successfully."""
        errors: list[HealthCheckError] = []
        warnings: list[str] = []
        
        # Generate a unique test worktree name
        import uuid
        test_id = f"health-check-{uuid.uuid4().hex[:8]}"
        test_worktree_path = self.repo_path / "worktrees" / f"test-{test_id}"
        test_branch = f"test/health-check-{test_id}"
        
        try:
            # Ensure worktrees directory exists
            (self.repo_path / "worktrees").mkdir(exist_ok=True)
            
            # Try to create a test worktree
            cmd = [
                'git', 'worktree', 'add', str(test_worktree_path),
                '-b', test_branch, 'HEAD'
            ]
            
            result = subprocess.run(
                cmd, capture_output=True, text=True, check=True,
                cwd=str(self.repo_path), timeout=self.config['worktree_test_timeout']
            )
            
            # Verify the worktree was created
            if not test_worktree_path.exists():
                errors.append(HealthCheckError(
                    check_name='worktree_creation_check',
                    message="Test worktree directory was not created",
                    severity=ErrorSeverity.ENVIRONMENTAL,
                    details={'expected_path': str(test_worktree_path)}
                ))
            
        except subprocess.CalledProcessError as e:
            stderr = e.stderr or str(e)
            errors.append(HealthCheckError(
                check_name='worktree_creation_check',
                message=f"Failed to create test worktree: {stderr}",
                severity=ErrorSeverity.ENVIRONMENTAL,
                details={'returncode': e.returncode, 'stderr': stderr, 'cmd': cmd}
            ))
        except subprocess.TimeoutExpired:
            errors.append(HealthCheckError(
                check_name='worktree_creation_check',
                message="Worktree creation test timed out",
                severity=ErrorSeverity.ENVIRONMENTAL,
                details={'timeout': self.config['worktree_test_timeout']}
            ))
        finally:
            # Clean up test worktree
            try:
                if test_worktree_path.exists():
                    subprocess.run(
                        ['git', 'worktree', 'remove', '--force', str(test_worktree_path)],
                        capture_output=True, cwd=str(self.repo_path), timeout=30
                    )
                # Clean up test branch
                subprocess.run(
                    ['git', 'branch', '-D', test_branch],
                    capture_output=True, cwd=str(self.repo_path), timeout=30
                )
            except Exception as cleanup_error:
                warnings.append(f"Failed to clean up test worktree: {cleanup_error}")
        
        return errors, warnings
    
    def _check_lock_availability(self) -> tuple[list[HealthCheckError], list[str]]:
        """Check that required locks are available and clear stale ones."""
        errors: list[HealthCheckError] = []
        warnings: list[str] = []
        
        # Check common lock files
        lock_files = [
            '.pokepoke/orchestrator.lock',
            '.pokepoke/worktree-setup.lock',
            '.pokepoke/merge.lock',
            '.pokepoke/cleanup.lock',
        ]
        
        for lock_file in lock_files:
            lock_path = self.repo_path / lock_file
            
            if lock_path.exists():
                try:
                    # Check if the lock is stale
                    is_stale, details = self._is_lock_stale(lock_path)
                    
                    if is_stale:
                        warnings.append(f"Stale lock detected: {lock_file}")
                        if self.config.get('enable_self_repair', True):
                            # Will be cleaned up in self-repair phase
                            continue
                    else:
                        errors.append(HealthCheckError(
                            check_name='lock_availability_check',
                            message=f"Active lock preventing operations: {lock_file}",
                            severity=ErrorSeverity.ENVIRONMENTAL,
                            details={'lock_file': str(lock_path), **details}
                        ))
                
                except Exception as e:
                    warnings.append(f"Failed to check lock status for {lock_file}: {e}")
        
        return errors, warnings
    
    def _check_disk_space(self) -> tuple[list[HealthCheckError], list[str]]:
        """Check that sufficient disk space is available."""
        errors: list[HealthCheckError] = []
        warnings: list[str] = []
        
        try:
            disk_usage = shutil.disk_usage(str(self.repo_path))
            free_gb = disk_usage.free / (1024**3)
            min_required = self.config['min_disk_space_gb']
            
            if free_gb < min_required:
                errors.append(HealthCheckError(
                    check_name='disk_space_check',
                    message=f"Insufficient disk space: {free_gb:.2f}GB free, {min_required}GB required",
                    severity=ErrorSeverity.ENVIRONMENTAL,
                    details={
                        'free_gb': free_gb,
                        'required_gb': min_required,
                        'total_gb': disk_usage.total / (1024**3),
                        'used_gb': disk_usage.used / (1024**3)
                    }
                ))
            elif free_gb < min_required * 2:
                warnings.append(f"Low disk space: {free_gb:.2f}GB free (recommended: {min_required * 2:.2f}GB)")
        
        except Exception as e:
            errors.append(HealthCheckError(
                check_name='disk_space_check',
                message=f"Failed to check disk space: {str(e)}",
                severity=ErrorSeverity.ENVIRONMENTAL,
                details={'exception': str(e)}
            ))
        
        return errors, warnings
    
    def _check_repository_integrity(self) -> tuple[list[HealthCheckError], list[str]]:
        """Check for orphaned worktrees and other repository integrity issues."""
        errors: list[HealthCheckError] = []
        warnings: list[str] = []
        
        try:
            # Check for orphaned worktrees
            worktrees = list_worktrees()
            worktree_paths = [Path(wt['path']) for wt in worktrees if 'path' in wt]
            
            # Find orphaned worktree directories
            worktrees_dir = self.repo_path / 'worktrees'
            if worktrees_dir.exists():
                existing_dirs = [d for d in worktrees_dir.iterdir() if d.is_dir()]
                orphaned = []
                
                for dir_path in existing_dirs:
                    # Check if this directory is registered as an active worktree
                    is_active = any(
                        Path(wt_path).resolve() == dir_path.resolve()
                        for wt_path in worktree_paths
                    )
                    if not is_active:
                        orphaned.append(dir_path)
                
                if len(orphaned) > self.config['max_orphan_worktrees']:
                    errors.append(HealthCheckError(
                        check_name='repository_integrity_check',
                        message=f"Too many orphaned worktrees: {len(orphaned)} (max: {self.config['max_orphan_worktrees']})",
                        severity=ErrorSeverity.RECOVERABLE,
                        details={'orphaned_paths': [str(p) for p in orphaned[:10]]}
                    ))
                elif orphaned:
                    warnings.append(f"Found {len(orphaned)} orphaned worktree directories")
        
        except Exception as e:
            warnings.append(f"Failed to check repository integrity: {str(e)}")
        
        return errors, warnings
    
    def _is_lock_stale(self, lock_path: Path) -> tuple[bool, dict[str, Any]]:
        """Check if a lock file is stale (holder process no longer running)."""
        details: dict[str, Any] = {}  # Fix: use Any instead of restricting types
        
        try:
            stat = lock_path.stat()
            details['lock_age_seconds'] = time.time() - stat.st_mtime
            details['lock_size'] = stat.st_size
            
            # If lock is very old, likely stale
            if details['lock_age_seconds'] > 3600:  # 1 hour
                details['reason'] = 'lock_too_old'
                return True, details
            
            # Try to read PID from lock file if it contains one
            try:
                content = lock_path.read_text().strip()
                if content.isdigit():
                    pid = int(content)
                    details['pid'] = pid
                    
                    if not is_process_running(pid):
                        details['reason'] = 'process_not_running'
                        return True, details
                    else:
                        details['reason'] = 'process_still_running'
                        return False, details
            except (ValueError, OSError):
                # Lock file doesn't contain a valid PID
                pass
            
            # Default to not stale if we can't determine
            details['reason'] = 'cannot_determine'
            return False, details
            
        except OSError as e:
            details['error'] = str(e)
            return False, details
    
    def attempt_self_repair(self, health_result: HealthCheckResult) -> bool:
        """Attempt to automatically repair recoverable issues.
        
        Args:
            health_result: The result containing errors to attempt repair
            
        Returns:
            True if all repairs were successful, False otherwise
        """
        recoverable_errors = health_result.get_recoverable_errors()
        if not recoverable_errors:
            return True
        
        logger.info(f"Attempting self-repair for {len(recoverable_errors)} issues")
        
        repair_success = True
        max_attempts = self.config['max_repair_attempts']
        
        for error in recoverable_errors:
            error.recovery_attempted = True
            
            for attempt in range(1, max_attempts + 1):
                logger.info(f"Repair attempt {attempt}/{max_attempts} for {error.check_name}")
                
                try:
                    if error.check_name == 'git_status_check':
                        success = self._repair_git_status(error)
                    elif error.check_name == 'repository_integrity_check':
                        success = self._repair_repository_integrity(error)
                    elif error.check_name == 'lock_availability_check':
                        success = self._repair_lock_availability(error)
                    else:
                        logger.warning(f"No repair method for check: {error.check_name}")
                        success = False
                    
                    if success:
                        error.recovery_successful = True
                        logger.info(f"Successfully repaired {error.check_name}")
                        break
                    elif attempt < max_attempts:
                        logger.warning(f"Repair attempt {attempt} failed, retrying")
                        time.sleep(2 ** attempt)  # Exponential backoff
                    else:
                        logger.error(f"All repair attempts failed for {error.check_name}")
                        repair_success = False
                        
                except Exception as e:
                    logger.exception(f"Repair attempt {attempt} raised exception: {e}")
                    if attempt == max_attempts:
                        repair_success = False
        
        return repair_success
    
    def _repair_git_status(self, error: HealthCheckError) -> bool:
        """Repair git status issues (dirty working directory)."""
        try:
            # Try auto-commit first
            logger.info("Attempting auto-commit of uncommitted changes")
            result = subprocess.run(
                ['git', 'add', '-A'],
                capture_output=True, text=True, check=True,
                cwd=str(self.repo_path), timeout=30
            )
            
            result = subprocess.run(
                ['git', 'commit', '-m', 'chore: auto-commit for pre-flight health check'],
                capture_output=True, text=True,
                cwd=str(self.repo_path), timeout=60
            )
            
            if result.returncode == 0:
                logger.info("Auto-commit successful")
                return True
            
            # Auto-commit failed, try stashing
            logger.info("Auto-commit failed, attempting stash")
            result = subprocess.run(
                ['git', 'stash', 'push', '-m', 'pokepoke-preflight-stash'],
                capture_output=True, text=True, check=True,
                cwd=str(self.repo_path), timeout=60
            )
            
            logger.info("Stash successful")
            return True
            
        except subprocess.CalledProcessError as e:
            logger.warning(f"Git repair failed: {e.stderr or str(e)}")
            return False
        except Exception as e:
            logger.exception(f"Git repair failed with exception: {e}")
            return False
    
    def _repair_repository_integrity(self, error: HealthCheckError) -> bool:
        """Repair repository integrity issues (orphaned worktrees)."""
        try:
            orphaned_paths = error.details.get('orphaned_paths', [])
            
            for path_str in orphaned_paths:
                path = Path(path_str)
                if path.exists():
                    logger.info(f"Removing orphaned worktree directory: {path}")
                    shutil.rmtree(path, ignore_errors=True)
                    
                    # Verify removal
                    if path.exists():
                        logger.warning(f"Failed to remove orphaned worktree: {path}")
                        return False
            
            logger.info(f"Cleaned up {len(orphaned_paths)} orphaned worktree directories")
            return True
            
        except Exception as e:
            logger.exception(f"Repository integrity repair failed: {e}")
            return False
    
    def _repair_lock_availability(self, error: HealthCheckError) -> bool:
        """Repair lock availability issues (clear stale locks)."""
        try:
            lock_file = error.details.get('lock_file')
            if not lock_file:
                return False
            
            lock_path = Path(lock_file)
            if not lock_path.exists():
                return True  # Already gone
            
            # Double-check that the lock is actually stale
            is_stale, details = self._is_lock_stale(lock_path)
            if is_stale:
                logger.info(f"Removing stale lock: {lock_path}")
                lock_path.unlink()
                
                # Verify removal
                if lock_path.exists():
                    logger.warning(f"Failed to remove stale lock: {lock_path}")
                    return False
                
                logger.info(f"Successfully removed stale lock: {lock_path}")
                return True
            else:
                logger.warning(f"Lock is not stale, cannot remove: {lock_path}")
                return False
                
        except Exception as e:
            logger.exception(f"Lock repair failed: {e}")
            return False
    
    def _rerun_failed_checks(self, original_result: HealthCheckResult) -> HealthCheckResult:
        """Re-run checks that previously failed to verify repairs were successful."""
        # For simplicity, re-run all checks since repairs may have affected multiple areas
        # In a more sophisticated implementation, we could track which checks to re-run
        return self.run_all_checks()


def run_preflight_checks(repo_path: Path | None = None, config: dict[str, Any] | None = None) -> HealthCheckResult:
    """Convenience function to run pre-flight health checks.
    
    Args:
        repo_path: Path to the repository (defaults to current directory)
        config: Configuration dict for health check parameters
        
    Returns:
        HealthCheckResult with overall status and any issues found
    """
    checker = PreflightChecker(repo_path, config)
    return checker.run_all_checks()


def attempt_self_repair(health_result: HealthCheckResult, repo_path: Path | None = None, 
                       config: dict[str, Any] | None = None) -> bool:
    """Convenience function to attempt self-repair of health check issues.
    
    Args:
        health_result: The health check result containing errors to repair
        repo_path: Path to the repository (defaults to current directory)
        config: Configuration dict for repair parameters
        
    Returns:
        True if all repairs were successful, False otherwise
    """
    checker = PreflightChecker(repo_path, config)
    return checker.attempt_self_repair(health_result)