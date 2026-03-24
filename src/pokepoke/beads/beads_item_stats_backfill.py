"""Backfill beads item creation events from the beads database.

This module provides automatic backfilling of beads item creation events
that may be missing from the stats log. This ensures the Desktop UI's
"Lifetime beads throughput" ADDED count accurately reflects reality.

Strategy:
1. Backfill from current beads database (items that exist now)
2. Backfill from completed items (assume every completed item was also created)
"""

from __future__ import annotations

import json
import logging
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _get_all_beads_items() -> list[dict[str, Any]]:
    """Fetch all items from beads database using bd list --json."""
    try:
        result = subprocess.run(
            ["bd", "list", "--json"],
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            check=True,
            timeout=30,
        )
        if not result.stdout:
            return []
        items = json.loads(result.stdout)
        return items if isinstance(items, list) else []
    except (subprocess.CalledProcessError, json.JSONDecodeError, FileNotFoundError, subprocess.TimeoutExpired, TypeError) as e:
        logger.warning(f"Failed to fetch beads items for backfill: {e}")
        return []


def _determine_agent_type(created_by: str) -> str:
    """Determine agent type from created_by field."""
    if not created_by:
        return "unknown"
    created_lower = created_by.lower()
    from pokepoke.utils.constants import HUMAN_IDENTIFIERS
    if any(kw in created_lower for kw in HUMAN_IDENTIFIERS):
        return "human"
    return "unknown"


def backfill_from_beads_db(stats_path: Path | None = None, silent: bool = False) -> dict[str, Any]:
    """Backfill created events for all beads items from the beads database.

    This function is idempotent - it's safe to call multiple times.
    Items that already have created events will be skipped.

    Args:
        stats_path: Path to beads_item_stats.json (defaults to .pokepoke/beads_item_stats.json)
        silent: If True, suppress info logging (only log warnings/errors)

    Returns:
        Dict with backfill results:
        {
            "backfilled": int,  # Number of items backfilled
            "total_created": int,
            "total_completed": int,
            "net_delta": int,
            "already_complete": bool  # True if no backfill needed
        }
    """
    from pokepoke.beads.beads_item_stats_store import (
        _rebuild_summary,
        _resolve_stats_path,
        load_beads_item_stats,
        save_beads_item_stats,
    )

    if stats_path is None:
        stats_path = _resolve_stats_path()

    if not silent:
        logger.info("Starting beads item stats backfill...")

    # Load all beads items from database
    all_items = _get_all_beads_items()
    if not silent and all_items:
        logger.info(f"Found {len(all_items)} items in beads database")

    # Load existing stats
    stats = load_beads_item_stats(stats_path)
    log = stats.get("log", [])

    # Build set of item IDs that already have created events
    created_items = {entry["item_id"] for entry in log if entry.get("event") == "created"}

    # Build set of item IDs that have completed events
    completed_items = {entry["item_id"] for entry in log if entry.get("event") == "completed"}

    # Strategy 1: Backfill items that exist in beads database
    items_from_db = [item for item in all_items if item.get("id") and item["id"] not in created_items]

    # Strategy 2: Backfill items that were completed but have no creation event
    # These are items that no longer exist in the database (archived/deleted)
    items_from_completed = [item_id for item_id in completed_items if item_id not in created_items]

    total_to_backfill = len(items_from_db) + len(items_from_completed)

    if total_to_backfill == 0:
        if not silent:
            logger.info("All items already have 'created' events - nothing to backfill")
        summary = stats.get("summary", {})
        return {
            "backfilled": 0,
            "total_created": int(summary.get("total_created", 0)),
            "total_completed": int(summary.get("total_completed", 0)),
            "net_delta": int(summary.get("net_delta", 0)),
            "already_complete": True,
        }

    if not silent:
        logger.info(
            f"Backfilling {total_to_backfill} items "
            f"({len(items_from_db)} from DB, {len(items_from_completed)} from completed history)"
        )

    # Add created events for items from current beads database
    backfilled_count = 0
    for item in items_from_db:
        item_id = item["id"]
        created_at = item.get("created_at")
        created_by = item.get("created_by", "")
        agent_type = _determine_agent_type(created_by)

        created_event = {
            "event": "created",
            "item_id": item_id,
            "agent_type": agent_type,
            "timestamp": created_at or datetime.now(UTC).isoformat(),
        }

        log.append(created_event)
        created_items.add(item_id)  # Track that this item now has a created event
        backfilled_count += 1

    if not silent and items_from_db:
        logger.info(f"Backfilled {len(items_from_db)} items from beads database")

    # Add created events for completed items (use earliest completed timestamp)
    # Skip items that were already backfilled from DB
    items_backfilled_from_completed = 0
    for item_id in items_from_completed:
        if item_id in created_items:  # Already backfilled from DB
            continue

        # Find earliest completed event for this item
        completed_events = [entry for entry in log if entry.get("item_id") == item_id and entry.get("event") == "completed"]

        if not completed_events:
            continue

        # Sort by timestamp to find earliest
        completed_events.sort(key=lambda e: e.get("timestamp", ""))
        earliest_completed = completed_events[0]

        # Get agent type from completed event
        agent_type = earliest_completed.get("agent_type", "unknown")

        # Use timestamp slightly before completion (creation must precede completion)
        completed_timestamp = earliest_completed.get("timestamp", datetime.now(UTC).isoformat())

        created_event = {
            "event": "created",
            "item_id": item_id,
            "agent_type": agent_type,
            "timestamp": completed_timestamp,  # Use same timestamp as completion
        }

        log.append(created_event)
        created_items.add(item_id)  # Track that this item now has a created event
        backfilled_count += 1
        items_backfilled_from_completed += 1

    if not silent and items_backfilled_from_completed > 0:
        logger.info(f"Backfilled {items_backfilled_from_completed} items from completed history")

    # Rebuild summary
    stats["log"] = log
    stats["summary"] = _rebuild_summary(log)

    # Save updated stats
    save_beads_item_stats(stats, stats_path)

    summary = stats["summary"]
    if not silent:
        logger.info(
            f"Backfill complete: Created={summary['total_created']}, "
            f"Completed={summary['total_completed']}, Net={summary['net_delta']:+d}"
        )

    return {
        "backfilled": backfilled_count,
        "total_created": int(summary["total_created"]),
        "total_completed": int(summary["total_completed"]),
        "net_delta": int(summary["net_delta"]),
        "already_complete": False,
    }
