#!/usr/bin/env python3
"""Example: Using CopilotInvoker with worktrees for beads work items."""

from pokepoke import CopilotInvoker, BeadsWorkItem, create_validation_hook


def example_with_worktrees():
    """Example showing full worktree integration."""
    
    # Create a sample work item (normally from beads)
    work_item = BeadsWorkItem(
        id="incredible_icm-42",
        title="Add authentication to API endpoints",
        description="""Implement JWT-based authentication for all API endpoints.
        
Requirements:
- Add authentication middleware
- Implement token generation and validation
- Add tests for auth flows
- Update API documentation
""",
        status="ready",
        priority=1,
        issue_type="feature",
        labels=["backend", "security"]
    )
    
    print("=" * 80)
    print("🤖 PokePoke - Autonomous Work Item Processing with Worktrees")
    print("=" * 80)
    print()
    
    # Create invoker with worktrees and validation
    invoker = CopilotInvoker(
        model="claude-sonnet-4.5",
        timeout_seconds=300,
        max_retries=3,
        validation_hook=create_validation_hook(),  # Enable quality gates
        use_worktrees=True,  # Enable worktree isolation
        source_branch="master"  # Branch to create worktrees from
    )
    
    print(f"📋 Processing work item: {work_item.id}")
    print(f"   Title: {work_item.title}")
    print(f"   Priority: {work_item.priority}")
    print(f"   Type: {work_item.issue_type}")
    if work_item.labels:
        print(f"   Labels: {', '.join(work_item.labels)}")
    print()
    
    # Process the work item
    # Note: This will:
    # 1. Create a worktree at ./worktrees/task-incredible_icm-42
    # 2. Create branch task/incredible_icm-42
    # 3. Invoke Copilot CLI in the worktree
    # 4. Run validation checks
    # 5. Retry up to 3 times if validation fails
    # 6. Clean up worktree when done
    
    result = invoker.invoke(work_item)
    
    print()
    print("=" * 80)
    print("📊 RESULT")
    print("=" * 80)
    
    if result.success:
        print(f"✅ Work item {result.work_item_id} completed successfully!")
        if result.output:
            print(f"\n📄 Output:\n{result.output[:500]}...")
    else:
        print(f"❌ Work item {result.work_item_id} failed")
        print(f"   Error: {result.error}")
        if result.validation_errors:
            print(f"\n   Validation errors:")
            for error in result.validation_errors:
                print(f"   - {error}")
    
    print()
    print("=" * 80)


def example_without_worktrees():
    """Example showing execution without worktrees (legacy mode)."""
    
    work_item = BeadsWorkItem(
        id="incredible_icm-43",
        title="Fix typo in README",
        description="Correct spelling error in installation instructions",
        status="ready",
        priority=3,
        issue_type="bug"
    )
    
    print("=" * 80)
    print("🤖 PokePoke - Legacy Mode (No Worktrees)")
    print("=" * 80)
    print()
    
    # Disable worktrees for simple tasks
    invoker = CopilotInvoker(
        model="claude-sonnet-4.5",
        timeout_seconds=60,
        max_retries=1,
        use_worktrees=False  # Work directly in current directory
    )
    
    print(f"📋 Processing work item: {work_item.id}")
    print(f"   Title: {work_item.title}")
    print()
    
    result = invoker.invoke(work_item)
    
    print()
    if result.success:
        print(f"✅ Completed: {result.work_item_id}")
    else:
        print(f"❌ Failed: {result.work_item_id}")
        print(f"   Error: {result.error}")
    
    print()
    print("=" * 80)


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "--no-worktree":
        example_without_worktrees()
    else:
        print("\n⚠️  This is a demonstration script.")
        print("    It will attempt to invoke Copilot CLI with worktrees.")
        print("    Use --no-worktree flag to disable worktrees.\n")
        
        # Uncomment to actually run:
        # example_with_worktrees()
        
        print("✅ Run 'python example_worktree_integration.py' to see the demo")
        print("   (Uncomment the function call in __main__ to actually execute)\n")
