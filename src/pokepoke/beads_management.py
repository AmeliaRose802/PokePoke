"""Beads item management - create, close, filter work items."""

import json
import os
import subprocess
from typing import List, Optional

from .types import BeadsWorkItem
from .beads_hierarchy import has_feature_parent, get_next_child_task, close_parent_if_complete


def assign_and_sync_item(item_id: str, agent_name: Optional[str] = None) -> bool:
    """Assign a work item to an agent and sync to prevent parallel conflicts.
    
    This should be called BEFORE creating a worktree to ensure other parallel
    agents see the assignment and don't pick the same item.
    
    Args:
        item_id: The item ID to assign.
        agent_name: Agent name to assign to (defaults to $AGENT_NAME env var or 'agent').
        
    Returns:
        True if successful, False otherwise.
    """
    if agent_name is None:
        agent_name = os.environ.get('AGENT_NAME', 'agent')
    
    try:
        # Update item to in_progress and assign to agent
        subprocess.run(
            ['bd', 'update', item_id, '--status', 'in_progress', '-a', agent_name, '--json'],
            capture_output=True,
            text=True,
            encoding='utf-8',
            check=True
        )
        print(f"✅ Assigned {item_id} to {agent_name} and marked in_progress")
        
        # Sync to push assignment to other agents
        sync_result = subprocess.run(
            ['bd', 'sync'],
            capture_output=True,
            text=True,
            encoding='utf-8'
        )
        
        if sync_result.returncode == 0:
            print(f"✅ Synced assignment - other agents will see {item_id} is claimed")
        else:
            print(f"⚠️  bd sync returned non-zero: {sync_result.returncode}")
            print(f"   Assignment may not be immediately visible to other agents")
        
        return True
        
    except subprocess.CalledProcessError as e:
        print(f"⚠️  Failed to assign {item_id}: {e.stderr}")
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
            encoding='utf-8',
            check=True
        )
        print(f"✅ Closed {item_id}")
        return True
    except subprocess.CalledProcessError as e:
        print(f"⚠️  Failed to close {item_id}: {e.stderr}")
        return False


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
            encoding='utf-8',
            check=True
        )
        
        if not result.stdout:
            return None
        
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
                    text=True,
                    encoding='utf-8'
                )
            
            return issue_id
        
        return None
        
    except (subprocess.CalledProcessError, json.JSONDecodeError, KeyError) as e:
        print(f"⚠️  Failed to create issue: {e}")
        return None


def create_cleanup_delegation_issue(
    title: str,
    description: str,
    labels: Optional[List[str]] = None,
    parent_id: Optional[str] = None,
    priority: int = 0
) -> Optional[str]:
    """Create a cleanup/delegation issue for agent to handle.
    
    Used when automated operations fail and require manual/agent intervention.
    
    Args:
        title: Issue title
        description: Detailed description of the cleanup needed
        labels: Labels to add (defaults to ['cleanup', 'delegation'])
        parent_id: Optional parent issue that this relates to
        priority: Priority (default 0 = critical, needs immediate attention)
        
    Returns:
        Created issue ID, or None if creation failed
    """
    default_labels = ['cleanup', 'delegation']
    all_labels = list(set(default_labels + (labels or [])))
    
    issue_id = create_issue(
        title=title,
        issue_type='task',
        priority=priority,
        description=description,
        labels=all_labels,
        parent_id=parent_id
    )
    
    if issue_id:
        print(f"\n📋 Created delegation issue: {issue_id}")
        print("   An agent will handle this cleanup automatically")
    
    return issue_id


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
    from .beads_query import get_ready_work_items
    items = get_ready_work_items()
    filtered = filter_work_items(items)
    return filtered[0] if filtered else None


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
