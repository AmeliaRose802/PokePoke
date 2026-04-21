"""Periodic maintenance agent orchestration."""

from pathlib import Path
from typing import TYPE_CHECKING

from pokepoke.types import AgentStats

if TYPE_CHECKING:
    from pokepoke.utils.logging_utils import ItemLogger


def _run_special_agent(name: str, repo_root: Path, item_logger: 'ItemLogger | None' = None, parent_agent_id: str | None = None) -> AgentStats | None:
    """Run a special agent that has its own runner function."""
    if name == "Beta Tester":
        from pokepoke.agents.agent_runner import run_beta_tester
        return run_beta_tester(repo_root=repo_root, item_logger=item_logger, parent_agent_id=parent_agent_id)
    if name == "Worktree Cleanup":
        from pokepoke.agents.agent_runner import run_worktree_cleanup
        return run_worktree_cleanup(repo_root=repo_root, item_logger=item_logger, parent_agent_id=parent_agent_id)
    return None
