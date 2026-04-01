"""Recovery for failed beads unassign operations.

Provides persistent tracking and retry logic for items that failed to
unassign, preventing them from becoming permanently stuck.
"""

import logging
import time

from .beads_management import unassign_item as _unassign
from .beads_manifest_utils import (
    _load_failed_unassign_manifest,
    add_failed_unassign,
    remove_failed_unassign,
)

logger = logging.getLogger(__name__)

# Retry settings for unassign operations
_UNASSIGN_MAX_RETRIES = 3
_UNASSIGN_BASE_DELAY = 1.0  # seconds


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
    add_failed_unassign(item_id, reason)
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
                remove_failed_unassign(item_id)
                recovered += 1
                logger.info("Recovered stuck item %s", item_id)
        except Exception as e:
            logger.warning("Still unable to unassign %s: %s", item_id, e)

    if recovered:
        logger.info(f"↩️  Recovered {recovered} previously stuck item(s)")
    return recovered
