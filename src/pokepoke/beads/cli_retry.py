"""Retry with exponential backoff for beads CLI subprocess calls.

Provides :func:`_is_transient_cli_error` for classifying exceptions and
:func:`_run_bd_with_retry` which wraps :func:`~pokepoke.beads.beads_query._run_bd`
with automatic retries for transient failures (timeouts, lock contention,
daemon-not-ready, OS permission races).
"""

from __future__ import annotations

import logging
import subprocess
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Transient-error detection
# ---------------------------------------------------------------------------


def _is_transient_cli_error(exc: Exception) -> bool:
    """Return True if *exc* indicates a transient CLI error worth retrying.

    Transient conditions include CLI timeouts, JSONL / file-lock contention,
    daemon-not-ready errors, and OS-level permission races.
    """
    if isinstance(exc, subprocess.TimeoutExpired):
        return True
    if isinstance(exc, OSError):
        return True
    if isinstance(exc, subprocess.CalledProcessError):
        output = f"{exc.stdout or ''}\n{exc.stderr or ''}"
        normalized = output.lower()
        if "jsonl" in normalized and (
            "lock" in normalized or "access is denied" in normalized
        ):
            return True
        if "failed to replace jsonl file" in normalized:
            return True
        if "lock" in normalized and (
            "could not" in normalized or "failed" in normalized
        ):
            return True
        if "daemon" in normalized and (
            "not" in normalized or "connect" in normalized
        ):
            return True
        if "connection" in normalized and (
            "refused" in normalized or "timed out" in normalized
        ):
            return True
    return False


# ---------------------------------------------------------------------------
# Retry wrapper
# ---------------------------------------------------------------------------


def _run_bd_with_retry(
    args: list[str],
    *,
    max_attempts: int = 3,
    base_delay: float = 0.5,
    check: bool = True,
    timeout: int | None = 30,
    cwd: str | None = None,
    backend: object | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a beads CLI command with retry and exponential backoff.

    Transient errors (timeouts, lock contention, daemon not ready) are
    retried up to *max_attempts* times with exponential back-off starting
    at *base_delay* seconds.  Non-transient errors are re-raised immediately.
    """
    from pokepoke.beads.beads_query import _run_bd

    last_exc: Exception | None = None
    cmd_label = args[0] if args else "unknown"
    for attempt in range(1, max_attempts + 1):
        try:
            result = _run_bd(
                args, check=check, timeout=timeout, cwd=cwd, backend=backend,
            )
            if attempt > 1:
                logger.info(
                    "✅ beads %s succeeded after retry (%d/%d)",
                    cmd_label, attempt, max_attempts,
                )
            return result
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as exc:
            last_exc = exc
            if _is_transient_cli_error(exc) and attempt < max_attempts:
                delay = base_delay * (2 ** (attempt - 1))
                logger.warning(
                    "⚠️  beads %s failed (attempt %d/%d), retrying in %.1fs: %s",
                    cmd_label, attempt, max_attempts, delay, exc,
                )
                time.sleep(delay)
                continue
            raise

    assert last_exc is not None  # pragma: no cover
    raise last_exc  # pragma: no cover
