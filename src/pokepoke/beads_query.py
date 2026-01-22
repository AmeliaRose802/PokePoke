"""Beads query operations - fetch work items and dependencies."""

import json
import subprocess
from typing import List, Optional

from .types import BeadsWorkItem, IssueWithDependencies, Dependency, BeadsStats


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
    
    # Filter out warning/note lines
    filtered_lines = [
        line for line in result.stdout.split('\n')
        if line.strip() 
        and not line.strip().startswith(('Note:', 'Warning:', 'Hint:'))
    ]
    
    # Find JSON array start
    json_start = next(
        (i for i, line in enumerate(filtered_lines) if line.strip().startswith('[')),
        None
    )
    
    if json_start is None:
        return []
    
    json_text = '\n'.join(filtered_lines[json_start:])
    
    if json_text.strip() == '[]':
        return []
    
    items_data = json.loads(json_text)
    
    # Filter out fields not in BeadsWorkItem dataclass
    valid_work_item_fields = {
        'id', 'title', 'status', 'priority', 'issue_type', 'description',
        'owner', 'created_at', 'created_by', 'updated_at', 'labels',
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
    
    # Filter out warning/note lines
    filtered_lines = [
        line for line in result.stdout.split('\n')
        if line.strip() 
        and not line.strip().startswith(('Note:', 'Warning:', 'Hint:'))
    ]
    
    # Find JSON array start
    json_start = next(
        (i for i, line in enumerate(filtered_lines) if line.strip().startswith('[')),
        None
    )
    
    if json_start is None:
        return None
    
    json_text = '\n'.join(filtered_lines[json_start:])
    issues_data = json.loads(json_text)
    
    if not issues_data:
        return None
    
    issue_dict = issues_data[0]
    
    # Filter out fields not in IssueWithDependencies dataclass
    valid_issue_fields = {
        'id', 'title', 'status', 'priority', 'issue_type', 'description',
        'dependencies', 'dependents', 'owner', 'created_at', 'created_by',
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


def get_beads_stats() -> Optional[BeadsStats]:
    """Get current beads database statistics.
    
    Returns:
        BeadsStats object with current counts, or None if command fails.
    """
    try:
        result = subprocess.run(
            ['bd', 'stats', '--json'],
            capture_output=True,
            text=True,
            encoding='utf-8',
            check=True
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
