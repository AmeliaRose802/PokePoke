"""Agent runner utilities for cleanup and maintenance agents."""
import logging
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from pokepoke.constants import SUBPROCESS_ERRORS, SUBPROCESS_OR_RUNTIME_ERRORS, SUBPROCESS_RUNTIME_VALUE_ERRORS

logger = logging.getLogger(__name__)

from pokepoke.agents.cleanup_agents import (
    aggregate_cleanup_stats,
    get_pokepoke_prompts_dir,
    invoke_cleanup_agent,
    invoke_merge_conflict_cleanup_agent,
    run_cleanup_loop,
)
from pokepoke.agents.gate_agent_executor import run_gate_agent
from pokepoke.agents.simple_runners import (
    _extract_stats,
    _run_beads_only_agent,
    _run_main_repo_agent,
)
from pokepoke.beads.reconciliation import worktree_branch_has_commits
from pokepoke.desktop import terminal_ui
from pokepoke.models.ai_backends import invoke_copilot
from pokepoke.stats.metrics_context import agent_type_context
from pokepoke.types import AgentStats, BeadsWorkItem
from pokepoke.types_agent import CopilotResult
from pokepoke.utils.constants import STATUS_IN_PROGRESS
from pokepoke.worktrees.worktree_cleanup import (
    add_uncleaned_worktree,
    get_uncleaned_worktree_count,
    has_unmerged_worktrees,
    remove_from_manifest,
    retry_failed_cleanups,
)
from pokepoke.worktrees.worktree_merge_handler import WorktreeMergeContext, handle_worktree_merge
from pokepoke.worktrees.worktrees import cleanup_worktree, create_worktree

if TYPE_CHECKING:
    from pokepoke.utils.logging_utils import ItemLogger

__all__ = ['aggregate_cleanup_stats', 'invoke_cleanup_agent', 'invoke_merge_conflict_cleanup_agent', 'run_beta_tester', 'run_cleanup_loop', 'run_gate_agent', 'run_maintenance_agent', 'run_worktree_cleanup']


@dataclass
class AgentRunnerConfig:
    """Configuration for agent runner operations.

    Bundles shared parameters to reduce function parameter counts.
    """
    agent_name: str
    agent_id: str
    agent_item: BeadsWorkItem
    repo_root: Path
    worktree_path: Path
    model: str | None = None
    item_logger: 'ItemLogger | None' = None

def _generate_unique_agent_id(agent_type: str) -> str:
    """Generate a unique agent ID with timestamp to avoid worktree conflicts."""
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"{agent_type}-{timestamp}"

def _print_preserved_worktree_debug(agent_id: str, worktree_path: Path, repo_root: Path) -> None:
    logger.info("Worktree preserved at %s — logs: %s/.pokepoke/logs/ — cleanup: cleanup_worktree('%s', force=True)", worktree_path, repo_root, agent_id)


def run_maintenance_agent(
    agent_name: str,
    prompt_file: str,
    *,
    repo_root: Path | None = None,
    needs_worktree: bool = True,
    needs_shell: bool = False,
    merge_changes: bool = True,
    model: str | None = None,
    item_logger: 'ItemLogger | None' = None,
    parent_agent_id: str | None = None
) -> AgentStats | None:
    """Run a maintenance agent with optional worktree isolation."""
    terminal_ui.ui.set_current_agent(f"{agent_name} Agent")
    logger.info(f"\n{'='*60}\n🔧 Running {agent_name} Agent\n{'='*60}")

    try:
        prompts_dir = get_pokepoke_prompts_dir()
        prompt_path = prompts_dir / prompt_file
    except FileNotFoundError as e:
        msg = f"{agent_name} Agent failed to start: {e}"
        logger.error("%s", msg)
        logger.error("The prompts directory is missing. Ensure .pokepoke/prompts/ exists in the PokePoke installation.")
        if item_logger:
            item_logger.log_error(msg)
        return None
    if not prompt_path.exists():
        msg = (
            f"{agent_name} Agent failed to start: prompt file '{prompt_file}' not found "
            f"(expected: {prompt_path}, available: {', '.join(p.name for p in prompts_dir.glob('*.md'))})"
        )
        logger.error("%s", msg)
        if item_logger:
            item_logger.log_error(msg)
        return None
    agent_prompt = prompt_path.read_text(encoding='utf-8')
    # Use unique ID with timestamp to avoid worktree conflicts
    base_agent_type = f"maintenance-{agent_name.lower().replace(' ', '-')}"
    agent_id = _generate_unique_agent_id(base_agent_type) if needs_worktree else base_agent_type
    agent_item = BeadsWorkItem(
        id=agent_id, title=f"{agent_name} Maintenance", description=agent_prompt,
        status=STATUS_IN_PROGRESS, priority=0, issue_type="task",
        labels=["maintenance", agent_name.lower()],
        is_ephemeral=True,
    )

    if repo_root is None:
        repo_root = Path.cwd()

    # Create config object
    config = AgentRunnerConfig(
        agent_name=agent_name,
        agent_id=agent_id,
        agent_item=agent_item,
        repo_root=repo_root,
        worktree_path=repo_root,  # Updated in _run_worktree_agent if needed
        model=model,
        item_logger=item_logger,
    )

    if not needs_worktree:
        if needs_shell:
            return _run_main_repo_agent(config, agent_prompt)
        return _run_beads_only_agent(config, agent_prompt)

    return _run_worktree_agent(
        config, agent_prompt,
        merge_changes=merge_changes,
        parent_agent_id=parent_agent_id
    )

def run_worktree_cleanup(repo_root: Path | None = None, item_logger: 'ItemLogger | None' = None, parent_agent_id: str | None = None) -> AgentStats | None:
    """Run worktree cleanup agent to merge/delete stale worktrees."""
    terminal_ui.ui.set_current_agent("Worktree Cleanup")

    if not has_unmerged_worktrees():
        logger.info("No unmerged worktrees detected — skipping Worktree Cleanup Agent")
        return None

    agent_id = "worktree-cleanup"
    terminal_ui.ui.push_agent_status(agent_id, "Worktree Cleanup", iteration=1, status="running", parent_agent_id=parent_agent_id, agent_type="worktree_cleanup")
    logger.info(f"\n{'='*60}\n🌳 Running Worktree Cleanup Agent\n{'='*60}")

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
            labels=["maintenance", "worktree-cleanup"],
            is_ephemeral=True,
        )

        # Create config object for cleanup agent
        config = AgentRunnerConfig(
            agent_name="Worktree Cleanup",
            agent_id=agent_id,
            agent_item=cleanup_item,
            repo_root=repo_root or Path.cwd(),
            worktree_path=repo_root or Path.cwd(),  # Uses main repo
            model=None,
            item_logger=item_logger,
        )

        cwd = str(repo_root) if repo_root is not None else None
        agent_result = _run_main_repo_agent(config, cleanup_prompt, cwd=cwd, add_parent_dir=True)
        status = "success" if agent_result is not None else "failed"
        terminal_ui.ui.push_agent_status(agent_id, "Worktree Cleanup", iteration=1, status=status, parent_agent_id=parent_agent_id, agent_type="worktree_cleanup")
        return agent_result

    except SUBPROCESS_RUNTIME_VALUE_ERRORS as e:
        logger.warning(f"Worktree cleanup agent raised exception: {e}", exc_info=True)
        terminal_ui.ui.push_agent_status(agent_id, "Worktree Cleanup", iteration=1, status="failed", parent_agent_id=parent_agent_id, agent_type="worktree_cleanup")
        return None

def _reconcile_worktree_branch(
    config: AgentRunnerConfig,
    result: CopilotResult,
    cleanup_parent_id: str,
) -> AgentStats | None:
    """Attempt to merge partial work when a worktree branch has commits.

    Called on the failure path of ``_run_worktree_agent`` to rescue valid
    commits that would otherwise be stranded (e.g. when the SDK session
    exhausted its turn/token budget but had already committed work).

    Returns ``AgentStats`` (possibly empty) on successful merge, or ``None``
    if there are no commits to salvage or the merge fails.
    """
    try:
        if not worktree_branch_has_commits(config.agent_id, config.repo_root):
            return None
    except SUBPROCESS_ERRORS as exc:
        logger.debug("Reconciliation check failed for %s: %s", config.agent_id, exc)
        return None

    logger.warning(
        "Reconciliation: %s failed but worktree branch has commits — "
        "attempting merge of partial work",
        config.agent_name,
    )
    agent_stats = _extract_stats(result)
    merge_success, _worktree_cleaned = handle_worktree_merge(
        WorktreeMergeContext(
            agent_id=config.agent_id,
            agent_item=config.agent_item,
            agent_name=config.agent_name,
            worktree_path=config.worktree_path,
            repo_root=config.repo_root,
            parent_agent_id=cleanup_parent_id,
        ),
        agent_stats,
    )
    if merge_success:
        logger.info("Reconciliation: merged partial work from %s", config.agent_name)
        return agent_stats if agent_stats is not None else AgentStats()
    logger.warning("Reconciliation: merge failed for %s", config.agent_name)
    return None


def _handle_successful_agent(
    config: AgentRunnerConfig,
    result: CopilotResult,
    merge_changes: bool,
    cleanup_parent_id: str,
) -> tuple[AgentStats | None, bool, bool]:
    """Handle the success path for a worktree agent.

    Returns ``(agent_stats, preserve_for_debugging, worktree_cleaned)``.
    """
    logger.info("%s agent completed successfully!", config.agent_name)
    if not merge_changes:
        logger.info("Discarding worktree (merge_changes=False)")
        try:
            cleanup_worktree(config.agent_id, force=True)
            return _extract_stats(result) or AgentStats(), False, True
        except SUBPROCESS_OR_RUNTIME_ERRORS as cleanup_error:
            logger.warning("Explicit cleanup failed: %s", cleanup_error)
            add_uncleaned_worktree(
                config.agent_id, str(config.worktree_path),
                f"Failed explicit cleanup: {cleanup_error}",
            )
            return None, True, False

    logger.info("All changes committed and validated")
    agent_stats = _extract_stats(result) or AgentStats()
    merge_success, worktree_cleaned = handle_worktree_merge(
        WorktreeMergeContext(
            agent_id=config.agent_id,
            agent_item=config.agent_item,
            agent_name=config.agent_name,
            worktree_path=config.worktree_path,
            repo_root=config.repo_root,
            parent_agent_id=cleanup_parent_id,
        ),
        agent_stats,
    )
    if not merge_success:
        _print_preserved_worktree_debug(config.agent_id, config.worktree_path, config.repo_root)
        return None, True, False
    logger.info("Merged and cleaned up worktree")
    return agent_stats, not worktree_cleaned, worktree_cleaned


def _run_worktree_agent(
    config: AgentRunnerConfig,
    agent_prompt: str,
    *,
    merge_changes: bool = True,
    parent_agent_id: str | None = None
) -> AgentStats | None:
    """Run a code-modifying maintenance agent in a worktree."""
    logger.info("Creating worktree for %s...", config.agent_id)
    try:
        worktree_path = create_worktree(config.agent_id)
        logger.info("Worktree created at: %s", worktree_path)
    except SUBPROCESS_OR_RUNTIME_ERRORS as e:
        msg = f"Failed to create worktree for {config.agent_name}: {e}"
        logger.error("%s", msg)
        if config.item_logger:
            config.item_logger.log_error(msg)
        return None

    # Update config with actual worktree path
    config.worktree_path = worktree_path

    worktree_cwd = str(worktree_path)
    logger.debug("Working directory: %s", worktree_cwd)
    if config.model:
        logger.debug("Model: %s", config.model)
    worktree_cleaned = False
    preserve_for_debugging = True
    cleanup_parent_id = parent_agent_id if parent_agent_id else config.agent_id
    try:
        try:
            normalized = config.agent_name.lower().replace(" ", "_")
            with agent_type_context(normalized):
                terminal_ui.ui.push_agent_status(
                    config.agent_id, f"{config.agent_name} Agent", iteration=1, status="running",
                    parent_agent_id=parent_agent_id,
                    agent_type=normalized,
                    agent_prompt=agent_prompt,
                )
                result = invoke_copilot(config.agent_item, prompt=agent_prompt, model=config.model, cwd=worktree_cwd, item_logger=config.item_logger)
        except SUBPROCESS_OR_RUNTIME_ERRORS as e:
            logger.error("Error invoking Copilot: %s", e)
            result = CopilotResult(
                work_item_id=config.agent_item.id, success=False, output="", error=str(e), attempt_count=1
            )
        cleanup_success, _ = run_cleanup_loop(
            config.agent_item,
            result,
            cwd=worktree_cwd,
            parent_agent_id=cleanup_parent_id,
        )
        if not cleanup_success:
            result.success = False
        if result.success:
            agent_stats, preserve_for_debugging, worktree_cleaned = _handle_successful_agent(
                config, result, merge_changes, cleanup_parent_id,
            )
            return agent_stats
        else:
            logger.error("%s agent failed: %s", config.agent_name, result.error)
            # Reconciliation: merge partial work when the branch has valid
            # commits despite the session reporting failure (e.g. budget
            # exhaustion).
            if merge_changes:
                reconciled_stats = _reconcile_worktree_branch(
                    config, result, cleanup_parent_id,
                )
                if reconciled_stats is not None:
                    agent_stats = reconciled_stats
                    preserve_for_debugging = False
                    worktree_cleaned = True
                    return agent_stats
            _print_preserved_worktree_debug(config.agent_id, worktree_path, config.repo_root)
            return None

    except SUBPROCESS_RUNTIME_VALUE_ERRORS as e:
        logger.warning(
            f"Unhandled error while running {config.agent_name} in worktree {config.agent_id}: {e}",
            exc_info=True,
        )
        logger.error("Unexpected error in %s agent: %s", config.agent_name, e)
        # Reconciliation: attempt to salvage commits even after an
        # unexpected exception.  Use a fallback CopilotResult when
        # ``result`` was never assigned (exception before inner try).
        if merge_changes:
            fallback = CopilotResult(
                work_item_id=config.agent_item.id, success=False,
                output="", error=str(e), attempt_count=0,
            )
            reconciled_stats = _reconcile_worktree_branch(
                config, fallback, cleanup_parent_id,
            )
            if reconciled_stats is not None:
                preserve_for_debugging = False
                worktree_cleaned = True
                return reconciled_stats
        _print_preserved_worktree_debug(config.agent_id, worktree_path, config.repo_root)
        return None

    finally:
        if preserve_for_debugging:
            logger.info("Worktree preserved at %s — manual cleanup required", worktree_path)
        elif not worktree_cleaned:
            logger.info("Final cleanup: removing worktree %s...", config.agent_id)
            try:
                cleanup_worktree(config.agent_id, force=True)
                remove_from_manifest(config.agent_id)
            except SUBPROCESS_OR_RUNTIME_ERRORS as cleanup_error:
                logger.warning("Final cleanup failed: %s", cleanup_error)
                add_uncleaned_worktree(config.agent_id, str(worktree_path), f"Failed final cleanup: {cleanup_error}")

# Re-export beta tester for backward compatibility
from pokepoke.agents.beta_tester import run_beta_tester
