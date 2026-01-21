"""PokePoke Orchestrator - Main entry point for autonomous and interactive modes."""

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

from pokepoke.beads import (
    get_ready_work_items, 
    select_next_hierarchical_item,
    close_item,
    get_parent_id,
    close_parent_if_complete
)
from pokepoke.copilot import invoke_copilot_cli, build_prompt_from_template
from pokepoke.types import BeadsWorkItem, AgentStats
import re


def parse_agent_stats(output: str) -> Optional[AgentStats]:
    """Parse agent statistics from copilot CLI output.
    
    Args:
        output: The output text from copilot CLI
        
    Returns:
        AgentStats object with parsed values, or None if parsing fails
    """
    if not output:
        return None
    
    stats = AgentStats()
    
    try:
        # Parse durations
        if match := re.search(r'Total duration \(wall\):\s*([\d.]+)s', output):
            stats.wall_duration = float(match.group(1))
        if match := re.search(r'Total duration \(API\):\s*([\d.]+)s', output):
            stats.api_duration = float(match.group(1))
        
        # Parse code changes
        if match := re.search(r'Total code changes:\s*(\d+) lines added,\s*(\d+) lines removed', output):
            stats.lines_added = int(match.group(1))
            stats.lines_removed = int(match.group(2))
        
        # Parse tokens - look for input and output
        if match := re.search(r'(\d+\.?\d*)k?\s+input', output, re.IGNORECASE):
            value = match.group(1).replace('k', '')
            stats.input_tokens = int(float(value) * 1000 if 'k' in match.group(0).lower() else float(value))
        if match := re.search(r'(\d+\.?\d*)k?\s+output', output, re.IGNORECASE):
            value = match.group(1).replace('k', '')
            stats.output_tokens = int(float(value) * 1000 if 'k' in match.group(0).lower() else float(value))
        
        # Parse premium requests
        if match := re.search(r'Est\.\s*(\d+)\s+Premium request', output, re.IGNORECASE):
            stats.premium_requests = int(match.group(1))
        elif match := re.search(r'Total usage est:\s*(\d+)\s+Premium request', output, re.IGNORECASE):
            stats.premium_requests = int(match.group(1))
        
        return stats
    except (ValueError, AttributeError) as e:
        print(f"⚠️  Warning: Failed to parse agent stats: {e}")
        return None

from pokepoke.worktrees import (
    create_worktree,
    merge_worktree,
    cleanup_worktree,
    get_main_repo_root
)


def check_main_repo_ready_for_merge() -> tuple[bool, str]:
    """Check if main repo is ready for worktree merge.
    
    Returns:
        (is_ready, error_message) tuple
    """
    try:
        # Check for uncommitted changes
        status_result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            check=True
        )
        
        uncommitted = status_result.stdout.strip()
        if uncommitted:
            # Check if it's just beads files
            lines = uncommitted.split('\n')
            non_beads_changes = [line for line in lines if line and '.beads/' not in line]
            
            if non_beads_changes:
                return False, f"Main repo has uncommitted non-beads changes:\n{chr(10).join(non_beads_changes)}"
            else:
                # Just beads changes - try to commit them
                print("🔧 Committing beads database changes in main repo...")
                subprocess.run(["git", "add", ".beads/"], check=True)
                subprocess.run(
                    ["git", "commit", "-m", "chore: sync beads before worktree merge"],
                    check=True,
                    capture_output=True
                )
                print("✅ Beads changes committed")
        
        return True, ""
    except Exception as e:
        return False, f"Error checking main repo status: {e}"


def has_uncommitted_changes() -> bool:
    """Check if there are any uncommitted changes in the current directory.
    
    Returns:
        True if there are uncommitted changes, False otherwise
    """
    try:
        # Check git status
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            check=True
        )
        # If output is non-empty, there are uncommitted changes
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
        # Stage all changes
        subprocess.run(
            ["git", "add", "-A"],
            check=True,
            capture_output=True,
            text=True
        )
        
        # Try to commit (this will trigger pre-commit hooks)
        result = subprocess.run(
            ["git", "commit", "-m", message],
            capture_output=True,
            text=True
        )
        
        if result.returncode == 0:
            return True, ""
        else:
            # Extract error details from stderr
            error_lines = result.stderr.strip().split('\n') if result.stderr else []
            if error_lines:
                # Get meaningful error lines (skip hints)
                errors = [line for line in error_lines if line.strip() and not line.startswith('hint:')][:5]
                return False, '\n   '.join(errors) if errors else "Commit failed"
            return False, "Commit failed (unknown reason)"
    except subprocess.CalledProcessError as e:
        return False, f"Commit error: {e.stderr if e.stderr else str(e)}"


def invoke_cleanup_agent(item: BeadsWorkItem, repo_root: Path) -> bool:
    """Invoke cleanup agent to commit uncommitted changes.
    
    Args:
        item: The work item being processed
        repo_root: Path to the main repository root
        
    Returns:
        True if cleanup succeeded, False otherwise
    """
    # Read cleanup prompt from main repo (not worktree)
    cleanup_prompt_path = repo_root / ".pokepoke" / "prompts" / "cleanup.md"
    if not cleanup_prompt_path.exists():
        print(f"❌ Cleanup prompt not found at {cleanup_prompt_path}")
        return False
    
    cleanup_prompt_template = cleanup_prompt_path.read_text()
    
    # Build context about the work item being cleaned up
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
    
    # Combine work item context with cleanup instructions
    cleanup_prompt = f"{work_item_context}\n\n---\n\n{cleanup_prompt_template}"
    
    # Create a synthetic work item for cleanup
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
    
    return result.success


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
    
    # Use provided repo_root or default to current directory
    if repo_root is None:
        repo_root = Path.cwd()
    
    # Read agent prompt from main repo (not worktree)
    prompt_path = repo_root / ".pokepoke" / "prompts" / prompt_file
    if not prompt_path.exists():
        print(f"❌ Prompt not found at {prompt_path}")
        return None
    
    agent_prompt = prompt_path.read_text()
    
    # Create synthetic work item for agent
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
        print(f"\n📋 Running {agent_name} in main repository (beads-only)")
        print(f"   File write access: DENIED")
        
        # Invoke agent with file write tools denied
        result = invoke_copilot_cli(agent_item, prompt=agent_prompt, deny_write=True)
        
        # No cleanup needed for beads-only agents (bd handles its own sync)
        if result.success:
            print(f"\n✅ {agent_name} agent completed successfully")
            return parse_agent_stats(result.output) if result.output else None
        else:
            print(f"\n❌ {agent_name} agent failed: {result.error}")
            return None
    
    # Code-modifying agents need worktree isolation
    print(f"\n🌳 Creating worktree for {agent_id}...")
    try:
        worktree_path = create_worktree(agent_id)
        print(f"   Created at: {worktree_path}")
    except Exception as e:
        print(f"\n❌ Failed to create worktree: {e}")
        return None
    
    # Save current directory and change to worktree
    original_dir = os.getcwd()
    try:
        os.chdir(worktree_path)
        print(f"   Switched to worktree directory\n")
        
        # Invoke agent
        result = invoke_copilot_cli(agent_item, prompt=agent_prompt)
        
        # Cleanup loop: commit changes and fix any validation failures
        cleanup_attempt = 0
        
        while result.success and has_uncommitted_changes():
            cleanup_attempt += 1
            print(f"\n⚠️  Uncommitted changes detected (cleanup attempt {cleanup_attempt})")
            
            # Try to commit all changes (this triggers pre-commit hooks)
            commit_success, commit_error = commit_all_changes(f"{agent_name} maintenance")
            
            if commit_success:
                print("✅ Changes committed successfully (validation passed)")
                break
            else:
                print(f"\n❌ Commit failed - validation errors:")
                print(f"   {commit_error}")
            
            # Invoke cleanup agent
            print("\n🧹 Invoking cleanup agent to fix validation errors...")
            cleanup_success = invoke_cleanup_agent(agent_item, repo_root)
            if not cleanup_success:
                print("\n❌ Cleanup agent failed")
                result.success = False
                result.error = "Cleanup agent failed to fix issues"
                break
            if not cleanup_success:
                print("\n❌ Cleanup agent failed")
                result.success = False
                result.error = "Cleanup agent failed to fix issues"
                break
    
    finally:
        # Always return to original directory
        os.chdir(original_dir)
    
    if result.success:
        print(f"\n✅ {agent_name} agent completed successfully!")
        print("   All changes committed and validated")
        
        # Parse statistics from output
        agent_stats = parse_agent_stats(result.output) if result.output else None
        
        # Check if main repo is ready for merge
        print(f"\n🔍 Checking if main repo is ready for merge...")
        is_ready, error_msg = check_main_repo_ready_for_merge()
        
        if not is_ready:
            print(f"\n⚠️  Cannot merge: {error_msg}")
            print(f"   Worktree preserved at worktrees/task-{agent_id} for manual intervention")
            print(f"   To merge later: cd worktrees/task-{agent_id} && git push && cd ../.. && git merge task/{agent_id}")
            return None
        
        # Merge worktree back to master
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
    
    # Display all items
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
        # Prompt user to select
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
    else:
        # Autonomous mode: use hierarchical selection
        selected = select_next_hierarchical_item(ready_items)
        if selected:
            print(f"🤖 Hierarchically selected item: {selected.id}")
            print(f"   Type: {selected.issue_type} | Priority: {selected.priority}")
        return selected


def process_work_item(item: BeadsWorkItem, interactive: bool, timeout_hours: float = 2.0, run_cleanup_agents: bool = False) -> tuple[bool, int, Optional[AgentStats]]:
    """Process a single work item with timeout protection.
    
    Args:
        item: Work item to process
        interactive: If True, prompt for confirmation before proceeding
        timeout_hours: Maximum hours before timing out and restarting (default: 2.0)
        run_cleanup_agents: If True, run maintenance agents after completion (default: False)
        
    Returns:
        Tuple of (success: bool, request_count: int, stats: Optional[AgentStats])
    """
    start_time = time.time()
    timeout_seconds = timeout_hours * 3600
    request_count = 0
    
    print(f"\n🚀 Processing work item: {item.id}")
    print(f"   {item.title}")
    print(f"   ⏱️  Timeout: {timeout_hours} hours\n")
    
    if interactive:
        confirm = input("Proceed with this item? [Y/n]: ").strip().lower()
        if confirm and confirm != 'y':
            print("⏭️  Skipped.")
            return False, 0, None  # Skipped, no requests made, no stats
    
    # PokePoke repo root (where prompts are stored) - absolute path
    pokepoke_root = Path(r"C:\Users\ameliapayne\PokePoke")
    original_dir = os.getcwd()
    
    # Create worktree for isolated execution
    print(f"\n🌳 Creating worktree for {item.id}...")
    try:
        worktree_path = create_worktree(item.id)
        print(f"   Created at: {worktree_path}")
    except Exception as e:
        print(f"\n❌ Failed to create worktree: {e}")
        return False, 0, None  # Failed before any requests, no stats
    
    try:
        os.chdir(worktree_path)
        print(f"   Switched to worktree directory\n")
        
        # Check timeout before invoking Copilot
        elapsed = time.time() - start_time
        if elapsed >= timeout_seconds:
            print(f"\n⏱️  TIMEOUT: Execution exceeded {timeout_hours} hours")
            print(f"   Restarting item {item.id} in same worktree...\n")
            os.chdir(original_dir)
            return process_work_item(item, interactive, timeout_hours)  # Recursive restart
        
        # Invoke Copilot CLI for the item with remaining timeout
        remaining_timeout = timeout_seconds - elapsed
        result = invoke_copilot_cli(item, timeout=remaining_timeout)
        request_count += result.attempt_count
        
        # Check if any work was actually done
        if result.success and not has_uncommitted_changes():
            print("\n✅ No changes made - work item may already be complete")
            print("   Skipping cleanup and commit steps")
        
        # Cleanup loop: commit changes and fix any validation failures
        cleanup_attempt = 0
        
        while result.success and has_uncommitted_changes():
            # Check timeout before cleanup attempt
            elapsed = time.time() - start_time
            if elapsed >= timeout_seconds:
                print(f"\n⏱️  TIMEOUT: Execution exceeded {timeout_hours} hours during cleanup")
                print(f"   Restarting item {item.id} in same worktree...\n")
                os.chdir(original_dir)
                return process_work_item(item, interactive, timeout_hours)  # Recursive restart
            
            cleanup_attempt += 1
            print(f"\n⚠️  Uncommitted changes detected (cleanup attempt {cleanup_attempt})")
            
            # Try to commit all changes (this triggers pre-commit hooks)
            commit_success, commit_error = commit_all_changes(f"Work on {item.id}")
            
            if commit_success:
                print("✅ Changes committed successfully (validation passed)")
                break
            else:
                print(f"\n❌ Commit failed - validation errors:")
                print(f"   {commit_error}")
            
            # Invoke cleanup agent (pass pokepoke_root for prompt access)
            print("\n🧹 Invoking cleanup agent to fix validation errors...")
            cleanup_success = invoke_cleanup_agent(item, pokepoke_root)
            if not cleanup_success:
                print("\n❌ Cleanup agent failed")
                result.success = False
                result.error = "Cleanup agent failed to fix issues"
                break
    
    finally:
        # Always return to original directory
        os.chdir(original_dir)
    
    if result.success:
        print("\n✅ Successfully completed work item!")
        print("   All changes committed and validated")
        # Output already streamed during invocation
        
        # Check if worktree has any commits (not just the base branch)
        try:
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
            else:
                # Check if main repo is ready for merge
                print(f"\n🔍 Checking if main repo is ready for merge...")
                is_ready, error_msg = check_main_repo_ready_for_merge()
                
                if not is_ready:
                    print(f"\n⚠️  Cannot merge: {error_msg}")
                    print(f"   Worktree preserved at worktrees/task-{item.id} for manual intervention")
                    print(f"   To merge later: cd worktrees/task-{item.id} && git push && cd ../.. && git merge task/{item.id}")
                    return False, request_count, None
                
                # Merge worktree back to master
                print(f"\n🔀 Merging worktree for {item.id}...")
                merge_success = merge_worktree(item.id, cleanup=True)
                
                if not merge_success:
                    print(f"\n❌ Worktree merge failed!")
                    print(f"   Worktree preserved at worktrees/task-{item.id} for manual intervention")
                    print(f"   Check 'git status' in main repo and worktree, resolve conflicts, then merge manually")
                    return False, request_count, None  # Failed but requests were made
                
                print("   Merged and cleaned up worktree")
        except Exception as e:
            os.chdir(original_dir)
            print(f"\n⚠️  Could not check commit count: {e}")
            print(f"   Attempting merge anyway...")
            
            # Check if main repo is ready for merge
            is_ready, error_msg = check_main_repo_ready_for_merge()
            if not is_ready:
                print(f"\n⚠️  Cannot merge: {error_msg}")
                print(f"   Worktree preserved at worktrees/task-{item.id} for manual intervention")
                return False, request_count, None
            
            merge_success = merge_worktree(item.id, cleanup=True)
            if not merge_success:
                print(f"\n❌ Worktree merge failed!")
                print(f"   Worktree preserved at worktrees/task-{item.id} for manual intervention")
                return False, request_count, None
        
        # Close the completed item
        close_item(item.id, "Completed by PokePoke orchestrator")
        
        # Check if this item has a parent and close parent if all children complete
        parent_id = get_parent_id(item.id)
        if parent_id:
            print(f"\n🔍 Checking parent {parent_id} completion status...")
            close_parent_if_complete(parent_id)
            
            # Check grandparent if parent was closed
            grandparent_id = get_parent_id(parent_id)
            if grandparent_id:
                print(f"\n🔍 Checking grandparent {grandparent_id} completion status...")
                close_parent_if_complete(grandparent_id)
        
        # Parse statistics from output
        item_stats = parse_agent_stats(result.output) if result.output else None
        
        # Cleanup agents now run on 5-item periodic schedule
        
        return True, request_count, item_stats
    else:
        print(f"\n❌ Failed to complete work item: {result.error}")
        print(f"\n🧹 Cleaning up worktree...")
        cleanup_worktree(item.id, force=True)
        return False, request_count, None


def print_stats(items_completed: int, total_requests: int, elapsed_seconds: float, session_stats: Optional[AgentStats] = None) -> None:
    """Print session statistics.
    
    Args:
        items_completed: Number of work items completed
        total_requests: Total number of Copilot CLI requests (including retries)
        elapsed_seconds: Total elapsed time in seconds
        session_stats: Aggregated statistics from all agents
    """
    print("\n" + "=" * 60)
    print("📊 Session Statistics")
    print("=" * 60)
    print(f"✅ Items completed:     {items_completed}")
    print(f"🔄 Total API requests:  {total_requests}")
    
    # Format elapsed time
    hours = int(elapsed_seconds // 3600)
    minutes = int((elapsed_seconds % 3600) // 60)
    seconds = int(elapsed_seconds % 60)
    
    if hours > 0:
        time_str = f"{hours}h {minutes}m {seconds}s"
    elif minutes > 0:
        time_str = f"{minutes}m {seconds}s"
    else:
        time_str = f"{seconds}s"
    
    print(f"⏱️  Total time:         {time_str}")
    
    # Print agent statistics if available
    if session_stats:
        print("\n" + "=" * 60)
        print("🤖 Agent Usage Statistics")
        print("=" * 60)
        print(f"⏱️  Wall duration:      {session_stats.wall_duration:.1f}s")
        print(f"⚡ API duration:       {session_stats.api_duration:.1f}s")
        print(f"📊 Input tokens:       {session_stats.input_tokens:,}")
        print(f"📤 Output tokens:      {session_stats.output_tokens:,}")
        print(f"➕ Lines added:        {session_stats.lines_added:,}")
        print(f"➖ Lines removed:      {session_stats.lines_removed:,}")
        if session_stats.premium_requests > 0:
            print(f"💎 Premium requests:   {session_stats.premium_requests}")
    
    # Calculate average time per item if any completed
    if items_completed > 0:
        avg_seconds = elapsed_seconds / items_completed
        avg_minutes = int(avg_seconds // 60)
        avg_secs = int(avg_seconds % 60)
        if avg_minutes > 0:
            avg_str = f"{avg_minutes}m {avg_secs}s"
        else:
            avg_str = f"{avg_secs}s"
        print(f"📈 Avg time per item:  {avg_str}")
    
    print("=" * 60)


def run_orchestrator(interactive: bool = True, continuous: bool = False) -> int:
    """Main orchestrator loop.
    
    Args:
        interactive: If True, prompt for user input at decision points
        continuous: If True, loop continuously; if False, process one item and exit
        
    Returns:
        Exit code (0 for success, 1 for failure)
    """
    mode_name = "Interactive" if interactive else "Autonomous"
    print(f"🎯 PokePoke {mode_name} Mode")
    print("=" * 50)
    
    # Maintenance agent frequency configuration (run every N completed items)
    TECH_DEBT_FREQUENCY = 10  # Run tech debt agent every 10 items
    JANITOR_FREQUENCY = 3    # Run janitor agent every 3 items
    BACKLOG_FREQUENCY = 5    # Run backlog cleanup agent every 1 item
    
    # Track statistics
    start_time = time.time()
    items_completed = 0
    total_requests = 0
    session_stats = AgentStats()
    
    try:
        while True:
            # CRITICAL: Check main repo for uncommitted changes BEFORE processing any work items
            print("\n🔍 Checking main repository status...")
            status_result = subprocess.run(
                ["git", "status", "--porcelain"],
                capture_output=True,
                text=True,
                check=True
            )
            
            uncommitted = status_result.stdout.strip()
            if uncommitted:
                # Check if it's just beads files
                lines = uncommitted.split('\n')
                non_beads_changes = [line for line in lines if line and '.beads/' not in line]
                
                if non_beads_changes:
                    print(f"\n⚠️  Main repository has uncommitted changes:")
                    for line in non_beads_changes[:10]:
                        print(f"   {line}")
                    if len(non_beads_changes) > 10:
                        print(f"   ... and {len(non_beads_changes) - 10} more")
                    
                    print("\n❌ Please commit or stash these changes before running PokePoke.")
                    print("   Worktree operations require a clean working directory.")
                    return 1
                elif '.beads/' in uncommitted:
                    # Just beads changes - commit them automatically
                    print("🔧 Committing beads database changes...")
                    subprocess.run(["git", "add", ".beads/"], check=True)
                    subprocess.run(
                        ["git", "commit", "-m", "chore: auto-commit beads changes"],
                        check=True,
                        capture_output=True
                    )
                    print("✅ Beads changes committed")
            
            print("\nFetching ready work from beads...")
            ready_items = get_ready_work_items()
            
            # Select work item
            selected_item = select_work_item(ready_items, interactive)
            
            if selected_item is None:
                print("\n👋 Exiting PokePoke.")
                return 0
            
            # Process the selected item
            success, requests, item_stats = process_work_item(selected_item, interactive)
            total_requests += requests
            
            # Aggregate item statistics
            if item_stats:
                session_stats.wall_duration += item_stats.wall_duration
                session_stats.api_duration += item_stats.api_duration
                session_stats.input_tokens += item_stats.input_tokens
                session_stats.output_tokens += item_stats.output_tokens
                session_stats.lines_added += item_stats.lines_added
                session_stats.lines_removed += item_stats.lines_removed
                session_stats.premium_requests += item_stats.premium_requests
            
            # Increment counter on successful processing
            if success:
                items_completed += 1
                print(f"\n📈 Items completed this session: {items_completed}")
                
                # Use absolute path to PokePoke repo for prompts
                pokepoke_repo = Path(r"C:\Users\ameliapayne\PokePoke")
                
                # Run Tech Debt Agent based on frequency
                if items_completed % TECH_DEBT_FREQUENCY == 0:
                    print("\n📊 Running Tech Debt Agent...")
                    tech_stats = run_maintenance_agent("Tech Debt", "tech-debt.md", repo_root=pokepoke_repo, needs_worktree=False)
                    if tech_stats:
                        session_stats.wall_duration += tech_stats.wall_duration
                        session_stats.api_duration += tech_stats.api_duration
                        session_stats.input_tokens += tech_stats.input_tokens
                        session_stats.output_tokens += tech_stats.output_tokens
                        session_stats.lines_added += tech_stats.lines_added
                        session_stats.lines_removed += tech_stats.lines_removed
                        session_stats.premium_requests += tech_stats.premium_requests
                
                # Run Janitor Agent based on frequency
                if items_completed % JANITOR_FREQUENCY == 0:
                    print("\n🧹 Running Janitor Agent...")
                    janitor_stats = run_maintenance_agent("Janitor", "janitor.md", repo_root=pokepoke_repo, needs_worktree=True)
                    if janitor_stats:
                        session_stats.wall_duration += janitor_stats.wall_duration
                        session_stats.api_duration += janitor_stats.api_duration
                        session_stats.input_tokens += janitor_stats.input_tokens
                        session_stats.output_tokens += janitor_stats.output_tokens
                        session_stats.lines_added += janitor_stats.lines_added
                        session_stats.lines_removed += janitor_stats.lines_removed
                        session_stats.premium_requests += janitor_stats.premium_requests
                
                # Run Backlog Cleanup Agent based on frequency
                if items_completed % BACKLOG_FREQUENCY == 0:
                    print("\n🗑️ Running Backlog Cleanup Agent...")
                    backlog_stats = run_maintenance_agent("Backlog Cleanup", "backlog-cleanup.md", repo_root=pokepoke_repo, needs_worktree=False)
                    if backlog_stats:
                        session_stats.wall_duration += backlog_stats.wall_duration
                        session_stats.api_duration += backlog_stats.api_duration
                        session_stats.input_tokens += backlog_stats.input_tokens
                        session_stats.output_tokens += backlog_stats.output_tokens
                        session_stats.lines_added += backlog_stats.lines_added
                        session_stats.lines_removed += backlog_stats.lines_removed
                        session_stats.premium_requests += backlog_stats.premium_requests
            
            # Decide whether to continue
            if not continuous:
                # Single-shot mode - show stats
                elapsed = time.time() - start_time
                print_stats(items_completed, total_requests, elapsed, session_stats)
                return 0 if success else 1
            
            if interactive:
                # Ask if user wants to continue
                cont = input("\nProcess another item? [Y/n]: ").strip().lower()
                if cont and cont != 'y':
                    elapsed = time.time() - start_time
                    print("\n👋 Exiting PokePoke.")
                    print_stats(items_completed, total_requests, elapsed, session_stats)
                    return 0
            else:
                # Autonomous mode: brief pause before next iteration
                print("\n⏳ Waiting 5 seconds before next iteration...")
                time.sleep(5)
    
    except KeyboardInterrupt:
        elapsed = time.time() - start_time
        print("\n\n👋 Interrupted. Exiting PokePoke.")
        print_stats(items_completed, total_requests, elapsed, session_stats)
        return 0
    except Exception as e:
        elapsed = time.time() - start_time
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        print_stats(items_completed, total_requests, elapsed, session_stats)
        return 1


def main() -> int:
    """Main entry point for PokePoke CLI.
    
    Returns:
        Exit code (0 for success, 1 for failure)
    """
    parser = argparse.ArgumentParser(
        description="PokePoke - Autonomous Beads + Copilot CLI Orchestrator"
    )
    parser.add_argument(
        "--interactive",
        action="store_true",
        default=True,
        help="Interactive mode: prompt for user input (default)",
    )
    parser.add_argument(
        "--autonomous",
        action="store_true",
        help="Autonomous mode: automatic decision making",
    )
    parser.add_argument(
        "--continuous",
        action="store_true",
        help="Continuous mode: loop through multiple items instead of single-shot",
    )
    
    args = parser.parse_args()
    
    # Autonomous flag overrides interactive
    interactive = not args.autonomous
    
    return run_orchestrator(interactive=interactive, continuous=args.continuous)


if __name__ == "__main__":
    sys.exit(main())
