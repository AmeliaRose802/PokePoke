"""Shared manifest utilities for beads tracking.

Provides persistent tracking for failed unassign operations,
allowing recovery without creating circular dependencies between
beads_management and beads_recovery modules.
"""

import json
import logging
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from pokepoke.worktrees.coordination import manifest_lock

logger = logging.getLogger(__name__)

__all__ = [
    'FailedUnassignEntry',
    'FailedUnassignManifest',
    'add_failed_unassign',
    'remove_failed_unassign',
    'unassign_with_retry',
]

# Retry settings for unassign operations
_UNASSIGN_MAX_RETRIES = 3
_UNASSIGN_BASE_DELAY = 1.0  # seconds


@dataclass(frozen=True)
class FailedUnassignEntry:
    """A single entry in the failed-unassign manifest."""

    reason: str
    timestamp: str


FailedUnassignManifest = dict[str, FailedUnassignEntry]


def _get_failed_unassign_manifest_path() -> Path:
    """Get the path to the failed unassigns manifest file."""
    return Path(".pokepoke") / "failed_unassigns.json"


def _load_failed_unassign_manifest() -> FailedUnassignManifest:
    """Load the failed unassigns manifest."""
    manifest_path = _get_failed_unassign_manifest_path()
    if not manifest_path.exists():
        return {}
    try:
        with open(manifest_path, encoding='utf-8') as f:
            raw = json.load(f)
            if isinstance(raw, dict):
                return {
                    k: FailedUnassignEntry(
                        reason=str(v.get("reason", "")),
                        timestamp=str(v.get("timestamp", "")),
                    )
                    for k, v in raw.items()
                    if isinstance(v, dict)
                }
            return {}
    except (json.JSONDecodeError, OSError):
        return {}


def _save_failed_unassign_manifest(manifest: FailedUnassignManifest) -> None:
    """Save the failed unassigns manifest."""
    manifest_path = _get_failed_unassign_manifest_path()
    try:
        manifest_path.parent.mkdir(exist_ok=True)
        serializable = {k: asdict(v) for k, v in manifest.items()}
        # Write atomically via a temp file, then rename.
        tmp = manifest_path.with_suffix('.tmp')
        tmp.write_text(json.dumps(serializable, indent=2, ensure_ascii=False), encoding='utf-8')
        tmp.replace(manifest_path)
    except OSError as e:
        logger.warning('Failed to save unassign manifest: %s', e)


def add_failed_unassign(item_id: str, reason: str) -> None:
    """Track an item whose unassign failed for later recovery."""
    with manifest_lock():
        manifest = _load_failed_unassign_manifest()
        manifest[item_id] = FailedUnassignEntry(
            reason=reason,
            timestamp=datetime.now().isoformat(),
        )
        _save_failed_unassign_manifest(manifest)


def remove_failed_unassign(item_id: str) -> None:
    """Remove an item from the failed-unassign manifest after recovery."""
    with manifest_lock():
        manifest = _load_failed_unassign_manifest()
        if item_id in manifest:
            del manifest[item_id]
            _save_failed_unassign_manifest(manifest)


def unassign_with_retry(item_id: str) -> bool:
    """Unassign an item with retry and persistent failure tracking.

    Retries up to ``_UNASSIGN_MAX_RETRIES`` times with exponential backoff.
    If all retries fail, the item ID is persisted to a manifest file so that
    ``retry_failed_unassigns()`` can recover it later.

    Args:
        item_id: The item ID to unassign.

    Returns:
        True if the item was successfully unassigned, False otherwise.
    """
    # Import here to avoid circular dependency during module initialization
    from .beads_management import unassign_item

    last_error: Exception | None = None
    for attempt in range(1, _UNASSIGN_MAX_RETRIES + 1):
        try:
            if unassign_item(item_id):
                return True
            last_error = RuntimeError(f"unassign_item returned False on attempt {attempt}")
        except Exception as e:
            last_error = e
        if attempt < _UNASSIGN_MAX_RETRIES:
            delay = _UNASSIGN_BASE_DELAY * (2 ** (attempt - 1))
            logger.info("Retrying unassign for %s in %.1fs (attempt %d/%d)",
                        item_id, delay, attempt, _UNASSIGN_MAX_RETRIES)
            time.sleep(delay)

    # All retries exhausted — persist for later recovery
    reason = str(last_error) if last_error else "unknown"
    logger.warning("All %d unassign attempts failed for %s: %s",
                   _UNASSIGN_MAX_RETRIES, item_id, reason)
    add_failed_unassign(item_id, reason)
    return False
