"""Beads item management - close, assign, and select work items."""

import json
import subprocess
import time
from typing import List, Optional

from .agent_context import get_agent_name
from .types import BeadsWorkItem
from .beads_hierarchy import resolve_to_leaf_task, HUMAN_REQUIRED_LABEL
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
        agent_name = get_agent_name()
    
    # CRITICAL: Check current ownership RIGHT BEFORE claiming
    # This catches race conditions where another agent claimed between fetch and now
    try:
        result = subprocess.run(
            ['bd', 'show', item_id, '--json'],
            capture_output=True,
            text=True,
            encoding='utf-8',
            check=True,
            timeout=30
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
            check=True,
            timeout=30
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
            check=True,
            timeout=30
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
            check=True,
            timeout=30
        )
        print(f"💬 Added comment to {item_id}")
        return True
    except subprocess.CalledProcessError as e:
        print(f"⚠️  Failed to add comment to {item_id}: {e.stderr}")
        return False


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
