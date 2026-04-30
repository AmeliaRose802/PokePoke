"""PokePoke CLI entry point.

Extracted from orchestrator.py to keep that module under the
400-line limit enforced by the pre-commit hook.
"""
import argparse
import logging
import os
import sys
from pathlib import Path

from pokepoke.desktop import terminal_ui
from pokepoke.orchestration.orchestrator import run_orchestrator

logger = logging.getLogger(__name__)

def main() -> int:
    """Main entry point for PokePoke CLI."""
    # Ensure stdout/stderr use UTF-8 so emoji display correctly on Windows
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(
        description="PokePoke - Autonomous Beads + Copilot SDK Orchestrator"
    )
    parser.add_argument("--interactive", action="store_true", default=True,
                        help="Interactive mode: prompt for user input (default)")
    parser.add_argument("--autonomous", action="store_true",
                        help="Autonomous mode: automatic decision making")
    parser.add_argument("--continuous", action="store_true",
                        help="Continuous mode: loop through multiple items")
    parser.add_argument("--beta-first", action="store_true",
                        help="Run beta tester at startup before work items")
    parser.add_argument("--agent-name", type=str, default=None,
                        help="Custom agent name instead of auto-generating")
    parser.add_argument("--init", action="store_true",
                        help="Initialize .pokepoke/ directory with sample config")
    parser.add_argument("--max-agents", type=int, default=None, metavar="N",
                        help="Max concurrent work-item agents (default: from config)")
    parser.add_argument("--repo", type=str, default=None, metavar="PATH",
                        help="Path to the repository to work in (changes cwd)")
    args = parser.parse_args()

    # --repo changes working directory before anything else
    if args.repo:
        repo_path = Path(args.repo).resolve()
        if not repo_path.is_dir():
            logger.info(f"\u274c  --repo path does not exist: {repo_path}")
            return 1
        os.chdir(repo_path)
    elif getattr(sys, 'frozen', False):
        from pokepoke.git.repo_picker import pick_repo_directory
        launch_config = pick_repo_directory()
        if launch_config is None:
            return 0
        os.chdir(launch_config.repo_path)
        if args.max_agents is None and launch_config.max_agents > 1:
            args.max_agents = launch_config.max_agents

    if args.init:
        from pokepoke.init import init_project
        return 0 if init_project() else 1

    # Autonomous flag overrides interactive
    interactive = not args.autonomous

    from pokepoke.desktop.desktop_ui import DesktopUI
    from pokepoke.utils.project_utils import ensure_project_ready
    active_ui: DesktopUI = terminal_ui.ui

    desktop_ui_ref = active_ui if isinstance(active_ui, DesktopUI) else None

    def orchestrator_func() -> int:
        if not ensure_project_ready(interactive, desktop_ui_ref):
            return 1
        return run_orchestrator(
            interactive=interactive,
            continuous=args.continuous,
            run_beta_first=args.beta_first,
            agent_name_override=args.agent_name,
            max_parallel_agents=args.max_agents,
        )

    return active_ui.run_with_orchestrator(orchestrator_func)


if __name__ == "__main__":
    sys.exit(main())
