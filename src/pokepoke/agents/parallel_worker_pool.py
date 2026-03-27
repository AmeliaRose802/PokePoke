"""ParallelWorkerPool: encapsulates ThreadPoolExecutor, semaphore, and futures tracking.

Extracted from ``parallel.py`` to isolate executor / futures / semaphore
management behind a cohesive class interface.  The three primary operations are:

* **dispatch_item** – acquire the semaphore and submit work to the pool
* **collect_done** – harvest completed futures, record results
* **has_active_workers** – check whether any futures are still running
"""

import concurrent.futures
import logging
import threading
from typing import Any

from pokepoke.types import BeadsWorkItem, SessionStats, WorkItemResult
from pokepoke.utils.logging_utils import RunLogger

logger = logging.getLogger(__name__)

# Type alias matching the one used in parallel.py / parallel_support.py.
_Future = concurrent.futures.Future[WorkItemResult]


# ---------------------------------------------------------------------------
# Standalone helper – kept as a module-level function so that ``parallel.py``
# can re-export it under the legacy name ``_collect_done_futures`` and tests
# that ``@patch("pokepoke.agents.parallel._collect_done_futures")`` keep
# working without modification.
# ---------------------------------------------------------------------------

def collect_done_futures(
    futures: dict[_Future, BeadsWorkItem],
    failed_claim_ids: set[str],
    total_requests: int,
    session_stats: SessionStats,
    run_logger: RunLogger,
    record_fn: Any,
) -> tuple[int, bool, int, int]:
    """Collect completed futures and record results.

    Returns ``(total_requests, any_success, success_count, failure_count)``.
    """
    done_futs: set[_Future] = set()
    for fut in list(futures):
        if fut.done():
            done_futs.add(fut)

    if not done_futs and futures:
        done_batch, _ = concurrent.futures.wait(
            futures, timeout=2.0, return_when=concurrent.futures.FIRST_COMPLETED,
        )
        done_futs.update(done_batch)
        # Second sweep: catch futures that completed while wait() was running.
        # Without this, concurrent completions are missed and slots = 1 not N.
        for fut in list(futures):
            if fut.done():
                done_futs.add(fut)

    if done_futs:
        run_logger.log_orchestrator(
            f"Agent lifecycle: collected {len(done_futs)} agent(s); "
            f"{len(futures) - len(done_futs)} remain active"
        )

    any_success = False
    success_count = 0
    failure_count = 0
    for fut in done_futs:
        item = futures.pop(fut)
        was_exception = False
        try:
            result = fut.result()
        except Exception as exc:
            logger.error(f"\n❌ Agent for {item.id} raised: {exc}")
            run_logger.log_orchestrator(f"Agent error for {item.id}: {exc}", level="ERROR")
            result = WorkItemResult(success=False, request_count=0)
            was_exception = True
        # Only blacklist explicit claim failures, not exception-crashed workers.
        if not result.success and result.request_count == 0 and not was_exception:
            failed_claim_ids.add(item.id)
        if result.success:
            failed_claim_ids.discard(item.id)
            any_success = True
            success_count += 1
        else:
            failure_count += 1
        total_requests += result.request_count
        try:
            record_fn(item, result, session_stats, run_logger)
        except Exception as exc:
            logger.warning(f"record_fn raised for {item.id}: {exc}", exc_info=True)
            run_logger.log_orchestrator(
                f"Error recording result for {item.id}: {exc}", level="ERROR"
            )

    return total_requests, any_success, success_count, failure_count


# ---------------------------------------------------------------------------
# Pool class
# ---------------------------------------------------------------------------

class ParallelWorkerPool:
    """Manages a :class:`~concurrent.futures.ThreadPoolExecutor`, a
    :class:`~threading.Semaphore`, and a ``futures`` dict that maps running
    futures to their :class:`~pokepoke.types.BeadsWorkItem`.

    Parameters
    ----------
    pool_size:
        Maximum number of concurrent workers (executor threads **and**
        semaphore permits).
    """

    def __init__(self, pool_size: int) -> None:
        self._semaphore = threading.Semaphore(pool_size)
        self._futures: dict[_Future, BeadsWorkItem] = {}
        self._executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=pool_size,
            thread_name_prefix="pokepoke-agent",
        )

    # -- Properties ----------------------------------------------------------

    @property
    def futures(self) -> dict[_Future, BeadsWorkItem]:
        """Direct reference to the internal futures dict.

        Returned by reference so that existing callers (e.g. ``parallel_support``
        functions) that read or mutate the dict continue to work.
        """
        return self._futures

    @property
    def semaphore(self) -> threading.Semaphore:
        """The pool-wide semaphore that caps concurrent workers."""
        return self._semaphore

    @property
    def executor(self) -> concurrent.futures.ThreadPoolExecutor:
        """The underlying :class:`~concurrent.futures.ThreadPoolExecutor`."""
        return self._executor

    @property
    def active_count(self) -> int:
        """Number of futures currently tracked (submitted but not yet collected)."""
        return len(self._futures)

    @property
    def active_ids(self) -> set[str]:
        """Set of work-item IDs with a tracked future."""
        return {item.id for item in self._futures.values()}

    # -- Core methods --------------------------------------------------------

    def dispatch_item(
        self,
        item: BeadsWorkItem,
        run_logger: RunLogger,
        process_item_fn: Any,
        worker_name: str,
    ) -> None:
        """Acquire the semaphore and submit *item* to the thread pool.

        On submission failure the semaphore is released and the exception
        propagated so the caller can handle clean-up (e.g. un-assign the item).
        """
        self._semaphore.acquire()
        try:
            fut = self._executor.submit(
                process_item_fn, item, run_logger, self._semaphore, worker_name,
            )
        except Exception:
            self._semaphore.release()
            raise
        self._futures[fut] = item

    def collect_done(
        self,
        failed_claim_ids: set[str],
        total_requests: int,
        session_stats: SessionStats,
        run_logger: RunLogger,
        record_fn: Any,
    ) -> tuple[int, bool, int, int]:
        """Collect completed futures and record results.

        Delegates to the module-level :func:`collect_done_futures` with
        ``self.futures``.

        Returns ``(total_requests, any_success, success_count, failure_count)``.
        """
        return collect_done_futures(
            self._futures, failed_claim_ids, total_requests,
            session_stats, run_logger, record_fn,
        )

    def has_active_workers(self) -> bool:
        """Return ``True`` if any futures are still pending or running."""
        return bool(self._futures)

    def shutdown(self, *, wait: bool = True, cancel_futures: bool = False) -> None:
        """Shut down the underlying :class:`~concurrent.futures.ThreadPoolExecutor`."""
        self._executor.shutdown(wait=wait, cancel_futures=cancel_futures)
