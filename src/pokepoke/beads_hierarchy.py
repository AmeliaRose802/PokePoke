"""Beads hierarchy operations - parent-child relationships."""

import os
import subprocess
from typing import List, Optional

from .types import BeadsWorkItem
from .beads_query import get_issue_dependencies

# Label that marks items as requiring human intervention - agents will skip these
HUMAN_REQUIRED_LABEL = 'human-required'

# Statuses that indicate a work item is complete
COMPLETED_STATUSES = ('done', 'closed', 'resolved')


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
                assignee=getattr(child_issue, 'assignee', None),
                created_at=child_issue.created_at,
                created_by=child_issue.created_by,
                updated_at=child_issue.updated_at,
                labels=child_issue.labels
            ))
    
    return children


def is_assigned_to_current_user(item: BeadsWorkItem) -> bool:
    """Check if item is assignable by current agent.
    
    CRITICAL: Checks the 'assignee' field (specific agent), NOT 'owner' field.
    - assignee: pokepoke_agent_123 (who is actively working on it)
    - owner: user@example.com (who created/owns it - NOT relevant for claiming)
    
    Also checks status: if 'in_progress' with no assignee info, assumes
    another agent has claimed it (bd commands sometimes omit assignee).
    
    Args:
        item: Work item to check.
        
    Returns:
        True if item is unassigned or assigned to THIS agent, False otherwise.
    """
    assignee = getattr(item, 'assignee', None) or ''
    agent_name = os.environ.get('AGENT_NAME', '')
    
    if assignee:
        # Has an assignee - check if it's THIS agent
        if agent_name and agent_name.lower() == assignee.lower():
            return True
        # Assigned to a different agent - SKIP
        return False
    
    # No assignee field - check status as fallback.
    # If status is 'in_progress', another agent likely claimed it.
    if item.status == 'in_progress':
        return False
    
    # No assignee, not in_progress - claimable
    return True


def get_next_child_task(parent_id: str) -> Optional[BeadsWorkItem]:
    """Get the next ready child task for a parent epic or feature.
    
    Returns the highest priority open child, or None if all children are complete.
    Skips items that are in_progress and assigned to other agents.
    
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
        if child.status not in COMPLETED_STATUSES
    ]
    
    if not open_children:
        return None
    
    # Filter out items assigned to other agents
    available_children = [
        child for child in open_children
        if is_assigned_to_current_user(child)
    ]
    
    # Filter out items that require human intervention
    available_children = [
        child for child in available_children
        if not (child.labels and HUMAN_REQUIRED_LABEL in child.labels)
    ]
    
    if not available_children:
        # All children are assigned to other agents
        return None
    
    # Return highest priority (lowest number)
    return min(available_children, key=lambda x: x.priority)


def _get_available_children(parent_id: str) -> tuple[list[BeadsWorkItem], list[BeadsWorkItem]]:
    """Get available children for a parent, separated from all children.
    
    Returns:
        Tuple of (available_children sorted by priority, all_children).
        available_children excludes completed, blocked, and human-required items.
    """
    children = get_children(parent_id)
    
    if not children:
        return [], []
    
    # Filter to open/in_progress children only
    open_children = [
        child for child in children
        if child.status not in COMPLETED_STATUSES
    ]
    
    if not open_children:
        return [], children
    
    # Filter out items assigned to other agents and human-required
    available = [
        child for child in open_children
        if is_assigned_to_current_user(child)
        and not (child.labels and HUMAN_REQUIRED_LABEL in child.labels)
    ]
    
    # Sort by priority (lowest number = highest priority)
    available.sort(key=lambda x: x.priority)
    
    return available, children


def resolve_to_leaf_task(item: BeadsWorkItem, _depth: int = 0) -> Optional[BeadsWorkItem]:
    """Recursively resolve an epic/feature to an assignable leaf task.
    
    Core rule: NEVER directly assign an epic/feature that has children.
    Instead, walk down the hierarchy to find the first assignable leaf task.
    
    Behavior:
    - Non-epic/feature items are returned directly (leaf tasks).
    - Childless epics/features are returned directly (agent should decompose).
    - Epics/features with children: iterate available children by priority.
      Leaf children are returned. Epic/feature children are recursively resolved.
    - If all children are complete, auto-closes the parent and returns None.
    - If all children are blocked (assigned to others, human-required),
      returns None (skip parent entirely).
    
    Args:
        item: The work item to resolve.
        _depth: Internal recursion depth tracker (prevents infinite loops).
        
    Returns:
        An assignable leaf task, the item itself if childless, or None if
        all children are blocked/complete.
    """
    _MAX_DEPTH = 10
    if _depth >= _MAX_DEPTH:
        return None
    
    # Non-epic/feature items are always leaf tasks - return directly
    if item.issue_type not in ('epic', 'feature'):
        return item
    
    available, all_children = _get_available_children(item.id)
    
    if not all_children:
        # Childless epic/feature - return for direct work
        # (the agent should break it down into tasks)
        return item
    
    if not available:
        # Has children but none are available
        # Check if all are complete → auto-close parent
        # Otherwise they're all blocked → skip parent entirely
        close_parent_if_complete(item.id)
        return None
    
    # Iterate through available children by priority
    for child in available:
        if child.issue_type in ('epic', 'feature'):
            # Child is itself an epic/feature - recursively resolve
            resolved = resolve_to_leaf_task(child, _depth + 1)
            if resolved:
                return resolved
            # This child resolved to nothing - try next sibling
            continue
        else:
            # Leaf task (task/bug/chore) - return directly
            return child
    
    # All available children resolved to nothing
    # Try to auto-close if all children are now complete
    close_parent_if_complete(item.id)
    return None


def all_children_complete(parent_id: str) -> bool:
    """Check if all children of a parent are complete.
    
    Args:
        parent_id: The parent issue ID.
        
    Returns:
        True if all children are complete, False otherwise.
        Returns False if no children exist (prevents premature parent closure).
    """
    children = get_children(parent_id)
    
    if not children:
        # No children means NOT complete - prevents premature closure of
        # features/epics that have no registered children yet or when
        # get_children fails due to errors/race conditions
        return False
    
    # Check if all children are in done/closed/resolved status
    return all(
        child.status in COMPLETED_STATUSES
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
            encoding='utf-8',
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
