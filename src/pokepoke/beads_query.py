"""Beads query operations - fetch work items and dependencies."""

import dataclasses
import json
import logging
import subprocess
from pathlib import Path
from typing import Any

from .coordination import beads_db_lock
from .perf_timing import timed_block
from .types import BeadsWorkItem, IssueWithDependencies, Dependency, BeadsStats


logger = logging.getLogger(__name__)


_MUTATING_BD_COMMANDS: frozenset[str] = frozenset({
    "update",
    "close",
    "sync",
    "comments",
})


def _run_bd(
    args: list[str],
    *,
    check: bool = True,
    timeout: int | None = 30,
    cwd: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a ``bd`` CLI command with standard options.

    IMPORTANT: All mutating beads operations are serialized through a single
    global lock to prevent SQLite lock contention in parallel mode.
    """
    cmd = args[0] if args else ""

    def _run() -> subprocess.CompletedProcess[str]:
        with timed_block(f"bd.{cmd}" if cmd else "bd.unknown"):
            return subprocess.run(
                ['bd'] + args,
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace',
                check=check,
                timeout=timeout,
                cwd=cwd,
            )

    if cmd in _MUTATING_BD_COMMANDS:
        # Default timeout of 180s is intentionally larger than the bd subprocess
        # timeout so contention queues rather than timing out inside SQLite.
        lock_timeout = 180.0
        with beads_db_lock(timeout=lock_timeout):
            return _run()

    return _run()


def _filter_to_dataclass(cls: type, data: dict[str, Any]) -> Any:
    """Construct a dataclass instance, keeping only fields defined on *cls*."""
    valid = {f.name for f in dataclasses.fields(cls)}
    return cls(**{k: v for k, v in data.items() if k in valid})


def _parse_beads_json(output: str, extra_prefixes: tuple[str, ...] = ()) -> Any:
    """Parse JSON from beads CLI output, filtering warning/note lines.

    Args:
        output: Raw stdout from a beads command.
        extra_prefixes: Additional line prefixes to filter out (e.g., 'Created').

    Returns:
        Parsed JSON data, or None if no JSON found.
    """
    prefixes = ('Note:', 'Warning:', 'Hint:') + extra_prefixes
    filtered_lines = [
        line for line in output.split('\n')
        if line.strip() and not line.strip().startswith(prefixes)
    ]
    json_start = next(
        (i for i, line in enumerate(filtered_lines)
         if line.strip().startswith('[') or line.strip().startswith('{')),
        None
    )
    if json_start is None:
        return None
    json_text = '\n'.join(filtered_lines[json_start:])
    return json.loads(json_text)


def _get_main_repo_root() -> Path | None:
    """Get the main repository root directory (not a worktree).

    Returns:
        Path to the main repo root, or None if not in a git repository.
    """
    from .git_operations import get_main_repo_root
    try:
        return get_main_repo_root()
    except RuntimeError:
        return None


def get_ready_work_items() -> list[BeadsWorkItem]:
    """Query beads database for ready work items.

    Returns:
        List of ready work items. Returns empty list if beads command fails.
    """
    try:
        result = _run_bd(['ready', '--json'])
    except subprocess.CalledProcessError as e:
        # Log error but don't crash the orchestrator
        # This can happen when beads database is temporarily unavailable
        logger.warning(f"⚠️  Warning: beads ready command failed (exit code {e.returncode})")
        if e.stderr:
            logger.warning(f"⚠️  Error output: {e.stderr.strip()}")
        return []
    except subprocess.TimeoutExpired:
        logger.warning("⚠️  Warning: beads ready command timed out after 30 seconds")
        return []
    except Exception as e:
        logger.warning(f"⚠️  Warning: unexpected error querying beads: {e}")
        return []

    if not result.stdout:
        return []

    try:
        items_data = _parse_beads_json(result.stdout)
        if not items_data:
            return []

        return [_filter_to_dataclass(BeadsWorkItem, item) for item in items_data]
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        logger.warning(f"⚠️  Warning: failed to parse beads output: {e}")
        return []


def get_issue_dependencies(issue_id: str) -> IssueWithDependencies | None:
    """Get detailed issue information including dependencies.

    Args:
        issue_id: The issue ID to query.

    Returns:
        Issue with dependencies, or None if not found.
    """
    try:
        result = _run_bd(['show', issue_id, '--json'])
    except subprocess.CalledProcessError:
        return None
    except subprocess.TimeoutExpired:
        logger.warning("Timed out querying dependencies for %s", issue_id)
        return None
    except Exception as e:
        logger.warning("Unexpected error querying dependencies for %s: %s", issue_id, e)
        return None

    if not result.stdout:
        return None

    try:
        issues_data = _parse_beads_json(result.stdout)
        if not issues_data:
            return None

        if not isinstance(issues_data, list) or len(issues_data) == 0:
            return None

        issue_dict = issues_data[0]

        filtered_issue = {k: v for k, v in issue_dict.items()
                          if k in {f.name for f in dataclasses.fields(IssueWithDependencies)}}

        # Convert dependencies if present
        if 'dependencies' in filtered_issue and filtered_issue['dependencies']:
            filtered_issue['dependencies'] = [
                _filter_to_dataclass(Dependency, dep)
                for dep in filtered_issue['dependencies']
            ]

        if 'dependents' in filtered_issue and filtered_issue['dependents']:
            filtered_issue['dependents'] = [
                _filter_to_dataclass(Dependency, dep)
                for dep in filtered_issue['dependents']
            ]

        return IssueWithDependencies(**filtered_issue)
    except (json.JSONDecodeError, KeyError, TypeError, IndexError) as e:
        logger.warning("Failed to parse issue dependencies for %s: %s", issue_id, e)
        return None


def has_unmet_blocking_dependencies(item_id: str) -> bool:
    """Check if an item or any of its ancestors has unmet blocking dependencies.

    An item should not be worked on if it (or any parent in the hierarchy) has
    dependencies with type 'blocks' that are not in 'closed' status.  This
    prevents children of blocked parents from appearing in the ready queue.

    Args:
        item_id: The issue ID to check.

    Returns:
        True if the item or any ancestor has unmet blocking dependencies,
        False otherwise.
    """
    return _has_unmet_blocking_in_chain(item_id, _visited=set())


def _has_unmet_blocking_in_chain(item_id: str, *, _visited: set[str]) -> bool:
    """Walk up the parent chain checking for unmet blocking dependencies.

    Args:
        item_id: The issue ID to check.
        _visited: Set of already-visited IDs to prevent infinite loops.

    Returns:
        True if this item or any ancestor has an unmet blocker.
    """
    if item_id in _visited:
        return False
    _visited.add(item_id)

    issue = get_issue_dependencies(item_id)
    if not issue or not issue.dependencies:
        return False

    # Check this item's own blocking dependencies
    if any(
        dep.dependency_type == 'blocks' and dep.status != 'closed'
        for dep in issue.dependencies
    ):
        return True

    # Walk up to parent and check its chain
    parent_dep = next(
        (dep for dep in issue.dependencies if dep.dependency_type == 'parent'),
        None,
    )
    if parent_dep:
        return _has_unmet_blocking_in_chain(parent_dep.id, _visited=_visited)

    return False


def is_beads_item_closed(item_id: str) -> bool:
    """Check if a beads item is already closed by querying its current status.

    Performs a live ``bd show`` to get the freshest status, preventing the
    orchestrator from re-processing items that were closed between the last
    ``bd ready`` fetch and the current assignment attempt.

    Args:
        item_id: The issue ID to check.

    Returns:
        True if the item's status is 'closed', False otherwise (including
        on errors, so the caller can fall through to normal processing).
    """
    try:
        result = _run_bd(['show', item_id, '--json'])
        data = _parse_beads_json(result.stdout)
        if data is None:
            return False

        current_item = data[0] if isinstance(data, list) else data
        status = str(current_item.get('status', '')).lower()
        return status == 'closed'
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired,
            json.JSONDecodeError, Exception):
        return False


def get_beads_stats() -> BeadsStats | None:
    """Get current beads database statistics.

    Runs from the main repository root to ensure beads database is accessible
    even when called from a worktree.

    Returns:
        BeadsStats object with current counts, or None if command fails.
    """
    try:
        # Get main repo root to ensure beads database is accessible
        main_repo = _get_main_repo_root()
        cwd = str(main_repo) if main_repo else None

        result = _run_bd(['stats', '--json'], cwd=cwd)

        data = json.loads(result.stdout)
        summary = data.get('summary', {})

        return BeadsStats(
            total_issues=summary.get('total_issues', 0),
            open_issues=summary.get('open_issues', 0),
            in_progress_issues=summary.get('in_progress_issues', 0),
            closed_issues=summary.get('closed_issues', 0),
            ready_issues=summary.get('ready_issues', 0)
        )
    except Exception as e:
        logger.warning(f"⚠️  Warning: Failed to get beads stats: {e}")
        return None
