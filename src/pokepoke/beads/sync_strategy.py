"""Sync strategy abstraction for beads backends.

Provides pluggable sync behaviour so both daemon-based (``bd``) and
explicit-sync (``br``) backends work correctly through the same public API.

* :class:`DaemonSync` — ``bd`` uses a background daemon for auto-sync.
  Calling ``bd sync`` triggers the daemon; retries handle transient JSONL
  lock errors that arise when multiple agents sync concurrently.

* :class:`ExplicitSync` — ``br`` requires explicit sync calls and follow-up
  git operations (add / commit / push) to publish changes to other agents.
"""

from __future__ import annotations

import abc
import logging
import subprocess
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pokepoke.beads.beads_query import CLIBackendConfig


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Transient-error detection helpers
# ---------------------------------------------------------------------------


def _is_transient_jsonl_sync_error(output: str) -> bool:
    """Return True if *output* indicates a transient JSONL lock error (``bd``)."""
    normalized = output.lower()
    if "access is denied" in normalized and "jsonl" in normalized:
        return True
    return (
        "failed to replace jsonl file" in normalized
        or "jsonl file hash mismatch" in normalized
    )


def _is_transient_br_sync_error(output: str) -> bool:
    """Return True if *output* indicates a transient ``br`` sync error.

    Retryable conditions include git lock contention (stale ``index.lock``),
    and network connectivity hiccups.
    """
    normalized = output.lower()
    if "index.lock" in normalized:
        return True
    if "lock" in normalized and (
        "could not" in normalized or "failed" in normalized
    ):
        return True
    if "connection" in normalized and (
        "refused" in normalized or "timed out" in normalized
    ):
        return True
    return False


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------


class SyncStrategy(abc.ABC):
    """Abstract base class for beads sync strategies."""

    @abc.abstractmethod
    def sync(
        self,
        max_attempts: int = 3,
        base_delay: float = 0.5,
        timeout: int | None = 60,
    ) -> subprocess.CompletedProcess[str]:
        """Sync the beads database with retries for transient errors.

        Args:
            max_attempts: Maximum retry attempts.
            base_delay: Initial delay between retries (doubles each attempt).
            timeout: Maximum seconds per sync attempt.  Defaults to 60 s to
                prevent indefinite hangs inside file locks.

        Returns:
            :class:`~subprocess.CompletedProcess` from the final sync attempt.
        """
        ...


# ---------------------------------------------------------------------------
# Concrete strategies
# ---------------------------------------------------------------------------


class DaemonSync(SyncStrategy):
    """Sync strategy for ``bd`` (background daemon).

    ``bd`` uses a background daemon that auto-syncs.  Calling ``bd sync``
    triggers the daemon to push/pull.  Retries handle transient JSONL lock
    errors that occur when multiple agents sync concurrently.
    """

    def __init__(self, backend: CLIBackendConfig | None = None) -> None:
        self._backend = backend

    def _get_backend(self) -> CLIBackendConfig:
        from pokepoke.beads.beads_query import get_active_backend

        if self._backend is not None:
            return self._backend
        return get_active_backend()

    def sync(
        self,
        max_attempts: int = 3,
        base_delay: float = 0.5,
        timeout: int | None = 60,
    ) -> subprocess.CompletedProcess[str]:
        from pokepoke.beads.beads_query import _run_cli

        last_result: subprocess.CompletedProcess[str] | None = None
        for attempt in range(1, max_attempts + 1):
            result = _run_cli(
                ["sync"],
                backend=self._get_backend(),
                check=False,
                timeout=timeout,
            )
            last_result = result
            if result.returncode == 0:
                if attempt > 1:
                    print(
                        f"✅ bd sync succeeded after retry "
                        f"({attempt}/{max_attempts})"
                    )
                return result

            output = f"{result.stdout}\n{result.stderr}"
            if _is_transient_jsonl_sync_error(output) and attempt < max_attempts:
                delay = base_delay * (2 ** (attempt - 1))
                message = (
                    "⚠️  bd sync failed due to locked JSONL file; "
                    f"retrying in {delay:.1f}s (attempt {attempt}/{max_attempts})"
                )
                print(message)
                logger.warning(message)
                time.sleep(delay)
                continue
            return result

        assert last_result is not None
        return last_result


class ExplicitSync(SyncStrategy):
    """Sync strategy for ``br`` (explicit sync with git operations).

    ``br`` does not use a background daemon.  Syncing requires:

    1. Call ``br sync`` to synchronise the local beads database.
    2. Stage beads changes with ``git add``.
    3. Commit and push to make changes visible to other agents.

    Retries handle transient errors like git lock contention and connection
    timeouts.  Non-transient failures (e.g. merge conflicts) are returned
    immediately so the caller can decide how to proceed.
    """

    def __init__(self, backend: CLIBackendConfig | None = None) -> None:
        self._backend = backend

    def _get_backend(self) -> CLIBackendConfig:
        from pokepoke.beads.beads_query import get_active_backend

        if self._backend is not None:
            return self._backend
        return get_active_backend()

    def sync(
        self,
        max_attempts: int = 3,
        base_delay: float = 0.5,
        timeout: int | None = 60,
    ) -> subprocess.CompletedProcess[str]:
        from pokepoke.beads.beads_query import _run_cli

        last_result: subprocess.CompletedProcess[str] | None = None
        for attempt in range(1, max_attempts + 1):
            result = _run_cli(
                ["sync"],
                backend=self._get_backend(),
                check=False,
                timeout=timeout,
            )
            last_result = result
            if result.returncode == 0:
                if attempt > 1:
                    print(
                        f"✅ br sync succeeded after retry "
                        f"({attempt}/{max_attempts})"
                    )
                if not self._git_publish_sync():
                    # br sync succeeded but git publish failed
                    return subprocess.CompletedProcess(
                        args=result.args,
                        returncode=1,
                        stdout=result.stdout,
                        stderr="git publish failed after successful br sync"
                    )
                return result

            output = f"{result.stdout}\n{result.stderr}"
            if _is_transient_br_sync_error(output) and attempt < max_attempts:
                delay = base_delay * (2 ** (attempt - 1))
                message = (
                    "⚠️  br sync failed due to transient error; "
                    f"retrying in {delay:.1f}s (attempt {attempt}/{max_attempts})"
                )
                print(message)
                logger.warning(message)
                time.sleep(delay)
                continue
            return result

        assert last_result is not None
        return last_result

    # -- internal helpers ----------------------------------------------------

    @staticmethod
    def _git_publish_sync() -> bool:
        """Best-effort ``git add / commit / push`` after a successful ``br sync``.

        Returns:
            True if publish succeeded or there were no changes to publish.
            False if git operations failed.
        """
        try:
            status = subprocess.run(
                ["git", "status", "--porcelain", ".beads/"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if not status.stdout.strip():
                return True  # Nothing to commit - success

            subprocess.run(
                ["git", "add", ".beads/"],
                capture_output=True,
                text=True,
                timeout=10,
                check=True,
            )
            subprocess.run(
                ["git", "commit", "-m", "beads: sync database"],
                capture_output=True,
                text=True,
                timeout=10,
                check=True,
            )
            subprocess.run(
                ["git", "push"],
                capture_output=True,
                text=True,
                timeout=30,
                check=True,
            )
            return True
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as exc:
            logger.warning("⚠️  Best-effort git publish after br sync failed: %s", exc)
            return False


# ---------------------------------------------------------------------------
# Module-level active sync strategy
# ---------------------------------------------------------------------------

_active_sync_strategy: SyncStrategy = DaemonSync()


def get_active_sync_strategy() -> SyncStrategy:
    """Return the currently active sync strategy."""
    return _active_sync_strategy


def set_active_sync_strategy(strategy: SyncStrategy) -> None:
    """Set the active sync strategy."""
    global _active_sync_strategy
    _active_sync_strategy = strategy
