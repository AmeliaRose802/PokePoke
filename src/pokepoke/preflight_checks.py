"""Pre-flight health check implementations.

Individual check functions used by PreflightChecker to validate
environment readiness before work batch processing.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pokepoke.git_operations import has_uncommitted_changes, categorize_git_changes, list_worktrees
from pokepoke.process_utils import is_process_running

logger = logging.getLogger(__name__)

# Re-use shared types from preflight_health to avoid circular imports.
# These are imported lazily or passed in to check functions.


@dataclass
class HealthCheckError:
    """Represents a health check failure with context."""
    check_name: str
    message: str
    severity: str
    details: dict[str, Any] = field(default_factory=dict)
    recovery_attempted: bool = False
    recovery_successful: bool = False


class ErrorSeverity:
    """Classification of error severity for proper handling."""
    ENVIRONMENTAL = "environmental"  # Stop all work
    ITEM_SPECIFIC = "item_specific"  # Skip item, continue
    RECOVERABLE = "recoverable"      # Attempt self-repair
    CRITICAL = "critical"            # Immediate shutdown


def check_git_status(
    repo_path: Path, config: dict[str, Any]
) -> tuple[list[HealthCheckError], list[str]]:
    """Check that git repository is in a clean state."""
    errors: list[HealthCheckError] = []
    warnings: list[str] = []

    try:
        # Check if we're in a git repository
        if not (repo_path / '.git').exists():
            errors.append(HealthCheckError(
                check_name='git_status_check',
                message=f"Not a git repository: {repo_path}",
                severity=ErrorSeverity.CRITICAL,
                details={'repo_path': str(repo_path)}
            ))
            return errors, warnings

        # Check for uncommitted changes
        if has_uncommitted_changes(cwd=str(repo_path)):
            try:
                result = subprocess.run(
                    ['git', 'status', '--porcelain'],
                    capture_output=True, text=True, check=True,
                    cwd=str(repo_path), timeout=config['git_operation_timeout']
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
                    details={'timeout': config['git_operation_timeout']}
                ))

    except Exception as e:
        errors.append(HealthCheckError(
            check_name='git_status_check',
            message=f"Git status check failed: {str(e)}",
            severity=ErrorSeverity.ENVIRONMENTAL,
            details={'exception': str(e)}
        ))

    return errors, warnings


def check_worktree_creation(
    repo_path: Path, config: dict[str, Any]
) -> tuple[list[HealthCheckError], list[str]]:
    """Test that worktrees can be created successfully."""
    errors: list[HealthCheckError] = []
    warnings: list[str] = []

    # Generate a unique test worktree name
    test_id = f"health-check-{uuid.uuid4().hex[:8]}"
    test_worktree_path = repo_path / "worktrees" / f"test-{test_id}"
    test_branch = f"test/health-check-{test_id}"

    try:
        # Ensure worktrees directory exists
        (repo_path / "worktrees").mkdir(exist_ok=True)

        # Try to create a test worktree
        cmd = [
            'git', 'worktree', 'add', str(test_worktree_path),
            '-b', test_branch, 'HEAD'
        ]

        subprocess.run(
            cmd, capture_output=True, text=True, check=True,
            cwd=str(repo_path), timeout=config['worktree_test_timeout']
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
            details={'timeout': config['worktree_test_timeout']}
        ))
    finally:
        # Clean up test worktree
        try:
            if test_worktree_path.exists():
                subprocess.run(
                    ['git', 'worktree', 'remove', '--force', str(test_worktree_path)],
                    capture_output=True, cwd=str(repo_path), timeout=30
                )
            # Clean up test branch
            subprocess.run(
                ['git', 'branch', '-D', test_branch],
                capture_output=True, cwd=str(repo_path), timeout=30
            )
        except Exception as cleanup_error:
            warnings.append(f"Failed to clean up test worktree: {cleanup_error}")

    return errors, warnings


def check_lock_availability(
    repo_path: Path, config: dict[str, Any]
) -> tuple[list[HealthCheckError], list[str]]:
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
        lock_path = repo_path / lock_file

        if lock_path.exists():
            try:
                # Check if the lock is stale
                stale, details = is_lock_stale(lock_path)

                if stale:
                    warnings.append(f"Stale lock detected: {lock_file}")
                    if config.get('enable_self_repair', True):
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


def check_disk_space(
    repo_path: Path, config: dict[str, Any]
) -> tuple[list[HealthCheckError], list[str]]:
    """Check that sufficient disk space is available."""
    errors: list[HealthCheckError] = []
    warnings: list[str] = []

    try:
        disk_usage = shutil.disk_usage(str(repo_path))
        free_gb = disk_usage.free / (1024**3)
        min_required = config['min_disk_space_gb']

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


def check_repository_integrity(
    repo_path: Path, config: dict[str, Any]
) -> tuple[list[HealthCheckError], list[str]]:
    """Check for orphaned worktrees and other repository integrity issues."""
    errors: list[HealthCheckError] = []
    warnings: list[str] = []

    try:
        # Check for orphaned worktrees
        worktrees = list_worktrees()
        worktree_paths = [Path(wt['path']) for wt in worktrees if 'path' in wt]

        # Find orphaned worktree directories
        worktrees_dir = repo_path / 'worktrees'
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

            if len(orphaned) > config['max_orphan_worktrees']:
                errors.append(HealthCheckError(
                    check_name='repository_integrity_check',
                    message=f"Too many orphaned worktrees: {len(orphaned)} (max: {config['max_orphan_worktrees']})",
                    severity=ErrorSeverity.RECOVERABLE,
                    details={'orphaned_paths': [str(p) for p in orphaned[:10]]}
                ))
            elif orphaned:
                warnings.append(f"Found {len(orphaned)} orphaned worktree directories")

    except Exception as e:
        warnings.append(f"Failed to check repository integrity: {str(e)}")

    return errors, warnings


def is_lock_stale(lock_path: Path) -> tuple[bool, dict[str, Any]]:
    """Check if a lock file is stale (holder process no longer running)."""
    details: dict[str, Any] = {}

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
