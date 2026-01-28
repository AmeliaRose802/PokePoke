"""Work item selection logic for PokePoke."""

import os
from typing import Optional

from .types import BeadsWorkItem
from .beads import select_next_hierarchical_item


def _is_assigned_to_current_user(item: BeadsWorkItem) -> bool:
    """Check if item is assignable by current agent.
    
    CRITICAL: Checks the 'assignee' field (specific agent), NOT 'owner' field (human user).
    - assignee: pokepoke_agent_123 (who is actively working on it)
    - owner: ameliapayne@microsoft.com (who created/owns it)
    
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
    
    if not available_items:
        print("\n✨ No available work - all ready items are assigned to other agents.")
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
    while True:
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


def autonomous_selection(ready_items: list[BeadsWorkItem]) -> Optional[BeadsWorkItem]:
    """Use hierarchical selection for autonomous mode."""
    selected = select_next_hierarchical_item(ready_items)
    if selected:
        print(f"🤖 Hierarchically selected item: {selected.id}")
        print(f"   Type: {selected.issue_type} | Priority: {selected.priority}")
    return selected
