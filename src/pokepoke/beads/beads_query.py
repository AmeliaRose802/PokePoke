"""Beads query operations - fetch work items and dependencies."""

import dataclasses
import json
import logging
import subprocess
from pathlib import Path
from typing import Any

from pokepoke.worktrees.coordination import beads_db_lock
from pokepoke.stats.perf_timing import timed_block
from pokepoke.types import BeadsWorkItem, IssueWithDependencies, Dependency, BeadsStats
from pokepoke.utils.constants import (
    BEADS_BINARY_BD,
    BEADS_BINARY_BR,
    DEFAULT_BEADS_LOCK_TIMEOUT,
    DEFAULT_BEADS_TIMEOUT,
)


logger = logging.getLogger(__name__)


_MUTATING_BD_COMMANDS: frozenset[str] = frozenset({
    "update",
    "close",
    "sync",
    "comments",
})


# ---------------------------------------------------------------------------
# Backend configuration
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class CLIBackendConfig:
    """Configuration for a beads CLI backend (``bd`` or ``br``).

    Encapsulates the binary name, timeout defaults, and lock behaviour so
    that the subprocess runner (:func:`_run_cli`) is backend-agnostic.
    """

    binary: str
    default_timeout: int = DEFAULT_BEADS_TIMEOUT
    lock_timeout: float = DEFAULT_BEADS_LOCK_TIMEOUT
    mutating_commands: frozenset[str] = _MUTATING_BD_COMMANDS


BD_CONFIG = CLIBackendConfig(binary=BEADS_BINARY_BD)
BR_CONFIG = CLIBackendConfig(binary=BEADS_BINARY_BR)

_active_backend: CLIBackendConfig = BD_CONFIG


def get_active_backend() -> CLIBackendConfig:
    """Return the currently active CLI backend configuration."""
    return _active_backend


def set_active_backend(config: CLIBackendConfig) -> None:
    """Set the active CLI backend configuration used by :func:`_run_bd`.

    Also updates the active sync strategy to match the backend:
    ``bd`` → :class:`~pokepoke.beads.sync_strategy.DaemonSync`,
    ``br`` → :class:`~pokepoke.beads.sync_strategy.ExplicitSync`.
    """
    global _active_backend
    _active_backend = config

    from pokepoke.beads.sync_strategy import (
        DaemonSync,
        ExplicitSync,
        set_active_sync_strategy,
    )

    if config.binary == BEADS_BINARY_BR:
        set_active_sync_strategy(ExplicitSync(backend=config))
    else:
        set_active_sync_strategy(DaemonSync(backend=config))


# ---------------------------------------------------------------------------
# Backend-agnostic subprocess runner
# ---------------------------------------------------------------------------


def _run_cli(
    args: list[str],
    *,
    backend: CLIBackendConfig,
    check: bool = True,
    timeout: int | None = None,
    cwd: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a beads CLI command.  Mutating commands are serialized via lock."""
    if timeout is None:
        timeout = backend.default_timeout

    cmd = args[0] if args else ""

    def _run() -> subprocess.CompletedProcess[str]:
        with timed_block(f"{backend.binary}.{cmd}" if cmd else f"{backend.binary}.unknown"):
            return subprocess.run(
                [backend.binary] + args,
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace',
                check=check,
                timeout=timeout,
                cwd=cwd,
            )

    if cmd in backend.mutating_commands:
        with beads_db_lock(timeout=backend.lock_timeout):
            return _run()

    return _run()


def _run_bd(
    args: list[str],
    *,
    check: bool = True,
    timeout: int | None = 30,
    cwd: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a beads CLI command using the active backend."""
    return _run_cli(
        args,
        backend=_active_backend,
        check=check,
        timeout=timeout,
        cwd=cwd,
    )


def _filter_to_dataclass(cls: type, data: dict[str, Any]) -> Any:
    """Construct a dataclass instance, keeping only fields defined on *cls*."""
    valid = {f.name for f in dataclasses.fields(cls)}
    return cls(**{k: v for k, v in data.items() if k in valid})


def _parse_beads_json(output: str, extra_prefixes: tuple[str, ...] = ()) -> Any:
    """Parse JSON from beads CLI output, filtering warning/note lines."""
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
    """Return the main repo root, or None if not in a git repo."""
    from pokepoke.git.git_operations import get_main_repo_root
    try:
        return get_main_repo_root()
    except RuntimeError:
        return None


def get_ready_work_items() -> list[BeadsWorkItem]:
    """Query beads for ready work items. Returns empty list on failure."""
    try:
        result = _run_bd(['ready', '--json'])
    except subprocess.CalledProcessError as e:
        logger.warning("⚠️  beads ready command failed (exit code %s)", e.returncode)
        if e.stderr:
            logger.warning("⚠️  Error output: %s", e.stderr.strip())
        return []
    except subprocess.TimeoutExpired:
        logger.warning("⚠️  beads ready command timed out")
        return []
    except Exception as e:
        logger.warning("⚠️  unexpected error querying beads: %s", e)
        return []

    if not result.stdout:
        return []

    try:
        items_data = _parse_beads_json(result.stdout)
        if not items_data or isinstance(items_data, dict):
            if isinstance(items_data, dict) and 'error' in items_data:
                logger.warning("⚠️  beads returned error: %s", items_data['error'].split('\n')[0])
            return []
        return [_filter_to_dataclass(BeadsWorkItem, item) for item in items_data]
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        logger.warning(f"⚠️  Warning: failed to parse beads output: {e}")
        return []


def get_in_progress_items() -> list[BeadsWorkItem]:
    """Query beads for items with ``in_progress`` status.

    These are items that were claimed by a previous run but never completed
    (e.g. the orchestrator was killed).  The caller can merge them with
    ``get_ready_work_items()`` so that existing worktrees are resumed.
    """
    try:
        result = _run_bd(['list', '--status', 'in_progress', '--json'])
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, Exception) as e:
        logger.warning("⚠️  beads in_progress query failed: %s", e)
        return []

    if not result.stdout:
        return []

    try:
        items_data = _parse_beads_json(result.stdout)
        if not items_data or isinstance(items_data, dict):
            return []
        return [_filter_to_dataclass(BeadsWorkItem, item) for item in items_data]
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        logger.warning("⚠️  failed to parse in_progress output: %s", e)
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

        data = _parse_beads_json(result.stdout)
        if data is None:
            return None
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
