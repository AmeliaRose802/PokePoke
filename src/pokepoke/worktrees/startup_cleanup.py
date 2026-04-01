"""Startup cleanup of stale worktrees for PokePoke.

Automatically cleans up worktrees from previous runs that are significantly
behind master (e.g., >20 commits behind) at orchestrator startup.
"""

import logging
from pathlib import Path

from pokepoke.config import ProjectConfig, get_config
from pokepoke.git.git_helpers import get_commits_behind, list_worktrees
from pokepoke.worktrees.coordination import with_worktree_lock
from pokepoke.worktrees.worktree_cleanup import cleanup_worktree_and_branch
from pokepoke.worktrees.worktrees import is_worktree_merged

logger = logging.getLogger(__name__)

def cleanup_stale_worktrees_at_startup(
    repo_path: str | None = None,
    cfg: ProjectConfig | None = None
) -> dict[str, int]:
    """Clean up stale worktrees at orchestrator startup.

    Removes worktrees that are either:
    1. Significantly behind master (> threshold commits)
    2. Already merged and pushed (regardless of distance)

    Args:
        repo_path: Path to the repository (defaults to current working directory)
        cfg: Project configuration (defaults to loaded config)

    Returns:
        Dict with cleanup statistics: {
            'stale_removed': int,       # Worktrees removed due to being behind
            'merged_removed': int,      # Worktrees removed due to being merged
            'total_removed': int,       # Total worktrees removed
            'errors': int,              # Number of cleanup errors
            'checked': int,             # Total worktrees checked
        }
    """
    if cfg is None:
        cfg = get_config()

    if not cfg.startup_cleanup_enabled:
        logger.debug("Startup worktree cleanup is disabled")
        return {
            'stale_removed': 0,
            'merged_removed': 0,
            'total_removed': 0,
            'errors': 0,
            'checked': 0,
        }

    repo_path = repo_path or str(Path.cwd())
    threshold = cfg.stale_worktree_commit_threshold

    logger.info(f"🧹 Starting worktree cleanup (threshold: {threshold} commits)")

    stats = {
        'stale_removed': 0,
        'merged_removed': 0,
        'total_removed': 0,
        'errors': 0,
        'checked': 0,
    }

    try:
        # Get the default branch to compare against
        default_branch = _get_default_branch(repo_path, cfg)
        logger.debug(f"Using '{default_branch}' as the default branch for comparison")

        # List all worktrees
        worktrees = list_worktrees(cwd=repo_path)
        logger.debug(f"Found {len(worktrees)} worktrees to check")

        for wt in worktrees:
            # Skip the main repository worktree
            if not wt.get('branch'):
                logger.debug(f"Skipping main repo worktree at {wt.get('path', 'unknown')}")
                continue

            stats['checked'] += 1
            branch = wt['branch']
            worktree_path = wt['path']

            logger.debug(f"Checking worktree: {branch} at {worktree_path}")

            try:
                # Check if the branch is already merged
                # Extract item_id from branch name since is_worktree_merged expects item_id
                if branch.startswith("task/"):
                    item_id = branch[5:]  # Remove "task/" prefix to get the item_id
                    is_merged = is_worktree_merged(item_id, default_branch, repo_path)
                else:
                    # For non-standard branch names, use the full branch name as item_id
                    is_merged = is_worktree_merged(branch, default_branch, repo_path)
                
                if is_merged:
                    logger.info(f"🔗 Removing merged worktree: {branch}")
                    _cleanup_worktree_safe(branch, worktree_path, repo_path)
                    stats['merged_removed'] += 1
                    continue

                # Check how many commits behind the branch is
                commits_behind = get_commits_behind(branch, default_branch, cwd=repo_path)

                if commits_behind is None:
                    logger.debug(f"Could not determine commits behind for {branch}")
                    continue

                logger.debug(f"Branch {branch} is {commits_behind} commits behind {default_branch}")

                if commits_behind > threshold:
                    logger.info(f"🗑️  Removing stale worktree: {branch} ({commits_behind} commits behind)")
                    _cleanup_worktree_safe(branch, worktree_path, repo_path)
                    stats['stale_removed'] += 1
                else:
                    logger.debug(f"Keeping worktree {branch} ({commits_behind} <= {threshold} commits behind)")

            except Exception as e:
                logger.warning(f"Failed to process worktree {branch}: {e}")
                stats['errors'] += 1

        stats['total_removed'] = stats['stale_removed'] + stats['merged_removed']

        if stats['total_removed'] > 0:
            logger.info(
                f"✅ Cleanup complete: {stats['total_removed']} worktrees removed "
                f"({stats['stale_removed']} stale, {stats['merged_removed']} merged)"
            )
        else:
            logger.debug("No worktrees required cleanup")

    except Exception as e:
        logger.error(f"Error during startup worktree cleanup: {e}")
        stats['errors'] += 1

    return stats


def _get_default_branch(repo_path: str, cfg: ProjectConfig) -> str:
    """Get the default branch name to compare against.

    Uses the configured default branch if available, otherwise falls back to
    the GitConfig fallback branch.
    """
    # Use the configured default branch if specified
    if cfg.git.default_branch:
        return cfg.git.default_branch

    # Fall back to the configured fallback branch
    return cfg.git.fallback_branch


def _cleanup_worktree_safe(branch: str, worktree_path: str, repo_path: str) -> None:
    """Safely clean up a worktree with proper locking.

    Args:
        branch: Branch name to clean up
        worktree_path: Path to the worktree directory
        repo_path: Path to the repository
    """
    try:
        # Use the coordination lock to prevent race conditions
        with with_worktree_lock():
            # Extract the item ID from the branch name for cleanup
            # Branch format is typically "task/sanitized-item-id"
            if branch.startswith("task/"):
                item_id = branch[5:]  # Remove "task/" prefix
            else:
                # Fallback - use the branch name as-is
                item_id = branch

            cleanup_worktree_and_branch(
                worktree_path=Path(worktree_path),
                branch_name=branch,
                worktree_id=item_id,
                cwd=repo_path,
            )

    except Exception as e:
        # Log the error but don't re-raise to avoid stopping the entire cleanup process
        logger.warning(f"Failed to cleanup worktree {branch}: {e}")
        raise
