"""Merge queue coordinator for serialized worktree merges.

When parallel agents complete work simultaneously, they must not merge
to the target branch concurrently. This module provides a MergeQueue
that serializes merges using a threading.Queue + dedicated worker thread.

Agents call merge_queue.submit(worktree_path, item) when their work
passes the gate. The queue processes one merge at a time using
merge_worktree_to_dev() from worktree_finalization.py.
"""

import logging
import subprocess
import threading
import time
from concurrent.futures import Future
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from queue import Empty, Queue

from .git_operations import get_default_branch, is_worktree_clean
from .shutdown import is_shutting_down
from .types import BeadsWorkItem
from .beads import is_high_conflict_risk

logger = logging.getLogger(__name__)

# Queue polling interval (seconds) - how often the worker checks for shutdown
_QUEUE_POLL_INTERVAL = 1.0


class MergeStatus(Enum):
    """Result status for a merge request."""
    SUCCESS = "success"
    CONFLICT = "conflict"
    FAILED = "failed"
    SHUTDOWN = "shutdown"


@dataclass
class MergeResult:
    """Result of a merge operation."""
    status: MergeStatus
    item_id: str
    message: str = ""


@dataclass
class _MergeRequest:
    """Internal merge request placed on the queue."""
    worktree_path: Path
    item: BeadsWorkItem
    future: Future[MergeResult]


class MergeQueue:
    """Serializes worktree merges to prevent concurrent merge conflicts.

    Uses a threading.Queue with a dedicated worker thread that processes
    one merge at a time. Between merges, runs git pull --rebase in the
    next worktree to incorporate the previous merge.
    """

    def __init__(self) -> None:
        self._queue: Queue[_MergeRequest | None] = Queue()
        self._worker: threading.Thread | None = None
        self._started = False
        self._shutdown_event = threading.Event()
        self._lock = threading.Lock()

    def start(self) -> None:
        """Start the merge worker thread."""
        with self._lock:
            if self._started:
                if self._worker is not None and self._worker.is_alive():
                    return
                self._started = False
                self._worker = None
            self._shutdown_event.clear()
            self._worker = threading.Thread(
                target=self._worker_loop,
                daemon=False,
                name="merge-queue-worker",
            )
            self._worker.start()
            self._started = True

    def submit(self, worktree_path: Path, item: BeadsWorkItem) -> "Future[MergeResult]":
        """Submit a merge request to the queue.

        Args:
            worktree_path: Path to the worktree to merge.
            item: The beads work item being merged.

        Returns:
            A Future that resolves to a MergeResult when the merge completes.
        """
        if not self.is_running:
            self.start()

        future: Future[MergeResult] = Future()
        request = _MergeRequest(
            worktree_path=worktree_path,
            item=item,
            future=future,
        )
        self._queue.put(request)
        logger.info("Queued merge for %s (queue size: %d)", item.id, self._queue.qsize())
        return future

    def shutdown(self, timeout: float = 30.0) -> None:
        """Signal the worker to stop and wait for it to finish.

        Drains any remaining items in the queue before stopping.

        Args:
            timeout: Maximum seconds to wait for the worker thread to finish.
        """
        with self._lock:
            if not self._started:
                return
            self._shutdown_event.set()
            # Send sentinel to unblock worker if waiting on queue.get()
            self._queue.put(None)

        worker = self._worker
        if worker is not None:
            worker.join(timeout=timeout)

        with self._lock:
            if worker is not None and worker.is_alive():
                logger.warning(
                    "Merge queue worker did not stop within %.1fs; shutdown will continue in background.",
                    timeout,
                )
                return
            self._started = False
            self._worker = None

    @property
    def pending_count(self) -> int:
        """Number of merge requests waiting in the queue."""
        return self._queue.qsize()

    @property
    def is_running(self) -> bool:
        """Whether the merge worker thread is currently running."""
        worker = self._worker
        return worker is not None and worker.is_alive()

    def _worker_loop(self) -> None:
        """Main loop for the merge worker thread."""
        logger.info("Merge queue worker started")
        while not self._shutdown_event.is_set() and not is_shutting_down():
            try:
                request = self._queue.get(timeout=_QUEUE_POLL_INTERVAL)
            except Empty:
                continue

            # None sentinel signals shutdown
            if request is None:
                # Drain remaining items with shutdown results
                self._drain_on_shutdown()
                break

            self._process_request(request)

        # Drain anything left after loop exits
        self._drain_on_shutdown()
        logger.info("Merge queue worker stopped")

    def _process_request(self, request: _MergeRequest) -> None:
        """Process a single merge request."""
        item = request.item
        worktree_path = request.worktree_path
        high_conflict = is_high_conflict_risk(item)

        logger.info("Processing merge for %s from %s", item.id, worktree_path)
        if high_conflict:
            logger.info("Applying cautious merge strategy for high-conflict item %s", item.id)

        # Rebase worktree against target branch to incorporate any previous merges
        target_branch = get_default_branch()
        rebase_ok = _rebase_worktree(worktree_path, target_branch=target_branch)
        if high_conflict and rebase_ok:
            logger.info("Second safety rebase for high-conflict item %s", item.id)
            rebase_ok = _rebase_worktree(worktree_path, target_branch=target_branch) and rebase_ok
            time.sleep(1.0)
        if not rebase_ok:
            if not is_worktree_clean(worktree_path):
                logger.error(
                    "Worktree %s is dirty after failed rebase for %s - skipping merge",
                    worktree_path,
                    item.id,
                )
                from .worktree_cleanup import add_uncleaned_worktree

                add_uncleaned_worktree(
                    worktree_id=item.id,
                    worktree_path=str(worktree_path),
                    reason="Rebase failed and abort left worktree in dirty state",
                )
                request.future.set_result(
                    MergeResult(
                        status=MergeStatus.FAILED,
                        item_id=item.id,
                        message="Rebase failed and worktree is in dirty state after abort",
                    )
                )
                return
            logger.warning(
                "Rebase failed for %s but worktree is clean - attempting merge", item.id
            )

        try:
            from .worktree_finalization import merge_worktree_to_dev

            success = merge_worktree_to_dev(item, worktree_path=worktree_path)
            if success:
                result = MergeResult(
                    status=MergeStatus.SUCCESS,
                    item_id=item.id,
                    message="Merge completed successfully",
                )
            else:
                result = MergeResult(
                    status=MergeStatus.FAILED,
                    item_id=item.id,
                    message="merge_worktree_to_dev returned False",
                )
        except Exception as exc:
            logger.exception("Merge failed for %s", item.id)
            result = MergeResult(
                status=MergeStatus.FAILED,
                item_id=item.id,
                message=str(exc),
            )

        request.future.set_result(result)

    def _drain_on_shutdown(self) -> None:
        """Drain remaining queue items, setting shutdown results."""
        while True:
            try:
                request = self._queue.get_nowait()
            except Empty:
                break
            if request is None:
                continue
            result = MergeResult(
                status=MergeStatus.SHUTDOWN,
                item_id=request.item.id,
                message="Merge queue shutting down",
            )
            request.future.set_result(result)


def _abort_rebase(worktree_path: Path) -> None:
    """Abort a rebase and verify worktree state.

    Attempts to abort an in-progress rebase. If the abort fails,
    verifies the worktree state and logs any inconsistencies.
    """
    try:
        subprocess.run(
            ["git", "rebase", "--abort"],
            cwd=str(worktree_path),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors='replace',
            timeout=30,
            check=True,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as abort_exc:
        logger.warning(
            "Failed to abort rebase in %s: %s. Worktree may be in inconsistent state.",
            worktree_path,
            abort_exc.stderr if hasattr(abort_exc, "stderr") else str(abort_exc),
        )
        # Verify worktree state after abort failure
        try:
            status_result = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=str(worktree_path),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors='replace',
                timeout=10,
                check=True,
            )
            if status_result.stdout.strip():
                logger.error(
                    "Worktree %s is dirty after failed rebase abort: %s",
                    worktree_path,
                    status_result.stdout[:200],
                )
        except Exception as status_exc:
            logger.error(
                "Unable to verify worktree state in %s: %s",
                worktree_path,
                str(status_exc),
            )


def _rebase_worktree(worktree_path: Path, target_branch: str | None = None) -> bool:
    """Rebase a worktree onto the latest target branch.

    Uses explicit ``git fetch origin`` + ``git rebase origin/<target>``
    instead of ``git pull --rebase`` to avoid the
    "Cannot rebase onto multiple branches" error that occurs when
    FETCH_HEAD contains multiple merge entries (common when beads-sync
    or other branches are being pushed concurrently).

    Returns True if rebase succeeded or was unnecessary, False on failure.
    """
    if not worktree_path.exists():
        logger.warning("Worktree path does not exist: %s", worktree_path)
        return False

    if target_branch is None:
        target_branch = get_default_branch()

    try:
        subprocess.run(
            ["git", "fetch", "origin", target_branch],
            cwd=str(worktree_path),
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors='replace',
            timeout=60,
        )
        subprocess.run(
            ["git", "rebase", f"origin/{target_branch}"],
            cwd=str(worktree_path),
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors='replace',
            timeout=120,
        )
        logger.info("Rebased worktree %s onto origin/%s successfully", worktree_path, target_branch)
        return True
    except subprocess.CalledProcessError as exc:
        logger.warning(
            "Rebase failed in %s: %s", worktree_path, exc.stderr or str(exc)
        )
        _abort_rebase(worktree_path)
        return False
    except subprocess.TimeoutExpired:
        logger.warning("Rebase timed out in %s", worktree_path)
        _abort_rebase(worktree_path)
        return False


# Module-level singleton
_merge_queue: MergeQueue | None = None
_singleton_lock = threading.Lock()


def get_merge_queue() -> MergeQueue:
    """Get or create the module-level MergeQueue singleton."""
    global _merge_queue
    with _singleton_lock:
        if _merge_queue is None:
            _merge_queue = MergeQueue()
        return _merge_queue


def reset_merge_queue() -> None:
    """Reset the singleton. Only for tests."""
    global _merge_queue
    with _singleton_lock:
        if _merge_queue is not None:
            _merge_queue.shutdown(timeout=5.0)
        _merge_queue = None
