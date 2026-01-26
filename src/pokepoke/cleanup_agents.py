"""Cleanup agent invocation utilities."""

import os
import subprocess
from pathlib import Path
from typing import Optional

from pokepoke.copilot import invoke_copilot
from pokepoke.types import BeadsWorkItem, AgentStats, CopilotResult
from pokepoke.git_operations import verify_main_repo_clean, commit_all_changes

def aggregate_cleanup_stats(result_stats: Optional[AgentStats], cleanup_stats: Optional[AgentStats]) -> None:
    """Aggregate cleanup agent stats into result stats."""
    if cleanup_stats and result_stats:
        result_stats.wall_duration += cleanup_stats.wall_duration
        result_stats.api_duration += cleanup_stats.api_duration
        result_stats.input_tokens += cleanup_stats.input_tokens
        result_stats.output_tokens += cleanup_stats.output_tokens
        result_stats.lines_added += cleanup_stats.lines_added
        result_stats.lines_removed += cleanup_stats.lines_removed
        result_stats.premium_requests += cleanup_stats.premium_requests


def run_cleanup_loop(item: BeadsWorkItem, result: CopilotResult, repo_root: Path) -> tuple[bool, int]:
    """Run cleanup loop to commit changes and fix validation failures."""
    cleanup_agent_runs = 0
    cleanup_attempt = 0
    
    # Check for uncommitted changes, excluding beads-only changes
    try:
        is_clean, uncommitted, non_beads_changes = verify_main_repo_clean()
    except Exception as e:
        print(f"\n⚠️  Error checking git status: {e}")
        return False, cleanup_agent_runs
    
    while result.success and not is_clean:
        cleanup_attempt += 1
        print(f"\n⚠️  Uncommitted non-beads changes detected (cleanup attempt {cleanup_attempt})")
        print(f"   Files: {', '.join(f.split()[1] if len(f.split()) > 1 else f for f in non_beads_changes[:5])}..." if len(non_beads_changes) > 5 else f"   Files: {', '.join(f.split()[1] if len(f.split()) > 1 else f for f in non_beads_changes)}")
        
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
        
        # Re-check status after cleanup
        try:
            is_clean, uncommitted, non_beads_changes = verify_main_repo_clean()
        except Exception as e:
            print(f"\n⚠️  Error checking git status after cleanup: {e}")
            result.success = False
            result.error = f"Git status check failed: {e}"
            break
    
    return result.success, cleanup_agent_runs


def get_pokepoke_prompts_dir() -> Path:
    """Get the prompts directory from the PokePoke installation."""
    # Prompts are relative to this file's location in the PokePoke package
    # This file is at: PokePoke/src/pokepoke/cleanup_agents.py
    # Prompts are at: PokePoke/.pokepoke/prompts/
    pokepoke_root = Path(__file__).parent.parent.parent
    prompts_dir = pokepoke_root / ".pokepoke" / "prompts"
    
    if not prompts_dir.exists():
        raise FileNotFoundError(
            f"PokePoke prompts directory not found at {prompts_dir}. "
            f"Make sure you have the .pokepoke/prompts/ directory in your PokePoke installation."
        )
    
    return prompts_dir


def _get_current_git_context() -> tuple[str, str, bool]:
    """Get current git context (directory, branch, is_worktree)."""
    current_dir = os.getcwd()
    
    # Get current branch
    try:
        branch_result = subprocess.run(
            ["git", "branch", "--show-current"],
            capture_output=True,
            text=True,
            timeout=10,
            errors='replace'
        )
        current_branch = branch_result.stdout.strip() if branch_result.returncode == 0 else "unknown"
    except Exception:
        current_branch = "unknown"
    
    # Determine if we're in a worktree
    try:
        worktree_result = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            capture_output=True,
            text=True,
            timeout=10,
            errors='replace'
        )
        is_worktree = worktree_result.returncode == 0 and worktree_result.stdout.strip() == "true"
    except Exception:
        is_worktree = False
    
    return current_dir, current_branch, is_worktree


def invoke_cleanup_agent(item: BeadsWorkItem, repo_root: Path) -> tuple[bool, Optional[AgentStats]]:
    """Invoke cleanup agent to commit uncommitted changes."""
    try:
        prompts_dir = get_pokepoke_prompts_dir()
        cleanup_prompt_path = prompts_dir / "cleanup.md"
    except FileNotFoundError as e:
        print(f"❌ {e}")
        return False, None
    
    if not cleanup_prompt_path.exists():
        print(f"❌ Cleanup prompt not found at {cleanup_prompt_path}")
        return False, None
    
    cleanup_prompt_template = cleanup_prompt_path.read_text(encoding='utf-8')
    
    # Get current context information
    current_dir, current_branch, is_worktree = _get_current_git_context()
    
    # Replace placeholders in template
    cleanup_prompt_template = cleanup_prompt_template.replace("{cwd}", current_dir)
    cleanup_prompt_template = cleanup_prompt_template.replace("{branch}", current_branch)
    cleanup_prompt_template = cleanup_prompt_template.replace("{is_worktree}", str(is_worktree))
    
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
    copilot_result = invoke_copilot(cleanup_item, prompt=cleanup_prompt)
    
    return copilot_result.success, copilot_result.stats


def invoke_merge_conflict_cleanup_agent(item: BeadsWorkItem, repo_root: Path, error_msg: str) -> tuple[bool, Optional[AgentStats]]:
    """Invoke cleanup agent to resolve merge conflicts."""
    try:
        prompts_dir = get_pokepoke_prompts_dir()
        cleanup_prompt_path = prompts_dir / "merge-conflict-cleanup.md"
    except FileNotFoundError as e:
        print(f"❌ {e}")
        return False, None
    
    if not cleanup_prompt_path.exists():
        # Fallback to standard cleanup
        print(f"⚠️ Merge conflict cleanup prompt not found at {cleanup_prompt_path}, falling back to standard cleanup")
        return invoke_cleanup_agent(item, repo_root)
    
    cleanup_prompt_template = cleanup_prompt_path.read_text(encoding='utf-8')
    
    # Get current context information
    current_dir, current_branch, is_worktree = _get_current_git_context()
    
    # Replace placeholders in template
    cleanup_prompt_template = cleanup_prompt_template.replace("{cwd}", current_dir)
    cleanup_prompt_template = cleanup_prompt_template.replace("{branch}", current_branch)
    cleanup_prompt_template = cleanup_prompt_template.replace("{is_worktree}", str(is_worktree))
    cleanup_prompt_template = cleanup_prompt_template.replace("{merge_error}", error_msg)
    cleanup_prompt_template = cleanup_prompt_template.replace("{worktree_path}", f"worktrees/task-{item.id}")
    
    work_item_context = f"""
# Work Item That Failed to Merge

**ID:** {item.id}
**Title:** {item.title}
**Type:** {item.issue_type}
**Priority:** {item.priority}
**Status:** {item.status}

**Description:**
{item.description}

**Merge Error:**
{error_msg}
"""
    
    if item.labels:
        work_item_context += f"\n**Labels:** {', '.join(item.labels)}\n"
    
    cleanup_prompt = f"{work_item_context}\n\n---\n\n{cleanup_prompt_template}"
    
    cleanup_item = BeadsWorkItem(
        id=f"{item.id}-merge-fix",
        title=f"Fix merge conflicts for {item.id}",
        description=cleanup_prompt,
        status="in_progress",
        priority=0,
        issue_type="task",
        labels=["cleanup", "merge-conflict"]
    )
    
    print("\n🧹 Invoking merge conflict cleanup agent...")
    copilot_result = invoke_copilot(cleanup_item, prompt=cleanup_prompt)
    
    return copilot_result.success, copilot_result.stats
