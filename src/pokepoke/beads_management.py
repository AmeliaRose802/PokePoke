"""Beads item management - create, close, filter work items."""

import json
import os
import subprocess
import time
from typing import List, Optional

from .types import BeadsWorkItem
from .beads_hierarchy import has_feature_parent, get_next_child_task, close_parent_if_complete, get_children, resolve_to_leaf_task, HUMAN_REQUIRED_LABEL
from .beads_query import _parse_beads_json


def _is_transient_jsonl_sync_error(output: str) -> bool:
    normalized = output.lower()
    if "access is denied" in normalized and "jsonl" in normalized:
        return True
    return "failed to replace jsonl file" in normalized or "jsonl file hash mismatch" in normalized


def run_bd_sync_with_retry(
    max_attempts: int = 3,
    base_delay: float = 0.5,
    timeout: Optional[int] = None
) -> subprocess.CompletedProcess[str]:
    """Run bd sync with retries for transient JSONL lock errors."""
    last_result: Optional[subprocess.CompletedProcess[str]] = None
    for attempt in range(1, max_attempts + 1):
        result = subprocess.run(
            ['bd', 'sync'],
            capture_output=True,
            text=True,
            encoding='utf-8',
            timeout=timeout
        )
        last_result = result
        if result.returncode == 0:
            if attempt > 1:
                print(f"✅ bd sync succeeded after retry ({attempt}/{max_attempts})")
            return result

        output = f"{result.stdout}\n{result.stderr}"
        if _is_transient_jsonl_sync_error(output) and attempt < max_attempts:
            delay = base_delay * (2 ** (attempt - 1))
            print(
                "⚠️  bd sync failed due to locked JSONL file; "
                f"retrying in {delay:.1f}s (attempt {attempt}/{max_attempts})"
            )
            time.sleep(delay)
            continue
        return result

    assert last_result is not None
    return last_result


def assign_and_sync_item(item_id: str, agent_name: Optional[str] = None) -> bool:
    """Assign a work item to an agent and sync to prevent parallel conflicts.
    
    This should be called BEFORE creating a worktree to ensure other parallel
    agents see the assignment and don't pick the same item.
    
    CRITICAL: Verifies item is still claimable immediately before assignment
    to catch race conditions where another agent claimed it between fetch and now.
    
    Args:
        item_id: The item ID to assign.
        agent_name: Agent name to assign to (defaults to $AGENT_NAME env var or 'agent').
        
    Returns:
        True if successful, False if already claimed or failed.
    """
    if agent_name is None:
        agent_name = os.environ.get('AGENT_NAME', 'agent')
    
    # CRITICAL: Check current ownership RIGHT BEFORE claiming
    # This catches race conditions where another agent claimed between fetch and now
    try:
        result = subprocess.run(
            ['bd', 'show', item_id, '--json'],
            capture_output=True,
            text=True,
            encoding='utf-8',
            check=True
        )
        
        # Parse current item state
        data = _parse_beads_json(result.stdout)
        if data is not None:
            current_item = data[0] if isinstance(data, list) else data
            
            # CRITICAL: Check 'assignee' field, NOT 'owner' field!
            # - assignee: The specific agent currently working on it (pokepoke_agent_123)
            # - owner: The human user who owns it (e.g., user@example.com)
            current_assignee = current_item.get('assignee', '')
            
            # Check if already assigned to another agent
            if current_assignee:
                is_ours = (current_assignee.lower() == agent_name.lower())
                
                if not is_ours:
                    print(f"⚠️  RACE CONDITION DETECTED: {item_id} already assigned to {current_assignee}")
                    return False
    
    except (subprocess.CalledProcessError, json.JSONDecodeError) as e:
        print(f"⚠️  Failed to verify {item_id} ownership: {e}")
        return False
    
    try:
        # Now safe to claim - we verified it's unassigned or ours
        subprocess.run(
            ['bd', 'update', item_id, '--status', 'in_progress', '-a', agent_name, '--json'],
            capture_output=True,
            text=True,
            encoding='utf-8',
            check=True
        )
        print(f"✅ Assigned {item_id} to {agent_name} and marked in_progress")
        
        # Sync to push assignment to other agents
        sync_result = run_bd_sync_with_retry()
        
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


def add_comment(item_id: str, comment: str) -> bool:
    """Add a comment to a beads item.
    
    Args:
        item_id: The item ID to add a comment to.
        comment: The comment text.
        
    Returns:
        True if successful, False otherwise.
    """
    try:
        subprocess.run(
            ['bd', 'comments', 'add', item_id, comment],
            capture_output=True,
            text=True,
            encoding='utf-8',
            check=True
        )
        print(f"💬 Added comment to {item_id}")
        return True
    except subprocess.CalledProcessError as e:
        print(f"⚠️  Failed to add comment to {item_id}: {e.stderr}")
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
        data = _parse_beads_json(result.stdout, extra_prefixes=('Created',))
        
        if data is not None:
            
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


def select_next_hierarchical_item(items: List[BeadsWorkItem]) -> Optional[BeadsWorkItem]:
    """Select next work item using hierarchical assignment strategy.
    
    Core rule: NEVER directly assign an epic/feature that has children.
    Always assign children before parents, recursively walking down
    the hierarchy to find an assignable leaf task.
    
    Strategy:
    1. For epics/features WITH children: recursively resolve to a leaf task.
       Iterates through available children by priority. If a child is itself
       an epic/feature, recursively resolves it.
    2. For epics/features with NO children: return the epic/feature itself
       (agent should break it down into tasks).
    3. For standalone tasks/bugs/chores: return the item directly.
    4. Auto-close parents when all children are complete.
    5. Skip parents entirely when all children are blocked
       (assigned to others, human-required, etc.).
    
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
        # Skip items that require human intervention
        if item.labels and HUMAN_REQUIRED_LABEL in item.labels:
            continue
        
        # Check if this is an epic or feature
        if item.issue_type in ('epic', 'feature'):
            # Recursively resolve to a leaf task
            # This handles nested hierarchies (epic → feature → task)
            # and ensures we never directly assign a parent with children
            resolved = resolve_to_leaf_task(item)
            if resolved:
                return resolved
            # Could not resolve to an assignable item - skip
            continue
        
        # Regular task/bug/chore - work on it directly
        return item
    
    return None
