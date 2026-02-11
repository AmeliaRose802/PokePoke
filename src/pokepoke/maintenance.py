"""Periodic maintenance agent orchestration."""

from pathlib import Path

from pokepoke.types import AgentStats, SessionStats
from pokepoke.agent_runner import run_maintenance_agent
from pokepoke.terminal_ui import set_terminal_banner, ui
from pokepoke.logging_utils import RunLogger


def aggregate_stats(session_stats: SessionStats, item_stats: AgentStats) -> None:
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


def run_periodic_maintenance(items_completed: int, session_stats: SessionStats, run_logger: RunLogger) -> None:
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
            aggregate_stats(session_stats, tech_stats)
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
            aggregate_stats(session_stats, janitor_stats)
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
            aggregate_stats(session_stats, backlog_stats)
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
            aggregate_stats(session_stats, beta_stats)
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
            aggregate_stats(session_stats, code_review_stats)
            run_logger.log_maintenance("code_review", "Code Review Agent completed successfully")
        else:
            run_logger.log_maintenance("code_review", "Code Review Agent failed")
    
    # Run Worktree Cleanup Agent (every 4 items)
    if items_completed % 4 == 0:
        set_terminal_banner("PokePoke - Synced Worktree Cleanup Agent")
        ui.update_header("MAINTENANCE", "Worktree Cleanup Agent", "Running")
        from pokepoke.agent_runner import run_worktree_cleanup
        print("\n🌳 Running Worktree Cleanup Agent...")
        run_logger.log_maintenance("worktree_cleanup", "Starting Worktree Cleanup Agent")
        session_stats.worktree_cleanup_agent_runs += 1
        cleanup_stats = run_worktree_cleanup(repo_root=pokepoke_repo)
        if cleanup_stats:
            aggregate_stats(session_stats, cleanup_stats)
        run_logger.log_maintenance("worktree_cleanup", f"Worktree Cleanup Agent {'completed successfully' if cleanup_stats else 'failed'}")
