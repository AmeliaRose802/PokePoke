"""Helpers for coordinating access to the main repository when it's dirty.

Provides a cross-process cleanup lock plus polling utilities so only one
cleanup-capable agent attempts to fix uncommitted changes at a time, while
other schedulers can wait until the repository is ready.
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from pathlib import Path
from collections.abc import Callable, Iterable, Generator

from pokepoke.coordination import acquire_lock, try_lock
from pokepoke.git_operations import verify_main_repo_clean

CleanupLogFn = Callable[[str], None]

_CLEANUP_LOCK_NAME = "main-repo-cleanup"


def _emit(message: str, log_fn: CleanupLogFn | None) -> None:
    """Emit a log message either through RunLogger or stdout."""
    if log_fn:
        log_fn(message)
    else:
        print(message)


def is_main_repo_clean(repo_path: Path | None = None) -> tuple[bool, list[str]]:
    """Return whether the main repo is clean plus the list of dirty files."""
    cwd = str(repo_path) if repo_path else None
    try:
        is_clean, _raw, non_beads = verify_main_repo_clean(cwd=cwd)
        return is_clean, non_beads
    except RuntimeError as exc:
        # Treat failures as dirty to avoid races that could lose work.
        return False, [str(exc)]


def cleanup_lock_active() -> bool:
    """Return True if another cleanup-capable agent currently holds the lock."""
    lock = try_lock(_CLEANUP_LOCK_NAME)
    if lock is None:
        return True
    lock.release()
    return False


@contextmanager
def cleanup_lock(timeout: float = 600.0) -> Generator[None, None, None]:
    """Block until the cleanup lock is available, then yield to the caller."""
    with acquire_lock(_CLEANUP_LOCK_NAME, timeout=timeout):
        yield


def wait_for_main_repo_clean(
    repo_path: Path | None = None,
    *,
    timeout: float = 180.0,
    poll_interval: float = 2.0,
    log_fn: CleanupLogFn | None = None,
) -> bool:
    """Poll until the main repo is clean and no cleanup agent is running.

    Args:
        repo_path: Optional repo path; defaults to the current working directory.
        timeout: Seconds to wait before giving up. ``-1`` waits indefinitely.
        poll_interval: Seconds between status checks.
        log_fn: Optional logger callable for status updates.

    Returns:
        True when the repository is clean and no cleanup agent owns the lock.
        False if the timeout elapsed while waiting.
    """
    deadline = (time.time() + timeout) if timeout >= 0 else None

    while True:
        is_clean, dirty_files = is_main_repo_clean(repo_path)
        lock_busy = cleanup_lock_active()

        if is_clean and not lock_busy:
            return True

        if not is_clean:
            sample = list(_truncate_files(dirty_files))
            summary = ", ".join(sample)
            if len(dirty_files) > len(sample):
                summary += f", … +{len(dirty_files) - len(sample)} more"
            _emit(
                f"Main repo dirty ({len(dirty_files)} file(s)). Waiting for cleanup to finish: {summary}",
                log_fn,
            )
        elif lock_busy:
            _emit("Cleanup agent still holding lock; waiting before scheduling new agents.", log_fn)

        if deadline is not None and time.time() >= deadline:
            _emit("Timed out waiting for main repo to become clean.", log_fn)
            return False

        time.sleep(poll_interval)


def _truncate_files(files: Iterable[str], limit: int = 3) -> Iterable[str]:
    """Yield up to *limit* formatted file paths for logging."""
    count = 0
    for f in files:
        yield f.strip()
        count += 1
        if count >= limit:
            break
