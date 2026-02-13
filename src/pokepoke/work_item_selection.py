"""Work item selection logic for PokePoke."""

from typing import Optional

from .types import BeadsWorkItem
from .beads import select_next_hierarchical_item
from .beads_hierarchy import HUMAN_REQUIRED_LABEL, is_assigned_to_current_user
from .shutdown import is_shutting_down


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


def select_work_item(ready_items: list[BeadsWorkItem], interactive: bool, skip_ids: Optional[set[str]] = None) -> Optional[BeadsWorkItem]:
    """Select a work item to process using hierarchical assignment.
    
    Args:
        ready_items: List of available work items
        interactive: If True, prompt user to select; if False, use hierarchical selection
        skip_ids: Set of item IDs to skip (e.g., items that failed claiming)
        
    Returns:
        Selected work item or None to quit
    """
    if not ready_items:
        print("\n\u2728 No ready work found in beads database.")
        print("   Run 'bd ready' to see available work items.")
        return None
    
    # Filter out items that previously failed claiming this session
    if skip_ids:
        skipped = [item for item in ready_items if item.id in skip_ids]
        if skipped:
            for item in skipped:
                print(f"   \u23ed\ufe0f  Skipping {item.id} - failed to claim earlier this session")
            ready_items = [item for item in ready_items if item.id not in skip_ids]
    
    if not ready_items:
        print("\n\u2728 No ready work found - all items were previously skipped.")
        print("   Other agents may still be working. Waiting for items to become available.")
        return None
    
    # Filter out items assigned to other agents
    available_items = [item for item in ready_items if is_assigned_to_current_user(item)]
    
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
