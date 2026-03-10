"""RAII context manager for work-item session lifecycle.

WorkItemSession acquires resources in __enter__ (assign → branch → worktree)
and releases them in __exit__ on failure via a deterministic unwind sequence.
Journals are written before each state transition so that SessionReconciler
can clean up after crashes.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Literal
from types import TracebackType

from pokepoke.constants import BRANCH_PREFIX
from pokepoke.merge_conflict import is_merge_in_progress
from pokepoke.session_journal import (
    SessionPhase,
    delete_journal,
    write_journal,
)

logger = logging.getLogger(__name__)


class WorkItemSession:
    """Context manager that owns the lifecycle of a single work-item session.

    Usage::

        session = WorkItemSession(item_id="PokePoke-abc", agent_name="worker-1")
        with session:
            # session.worktree_path is available
            do_work(session.worktree_path)
        # On exception: resources are unwound in reverse order.
        # On success: caller is responsible for finalization.

    Attributes:
        item_id: Beads work-item ID.
        branch: Git branch name (derived from item_id).
        worktree_path: Absolute path to the worktree directory (set by __enter__).
        agent_name: Name of the agent owning this session.
    """

    def __init__(
        self,
        item_id: str,
        agent_name: str,
        *,
        branch: str | None = None,
        worktree_path: str | None = None,
        sessions_dir: Path | None = None,
        lock_timeout: float = 300.0,
    ) -> None:
        from pokepoke.git_operations import sanitize_branch_name

        self.item_id = item_id
        self.agent_name = agent_name
        sanitized = sanitize_branch_name(item_id)
        self.branch = branch if branch is not None else f"{BRANCH_PREFIX}{sanitized}"
        self.worktree_path = worktree_path or ""
        self._sessions_dir = sessions_dir
        self._lock_timeout = lock_timeout
        # Track which resources were successfully acquired for rollback.
        self._assigned = False
        self._branch_created = False
        self._worktree_created = False

    # ------------------------------------------------------------------
    # __enter__: ordered resource acquisition with rollback
    # ------------------------------------------------------------------

    def __enter__(self) -> WorkItemSession:
        """Acquire resources in order: assign → branch → worktree.

        Each step is preceded by a journal write so that SessionReconciler
        can determine what to clean up after a crash.  If any step fails,
        all previously acquired resources are released in reverse order
        before the exception propagates.
        """
        from pokepoke.beads_management import assign_and_sync_item
        from pokepoke.worktrees import create_worktree

        try:
            # Step 1 — Assign beads item
            self._write_journal(SessionPhase.ASSIGNING)
            if not assign_and_sync_item(self.item_id):
                raise RuntimeError(f"Failed to assign beads item {self.item_id}")
            self._assigned = True

            # Step 2 — Create worktree (also creates the branch)
            self._write_journal(SessionPhase.CREATING_WT)
            wt = create_worktree(self.item_id, lock_timeout=self._lock_timeout)
            self.worktree_path = str(wt)
            self._worktree_created = True
            self._branch_created = True

            # Step 3 — Mark session as ACTIVE
            self._write_journal(SessionPhase.ACTIVE)
            return self

        except BaseException:
            # Reverse-order rollback of whatever was acquired.
            self._rollback_enter()
            raise

    def _rollback_enter(self) -> None:
        """Release resources acquired during __enter__ in reverse order."""
        if self._worktree_created:
            try:
                self._remove_worktree()
            except Exception as exc:
                logger.error("Rollback: failed to remove worktree for %s: %s", self.item_id, exc)
            self._worktree_created = False

        if self._branch_created:
            try:
                self._delete_branch()
            except Exception as exc:
                logger.error("Rollback: failed to delete branch for %s: %s", self.item_id, exc)
            self._branch_created = False

        if self._assigned:
            try:
                self._unassign_beads_item()
            except Exception as exc:
                logger.error("Rollback: failed to unassign item %s: %s", self.item_id, exc)
            self._assigned = False

        try:
            delete_journal(self.item_id, sessions_dir=self._sessions_dir)
        except Exception as exc:
            logger.error("Rollback: failed to delete journal for %s: %s", self.item_id, exc)

    # ------------------------------------------------------------------
    # __exit__: failure / unwind path
    # ------------------------------------------------------------------

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> Literal[False]:
        """Release resources on failure; no-op on success.

        When *exc_type* is not ``None`` the failure unwind runs via
        :meth:`cleanup_on_failure`.  On the success path the caller is
        responsible for finalization.

        Returns ``False`` so that the original exception is never suppressed.
        """
        if exc_type is None:
            # Success path — caller is responsible for finalization.
            return False

        self.cleanup_on_failure()
        # Never suppress the original exception.
        return False

    # ------------------------------------------------------------------
    # Public cleanup API
    # ------------------------------------------------------------------

    def cleanup_on_failure(self) -> None:
        """Run the deterministic failure-unwind sequence.

        Steps (all best-effort — failures are logged at ERROR and execution
        continues so that every resource gets a cleanup attempt):

        1. ``write_journal(UNWINDING)``
        2. ``abort_any_in_progress_merge()``
        3. ``remove_worktree(force=True)``
        4. ``delete_branch()``
        5. ``unassign_beads_item()``
        6. If **all** steps succeeded → ``delete_journal()``
           Else → ``write_journal(ABANDONED)`` (leaves journal for
           :class:`SessionReconciler`)

        This method is called automatically by :meth:`__exit__` when an
        exception is active, but may also be called directly by code that
        needs to trigger cleanup outside a ``with`` block (e.g. the
        ``workflow.py`` finally block).
        """
        all_ok = True

        # Step 1 — Record that we are unwinding.
        try:
            self._write_journal(SessionPhase.UNWINDING)
        except Exception as exc:
            logger.error("Failed to write UNWINDING journal for %s: %s", self.item_id, exc)
            all_ok = False

        # Step 2 — Abort any in-progress merge.
        try:
            self._abort_any_in_progress_merge()
        except Exception as exc:
            logger.error("Failed to abort in-progress merge for %s: %s", self.item_id, exc)
            all_ok = False

        # Step 3 — Remove worktree.
        try:
            self._remove_worktree()
        except Exception as exc:
            logger.error("Failed to remove worktree for %s: %s", self.item_id, exc)
            all_ok = False

        # Step 4 — Delete branch.
        try:
            self._delete_branch()
        except Exception as exc:
            logger.error("Failed to delete branch for %s: %s", self.item_id, exc)
            all_ok = False

        # Step 5 — Unassign beads item.
        try:
            self._unassign_beads_item()
        except Exception as exc:
            logger.error("Failed to unassign beads item %s: %s", self.item_id, exc)
            all_ok = False

        # Step 6 — Final journal disposition.
        if all_ok:
            try:
                delete_journal(self.item_id, sessions_dir=self._sessions_dir)
            except Exception as exc:
                logger.error("Failed to delete journal for %s: %s", self.item_id, exc)
        else:
            try:
                self._write_journal(SessionPhase.ABANDONED)
            except Exception as exc:
                logger.error("Failed to write ABANDONED journal for %s: %s", self.item_id, exc)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _write_journal(self, phase: SessionPhase) -> Path:
        """Write the session journal with the current state."""
        return write_journal(
            item_id=self.item_id,
            branch=self.branch,
            worktree_path=self.worktree_path,
            agent_name=self.agent_name,
            phase=phase,
            sessions_dir=self._sessions_dir,
        )

    def _abort_any_in_progress_merge(self) -> None:
        """Abort a merge if one is in progress in the worktree directory."""
        wt = Path(self.worktree_path)
        if not wt.exists():
            return
        if not is_merge_in_progress(wt):
            return
        subprocess.run(
            ["git", "-C", str(wt), "merge", "--abort"],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        logger.info("Aborted in-progress merge in %s", wt)

    def _remove_worktree(self) -> None:
        """Remove the worktree directory (force)."""
        if not self.worktree_path:
            return
        from pokepoke.worktrees import cleanup_worktree

        if not cleanup_worktree(self.item_id, force=True):
            raise RuntimeError(f"cleanup_worktree returned False for {self.item_id}")

    def _delete_branch(self) -> None:
        """Delete the session's git branch."""
        from pokepoke.git_operations import branch_exists

        if not branch_exists(self.branch):
            return
        subprocess.run(
            ["git", "branch", "-D", self.branch],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )

    def _unassign_beads_item(self) -> None:
        """Return the beads item to the ready queue."""
        from pokepoke.beads_management import unassign_item

        if not unassign_item(self.item_id):
            raise RuntimeError(f"unassign_item returned False for {self.item_id}")
