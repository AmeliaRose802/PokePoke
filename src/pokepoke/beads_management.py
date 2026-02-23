"""Beads item management - close, assign, and select work items."""

import json
import subprocess
import time

from filelock import Timeout

from .agent_context import get_agent_name
from .coordination import acquire_lock
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
    timeout: int | None = None
) -> subprocess.CompletedProcess[str]:
    """Run bd sync with retries for transient JSONL lock errors."""
    last_result: subprocess.CompletedProcess[str] | None = None
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


def assign_and_sync_item(item_id: str, agent_name: str | None = None) -> bool:
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

    safe_id = ''.join(c if c.isalnum() or c in ('-', '_') else '_' for c in item_id)
    lock_name = f"beads-claim-{safe_id}"

    try:
        # Serialize check+claim across parallel agents to eliminate TOCTOU.
        with acquire_lock(lock_name, timeout=0):
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

                # Detect-and-abort: re-read and verify the assignee is actually us.
                verify_result = subprocess.run(
                    ['bd', 'show', item_id, '--json'],
                    capture_output=True,
                    text=True,
                    encoding='utf-8',
                    check=True,
                    timeout=30
                )
                verify_data = _parse_beads_json(verify_result.stdout)
                if verify_data is None:
                    print(f"⚠️  CLAIM VERIFICATION FAILED: {item_id} could not be re-read after update")
                    return False

                verify_item = verify_data[0] if isinstance(verify_data, list) else verify_data
                verify_assignee = verify_item.get('assignee', '')
                if verify_assignee.lower() != agent_name.lower():
                    print(
                        f"⚠️  CLAIM VERIFICATION FAILED: {item_id} assignee is '{verify_assignee}', "
                        f"expected '{agent_name}'"
                    )
                    return False

                # Sync to push assignment to other agents
                sync_result = run_bd_sync_with_retry()

                if sync_result.returncode == 0:
                    print(f"✅ Synced assignment - other agents will see {item_id} is claimed")
                else:
                    print(f"⚠️  bd sync returned non-zero: {sync_result.returncode}")
                    print("   Assignment may not be immediately visible to other agents")

                return True

            except (subprocess.CalledProcessError, json.JSONDecodeError) as e:
                stderr = e.stderr if isinstance(e, subprocess.CalledProcessError) else str(e)
                print(f"⚠️  Failed to assign {item_id}: {stderr}")
                return False

    except Timeout:
        print(f"⚠️  Claim lock busy ('{lock_name}') — another agent is claiming this item")
        return False


def unassign_item(item_id: str) -> bool:
    """Unassign a work item and reset its status to 'new' so other agents can claim it.

    Should be called when a post-assignment step (e.g. worktree creation) fails and
    the item needs to be returned to the ready queue.

    Args:
        item_id: The item ID to unassign.

    Returns:
        True if the item was successfully returned to 'new', False otherwise.
    """
    agent_name = get_agent_name()
    # Try resetting status and clearing the assignee in one command.
    try:
        subprocess.run(
            ['bd', 'update', item_id, '--status', 'new', '-a', ''],
            capture_output=True,
            text=True,
            encoding='utf-8',
            check=True,
            timeout=30,
        )
        print(f"↩️  Unassigned {item_id} from {agent_name} and reset to 'new'")
    except subprocess.CalledProcessError:
        # Some bd versions may not accept an empty -a; fall back to status-only reset.
        try:
            subprocess.run(
                ['bd', 'update', item_id, '--status', 'new'],
                capture_output=True,
                text=True,
                encoding='utf-8',
                check=True,
                timeout=30,
            )
            print(f"↩️  Reset {item_id} to 'new' (assignee field may still reference {agent_name})")
        except subprocess.CalledProcessError as e:
            print(f"⚠️  Failed to unassign {item_id}: {e.stderr}")
            return False

    # Best-effort sync so other agents see the item is available again.
    sync_result = run_bd_sync_with_retry()
    if sync_result.returncode != 0:
        print(f"⚠️  bd sync returned non-zero after unassign: {sync_result.returncode}")
        print(f"   Other agents may not immediately see {item_id} as available")

    return True


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


def select_next_hierarchical_item(items: list[BeadsWorkItem]) -> BeadsWorkItem | None:
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
