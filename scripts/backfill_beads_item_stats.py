#!/usr/bin/env python3
"""Backfill beads item creation events from the beads database.

This script is a CLI wrapper around the backfill_from_beads_db() function
from pokepoke.beads_item_stats_backfill module.

Usage:
    python scripts/backfill_beads_item_stats.py [--dry-run]
"""

import argparse
import sys
from pathlib import Path


def backfill_created_events(dry_run: bool = False) -> int:
    """Backfill created events for all beads items.

    Strategy:
    1. Backfill from current beads database (items that exist now)
    2. Backfill from completed items (assume every completed item was also created)

    Returns:
        Number of items backfilled.
    """
    if dry_run:
        print("🔍 DRY RUN MODE - No changes will be made")
        print("\n📊 Loading beads items from database...")
        from pokepoke.beads_item_stats_backfill import _get_all_beads_items
        from pokepoke.beads_item_stats_store import load_beads_item_stats

        all_items = _get_all_beads_items()
        print(f"✅ Found {len(all_items)} items in beads database")

        stats_path = Path('.pokepoke') / 'beads_item_stats.json'
        stats = load_beads_item_stats(stats_path)
        log = stats.get('log', [])

        created_items = {
            entry['item_id']
            for entry in log
            if entry.get('event') == 'created'
        }
        completed_items = {
            entry['item_id']
            for entry in log
            if entry.get('event') == 'completed'
        }

        print(f"✅ Found {len(created_items)} items with 'created' events")
        print(f"✅ Found {len(completed_items)} items with 'completed' events")

        items_from_db = [
            item for item in all_items
            if item.get('id') and item['id'] not in created_items
        ]
        items_from_completed = [
            item_id for item_id in completed_items
            if item_id not in created_items
        ]

        total_to_backfill = len(items_from_db) + len(items_from_completed)

        if total_to_backfill == 0:
            print("✅ All items already have 'created' events - nothing to backfill")
            return 0

        print(f"\n🔄 Would backfill {total_to_backfill} items:")
        print(f"   • {len(items_from_db)} from current beads database")
        print(f"   • {len(items_from_completed)} from completed history (no longer in DB)")

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

    # Real backfill
    print("📊 Starting beads item stats backfill...")
    from pokepoke.beads_item_stats_backfill import backfill_from_beads_db

    result = backfill_from_beads_db(silent=False)

    if result['already_complete']:
        print("✅ All items already have 'created' events - nothing to backfill")
        return 0

    print("\n✅ Backfill complete!")
    print(f"   • Backfilled: {result['backfilled']} items")
    print(f"   • Created: {result['total_created']}")
    print(f"   • Completed: {result['total_completed']}")
    print(f"   • Net delta: {result['net_delta']:+d}")

    return result['backfilled']


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
