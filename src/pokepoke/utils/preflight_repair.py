"""Self-repair functions for pre-flight health check failures.

Provides automatic repair capabilities for recoverable issues found
during pre-flight health checks, such as dirty git state, orphaned
worktrees, and stale lock files.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from pokepoke.utils.constants import STATUS_IN_PROGRESS
from pokepoke.git.git_helpers import run_git
from pokepoke.utils.preflight_checks import HealthCheckError, is_lock_stale

logger = logging.getLogger(__name__)


def repair_git_status(error: HealthCheckError, repo_path: Path) -> bool:
    """Repair git status issues (dirty working directory).

    Uses targeted staging (tracked files only via ``git add -u``) and
    attempts to commit.  If the commit fails (e.g. pre-commit hooks
    reject it), a cleanup agent is invoked to fix the issues instead of
    stashing — uncommitted work is **never** discarded or hidden.
    """
    try:
        logger.warning(
            "Uncommitted changes detected in %s – attempting targeted commit",
            repo_path,
        )

        # Stage only tracked-file changes (not untracked files / temp files)
        run_git(
            ['git', 'add', '-u'],
            cwd=str(repo_path),
        )

        result = run_git(
            ['git', 'commit', '-m', 'chore: auto-commit for pre-flight health check'],
            cwd=str(repo_path), timeout=60, check=False,
        )

        if result.returncode == 0:
            logger.info("Auto-commit of tracked changes successful")
            return True

        # Commit failed – invoke cleanup agent instead of stashing
        commit_error = result.stderr.strip() if result.stderr else "Unknown commit failure"
        logger.warning(
            "Auto-commit failed: %s. Invoking cleanup agent to fix issues.",
            commit_error,
        )
        return _invoke_preflight_cleanup(repo_path, commit_error)

    except subprocess.CalledProcessError as e:
        logger.warning("Git repair failed: %s", e.stderr or str(e))
        return False
    except Exception as e:
        logger.exception("Git repair failed with exception: %s", e)
        return False


def _invoke_preflight_cleanup(repo_path: Path, commit_error: str) -> bool:
    """Invoke cleanup agent to fix commit failures during preflight repair.

    Creates a synthetic work item and delegates to the existing cleanup
    agent infrastructure so that test failures, lint errors, etc. are
    fixed and committed properly.  Returns *False* (never raises) when
    the cleanup agent is unavailable or fails.
    """
    try:
        from pokepoke.agents.cleanup_agents import invoke_cleanup_agent  # noqa: F811
        from pokepoke.types import BeadsWorkItem
    except ImportError:
        logger.warning(
            "Cleanup agent infrastructure not available. "
            "Cannot auto-fix commit failures – please fix issues manually."
        )
        return False

    cleanup_item = BeadsWorkItem(
        id="preflight-repair",
        title="Preflight repair: fix commit failures",
        description=(
            "The pre-flight health check found uncommitted changes and attempted "
            f"to commit them, but the commit failed with:\n\n{commit_error}\n\n"
            "Fix the issues (test failures, lint errors, etc.) and commit the changes."
        ),
        status=STATUS_IN_PROGRESS,
        priority=0,
        issue_type="task",
        labels=["preflight", "automated"],
    )

    try:
        logger.info("Invoking cleanup agent for preflight repair")
        success, _stats = invoke_cleanup_agent(
            cleanup_item,
            cwd=str(repo_path),
            wait_for_merge=False,
        )
    except Exception as e:
        logger.warning("Cleanup agent raised an exception: %s", e, exc_info=True)
        return False

    if success:
        logger.info("Cleanup agent fixed issues – preflight repair successful")
    else:
        logger.warning(
            "Cleanup agent could not fix commit failures. "
            "Uncommitted changes remain in the working directory – "
            "please review and fix issues manually."
        )

    return success


def repair_repository_integrity(error: HealthCheckError) -> bool:
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


def repair_lock_availability(error: HealthCheckError, repo_path: Path) -> bool:
    """Repair lock availability issues (clear stale locks)."""
    try:
        lock_file = error.details.get('lock_file')
        if not lock_file:
            return False

        lock_path = Path(lock_file)
        if not lock_path.exists():
            return True  # Already gone

        # Double-check that the lock is actually stale
        stale, details = is_lock_stale(lock_path)
        if stale:
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


def attempt_repair(
    health_result: Any,
    repo_path: Path,
    config: dict[str, Any],
) -> bool:
    """Attempt to automatically repair recoverable issues.

    Args:
        health_result: The HealthCheckResult containing errors to attempt repair
        repo_path: Path to the repository root
        config: Configuration dict for repair parameters

    Returns:
        True if all repairs were successful, False otherwise
    """
    recoverable_errors = health_result.get_recoverable_errors()
    if not recoverable_errors:
        return True

    logger.info(f"Attempting self-repair for {len(recoverable_errors)} issues")

    repair_success = True
    max_attempts = config.get('max_repair_attempts', 3)

    for error in recoverable_errors:
        error.recovery_attempted = True

        for attempt in range(1, max_attempts + 1):
            logger.info(f"Repair attempt {attempt}/{max_attempts} for {error.check_name}")

            try:
                if error.check_name == 'git_status_check':
                    success = repair_git_status(error, repo_path)
                elif error.check_name == 'repository_integrity_check':
                    success = repair_repository_integrity(error)
                elif error.check_name == 'lock_availability_check':
                    success = repair_lock_availability(error, repo_path)
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
