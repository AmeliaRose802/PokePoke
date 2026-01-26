"""Agent runner utilities for cleanup and maintenance agents."""

import os
import subprocess
from pathlib import Path
from typing import Optional

from pokepoke.copilot import invoke_copilot
from pokepoke.types import BeadsWorkItem, AgentStats, CopilotResult
from pokepoke.stats import parse_agent_stats
from pokepoke.worktrees import create_worktree, merge_worktree, cleanup_worktree
from pokepoke.cleanup_agents import (
    invoke_cleanup_agent, 
    invoke_merge_conflict_cleanup_agent, 
    get_pokepoke_prompts_dir,
    run_cleanup_loop,
    aggregate_cleanup_stats
)

# Re-export cleanup agent functions for backward compatibility
__all__ = [
    'invoke_cleanup_agent',
    'invoke_merge_conflict_cleanup_agent',
    'aggregate_cleanup_stats',
    'run_cleanup_loop',
    'run_maintenance_agent',
    'run_beta_tester',
]


def run_maintenance_agent(agent_name: str, prompt_file: str, repo_root: Optional[Path] = None, needs_worktree: bool = True) -> Optional[AgentStats]:
    """Run a maintenance agent with optional worktree isolation.
    
    Args:
        agent_name: Display name for the agent (e.g., 'Janitor', 'Tech Debt')
        prompt_file: Path to the prompt file (e.g., 'janitor.md')
        repo_root: Path to the main repository root (defaults to current directory)
        needs_worktree: If True, creates worktree for code changes. If False, runs in main repo for beads-only changes.
        
    Returns:
        AgentStats if successful, None otherwise
    """
    print(f"\n{'='*60}")
    print(f"🔧 Running {agent_name} Agent")
    print(f"{'='*60}")
    
    try:
        prompts_dir = get_pokepoke_prompts_dir()
        prompt_path = prompts_dir / prompt_file
    except FileNotFoundError as e:
        print(f"❌ {e}")
        return None
    
    if not prompt_path.exists():
        print(f"❌ Prompt not found at {prompt_path}")
        return None
    
    agent_prompt = prompt_path.read_text()
    
    agent_id = f"maintenance-{agent_name.lower().replace(' ', '-')}"
    agent_item = BeadsWorkItem(
        id=agent_id,
        title=f"{agent_name} Maintenance",
        description=agent_prompt,
        status="in_progress",
        priority=0,
        issue_type="task",
        labels=["maintenance", agent_name.lower()]
    )
    
    # Beads-only agents run in main repo without worktree
    if not needs_worktree:
        return _run_beads_only_agent(agent_name, agent_item, agent_prompt)
    
    # Code-modifying agents need worktree isolation
    # Ensure repo_root has a value
    if repo_root is None:
        repo_root = Path.cwd()
    
    return _run_worktree_agent(agent_name, agent_id, agent_item, agent_prompt, repo_root)


def _run_beads_only_agent(agent_name: str, agent_item: BeadsWorkItem, agent_prompt: str) -> Optional[AgentStats]:
    """Run a beads-only maintenance agent in the main repo."""
    print(f"\n📋 Running {agent_name} in main repository (beads-only)")
    print(f"   File write access: DENIED")
    
    result = invoke_copilot(agent_item, prompt=agent_prompt, deny_write=True)
    
    if result.success:
        print(f"\n✅ {agent_name} agent completed successfully")
        return parse_agent_stats(result.output) if result.output else None
    else:
        print(f"\n❌ {agent_name} agent failed: {result.error}")
        return None


def _run_worktree_agent(agent_name: str, agent_id: str, agent_item: BeadsWorkItem, agent_prompt: str, repo_root: Path) -> Optional[AgentStats]:
    """Run a code-modifying maintenance agent in a worktree."""
    print(f"\n🌳 Creating worktree for {agent_id}...")
    try:
        worktree_path = create_worktree(agent_id)
        print(f"   Created at: {worktree_path}")
    except Exception as e:
        print(f"\n❌ Failed to create worktree: {e}")
        return None
    
    original_dir = os.getcwd()
    try:
        os.chdir(worktree_path)
        print(f"   Switched to worktree directory\n")
        
        try:
            result = invoke_copilot(agent_item, prompt=agent_prompt)
        except Exception as e:
            print(f"❌ Error invoking Copilot: {e}")
            from pokepoke.types import CopilotResult
            result = CopilotResult(
                work_item_id=agent_item.id,
                success=False,
                output="",
                error=str(e),
                attempt_count=1
            )
        
        cleanup_success, _ = run_cleanup_loop(agent_item, result, repo_root)
        
        if not cleanup_success:
            result.success = False
    
    finally:
        os.chdir(original_dir)
    
    if result.success:
        print(f"\n✅ {agent_name} agent completed successfully!")
        print("   All changes committed and validated")
        
        agent_stats = parse_agent_stats(result.output) if result.output else None
        
        # Check if main repo is ready for merge
        from pokepoke.git_operations import check_main_repo_ready_for_merge
        
        print(f"\n🔍 Checking if main repo is ready for merge...")
        is_ready, error_msg = check_main_repo_ready_for_merge()
        
        if not is_ready:
            print(f"\n⚠️  Cannot merge: {error_msg}")
            print(f"   Worktree preserved at worktrees/task-{agent_id} for manual intervention")
            
            # Create delegation issue for cleanup
            from pokepoke.beads_management import create_cleanup_delegation_issue
            
            description = f"""Failed to merge worktree for {agent_name} agent (ID: {agent_id})

**Error:** {error_msg}

**Worktree Location:** `worktrees/task-{agent_id}`

**Required Actions:**
1. Check git status in main repository: `git status`
2. Check git status in worktree: `cd worktrees/task-{agent_id} && git status`
3. Resolve any uncommitted changes or conflicts
4. Manually merge the worktree:
   ```bash
   cd worktrees/task-{agent_id}
   git push
   cd ../..
   git merge task/{agent_id}
   ```
5. Clean up the worktree: `git worktree remove worktrees/task-{agent_id}`

**Agent:** {agent_name}
"""
            
            print(f"   Invoking cleanup agent to resolve uncommitted changes before merge...")
            # We use agent_item as context
            cleanup_success, _ = invoke_cleanup_agent(agent_item, repo_root)
            
            if cleanup_success:
                 print("   Cleanup successful, retrying merge check...")
                 is_ready, error_msg = check_main_repo_ready_for_merge()
                 if not is_ready:
                     print(f"   Still failing after cleanup: {error_msg}")
                     return None
            else:
                 print("   Cleanup failed.")
                 return None

            # print(f"   Note: Automatic cleanup issue creation disabled by user request.")
            # create_cleanup_delegation_issue(
            #     title=f"Resolve merge conflict for {agent_name} agent worktree",
            #     description=description,
            #     labels=['git', 'worktree', 'merge-conflict', 'agent'],
            #     priority=1  # High priority
            # )
            
            # print(f"   📋 Created delegation issue for cleanup")
            return None
        
        print(f"\n🔀 Merging worktree for {agent_id}...")
        merge_success = merge_worktree(agent_id, cleanup=True)
        
        if not merge_success:
            print(f"\n❌ Worktree merge failed!")
            print(f"   Worktree preserved at worktrees/task-{agent_id} for manual intervention")
            
            # Create delegation issue for merge failure
            from pokepoke.beads_management import create_cleanup_delegation_issue
            
            description = f"""Failed to merge worktree for {agent_name} agent (ID: {agent_id})

**Issue:** Git merge command failed (likely merge conflicts)

**Worktree Location:** `worktrees/task-{agent_id}`

**Required Actions:**
1. Check merge conflicts:
   ```bash
   cd worktrees/task-{agent_id}
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
   git merge task/{agent_id}
   ```
5. Clean up worktree: `git worktree remove worktrees/task-{agent_id}`

**Agent:** {agent_name}
"""
            
            print(f"   Invoking cleanup agent to resolve conflicts...")
            
            success, _ = invoke_merge_conflict_cleanup_agent(agent_item, repo_root, "Merge conflict detected")
            
            if success:
                print("   Cleanup successful, retrying merge...")
                merge_success = merge_worktree(agent_id, cleanup=True)
                if merge_success:
                     print("   Merged and cleaned up worktree")
                     return agent_stats
                else:
                     print("   Merge failed again after cleanup.")
                     return None
            else:
                 print("   Cleanup failed.")
                 return None

            # print(f"   Note: Automatic cleanup issue creation disabled by user request.")
            # create_cleanup_delegation_issue(
            #     title=f"Resolve merge conflict for {agent_name} agent worktree",
            #     description=description,
            #     labels=['git', 'worktree', 'merge-conflict', 'agent'],
            #     priority=1  # High priority
            # )
            
            # print(f"   📋 Created delegation issue for cleanup")
            return None
        
        print("   Merged and cleaned up worktree")
        return agent_stats
    else:
        print(f"\n❌ {agent_name} agent failed: {result.error}")
        print(f"\n🧹 Cleaning up worktree...")
        cleanup_worktree(agent_id, force=True)
        return None


def run_beta_tester() -> Optional[AgentStats]:
    """Run beta tester agent to test all MCP tools.
    
    Restarts the MCP server before testing to ensure latest code is loaded.
    Beta tester runs without a worktree since it only tests and files issues.
    
    Returns:
        AgentStats if successful, None otherwise
    """
    print(f"\n{'='*60}")
    print(f"🧪 Running Beta Tester Agent")
    print(f"{'='*60}")
    
    # Restart MCP server to load latest code
    print("\n🔄 Restarting MCP server to load latest changes...")
    try:
        restart_script = Path(r"C:\Users\ameliapayne\PokePoke\scripts\Restart-MCPServer.ps1")
        if not restart_script.exists():
            print(f"⚠️  Restart script not found at {restart_script}")
            print("   Proceeding without restart - server may have stale code")
        else:
            result = subprocess.run(
                ["pwsh", "-NoProfile", "-File", str(restart_script)],
                capture_output=True,
                text=True,
                encoding='utf-8',
                timeout=60  # 60 second timeout for restart
            )
            if result.returncode == 0:
                print("✓ MCP server restarted successfully")
            else:
                print(f"⚠️  MCP server restart had issues (exit code {result.returncode})")
                if result.stdout:
                    print(f"   Output: {result.stdout[:200]}")
    except subprocess.TimeoutExpired:
        print("⚠️  MCP server restart timed out (server may still be starting)")
    except Exception as e:
        print(f"⚠️  Could not restart MCP server: {e}")
        print("   Proceeding anyway - server may have stale code")
    
    # Load beta tester prompt
    try:
        prompts_dir = get_pokepoke_prompts_dir()
        prompt_path = prompts_dir / "beta-tester.md"
    except FileNotFoundError as e:
        print(f"❌ {e}")
        return None
    
    if not prompt_path.exists():
        print(f"❌ Prompt not found at {prompt_path}")
        return None
    
    beta_prompt = prompt_path.read_text(encoding='utf-8')
    
    beta_item = BeadsWorkItem(
        id="beta-tester",
        title="Beta Test All MCP Tools",
        description=beta_prompt,
        status="in_progress",
        priority=2,
        issue_type="task",
        labels=["testing", "mcp-server", "automated"]
    )
    
    print("\n🧪 Invoking beta tester agent...")
    # Beta tester doesn't need file write access - it only tests and files issues
    copilot_result = invoke_copilot(beta_item, prompt=beta_prompt, deny_write=True)
    
    if copilot_result.success:
        print(f"\n✅ Beta tester completed successfully!")
        return parse_agent_stats(copilot_result.output) if copilot_result.output else None
    else:
        print(f"\n❌ Beta tester failed: {copilot_result.error}")
        return None

