"""Beads item creation tracking for SDK tool events."""

import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


_BEADS_CREATE_RE = re.compile(r"\b(bd|br)\s+create\b", re.IGNORECASE)
_ITEM_ID_RE = re.compile(r"\bPokePoke-[0-9A-Za-z_-]+\b")


def extract_command(arguments: Any) -> str:
    if isinstance(arguments, dict):
        cmd = arguments.get("command")
        return cmd if isinstance(cmd, str) else str(arguments)
    return str(arguments)


def parse_created_items(result_content: str) -> list[tuple[str, str]]:
    """Return list of (item_id, title) parsed from tool output."""
    if not result_content:
        return []

    try:
        parsed = json.loads(result_content)
        if isinstance(parsed, dict):
            item_id = parsed.get("id")
            title = parsed.get("title")
            if isinstance(item_id, str) and item_id:
                return [(item_id, title if isinstance(title, str) else "")]
        if isinstance(parsed, list):
            out: list[tuple[str, str]] = []
            for entry in parsed:
                if not isinstance(entry, dict):
                    continue
                item_id = entry.get("id")
                title = entry.get("title")
                if isinstance(item_id, str) and item_id:
                    out.append((item_id, title if isinstance(title, str) else ""))
            if out:
                return out
    except Exception as e:
        logger.debug(f"Failed to parse created items from JSON, falling back to regex: {e}")

    ids = _ITEM_ID_RE.findall(result_content)
    return [(i, "") for i in ids]


def record_items_created(items: list[tuple[str, str]]) -> None:
    if not items:
        return

    from pokepoke.beads.beads_item_stats_store import record_item_created
    from pokepoke.stats.metrics_context import get_current_agent_type
    from pokepoke.stats.session_stats_registry import get_current_session_stats
    from pokepoke.types_beads import BeadsCreatedItem

    agent_type = get_current_agent_type()
    stats = get_current_session_stats()

    latest_summary: dict[str, Any] | None = None
    for item_id, title in items:
        if stats is not None:
            stats.record_created_item(BeadsCreatedItem(id=item_id, title=title, agent_type=agent_type))
        latest_summary = record_item_created(item_id=item_id, agent_type=agent_type)

    if stats is not None and latest_summary:
        stats.set_lifetime_beads_item_totals(
            created=int(latest_summary.get("total_created", 0)),
            completed=int(latest_summary.get("total_completed", 0)),
        )


def is_beads_create(cmd: str) -> bool:
    """Check if a command string contains a beads create call."""
    return bool(_BEADS_CREATE_RE.search(cmd))
