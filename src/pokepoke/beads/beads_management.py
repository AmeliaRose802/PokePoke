"""Beads item management - close, assign, and select work items."""

import json
import logging
import subprocess

from filelock import Timeout

from pokepoke.agents.agent_context import get_agent_name
from pokepoke.utils.constants import STATUS_IN_PROGRESS
from pokepoke.worktrees.coordination import acquire_lock
from pokepoke.types import BeadsWorkItem
from .beads_hierarchy import resolve_to_leaf_task, HUMAN_REQUIRED_LABEL
from .beads_query import _parse_beads_json, _run_bd


logger = logging.getLogger(__name__)


# Re-export for backward compatibility (moved to sync_strategy module).
from .sync_strategy import _is_transient_jsonl_sync_error as _is_transient_jsonl_sync_error


def run_bd_sync_with_retry(
    max_attempts: int = 3,
    base_delay: float = 0.5,
    timeout: int | None = 60,
) -> subprocess.CompletedProcess[str]:
    """Run beads sync with retries.  Delegates to DaemonSync (bd) or ExplicitSync (br)."""
    from .sync_strategy import get_active_sync_strategy

    return get_active_sync_strategy().sync(
        max_attempts=max_attempts,
        base_delay=base_delay,
        timeout=timeout,
    )


def is_item_claimable(item_id: str) -> bool:
    """Quick check if an item is still claimable (unassigned).

    This is a non-locking check used for pre-filtering items before dispatch.
    It catches obvious cases where an item was already claimed by another agent.

    Note: This is not atomic. Use within assign_and_sync_item's lock for
    guarantees. This function is meant for quick pre-checks to avoid
    submitting obviously-taken items to worker threads.

    Args:
        item_id: The item ID to check.

    Returns:
        True if item appears unassigned, False if assigned or error querying.
    """
    try:
        result = _run_bd(['show', item_id, '--json'])
        data = _parse_beads_json(result.stdout)
        if data is None:
            return False

        current_item = data[0] if isinstance(data, list) else data
        current_assignee = current_item.get('assignee', '')

        # Item is claimable if assignee is empty
        return not current_assignee
    except (subprocess.CalledProcessError, json.JSONDecodeError):
        # On error, assume not claimable (safer to skip than to try)
        return False


def _rollback_assignment(item_id: str, reason: str) -> None:
    """Best-effort rollback: unassign item, or persist to manifest for startup recovery."""
    logger.warning("↩️  Rolling back assignment for %s: %s", item_id, reason)
    if not unassign_item(item_id):
        from .beads_recovery import _add_failed_unassign  # late import: circular dep
        _add_failed_unassign(item_id, f"rollback failed: {reason}")


def assign_and_sync_item(item_id: str, agent_name: str | None = None) -> bool:
    """Assign a work item to an agent and sync to prevent parallel conflicts.

    Verifies the item is claimable before assigning. Returns True on success.
    """
    if agent_name is None:
        agent_name = get_agent_name()

    safe_id = ''.join(c if c.isalnum() or c in ('-', '_') else '_' for c in item_id)
    lock_name = f"beads-claim-{safe_id}"

    claimed = False
    try:
        # Serialize check+claim across parallel agents to eliminate TOCTOU.
        with acquire_lock(lock_name, timeout=0):
            # CRITICAL: Check current ownership RIGHT BEFORE claiming
            # This catches race conditions where another agent claimed between fetch and now
            try:
                result = _run_bd(['show', item_id, '--json'])

                # Parse current item state
                data = _parse_beads_json(result.stdout)
                if data is not None:
                    current_item = data[0] if isinstance(data, list) else data

                    # CRITICAL: Check 'assignee' field, NOT 'owner' field!
                    # - assignee: The specific agent currently working on it (pokepoke_agent_123)
                    # - owner: The human user who owns it (e.g., user@example.com)
                    current_assignee = current_item.get('assignee', '')
                    current_status = str(current_item.get('status', '') or '')

                    # Check if already assigned to another agent
                    if current_assignee:
                        is_ours = (current_assignee.lower() == agent_name.lower())

                        if not is_ours:
                            # Allow reclaiming items from previous PokePoke runs
                            # that were orphaned when the orchestrator was killed.
                            is_pokepoke_orphan = current_assignee.lower().startswith("pokepoke_")
                            if is_pokepoke_orphan:
                                logger.info(
                                    "♻️  Reclaiming %s from dead agent %s",
                                    item_id, current_assignee,
                                )
                            else:
                                logger.warning(f"⚠️  RACE CONDITION DETECTED: {item_id} already assigned to {current_assignee}")
                                return False

                        # If the item is already ours and in progress, this is a
                        # no-op claim (common when the orchestrator claims in the
                        # main thread before dispatching a worker).
                        if current_status.lower() == STATUS_IN_PROGRESS:
                            logger.info("ℹ️  %s already assigned to %s and %s — skipping bd update", item_id, agent_name, STATUS_IN_PROGRESS)
                            return True

            except (subprocess.CalledProcessError, json.JSONDecodeError) as e:
                logger.warning(f"⚠️  Failed to verify {item_id} ownership: {e}")
                return False

            update_succeeded = False
            try:
                # Now safe to claim - we verified it's unassigned or ours
                _run_bd(['update', item_id, '--status', STATUS_IN_PROGRESS, '-a', agent_name, '--json'])
                update_succeeded = True
                logger.info("✅ Assigned %s to %s and marked %s", item_id, agent_name, STATUS_IN_PROGRESS)

                # Detect-and-abort: re-read and verify the assignee is actually us.
                verify_result = _run_bd(['show', item_id, '--json'])
                verify_data = _parse_beads_json(verify_result.stdout)
                if verify_data is None:
                    logger.error(f"⚠️  CLAIM VERIFICATION FAILED: {item_id} could not be re-read after update")
                    _rollback_assignment(item_id, "could not re-read after update")
                    return False

                verify_item = verify_data[0] if isinstance(verify_data, list) else verify_data
                verify_assignee = verify_item.get('assignee', '')
                if verify_assignee.lower() != agent_name.lower():
                    logger.error(
                        f"⚠️  CLAIM VERIFICATION FAILED: {item_id} assignee is '{verify_assignee}', "
                        f"expected '{agent_name}'"
                    )
                    _rollback_assignment(item_id, f"assignee mismatch: '{verify_assignee}'")
                    return False

                claimed = True

            except (subprocess.CalledProcessError, json.JSONDecodeError) as e:
                stderr = e.stderr if isinstance(e, subprocess.CalledProcessError) else str(e)
                logger.error(f"⚠️  Failed to assign {item_id}: {stderr}")
                if update_succeeded:
                    _rollback_assignment(item_id, f"post-update error: {stderr}")
                return False

    except Timeout:
        logger.warning(f"⚠️  Claim lock busy ('{lock_name}') — another agent is claiming this item")
        return False

    # Best-effort sync OUTSIDE the lock so the agent slot is freed immediately.
    # The claim is already verified; sync only pushes visibility to other agents.
    if claimed:
        sync_result = run_bd_sync_with_retry()

        if sync_result.returncode == 0:
            logger.info("✅ Synced assignment - other agents will see %s is claimed", item_id)
        else:
            logger.warning(f"⚠️  bd sync returned non-zero: {sync_result.returncode}")
            logger.warning("   Assignment may not be immediately visible to other agents")

    return claimed


def unassign_item(item_id: str) -> bool:
    """Unassign a work item and reset its status to 'open' so other agents can claim it.

    Should be called when a post-assignment step (e.g. worktree creation) fails and
    the item needs to be returned to the ready queue.

    Args:
        item_id: The item ID to unassign.

    Returns:
        True if the item was successfully returned to 'open', False otherwise.
    """
    agent_name = get_agent_name()
    # Try resetting status and clearing the assignee in one command.
    # NOTE: The valid beads status is 'open' (not 'new'). The bd CLI may
    # return exit-code 0 even on validation errors, so we also check stderr.
    try:
        result = _run_bd(['update', item_id, '--status', 'open', '-a', ''])
        if result.stderr and 'error' in result.stderr.lower():
            raise subprocess.CalledProcessError(1, 'bd', stderr=result.stderr)
        logger.info("↩️  Unassigned %s from %s and reset to 'open'", item_id, agent_name)
    except subprocess.CalledProcessError:
        # Some bd versions may not accept an empty -a; fall back to status-only reset.
        try:
            result = _run_bd(['update', item_id, '--status', 'open'])
            if result.stderr and 'error' in result.stderr.lower():
                raise subprocess.CalledProcessError(1, 'bd', stderr=result.stderr)
            logger.info("↩️  Reset %s to 'open' (assignee field may still reference %s)", item_id, agent_name)
        except subprocess.CalledProcessError as e:
            logger.error(f"⚠️  Failed to unassign {item_id}: {e.stderr}")
            return False

    # Best-effort sync so other agents see the item is available again.
    sync_result = run_bd_sync_with_retry()
    if sync_result.returncode != 0:
        logger.warning(f"⚠️  bd sync returned non-zero after unassign: {sync_result.returncode}")
        logger.warning(f"   Other agents may not immediately see {item_id} as available")

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
        _run_bd(['close', item_id, '--reason', message])
        logger.info("✅ Closed %s", item_id)
        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"⚠️  Failed to close {item_id}: {e.stderr}")
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
        _run_bd(['comments', 'add', item_id, comment])
        logger.info("💬 Added comment to %s", item_id)
        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"⚠️  Failed to add comment to {item_id}: {e.stderr}")
        return False


def get_total_attempts(item_id: str) -> int:
    """Get the total attempts counter for a work item.

    Returns:
        The total number of attempts, or 0 if not tracked.
    """
    try:
        result = _run_bd(['show', item_id, '--json'], check=False)
        data = _parse_beads_json(result.stdout)
        if data is None:
            return 0

        item = data[0] if isinstance(data, list) else data
        metadata = item.get('metadata')
        if metadata and isinstance(metadata, dict):
            return int(metadata.get('total_attempts', 0))
        return 0
    except (subprocess.CalledProcessError, json.JSONDecodeError, ValueError, TypeError):
        logger.warning(f"Failed to get total_attempts for {item_id}, defaulting to 0")
        return 0


def increment_total_attempts(item_id: str) -> bool:
    """Increment the total attempts counter for a work item.

    Returns:
        True if successful, False otherwise.
    """
    try:
        current_attempts = get_total_attempts(item_id)
        new_attempts = current_attempts + 1

        metadata_json = json.dumps({'total_attempts': new_attempts})
        _run_bd(['update', item_id, '--metadata', metadata_json])
        logger.info(f"Incremented total_attempts for {item_id} to {new_attempts}")
        return True
    except (subprocess.CalledProcessError, json.JSONDecodeError, ValueError, TypeError):
        logger.warning(f"Failed to increment total_attempts for {item_id}")
        return False


def _resolve_with_timeout(
    item: BeadsWorkItem, timeout: int = 15,
) -> BeadsWorkItem | None:
    """Resolve an epic/feature to a leaf task with a timeout guard.

    Prevents multi-minute stalls when epics have many children that
    each require a bd show subprocess call.
    """
    import concurrent.futures
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    fut = pool.submit(resolve_to_leaf_task, item)
    try:
        return fut.result(timeout=timeout)
    except concurrent.futures.TimeoutError:
        logger.warning(
            "Hierarchical resolve timed out after %ds for %s — skipping",
            timeout, item.id,
        )
        return None
    except Exception:
        logger.warning("Hierarchical resolve failed for %s", item.id, exc_info=True)
        return None
    finally:
        pool.shutdown(wait=False, cancel_futures=True)


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
            # Recursively resolve to a leaf task with a timeout to prevent
            # multi-minute stalls from cascading bd show calls
            resolved = _resolve_with_timeout(item, timeout=15)
            if resolved:
                return resolved
            # Could not resolve to an assignable item - skip
            continue

        # Regular task/bug/chore - work on it directly
        return item

    return None
