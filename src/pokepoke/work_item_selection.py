"""Work item selection logic for PokePoke."""

import os
from typing import Optional

from .types import BeadsWorkItem
from .beads import select_next_hierarchical_item
from .shutdown import is_shutting_down

# Label that marks items as requiring human intervention - PokePoke will skip these
HUMAN_REQUIRED_LABEL = 'human-required'


def _is_human_required(item: BeadsWorkItem) -> bool:
    """Check if an item has the human-required label.
    
    Items with this label need human intervention and should be
    skipped by autonomous agents.
    
    Args:
        item: Work item to check.
        
    Returns:
        True if the item has the human-required label.
    """
    if not item.labels:
        return False
    return HUMAN_REQUIRED_LABEL in item.labels


def _is_assigned_to_current_user(item: BeadsWorkItem) -> bool:
    """Check if item is assignable by current agent.
    
    CRITICAL: Checks the 'assignee' field (specific agent), NOT 'owner' field (human user).
    - assignee: pokepoke_agent_123 (who is actively working on it)
    - owner: user@example.com (who created/owns it)
    
    Args:
        item: Work item to check.
        
    Returns:
        True if item is unassigned or assigned to THIS agent, False if assigned to another agent.
    """
    # Get the assignee (specific agent working on it)
    assignee = getattr(item, 'assignee', None) or ''
    
    # If no assignee, it's claimable
    if not assignee:
        return True
    
    # Has an assignee - check if it's THIS agent
    agent_name = os.environ.get('AGENT_NAME', '')
    
    # Is it assigned to THIS agent specifically?
    if agent_name and agent_name.lower() == assignee.lower():
        return True
    
    # Assigned to a different agent - SKIP
    status_info = f" ({item.status})" if item.status else ""
    print(f"   ⏭️  Skipping {item.id}{status_info} - assigned to {assignee}")
    return False


def select_work_item(ready_items: list[BeadsWorkItem], interactive: bool) -> Optional[BeadsWorkItem]:
    """Select a work item to process using hierarchical assignment.
    
    Args:
        ready_items: List of available work items
        interactive: If True, prompt user to select; if False, use hierarchical selection
        
    Returns:
        Selected work item or None to quit
    """
    if not ready_items:
        print("\n✨ No ready work found in beads database.")
        print("   Run 'bd ready' to see available work items.")
        return None
    
    # Filter out items assigned to other agents
    available_items = [item for item in ready_items if _is_assigned_to_current_user(item)]
    
    # Show how many items were filtered out
    filtered_count = len(ready_items) - len(available_items)
    if filtered_count > 0:
        print(f"\n⏭️  Skipped {filtered_count} item(s) assigned to other agents")
    
    # Filter out items that require human intervention
    human_required = [item for item in available_items if _is_human_required(item)]
    if human_required:
        for item in human_required:
            print(f"   🧑 Skipping {item.id} - labeled '{HUMAN_REQUIRED_LABEL}' (needs human)")
        available_items = [item for item in available_items if not _is_human_required(item)]
    
    if not available_items:
        print("\n✨ No available work - all ready items are assigned to other agents or require human intervention.")
        print("   Wait for other agents to complete their work, or claim unassigned items.")
        return None
    
    ready_items = available_items
    
    if interactive:
        print(f"\n📋 Found {len(ready_items)} ready work items:\n")
        
        for idx, item in enumerate(ready_items, 1):
            print(f"{idx}. [{item.id}] {item.title}")
            print(f"   Type: {item.issue_type} | Priority: {item.priority}")
            if item.description:
                desc = item.description[:80]
                if len(item.description) > 80:
                    desc += "..."
                print(f"   {desc}")
            print()
    
    if interactive:
        return interactive_selection(ready_items)
    else:
        return autonomous_selection(ready_items)


def interactive_selection(ready_items: list[BeadsWorkItem]) -> Optional[BeadsWorkItem]:
    """Prompt user to select a work item."""
    while not is_shutting_down():
        try:
            choice = input("Select a work item (number) or 'q' to quit: ").strip()
            
            if choice.lower() == 'q':
                return None
            
            idx = int(choice)
            if 1 <= idx <= len(ready_items):
                return ready_items[idx - 1]
            else:
                print(f"❌ Please enter a number between 1 and {len(ready_items)}")
        except ValueError:
            print("❌ Invalid input. Enter a number or 'q' to quit.")
        except KeyboardInterrupt:
            print("\n")
            return None
    return None

def autonomous_selection(ready_items: list[BeadsWorkItem]) -> Optional[BeadsWorkItem]:
    """Use hierarchical selection for autonomous mode."""
    selected = select_next_hierarchical_item(ready_items)
    if selected:
        print(f"🤖 Hierarchically selected item: {selected.id}")
        print(f"   Type: {selected.issue_type} | Priority: {selected.priority}")
    return selected
