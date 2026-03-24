"""Multi-repo work item aggregator.

Queries beads ready queues across multiple configured repositories and returns
a unified, priority-weighted list of available work items. Each item carries
its repo context (path, config) so the orchestrator knows where to create
worktrees and run agents.
"""

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

from pokepoke.beads.beads_query import _filter_to_dataclass, _parse_beads_json, _run_bd
from pokepoke.config import RepoConfig
from pokepoke.types import BeadsWorkItem

logger = logging.getLogger(__name__)


@dataclass
class AggregatedWorkItem:
    """A work item from a specific repository in multi-repo aggregation.

    Wraps a BeadsWorkItem with the repository context it came from,
    enabling the orchestrator to operate on items across repos.
    """
    item: BeadsWorkItem
    repo_path: str
    repo_name: str = ""
    repo_priority_weight: int = 1


@dataclass
class RepoQueryResult:
    """Result of querying a single repo's ready queue."""
    repo_config: RepoConfig
    items: list[BeadsWorkItem] = field(default_factory=list)
    error: str | None = None


def _derive_repo_name(repo_config: RepoConfig) -> str:
    """Derive a human-readable repo name from the config.

    Uses the last component of the path as the name, or falls back to the
    full path if empty.
    """
    if not repo_config.path:
        return ""
    return Path(repo_config.path).name or repo_config.path


def query_repo_ready_items(repo_config: RepoConfig) -> RepoQueryResult:
    """Query the beads ready queue for a single repository.

    Args:
        repo_config: Configuration for the repo to query.

    Returns:
        RepoQueryResult with items found or error details.
    """
    if not repo_config.enabled:
        return RepoQueryResult(repo_config=repo_config)

    if not repo_config.path:
        return RepoQueryResult(
            repo_config=repo_config,
            error="Repo path is empty",
        )

    repo_path = Path(repo_config.path)
    if not repo_path.is_dir():
        return RepoQueryResult(
            repo_config=repo_config,
            error=f"Repo path does not exist: {repo_config.path}",
        )

    try:
        result = _run_bd(
            ['ready', '--json'],
            check=True,
            timeout=30,
            cwd=str(repo_path),
        )
    except Exception as e:
        logger.warning(
            "⚠️  Failed to query beads for repo %s: %s",
            repo_config.path, e,
        )
        return RepoQueryResult(repo_config=repo_config, error=str(e))

    if not result.stdout:
        return RepoQueryResult(repo_config=repo_config)

    try:
        items_data = _parse_beads_json(result.stdout)
        if not items_data:
            return RepoQueryResult(repo_config=repo_config)
        items = [_filter_to_dataclass(BeadsWorkItem, item) for item in items_data]
        return RepoQueryResult(repo_config=repo_config, items=items)
    except Exception as e:
        logger.warning(
            "⚠️  Failed to parse beads output for repo %s: %s",
            repo_config.path, e,
        )
        return RepoQueryResult(repo_config=repo_config, error=str(e))


def aggregate_ready_work_items(
    repos: list[RepoConfig],
    *,
    max_workers: int = 4,
) -> list[AggregatedWorkItem]:
    """Query all configured repos and return a unified priority-weighted list.

    Items are sorted so that higher-priority repos (higher ``priority_weight``)
    and higher-priority items (lower ``priority`` number) appear first.

    Repos with errors or no ready items are silently tolerated — they simply
    contribute zero items to the result.

    Args:
        repos: List of repo configurations to query.
        max_workers: Maximum threads for parallel querying.

    Returns:
        Sorted list of AggregatedWorkItem across all repos.
    """
    if not repos:
        return []

    enabled_repos = [r for r in repos if r.enabled]
    if not enabled_repos:
        return []

    results = _query_all_repos(enabled_repos, max_workers=max_workers)
    return _merge_and_sort(results)


def _query_all_repos(
    repos: list[RepoConfig],
    *,
    max_workers: int = 4,
) -> list[RepoQueryResult]:
    """Query all repos, using threads for parallelism when beneficial."""
    if not repos:
        return []

    if len(repos) == 1:
        return [query_repo_ready_items(repos[0])]

    clamped_workers = min(max_workers, len(repos), 8)
    results: list[RepoQueryResult] = []

    with ThreadPoolExecutor(max_workers=clamped_workers) as pool:
        futures = {
            pool.submit(query_repo_ready_items, repo): repo
            for repo in repos
        }
        for future in as_completed(futures):
            try:
                results.append(future.result())
            except Exception as e:
                repo = futures[future]
                logger.warning(
                    "⚠️  Unexpected error querying repo %s: %s",
                    repo.path, e,
                )
                results.append(RepoQueryResult(repo_config=repo, error=str(e)))

    return results


def _merge_and_sort(results: list[RepoQueryResult]) -> list[AggregatedWorkItem]:
    """Merge query results into a single sorted list.

    Sort order (descending importance):
    1. Higher repo priority_weight first (descending)
    2. Lower item priority number first (ascending — 0 is highest priority)
    3. Item ID for stable ordering
    """
    aggregated: list[AggregatedWorkItem] = []

    for result in results:
        if result.error or not result.items:
            continue
        repo_name = _derive_repo_name(result.repo_config)
        weight = result.repo_config.priority_weight
        aggregated.extend(
            AggregatedWorkItem(
                item=item,
                repo_path=result.repo_config.path,
                repo_name=repo_name,
                repo_priority_weight=weight,
            )
            for item in result.items
        )

    aggregated.sort(key=lambda a: (-a.repo_priority_weight, a.item.priority, a.item.id))
    return aggregated


def get_aggregated_stats(
    repos: list[RepoConfig],
) -> dict[str, int]:
    """Return a summary of ready-item counts per repo.

    Args:
        repos: List of repo configurations.

    Returns:
        Mapping of repo path → ready item count.
    """
    results = _query_all_repos([r for r in repos if r.enabled])
    return {
        r.repo_config.path: len(r.items)
        for r in results
    }
