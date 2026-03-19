"""Crash-recovery via journal scanning.

Scans .pokepoke/sessions/*.json for abandoned session journals and cleans up
resources (worktrees, branches, beads assignments) left behind by crashed agents.

Designed to run in the existing maintenance cycle alongside other cleanup agents.
"""

import json
import logging
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from pokepoke.utils.constants import STATUS_IN_PROGRESS
from pokepoke.git.git_helpers import run_git
from pokepoke.utils.process_utils import is_process_running
from pokepoke.stats.session_journal import (
    SessionJournal,
    SessionPhase,
    delete_journal,
    list_abandoned_journals,
)

logger = logging.getLogger(__name__)

# Default timeout multiplier: config.timeout_hours * 2
_DEFAULT_TIMEOUT_MULTIPLIER = 2


def _get_session_timeout_seconds(timeout_hours: float | None = None) -> float:
    """Return session timeout in seconds.

    Default is ``timeout_hours * 2``.  When *timeout_hours* is not provided
    the workflow default of 0.5 h is used.
    """
    if timeout_hours is None:
        timeout_hours = 0.5
    return timeout_hours * _DEFAULT_TIMEOUT_MULTIPLIER * 3600


def _session_age_seconds(journal: SessionJournal) -> float:
    """Return the age of a session in seconds based on its started_at timestamp."""
    try:
        started = datetime.fromisoformat(journal.started_at)
        if started.tzinfo is None:
            started = started.replace(tzinfo=UTC)
        now = datetime.now(tz=UTC)
        return (now - started).total_seconds()
    except (ValueError, TypeError):
        # If we can't parse the timestamp, treat as very old (should be cleaned)
        return float("inf")


def _remove_worktree(worktree_path: str) -> bool:
    """Remove a worktree directory. Returns True on success."""
    path = Path(worktree_path)
    if not path.exists():
        return True
    try:
        from pokepoke.worktrees.worktree_cleanup import force_remove_directory
        return force_remove_directory(path)
    except Exception as exc:
        logger.error("Failed to remove worktree %s: %s", worktree_path, exc)
        return False


def _delete_branch(branch_name: str) -> bool:
    """Delete a local git branch. Returns True on success."""
    from pokepoke.git.git_operations import branch_exists
    if not branch_exists(branch_name):
        return True
    try:
        run_git(
            ["git", "branch", "-D", branch_name],
        )
        return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        logger.error("Failed to delete branch %s: %s", branch_name, exc)
        return False


def _should_unassign(item_id: str, agent_name: str) -> bool:
    """Check if the beads item is in_progress and assigned to the given agent."""
    try:
        result = subprocess.run(
            ["bd", "show", item_id, "--json"],
            capture_output=True, text=True,
            encoding="utf-8", errors="replace",
            check=True, timeout=30,
        )
        items = json.loads(result.stdout or "[]")
        if not items:
            return False
        item = items[0] if isinstance(items, list) else items
        status = (item.get("status") or "").lower()
        assignee = item.get("assignee") or ""
        return status == STATUS_IN_PROGRESS and assignee == agent_name
    except Exception as exc:
        logger.warning("Failed to check beads item %s: %s", item_id, exc)
        return False


def _unassign_item(item_id: str) -> bool:
    """Unassign a beads item so it returns to the ready queue."""
    try:
        from pokepoke.beads.beads_management import unassign_item
        return unassign_item(item_id)
    except Exception as exc:
        logger.error("Failed to unassign item %s: %s", item_id, exc)
        return False


def _reconcile_journal(
    journal: SessionJournal,
    session_timeout: float,
    sessions_dir: Path | None = None,
) -> None:
    """Reconcile a single session journal entry.

    Args:
        journal: The journal to reconcile.
        session_timeout: Maximum session age in seconds before forced cleanup.
        sessions_dir: Override for the sessions directory (used in tests).
    """
    item_id = journal.item_id
    phase = journal.phase

    # CLOSED journals: just delete and move on
    if phase == SessionPhase.CLOSED.value:
        delete_journal(item_id, sessions_dir)
        logger.debug("Deleted CLOSED journal for %s", item_id)
        return

    # If PID is alive and session is within timeout, skip (still running)
    if is_process_running(journal.pid):
        age = _session_age_seconds(journal)
        if age < session_timeout:
            logger.debug(
                "Skipping %s: PID %d alive, age %.0fs < timeout %.0fs",
                item_id, journal.pid, age, session_timeout,
            )
            return

    # PID dead or timed out — clean up
    logger.warning(
        "Reconciling abandoned session %s (phase=%s, pid=%d)",
        item_id, phase, journal.pid,
    )
    all_ok = True

    # Step 1: Remove worktree if it exists
    worktree_path = journal.worktree_path
    if Path(worktree_path).exists() and not _remove_worktree(worktree_path):
        logger.error("Worktree removal failed for %s, leaving journal for next cycle", item_id)
        all_ok = False

    # Step 2: Delete branch if it exists
    if journal.branch and not _delete_branch(journal.branch):
        logger.error("Branch deletion failed for %s, leaving journal for next cycle", item_id)
        all_ok = False

    # Step 3: Unassign beads item if still assigned to this agent
    if _should_unassign(item_id, journal.agent_name) and not _unassign_item(item_id):
        logger.error("Unassign failed for %s, leaving journal for next cycle", item_id)
        all_ok = False

    # Step 4: Delete journal only if all cleanup steps succeeded
    if all_ok:
        delete_journal(item_id, sessions_dir)
        logger.info("Successfully reconciled abandoned session %s", item_id)
    else:
        logger.error(
            "Partial cleanup for %s — journal left for next cycle", item_id
        )


def run(sessions_dir: Path | None = None) -> int:
    """Scan all session journals and reconcile abandoned sessions.

    Args:
        sessions_dir: Override for the sessions directory (used in tests).

    Returns:
        Number of journals that were fully reconciled (cleaned up and deleted).
    """
    journals = list_abandoned_journals(sessions_dir)
    if not journals:
        return 0

    session_timeout = _get_session_timeout_seconds()
    logger.info(
        "SessionReconciler: scanning %d journal(s), timeout=%.0fs",
        len(journals), session_timeout,
    )

    reconciled = 0
    for journal in journals:
        existed_before = (
            sessions_dir or Path(".pokepoke") / "sessions"
        ) / f"{journal.item_id}.json"
        _reconcile_journal(journal, session_timeout, sessions_dir)
        if not existed_before.exists():
            reconciled += 1

    if reconciled:
        logger.info("SessionReconciler: reconciled %d session(s)", reconciled)

    return reconciled
