"""Beads integration - query and filter work items."""

import json
import subprocess
from typing import List, Optional

from .types import BeadsWorkItem, IssueWithDependencies, Dependency


def get_ready_work_items() -> List[BeadsWorkItem]:
    """Query beads database for ready work items.
    
    Returns:
        List of ready work items.
    """
    result = subprocess.run(
        ['bd', 'ready', '--json'],
        capture_output=True,
        text=True,
        check=True
    )
    
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
    return [BeadsWorkItem(**item) for item in items_data]


def get_issue_dependencies(issue_id: str) -> Optional[IssueWithDependencies]:
    """Get detailed issue information including dependencies.
    
    Args:
        issue_id: The issue ID to query.
        
    Returns:
        Issue with dependencies, or None if not found.
    """
    result = subprocess.run(
        ['bd', 'show', issue_id, '--json'],
        capture_output=True,
        text=True,
        check=True
    )
    
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
    
    # Convert dependencies if present
    if 'dependencies' in issue_dict and issue_dict['dependencies']:
        issue_dict['dependencies'] = [
            Dependency(**dep) for dep in issue_dict['dependencies']
        ]
    
    if 'dependents' in issue_dict and issue_dict['dependents']:
        issue_dict['dependents'] = [
            Dependency(**dep) for dep in issue_dict['dependents']
        ]
    
    return IssueWithDependencies(**issue_dict)


def has_feature_parent(issue_id: str) -> bool:
    """Check if an issue has a parent that is a feature.
    
    Args:
        issue_id: The issue ID to check.
        
    Returns:
        True if has feature parent, False otherwise.
    """
    try:
        issue = get_issue_dependencies(issue_id)
        if not issue or not issue.dependencies:
            return False
        
        # Check if any dependency is a parent relationship with type 'feature'
        return any(
            dep.dependency_type == 'parent' and dep.issue_type == 'feature'
            for dep in issue.dependencies
        )
    except Exception as e:
        print(f"Warning: Failed to check dependencies for {issue_id}: {e}")
        return False


def filter_work_items(items: List[BeadsWorkItem]) -> List[BeadsWorkItem]:
    """Filter work items based on selection criteria.
    
    - Exclude epics (too broad)
    - Include features
    - Include tasks/bugs/chores only if NOT parented to a feature
    
    Args:
        items: Array of work items to filter.
        
    Returns:
        Filtered array.
    """
    filtered = []
    
    for item in items:
        # Skip epics - too broad
        if item.issue_type == 'epic':
            print(f"   ⏭️  Skipping epic: {item.id} - {item.title}")
            continue
        
        # Always include features
        if item.issue_type == 'feature':
            filtered.append(item)
            continue
        
        # For tasks, bugs, chores - only include if NOT parented to a feature
        if item.issue_type in ('task', 'bug', 'chore'):
            if has_feature_parent(item.id):
                print(f"   ⏭️  Skipping {item.issue_type} with feature parent: {item.id} - {item.title}")
                continue
            filtered.append(item)
            continue
        
        # Include any other types by default
        filtered.append(item)
    
    return filtered


def get_first_ready_work_item() -> Optional[BeadsWorkItem]:
    """Get the first ready work item that meets selection criteria.
    
    Returns:
        First ready work item, or None if none available.
    """
    items = get_ready_work_items()
    filtered = filter_work_items(items)
    return filtered[0] if filtered else None
