"""Beads metadata management - track attempts, gate rejections, and merge retry."""

import json
import logging
import subprocess
from typing import Any

from .beads_query import _parse_beads_json, _run_bd

logger = logging.getLogger(__name__)


def _get_metadata(item_id: str) -> dict[str, Any] | None:
    """Fetch the metadata dict for an item. Returns None on failure."""
    try:
        result = _run_bd(['show', item_id, '--json'], check=False)
        data = _parse_beads_json(result.stdout)
        if data is None:
            return None
        item = data[0] if isinstance(data, list) else data
        metadata = item.get('metadata', {})
        return metadata if isinstance(metadata, dict) else {}
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired,
            json.JSONDecodeError, ValueError, TypeError):
        return None


def _set_metadata(item_id: str, metadata: dict[str, Any]) -> bool:
    """Write the metadata dict for an item. Returns True on success."""
    try:
        _run_bd(['update', item_id, '--metadata', json.dumps(metadata)])
        return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return False


def get_total_attempts(item_id: str) -> int:
    """Get the total attempts counter for a work item.

    Returns:
        The total number of attempts, or 0 if not tracked.
    """
    try:
        result = _run_bd(['show', item_id, '--json'], check=False)
        data = _parse_beads_json(result.stdout)
        if data is None:
            return 0

        item = data[0] if isinstance(data, list) else data
        metadata = item.get('metadata')
        if metadata and isinstance(metadata, dict):
            return int(metadata.get('total_attempts', 0))
        return 0
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, json.JSONDecodeError, ValueError, TypeError):
        logger.warning(f"Failed to get total_attempts for {item_id}, defaulting to 0")
        return 0


def increment_total_attempts(item_id: str) -> bool:
    """Increment the total attempts counter for a work item.

    Fetches item metadata once to avoid race conditions in concurrent updates.

    Returns:
        True if successful, False otherwise.
    """
    try:
        # Fetch item once and derive both current value and full metadata from single snapshot
        result = _run_bd(['show', item_id, '--json'], check=False)
        data = _parse_beads_json(result.stdout)
        if data is None:
            logger.warning(f"Failed to fetch item {item_id} for metadata update")
            return False

        item = data[0] if isinstance(data, list) else data
        metadata = item.get('metadata', {}) if isinstance(item.get('metadata'), dict) else {}

        # Increment from the snapshot value
        current_attempts = int(metadata.get('total_attempts', 0))
        new_attempts = current_attempts + 1
        metadata['total_attempts'] = new_attempts

        # Single atomic update with all metadata preserved
        _run_bd(['update', item_id, '--metadata', json.dumps(metadata)])
        logger.info(f"Incremented total_attempts for {item_id} to {new_attempts}")
        return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, json.JSONDecodeError, ValueError, TypeError):
        logger.warning(f"Failed to increment total_attempts for {item_id}")
        return False


def get_gate_rejection_count(item_id: str) -> int:
    """Get the gate rejection counter for a work item."""
    try:
        result = _run_bd(['show', item_id, '--json'], check=False)
        data = _parse_beads_json(result.stdout)
        if data is None:
            return 0

        item = data[0] if isinstance(data, list) else data
        metadata = item.get('metadata')
        if metadata and isinstance(metadata, dict):
            return int(metadata.get('gate_rejection_count', 0))
        return 0
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, json.JSONDecodeError, ValueError, TypeError):
        logger.warning(f"Failed to get gate_rejection_count for {item_id}, defaulting to 0")
        return 0


def increment_gate_rejection_count(item_id: str) -> int:
    """Increment the gate rejection counter for a work item.

    Fetches item metadata once to avoid race conditions in concurrent updates.

    Returns:
        New count on success, or -1 on failure.
    """
    try:
        # Fetch item once and derive both current value and full metadata from single snapshot
        result = _run_bd(['show', item_id, '--json'], check=False)
        data = _parse_beads_json(result.stdout)
        if data is None:
            logger.warning(f"Failed to fetch item {item_id} for metadata update")
            return -1

        item = data[0] if isinstance(data, list) else data
        metadata = item.get('metadata', {})
        if not isinstance(metadata, dict):
            metadata = {}

        # Increment from the snapshot value
        current_count = int(metadata.get('gate_rejection_count', 0))
        new_count = current_count + 1
        metadata['gate_rejection_count'] = new_count

        # Single atomic update with all metadata preserved
        metadata_json = json.dumps(metadata)
        _run_bd(['update', item_id, '--metadata', metadata_json])
        logger.info(f"Incremented gate_rejection_count for {item_id} to {new_count}")
        return new_count
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, json.JSONDecodeError, ValueError, TypeError) as e:
        logger.warning(f"Failed to increment gate_rejection_count for {item_id}: {e}")
        return -1


def set_merge_retry(item_id: str) -> bool:
    """Mark the item for merge-only retry (gate already passed)."""
    metadata = _get_metadata(item_id)
    if metadata is None:
        logger.warning("Failed to fetch metadata for %s when setting merge_retry", item_id)
        return False
    metadata['merge_retry'] = True
    if _set_metadata(item_id, metadata):
        logger.info("Set merge_retry flag for %s", item_id)
        return True
    logger.warning("Failed to set merge_retry for %s", item_id)
    return False


def clear_merge_retry(item_id: str) -> bool:
    """Clear the merge-retry flag (after successful merge or before re-running work)."""
    metadata = _get_metadata(item_id)
    if metadata is None:
        return False
    metadata.pop('merge_retry', None)
    return _set_metadata(item_id, metadata)
