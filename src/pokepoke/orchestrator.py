"""PokePoke Orchestrator - Main entry point for autonomous and interactive modes."""

import argparse
import subprocess
import sys
import time
from pathlib import Path

from pokepoke.beads import get_ready_work_items, get_beads_stats
from pokepoke.beads_management import create_cleanup_delegation_issue
from pokepoke.types import AgentStats, SessionStats
from pokepoke.stats import print_stats
from pokepoke.workflow import select_work_item, process_work_item
from pokepoke.agent_runner import run_maintenance_agent


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
    
    # Maintenance agent frequency configuration
    TECH_DEBT_FREQUENCY = 10
    JANITOR_FREQUENCY = 3
    BACKLOG_FREQUENCY = 5
    
    # Track statistics
    start_time = time.time()
    items_completed = 0
    total_requests = 0
    session_stats = SessionStats(agent_stats=AgentStats())
    
    print("📊 Recording starting beads statistics...")
    session_stats.starting_beads_stats = get_beads_stats()
    
    try:
        while True:
            # Check main repo status before processing
            print("\n🔍 Checking main repository status...")
            if not _check_and_commit_main_repo():
                return 1
            
            print("\nFetching ready work from beads...")
            ready_items = get_ready_work_items()
            
            selected_item = select_work_item(ready_items, interactive)
            
            if selected_item is None:
                print("\n👋 Exiting PokePoke.")
                return 0
            
            # Process the selected item
            success, requests, item_stats, cleanup_runs = process_work_item(selected_item, interactive)
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
                
                _run_periodic_maintenance(items_completed, session_stats)
            
            # Decide whether to continue
            if not continuous:
                session_stats.ending_beads_stats = get_beads_stats()
                elapsed = time.time() - start_time
                print_stats(items_completed, total_requests, elapsed, session_stats)
                return 0 if success else 1
            
            if interactive:
                cont = input("\nProcess another item? [Y/n]: ").strip().lower()
                if cont and cont != 'y':
                    session_stats.ending_beads_stats = get_beads_stats()
                    elapsed = time.time() - start_time
                    print("\n👋 Exiting PokePoke.")
                    print_stats(items_completed, total_requests, elapsed, session_stats)
                    return 0
            else:
                print("\n⏳ Waiting 5 seconds before next iteration...")
                time.sleep(5)
    
    except KeyboardInterrupt:
        session_stats.ending_beads_stats = get_beads_stats()
        elapsed = time.time() - start_time
        print("\n\n👋 Interrupted. Exiting PokePoke.")
        print_stats(items_completed, total_requests, elapsed, session_stats)
        return 0
    except Exception as e:
        session_stats.ending_beads_stats = get_beads_stats()
        elapsed = time.time() - start_time
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        print_stats(items_completed, total_requests, elapsed, session_stats)
        return 1


def _check_and_commit_main_repo() -> bool:
    """Check main repository status and commit beads changes if needed.
    
    Returns:
        True if ready to continue, False if should exit
    """
    status_result = subprocess.run(
        ["git", "status", "--porcelain"],
        capture_output=True,
        text=True,
        check=True
    )
    
    uncommitted = status_result.stdout.strip()
    if uncommitted:
        lines = uncommitted.split('\n')
        non_beads_changes = [line for line in lines if line and '.beads/' not in line]
        
        if non_beads_changes:
            print(f"\n⚠️  Main repository has uncommitted changes:")
            for line in non_beads_changes[:10]:
                print(f"   {line}")
            if len(non_beads_changes) > 10:
                print(f"   ... and {len(non_beads_changes) - 10} more")
            
            # Create delegation issue for cleanup
            changes_list = '\n'.join(f"  - {line}" for line in non_beads_changes[:20])
            if len(non_beads_changes) > 20:
                changes_list += f"\n  ... and {len(non_beads_changes) - 20} more"
            
            description = f"""Main repository has uncommitted changes that need to be resolved:

{changes_list}

**Required Actions:**
1. Review uncommitted changes with `git status`
2. Either commit changes if they are valid work, or stash/discard if not
3. Ensure main repository is clean before PokePoke continues
4. If there are worktree directories uncommitted, investigate why merge failed

**Commands to run:**
```bash
git status
# Then either:
git add . && git commit -m "description"
# Or:
git stash
```

Once resolved, this issue can be closed and PokePoke will continue.
"""
            
            create_cleanup_delegation_issue(
                title="Clean up uncommitted changes in main repository",
                description=description,
                labels=['git', 'cleanup'],
                priority=0  # Critical - blocks all work
            )
            
            print("\n📋 Created delegation issue for cleanup")
            print("   An agent will handle this automatically")
            return False
        elif '.beads/' in uncommitted:
            print("🔧 Committing beads database changes...")
            subprocess.run(["git", "add", ".beads/"], check=True)
            subprocess.run(
                ["git", "commit", "-m", "chore: auto-commit beads changes"],
                check=True,
                capture_output=True
            )
            print("✅ Beads changes committed")
    
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


def _run_periodic_maintenance(items_completed: int, session_stats: SessionStats) -> None:
    """Run periodic maintenance agents based on completion count."""
    pokepoke_repo = Path(r"C:\Users\ameliapayne\PokePoke")
    
    # Run Tech Debt Agent
    if items_completed % 10 == 0:
        print("\n📊 Running Tech Debt Agent...")
        session_stats.tech_debt_agent_runs += 1
        tech_stats = run_maintenance_agent("Tech Debt", "tech-debt.md", repo_root=pokepoke_repo, needs_worktree=False)
        if tech_stats:
            _aggregate_stats(session_stats, tech_stats)
    
    # Run Janitor Agent
    if items_completed % 3 == 0:
        print("\n🧹 Running Janitor Agent...")
        session_stats.janitor_agent_runs += 1
        janitor_stats = run_maintenance_agent("Janitor", "janitor.md", repo_root=pokepoke_repo, needs_worktree=True)
        if janitor_stats:
            _aggregate_stats(session_stats, janitor_stats)
    
    # Run Backlog Cleanup Agent
    if items_completed % 5 == 0:
        print("\n🗑️ Running Backlog Cleanup Agent...")
        session_stats.backlog_cleanup_agent_runs += 1
        backlog_stats = run_maintenance_agent("Backlog Cleanup", "backlog-cleanup.md", repo_root=pokepoke_repo, needs_worktree=False)
        if backlog_stats:
            _aggregate_stats(session_stats, backlog_stats)



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
