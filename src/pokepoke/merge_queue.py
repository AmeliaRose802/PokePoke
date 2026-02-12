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
from concurrent.futures import Future
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from queue import Empty, Queue
from typing import Optional

from .shutdown import is_shutting_down
from .types import BeadsWorkItem

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
    future: Future  # type: ignore[type-arg]


class MergeQueue:
    """Serializes worktree merges to prevent concurrent merge conflicts.

    Uses a threading.Queue with a dedicated worker thread that processes
    one merge at a time. Between merges, runs git pull --rebase in the
    next worktree to incorporate the previous merge.
    """

    def __init__(self) -> None:
        self._queue: Queue[Optional[_MergeRequest]] = Queue()
        self._worker: Optional[threading.Thread] = None
        self._started = False
        self._shutdown_event = threading.Event()
        self._lock = threading.Lock()

    def start(self) -> None:
        """Start the merge worker thread."""
        with self._lock:
            if self._started:
                return
            self._shutdown_event.clear()
            self._worker = threading.Thread(
                target=self._worker_loop,
                daemon=True,
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
        if not self._started:
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

        if self._worker is not None:
            self._worker.join(timeout=timeout)

        with self._lock:
            self._started = False
            self._worker = None

    @property
    def pending_count(self) -> int:
        """Number of merge requests waiting in the queue."""
        return self._queue.qsize()

    @property
    def is_running(self) -> bool:
        """Whether the merge worker thread is currently running."""
        return self._started

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

        logger.info("Processing merge for %s from %s", item.id, worktree_path)

        # Rebase worktree against target branch to incorporate any previous merges
        rebase_ok = _rebase_worktree(worktree_path)
        if not rebase_ok:
            logger.warning(
                "Rebase failed for %s - attempting merge anyway", item.id
            )

        try:
            from .worktree_finalization import merge_worktree_to_dev

            success = merge_worktree_to_dev(item)
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


def _rebase_worktree(worktree_path: Path) -> bool:
    """Run git pull --rebase in a worktree to incorporate previous merges.

    Returns True if rebase succeeded or was unnecessary, False on failure.
    """
    if not worktree_path.exists():
        logger.warning("Worktree path does not exist: %s", worktree_path)
        return False

    try:
        subprocess.run(
            ["git", "pull", "--rebase"],
            cwd=str(worktree_path),
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=120,
        )
        logger.info("Rebased worktree %s successfully", worktree_path)
        return True
    except subprocess.CalledProcessError as exc:
        logger.warning(
            "Rebase failed in %s: %s", worktree_path, exc.stderr or str(exc)
        )
        # Abort the rebase to leave worktree in a clean state
        try:
            subprocess.run(
                ["git", "rebase", "--abort"],
                cwd=str(worktree_path),
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=30,
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            pass
        return False
    except subprocess.TimeoutExpired:
        logger.warning("Rebase timed out in %s", worktree_path)
        return False


# Module-level singleton
_merge_queue: Optional[MergeQueue] = None
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
