"""Beta tester agent — tests all MCP tools in an isolated worktree."""

import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from pokepoke.config import get_config
from pokepoke.types import BeadsWorkItem, AgentStats
from pokepoke import terminal_ui
from pokepoke.cleanup_agents import get_pokepoke_prompts_dir

if TYPE_CHECKING:
    from pokepoke.logging_utils import ItemLogger


def run_beta_tester(repo_root: Path | None = None, item_logger: 'ItemLogger | None' = None) -> AgentStats | None:
    """Run beta tester agent to test all MCP tools. Restarts MCP server first."""
    from pokepoke.agent_runner import _generate_unique_agent_id, _run_worktree_agent

    config = get_config()
    terminal_ui.ui.set_current_agent("Beta Tester")

    # Register Beta Tester agent in the Agents panel (if not already registered by maintenance)
    agent_id = "beta-tester"
    terminal_ui.ui.push_agent_status(agent_id, "Beta Tester", iteration=1, status="running")

    print(f"\n{'='*60}\n🧪 Running Beta Tester Agent\n{'='*60}")

    try:
        # Restart MCP server to load latest code (if configured)
        if config.mcp_server.enabled and config.mcp_server.restart_script:
            print("\n🔄 Restarting MCP server...")
            try:
                package_root = Path(__file__).resolve().parent.parent.parent
                restart_script = package_root / config.mcp_server.restart_script

                if not restart_script.exists():
                    print(f"⚠️  Restart script not found at {restart_script}")
                    print("   Proceeding without restart - server may have stale code")
                else:
                    result = subprocess.run(
                        ["pwsh", "-NoProfile", "-File", str(restart_script)],
                        capture_output=True, text=True, encoding='utf-8', timeout=60
                    )
                    if result.returncode == 0:
                        print("✓ MCP server restarted successfully")
                    else:
                        print(f"⚠️  MCP server restart had issues (exit code {result.returncode})")
                        if result.stdout:
                            print(f"   Output: {result.stdout[:200]}")
            except subprocess.TimeoutExpired:
                print("⚠️  MCP server restart timed out (server may still be starting)")
            except Exception as e:
                print(f"⚠️  Could not restart MCP server: {e}")
                print("   Proceeding anyway - server may have stale code")
        elif not config.mcp_server.enabled:
            print("ℹ️  MCP server not enabled in config - skipping restart")

        # Load beta tester prompt
        try:
            prompts_dir = get_pokepoke_prompts_dir()
            prompt_path = prompts_dir / "beta-tester.md"
        except FileNotFoundError as e:
            print(f"❌ {e}")
            terminal_ui.ui.push_agent_status(agent_id, "Beta Tester", iteration=1, status="failed")
            return None

        if not prompt_path.exists():
            print(f"❌ Prompt not found at {prompt_path}")
            terminal_ui.ui.push_agent_status(agent_id, "Beta Tester", iteration=1, status="failed")
            return None

        beta_prompt = prompt_path.read_text(encoding='utf-8')

        # Use unique ID with timestamp to avoid worktree conflicts on multiple runs
        worktree_agent_id = _generate_unique_agent_id("beta-tester")
        beta_item = BeadsWorkItem(
            id=worktree_agent_id, title="Beta Test All MCP Tools", description=beta_prompt,
            status="in_progress", priority=2, issue_type="task",
            labels=["testing", "mcp-server", "automated"]
        )

        print("\n🧪 Invoking beta tester agent in isolated worktree (will be discarded)...")
        if repo_root is None:
            repo_root = Path.cwd()

        agent_result = _run_worktree_agent("Beta Tester", worktree_agent_id, beta_item, beta_prompt, repo_root, merge_changes=False, item_logger=item_logger)

        # Update agent status based on result
        status = "success" if agent_result is not None else "failed"
        terminal_ui.ui.push_agent_status(agent_id, "Beta Tester", iteration=1, status=status)

        return agent_result

    except Exception:
        terminal_ui.ui.push_agent_status(agent_id, "Beta Tester", iteration=1, status="failed")
        raise
