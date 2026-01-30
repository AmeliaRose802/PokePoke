"""Workflow management for work item selection and processing."""

import os
import time
from pathlib import Path
from typing import Optional, TYPE_CHECKING

from pokepoke.copilot import invoke_copilot
from pokepoke.types import BeadsWorkItem, AgentStats, CopilotResult
from pokepoke.worktrees import create_worktree, cleanup_worktree
from pokepoke.git_operations import has_uncommitted_changes
from pokepoke.beads import assign_and_sync_item, add_comment
from pokepoke.agent_runner import run_cleanup_loop, run_beta_tester, run_gate_agent
from pokepoke.worktree_finalization import finalize_work_item
from pokepoke.work_item_selection import select_work_item
from pokepoke.stats import parse_agent_stats
from pokepoke.terminal_ui import set_terminal_banner, format_work_item_banner, ui

if TYPE_CHECKING:
    from pokepoke.logging_utils import RunLogger


def process_work_item(
    item: BeadsWorkItem, 
    interactive: bool, 
    timeout_hours: float = 2.0, 
    run_cleanup_agents: bool = False, 
    run_beta_test: bool = True,
    run_logger: Optional['RunLogger'] = None
) -> tuple[bool, int, Optional[AgentStats], int]:
    """Process a single work item with timeout protection.
    
    Args:
        item: Work item to process
        interactive: If True, prompt for confirmation before proceeding
        timeout_hours: Maximum hours before timing out and restarting (default: 2.0)
        run_cleanup_agents: If True, run maintenance agents after completion (default: False)
        run_beta_test: If True, run beta tester after completion (default: True)
        run_logger: Optional run logger instance for file logging
        
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
    
    # Start item logging
    item_logger = None
    if run_logger:
        item_logger = run_logger.start_item_log(item.id, item.title)
    
    if interactive:
        ui.stop()
        confirm = input("Proceed with this item? [Y/n]: ").strip().lower()
        ui.start()
        if confirm and confirm != 'y':
            print("⏭️  Skipped.")
            if run_logger:
                run_logger.end_item_log(False, 0)
            return False, 0, None, 0
    
    # Assign and sync BEFORE creating worktree to prevent parallel conflicts
    print(f"\n🔒 Claiming work item...")
    if not assign_and_sync_item(item.id):
        print(f"❌ Failed to assign work item {item.id}")
        if run_logger:
            run_logger.end_item_log(False, 0)
        return False, 0, None, 0
    
    # Use current working directory as repo root
    pokepoke_root = Path.cwd()
    worktree_path = _setup_worktree(item)
    
    if worktree_path is None:
        if run_logger:
            run_logger.end_item_log(False, 0)
        return False, 0, None, 0
    
    original_dir = os.getcwd()
    
    try:
        os.chdir(worktree_path)
        print(f"   Switched to worktree directory\n")
        
        last_feedback = ""
        # Initialize accumulated stats
        accumulated_stats = AgentStats()
        
        while True:
            # Check timeout before invoking Copilot
            elapsed = time.time() - start_time
            if elapsed >= timeout_seconds:
                print(f"\n⏱️  TIMEOUT: Execution exceeded {timeout_hours} hours")
                print(f"   Restarting item {item.id} in same worktree...\n")
                os.chdir(original_dir)
                return process_work_item(item, interactive, timeout_hours, run_cleanup_agents, run_beta_test, run_logger)
            
            remaining_timeout = timeout_seconds - elapsed
            
            # Append feedback if retrying
            if last_feedback:
                 print(f"\n🔄 Restarting Work Agent with feedback...")
                 current_desc = item.description or ""
                 if "**PREVIOUS GATE AGENT FEEDBACK:**" not in current_desc:
                     current_desc += "\n\n**PREVIOUS GATE AGENT FEEDBACK:**\n"
                 current_desc += f"\n- {last_feedback}"
                 item.description = current_desc

            ui.set_current_agent("Work Agent")
            result = invoke_copilot(item, timeout=remaining_timeout, item_logger=item_logger)
            request_count += result.attempt_count
            
            # Aggregate stats
            current_stats = result.stats if result.stats else (parse_agent_stats(result.output) if result.output else None)
            if current_stats:
                accumulated_stats.wall_duration += current_stats.wall_duration
                accumulated_stats.api_duration += current_stats.api_duration
                accumulated_stats.input_tokens += current_stats.input_tokens
                accumulated_stats.output_tokens += current_stats.output_tokens
                accumulated_stats.lines_added += current_stats.lines_added
                accumulated_stats.lines_removed += current_stats.lines_removed
                accumulated_stats.premium_requests += current_stats.premium_requests
                accumulated_stats.tool_calls += current_stats.tool_calls
                accumulated_stats.retries += current_stats.retries
                accumulated_stats.estimated_cost += current_stats.estimated_cost

            # If work agent failed, break
            if not result.success:
                break
            
            if not has_uncommitted_changes():
                print("\n✅ No changes made - work item may already be complete")
                print("   Skipping cleanup and commit steps")
            
            # Run cleanup loop with timeout checking
            cleanup_success, cleanup_runs = _run_cleanup_with_timeout(
                item, result, pokepoke_root, start_time, timeout_seconds, timeout_hours
            )
            cleanup_agent_runs += cleanup_runs
            
            if not cleanup_success:
                # Cleanup failed (e.g. timeout), consider item failed or retry?
                # For now, if cleanup fails, we fail the cycle.
                result.success = False
                os.chdir(original_dir)
                if run_logger:
                    run_logger.end_item_log(False, request_count)
                return False, request_count, accumulated_stats, cleanup_agent_runs

            # --- GATE AGENT CHECK ---
            gate_success, gate_reason, gate_stats = run_gate_agent(item)
            if gate_stats:
                accumulated_stats.wall_duration += gate_stats.wall_duration
                accumulated_stats.api_duration += gate_stats.api_duration
                accumulated_stats.input_tokens += gate_stats.input_tokens
                accumulated_stats.output_tokens += gate_stats.output_tokens
                accumulated_stats.premium_requests += gate_stats.premium_requests
                accumulated_stats.tool_calls += gate_stats.tool_calls
                accumulated_stats.estimated_cost += gate_stats.estimated_cost
            
            if gate_success:
                print("\n✅ Gate Agent signed off!")
                break
            else:
                print(f"\n❌ Gate Agent rejected fix: {gate_reason}")
                add_comment(item.id, f"Gate Agent Rejection:\n{gate_reason}")
                last_feedback = gate_reason
                # Loop continues...
    
    finally:
        os.chdir(original_dir)
    
    if result.success:
        set_terminal_banner(format_work_item_banner(item.id, item.title, "Finalizing"))
        success = finalize_work_item(item, worktree_path)
        # Use accumulated stats
        item_stats = accumulated_stats
        
        # Update banner based on finalization result
        if success:
            set_terminal_banner(format_work_item_banner(item.id, item.title, "Completed"))
        else:
            set_terminal_banner(format_work_item_banner(item.id, item.title, "Failed"))
        
        # Run beta tester after successful completion
        if success and run_beta_test:
            set_terminal_banner(format_work_item_banner(item.id, item.title, "Beta Testing"))
            beta_stats = run_beta_tester()
            if beta_stats and item_stats:
                # Aggregate beta tester stats
                item_stats.wall_duration += beta_stats.wall_duration
                item_stats.api_duration += beta_stats.api_duration
                item_stats.input_tokens += beta_stats.input_tokens
                item_stats.output_tokens += beta_stats.output_tokens
                item_stats.premium_requests += beta_stats.premium_requests
            set_terminal_banner(format_work_item_banner(item.id, item.title, "Completed"))
        
        if run_logger:
            run_logger.end_item_log(success, request_count)
        
        ui.set_current_agent(None)
        return success, request_count, item_stats, cleanup_agent_runs
    else:
        set_terminal_banner(format_work_item_banner(item.id, item.title, "Failed"))
        print(f"\n❌ Failed to complete work item: {result.error}")
        print(f"\n🧹 Cleaning up worktree...")
        cleanup_worktree(item.id, force=True)
        
        if run_logger:
            run_logger.end_item_log(False, request_count)
        
        ui.set_current_agent(None)
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
        set_terminal_banner(format_work_item_banner(item.id, item.title, f"Cleanup #{cleanup_attempt}"))
        cleanup_success, cleanup_runs = run_cleanup_loop(item, result, repo_root)
        cleanup_agent_runs += cleanup_runs
        
        if not cleanup_success:
            break
    
    return result.success, cleanup_agent_runs
