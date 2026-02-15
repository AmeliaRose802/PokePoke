"""Work item selection logic for PokePoke."""

from typing import Optional

from .types import BeadsWorkItem
from .beads import select_next_hierarchical_item, has_unmet_blocking_dependencies
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
    
    # Filter out items with unmet blocking dependencies
    items_with_unmet_deps = []
    for item in available_items:
        if has_unmet_blocking_dependencies(item.id):
            items_with_unmet_deps.append(item)
            print(f"   🚫 Skipping {item.id} - has unmet blocking dependencies")
    
    available_items = [item for item in available_items if item not in items_with_unmet_deps]
    
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


def select_multiple_items(
    ready_items: list[BeadsWorkItem],
    count: int,
    skip_ids: Optional[set[str]] = None,
    claimed_ids: Optional[set[str]] = None,
) -> list[BeadsWorkItem]:
    """Select up to *count* work items for parallel processing.

    Uses the same filtering as ``select_work_item`` (skips human-required,
    other-agent-assigned, and previously-failed items) then returns the top
    *count* items via hierarchical selection.

    Args:
        ready_items: List of available work items from beads.
        count: Maximum number of items to return.
        skip_ids: IDs to skip (e.g. failed claims).
        claimed_ids: IDs already being processed in the thread pool.

    Returns:
        List of selected items (may be shorter than *count*).
    """
    if not ready_items or count <= 0:
        return []

    excluded: set[str] = set()
    if skip_ids:
        excluded.update(skip_ids)
    if claimed_ids:
        excluded.update(claimed_ids)

    # Apply the same filters as select_work_item
    filtered = [item for item in ready_items if item.id not in excluded]
    filtered = [item for item in filtered if is_assigned_to_current_user(item)]
    filtered = [item for item in filtered if not _is_human_required(item)]
    filtered = [
        item for item in filtered
        if not has_unmet_blocking_dependencies(item.id)
    ]

    if not filtered:
        return []

    # Use hierarchical selection repeatedly to pick up to `count` items
    selected: list[BeadsWorkItem] = []
    remaining = list(filtered)
    for _ in range(count):
        if not remaining:
            break
        item = select_next_hierarchical_item(remaining)
        if item is None:
            break
        selected.append(item)
        remaining = [i for i in remaining if i.id != item.id]

    return selected
