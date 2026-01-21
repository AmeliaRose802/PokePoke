"""Agent runner utilities for cleanup and maintenance agents."""

import os
import subprocess
from pathlib import Path
from typing import Optional

from pokepoke.copilot import invoke_copilot_cli
from pokepoke.types import BeadsWorkItem, AgentStats, CopilotResult
from pokepoke.stats import parse_agent_stats
from pokepoke.worktrees import create_worktree, merge_worktree, cleanup_worktree


def has_uncommitted_changes() -> bool:
    """Check if there are any uncommitted changes in the current directory.
    
    Returns:
        True if there are uncommitted changes, False otherwise
    """
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            check=True
        )
        return bool(result.stdout.strip())
    except subprocess.CalledProcessError:
        return False


def commit_all_changes(message: str = "Auto-commit by PokePoke") -> tuple[bool, str]:
    """Commit all changes, triggering pre-commit hooks for validation.
    
    Args:
        message: Commit message
        
    Returns:
        Tuple of (success: bool, error_message: str)
    """
    try:
        subprocess.run(
            ["git", "add", "-A"],
            check=True,
            capture_output=True,
            text=True
        )
        
        result = subprocess.run(
            ["git", "commit", "-m", message],
            capture_output=True,
            text=True
        )
        
        if result.returncode == 0:
            return True, ""
        else:
            error_lines = result.stderr.strip().split('\n') if result.stderr else []
            if error_lines:
                errors = [line for line in error_lines if line.strip() and not line.startswith('hint:')][:5]
                return False, '\n   '.join(errors) if errors else "Commit failed"
            return False, "Commit failed (unknown reason)"
    except subprocess.CalledProcessError as e:
        return False, f"Commit error: {e.stderr if e.stderr else str(e)}"


def invoke_cleanup_agent(item: BeadsWorkItem, repo_root: Path) -> tuple[bool, Optional[AgentStats]]:
    """Invoke cleanup agent to commit uncommitted changes.
    
    Args:
        item: The work item being processed
        repo_root: Path to the main repository root
        
    Returns:
        Tuple of (success, stats)
    """
    cleanup_prompt_path = repo_root / ".pokepoke" / "prompts" / "cleanup.md"
    if not cleanup_prompt_path.exists():
        print(f"❌ Cleanup prompt not found at {cleanup_prompt_path}")
        return False, None
    
    cleanup_prompt_template = cleanup_prompt_path.read_text()
    
    work_item_context = f"""
# Work Item Being Cleaned Up

**ID:** {item.id}
**Title:** {item.title}
**Type:** {item.issue_type}
**Priority:** {item.priority}
**Status:** {item.status}

**Description:**
{item.description}
"""
    
    if item.labels:
        work_item_context += f"\n**Labels:** {', '.join(item.labels)}\n"
    
    cleanup_prompt = f"{work_item_context}\n\n---\n\n{cleanup_prompt_template}"
    
    cleanup_item = BeadsWorkItem(
        id=f"{item.id}-cleanup",
        title=f"Cleanup for {item.id}",
        description=cleanup_prompt,
        status="in_progress",
        priority=0,
        issue_type="task",
        labels=["cleanup", "automated"]
    )
    
    print("\n🧹 Invoking cleanup agent...")
    result = invoke_copilot_cli(cleanup_item, prompt=cleanup_prompt)
    
    return result.success, result.stats


def aggregate_cleanup_stats(result_stats: Optional[AgentStats], cleanup_stats: Optional[AgentStats]) -> None:
    """Aggregate cleanup agent stats into result stats.
    
    Args:
        result_stats: Main agent stats to update (modified in place)
        cleanup_stats: Cleanup agent stats to add
    """
    if cleanup_stats and result_stats:
        result_stats.wall_duration += cleanup_stats.wall_duration
        result_stats.api_duration += cleanup_stats.api_duration
        result_stats.input_tokens += cleanup_stats.input_tokens
        result_stats.output_tokens += cleanup_stats.output_tokens
        result_stats.lines_added += cleanup_stats.lines_added
        result_stats.lines_removed += cleanup_stats.lines_removed
        result_stats.premium_requests += cleanup_stats.premium_requests


def run_cleanup_loop(item: BeadsWorkItem, result: CopilotResult, repo_root: Path) -> tuple[bool, int]:
    """Run cleanup loop to commit changes and fix validation failures.
    
    Args:
        item: Work item being processed
        result: Result from Copilot CLI invocation
        repo_root: Path to main repository root
        
    Returns:
        Tuple of (success: bool, cleanup_agent_runs: int)
    """
    cleanup_agent_runs = 0
    cleanup_attempt = 0
    
    while result.success and has_uncommitted_changes():
        cleanup_attempt += 1
        print(f"\n⚠️  Uncommitted changes detected (cleanup attempt {cleanup_attempt})")
        
        commit_success, commit_error = commit_all_changes(f"Work on {item.id}")
        
        if commit_success:
            print("✅ Changes committed successfully (validation passed)")
            break
        else:
            print(f"\n❌ Commit failed - validation errors:")
            print(f"   {commit_error}")
        
        print("\n🧹 Invoking cleanup agent to fix validation errors...")
        cleanup_agent_runs += 1
        cleanup_success, cleanup_stats = invoke_cleanup_agent(item, repo_root)
        
        aggregate_cleanup_stats(result.stats, cleanup_stats)
        
        if not cleanup_success:
            print("\n❌ Cleanup agent failed")
            result.success = False
            result.error = "Cleanup agent failed to fix issues"
            break
    
    return result.success, cleanup_agent_runs


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
    
    if repo_root is None:
        repo_root = Path.cwd()
    
    prompt_path = repo_root / ".pokepoke" / "prompts" / prompt_file
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
    return _run_worktree_agent(agent_name, agent_id, agent_item, agent_prompt, repo_root)


def _run_beads_only_agent(agent_name: str, agent_item: BeadsWorkItem, agent_prompt: str) -> Optional[AgentStats]:
    """Run a beads-only maintenance agent in the main repo."""
    print(f"\n📋 Running {agent_name} in main repository (beads-only)")
    print(f"   File write access: DENIED")
    
    result = invoke_copilot_cli(agent_item, prompt=agent_prompt, deny_write=True)
    
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
        
        result = invoke_copilot_cli(agent_item, prompt=agent_prompt)
        
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
            print(f"   To merge later: cd worktrees/task-{agent_id} && git push && cd ../.. && git merge task/{agent_id}")
            return None
        
        print(f"\n🔀 Merging worktree for {agent_id}...")
        merge_success = merge_worktree(agent_id, cleanup=True)
        
        if not merge_success:
            print(f"\n❌ Worktree merge failed!")
            print(f"   Worktree preserved at worktrees/task-{agent_id} for manual intervention")
            print(f"   Check 'git status' in main repo and worktree, resolve conflicts, then merge manually")
            return None
        
        print("   Merged and cleaned up worktree")
        return agent_stats
    else:
        print(f"\n❌ {agent_name} agent failed: {result.error}")
        print(f"\n🧹 Cleaning up worktree...")
        cleanup_worktree(agent_id, force=True)
        return None
