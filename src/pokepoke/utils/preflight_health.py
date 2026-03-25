"""Pre-flight health checks and self-repair system for PokePoke.

This module implements comprehensive health checks that run before work batch processing
to prevent submission to broken environments. It includes automatic self-repair
capabilities and graceful shutdown with diagnostics on unrecoverable failures.

The system addresses the issue where broken environments (stale locks, dirty git state)
caused silent failures with 0 agent requests by implementing proactive health gates.

Check implementations live in preflight_checks.py and repair logic in preflight_repair.py.
"""

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pokepoke.utils.preflight_checks import (
    ErrorSeverity,
    HealthCheckError,
    check_disk_space,
    check_git_status,
    check_lock_availability,
    check_repository_integrity,
    check_worktree_creation,
    is_lock_stale,
)
from pokepoke.utils.preflight_repair import (
    attempt_repair,
    repair_git_status,
    repair_lock_availability,
    repair_repository_integrity,
)

logger = logging.getLogger(__name__)

# Re-export for backward compatibility
__all__ = [
    'ErrorSeverity',
    'HealthCheckError',
    'HealthCheckResult',
    'PreflightChecker',
    'attempt_self_repair',
    'run_preflight_checks'
]

# Re-export from preflight_checks for backward compatibility
HealthCheckError = HealthCheckError
ErrorSeverity = ErrorSeverity


@dataclass
class HealthCheckResult:
    """Result of running pre-flight health checks."""
    passed: bool = False
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
        result = HealthCheckResult(passed=False)

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
                    message=f"Health check failed with exception: {e!s}",
                    severity=ErrorSeverity.ENVIRONMENTAL,
                    details={'exception': str(e)}
                ))

        result.duration_seconds = time.time() - start_time
        result.passed = len(result.errors) == 0

        # Only attempt self-repair when there are recoverable errors
        if (not result.passed
                and self.config.get('enable_self_repair', True)
                and result.get_recoverable_errors()):
            logger.info("Health checks failed, attempting self-repair")
            result.self_repair_attempted = True
            result.self_repair_successful = self.attempt_self_repair(result)

            if result.self_repair_successful:
                logger.info("Self-repair completed, re-running failed checks")
                rerun_result = self._rerun_failed_checks(result)
                rerun_result.self_repair_attempted = True
                rerun_result.self_repair_successful = True
                result = rerun_result

        logger.info(f"Pre-flight health checks completed in {result.duration_seconds:.2f}s - "
                   f"{'PASSED' if result.passed else 'FAILED'}")

        return result

    # -- Delegation methods to standalone check/repair functions --

    def _check_git_status(self) -> tuple[list[HealthCheckError], list[str]]:
        """Delegate to check_git_status."""
        return check_git_status(self.repo_path, self.config)

    def _check_worktree_creation(self) -> tuple[list[HealthCheckError], list[str]]:
        """Delegate to check_worktree_creation."""
        return check_worktree_creation(self.repo_path, self.config)

    def _check_lock_availability(self) -> tuple[list[HealthCheckError], list[str]]:
        """Delegate to check_lock_availability."""
        return check_lock_availability(self.repo_path, self.config)

    def _check_disk_space(self) -> tuple[list[HealthCheckError], list[str]]:
        """Delegate to check_disk_space."""
        return check_disk_space(self.repo_path, self.config)

    def _check_repository_integrity(self) -> tuple[list[HealthCheckError], list[str]]:
        """Delegate to check_repository_integrity."""
        return check_repository_integrity(self.repo_path, self.config)

    def _is_lock_stale(self, lock_path: Path) -> tuple[bool, dict[str, Any]]:
        """Delegate to is_lock_stale."""
        return is_lock_stale(lock_path)

    def attempt_self_repair(self, health_result: HealthCheckResult) -> bool:
        """Delegate to attempt_repair."""
        return attempt_repair(health_result, self.repo_path, self.config)

    def _repair_git_status(self, error: HealthCheckError) -> bool:
        """Delegate to repair_git_status."""
        return repair_git_status(error, self.repo_path)

    def _repair_repository_integrity(self, error: HealthCheckError) -> bool:
        """Delegate to repair_repository_integrity."""
        return repair_repository_integrity(error)

    def _repair_lock_availability(self, error: HealthCheckError) -> bool:
        """Delegate to repair_lock_availability."""
        return repair_lock_availability(error, self.repo_path)

    def _rerun_failed_checks(self, original_result: HealthCheckResult) -> HealthCheckResult:
        """Re-run checks without self-repair to verify repairs were successful."""
        saved = self.config.get('enable_self_repair', True)
        self.config['enable_self_repair'] = False
        try:
            return self.run_all_checks()
        finally:
            self.config['enable_self_repair'] = saved


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
