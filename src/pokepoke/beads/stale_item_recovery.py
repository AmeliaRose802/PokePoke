"""Recovery of stale in-progress items from previous orchestrator runs.

When the orchestrator restarts, items may remain in 'in_progress' status assigned
to agent names from a now-defunct orchestrator instance. These items often have
partially-complete worktrees with real progress (commits, tests) that would be
wasted if we simply reset them. This module identifies such items and provides
context to help the next agent resume where the previous one left off.
"""

import contextlib
import logging
import re
from pathlib import Path
from typing import Any

from pokepoke.types import BeadsWorkItem

logger = logging.getLogger(__name__)

# Pattern for PokePoke-generated agent names: pokepoke_{adjective}_{creature}_{hex}
# See pokepoke.agents.agent_names for the generation logic
_POKEPOKE_AGENT_PATTERN = re.compile(r"^pokepoke_[a-z]+_[a-z]+_[a-f0-9]{4}$", re.IGNORECASE)


def is_pokepoke_agent_name(name: str | None) -> bool:
    """Check if a name matches the PokePoke agent naming pattern.

    Args:
        name: Agent name to check.

    Returns:
        True if name matches pokepoke_{adjective}_{creature}_{hex} pattern.
    """
    if not name:
        return False
    return bool(_POKEPOKE_AGENT_PATTERN.match(name))


def get_stale_in_progress_items(
    current_agent_name: str,
    in_progress_items: list[BeadsWorkItem] | None = None,
) -> list[BeadsWorkItem]:
    """Identify in-progress items assigned to defunct PokePoke agents.

    An item is considered stale if:
    1. It has status 'in_progress'
    2. It's assigned to a PokePoke-style agent name
    3. That agent name is NOT the current orchestrator's agent

    Args:
        current_agent_name: This orchestrator's agent name.
        in_progress_items: List of in_progress items (fetched if None).

    Returns:
        List of stale items that can be reclaimed, sorted by priority.
    """
    if in_progress_items is None:
        from pokepoke.beads.beads_query import get_in_progress_items
        in_progress_items = get_in_progress_items()

    if not in_progress_items:
        return []

    stale_items: list[BeadsWorkItem] = []
    for item in in_progress_items:
        assignee = item.assignee
        if not assignee:
            # Unassigned in_progress item - shouldn't happen but is reclaimable
            logger.debug("Found unassigned in_progress item: %s", item.id)
            stale_items.append(item)
            continue

        # Skip if assigned to current agent (we're already working on it)
        if assignee.lower() == current_agent_name.lower():
            continue

        # Check if this is a PokePoke agent name from a previous run
        if is_pokepoke_agent_name(assignee):
            logger.info(
                "Found stale in_progress item %s assigned to defunct agent %s",
                item.id, assignee,
            )
            stale_items.append(item)

    # Sort by priority (lower number = higher priority)
    return sorted(stale_items, key=lambda x: x.priority)


def get_worktree_path_for_item(item_id: str, repo_path: Path | None = None) -> Path | None:
    """Get the expected worktree path for an item if it exists.

    Args:
        item_id: Beads item ID.
        repo_path: Repository root (defaults to cwd).

    Returns:
        Path to existing worktree directory, or None if not found.
    """
    from pokepoke.git.git_operations import sanitize_branch_name
    from pokepoke.utils.constants import WORKTREE_DIR, WORKTREE_TASK_PREFIX

    repo_root = repo_path or Path.cwd()
    sanitized_id = sanitize_branch_name(item_id)
    worktree_path = repo_root / WORKTREE_DIR / f"{WORKTREE_TASK_PREFIX}{sanitized_id}"

    if worktree_path.exists() and worktree_path.is_dir():
        return worktree_path
    return None


def get_worktree_commit_count(worktree_path: Path) -> int:
    """Count commits ahead of the base branch in a worktree.

    Args:
        worktree_path: Path to worktree directory.

    Returns:
        Number of commits ahead of origin/main (or 0 on error).
    """
    from pokepoke.git.git_helpers import run_git

    try:
        # Get commits ahead of origin/main
        result = run_git(
            ["git", "rev-list", "--count", "origin/main..HEAD"],
            cwd=str(worktree_path),
            timeout=10,
            check=False,
        )
        if result.returncode == 0:
            return int(result.stdout.strip())
    except (ValueError, Exception) as e:
        logger.debug("Failed to count commits in %s: %s", worktree_path, e)
    return 0


def get_recent_commit_messages(worktree_path: Path, max_commits: int = 5) -> list[str]:
    """Get recent commit messages from a worktree for context.

    Args:
        worktree_path: Path to worktree directory.
        max_commits: Maximum number of commits to retrieve.

    Returns:
        List of commit subject lines (most recent first).
    """
    from pokepoke.git.git_helpers import run_git

    try:
        result = run_git(
            ["git", "log", f"--max-count={max_commits}", "--oneline", "--format=%s"],
            cwd=str(worktree_path),
            timeout=10,
            check=False,
        )
        if result.returncode == 0 and result.stdout.strip():
            return [line.strip() for line in result.stdout.strip().split('\n') if line.strip()]
    except Exception as e:
        logger.debug("Failed to get commit messages from %s: %s", worktree_path, e)
    return []


def get_modified_files_in_worktree(worktree_path: Path) -> list[str]:
    """Get list of files modified in worktree compared to base.

    Args:
        worktree_path: Path to worktree directory.

    Returns:
        List of file paths that were modified.
    """
    from pokepoke.git.git_helpers import run_git

    try:
        # Get files changed since branching from origin/main
        result = run_git(
            ["git", "diff", "--name-only", "origin/main...HEAD"],
            cwd=str(worktree_path),
            timeout=10,
            check=False,
        )
        if result.returncode == 0 and result.stdout.strip():
            return [line.strip() for line in result.stdout.strip().split('\n') if line.strip()]
    except Exception as e:
        logger.debug("Failed to get modified files from %s: %s", worktree_path, e)
    return []


def build_resume_context(
    item: BeadsWorkItem,
    repo_path: Path | None = None,
) -> dict[str, str | list[str] | int] | None:
    """Build context for resuming work on a stale item.

    Examines the existing worktree (if any) to extract information about
    previous progress that can help the next agent pick up where work left off.

    Args:
        item: The stale work item to build context for.
        repo_path: Repository root (defaults to cwd).

    Returns:
        Dict with resume context, or None if no useful context found.
        Keys: previous_assignee, commit_count, commits, modified_files
    """
    worktree_path = get_worktree_path_for_item(item.id, repo_path)
    if not worktree_path:
        logger.debug("No existing worktree found for %s", item.id)
        return None

    commit_count = get_worktree_commit_count(worktree_path)
    if commit_count == 0:
        logger.debug("Worktree for %s has no commits ahead", item.id)
        return None

    commits = get_recent_commit_messages(worktree_path)
    modified_files = get_modified_files_in_worktree(worktree_path)

    context: dict[str, str | list[str] | int] = {
        "previous_assignee": item.assignee or "unknown",
        "commit_count": commit_count,
        "commits": commits,
        "modified_files": modified_files[:20],  # Cap to avoid huge lists
        "worktree_path": str(worktree_path),
    }

    logger.info(
        "Built resume context for %s: %d commits, %d files modified",
        item.id, commit_count, len(modified_files),
    )
    return context


def recover_stale_items_for_orchestrator(
    agent_name: str,
    enabled: bool,
    log_orchestrator: Any = None,
) -> list[BeadsWorkItem]:
    """Discover stale in_progress items and log a one-line summary.

    Higher-level helper used by the orchestrator's setup phase so the
    orchestrator itself stays small. Never raises; returns [] on error.

    Args:
        agent_name: Current orchestrator's agent name.
        enabled: If False, recovery is skipped and [] is returned.
        log_orchestrator: Optional callable (message: str) for run log.

    Returns:
        List of stale items (sorted by priority) that should be prioritized.
    """
    if not enabled:
        logger.debug("Stale item recovery is disabled")
        return []
    try:
        stale_items = get_stale_in_progress_items(agent_name)
        if not stale_items:
            logger.debug("No stale in-progress items found")
            return []
        logger.info(f"♻️  Found {len(stale_items)} stale in-progress item(s) to reclaim:")
        for item in stale_items:
            context = build_resume_context(item)
            if context:
                commit_count = context.get("commit_count", 0)
                logger.info(f"   • {item.id}: {item.title[:50]}... ({commit_count} commits ahead)")
            else:
                logger.info(f"   • {item.id}: {item.title[:50]}... (no worktree progress)")
        if log_orchestrator is not None:
            log_orchestrator(
                f"Recovered {len(stale_items)} stale in-progress item(s) for priority processing"
            )
        return stale_items
    except Exception as e:
        logger.warning(f"⚠️  Stale item recovery failed: {e}")
        if log_orchestrator is not None:
            with contextlib.suppress(Exception):
                log_orchestrator(f"Stale item recovery error: {e}", level="WARNING")
        return []


def format_resume_context_for_prompt(context: dict[str, str | list[str] | int]) -> str:
    """Format resume context into a prompt section for the AI agent.

    Args:
        context: Resume context dict from build_resume_context().

    Returns:
        Formatted string to include in the agent prompt.
    """
    parts: list[str] = [
        "## Previous Work Session Context",
        "",
        "This item was previously being worked on by another agent that was interrupted.",
        f"Previous agent: {context.get('previous_assignee', 'unknown')}",
        f"Commits made: {context.get('commit_count', 0)}",
    ]

    commits = context.get("commits", [])
    if commits and isinstance(commits, list):
        parts.append("")
        parts.append("**Recent commits:**")
        parts.extend(f"- {commit}" for commit in commits[:5])

    modified_files = context.get("modified_files", [])
    if modified_files and isinstance(modified_files, list):
        parts.append("")
        parts.append("**Files previously modified:**")
        parts.extend(f"- {f}" for f in modified_files[:10])
        if len(modified_files) > 10:
            parts.append(f"- ... and {len(modified_files) - 10} more files")

    parts.extend([
        "",
        "**Instructions:** Review the existing commits and continue from where the previous",
        "agent left off. Do NOT redo work that has already been committed. Focus on:",
        "1. Understanding what was already done by examining the commits",
        "2. Identifying what remains to complete the task",
        "3. Completing the remaining work and ensuring all quality gates pass",
    ])

    return "\n".join(parts)
