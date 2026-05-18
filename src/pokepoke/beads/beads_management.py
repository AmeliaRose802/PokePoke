"""Beads item management - close, assign, and select work items."""

import concurrent.futures
import json
import logging
import subprocess
import time

from filelock import Timeout

from pokepoke.agents.agent_context import get_agent_name
from pokepoke.constants import SUBPROCESS_ERRORS
from pokepoke.types_beads import BeadsWorkItem
from pokepoke.utils.constants import STATUS_IN_PROGRESS
from pokepoke.worktrees.coordination import acquire_lock

from .beads_hierarchy import HUMAN_REQUIRED_LABEL, resolve_to_leaf_task
from .beads_query import _parse_beads_json, _run_bd
from .cli_retry import _run_bd_with_retry

logger = logging.getLogger(__name__)

# Re-exports for backward compatibility
from .beads_metadata import (
    get_gate_rejection_count,
    get_total_attempts,
    increment_gate_rejection_count,
    increment_total_attempts,
)
from .sync_strategy import (
    _is_transient_jsonl_sync_error as _is_transient_jsonl_sync_error,
)

__all__ = [
    'block_item',
    'defer_item',
    'fail_task',
    'get_gate_rejection_count',
    'get_total_attempts',
    'increment_gate_rejection_count',
    'increment_total_attempts',
    '_is_transient_jsonl_sync_error',
]

# Module-level thread pool for _resolve_with_timeout to avoid creating (and
# leaking) a new ThreadPoolExecutor on every call.  A single worker suffices
# because resolutions are dispatched sequentially from select_next_hierarchical_item.
#
# NOTE: We intentionally do NOT register an atexit handler here.  The previous
# ``atexit.register(_resolve_pool.shutdown, wait=False)`` caused a race with the
# parallel orchestrator's ThreadPoolExecutor — the atexit handler fires during
# interpreter teardown while the main loop may still be calling executor.submit(),
# producing "cannot schedule new futures after interpreter shutdown".  Letting
# Python's own executor finalizer handle cleanup is sufficient.
_resolve_pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
_RESOLVE_TIMEOUT_COOLDOWN_SECONDS = 120.0
_resolve_paused_until = 0.0
_resolve_timed_out_until: dict[str, float] = {}


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
    """Quick non-locking check if an item is still claimable (unassigned)."""
    try:
        result = _run_bd(['show', item_id, '--json'])
        data = _parse_beads_json(result.stdout)
        if data is None:
            return False

        current_item = data[0] if isinstance(data, list) else data
        current_assignee = current_item.get('assignee', '')

        # Item is claimable if assignee is empty
        return not current_assignee
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, json.JSONDecodeError):
        # On error, assume not claimable (safer to skip than to try)
        return False


def _rollback_assignment(item_id: str, reason: str) -> None:
    """Best-effort rollback: unassign item with retry, or persist to manifest for startup recovery."""
    from .beads_manifest_utils import unassign_with_retry

    logger.warning("↩️  Rolling back assignment for %s: %s", item_id, reason)
    if not unassign_with_retry(item_id):
        logger.error("All retry attempts exhausted for rollback of %s: %s", item_id, reason)


def assign_and_sync_item(item_id: str, agent_name: str | None = None) -> bool:
    """Assign a work item to an agent and sync to prevent parallel conflicts."""
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

                data = _parse_beads_json(result.stdout)
                if data is not None:
                    current_item = data[0] if isinstance(data, list) else data
                    current_assignee = current_item.get('assignee', '')
                    current_status = str(current_item.get('status', '') or '')

                    if current_assignee:
                        is_ours = (current_assignee.lower() == agent_name.lower())
                        if not is_ours:
                            is_pokepoke_orphan = current_assignee.lower().startswith("pokepoke_")
                            if is_pokepoke_orphan:
                                logger.info(
                                    "♻️  Reclaiming %s from dead agent %s",
                                    item_id, current_assignee,
                                )
                            else:
                                logger.warning(f"⚠️  RACE CONDITION DETECTED: {item_id} already assigned to {current_assignee}")
                                return False

                        if current_status.lower() == STATUS_IN_PROGRESS:
                            logger.info("ℹ️  %s already assigned to %s and %s — skipping bd update", item_id, agent_name, STATUS_IN_PROGRESS)
                            return True

            except (subprocess.CalledProcessError, subprocess.TimeoutExpired, json.JSONDecodeError) as e:
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

            except (subprocess.CalledProcessError, subprocess.TimeoutExpired, json.JSONDecodeError) as e:
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
    """Unassign a work item and reset its status to 'open'."""
    agent_name = get_agent_name()
    # Try resetting status and clearing the assignee in one command.
    # NOTE: The valid beads status is 'open' (not 'new'). The bd CLI may
    # return exit-code 0 even on validation errors, so we also check stderr.
    try:
        result = _run_bd(['update', item_id, '--status', 'open', '-a', ''])
        if result.stderr and 'error' in result.stderr.lower():
            raise subprocess.CalledProcessError(1, 'bd', stderr=result.stderr)
        logger.info("↩️  Unassigned %s from %s and reset to 'open'", item_id, agent_name)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        # Some bd versions may not accept an empty -a; fall back to status-only reset.
        try:
            result = _run_bd(['update', item_id, '--status', 'open'])
            if result.stderr and 'error' in result.stderr.lower():
                raise subprocess.CalledProcessError(1, 'bd', stderr=result.stderr)
            logger.info("↩️  Reset %s to 'open' (assignee field may still reference %s)", item_id, agent_name)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            logger.error(f"⚠️  Failed to unassign {item_id}: {e}")
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
        _run_bd_with_retry(['close', item_id, '--reason', message])
        logger.info("✅ Closed %s", item_id)
        return True
    except SUBPROCESS_ERRORS as e:
        logger.error("⚠️  Failed to close %s after retries: %s", item_id, e)
        return False


def fail_task(item_id: str, reason: str, agent_type: str = "work") -> bool:
    """Record a task failure: add comment and track in stats.

    Consolidates failure bookkeeping so callers don't have to remember
    each step individually.  Does NOT unassign the item — that remains
    the caller's responsibility (via WorkItemSession or unassign_item).

    Args:
        item_id: The beads item that failed.
        reason: Human-readable explanation of why the task failed.
        agent_type: Agent type for stats tracking (e.g. "work", "gate").

    Returns:
        True if the comment was persisted, False on error.
    """
    from .beads_item_stats_store import record_item_failed

    truncated = reason[:500] if reason else "Unknown failure"
    comment_ok = add_comment(item_id, f"❌ Agent failure: {truncated}")

    try:
        record_item_failed(item_id, agent_type=agent_type)
    except Exception as exc:
        logger.warning("Failed to record failure stats for %s: %s", item_id, exc)

    logger.info("📝 Recorded failure for %s: %s", item_id, truncated[:80])
    return comment_ok


def block_item(item_id: str, reason: str) -> bool:
    """Move a beads item to 'blocked' status with a comment explaining why.

    Args:
        item_id: The item ID to block.
        reason: Human-readable explanation of why the item is blocked.

    Returns:
        True if the status was updated successfully, False otherwise.
    """
    try:
        _run_bd_with_retry(['update', item_id, '--status', 'blocked'])
        logger.info("🚫 Marked %s as blocked", item_id)
    except SUBPROCESS_ERRORS as e:
        logger.error("⚠️  Failed to block %s after retries: %s", item_id, e)
        return False
    truncated = reason[:500] if reason else "Blocked by orchestrator"
    add_comment(item_id, f"🚫 Blocked: {truncated}")
    return True


def defer_item(item_id: str, reason: str) -> bool:
    """Defer a beads item to backlog with a needs-decomposition label.

    Used when an item has exceeded the gate rejection cap, indicating it is
    too complex for a single agent session and should be broken into smaller
    pieces rather than retried.

    Args:
        item_id: The item ID to defer.
        reason: Human-readable explanation of why the item is being deferred.

    Returns:
        True if the status was updated successfully, False otherwise.
    """
    from .beads_hierarchy import NEEDS_DECOMPOSITION_LABEL

    try:
        _run_bd_with_retry([
            'update', item_id,
            '--status', 'backlog',
            '--add-label', NEEDS_DECOMPOSITION_LABEL,
        ])
        logger.info("📦 Deferred %s to backlog with %s label", item_id, NEEDS_DECOMPOSITION_LABEL)
    except SUBPROCESS_ERRORS as e:
        logger.error("⚠️  Failed to defer %s after retries: %s", item_id, e)
        return False
    truncated = reason[:500] if reason else "Deferred to backlog for decomposition"
    add_comment(item_id, f"📦 Auto-deferred: {truncated}")
    return True


def add_comment(item_id: str, comment: str) -> bool:
    """Add a comment to a beads item.

    Args:
        item_id: The item ID to add a comment to.
        comment: The comment text.

    Returns:
        True if successful, False otherwise.
    """
    try:
        _run_bd_with_retry(['comments', 'add', item_id, comment])
        logger.info("💬 Added comment to %s", item_id)
        return True
    except SUBPROCESS_ERRORS as e:
        logger.error("⚠️  Failed to add comment to %s after retries: %s", item_id, e)
        return False


def _resolve_with_timeout(
    item: BeadsWorkItem, timeout: int = 15,
) -> BeadsWorkItem | None:
    """Resolve an epic/feature to a leaf task with a timeout guard.

    Prevents multi-minute stalls when epics have many children that
    each require a bd show subprocess call.  Uses the module-level
    ``_resolve_pool`` to avoid per-call thread creation/leak.
    """
    global _resolve_paused_until
    now = time.monotonic()
    if now < _resolve_paused_until or now < _resolve_timed_out_until.get(item.id, 0.0):
        return None
    try:
        fut = _resolve_pool.submit(resolve_to_leaf_task, item)
    except RuntimeError:
        # Pool may have been shut down during interpreter teardown
        logger.debug("Resolve pool shut down — skipping hierarchical resolve for %s", item.id)
        return None
    try:
        return fut.result(timeout=timeout)
    except concurrent.futures.TimeoutError:
        fut.cancel()
        cooldown_until = time.monotonic() + _RESOLVE_TIMEOUT_COOLDOWN_SECONDS
        _resolve_paused_until = cooldown_until
        _resolve_timed_out_until[item.id] = cooldown_until
        logger.warning(
            "Hierarchical resolve timed out after %ds for %s \u2014 skipping hierarchy for %.0fs",
            timeout, item.id, _RESOLVE_TIMEOUT_COOLDOWN_SECONDS,
        )
        return None
    except Exception:
        logger.warning("Hierarchical resolve failed for %s", item.id, exc_info=True)
        return None


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

    # Prefer ready leaf tasks before attempting expensive epic resolution
    for item in sorted_items:
        if item.labels and HUMAN_REQUIRED_LABEL in item.labels:
            continue
        if item.issue_type not in ('epic', 'feature'):
            return item

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
