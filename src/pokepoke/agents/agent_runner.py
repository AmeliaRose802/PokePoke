"""Agent runner utilities for cleanup and maintenance agents."""

import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

logger = logging.getLogger(__name__)

from pokepoke.models.ai_backends import invoke_copilot
from pokepoke.utils.constants import STATUS_IN_PROGRESS
from pokepoke.git.git_operations import get_default_branch
from pokepoke.types import BeadsWorkItem, AgentStats, GateAgentResult, CopilotResult
from pokepoke.stats.stats import parse_agent_stats
from pokepoke.worktrees.worktrees import create_worktree, cleanup_worktree
from pokepoke.prompts.prompts import PromptService
from pokepoke.desktop import terminal_ui
from pokepoke.agents.cleanup_agents import invoke_cleanup_agent, invoke_merge_conflict_cleanup_agent, get_pokepoke_prompts_dir, run_cleanup_loop, aggregate_cleanup_stats
from pokepoke.worktrees.worktree_cleanup import has_unmerged_worktrees, retry_failed_cleanups, get_uncleaned_worktree_count, add_uncleaned_worktree, remove_from_manifest
from pokepoke.models.model_selection import select_gate_model
from pokepoke.models.sdk_helpers import build_gate_resume_prompt
from pokepoke.stats.metrics_context import agent_type_context
from pokepoke.stats.gate_rejection_tracker import record_gate_check
from pokepoke.worktrees.worktree_merge_handler import handle_worktree_merge

if TYPE_CHECKING:
    from pokepoke.utils.logging_utils import ItemLogger
__all__ = ['invoke_cleanup_agent', 'invoke_merge_conflict_cleanup_agent', 'aggregate_cleanup_stats', 'run_cleanup_loop', 'run_maintenance_agent', 'run_beta_tester', 'run_gate_agent', 'run_worktree_cleanup']

def _generate_unique_agent_id(agent_type: str) -> str:
    """Generate a unique agent ID with timestamp to avoid worktree conflicts."""
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"{agent_type}-{timestamp}"

def _print_preserved_worktree_debug(agent_id: str, worktree_path: Path, repo_root: Path) -> None:
    logger.info("Worktree preserved at %s — logs: %s/.pokepoke/logs/ — cleanup: cleanup_worktree('%s', force=True)", worktree_path, repo_root, agent_id)

def run_gate_agent(
    item: BeadsWorkItem,
    cwd: str | None = None,
    work_model: str | None = None,
    handoff_context: str | None = None,
    agent_id: str | None = None,
    agent_iteration: int = 1,
    parent_agent_id: str | None = None,
    item_logger: 'ItemLogger | None' = None,
    session_id: str | None = None,
    is_resume: bool = False,
) -> 'GateAgentResult':
    """Run the Gate Agent to verify a fixed work item."""
    terminal_ui.ui.set_current_agent("Gate Agent")
    print(f"\n{'='*60}\n🕵️ Running Gate Agent on {item.id}\n{'='*60}")

    gate_model = None
    if work_model:
        gate_model = select_gate_model(work_model, item.id)
    # Build prompt: use resume prompt if continuing a timed-out session
    if is_resume and session_id:
        final_prompt = build_gate_resume_prompt(
            item,
            handoff_context=handoff_context,
            previous_output_summary=None,
            default_branch=get_default_branch(),
        )
    else:
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
            return GateAgentResult(
                success=False, reason=f"Failed to render prompt: {e}",
                crashed=True,
            )
    with agent_type_context("gate"):
        if agent_id:
            terminal_ui.ui.push_agent_status(
                agent_id, "Gate Agent", iteration=agent_iteration, status="running",
                parent_agent_id=parent_agent_id, work_item_id=item.id, work_item_title=item.title,
                agent_type="gate",
                agent_prompt=final_prompt,
            )
        result = invoke_copilot(
            item, prompt=final_prompt, deny_write=True, cwd=cwd,
            model=gate_model, item_logger=item_logger,
            session_id=session_id, is_resume=is_resume,
        )

    stats = parse_agent_stats(result.output) if result.output else None
    # Determine gate outcome and record for rejection rate tracking
    def _finish(success: bool, reason: str, crashed: bool,
                is_timeout: bool = False) -> 'GateAgentResult':
        if gate_model and not crashed:
            record_gate_check(gate_model, item.id, success)
        return GateAgentResult(
            success=success, reason=reason, stats=stats, crashed=crashed,
            is_timeout=is_timeout,
            session_id=result.session_id,
            last_output_summary=result.last_output_summary,
        )
    if not result.success:
        # Distinguish timeout from generic crash
        is_timeout = bool(
            result.error
            and ("timeout" in result.error.lower()
                 or "inactivity" in result.error.lower())
        )
        return _finish(
            False, f"Gate Agent execution failed: {result.error}",
            crashed=not is_timeout, is_timeout=is_timeout,
        )
    output = result.output or ""
    json_match = re.search(r'```json\s*(\{.*\})\s*```', output, re.DOTALL)
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

                return _finish(True, full_message, crashed=False)
            else:
                reason = data.get("reason", "Verification failed")
                details = data.get("details", "")
                full_reason = f"{reason}\nDetails: {details}"
                return _finish(False, full_reason, crashed=False)
        except json.JSONDecodeError:
            pass
    if "VERIFICATION SUCCESSFUL" in output or "NEW_WORK_VERIFIED" in output:
        return _finish(True, "Verification successful (text match)", crashed=False)
    return _finish(False, "Gate Agent did not explicitly approve the fix. Check logs.", crashed=False)

def run_maintenance_agent(
    agent_name: str, prompt_file: str, repo_root: Path | None = None,
    needs_worktree: bool = True, merge_changes: bool = True,
    model: str | None = None, item_logger: 'ItemLogger | None' = None,
    parent_agent_id: str | None = None
) -> AgentStats | None:
    """Run a maintenance agent with optional worktree isolation."""
    terminal_ui.ui.set_current_agent(f"{agent_name} Agent")
    print(f"\n{'='*60}\n🔧 Running {agent_name} Agent\n{'='*60}")

    try:
        prompts_dir = get_pokepoke_prompts_dir()
        prompt_path = prompts_dir / prompt_file
    except FileNotFoundError as e:
        logger.error("%s Agent failed to start: %s", agent_name, e)
        logger.error("The prompts directory is missing. Ensure .pokepoke/prompts/ exists in the PokePoke installation.")
        return None
    if not prompt_path.exists():
        logger.error(
            "%s Agent failed to start: prompt file '%s' not found (expected: %s, available: %s)",
            agent_name, prompt_file, prompt_path,
            ", ".join(p.name for p in prompts_dir.glob("*.md")),
        )
        return None
    agent_prompt = prompt_path.read_text(encoding='utf-8')
    # Use unique ID with timestamp to avoid worktree conflicts
    base_agent_type = f"maintenance-{agent_name.lower().replace(' ', '-')}"
    agent_id = _generate_unique_agent_id(base_agent_type) if needs_worktree else base_agent_type
    agent_item = BeadsWorkItem(
        id=agent_id, title=f"{agent_name} Maintenance", description=agent_prompt,
        status=STATUS_IN_PROGRESS, priority=0, issue_type="task",
        labels=["maintenance", agent_name.lower()]
    )
    if not needs_worktree:
        return _run_beads_only_agent(agent_name, agent_item, agent_prompt, model=model, item_logger=item_logger)

    if repo_root is None:
        repo_root = Path.cwd()

    return _run_worktree_agent(
        agent_name, agent_id, agent_item, agent_prompt, repo_root,
        merge_changes=merge_changes, model=model, item_logger=item_logger,
        parent_agent_id=parent_agent_id
    )

def _run_simple_agent(
    agent_name: str, agent_item: BeadsWorkItem, agent_prompt: str, deny_write: bool = True,
    model: str | None = None, cwd: str | None = None, item_logger: 'ItemLogger | None' = None
) -> AgentStats | None:
    """Run a simple agent in the main repo with configurable write access."""
    logger.info("Running %s (%s)%s", agent_name, "no write" if deny_write else "write enabled", f", model={model}" if model else "")
    normalized = agent_name.lower().replace(" ", "_")
    with agent_type_context(normalized):
        result = invoke_copilot(agent_item, prompt=agent_prompt, deny_write=deny_write, model=model, cwd=cwd, item_logger=item_logger)
    if result.success:
        logger.info("%s completed", agent_name)
        return (parse_agent_stats(result.output) if result.output else None) or AgentStats()
    logger.error("%s failed: %s", agent_name, result.error)
    return None

def _run_beads_only_agent(agent_name: str, agent_item: BeadsWorkItem, agent_prompt: str, model: str | None = None, cwd: str | None = None, item_logger: 'ItemLogger | None' = None) -> AgentStats | None:
    """Run a beads-only maintenance agent in the main repo."""
    return _run_simple_agent(agent_name, agent_item, agent_prompt, deny_write=True, model=model, cwd=cwd, item_logger=item_logger)

def _run_main_repo_agent(agent_name: str, agent_item: BeadsWorkItem, agent_prompt: str, model: str | None = None, cwd: str | None = None, item_logger: 'ItemLogger | None' = None) -> AgentStats | None:
    """Run a maintenance agent in the main repo WITH write access."""
    return _run_simple_agent(agent_name, agent_item, agent_prompt, deny_write=False, model=model, cwd=cwd, item_logger=item_logger)

def run_worktree_cleanup(repo_root: Path | None = None, item_logger: 'ItemLogger | None' = None, parent_agent_id: str | None = None) -> AgentStats | None:
    """Run worktree cleanup agent to merge/delete stale worktrees."""
    terminal_ui.ui.set_current_agent("Worktree Cleanup")

    if not has_unmerged_worktrees():
        logger.info("No unmerged worktrees detected — skipping Worktree Cleanup Agent")
        return None

    agent_id = "worktree-cleanup"
    terminal_ui.ui.push_agent_status(agent_id, "Worktree Cleanup", iteration=1, status="running", parent_agent_id=parent_agent_id, agent_type="worktree_cleanup")
    print(f"\n{'='*60}\n🌳 Running Worktree Cleanup Agent\n{'='*60}")

    failed_count = get_uncleaned_worktree_count()
    if failed_count > 0:
        logger.info("Pre-cleanup: Retrying %d previously failed worktree removals...", failed_count)
        cleaned_count = retry_failed_cleanups()
        logger.info("Recovered %d/%d failed worktrees", cleaned_count, failed_count)

    try:
        try:
            prompts_dir = get_pokepoke_prompts_dir()
            prompt_path = prompts_dir / "worktree-cleanup.md"
        except FileNotFoundError as e:
            logger.error("Worktree cleanup failed: %s", e)
            terminal_ui.ui.push_agent_status(agent_id, "Worktree Cleanup", iteration=1, status="failed", parent_agent_id=parent_agent_id, agent_type="worktree_cleanup")
            return None

        if not prompt_path.exists():
            logger.error("Prompt not found at %s", prompt_path)
            terminal_ui.ui.push_agent_status(agent_id, "Worktree Cleanup", iteration=1, status="failed", parent_agent_id=parent_agent_id, agent_type="worktree_cleanup")
            return None

        cleanup_prompt = prompt_path.read_text(encoding='utf-8')

        orchestrator_pid = os.getpid()
        cleanup_prompt += (
            f"\n\n## ⚠️ Orchestrator Process (DO NOT TOUCH)\n\n"
            f"The PokePoke orchestrator is running as PID **{orchestrator_pid}**.\n"
            f"This process and ALL of its child processes are **absolutely off-limits**.\n"
            f"But remember: you should NEVER kill ANY processes at all.\n"
        )
        terminal_ui.ui.push_agent_status(
            agent_id, "Worktree Cleanup", iteration=1, status="running",
            parent_agent_id=parent_agent_id, agent_type="worktree_cleanup",
            agent_prompt=cleanup_prompt,
        )

        cleanup_item = BeadsWorkItem(
            id=agent_id, title="Worktree Cleanup and Merge", description=cleanup_prompt,
            status=STATUS_IN_PROGRESS, priority=0, issue_type="task",
            labels=["maintenance", "worktree-cleanup"]
        )

        cwd = str(repo_root) if repo_root is not None else None
        agent_result = _run_main_repo_agent("Worktree Cleanup", cleanup_item, cleanup_prompt, cwd=cwd, item_logger=item_logger)

        status = "success" if agent_result is not None else "failed"
        terminal_ui.ui.push_agent_status(agent_id, "Worktree Cleanup", iteration=1, status=status, parent_agent_id=parent_agent_id, agent_type="worktree_cleanup")
        return agent_result

    except Exception as e:
        logger.warning(f"Worktree cleanup agent raised exception: {e}", exc_info=True)
        terminal_ui.ui.push_agent_status(agent_id, "Worktree Cleanup", iteration=1, status="failed", parent_agent_id=parent_agent_id, agent_type="worktree_cleanup")
        return None

def _run_worktree_agent(
    agent_name: str, agent_id: str, agent_item: BeadsWorkItem, agent_prompt: str, repo_root: Path,
    merge_changes: bool = True, model: str | None = None, item_logger: 'ItemLogger | None' = None,
    parent_agent_id: str | None = None
) -> AgentStats | None:
    """Run a code-modifying maintenance agent in a worktree."""
    logger.info("Creating worktree for %s...", agent_id)
    try:
        worktree_path = create_worktree(agent_id)
        logger.info("Worktree created at: %s", worktree_path)
    except Exception as e:
        logger.error("Failed to create worktree: %s", e)
        return None

    worktree_cwd = str(worktree_path)
    logger.debug("Working directory: %s", worktree_cwd)
    if model:
        logger.debug("Model: %s", model)
    worktree_cleaned = False
    preserve_for_debugging = True
    cleanup_parent_id = parent_agent_id if parent_agent_id else agent_id
    try:
        try:
            normalized = agent_name.lower().replace(" ", "_")
            with agent_type_context(normalized):
                terminal_ui.ui.push_agent_status(
                    agent_id, f"{agent_name} Agent", iteration=1, status="running",
                    parent_agent_id=parent_agent_id,
                    agent_type=normalized,
                    agent_prompt=agent_prompt,
                )
                result = invoke_copilot(agent_item, prompt=agent_prompt, model=model, cwd=worktree_cwd, item_logger=item_logger)
        except Exception as e:
            logger.error("Error invoking Copilot: %s", e)
            result = CopilotResult(
                work_item_id=agent_item.id, success=False, output="", error=str(e), attempt_count=1
            )

        cleanup_success, _ = run_cleanup_loop(
            agent_item,
            result,
            cwd=worktree_cwd,
            parent_agent_id=cleanup_parent_id,
        )

        if not cleanup_success:
            result.success = False

        if result.success:
            logger.info("%s agent completed successfully!", agent_name)
            if not merge_changes:
                logger.info("Discarding worktree (merge_changes=False)")
                try:
                    cleanup_worktree(agent_id, force=True)
                    worktree_cleaned = True
                    preserve_for_debugging = False
                    return parse_agent_stats(result.output) if result.output else None
                except Exception as cleanup_error:
                    logger.warning("Explicit cleanup failed: %s", cleanup_error)
                    add_uncleaned_worktree(
                        agent_id,
                        str(worktree_path),
                        f"Failed explicit cleanup: {cleanup_error}",
                    )
                    return None
            logger.info("All changes committed and validated")
            agent_stats = parse_agent_stats(result.output) if result.output else None
            merge_success, worktree_cleaned = handle_worktree_merge(
                agent_id, agent_item, agent_name, worktree_path, repo_root, agent_stats,
                parent_agent_id=cleanup_parent_id
            )

            if not merge_success:
                _print_preserved_worktree_debug(agent_id, worktree_path, repo_root)
                return None
            preserve_for_debugging = not worktree_cleaned
            logger.info("Merged and cleaned up worktree")
            return agent_stats
        else:
            logger.error("%s agent failed: %s", agent_name, result.error)
            _print_preserved_worktree_debug(agent_id, worktree_path, repo_root)
            return None

    except Exception as e:
        logger.warning(
            f"Unhandled error while running {agent_name} in worktree {agent_id}: {e}",
            exc_info=True,
        )
        logger.error("Unexpected error in %s agent: %s", agent_name, e)
        _print_preserved_worktree_debug(agent_id, worktree_path, repo_root)
        return None

    finally:
        if preserve_for_debugging:
            logger.info("Worktree preserved at %s — manual cleanup required", worktree_path)
        elif not worktree_cleaned:
            logger.info("Final cleanup: removing worktree %s...", agent_id)
            try:
                cleanup_worktree(agent_id, force=True)
                remove_from_manifest(agent_id)
            except Exception as cleanup_error:
                logger.warning("Final cleanup failed: %s", cleanup_error)
                add_uncleaned_worktree(agent_id, str(worktree_path), f"Failed final cleanup: {cleanup_error}")

# Re-export beta tester for backward compatibility
from pokepoke.agents.beta_tester import run_beta_tester  # noqa: E402,F401
