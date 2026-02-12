"""PokePoke Orchestrator - Main entry point for autonomous and interactive modes."""

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from pokepoke.beads import get_ready_work_items, get_beads_stats
from pokepoke.types import AgentStats, SessionStats
from pokepoke.stats import print_stats
from pokepoke.workflow import process_work_item
from pokepoke.work_item_selection import select_work_item
from pokepoke.logging_utils import RunLogger
from pokepoke.agent_names import initialize_agent_name
from pokepoke.terminal_ui import set_terminal_banner, format_work_item_banner, clear_terminal_banner
from pokepoke import terminal_ui
from pokepoke.maintenance_state import increment_items_completed
from pokepoke.repo_check import check_and_commit_main_repo
from pokepoke.maintenance import run_periodic_maintenance, aggregate_stats
from pokepoke.shutdown import is_shutting_down, request_shutdown


def _check_beads_available() -> bool:
    """Check that beads (bd) is installed and initialized in the current directory.
    
    Returns:
        True if beads is available and initialized, False otherwise.
    """
    # Check that bd command exists
    if not shutil.which('bd'):
        print("\nError: 'bd' (beads) command not found.", file=sys.stderr)
        print("   PokePoke requires beads for work item tracking.", file=sys.stderr)
        print("   Install beads: pip install beads", file=sys.stderr)
        print("   Then initialize: bd init", file=sys.stderr)
        return False
    
    # Check that beads is initialized (bd info should succeed)
    try:
        result = subprocess.run(
            ['bd', 'info', '--json'],
            capture_output=True, text=True, encoding='utf-8',
            timeout=10
        )
        if result.returncode != 0:
            print("\nError: This directory is not a beads repository.", file=sys.stderr)
            print("   Run 'bd init' to set up beads tracking.", file=sys.stderr)
            return False
    except subprocess.TimeoutExpired:
        print("\nError: 'bd info' timed out. Beads may not be configured correctly.", file=sys.stderr)
        return False
    except Exception as e:
        print(f"\nError: Failed to check beads status: {e}", file=sys.stderr)
        print("   Ensure beads is installed and initialized: bd init", file=sys.stderr)
        return False
    
    return True


def run_orchestrator(interactive: bool = True, continuous: bool = False, run_beta_first: bool = False) -> int:
    """Main orchestrator loop.
    
    Args:
        interactive: If True, prompt for user input at decision points
        continuous: If True, loop continuously; if False, process one item and exit
        run_beta_first: If True, run beta tester at startup before processing work items
        
    Returns:
        Exit code (0 for success, 1 for failure)
    """
    # UI is started by run_with_orchestrator - just update header
    terminal_ui.ui.update_header("PokePoke", f"Initializing {interactive and 'Interactive' or 'Autonomous'} Mode...")

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
        terminal_ui.ui.update_header("PokePoke", f"{mode_name} Mode", agent_name)
        
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
        
        # Set session start time for real-time clock updates
        terminal_ui.ui.set_session_start_time(start_time)
        
        # Initial stats display with 0 elapsed time (or very small)
        terminal_ui.ui.update_stats(session_stats, time.time() - start_time)
        
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
            
        while not is_shutting_down():
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
                terminal_ui.ui.stop()
            selected_item = select_work_item(ready_items, interactive)
            if interactive:
                terminal_ui.ui.start()
            
            if selected_item is None:
                terminal_ui.ui.stop_and_capture()
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
            terminal_ui.ui.update_header(selected_item.id, selected_item.title)
            
            success, requests, item_stats, cleanup_runs, gate_runs, model_completion = process_work_item(
                selected_item, interactive, run_logger=run_logger
            )
            total_requests += requests
            if requests > 1:
                session_stats.agent_stats.retries += (requests - 1)
            
            session_stats.work_agent_runs += 1
            session_stats.cleanup_agent_runs += cleanup_runs
            session_stats.gate_agent_runs += gate_runs
            
            # Aggregate statistics
            if item_stats:
                aggregate_stats(session_stats, item_stats)
            
            # Record model completion for A/B testing
            if model_completion:
                session_stats.model_completions.append(model_completion)
            
            # Increment counter on successful processing
            if success:
                items_completed += 1
                session_stats.items_completed = items_completed
                session_stats.completed_items_list.append(selected_item)
                total_persistent_count = increment_items_completed()
                print(f"\n📈 Items completed this session: {items_completed}")
                print(f"📈 Total items completed (lifetime): {total_persistent_count}")
                run_logger.log_orchestrator(f"Items completed this session: {items_completed}")
                
                run_periodic_maintenance(total_persistent_count, session_stats, run_logger)

            # Update UI stats with current runtime
            terminal_ui.ui.update_stats(session_stats, time.time() - start_time)
            
            # Decide whether to continue
            if not continuous:
                terminal_ui.ui.stop_and_capture()
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
                terminal_ui.ui.update_header("PokePoke", f"{mode_name} Mode", "Waiting...")
                
                terminal_ui.ui.stop()
                cont = input("\nProcess another item? [Y/n]: ").strip().lower()
                terminal_ui.ui.start()
                
                if cont and cont != 'y':
                    terminal_ui.ui.stop_and_capture()
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
                terminal_ui.ui.update_header("PokePoke", f"{mode_name} Mode", "Sleeping...")
                print("\n⏳ Waiting 5 seconds before next iteration...")
                for _ in range(10):
                    if is_shutting_down():
                        break
                    time.sleep(0.5)

        # Shutdown requested - clean exit
        terminal_ui.ui.stop_and_capture()
        session_stats.ending_beads_stats = get_beads_stats()
        elapsed = time.time() - start_time
        print("\n\ud83d\udc4b Shutdown requested - exiting PokePoke.")
        print_stats(items_completed, total_requests, elapsed, session_stats)
        run_logger.finalize(items_completed, total_requests, elapsed)
        clear_terminal_banner()
        return 0
    
    except KeyboardInterrupt:
        # Clean shutdown on Ctrl+C
        request_shutdown()
        terminal_ui.ui.stop_and_capture()
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
        terminal_ui.ui.stop_and_capture()
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
        terminal_ui.ui.stop()



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
    parser.add_argument(
        "--init",
        action="store_true",
        help="Initialize .pokepoke/ directory with sample config and templates",
    )
    args = parser.parse_args()

    if args.init:
        from pokepoke.init import init_project
        return 0 if init_project() else 1

    # Autonomous flag overrides interactive
    interactive = not args.autonomous
    
    # Check beads availability BEFORE starting any UI
    # so error messages print directly to stdout
    if not _check_beads_available():
        return 1
    
    from pokepoke.desktop_ui import DesktopUI
    active_ui: DesktopUI = terminal_ui.ui
    
    # Run the orchestrator with the selected UI
    def orchestrator_func() -> int:
        return run_orchestrator(
            interactive=interactive,
            continuous=args.continuous,
            run_beta_first=args.beta_first
        )
    
    return active_ui.run_with_orchestrator(orchestrator_func)


if __name__ == "__main__":
    sys.exit(main())
