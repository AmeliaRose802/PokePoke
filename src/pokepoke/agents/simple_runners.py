"""Simple agent runners (beads-only, main-repo) extracted from agent_runner."""
import logging
from typing import TYPE_CHECKING

from pokepoke.models.ai_backends import invoke_copilot
from pokepoke.stats.metrics_context import agent_type_context
from pokepoke.stats.stats import parse_agent_stats
from pokepoke.types import AgentStats
from pokepoke.types_agent import CopilotResult

if TYPE_CHECKING:
    from pokepoke.agents.agent_runner import AgentRunnerConfig

logger = logging.getLogger(__name__)


def _extract_stats(result: CopilotResult) -> AgentStats | None:
    """Extract stats from a CopilotResult, preferring SDK-captured stats."""
    if result.stats:
        return result.stats
    if result.output:
        return parse_agent_stats(result.output)
    return None


def _run_simple_agent(
    config: 'AgentRunnerConfig',
    agent_prompt: str,
    *,
    deny_write: bool = True,
    cwd: str | None = None,
    add_parent_dir: bool = False,
) -> AgentStats | None:
    """Run a simple agent in the main repo with configurable write access."""
    logger.info("Running %s (%s)%s", config.agent_name, "no write" if deny_write else "write enabled", f", model={config.model}" if config.model else "")
    normalized = config.agent_name.lower().replace(" ", "_")
    with agent_type_context(normalized):
        result = invoke_copilot(config.agent_item, prompt=agent_prompt, deny_write=deny_write, model=config.model, cwd=cwd, item_logger=config.item_logger, add_parent_dir=add_parent_dir)
    if result.success:
        logger.info("%s completed", config.agent_name)
        return _extract_stats(result) or AgentStats()
    logger.error("%s failed: %s", config.agent_name, result.error)
    return None


def _run_beads_only_agent(config: 'AgentRunnerConfig', agent_prompt: str, cwd: str | None = None) -> AgentStats | None:
    """Run a beads-only maintenance agent in the main repo."""
    return _run_simple_agent(config, agent_prompt, deny_write=True, cwd=cwd)


def _run_main_repo_agent(config: 'AgentRunnerConfig', agent_prompt: str, cwd: str | None = None, add_parent_dir: bool = False) -> AgentStats | None:
    """Run a maintenance agent in the main repo WITH write access."""
    return _run_simple_agent(config, agent_prompt, deny_write=False, cwd=cwd, add_parent_dir=add_parent_dir)
