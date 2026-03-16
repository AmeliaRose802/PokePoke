"""Work item selection logic for PokePoke."""

import logging

from pokepoke.types import BeadsWorkItem
from pokepoke.beads.beads import select_next_hierarchical_item
from pokepoke.beads.beads_hierarchy import HUMAN_REQUIRED_LABEL, is_assigned_to_current_user
from pokepoke.utils.shutdown import is_shutting_down

logger = logging.getLogger(__name__)


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


def _is_closed(item: BeadsWorkItem) -> bool:
    """Check if an item is already closed based on its status field.

    Args:
        item: Work item to check.

    Returns:
        True if the item's status indicates it is closed.
    """
    return item.status.lower() == 'closed' if item.status else False


def _filter_skip_ids(ready_items: list[BeadsWorkItem], skip_ids: set[str] | None) -> list[BeadsWorkItem]:
    """Remove items that previously failed claiming this session."""
    if not skip_ids:
        return ready_items
    skipped = [item for item in ready_items if item.id in skip_ids]
    for item in skipped:
        logger.info("Skipping %s - failed to claim earlier this session", item.id)
    return [item for item in ready_items if item.id not in skip_ids]


def _filter_available(ready_items: list[BeadsWorkItem]) -> list[BeadsWorkItem]:
    """Filter out items assigned to other agents, human-required, closed, or with unmet deps."""
    available = [item for item in ready_items if is_assigned_to_current_user(item)]

    filtered_count = len(ready_items) - len(available)
    if filtered_count > 0:
        logger.info("Skipped %d item(s) assigned to other agents", filtered_count)

    human_required = [item for item in available if _is_human_required(item)]
    if human_required:
        for item in human_required:
            logger.info("Skipping %s - labeled '%s' (needs human)", item.id, HUMAN_REQUIRED_LABEL)
        available = [item for item in available if not _is_human_required(item)]

    # Filter out items that are already closed in beads (status field from bd ready)
    closed_items = [item for item in available if _is_closed(item)]
    if closed_items:
        for item in closed_items:
            logger.info("Skipping %s - already closed in beads", item.id)
        available = [item for item in available if not _is_closed(item)]

    # Note: has_unmet_blocking_dependencies is NOT called here because
    # bd ready already performs blocker-aware filtering ("open issues with
    # no blockers").  Calling bd show per-item was adding ~5-10s per item.

    return available


def select_work_item(ready_items: list[BeadsWorkItem], interactive: bool, skip_ids: set[str] | None = None) -> BeadsWorkItem | None:
    """Select a work item to process using hierarchical assignment.

    Args:
        ready_items: List of available work items
        interactive: If True, prompt user to select; if False, use hierarchical selection
        skip_ids: Set of item IDs to skip (e.g., items that failed claiming)

    Returns:
        Selected work item or None to quit
    """
    if not ready_items:
        logger.info("No ready work found in beads database. Run 'bd ready' to see available work items.")
        return None

    ready_items = _filter_skip_ids(ready_items, skip_ids)

    if not ready_items:
        logger.info("No ready work found - all items were previously skipped. Other agents may still be working.")
        return None

    available_items = _filter_available(ready_items)

    if not available_items:
        logger.info("No available work - all ready items are assigned to other agents or require human intervention.")
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


def interactive_selection(ready_items: list[BeadsWorkItem]) -> BeadsWorkItem | None:
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

def autonomous_selection(ready_items: list[BeadsWorkItem]) -> BeadsWorkItem | None:
    """Use hierarchical selection for autonomous mode."""
    selected = select_next_hierarchical_item(ready_items)
    if selected:
        logger.info("Hierarchically selected item: %s (Type: %s, Priority: %s)", selected.id, selected.issue_type, selected.priority)
    return selected


def select_multiple_items(
    ready_items: list[BeadsWorkItem],
    count: int,
    skip_ids: set[str] | None = None,
    claimed_ids: set[str] | None = None,
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
    filtered = [item for item in filtered if not _is_closed(item)]
    # Note: has_unmet_blocking_dependencies check removed — bd ready already
    # applies blocker-aware filtering.  The per-item bd show calls were
    # adding ~5-10s each, causing multi-minute dispatch delays.

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
