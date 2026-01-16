#!/usr/bin/env python3
"""Test script for worktree functionality with CopilotInvoker."""

from pokepoke import CopilotInvoker, BeadsWorkItem


def test_worktree_lifecycle():
    """Test creating and cleaning up a worktree."""
    
    # Create a mock work item
    work_item = BeadsWorkItem(
        id="test-123",
        title="Test worktree creation",
        description="This is a test of the worktree creation and cleanup",
        status="ready",
        priority=1,
        issue_type="task"
    )
    
    # Create invoker with worktrees enabled
    invoker = CopilotInvoker(
        model="claude-sonnet-4.5",
        timeout_seconds=30,
        max_retries=1,
        use_worktrees=True,
        source_branch="master"
    )
    
    print("🧪 Testing worktree lifecycle...\n")
    
    # List existing worktrees
    print("📋 Current worktrees:")
    if invoker.worktree_manager:
        worktrees = invoker.worktree_manager.list_worktrees()
        for wt in worktrees:
            print(f"   - {wt.get('path', 'unknown')}: {wt.get('branch', 'no branch')}")
    
    # Create worktree
    print(f"\n🌳 Creating worktree for {work_item.id}...")
    if invoker.worktree_manager:
        success, message, path = invoker.worktree_manager.create_worktree(
            work_item.id,
            source_branch="master"
        )
        
        if success:
            print(f"✓ {message}")
            print(f"   Path: {path}")
            
            # List worktrees again
            print("\n📋 Worktrees after creation:")
            worktrees = invoker.worktree_manager.list_worktrees()
            for wt in worktrees:
                print(f"   - {wt.get('path', 'unknown')}: {wt.get('branch', 'no branch')}")
            
            # Clean up immediately
            print(f"\n🧹 Cleaning up worktree for {work_item.id}...")
            success, message = invoker.worktree_manager.cleanup_worktree(
                work_item.id,
                force=True
            )
            
            if success:
                print(f"✓ {message}")
            else:
                print(f"❌ {message}")
        else:
            print(f"❌ {message}")
    
    print("\n✨ Test complete!")


if __name__ == "__main__":
    test_worktree_lifecycle()
