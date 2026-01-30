"""PokePoke Orchestrator - Main entry point for autonomous and interactive modes."""

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

from pokepoke.beads import get_ready_work_items, get_beads_stats
from pokepoke.types import AgentStats, SessionStats
from pokepoke.stats import print_stats
from pokepoke.workflow import process_work_item
from pokepoke.work_item_selection import select_work_item
from pokepoke.agent_runner import run_maintenance_agent
from pokepoke.logging_utils import RunLogger
from pokepoke.agent_names import initialize_agent_name
from pokepoke.terminal_ui import set_terminal_banner, format_work_item_banner, clear_terminal_banner, ui
from pokepoke.maintenance_state import increment_items_completed
from pokepoke.repo_check import check_and_commit_main_repo


def run_orchestrator(interactive: bool = True, continuous: bool = False, run_beta_first: bool = False) -> int:
    """Main orchestrator loop.
    
    Args:
        interactive: If True, prompt for user input at decision points
        continuous: If True, loop continuously; if False, process one item and exit
        run_beta_first: If True, run beta tester at startup before processing work items
        
    Returns:
        Exit code (0 for success, 1 for failure)
    """
    # Start UI immediately to capture startup logs
    ui.start()
    ui.update_header("PokePoke", f"Initializing {interactive and 'Interactive' or 'Autonomous'} Mode...")

    try:
        # TELLTALE: Version identifier to verify correct code is running
        print("🔷 PokePoke MASTER-MERGED-v2 (2026-01-25 post-worktree-fix)")
        print("=" * 50)
        
        # Initialize unique agent name for this run
        agent_name = initialize_agent_name()
        os.environ['AGENT_NAME'] = agent_name
        
        mode_name = "Interactive" if interactive else "Autonomous"
        print(f"🎯 PokePoke {mode_name} Mode | 🤖 Agent: {agent_name}")
        print("=" * 50)
        set_terminal_banner(f"PokePoke {mode_name} - {agent_name}")
        ui.update_header("PokePoke", f"{mode_name} Mode", agent_name)
        
        # Initialize run logger
        run_logger = RunLogger()
        run_id = run_logger.get_run_id()
        print(f"📝 Run ID: {run_id} | 📁 Logs: {run_logger.get_run_dir()}")
        run_logger.log_orchestrator(f"PokePoke started in {mode_name} mode with agent name: {agent_name}")
        
        # Use the current working directory
        main_repo_path = Path.cwd()
        print(f"📁 Repository: {main_repo_path}")
        run_logger.log_orchestrator(f"Repository: {main_repo_path}")
        
        # Track statistics
        start_time = time.time()
        items_completed = 0
        total_requests = 0
        session_stats = SessionStats(agent_stats=AgentStats())
        print("📊 Recording starting beads statistics...")
        run_logger.log_orchestrator("Recording starting beads statistics")
        session_stats.starting_beads_stats = get_beads_stats()
        
        # Initial stats display with 0 elapsed time (or very small)
        ui.update_stats(session_stats, time.time() - start_time)
        
        # Run beta tester first if requested
        if run_beta_first:
            print("\n🧪 Running Beta Tester at startup...")
            run_logger.log_orchestrator("Running Beta Tester at startup")
            from pokepoke.agent_runner import run_beta_tester
            beta_stats = run_beta_tester(repo_root=main_repo_path)
            if beta_stats:
                # Aggregate beta tester stats
                session_stats.agent_stats.wall_duration += beta_stats.wall_duration
                session_stats.agent_stats.api_duration += beta_stats.api_duration
                session_stats.agent_stats.input_tokens += beta_stats.input_tokens
                session_stats.agent_stats.output_tokens += beta_stats.output_tokens
                session_stats.agent_stats.premium_requests += beta_stats.premium_requests
            print("✅ Beta Tester completed\n")
            
        while True:
            # Check main repo status before processing
            print("\n🔍 Checking main repository status...")
            run_logger.log_orchestrator("Checking main repository status")
            if not check_and_commit_main_repo(main_repo_path, run_logger):
                run_logger.log_orchestrator("Main repo check failed", level="ERROR")
                return 1
            print("\nFetching ready work from beads...")
            run_logger.log_orchestrator("Fetching ready work from beads")
            ready_items = get_ready_work_items()
            
            # Pause UI for interactive selection
            if interactive:
                ui.stop()
            selected_item = select_work_item(ready_items, interactive)
            if interactive:
                ui.start()
            
            if selected_item is None:
                ui.stop()
                # Get ending stats and print session stats before exiting
                session_stats.ending_beads_stats = get_beads_stats()
                elapsed = time.time() - start_time
                print("\n👋 Exiting PokePoke - no work items available.")
                run_logger.log_orchestrator("No work items available - exiting")
                print_stats(items_completed, total_requests, elapsed, session_stats)
                run_logger.finalize(items_completed, total_requests, elapsed)
                print(f"\n📝 Run ID: {run_id}")
                print(f"📁 Logs saved to: {run_logger.get_run_dir()}")
                clear_terminal_banner()
                return 0
            
            # Process the selected item
            run_logger.log_orchestrator(f"Selected item: {selected_item.id} - {selected_item.title}")
            
            # Update terminal banner and UI header
            banner = format_work_item_banner(selected_item.id, selected_item.title)
            set_terminal_banner(banner)
            ui.update_header(selected_item.id, selected_item.title)
            
            success, requests, item_stats, cleanup_runs = process_work_item(
                selected_item, interactive, run_logger=run_logger
            )
            total_requests += requests
            if requests > 1:
                session_stats.agent_stats.retries += (requests - 1)
            
            session_stats.work_agent_runs += 1
            session_stats.cleanup_agent_runs += cleanup_runs
            
            # Aggregate statistics
            if item_stats:
                _aggregate_stats(session_stats, item_stats)
            
            # Increment counter on successful processing
            if success:
                items_completed += 1
                session_stats.items_completed = items_completed
                session_stats.completed_items_list.append(selected_item)
                total_persistent_count = increment_items_completed()
                print(f"\n📈 Items completed this session: {items_completed}")
                print(f"📈 Total items completed (lifetime): {total_persistent_count}")
                run_logger.log_orchestrator(f"Items completed this session: {items_completed}")
                
                _run_periodic_maintenance(total_persistent_count, session_stats, run_logger)

            # Update UI stats with current runtime
            ui.update_stats(session_stats, time.time() - start_time)
            
            # Decide whether to continue
            if not continuous:
                ui.stop()
                session_stats.ending_beads_stats = get_beads_stats()
                elapsed = time.time() - start_time
                print_stats(items_completed, total_requests, elapsed, session_stats)
                run_logger.finalize(items_completed, total_requests, elapsed)
                print(f"\n📝 Run ID: {run_id}")
                print(f"📁 Logs saved to: {run_logger.get_run_dir()}")
                clear_terminal_banner()
                return 0 if success else 1
            
            if interactive:
                # Clear banner between items
                set_terminal_banner(f"PokePoke {mode_name} - {agent_name}")
                ui.update_header("PokePoke", f"{mode_name} Mode", "Waiting...")
                
                ui.stop()
                cont = input("\nProcess another item? [Y/n]: ").strip().lower()
                ui.start()
                
                if cont and cont != 'y':
                    ui.stop()
                    session_stats.ending_beads_stats = get_beads_stats()
                    elapsed = time.time() - start_time
                    print("\n👋 Exiting PokePoke.")
                    print_stats(items_completed, total_requests, elapsed, session_stats)
                    run_logger.finalize(items_completed, total_requests, elapsed)
                    print(f"\n📝 Run ID: {run_id}")
                    print(f"📁 Logs saved to: {run_logger.get_run_dir()}")
                    clear_terminal_banner()
                    return 0
            else:
                ui.update_header("PokePoke", f"{mode_name} Mode", "Sleeping...")
                print("\n⏳ Waiting 5 seconds before next iteration...")
                time.sleep(5)
    
    except KeyboardInterrupt:
        # Clean shutdown on Ctrl+C
        ui.stop()
        print("\n\n⚠️  Interrupted by user (Ctrl+C)")
        print("📊 Collecting final statistics...")
        
        # Try to get ending stats, but don't fail if interrupted again
        try:
            session_stats.ending_beads_stats = get_beads_stats()
        except KeyboardInterrupt:
            print("⚠️  Stats collection interrupted, skipping...")
            session_stats.ending_beads_stats = None
        
        elapsed = time.time() - start_time
        print("\n👋 Exiting PokePoke.")
        print_stats(items_completed, total_requests, elapsed, session_stats)
        run_logger.finalize(items_completed, total_requests, elapsed)
        print(f"\n📝 Run ID: {run_id}")
        print(f"📁 Logs saved to: {run_logger.get_run_dir()}")
        clear_terminal_banner()
        return 0
    except Exception as e:
        ui.stop()
        print("\n📊 Collecting final statistics...")
        try:
            session_stats.ending_beads_stats = get_beads_stats()
        except KeyboardInterrupt:
            print("⚠️  Stats collection interrupted, skipping...")
            session_stats.ending_beads_stats = None
        
        elapsed = time.time() - start_time
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        print_stats(items_completed, total_requests, elapsed, session_stats)
        run_logger.log_orchestrator(f"Error: {e}", level="ERROR")
        run_logger.finalize(items_completed, total_requests, elapsed)
        print(f"\n📝 Run ID: {run_id}")
        print(f"📁 Logs saved to: {run_logger.get_run_dir()}")
        clear_terminal_banner()
        return 1
    finally:
        ui.stop()



def _aggregate_stats(session_stats: SessionStats, item_stats: AgentStats) -> None:
    """Aggregate item statistics into session statistics."""
    session_stats.agent_stats.wall_duration += item_stats.wall_duration
    session_stats.agent_stats.api_duration += item_stats.api_duration
    session_stats.agent_stats.input_tokens += item_stats.input_tokens
    session_stats.agent_stats.output_tokens += item_stats.output_tokens
    session_stats.agent_stats.lines_added += item_stats.lines_added
    session_stats.agent_stats.lines_removed += item_stats.lines_removed
    session_stats.agent_stats.premium_requests += item_stats.premium_requests
    session_stats.agent_stats.tool_calls += item_stats.tool_calls
    session_stats.agent_stats.estimated_cost += item_stats.estimated_cost
    session_stats.agent_stats.retries += item_stats.retries


def _run_periodic_maintenance(items_completed: int, session_stats: SessionStats, run_logger: 'RunLogger') -> None:
    """Run periodic maintenance agents based on completion count.
    
    Args:
        items_completed: Number of items completed
        session_stats: Session statistics
        run_logger: Run logger instance
    """
    pokepoke_repo = Path.cwd()
    
    # Skip maintenance at start (items_completed == 0)
    if items_completed == 0:
        return
    
    # Run Tech Debt Agent (every 5 items)
    if items_completed % 5 == 0:
        set_terminal_banner("PokePoke - Synced Tech Debt Agent")
        ui.update_header("MAINTENANCE", "Tech Debt Agent", "Running")
        print("\n📊 Running Tech Debt Agent...")
        run_logger.log_maintenance("tech_debt", "Starting Tech Debt Agent")
        session_stats.tech_debt_agent_runs += 1
        tech_stats = run_maintenance_agent("Tech Debt", "tech-debt.md", repo_root=pokepoke_repo, needs_worktree=False)
        if tech_stats:
            _aggregate_stats(session_stats, tech_stats)
            run_logger.log_maintenance("tech_debt", "Tech Debt Agent completed successfully")
        else:
            run_logger.log_maintenance("tech_debt", "Tech Debt Agent failed")
    
    # Run Janitor Agent (every 2 items instead of 3 for more frequent runs)
    if items_completed % 2 == 0:
        set_terminal_banner("PokePoke - Synced Janitor Agent")
        ui.update_header("MAINTENANCE", "Janitor Agent", "Running")
        print("\n🧹 Running Janitor Agent...")
        run_logger.log_maintenance("janitor", "Starting Janitor Agent")
        session_stats.janitor_agent_runs += 1
        janitor_stats = run_maintenance_agent("Janitor", "janitor.md", repo_root=pokepoke_repo, needs_worktree=True)
        if janitor_stats:
            _aggregate_stats(session_stats, janitor_stats)
            session_stats.janitor_lines_removed += janitor_stats.lines_removed
            run_logger.log_maintenance("janitor", "Janitor Agent completed successfully")
        else:
            run_logger.log_maintenance("janitor", "Janitor Agent failed")
    
    # Run Backlog Cleanup Agent (every 7 items)
    if items_completed % 7 == 0:
        set_terminal_banner("PokePoke - Synced Backlog Cleanup Agent")
        ui.update_header("MAINTENANCE", "Backlog Cleanup Agent", "Running")
        print("\n🗑️ Running Backlog Cleanup Agent...")
        run_logger.log_maintenance("backlog_cleanup", "Starting Backlog Cleanup Agent")
        session_stats.backlog_cleanup_agent_runs += 1
        # Run in worktree but do not merge (discard documentation changes)
        backlog_stats = run_maintenance_agent("Backlog Cleanup", "backlog-cleanup.md", repo_root=pokepoke_repo, needs_worktree=True, merge_changes=False)
        if backlog_stats:
            _aggregate_stats(session_stats, backlog_stats)
        run_logger.log_maintenance("backlog_cleanup", "Backlog Cleanup Agent completed successfully")
    # Run Beta Tester Agent (every 3 items - swap with Janitor)
    if items_completed % 3 == 0:
        set_terminal_banner("PokePoke - Synced Beta Tester Agent")
        ui.update_header("MAINTENANCE", "Beta Tester Agent", "Running")
        from pokepoke.agent_runner import run_beta_tester
        print("\n🧪 Running Beta Tester Agent...")
        run_logger.log_maintenance("beta_tester", "Starting Beta Tester Agent")
        session_stats.beta_tester_agent_runs += 1
        beta_stats = run_beta_tester(repo_root=pokepoke_repo)
        if beta_stats:
            _aggregate_stats(session_stats, beta_stats)
        run_logger.log_maintenance("beta_tester", f"Beta Tester Agent {'completed successfully' if beta_stats else 'failed'}")
    
    # Run Code Review Agent (every 5 items)
    if items_completed % 5 == 0:
        set_terminal_banner("PokePoke - Synced Code Review Agent")
        ui.update_header("MAINTENANCE", "Code Review Agent", "Running")
        print("\n🔍 Running Code Review Agent...")
        run_logger.log_maintenance("code_review", "Starting Code Review Agent")
        session_stats.code_review_agent_runs += 1
        # Code reviewer files issues in beads, doesn't need worktree
        code_review_stats = run_maintenance_agent(
            "Code Review", 
            "code-reviewer.md", 
            repo_root=pokepoke_repo, 
            needs_worktree=False,
            model="gpt-5.1-codex"
        )
        if code_review_stats:
            _aggregate_stats(session_stats, code_review_stats)
            run_logger.log_maintenance("code_review", "Code Review Agent completed successfully")
        else:
            run_logger.log_maintenance("code_review", "Code Review Agent failed")



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
    parser.add_argument(
        "--beta-first",
        action="store_true",
        help="Run beta tester at startup before processing work items",
    )
    args = parser.parse_args()
    # Autonomous flag overrides interactive
    interactive = not args.autonomous
    return run_orchestrator(interactive=interactive, continuous=args.continuous, run_beta_first=args.beta_first)


if __name__ == "__main__":
    sys.exit(main())
