"""Recovery for failed beads unassign operations.

Provides persistent tracking and retry logic for items that failed to
unassign, preventing them from becoming permanently stuck.
"""

import logging

from .beads_management import unassign_item as _unassign
from .beads_manifest_utils import (
    _load_failed_unassign_manifest,
    remove_failed_unassign,
)

logger = logging.getLogger(__name__)


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
