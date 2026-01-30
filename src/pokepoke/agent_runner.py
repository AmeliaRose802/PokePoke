"""Agent runner utilities for cleanup and maintenance agents."""

import os
import subprocess
import json
import re
from pathlib import Path
from typing import Optional

from pokepoke.copilot import invoke_copilot
from pokepoke.types import BeadsWorkItem, AgentStats, CopilotResult
from pokepoke.stats import parse_agent_stats
from pokepoke.worktrees import create_worktree, merge_worktree, cleanup_worktree
from pokepoke.prompts import PromptService
from pokepoke.cleanup_agents import (
    invoke_cleanup_agent, invoke_merge_conflict_cleanup_agent, 
    get_pokepoke_prompts_dir, run_cleanup_loop, aggregate_cleanup_stats
)

# Re-export cleanup agent functions for backward compatibility
__all__ = ['invoke_cleanup_agent', 'invoke_merge_conflict_cleanup_agent',
           'aggregate_cleanup_stats', 'run_cleanup_loop', 'run_maintenance_agent',
           'run_beta_tester', 'run_gate_agent']

def run_gate_agent(item: BeadsWorkItem) -> tuple[bool, str, Optional[AgentStats]]:
    """Run the Gate Agent to verify a fixed work item.
    
    Args:
        item: The work item to verify
        
    Returns:
        Tuple of (success: bool, reason: str, stats: AgentStats)
    """
    print(f"\n{'='*60}")
    print(f"🕵️ Running Gate Agent on {item.id}")
    print(f"{'='*60}")
    
    service = PromptService()
    try:
        final_prompt = service.load_and_render("gate-agent", {
            "item_id": item.id,
            "title": item.title,
            "description": item.description or ""
        })
    except Exception as e:
        return False, f"Failed to render prompt: {e}", None

    # Gate Agent runs in the current directory (which should be the worktree)
    # deny_write=True ensures it only reads/runs tests but doesn't modify code
    result = invoke_copilot(item, prompt=final_prompt, deny_write=True)
    
    stats = parse_agent_stats(result.output) if result.output else None
    
    if not result.success:
        return False, f"Gate Agent execution failed: {result.error}", stats
        
    # Parse output for decision
    output = result.output or ""
    
    # Try to find JSON block
    json_match = re.search(r'```json\s*(\{.*?\})\s*```', output, re.DOTALL)
    if json_match:
        try:
            data = json.loads(json_match.group(1))
            status = data.get("status")
            if status == "success":
                return True, data.get("message", "Verification successful"), stats
            else:
                reason = data.get("reason", "Verification failed")
                details = data.get("details", "")
                full_reason = f"{reason}\nDetails: {details}"
                return False, full_reason, stats
        except json.JSONDecodeError:
            pass
            
    # Fallback to text matching if JSON fails
    if "VERIFICATION SUCCESSFUL" in output:
        return True, "Verification successful (text match)", stats
    
    return False, "Gate Agent did not explicitly approve the fix. Check logs.", stats


def run_maintenance_agent(agent_name: str, prompt_file: str, repo_root: Optional[Path] = None, needs_worktree: bool = True, merge_changes: bool = True, model: Optional[str] = None) -> Optional[AgentStats]:
    """Run a maintenance agent with optional worktree isolation.
    
    Args:
        agent_name: Display name for the agent (e.g., 'Janitor', 'Tech Debt')
        prompt_file: Path to the prompt file (e.g., 'janitor.md')
        repo_root: Path to the main repository root (defaults to current directory)
        needs_worktree: If True, creates worktree for code changes. If False, runs in main repo for beads-only changes.
        merge_changes: If True, merges changes back to main repo. If False, discards worktree after run.
        model: Optional model name to use (e.g., 'gpt-5.1-codex', defaults to 'claude-sonnet-4.5')
        
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
        return _run_beads_only_agent(agent_name, agent_item, agent_prompt, model=model)
    
    # Code-modifying agents need worktree isolation
    # Ensure repo_root has a value
    if repo_root is None:
        repo_root = Path.cwd()
    
    return _run_worktree_agent(agent_name, agent_id, agent_item, agent_prompt, repo_root, merge_changes=merge_changes, model=model)


def _run_beads_only_agent(agent_name: str, agent_item: BeadsWorkItem, agent_prompt: str, model: Optional[str] = None) -> Optional[AgentStats]:
    """Run a beads-only maintenance agent in the main repo."""
    print(f"\n📋 Running {agent_name} in main repository (beads-only)")
    print(f"   File write access: DENIED")
    if model:
        print(f"   Model: {model}")
    
    result = invoke_copilot(agent_item, prompt=agent_prompt, deny_write=True, model=model)
    
    if result.success:
        print(f"\n✅ {agent_name} agent completed successfully")
        return parse_agent_stats(result.output) if result.output else None
    else:
        print(f"\n❌ {agent_name} agent failed: {result.error}")
        return None


def _run_worktree_agent(agent_name: str, agent_id: str, agent_item: BeadsWorkItem, agent_prompt: str, repo_root: Path, merge_changes: bool = True, model: Optional[str] = None) -> Optional[AgentStats]:
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
        if model:
            print(f"   Model: {model}")
        
        try:
            result = invoke_copilot(agent_item, prompt=agent_prompt, model=model)
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
        
        if not merge_changes:
            print("   Discarding worktree (merge_changes=False)")
            cleanup_worktree(agent_id, force=True)
            return parse_agent_stats(result.output) if result.output else None

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

            return None
        
        print(f"\n🔀 Merging worktree for {agent_id}...")
        from pokepoke.git_operations import is_merge_in_progress, get_unmerged_files, abort_merge
        
        merge_success, unmerged_files = merge_worktree(agent_id, cleanup=True)
        
        if not merge_success:
            print(f"\n❌ Worktree merge failed!")
            if unmerged_files:
                print(f"   Conflicted files ({len(unmerged_files)}):")
                for f in unmerged_files[:5]:
                    print(f"      - {f}")
                if len(unmerged_files) > 5:
                    print(f"      ... and {len(unmerged_files) - 5} more")
            print(f"   Worktree preserved at worktrees/task-{agent_id} for manual intervention")
            
            print(f"   Invoking cleanup agent to resolve conflicts...")
            
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
                        return None
                    print("   ✅ Merge aborted, will retry")
                
                merge_success, _ = merge_worktree(agent_id, cleanup=True)
                if merge_success:
                     print("   Merged and cleaned up worktree")
                     return agent_stats
                else:
                     print("   Merge failed again after cleanup.")
                     # Abort the merge to leave clean state
                     if is_merge_in_progress():
                         abort_merge()
                     return None
            else:
                 print("   Cleanup failed.")
                 # Abort the merge to leave clean state
                 if is_merge_in_progress():
                     print("   Aborting merge to reset state...")
                     abort_merge()
                 return None
        
        print("   Merged and cleaned up worktree")
        return agent_stats
    else:
        print(f"\n❌ {agent_name} agent failed: {result.error}")
        print(f"\n🧹 Cleaning up worktree...")
        cleanup_worktree(agent_id, force=True)
        return None


def run_beta_tester(repo_root: Optional[Path] = None) -> Optional[AgentStats]:
    """Run beta tester agent to test all MCP tools.
    
    Restarts the MCP server before testing to ensure latest code is loaded.
    Runs in a disposable worktree to isolate any generated documentation.
    
    Returns:
        AgentStats if successful, None otherwise
    """
    print(f"\n{'='*60}")
    print(f"🧪 Running Beta Tester Agent")
    print(f"{'='*60}")
    
    # Restart MCP server to load latest code
    print("\n🔄 Restarting MCP server to load latest changes...")
    try:
        # Resolve script path relative to this file
        # src/pokepoke/agent_runner.py -> src/pokepoke -> src -> root -> scripts
        package_root = Path(__file__).resolve().parent.parent.parent
        restart_script = package_root / "scripts" / "Restart-MCPServer.ps1"
        
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
    
    agent_id = "beta-tester"
    beta_item = BeadsWorkItem(
        id=agent_id,
        title="Beta Test All MCP Tools",
        description=beta_prompt,
        status="in_progress",
        priority=2,
        issue_type="task",
        labels=["testing", "mcp-server", "automated"]
    )
    
    print("\n🧪 Invoking beta tester agent in isolated worktree (will be discarded)...")
    
    if repo_root is None:
        repo_root = Path.cwd()
        
    return _run_worktree_agent("Beta Tester", agent_id, beta_item, beta_prompt, repo_root, merge_changes=False)

