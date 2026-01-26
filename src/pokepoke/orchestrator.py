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
from pokepoke.terminal_ui import set_terminal_banner, format_work_item_banner, clear_terminal_banner


def run_orchestrator(interactive: bool = True, continuous: bool = False, run_beta_first: bool = False) -> int:
    """Main orchestrator loop.
    
    Args:
        interactive: If True, prompt for user input at decision points
        continuous: If True, loop continuously; if False, process one item and exit
        run_beta_first: If True, run beta tester at startup before processing work items
        
    Returns:
        Exit code (0 for success, 1 for failure)
    """
    # Initialize unique agent name for this run
    agent_name = initialize_agent_name()
    os.environ['AGENT_NAME'] = agent_name
    
    mode_name = "Interactive" if interactive else "Autonomous"
    print(f"🎯 PokePoke {mode_name} Mode | 🤖 Agent: {agent_name}")
    print("=" * 50)
    set_terminal_banner(f"PokePoke {mode_name} - {agent_name}")
    
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
    # Run beta tester first if requested
    if run_beta_first:
        print("\n🧪 Running Beta Tester at startup...")
        run_logger.log_orchestrator("Running Beta Tester at startup")
        from pokepoke.agent_runner import run_beta_tester
        beta_stats = run_beta_tester()
        if beta_stats:
            # Aggregate beta tester stats
            session_stats.agent_stats.wall_duration += beta_stats.wall_duration
            session_stats.agent_stats.api_duration += beta_stats.api_duration
            session_stats.agent_stats.input_tokens += beta_stats.input_tokens
            session_stats.agent_stats.output_tokens += beta_stats.output_tokens
            session_stats.agent_stats.premium_requests += beta_stats.premium_requests
        print("✅ Beta Tester completed\n")
    try:
        while True:
            # Check main repo status before processing
            print("\n🔍 Checking main repository status...")
            run_logger.log_orchestrator("Checking main repository status")
            if not _check_and_commit_main_repo(main_repo_path, run_logger):
                run_logger.log_orchestrator("Main repo check failed", level="ERROR")
                return 1
            print("\nFetching ready work from beads...")
            run_logger.log_orchestrator("Fetching ready work from beads")
            ready_items = get_ready_work_items()
            selected_item = select_work_item(ready_items, interactive)
            
            if selected_item is None:
                print("\n👋 Exiting PokePoke.")
                run_logger.log_orchestrator("User chose to exit")
                clear_terminal_banner()
                return 0
            
            # Process the selected item
            run_logger.log_orchestrator(f"Selected item: {selected_item.id} - {selected_item.title}")
            # Update terminal banner with current work item
            banner = format_work_item_banner(selected_item.id, selected_item.title)
            set_terminal_banner(banner)
            success, requests, item_stats, cleanup_runs = process_work_item(
                selected_item, interactive, run_logger=run_logger
            )
            total_requests += requests
            session_stats.work_agent_runs += 1
            session_stats.cleanup_agent_runs += cleanup_runs
            
            # Aggregate statistics
            if item_stats:
                _aggregate_stats(session_stats, item_stats)
            
            # Increment counter on successful processing
            if success:
                items_completed += 1
                print(f"\n📈 Items completed this session: {items_completed}")
                run_logger.log_orchestrator(f"Items completed this session: {items_completed}")
                
                _run_periodic_maintenance(items_completed, session_stats, run_logger)
            
            # Decide whether to continue
            if not continuous:
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
                cont = input("\nProcess another item? [Y/n]: ").strip().lower()
                if cont and cont != 'y':
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
                print("\n⏳ Waiting 5 seconds before next iteration...")
                time.sleep(5)
    
    except KeyboardInterrupt:
        # Clean shutdown on Ctrl+C
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


def _check_and_commit_main_repo(repo_path: Path, run_logger: 'RunLogger') -> bool:
    """Check main repository status and commit beads changes if needed.
    
    Args:
        repo_path: Path to the main repository
        run_logger: Run logger instance
    
    Returns:
        True if ready to continue, False if should exit
    """
    status_result = subprocess.run(
        ["git", "status", "--porcelain"],
        capture_output=True,
        text=True,
        encoding='utf-8',
        check=True,
        cwd=str(repo_path)
    )
    
    uncommitted = status_result.stdout.strip()
    if uncommitted:
        lines = uncommitted.split('\n')
        # Categorize changes for proper handling
        beads_changes = [line for line in lines if line and '.beads/' in line]
        worktree_changes = [line for line in lines if line and 'worktrees/' in line and not line.startswith('??')]
        untracked_files = [line for line in lines if line and line.startswith('??')]
        other_changes = [
            line for line in lines
            if line
            and '.beads/' not in line
            and 'worktrees/' not in line
            and not line.startswith('??')
        ]
        
        # Handle problematic changes that need agent intervention
        if other_changes:
            print("\n⚠️  Main repository has uncommitted changes:")
            run_logger.log_orchestrator("Main repository has uncommitted changes", level="WARNING")
            for line in other_changes[:10]:
                print(f"   {line}")
            if len(other_changes) > 10:
                print(f"   ... and {len(other_changes) - 10} more")
            
            # Immediately run cleanup agent instead of delegating
            print("\n🤖 Launching cleanup agent to resolve uncommitted changes...")
            run_logger.log_orchestrator("Launching cleanup agent for uncommitted changes")
            
            from pokepoke.agent_runner import invoke_cleanup_agent
            from pokepoke.types import BeadsWorkItem
            
            # Create a temporary work item for the cleanup agent
            cleanup_item = BeadsWorkItem(
                id="cleanup-main-repo",
                title="Clean up uncommitted changes in main repository",
                description="Auto-generated cleanup task for uncommitted changes",
                issue_type="task",
                priority=0,
                status="in_progress",
                labels=["cleanup", "auto-generated"]
            )
            
            cleanup_success, cleanup_stats = invoke_cleanup_agent(cleanup_item, repo_path)
            
            if cleanup_success:
                print("✅ Cleanup agent successfully resolved uncommitted changes")
                run_logger.log_orchestrator("Cleanup agent successfully resolved uncommitted changes")
                return True  # Continue processing
            else:
                print("❌ Cleanup agent failed to resolve uncommitted changes")
                print("   Please manually resolve and try again")
                run_logger.log_orchestrator("Cleanup agent failed to resolve uncommitted changes", level="ERROR")
                return False
        
        # Beads changes are handled by beads' own sync mechanism (bd sync)
        # Do NOT manually commit them - beads daemon handles this automatically
        if beads_changes:
            print("ℹ️  Beads database changes detected - will be synced by beads daemon")
            print("ℹ️  Run 'bd sync' to force immediate sync if needed")
        
        # Auto-resolve worktree cleanup deletions
        if worktree_changes:
            print("🧹 Committing worktree cleanup changes...")
            subprocess.run(["git", "add", "worktrees/"], check=True, encoding='utf-8', errors='replace', cwd=str(repo_path))
            subprocess.run(
                ["git", "commit", "-m", "chore: cleanup deleted worktree directories"],
                check=True,
                capture_output=True,
                encoding='utf-8',
                errors='replace',
                cwd=str(repo_path)
            )
            print("✅ Worktree cleanup committed")
    
    return True


def _aggregate_stats(session_stats: SessionStats, item_stats: AgentStats) -> None:
    """Aggregate item statistics into session statistics."""
    session_stats.agent_stats.wall_duration += item_stats.wall_duration
    session_stats.agent_stats.api_duration += item_stats.api_duration
    session_stats.agent_stats.input_tokens += item_stats.input_tokens
    session_stats.agent_stats.output_tokens += item_stats.output_tokens
    session_stats.agent_stats.lines_added += item_stats.lines_added
    session_stats.agent_stats.lines_removed += item_stats.lines_removed
    session_stats.agent_stats.premium_requests += item_stats.premium_requests


def _run_periodic_maintenance(items_completed: int, session_stats: SessionStats, run_logger: 'RunLogger') -> None:
    """Run periodic maintenance agents based on completion count.
    
    Args:
        items_completed: Number of items completed
        session_stats: Session statistics
        run_logger: Run logger instance
    """
    pokepoke_repo = Path(r"C:\Users\ameliapayne\PokePoke")
    
    # Skip maintenance at start (items_completed == 0)
    if items_completed == 0:
        return
    
    # Run Tech Debt Agent (every 5 items)
    if items_completed % 5 == 0:
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
        print("\n🧹 Running Janitor Agent...")
        run_logger.log_maintenance("janitor", "Starting Janitor Agent")
        session_stats.janitor_agent_runs += 1
        janitor_stats = run_maintenance_agent("Janitor", "janitor.md", repo_root=pokepoke_repo, needs_worktree=True)
        if janitor_stats:
            _aggregate_stats(session_stats, janitor_stats)
            run_logger.log_maintenance("janitor", "Janitor Agent completed successfully")
        else:
            run_logger.log_maintenance("janitor", "Janitor Agent failed")
    
    # Run Backlog Cleanup Agent (every 7 items)
    if items_completed % 7 == 0:
        print("\n🗑️ Running Backlog Cleanup Agent...")
        run_logger.log_maintenance("backlog_cleanup", "Starting Backlog Cleanup Agent")
        session_stats.backlog_cleanup_agent_runs += 1
        backlog_stats = run_maintenance_agent("Backlog Cleanup", "backlog-cleanup.md", repo_root=pokepoke_repo, needs_worktree=False)
        if backlog_stats:
            _aggregate_stats(session_stats, backlog_stats)
        run_logger.log_maintenance("backlog_cleanup", "Backlog Cleanup Agent completed successfully")
    
    # Run Beta Tester Agent (every 3 items - swap with Janitor)
    if items_completed % 3 == 0:
        from pokepoke.agent_runner import run_beta_tester
        print("\n🧪 Running Beta Tester Agent...")
        run_logger.log_maintenance("beta_tester", "Starting Beta Tester Agent")
        session_stats.beta_tester_agent_runs += 1
        beta_stats = run_beta_tester()
        if beta_stats:
            _aggregate_stats(session_stats, beta_stats)
        run_logger.log_maintenance("beta_tester", f"Beta Tester Agent {'completed successfully' if beta_stats else 'failed'}")



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
