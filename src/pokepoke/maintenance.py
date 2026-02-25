"""Periodic maintenance agent orchestration."""

from pathlib import Path
from typing import TYPE_CHECKING

from pokepoke.types import AgentStats, SessionStats
from pokepoke.logging_utils import RunLogger

if TYPE_CHECKING:
    from pokepoke.logging_utils import ItemLogger


def aggregate_stats(session_stats: SessionStats, item_stats: AgentStats) -> None:
    """Aggregate item statistics into session statistics."""
    session_stats.agent_stats.accumulate(item_stats)


def _run_special_agent(name: str, repo_root: Path, item_logger: 'ItemLogger | None' = None, parent_agent_id: str | None = None) -> AgentStats | None:
    """Run a special agent that has its own runner function."""
    if name == "Beta Tester":
        from pokepoke.agent_runner import run_beta_tester
        return run_beta_tester(repo_root=repo_root, item_logger=item_logger, parent_agent_id=parent_agent_id)
    if name == "Worktree Cleanup":
        from pokepoke.agent_runner import run_worktree_cleanup
        return run_worktree_cleanup(repo_root=repo_root, item_logger=item_logger, parent_agent_id=parent_agent_id)
    if name == "Model Sync":
        from pokepoke.model_sync import sync_copilot_models
        return sync_copilot_models(item_logger=item_logger)
    return None


def run_periodic_maintenance(items_completed: int, session_stats: SessionStats, run_logger: RunLogger) -> None:
    """Run periodic maintenance agents based on config and completion count.

    This function now delegates to MaintenanceScheduler for singleton coordination.
    Kept for backward compatibility.
    """
    # Import here to avoid circular imports
    from pokepoke.maintenance_scheduler import run_periodic_maintenance as _run_with_scheduler
    return _run_with_scheduler(items_completed, session_stats, run_logger)
