"""Periodic maintenance agent orchestration."""

from pathlib import Path

from pokepoke.config import get_config
from pokepoke.types import AgentStats, SessionStats
from pokepoke.agent_runner import run_maintenance_agent
from pokepoke.logging_utils import RunLogger

# Agents that have special runner functions instead of the generic one
_SPECIAL_AGENTS = {"Beta Tester", "Worktree Cleanup"}

# Map of agent stat attribute names by agent name
_AGENT_STAT_ATTRS = {
    "Tech Debt": "tech_debt_agent_runs",
    "Janitor": "janitor_agent_runs",
    "Backlog Cleanup": "backlog_cleanup_agent_runs",
    "Beta Tester": "beta_tester_agent_runs",
    "Code Review": "code_review_agent_runs",
    "Worktree Cleanup": "worktree_cleanup_agent_runs",
}


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
    session_stats.agent_stats.retries += item_stats.retries


def _run_special_agent(name: str, repo_root: Path) -> AgentStats | None:
    """Run a special agent that has its own runner function."""
    if name == "Beta Tester":
        from pokepoke.agent_runner import run_beta_tester
        return run_beta_tester(repo_root=repo_root)
    if name == "Worktree Cleanup":
        from pokepoke.agent_runner import run_worktree_cleanup
        return run_worktree_cleanup(repo_root=repo_root)
    return None


def run_periodic_maintenance(items_completed: int, session_stats: SessionStats, run_logger: RunLogger) -> None:
    """Run periodic maintenance agents based on config and completion count.
    
    This function now delegates to MaintenanceScheduler for singleton coordination.
    Kept for backward compatibility.
    """
    # Import here to avoid circular imports
    from pokepoke.maintenance_scheduler import run_periodic_maintenance as _run_with_scheduler
    return _run_with_scheduler(items_completed, session_stats, run_logger)
