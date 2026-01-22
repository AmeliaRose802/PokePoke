"""Beads hierarchy operations - parent-child relationships."""

import subprocess
from typing import List, Optional

from .types import BeadsWorkItem, IssueWithDependencies
from .beads_query import get_issue_dependencies


def get_children(parent_id: str) -> List[BeadsWorkItem]:
    """Get all child items for a parent issue (epic or feature).
    
    Args:
        parent_id: The parent issue ID.
        
    Returns:
        List of child work items.
    """
    issue = get_issue_dependencies(parent_id)
    if not issue or not issue.dependents:
        return []
    
    # Get child items (those with parent dependency type pointing to this issue)
    child_ids = [
        dep.id for dep in issue.dependents 
        if dep.dependency_type == 'parent'
    ]
    
    if not child_ids:
        return []
    
    # Fetch full details for each child
    children = []
    for child_id in child_ids:
        child_issue = get_issue_dependencies(child_id)
        if child_issue:
            children.append(BeadsWorkItem(
                id=child_issue.id,
                title=child_issue.title,
                description=child_issue.description,
                status=child_issue.status,
                priority=child_issue.priority,
                issue_type=child_issue.issue_type,
                owner=child_issue.owner,
                created_at=child_issue.created_at,
                created_by=child_issue.created_by,
                updated_at=child_issue.updated_at,
                labels=child_issue.labels
            ))
    
    return children


def get_next_child_task(parent_id: str) -> Optional[BeadsWorkItem]:
    """Get the next ready child task for a parent epic or feature.
    
    Returns the highest priority open child, or None if all children are complete.
    
    Args:
        parent_id: The parent issue ID.
        
    Returns:
        Next ready child task, or None if all complete.
    """
    children = get_children(parent_id)
    
    if not children:
        return None
    
    # Filter to open/in_progress children only
    open_children = [
        child for child in children 
        if child.status not in ('done', 'closed', 'resolved')
    ]
    
    if not open_children:
        return None
    
    # Return highest priority (lowest number)
    return min(open_children, key=lambda x: x.priority)


def all_children_complete(parent_id: str) -> bool:
    """Check if all children of a parent are complete.
    
    Args:
        parent_id: The parent issue ID.
        
    Returns:
        True if all children are complete, False otherwise.
    """
    children = get_children(parent_id)
    
    if not children:
        # No children means complete (trivially true)
        return True
    
    # Check if all children are in done/closed/resolved status
    return all(
        child.status in ('done', 'closed', 'resolved') 
        for child in children
    )


def close_parent_if_complete(parent_id: str) -> bool:
    """Close a parent issue if all its children are complete.
    
    Args:
        parent_id: The parent issue ID to check and close.
        
    Returns:
        True if parent was closed, False otherwise.
    """
    if not all_children_complete(parent_id):
        return False
    
    try:
        subprocess.run(
            ['bd', 'close', parent_id, '-r', 'All child items completed'],
            capture_output=True,
            text=True,
            check=True
        )
        print(f"✅ Auto-closed parent {parent_id} - all children complete")
        return True
    except subprocess.CalledProcessError as e:
        print(f"⚠️  Failed to close parent {parent_id}: {e.stderr}")
        return False


def get_parent_id(child_id: str) -> Optional[str]:
    """Get the parent ID of a child item.
    
    Args:
        child_id: The child issue ID.
        
    Returns:
        Parent ID if exists, None otherwise.
    """
    issue = get_issue_dependencies(child_id)
    if not issue or not issue.dependencies:
        return None
    
    # Find parent dependency
    for dep in issue.dependencies:
        if dep.dependency_type == 'parent':
            return dep.id
    
    return None


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
