"""Beta tester agent — tests all MCP tools in an isolated worktree."""

import logging
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

logger = logging.getLogger(__name__)

from pokepoke.agents.cleanup_agents import get_pokepoke_prompts_dir
from pokepoke.config import get_config
from pokepoke.desktop import terminal_ui
from pokepoke.types import AgentStats, BeadsWorkItem
from pokepoke.utils.constants import STATUS_IN_PROGRESS

if TYPE_CHECKING:
    from pokepoke.utils.logging_utils import ItemLogger


def run_beta_tester(repo_root: Path | None = None, item_logger: 'ItemLogger | None' = None, parent_agent_id: str | None = None) -> AgentStats | None:
    """Run beta tester agent to test all MCP tools. Restarts MCP server first."""
    from pokepoke.agents.agent_runner import _generate_unique_agent_id, _run_worktree_agent

    config = get_config()
    terminal_ui.ui.set_current_agent("Beta Tester")

    # Register Beta Tester agent in the Agents panel (if not already registered by maintenance)
    agent_id = "beta-tester"

    logger.info(f"\n{'='*60}\n🧪 Running Beta Tester Agent\n{'='*60}")

    try:
        # Restart MCP server to load latest code (if configured)
        if config.mcp_server.enabled and config.mcp_server.restart_script:
            logger.info("\n🔄 Restarting MCP server...")
            try:
                package_root = Path(__file__).resolve().parent.parent.parent
                package_root_resolved = package_root.resolve(strict=False)

                restart_candidate = (package_root / config.mcp_server.restart_script).resolve(strict=False)
                if not restart_candidate.is_relative_to(package_root_resolved):
                    raise ValueError(
                        f"Resolved restart script path '{restart_candidate}' escapes package root '{package_root_resolved}'"
                    )

                restart_script = restart_candidate
                if restart_script.exists():
                    restart_script = restart_script.resolve(strict=True)
                    if not restart_script.is_relative_to(package_root_resolved):
                        raise ValueError(
                            f"Resolved restart script path '{restart_script}' escapes package root '{package_root_resolved}'"
                        )

                if not restart_script.exists():
                    logger.warning(f"⚠️  Restart script not found at {restart_script}")
                    logger.info("   Proceeding without restart - server may have stale code")
                else:
                    result = subprocess.run(
                        ["pwsh", "-NoProfile", "-File", str(restart_script)],
                        capture_output=True, text=True, encoding='utf-8', timeout=60,
                        errors='replace',
                    )
                    if result.returncode == 0:
                        logger.info("✓ MCP server restarted successfully")
                    else:
                        logger.warning(f"⚠️  MCP server restart had issues (exit code {result.returncode})")
                        if result.stdout:
                            logger.info(f"   Output: {result.stdout[:200]}")
            except subprocess.TimeoutExpired:
                logger.warning("⚠️  MCP server restart timed out (server may still be starting)")
            except Exception as e:
                logger.warning(f"⚠️  Could not restart MCP server: {e}")
                logger.info("   Proceeding anyway - server may have stale code")
        elif not config.mcp_server.enabled:
            logger.warning("ℹ️  MCP server not enabled in config - skipping restart")

        # Load beta tester prompt
        try:
            prompts_dir = get_pokepoke_prompts_dir()
            prompt_path = prompts_dir / "beta-tester.md"
        except FileNotFoundError as e:
            logger.error(f"❌ {e}")
            terminal_ui.ui.push_agent_status(agent_id, "Beta Tester", iteration=1, status="failed", parent_agent_id=parent_agent_id, agent_type="beta_tester")
            return None

        if not prompt_path.exists():
            logger.error(f"❌ Prompt not found at {prompt_path}")
            terminal_ui.ui.push_agent_status(agent_id, "Beta Tester", iteration=1, status="failed", parent_agent_id=parent_agent_id, agent_type="beta_tester")
            return None

        beta_prompt = prompt_path.read_text(encoding='utf-8')

        # Use unique ID with timestamp to avoid worktree conflicts on multiple runs
        worktree_agent_id = _generate_unique_agent_id("beta-tester")
        beta_item = BeadsWorkItem(
            id=worktree_agent_id, title="Beta Test All MCP Tools", description=beta_prompt,
            status=STATUS_IN_PROGRESS, priority=2, issue_type="task",
            labels=["testing", "mcp-server", "automated"]
        )

        logger.info("\n🧪 Invoking beta tester agent in isolated worktree (will be discarded)...")
        if repo_root is None:
            repo_root = Path.cwd()

        # Pass parent_agent_id so any sub-agents nest under the maintenance scheduler's UI card
        agent_result = _run_worktree_agent("Beta Tester", worktree_agent_id, beta_item, beta_prompt, repo_root, merge_changes=False, item_logger=item_logger, parent_agent_id=parent_agent_id)

        # Update agent status based on result
        status = "success" if agent_result is not None else "failed"
        terminal_ui.ui.push_agent_status(agent_id, "Beta Tester", iteration=1, status=status, parent_agent_id=parent_agent_id, agent_type="beta_tester")

        return agent_result

    except Exception as e:
        logger.warning(f"Beta Tester agent raised exception: {e}", exc_info=True)
        terminal_ui.ui.push_agent_status(agent_id, "Beta Tester", iteration=1, status="failed", parent_agent_id=parent_agent_id, agent_type="beta_tester")
        raise
