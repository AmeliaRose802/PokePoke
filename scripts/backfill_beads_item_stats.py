#!/usr/bin/env python3
"""Backfill beads item creation events from the beads database.

This script queries the beads database for all items and ensures each one has
a corresponding 'created' event in the beads_item_stats.json log.

Usage:
    python scripts/backfill_beads_item_stats.py [--dry-run]
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path
from datetime import datetime, UTC


def get_all_beads_items() -> list[dict]:
    """Fetch all items from beads database using bd list --json."""
    try:
        result = subprocess.run(
            ['bd', 'list', '--json'],
            capture_output=True,
            text=True,
            check=True
        )
        items = json.loads(result.stdout)
        return items if isinstance(items, list) else []
    except (subprocess.CalledProcessError, json.JSONDecodeError, FileNotFoundError) as e:
        print(f"❌ Failed to fetch beads items: {e}", file=sys.stderr)
        return []


def load_stats(stats_path: Path) -> dict:
    """Load existing stats or return empty structure."""
    if not stats_path.exists():
        return {
            "log": [],
            "summary": {
                "total_created": 0,
                "total_completed": 0,
                "net_delta": 0,
                "by_agent_type": {},
                "last_updated": ""
            }
        }

    try:
        with stats_path.open(encoding='utf-8') as f:
            data = json.load(f)
        if not isinstance(data, dict) or 'log' not in data:
            return {"log": [], "summary": {}}
        return data
    except (json.JSONDecodeError, OSError) as e:
        print(f"⚠️  Warning: Failed to load existing stats: {e}", file=sys.stderr)
        return {"log": [], "summary": {}}


def rebuild_summary(log: list[dict]) -> dict:
    """Rebuild summary from log entries.

    Counts unique items (deduplicates by item_id + event type).
    """
    created_items = set()
    completed_items = set()
    by_agent = {}

    for entry in log:
        event = entry.get('event')
        item_id = entry.get('item_id')
        agent = entry.get('agent_type') or 'unknown'

        if not item_id:
            continue

        if agent not in by_agent:
            by_agent[agent] = {'created': 0, 'completed': 0}

        if event == 'created' and item_id not in created_items:
            created_items.add(item_id)
            by_agent[agent]['created'] += 1
        elif event == 'completed' and item_id not in completed_items:
            completed_items.add(item_id)
            by_agent[agent]['completed'] += 1

    total_created = len(created_items)
    total_completed = len(completed_items)

    by_agent_out = {}
    for agent, counts in by_agent.items():
        created = counts['created']
        completed = counts['completed']
        by_agent_out[agent] = {
            'created': created,
            'completed': completed,
            'net_delta': created - completed
        }

    return {
        'total_created': total_created,
        'total_completed': total_completed,
        'net_delta': total_created - total_completed,
        'by_agent_type': by_agent_out,
        'last_updated': datetime.now(UTC).isoformat()
    }


def backfill_created_events(dry_run: bool = False) -> int:
    """Backfill created events for all beads items.

    Strategy:
    1. Backfill from current beads database (items that exist now)
    2. Backfill from completed items (assume every completed item was also created)

    Returns:
        Number of items backfilled.
    """
    stats_path = Path('.pokepoke') / 'beads_item_stats.json'

    print("📊 Loading beads items from database...")
    all_items = get_all_beads_items()
    print(f"✅ Found {len(all_items)} items in beads database")

    print("📂 Loading existing stats...")
    stats = load_stats(stats_path)
    log = stats.get('log', [])

    # Build set of item IDs that already have created events
    created_items = {
        entry['item_id']
        for entry in log
        if entry.get('event') == 'created'
    }

    # Build set of item IDs that have completed events
    completed_items = {
        entry['item_id']
        for entry in log
        if entry.get('event') == 'completed'
    }

    print(f"✅ Found {len(created_items)} items with 'created' events")
    print(f"✅ Found {len(completed_items)} items with 'completed' events")

    # Strategy 1: Backfill items that exist in beads database
    items_from_db = [
        item for item in all_items
        if item.get('id') and item['id'] not in created_items
    ]

    # Strategy 2: Backfill items that were completed but have no creation event
    # These are items that no longer exist in the database (archived/deleted)
    items_from_completed = [
        item_id for item_id in completed_items
        if item_id not in created_items
    ]

    total_to_backfill = len(items_from_db) + len(items_from_completed)

    if total_to_backfill == 0:
        print("✅ All items already have 'created' events - nothing to backfill")
        return 0

    print(f"\n🔄 Need to backfill {total_to_backfill} items:")
    print(f"   • {len(items_from_db)} from current beads database")
    print(f"   • {len(items_from_completed)} from completed history (no longer in DB)")

    if dry_run:
        print("\n🔍 DRY RUN - would add these created events:")
        print("\nFrom current beads database:")
        for item in items_from_db[:5]:
            print(f"  • {item['id']}: {item.get('title', 'untitled')}")
        if len(items_from_db) > 5:
            print(f"  ... and {len(items_from_db) - 5} more")

        print("\nFrom completed history (archived items):")
        for item_id in list(items_from_completed)[:5]:
            print(f"  • {item_id}")
        if len(items_from_completed) > 5:
            print(f"  ... and {len(items_from_completed) - 5} more")

        return total_to_backfill

    # Add created events for items from current beads database
    backfilled_count = 0
    for item in items_from_db:
        item_id = item['id']
        created_at = item.get('created_at')

        # Determine agent type based on created_by
        created_by = item.get('created_by', '')
        agent_type = 'human' if 'Amelia' in created_by or 'payne' in created_by else 'unknown'

        created_event = {
            'event': 'created',
            'item_id': item_id,
            'agent_type': agent_type,
            'timestamp': created_at or datetime.now(UTC).isoformat()
        }

        log.append(created_event)
        backfilled_count += 1

    print(f"✅ Backfilled {len(items_from_db)} items from beads database")

    # Add created events for completed items (use earliest completed timestamp)
    for item_id in items_from_completed:
        # Find earliest completed event for this item
        completed_events = [
            entry for entry in log
            if entry.get('item_id') == item_id and entry.get('event') == 'completed'
        ]

        if not completed_events:
            continue

        # Sort by timestamp to find earliest
        completed_events.sort(key=lambda e: e.get('timestamp', ''))
        earliest_completed = completed_events[0]

        # Get agent type from completed event
        agent_type = earliest_completed.get('agent_type', 'unknown')

        # Use timestamp slightly before completion (creation must precede completion)
        completed_timestamp = earliest_completed.get('timestamp', datetime.now(UTC).isoformat())

        created_event = {
            'event': 'created',
            'item_id': item_id,
            'agent_type': agent_type,
            'timestamp': completed_timestamp  # Use same timestamp as completion
        }

        log.append(created_event)
        backfilled_count += 1

    print(f"✅ Backfilled {len(items_from_completed)} items from completed history")

    # Rebuild summary
    print("🔄 Rebuilding summary...")
    stats['log'] = log
    stats['summary'] = rebuild_summary(log)

    # Save updated stats
    print("💾 Saving updated stats...")
    stats_path.parent.mkdir(parents=True, exist_ok=True)
    with stats_path.open('w', encoding='utf-8') as f:
        json.dump(stats, f, indent=2)

    print("\n✅ Backfill complete!")
    print(f"   Created: {stats['summary']['total_created']}")
    print(f"   Completed: {stats['summary']['total_completed']}")
    print(f"   Net delta: {stats['summary']['net_delta']:+d}")

    return backfilled_count


def main():
    parser = argparse.ArgumentParser(
        description='Backfill beads item creation events from beads database'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be done without making changes'
    )
    args = parser.parse_args()

    try:
        backfilled = backfill_created_events(dry_run=args.dry_run)
        if backfilled == 0 and not args.dry_run:
            sys.exit(0)  # Success, nothing to do
        elif args.dry_run:
            print(f"\n🔍 Dry run complete - would backfill {backfilled} items")
            sys.exit(0)
        else:
            sys.exit(0)  # Success
    except Exception as e:
        print(f"❌ Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
