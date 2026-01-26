"""Worktree finalization and merging operations."""

import json
import os
import subprocess
from pathlib import Path

from .types import BeadsWorkItem
from .worktrees import merge_worktree, cleanup_worktree
from .git_operations import check_main_repo_ready_for_merge
from .beads_hierarchy import get_parent_id, close_parent_if_complete
from .beads_management import close_item, create_cleanup_delegation_issue


def finalize_work_item(item: BeadsWorkItem, worktree_path: Path) -> bool:
    """Finalize work item by merging worktree and closing issue.
    
    Returns:
        True if successful, False otherwise
    """
    print("\n✅ Successfully completed work item!")
    print("   All changes committed and validated")
    
    if not check_and_merge_worktree(item, worktree_path):
        return False
    
    close_work_item_and_parents(item)
    
    return True


def check_and_merge_worktree(item: BeadsWorkItem, worktree_path: Path) -> bool:
    """Check if worktree has commits and merge if needed."""
    try:
        original_dir = os.getcwd()
        os.chdir(worktree_path)
        check_result = subprocess.run(
            ["git", "rev-list", "--count", "HEAD", "^master"],
            capture_output=True,
            text=True,
            check=True
        )
        commit_count = int(check_result.stdout.strip())
        os.chdir(original_dir)
        
        if commit_count == 0:
            print("\n⏭️  No commits in worktree - nothing to merge")
            print(f"   Cleaning up worktree without merge...")
            cleanup_worktree(item.id, force=True)
            return True
        
        return merge_worktree_to_dev(item)
        
    except Exception as e:
        os.chdir(original_dir)
        print(f"\n⚠️  Could not check commit count: {e}")
        print(f"   Attempting merge anyway...")
        return merge_worktree_to_dev(item)


def merge_worktree_to_dev(item: BeadsWorkItem) -> bool:
    """Merge worktree to ameliapayne/dev branch."""
    print(f"\n🔍 Checking if main repo is ready for merge...")
    is_ready, error_msg = check_main_repo_ready_for_merge()
    
    if not is_ready:
        print(f"\n⚠️  Cannot merge: {error_msg}")
        print(f"   Worktree preserved at worktrees/task-{item.id} - requires cleanup")
        
        # Create delegation issue for merge pre-check failure
        description = f"""Failed to merge worktree for work item {item.id} ({item.title})

**Issue:** {error_msg}

**Worktree Location:** `worktrees/task-{item.id}`

**Required Actions:**
1. Resolve the issue preventing merge:
   - {error_msg}
2. If main repo has uncommitted changes:
   ```bash
   git status
   git add <files>
   git commit -m "your message"
   ```
3. Push resolved changes:
   ```bash
   cd worktrees/task-{item.id}
   git push
   cd ../..
   git merge task/{item.id}
   ```
4. Clean up the worktree: `git worktree remove worktrees/task-{item.id}`

**Work Item:** {item.id} - {item.title}
"""
        
        print(f"   Invoking cleanup agent to resolve uncommitted changes before merge...")
        from .cleanup_agents import invoke_cleanup_agent
        
        cleanup_success, _ = invoke_cleanup_agent(item, Path.cwd())
        
        if cleanup_success:
             print("   Cleanup successful, retrying merge check...")
             is_ready, error_msg = check_main_repo_ready_for_merge()
             if not is_ready:
                 print(f"   Still failing after cleanup: {error_msg}")
                 return False
        else:
             print("   Cleanup failed.")
             return False

        # print(f"   Note: Automatic cleanup issue creation disabled by user request.")
        # create_cleanup_delegation_issue(
        #     title=f"Resolve merge conflict for work item {item.id}",
        #     description=description,
        #     labels=['git', 'worktree', 'merge-conflict'],
        #     parent_id=item.id,
        #     priority=1  # High priority
        # )
        
        # print(f"   📋 Created delegation issue for cleanup")
        return False
    
    print(f"\n🔀 Merging worktree for {item.id}...")
    merge_success = merge_worktree(item.id, cleanup=True)
    
    if not merge_success:
        print(f"\n❌ Worktree merge failed (likely merge conflicts)!")
        print(f"   Worktree preserved at worktrees/task-{item.id} - requires conflict resolution")
        
        # Create delegation issue for merge failure
        description = f"""Failed to merge worktree for work item {item.id} ({item.title})

**Issue:** Git merge command failed (likely merge conflicts)

**Worktree Location:** `worktrees/task-{item.id}`

**Required Actions:**
1. Check merge conflicts:
   ```bash
   cd worktrees/task-{item.id}
   git status
   ```
2. Resolve conflicts manually:
   - Edit conflicted files
   - Mark as resolved: `git add <file>`
   - Complete merge: `git commit`
3. Push resolved changes: `git push`
4. Switch to main repo and merge:
   ```bash
   cd ../..
   git merge task/{item.id}
   ```
5. Clean up worktree: `git worktree remove worktrees/task-{item.id}`

**Work Item:** {item.id} - {item.title}
"""
        
        print(f"   Invoking cleanup agent to resolve conflicts...")
        from .cleanup_agents import invoke_merge_conflict_cleanup_agent
        
        success, _ = invoke_merge_conflict_cleanup_agent(item, Path.cwd(), "Merge conflict detected")
        
        if success:
            print("   Cleanup successful, retrying merge...")
            merge_success = merge_worktree(item.id, cleanup=True)
            if merge_success:
                 print("   Merged and cleaned up worktree")
                 return True
            else:
                 print("   Merge failed again after cleanup.")
                 return False
        else:
             print("   Cleanup failed.")
             return False

        # print(f"   Note: Automatic cleanup issue creation disabled by user request.")
        # create_cleanup_delegation_issue(
        #     title=f"Resolve merge conflict for work item {item.id}",
        #     description=description,
        #     labels=['git', 'worktree', 'merge-conflict'],
        #     parent_id=item.id,
        #     priority=1  # High priority
        # )
        
        # print(f"   📋 Created delegation issue for cleanup")
        return False
    
    print("   Merged and cleaned up worktree")
    return True


def close_work_item_and_parents(item: BeadsWorkItem) -> None:
    """Close work item and check if parents should be closed."""
    print(f"\n🔍 Checking if agent closed beads item {item.id}...")
    try:
        check_result = subprocess.run(
            ["bd", "show", item.id, "--json"],
            capture_output=True,
            text=True,
            check=True
        )
        # bd show --json returns a list, not a dict - get first element
        items_data = json.loads(check_result.stdout)
        if not items_data:
            raise ValueError(f"No data returned for item {item.id}")
        item_data = items_data[0]
        
        if item_data.get("status") in ["closed", "completed"]:
            print(f"   ✅ Agent successfully closed the item")
        else:
            print(f"   ⚠️  Item not closed by agent, closing now...")
            close_item(item.id, "Completed by PokePoke orchestrator (agent did not close)")
    except Exception as e:
        print(f"   ⚠️  Could not check item status: {e}")
        print(f"   Closing item as fallback...")
        close_item(item.id, "Completed by PokePoke orchestrator")
    
    # Check parent hierarchy
    check_parent_hierarchy(item)


def check_parent_hierarchy(item: BeadsWorkItem) -> None:
    """Check and close parent items if all children are complete."""
    parent_id = get_parent_id(item.id)
    if parent_id:
        print(f"\n🔍 Checking parent {parent_id} completion status...")
        close_parent_if_complete(parent_id)
        
        # Recursively check grandparents
        grandparent_id = get_parent_id(parent_id)
        if grandparent_id:
            close_parent_if_complete(grandparent_id)
