#!/usr/bin/env python3
"""Test the enhanced Copilot invoker with a real work item from beads."""

import json
import subprocess
import sys
from pathlib import Path

# Add pokepoke to path
sys.path.insert(0, str(Path(__file__).parent))

from pokepoke.copilot_enhanced import CopilotInvoker, create_validation_hook
from pokepoke.types import BeadsWorkItem


def fetch_ready_work_items():
    """Fetch ready work items from beads."""
    result = subprocess.run(
        ['bd', 'ready', '--json'],
        capture_output=True,
        text=True
    )
    
    if result.returncode != 0:
        print(f"Failed to fetch work items: {result.stderr}")
        return []
    
    try:
        items = json.loads(result.stdout)
        return items
    except json.JSONDecodeError as e:
        print(f"Failed to parse JSON: {e}")
        return []


def convert_to_work_item(beads_item: dict) -> BeadsWorkItem:
    """Convert beads JSON to BeadsWorkItem object."""
    return BeadsWorkItem(
        id=beads_item['id'],
        title=beads_item['title'],
        description=beads_item['description'],
        status=beads_item['status'],
        priority=beads_item['priority'],
        issue_type=beads_item['issue_type'],
        owner=beads_item.get('owner'),
        created_at=beads_item.get('created_at'),
        created_by=beads_item.get('created_by'),
        updated_at=beads_item.get('updated_at'),
        labels=beads_item.get('labels', [])
    )


def test_with_specific_item(item_id: str):
    """Test with a specific work item ID."""
    print(f"\n{'='*80}")
    print(f"Testing with work item: {item_id}")
    print(f"{'='*80}\n")
    
    # Fetch all ready items
    items = fetch_ready_work_items()
    
    if not items:
        print("❌ No ready work items found")
        return
    
    # Find the specific item
    target_item = None
    for item in items:
        if item['id'] == item_id:
            target_item = item
            break
    
    if not target_item:
        print(f"❌ Work item {item_id} not found in ready items")
        print(f"Available items:")
        for item in items:
            print(f"  - {item['id']}: {item['title']}")
        return
    
    # Convert to BeadsWorkItem
    work_item = convert_to_work_item(target_item)
    
    print(f"📋 Work Item Details:")
    print(f"   ID: {work_item.id}")
    print(f"   Title: {work_item.title}")
    print(f"   Type: {work_item.issue_type}")
    print(f"   Priority: {work_item.priority}")
    print(f"   Labels: {', '.join(work_item.labels) if work_item.labels else 'None'}")
    print(f"\n   Description:")
    print(f"   {work_item.description}\n")
    
    # Ask for confirmation
    response = input("Proceed with Copilot invocation? [y/N]: ")
    if response.lower() != 'y':
        print("❌ Cancelled by user")
        return
    
    # Create invoker with validation
    print("\n🔧 Creating Copilot invoker with validation...")
    invoker = CopilotInvoker(
        model="claude-sonnet-4.5",
        timeout_seconds=300,
        max_retries=3,
        validation_hook=create_validation_hook()
    )
    
    # Invoke
    print("\n🚀 Invoking Copilot CLI...\n")
    result = invoker.invoke(work_item)
    
    # Report results
    print(f"\n{'='*80}")
    if result.success:
        print(f"✅ SUCCESS after {result.attempt_count} attempt(s)")
        print(f"{'='*80}\n")
        print("Output:")
        print(result.output)
    else:
        print(f"❌ FAILED after {result.attempt_count} attempt(s)")
        print(f"{'='*80}\n")
        print(f"Error: {result.error}")
        if result.validation_errors:
            print("\nValidation errors:")
            for error in result.validation_errors:
                print(f"  - {error}")


def test_with_smallest_task():
    """Find and test with the smallest/simplest task."""
    print(f"\n{'='*80}")
    print("Finding smallest task to test with...")
    print(f"{'='*80}\n")
    
    items = fetch_ready_work_items()
    
    if not items:
        print("❌ No ready work items found")
        return
    
    # Find tasks (not epics or features), sorted by priority
    tasks = [
        item for item in items
        if item['issue_type'] == 'task' and 'epic' not in item['title'].lower()
    ]
    
    if not tasks:
        print("❌ No task-type work items found")
        print(f"Available items:")
        for item in items:
            print(f"  - {item['id']}: [{item['issue_type']}] {item['title']}")
        return
    
    # Sort by priority (lower number = higher priority, but we want simplest)
    # and by description length (shorter = simpler)
    tasks.sort(key=lambda x: (x['priority'], len(x['description'])))
    
    print("Available tasks (sorted by simplicity):")
    for i, task in enumerate(tasks[:5], 1):
        labels = ', '.join(task.get('labels', []))
        print(f"  {i}. {task['id']}: {task['title']}")
        print(f"     Labels: {labels}")
        print(f"     Description: {task['description'][:100]}...")
        print()
    
    # Use the first one
    selected = tasks[0]
    print(f"Selected: {selected['id']} - {selected['title']}\n")
    
    test_with_specific_item(selected['id'])


def main():
    """Main entry point."""
    if len(sys.argv) > 1:
        # Test with specific item ID
        item_id = sys.argv[1]
        test_with_specific_item(item_id)
    else:
        # Find and test with smallest task
        test_with_smallest_task()


if __name__ == "__main__":
    main()
