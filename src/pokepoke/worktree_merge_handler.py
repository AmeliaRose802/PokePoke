"""Worktree merge handling for maintenance agents."""

from pathlib import Path
from typing import Optional

from pokepoke.types import BeadsWorkItem, AgentStats
from pokepoke.worktrees import merge_worktree, cleanup_worktree
from pokepoke.cleanup_agents import invoke_cleanup_agent, invoke_merge_conflict_cleanup_agent


def handle_worktree_merge(
    agent_id: str,
    agent_item: BeadsWorkItem,
    agent_name: str,
    worktree_path: Path,
    repo_root: Path,
    agent_stats: Optional[AgentStats]
) -> tuple[bool, bool]:
    """Handle worktree merge with conflict resolution.
    
    Args:
        agent_id: Agent ID for worktree tracking
        agent_item: Work item for the agent
        agent_name: Display name of the agent
        worktree_path: Path to the worktree
        repo_root: Repository root path
        agent_stats: Agent statistics to return
        
    Returns:
        Tuple of (merge_success, worktree_cleaned)
    """
    from pokepoke.git_operations import (
        check_main_repo_ready_for_merge,
        is_merge_in_progress,
        get_unmerged_files,
        abort_merge
    )
    from pokepoke.worktree_cleanup import add_uncleaned_worktree, remove_from_manifest
    
    # Check if main repo is ready for merge
    print("\n🔍 Checking if main repo is ready for merge...")
    is_ready, error_msg = check_main_repo_ready_for_merge()

    if not is_ready:
        print(f"\n⚠️  Cannot merge: {error_msg}")
        print(f"   Worktree preserved at worktrees/task-{agent_id} for manual intervention")
        
        # Track preserved worktree in manifest
        add_uncleaned_worktree(
            agent_id,
            str(worktree_path),
            f"Main repo not ready for merge: {error_msg}"
        )
        
        print("   Invoking cleanup agent to resolve uncommitted changes before merge...")
        cleanup_success, _ = invoke_cleanup_agent(agent_item, repo_root)

        if cleanup_success:
            print("   Cleanup successful, retrying merge check...")
            is_ready, error_msg = check_main_repo_ready_for_merge()
            if not is_ready:
                print(f"   Still failing after cleanup: {error_msg}")
                return False, False
        else:
            print("   Cleanup failed.")
            return False, False

        return False, False
    
    # Attempt merge
    print(f"\n🔀 Merging worktree for {agent_id}...")
    merge_success, unmerged_files = merge_worktree(agent_id, cleanup=True)
    
    if not merge_success:
        print("\n❌ Worktree merge failed!")
        if unmerged_files:
            print(f"   Conflicted files ({len(unmerged_files)}):")
            for f in unmerged_files[:5]:
                print(f"      - {f}")
            if len(unmerged_files) > 5:
                print(f"      ... and {len(unmerged_files) - 5} more")
        print(f"   Worktree preserved at worktrees/task-{agent_id} for manual intervention")
        
        # Track preserved worktree in manifest
        add_uncleaned_worktree(
            agent_id,
            str(worktree_path),
            f"Merge conflict in {len(unmerged_files) if unmerged_files else 0} file(s)"
        )
        
        print("   Invoking cleanup agent to resolve conflicts...")

        # Get fresh unmerged files if not provided
        if not unmerged_files:
            unmerged_files = get_unmerged_files()

        success, _ = invoke_merge_conflict_cleanup_agent(
            agent_item,
            repo_root,
            f"Merge conflict detected in {len(unmerged_files)} file(s)",
            unmerged_files=unmerged_files
        )

        if success:
            print("   Cleanup successful, retrying merge...")
            # Check if merge is still in progress (agent may have completed it)
            if is_merge_in_progress():
                print("   ⚠️  Merge still in progress after cleanup - aborting to reset state")
                abort_success, abort_error = abort_merge()
                if not abort_success:
                    print(f"   ❌ Failed to abort merge: {abort_error}")
                    return False, False
                print("   ✅ Merge aborted, will retry")

            merge_success, _ = merge_worktree(agent_id, cleanup=True)
            if merge_success:
                # Successful merge - remove from manifest and mark as cleaned
                remove_from_manifest(agent_id)
                print("   Merged and cleaned up worktree")
                return True, True
            else:
                print("   Merge failed again after cleanup.")
                # Abort the merge to leave clean state
                if is_merge_in_progress():
                    abort_merge()
                return False, False
        else:
            print("   Cleanup failed.")
            # Abort the merge to leave clean state
            if is_merge_in_progress():
                print("   Aborting merge to reset state...")
                abort_merge()
            return False, False
    else:
        # Successful merge - worktree already cleaned by merge_worktree
        print("   Merged and cleaned up worktree")
        return True, True
