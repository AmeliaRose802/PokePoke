"""Work item selection logic for PokePoke."""

from typing import Optional

from .types import BeadsWorkItem
from .beads import select_next_hierarchical_item


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
