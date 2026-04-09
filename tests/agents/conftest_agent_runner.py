"""Test utilities for agent_runner tests - temporary backwards compatibility."""
from pathlib import Path
from typing import TYPE_CHECKING

from pokepoke.agents.agent_runner import AgentRunnerConfig, _run_worktree_agent
from pokepoke.types import AgentStats, BeadsWorkItem

if TYPE_CHECKING:
    from pokepoke.utils.logging_utils import ItemLogger


def run_worktree_agent_compat(
    agent_name: str,
    agent_id: str,
    agent_item: BeadsWorkItem,
    agent_prompt: str,
    repo_root: Path,
    *,
    merge_changes: bool = True,
    model: str | None = None,
    item_logger: 'ItemLogger | None' = None,
    parent_agent_id: str | None = None
) -> AgentStats | None:
    """Backwards-compatible wrapper for test code.

    TODO: Update tests to use AgentRunnerConfig directly, then remove this wrapper.
    """
    config = AgentRunnerConfig(
        agent_name=agent_name,
        agent_id=agent_id,
        agent_item=agent_item,
        repo_root=repo_root,
        worktree_path=repo_root,
        model=model,
        item_logger=item_logger,
    )
    return _run_worktree_agent(
        config,
        agent_prompt,
        merge_changes=merge_changes,
        parent_agent_id=parent_agent_id,
    )
