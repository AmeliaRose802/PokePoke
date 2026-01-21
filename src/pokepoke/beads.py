"""Beads integration - query and filter work items."""

import json
import subprocess
from typing import List, Optional, Dict, Set

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
            check=True
        )
    except subprocess.CalledProcessError:
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
            ['bd', 'close', parent_id, '-m', 'All child items completed'],
            capture_output=True,
            text=True,
            check=True
        )
        print(f"✅ Auto-closed parent {parent_id} - all children complete")
        return True
    except subprocess.CalledProcessError as e:
        print(f"⚠️  Failed to close parent {parent_id}: {e.stderr}")
        return False


def close_item(item_id: str, message: str = "Completed") -> bool:
    """Close a beads item with a completion message.
    
    Args:
        item_id: The item ID to close.
        message: Completion message.
        
    Returns:
        True if successful, False otherwise.
    """
    try:
        subprocess.run(
            ['bd', 'close', item_id, '--reason', message],
            capture_output=True,
            text=True,
            check=True
        )
        print(f"✅ Closed {item_id}")
        return True
    except subprocess.CalledProcessError as e:
        print(f"⚠️  Failed to close {item_id}: {e.stderr}")
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


def create_issue(
    title: str,
    issue_type: str = "task",
    priority: int = 1,
    description: str = "",
    labels: Optional[List[str]] = None,
    parent_id: Optional[str] = None
) -> Optional[str]:
    """Create a new beads issue.
    
    Args:
        title: Issue title
        issue_type: Type of issue (task, bug, feature, epic, chore)
        priority: Priority (0=critical, 1=high, 2=medium, 3=low, 4=backlog)
        description: Issue description
        labels: List of labels to add
        parent_id: Parent issue ID for dependencies
        
    Returns:
        Created issue ID, or None if creation failed
    """
    try:
        cmd = ['bd', 'create', title, '-t', issue_type, '-p', str(priority)]
        
        if description:
            cmd.extend(['-d', description])
        
        if parent_id:
            cmd.extend(['--deps', f'parent:{parent_id}'])
        
        cmd.append('--json')
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True
        )
        
        # Parse JSON output to get issue ID
        filtered_lines = [
            line for line in result.stdout.split('\n')
            if line.strip() 
            and not line.strip().startswith(('Note:', 'Warning:', 'Hint:', 'Created'))
        ]
        
        # Find JSON object start
        json_start = next(
            (i for i, line in enumerate(filtered_lines) if line.strip().startswith('{') or line.strip().startswith('[')),
            None
        )
        
        if json_start is not None:
            json_text = '\n'.join(filtered_lines[json_start:])
            data = json.loads(json_text)
            
            # Handle both array and single object responses
            if isinstance(data, list):
                issue_id = data[0].get('id') if data else None
            else:
                issue_id = data.get('id')
            
            # Add labels if provided
            if labels and issue_id:
                subprocess.run(
                    ['bd', 'label', 'add', issue_id] + labels + ['--json'],
                    capture_output=True,
                    text=True
                )
            
            return issue_id
        
        return None
        
    except (subprocess.CalledProcessError, json.JSONDecodeError, KeyError) as e:
        print(f"⚠️  Failed to create issue: {e}")
        return None


def select_next_hierarchical_item(items: List[BeadsWorkItem]) -> Optional[BeadsWorkItem]:
    """Select next work item using hierarchical assignment strategy.
    
    Strategy:
    1. For epics: return first incomplete child (feature or task)
    2. For features: return first incomplete child (task)
    3. For standalone tasks: return the task itself
    4. For items with incomplete children: return next child
    5. Auto-close parents when all children complete
    
    Args:
        items: List of ready work items.
        
    Returns:
        Next item to work on, or None if none available.
    """
    if not items:
        return None
    
    # Sort by priority for consistent ordering
    sorted_items = sorted(items, key=lambda x: x.priority)
    
    for item in sorted_items:
        # Check if this is an epic or feature with children
        if item.issue_type in ('epic', 'feature'):
            next_child = get_next_child_task(item.id)
            
            if next_child:
                # Work on this child
                return next_child
            else:
                # All children complete, close parent
                close_parent_if_complete(item.id)
                continue
        
        # Regular task/bug/chore - work on it directly
        return item
    
    return None
