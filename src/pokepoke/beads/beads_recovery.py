"""Recovery for failed beads unassign operations.

Provides persistent tracking and retry logic for items that failed to
unassign, preventing them from becoming permanently stuck.
"""

import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import cast

from pokepoke.worktrees.coordination import manifest_lock

from .beads_management import unassign_item as _unassign

logger = logging.getLogger(__name__)

# Retry settings for unassign operations
_UNASSIGN_MAX_RETRIES = 3
_UNASSIGN_BASE_DELAY = 1.0  # seconds


def _get_failed_unassign_manifest_path() -> Path:
    """Get the path to the failed unassigns manifest file."""
    return Path(".pokepoke") / "failed_unassigns.json"


def _load_failed_unassign_manifest() -> dict[str, dict[str, str]]:
    """Load the failed unassigns manifest."""
    manifest_path = _get_failed_unassign_manifest_path()
    if not manifest_path.exists():
        return {}
    try:
        with open(manifest_path, encoding='utf-8') as f:
            raw = json.load(f)
            if isinstance(raw, dict):
                return cast(dict[str, dict[str, str]], raw)
            return {}
    except (json.JSONDecodeError, OSError):
        return {}


def _save_failed_unassign_manifest(manifest: dict[str, dict[str, str]]) -> None:
    """Save the failed unassigns manifest."""
    manifest_path = _get_failed_unassign_manifest_path()
    try:
        manifest_path.parent.mkdir(exist_ok=True)
        # Write atomically via a temp file, then rename.
        tmp = manifest_path.with_suffix('.tmp')
        tmp.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding='utf-8')
        tmp.replace(manifest_path)
    except OSError as e:
        logger.warning('Failed to save unassign manifest: %s', e)


def _add_failed_unassign(item_id: str, reason: str) -> None:
    """Track an item whose unassign failed for later recovery."""
    with manifest_lock():
        manifest = _load_failed_unassign_manifest()
        manifest[item_id] = {
            "reason": reason,
            "timestamp": datetime.now().isoformat(),
        }
        _save_failed_unassign_manifest(manifest)


def _remove_failed_unassign(item_id: str) -> None:
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
    last_error: Exception | None = None
    for attempt in range(1, _UNASSIGN_MAX_RETRIES + 1):
        try:
            if _unassign(item_id):
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
    _add_failed_unassign(item_id, reason)
    return False


def get_failed_unassign_count() -> int:
    """Return the number of items that failed to unassign."""
    return len(_load_failed_unassign_manifest())


def retry_failed_unassigns() -> int:
    """Retry unassigning items that previously failed.

    Iterates over the failed-unassign manifest and attempts to unassign each
    item.  Successfully recovered items are removed from the manifest.

    Returns:
        The number of items successfully recovered.
    """
    manifest = _load_failed_unassign_manifest()
    if not manifest:
        return 0

    recovered = 0
    for item_id in list(manifest):
        try:
            if _unassign(item_id):
                _remove_failed_unassign(item_id)
                recovered += 1
                logger.info("Recovered stuck item %s", item_id)
        except Exception as e:
            logger.warning("Still unable to unassign %s: %s", item_id, e)

    if recovered:
        logger.info(f"↩️  Recovered {recovered} previously stuck item(s)")
    return recovered
