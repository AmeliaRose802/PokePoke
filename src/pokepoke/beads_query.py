"""Beads query operations - fetch work items and dependencies."""

import json
import subprocess
from pathlib import Path
from typing import Any, List, Optional

from .types import BeadsWorkItem, IssueWithDependencies, Dependency, BeadsStats


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


def _get_main_repo_root() -> Optional[Path]:
    """Get the main repository root directory (not a worktree).
    
    Returns:
        Path to the main repo root, or None if not in a git repository.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--git-common-dir"],
            capture_output=True, text=True, encoding='utf-8', check=True
        )
        git_common_dir = Path(result.stdout.strip())
        return git_common_dir.parent
    except subprocess.CalledProcessError:
        return None


def get_ready_work_items() -> List[BeadsWorkItem]:
    """Query beads database for ready work items.
    
    Returns:
        List of ready work items.
    """
    result = subprocess.run(
        ['bd', 'ready', '--json'],
        capture_output=True,
        text=True,
        encoding='utf-8',
        check=True
    )
    
    if not result.stdout:
        return []
    
    items_data = _parse_beads_json(result.stdout)
    if not items_data:
        return []
    
    # Filter out fields not in BeadsWorkItem dataclass
    valid_work_item_fields = {
        'id', 'title', 'status', 'priority', 'issue_type', 'description',
        'owner', 'assignee', 'created_at', 'created_by', 'updated_at', 'labels',
        'dependency_count', 'dependent_count', 'notes'
    }
    
    return [
        BeadsWorkItem(**{k: v for k, v in item.items() if k in valid_work_item_fields})
        for item in items_data
    ]


def get_issue_dependencies(issue_id: str) -> Optional[IssueWithDependencies]:
    """Get detailed issue information including dependencies.
    
    Args:
        issue_id: The issue ID to query.
        
    Returns:
        Issue with dependencies, or None if not found.
    """
    try:
        result = subprocess.run(
            ['bd', 'show', issue_id, '--json'],
            capture_output=True,
            text=True,
            encoding='utf-8',
            check=True
        )
    except subprocess.CalledProcessError:
        return None
    
    if not result.stdout:
        return None
    
    issues_data = _parse_beads_json(result.stdout)
    if not issues_data:
        return None
    
    issue_dict = issues_data[0]
    
    # Filter out fields not in IssueWithDependencies dataclass
    valid_issue_fields = {
        'id', 'title', 'status', 'priority', 'issue_type', 'description',
        'dependencies', 'dependents', 'owner', 'assignee', 'created_at', 'created_by',
        'updated_at', 'labels', 'notes'
    }
    filtered_issue = {k: v for k, v in issue_dict.items() if k in valid_issue_fields}
    
    # Filter out fields not in Dependency dataclass
    valid_dep_fields = {
        'id', 'title', 'issue_type', 'dependency_type', 'status', 'priority',
        'description', 'owner', 'created_at', 'created_by', 'updated_at',
        'labels', 'notes'
    }
    
    # Convert dependencies if present
    if 'dependencies' in filtered_issue and filtered_issue['dependencies']:
        filtered_issue['dependencies'] = [
            Dependency(**{k: v for k, v in dep.items() if k in valid_dep_fields})
            for dep in filtered_issue['dependencies']
        ]
    
    if 'dependents' in filtered_issue and filtered_issue['dependents']:
        filtered_issue['dependents'] = [
            Dependency(**{k: v for k, v in dep.items() if k in valid_dep_fields})
            for dep in filtered_issue['dependents']
        ]
    
    return IssueWithDependencies(**filtered_issue)


def has_unmet_blocking_dependencies(item_id: str) -> bool:
    """Check if an item has any unmet blocking dependencies.
    
    An item should not be worked on if it has dependencies with type 'blocks'
    that are not in 'closed' status.
    
    Args:
        item_id: The issue ID to check.
        
    Returns:
        True if the item has unmet blocking dependencies, False otherwise.
    """
    issue = get_issue_dependencies(item_id)
    if not issue or not issue.dependencies:
        return False
    
    # Check if any blocking dependencies are not closed
    for dep in issue.dependencies:
        if dep.dependency_type == 'blocks' and dep.status != 'closed':
            return True
    
    return False


def get_beads_stats() -> Optional[BeadsStats]:
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
        
        result = subprocess.run(
            ['bd', 'stats', '--json'],
            capture_output=True,
            text=True,
            encoding='utf-8',
            check=True,
            cwd=cwd
        )
        
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
        print(f"⚠️  Warning: Failed to get beads stats: {e}")
        return None
