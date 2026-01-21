"""Workflow management for work item selection and processing."""

import json
import os
import subprocess
import time
from pathlib import Path
from typing import Optional

from pokepoke.beads import (
    select_next_hierarchical_item,
    close_item,
    get_parent_id,
    close_parent_if_complete
)
from pokepoke.copilot import invoke_copilot_cli
from pokepoke.types import BeadsWorkItem, AgentStats, CopilotResult
from pokepoke.stats import parse_agent_stats
from pokepoke.worktrees import create_worktree, merge_worktree, cleanup_worktree
from pokepoke.git_operations import check_main_repo_ready_for_merge
from pokepoke.agent_runner import has_uncommitted_changes, run_cleanup_loop


def select_work_item(ready_items: list[BeadsWorkItem], interactive: bool) -> Optional[BeadsWorkItem]:
    """Select a work item to process using hierarchical assignment.
    
    Args:
        ready_items: List of available work items
        interactive: If True, prompt user to select; if False, use hierarchical selection
        
    Returns:
        Selected work item or None to quit
    """
    if not ready_items:
        print("\n✨ No ready work found in beads database.")
        print("   Run 'bd ready' to see available work items.")
        return None
    
    print(f"\n📋 Found {len(ready_items)} ready work items:\n")
    
    for idx, item in enumerate(ready_items, 1):
        print(f"{idx}. [{item.id}] {item.title}")
        print(f"   Type: {item.issue_type} | Priority: {item.priority}")
        if item.description:
            desc = item.description[:80]
            if len(item.description) > 80:
                desc += "..."
            print(f"   {desc}")
        print()
    
    if interactive:
        return _interactive_selection(ready_items)
    else:
        return _autonomous_selection(ready_items)


def _interactive_selection(ready_items: list[BeadsWorkItem]) -> Optional[BeadsWorkItem]:
    """Prompt user to select a work item."""
    while True:
        try:
            choice = input("Select a work item (number) or 'q' to quit: ").strip()
            
            if choice.lower() == 'q':
                return None
            
            idx = int(choice)
            if 1 <= idx <= len(ready_items):
                return ready_items[idx - 1]
            else:
                print(f"❌ Please enter a number between 1 and {len(ready_items)}")
        except ValueError:
            print("❌ Invalid input. Enter a number or 'q' to quit.")
        except KeyboardInterrupt:
            print("\n")
            return None


def _autonomous_selection(ready_items: list[BeadsWorkItem]) -> Optional[BeadsWorkItem]:
    """Use hierarchical selection for autonomous mode."""
    selected = select_next_hierarchical_item(ready_items)
    if selected:
        print(f"🤖 Hierarchically selected item: {selected.id}")
        print(f"   Type: {selected.issue_type} | Priority: {selected.priority}")
    return selected


def process_work_item(item: BeadsWorkItem, interactive: bool, timeout_hours: float = 2.0, run_cleanup_agents: bool = False) -> tuple[bool, int, Optional[AgentStats], int]:
    """Process a single work item with timeout protection.
    
    Args:
        item: Work item to process
        interactive: If True, prompt for confirmation before proceeding
        timeout_hours: Maximum hours before timing out and restarting (default: 2.0)
        run_cleanup_agents: If True, run maintenance agents after completion (default: False)
        
    Returns:
        Tuple of (success: bool, request_count: int, stats: Optional[AgentStats], cleanup_agent_runs: int)
    """
    start_time = time.time()
    timeout_seconds = timeout_hours * 3600
    request_count = 0
    cleanup_agent_runs = 0
    
    print(f"\n🚀 Processing work item: {item.id}")
    print(f"   {item.title}")
    print(f"   ⏱️  Timeout: {timeout_hours} hours\n")
    
    if interactive:
        confirm = input("Proceed with this item? [Y/n]: ").strip().lower()
        if confirm and confirm != 'y':
            print("⏭️  Skipped.")
            return False, 0, None, 0
    
    pokepoke_root = Path(r"C:\Users\ameliapayne\PokePoke")
    worktree_path = _setup_worktree(item)
    
    if worktree_path is None:
        return False, 0, None, 0
    
    original_dir = os.getcwd()
    
    try:
        os.chdir(worktree_path)
        print(f"   Switched to worktree directory\n")
        
        # Check timeout before invoking Copilot
        elapsed = time.time() - start_time
        if elapsed >= timeout_seconds:
            print(f"\n⏱️  TIMEOUT: Execution exceeded {timeout_hours} hours")
            print(f"   Restarting item {item.id} in same worktree...\n")
            os.chdir(original_dir)
            return process_work_item(item, interactive, timeout_hours)
        
        remaining_timeout = timeout_seconds - elapsed
        result = invoke_copilot_cli(item, timeout=remaining_timeout)
        request_count += result.attempt_count
        
        if result.success and not has_uncommitted_changes():
            print("\n✅ No changes made - work item may already be complete")
            print("   Skipping cleanup and commit steps")
        
        # Run cleanup loop with timeout checking
        cleanup_success, cleanup_runs = _run_cleanup_with_timeout(
            item, result, pokepoke_root, start_time, timeout_seconds, timeout_hours
        )
        cleanup_agent_runs += cleanup_runs
        
        if not cleanup_success:
            os.chdir(original_dir)
            return process_work_item(item, interactive, timeout_hours)
    
    finally:
        os.chdir(original_dir)
    
    if result.success:
        success = _finalize_work_item(item, worktree_path)
        item_stats = parse_agent_stats(result.output) if result.output else None
        return success, request_count, item_stats, cleanup_agent_runs
    else:
        print(f"\n❌ Failed to complete work item: {result.error}")
        print(f"\n🧹 Cleaning up worktree...")
        cleanup_worktree(item.id, force=True)
        return False, request_count, None, cleanup_agent_runs


def _setup_worktree(item: BeadsWorkItem) -> Optional[Path]:
    """Create worktree for work item processing."""
    print(f"\n🌳 Creating worktree for {item.id}...")
    try:
        worktree_path = create_worktree(item.id)
        print(f"   Created at: {worktree_path}")
        return worktree_path
    except Exception as e:
        print(f"\n❌ Failed to create worktree: {e}")
        return None


def _run_cleanup_with_timeout(item: BeadsWorkItem, result: CopilotResult, repo_root: Path, start_time: float, timeout_seconds: float, timeout_hours: float) -> tuple[bool, int]:
    """Run cleanup loop with timeout checking."""
    cleanup_agent_runs = 0
    cleanup_attempt = 0
    
    while result.success and has_uncommitted_changes():
        elapsed = time.time() - start_time
        if elapsed >= timeout_seconds:
            print(f"\n⏱️  TIMEOUT: Execution exceeded {timeout_hours} hours during cleanup")
            print(f"   Restarting item {item.id} in same worktree...\n")
            return False, cleanup_agent_runs
        
        cleanup_attempt += 1
        cleanup_success, cleanup_runs = run_cleanup_loop(item, result, repo_root)
        cleanup_agent_runs += cleanup_runs
        
        if not cleanup_success:
            break
    
    return result.success, cleanup_agent_runs


def _finalize_work_item(item: BeadsWorkItem, worktree_path: Path) -> bool:
    """Finalize work item by merging worktree and closing issue.
    
    Returns:
        True if successful, False otherwise
    """
    print("\n✅ Successfully completed work item!")
    print("   All changes committed and validated")
    
    if not _check_and_merge_worktree(item, worktree_path):
        return False
    
    _close_work_item_and_parents(item)
    
    return True


def _check_and_merge_worktree(item: BeadsWorkItem, worktree_path: Path) -> bool:
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
        
        return _merge_worktree_to_master(item)
        
    except Exception as e:
        os.chdir(original_dir)
        print(f"\n⚠️  Could not check commit count: {e}")
        print(f"   Attempting merge anyway...")
        return _merge_worktree_to_master(item)


def _merge_worktree_to_master(item: BeadsWorkItem) -> bool:
    """Merge worktree to master branch."""
    print(f"\n🔍 Checking if main repo is ready for merge...")
    is_ready, error_msg = check_main_repo_ready_for_merge()
    
    if not is_ready:
        print(f"\n⚠️  Cannot merge: {error_msg}")
        print(f"   Worktree preserved at worktrees/task-{item.id} for manual intervention")
        
        # Create delegation issue for cleanup
        from pokepoke.beads_management import create_cleanup_delegation_issue
        
        description = f"""Failed to merge worktree for item {item.id}: {item.title}

**Error:** {error_msg}

**Worktree Location:** `worktrees/task-{item.id}`

**Required Actions:**
1. Check git status in main repository: `git status`
2. Check git status in worktree: `cd worktrees/task-{item.id} && git status`
3. Resolve any uncommitted changes or conflicts
4. Manually merge the worktree:
   ```bash
   cd worktrees/task-{item.id}
   git push
   cd ../..
   git merge task/{item.id}
   ```
5. Clean up the worktree: `git worktree remove worktrees/task-{item.id}`

**Related Work Item:** {item.id}
"""
        
        create_cleanup_delegation_issue(
            title=f"Resolve merge conflict for worktree task-{item.id}",
            description=description,
            labels=['git', 'worktree', 'merge-conflict'],
            parent_id=item.id if item.issue_type != 'epic' else None,
            priority=1  # High priority - blocks completion of parent work
        )
        
        print(f"   📋 Created delegation issue for cleanup")
        return False
    
    print(f"\n🔀 Merging worktree for {item.id}...")
    merge_success = merge_worktree(item.id, cleanup=True)
    
    if not merge_success:
        print(f"\n❌ Worktree merge failed!")
        print(f"   Worktree preserved at worktrees/task-{item.id} for manual intervention")
        
        # Create delegation issue for merge failure
        from pokepoke.beads_management import create_cleanup_delegation_issue
        
        description = f"""Failed to merge worktree for item {item.id}: {item.title}

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

**Related Work Item:** {item.id}
"""
        
        create_cleanup_delegation_issue(
            title=f"Resolve merge conflict for worktree task-{item.id}",
            description=description,
            labels=['git', 'worktree', 'merge-conflict'],
            parent_id=item.id if item.issue_type != 'epic' else None,
            priority=1  # High priority
        )
        
        print(f"   📋 Created delegation issue for cleanup")
        return False
    
    print("   Merged and cleaned up worktree")
    return True


def _close_work_item_and_parents(item: BeadsWorkItem) -> None:
    """Close work item and check if parents should be closed."""
    print(f"\n🔍 Checking if agent closed beads item {item.id}...")
    try:
        check_result = subprocess.run(
            ["bd", "show", item.id, "--json"],
            capture_output=True,
            text=True,
            check=True
        )
        item_data = json.loads(check_result.stdout)
        
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
    _check_parent_hierarchy(item)


def _check_parent_hierarchy(item: BeadsWorkItem) -> None:
    """Check and close parent items if all children are complete."""
    parent_id = get_parent_id(item.id)
    if parent_id:
        print(f"\n🔍 Checking parent {parent_id} completion status...")
        close_parent_if_complete(parent_id)
        
        grandparent_id = get_parent_id(parent_id)
        if grandparent_id:
            print(f"\n🔍 Checking grandparent {grandparent_id} completion status...")
            close_parent_if_complete(grandparent_id)
