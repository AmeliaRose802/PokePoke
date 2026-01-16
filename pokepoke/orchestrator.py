#!/usr/bin/env python3
"""PokePoke - Autonomous Beads + Copilot CLI Orchestrator."""

import sys

from .beads import get_first_ready_work_item
from .copilot import invoke_copilot_cli, build_prompt


# Check for --no-interactive flag
INTERACTIVE_MODE = '--no-interactive' not in sys.argv


def prompt_for_approval(question: str) -> bool:
    """Prompt user for approval.
    
    Args:
        question: The question to ask.
        
    Returns:
        True if approved, False otherwise.
    """
    if not INTERACTIVE_MODE:
        return True
    answer = input(question).strip().lower()
    return answer in ('y', 'yes')


def display_work_item(work_item) -> None:
    """Display work item details for review.
    
    Args:
        work_item: The work item to display.
    """
    print("\n" + "=" * 80)
    print("📋 WORK ITEM SELECTED")
    print("=" * 80)
    print(f"ID:          {work_item.id}")
    print(f"Title:       {work_item.title}")
    print(f"Type:        {work_item.issue_type}")
    print(f"Priority:    {work_item.priority}")
    print(f"Status:      {work_item.status}")
    if work_item.labels:
        print(f"Labels:      {', '.join(work_item.labels)}")
    print(f"\nDescription:\n{work_item.description or '(no description)'}")
    print("=" * 80 + "\n")


def display_prompt(prompt: str) -> None:
    """Display the prompt that will be sent to Copilot.
    
    Args:
        prompt: The prompt to display.
    """
    print("\n" + "=" * 80)
    print("💬 PROMPT TO BE SENT TO COPILOT CLI")
    print("=" * 80)
    print(prompt)
    print("=" * 80 + "\n")


def main() -> int:
    """Main orchestrator entry point.
    
    Returns:
        Exit code (0 for success, 1 for failure).
    """
    mode = "non-interactive" if not INTERACTIVE_MODE else "interactive"
    print(f"🤖 PokePoke orchestrator starting ({mode} mode)...\n")
    
    try:
        # Step 1: Query beads for ready work
        print("1️⃣ Querying beads for ready work items...")
        work_item = get_first_ready_work_item()
        
        if not work_item:
            print("   ℹ️ No ready work items found. Exiting.\n")
            return 0
        
        print(f"   ✓ Found work item: {work_item.id} - {work_item.title}\n")
        
        # Step 1.5: Display work item and get approval
        display_work_item(work_item)
        if not prompt_for_approval("❓ Proceed with this work item? (y/n): "):
            print("   ❌ Work item rejected. Exiting.\n")
            return 0
        
        # Step 1.75: Show prompt and get approval
        prompt = build_prompt(work_item)
        display_prompt(prompt)
        if not prompt_for_approval("❓ Send this prompt to Copilot CLI? (y/n): "):
            print("   ❌ Prompt rejected. Exiting.\n")
            return 0
        
        # Step 2: Invoke Copilot CLI with work item
        print("\n2️⃣ Invoking GitHub Copilot CLI...")
        result = invoke_copilot_cli(work_item, prompt)
        
        # Step 3: Report completion status
        print("\n3️⃣ Reporting completion status...")
        if result.success:
            print(f"   ✓ Work item {result.work_item_id} completed successfully!")
            if result.output:
                print(f"\n📄 Output:\n{result.output}")
        else:
            print(f"   ✗ Work item {result.work_item_id} failed:")
            print(f"     {result.error}")
            return 1
        
        print("\n✨ PokePoke orchestrator finished successfully!\n")
        return 0
        
    except KeyboardInterrupt:
        print("\n\n⚠️  Interrupted by user. Exiting.\n")
        return 130
    except Exception as e:
        print(f"\n❌ Orchestrator error: {e}\n", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
