"""Agent runner utilities for cleanup and maintenance agents."""

import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

logger = logging.getLogger(__name__)

from pokepoke.copilot import invoke_copilot
from pokepoke.git_operations import get_default_branch
from pokepoke.types import BeadsWorkItem, AgentStats
from pokepoke.stats import parse_agent_stats
from pokepoke.worktrees import create_worktree, cleanup_worktree
from pokepoke.prompts import PromptService
from pokepoke import terminal_ui
from pokepoke.cleanup_agents import invoke_cleanup_agent, invoke_merge_conflict_cleanup_agent, get_pokepoke_prompts_dir, run_cleanup_loop, aggregate_cleanup_stats
from pokepoke.worktree_cleanup import has_unmerged_worktrees

if TYPE_CHECKING:
    from pokepoke.logging_utils import ItemLogger

# Re-export cleanup agent functions for backward compatibility
__all__ = ['invoke_cleanup_agent', 'invoke_merge_conflict_cleanup_agent', 'aggregate_cleanup_stats', 'run_cleanup_loop', 'run_maintenance_agent', 'run_beta_tester', 'run_gate_agent', 'run_worktree_cleanup']


def _generate_unique_agent_id(agent_type: str) -> str:
    """Generate a unique agent ID with timestamp to avoid worktree conflicts."""
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"{agent_type}-{timestamp}"

def run_gate_agent(
    item: BeadsWorkItem,
    cwd: str | None = None,
    work_model: str | None = None,
    handoff_context: str | None = None,
) -> tuple[bool, str, AgentStats | None]:
    """Run the Gate Agent to verify a fixed work item.

    Args:
        item: The work item to verify.
        cwd: Optional working directory for the gate agent.
        work_model: Optional model that completed the work. If provided, ensures
                   gate agent uses a different model for objective verification.
        handoff_context: Optional structured context from the work agent
                        (changed files, diff stats, commit history) to inject
                        into the gate prompt so it skips re-discovering the codebase.

    Returns:
        Tuple of (success, reason, stats).
    """
    terminal_ui.ui.set_current_agent("Gate Agent")
    print(f"\n{'='*60}\n🕵️ Running Gate Agent on {item.id}\n{'='*60}")

    # Select different model for gate agent if work model provided
    gate_model = None
    if work_model:
        from pokepoke.model_selection import select_gate_model
        gate_model = select_gate_model(work_model, item.id)

    service = PromptService()
    try:
        final_prompt = service.load_and_render("gate-agent", {
            "item_id": item.id,
            "title": item.title,
            "description": item.description or "",
            "handoff_context": handoff_context or "",
            "default_branch": get_default_branch(),
        })
    except Exception as e:
        return False, f"Failed to render prompt: {e}", None

    # Gate Agent runs in the specified directory (worktree)
    # deny_write=True ensures it only reads/runs tests but doesn't modify code
    from pokepoke.metrics_context import agent_type_context
    with agent_type_context("gate"):
        result = invoke_copilot(item, prompt=final_prompt, deny_write=True, cwd=cwd, model=gate_model)

    stats = parse_agent_stats(result.output) if result.output else None

    if not result.success:
        return False, f"Gate Agent execution failed: {result.error}", stats

    # Parse output for decision
    output = result.output or ""

    # Try to find JSON block
    json_match = re.search(r'```json\s*(\{.*?\})\s*```', output, re.DOTALL)
    if json_match:
        try:
            data = json.loads(json_match.group(1))
            status = data.get("status")
            if status == "success":
                message = data.get("message", "Verification successful")
                reason = data.get("reason", "")
                recommendation = data.get("recommendation", "")

                # Build success message with context
                full_message = message
                if reason:
                    full_message = f"[{reason}] {message}"
                if recommendation:
                    full_message += f"\nRecommendation: {recommendation}"

                return True, full_message, stats
            else:
                reason = data.get("reason", "Verification failed")
                details = data.get("details", "")
                full_reason = f"{reason}\nDetails: {details}"
                return False, full_reason, stats
        except json.JSONDecodeError:
            pass

    # Fallback to text matching if JSON fails
    if "VERIFICATION SUCCESSFUL" in output:
        return True, "Verification successful (text match)", stats

    return False, "Gate Agent did not explicitly approve the fix. Check logs.", stats


def run_maintenance_agent(
    agent_name: str, prompt_file: str, repo_root: Path | None = None,
    needs_worktree: bool = True, merge_changes: bool = True,
    model: str | None = None, item_logger: 'ItemLogger | None' = None
) -> AgentStats | None:
    """Run a maintenance agent with optional worktree isolation."""
    terminal_ui.ui.set_current_agent(f"{agent_name} Agent")
    print(f"\n{'='*60}\n🔧 Running {agent_name} Agent\n{'='*60}")

    try:
        prompts_dir = get_pokepoke_prompts_dir()
        prompt_path = prompts_dir / prompt_file
    except FileNotFoundError as e:
        print(f"❌ {agent_name} Agent failed to start: {e}")
        print("   The prompts directory is missing. Ensure .pokepoke/prompts/ exists in the PokePoke installation.")
        return None

    if not prompt_path.exists():
        print(f"❌ {agent_name} Agent failed to start: prompt file '{prompt_file}' not found")
        print(f"   Expected location: {prompt_path}")
        print(f"   Available prompts: {', '.join(p.name for p in prompts_dir.glob('*.md'))}")
        return None

    agent_prompt = prompt_path.read_text(encoding='utf-8')

    # Use unique ID with timestamp to avoid worktree conflicts
    base_agent_type = f"maintenance-{agent_name.lower().replace(' ', '-')}"
    agent_id = _generate_unique_agent_id(base_agent_type) if needs_worktree else base_agent_type
    agent_item = BeadsWorkItem(
        id=agent_id, title=f"{agent_name} Maintenance", description=agent_prompt,
        status="in_progress", priority=0, issue_type="task",
        labels=["maintenance", agent_name.lower()]
    )

    # Beads-only agents run in main repo without worktree
    if not needs_worktree:
        return _run_beads_only_agent(agent_name, agent_item, agent_prompt, model=model, item_logger=item_logger)

    # Code-modifying agents need worktree isolation
    # Ensure repo_root has a value
    if repo_root is None:
        repo_root = Path.cwd()

    return _run_worktree_agent(
        agent_name, agent_id, agent_item, agent_prompt, repo_root,
        merge_changes=merge_changes, model=model, item_logger=item_logger
    )


def _run_simple_agent(
    agent_name: str, agent_item: BeadsWorkItem, agent_prompt: str, deny_write: bool = True,
    model: str | None = None, cwd: str | None = None, item_logger: 'ItemLogger | None' = None
) -> AgentStats | None:
    """Run a simple agent in the main repo with configurable write access."""
    print(f"\n📋 Running {agent_name} ({'no write' if deny_write else 'write enabled'}){f', model={model}' if model else ''}")
    from pokepoke.metrics_context import agent_type_context
    normalized = agent_name.lower().replace(" ", "_")
    with agent_type_context(normalized):
        result = invoke_copilot(agent_item, prompt=agent_prompt, deny_write=deny_write, model=model, cwd=cwd, item_logger=item_logger)
    if result.success:
        print(f"✅ {agent_name} completed")
        return parse_agent_stats(result.output) if result.output else None
    print(f"❌ {agent_name} failed: {result.error}")
    return None

def _run_beads_only_agent(agent_name: str, agent_item: BeadsWorkItem, agent_prompt: str, model: str | None = None, cwd: str | None = None, item_logger: 'ItemLogger | None' = None) -> AgentStats | None:
    """Run a beads-only maintenance agent in the main repo."""
    return _run_simple_agent(agent_name, agent_item, agent_prompt, deny_write=True, model=model, cwd=cwd, item_logger=item_logger)

def _run_main_repo_agent(agent_name: str, agent_item: BeadsWorkItem, agent_prompt: str, model: str | None = None, cwd: str | None = None, item_logger: 'ItemLogger | None' = None) -> AgentStats | None:
    """Run a maintenance agent in the main repo WITH write access."""
    return _run_simple_agent(agent_name, agent_item, agent_prompt, deny_write=False, model=model, cwd=cwd, item_logger=item_logger)


def run_worktree_cleanup(repo_root: Path | None = None, item_logger: 'ItemLogger | None' = None) -> AgentStats | None:
    """Run worktree cleanup agent to merge/delete stale worktrees."""
    terminal_ui.ui.set_current_agent("Worktree Cleanup")

    # Import here to avoid circular dependency
    from pokepoke.worktree_cleanup import retry_failed_cleanups, get_uncleaned_worktree_count

    if not has_unmerged_worktrees():
        print("\n🌳 No unmerged worktrees detected — skipping Worktree Cleanup Agent")
        return None

    agent_id = "worktree-cleanup"
    terminal_ui.ui.push_agent_status(agent_id, "Worktree Cleanup", iteration=1, status="running")
    print(f"\n{'='*60}\n🌳 Running Worktree Cleanup Agent\n{'='*60}")

    # First, try to clean up any worktrees that previously failed
    failed_count = get_uncleaned_worktree_count()
    if failed_count > 0:
        print(f"\n🔧 Pre-cleanup: Retrying {failed_count} previously failed worktree removals...")
        cleaned_count = retry_failed_cleanups()
        print(f"   Recovered {cleaned_count}/{failed_count} failed worktrees")

    try:
        try:
            prompts_dir = get_pokepoke_prompts_dir()
            prompt_path = prompts_dir / "worktree-cleanup.md"
        except FileNotFoundError as e:
            print(f"❌ {e}")
            terminal_ui.ui.push_agent_status(agent_id, "Worktree Cleanup", iteration=1, status="failed")
            return None

        if not prompt_path.exists():
            print(f"❌ Prompt not found at {prompt_path}")
            terminal_ui.ui.push_agent_status(agent_id, "Worktree Cleanup", iteration=1, status="failed")
            return None

        cleanup_prompt = prompt_path.read_text(encoding='utf-8')

        # Inject orchestrator PID as defense-in-depth against process killing.
        # The prompt prohibits process killing entirely, but if the agent ignores
        # that rule, at minimum it should know the orchestrator PID is sacred.
        orchestrator_pid = os.getpid()
        cleanup_prompt += (
            f"\n\n## ⚠️ Orchestrator Process (DO NOT TOUCH)\n\n"
            f"The PokePoke orchestrator is running as PID **{orchestrator_pid}**.\n"
            f"This process and ALL of its child processes are **absolutely off-limits**.\n"
            f"But remember: you should NEVER kill ANY processes at all.\n"
        )

        cleanup_item = BeadsWorkItem(
            id=agent_id, title="Worktree Cleanup and Merge", description=cleanup_prompt,
            status="in_progress", priority=0, issue_type="task",
            labels=["maintenance", "worktree-cleanup"]
        )

        cwd = str(repo_root) if repo_root is not None else None
        agent_result = _run_main_repo_agent("Worktree Cleanup", cleanup_item, cleanup_prompt, cwd=cwd, item_logger=item_logger)

        status = "success" if agent_result is not None else "failed"
        terminal_ui.ui.push_agent_status(agent_id, "Worktree Cleanup", iteration=1, status=status)
        return agent_result

    except Exception as e:
        logger.warning(f"Worktree cleanup agent raised exception: {e}", exc_info=True)
        terminal_ui.ui.push_agent_status(agent_id, "Worktree Cleanup", iteration=1, status="failed")
        raise


def _run_worktree_agent(
    agent_name: str, agent_id: str, agent_item: BeadsWorkItem, agent_prompt: str, repo_root: Path,
    merge_changes: bool = True, model: str | None = None, item_logger: 'ItemLogger | None' = None
) -> AgentStats | None:
    """Run a code-modifying maintenance agent in a worktree."""
    print(f"\n🌳 Creating worktree for {agent_id}...")
    try:
        worktree_path = create_worktree(agent_id)
        print(f"   Created at: {worktree_path}")
    except Exception as e:
        print(f"\n❌ Failed to create worktree: {e}")
        return None

    worktree_cwd = str(worktree_path)
    print(f"   Working directory: {worktree_cwd}\n")
    if model:
        print(f"   Model: {model}")

    worktree_cleaned = False

    try:
        # Main agent execution block
        try:
            from pokepoke.metrics_context import agent_type_context
            normalized = agent_name.lower().replace(" ", "_")
            with agent_type_context(normalized):
                result = invoke_copilot(agent_item, prompt=agent_prompt, model=model, cwd=worktree_cwd, item_logger=item_logger)
        except Exception as e:
            print(f"❌ Error invoking Copilot: {e}")
            from pokepoke.types import CopilotResult
            result = CopilotResult(
                work_item_id=agent_item.id, success=False, output="", error=str(e), attempt_count=1
            )

        cleanup_success, _ = run_cleanup_loop(
            agent_item,
            result,
            repo_root,
            cwd=worktree_cwd,
            parent_agent_id=agent_id,
        )

        if not cleanup_success:
            result.success = False

        if result.success:
            print(f"\n✅ {agent_name} agent completed successfully!")

            if not merge_changes:
                print("   Discarding worktree (merge_changes=False)")
                cleanup_worktree(agent_id, force=True)
                worktree_cleaned = True
                return parse_agent_stats(result.output) if result.output else None

            print("   All changes committed and validated")

            agent_stats = parse_agent_stats(result.output) if result.output else None

            # Handle worktree merge
            from pokepoke.worktree_merge_handler import handle_worktree_merge
            merge_success, worktree_cleaned = handle_worktree_merge(
                agent_id, agent_item, agent_name, worktree_path, repo_root, agent_stats
            )

            if not merge_success:
                return None

            print("   Merged and cleaned up worktree")
            return agent_stats
        else:
            print(f"\n❌ {agent_name} agent failed: {result.error}")
            print("\n🧹 Cleaning up worktree...")
            cleanup_worktree(agent_id, force=True)
            worktree_cleaned = True
            return None

    finally:
        # Ensure worktree is cleaned up if not already done
        if not worktree_cleaned:
            print(f"\n🧹 Final cleanup: removing worktree {agent_id}...")
            try:
                cleanup_worktree(agent_id, force=True)
                # Remove from manifest if it was added
                from pokepoke.worktree_cleanup import remove_from_manifest
                remove_from_manifest(agent_id)
            except Exception as cleanup_error:
                print(f"⚠️  Final cleanup failed: {cleanup_error}")
                # Track failed cleanup in manifest
                from pokepoke.worktree_cleanup import add_uncleaned_worktree
                add_uncleaned_worktree(
                    agent_id,
                    str(worktree_path),
                    f"Failed final cleanup: {cleanup_error}"
                )


# Re-export beta tester for backward compatibility
from pokepoke.beta_tester import run_beta_tester  # noqa: E402,F401
