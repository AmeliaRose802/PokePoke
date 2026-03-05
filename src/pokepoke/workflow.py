"""Workflow management for work item selection and processing."""

import contextlib
import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING

from pokepoke.copilot import invoke_copilot
from pokepoke.copilot_sdk import build_prompt_from_work_item
from pokepoke.types import BeadsWorkItem, AgentStats, CopilotResult, WorkItemResult
from pokepoke.worktrees import create_worktree, cleanup_worktree
from pokepoke.beads import assign_and_sync_item, add_comment, unassign_with_retry
from pokepoke.agent_runner import run_gate_agent  # noqa: F401  # re-exported via workflow_helpers
from pokepoke.work_item_selection import select_work_item  # noqa: F401  # re-exported
from pokepoke import terminal_ui
from pokepoke.shutdown import is_shutting_down, register_agent, unregister_agent
from pokepoke.model_selection import select_model_for_item, get_assignment_for_item
from pokepoke.agent_context import get_agent_name
from pokepoke.config import get_config
from pokepoke.workflow_helpers import (
    _apply_gate_feedback, _extract_agent_stats, _fail_result,
    _finalize_item_result, _log_commit_status, _log_failure,
    _maybe_retry_copilot,
    run_cleanup_with_timeout,
)

if TYPE_CHECKING:
    from pokepoke.logging_utils import ItemLogger, RunLogger

logger = logging.getLogger(__name__)


def process_work_item(  # noqa: C901
    item: BeadsWorkItem,
    interactive: bool,
    timeout_hours: float = 2.0,
    run_beta_test: bool = False,
    run_logger: 'RunLogger | None' = None,
    max_timeout_restarts: int = 3,
    agent_id: str | None = None,
) -> WorkItemResult:
    """Process a single work item with timeout protection."""
    # Register this agent for shutdown coordination
    register_agent()
    worktree_path: Path | None = None
    was_assigned = False
    finalized_successfully = False

    try:
        start_time = time.time()
        timeout_seconds = timeout_hours * 3600
        request_count = 0
        cleanup_agent_runs = 0
        gate_agent_runs = 0
        config = get_config()
        selected_model = select_model_for_item(item)
        _, selected_prompt_template = get_assignment_for_item(item)
        base_agent_id = agent_id or item.id
        backend_provider = config.ai_backend.provider
        worktree_lock_timeout = max(float(config.command_timeout), 120.0 * max(1, int(config.max_parallel_agents)))

        terminal_ui.ui.push_agent_status(base_agent_id, get_agent_name(default="pokepoke"),
            iteration=1, status="running", model=selected_model,
            work_item_id=item.id, work_item_title=item.title, agent_type="work")

        print(f"\n🚀 Processing work item: {item.id} — {item.title}")
        print(f"   🤖 Model: {selected_model} | 🧠 Backend: {backend_provider} | ⏱️  Timeout: {timeout_hours}h\n")

        item_logger = run_logger.start_item_log(item.id, item.title) if run_logger else None

        if interactive:
            terminal_ui.ui.stop()
            confirm = input("Proceed with this item? [Y/n]: ").strip().lower()
            terminal_ui.ui.start()
            if confirm and confirm != 'y':
                print("⏭️  Skipped.")
                _log_failure(run_logger, item_logger)
                return _fail_result()

        # Assign and sync BEFORE creating worktree to prevent parallel conflicts
        print("\n🔒 Claiming work item...")
        # assign_and_sync_item has its own per-item lock (beads-claim-{item_id})
        if not assign_and_sync_item(item.id):
            print(f"❌ Failed to assign work item {item.id}")
            _log_failure(run_logger, item_logger)
            return _fail_result()
        was_assigned = True

        # create_worktree has its own lock (worktree-setup.lock) via with_worktree_lock
        worktree_path = _setup_worktree(
            item, lock_timeout=worktree_lock_timeout,
            run_logger=run_logger, item_logger=item_logger,
        )

        if worktree_path is None:
            print(f"↩️  Returning {item.id} to queue (unassigning due to worktree failure)...")
            _log_failure(run_logger, item_logger)
            return _fail_result()

        pokepoke_root = Path.cwd()
        worktree_cwd = str(worktree_path)
        print(f"   Working directory: {worktree_cwd}\n")
        last_feedback = ""
        accumulated_stats = AgentStats()
        gate_success = False
        timeout_restart_count = 0
        work_agent_iteration = 1
        copilot_failure_count = 0

        # Default result for shutdown before first loop iteration.
        result = CopilotResult(work_item_id=item.id, success=False,
            error="Session aborted due to application shutdown", attempt_count=0)

        while not is_shutting_down():
            # Check timeout before invoking Copilot
            elapsed = time.time() - start_time
            if elapsed >= timeout_seconds:
                timeout_restart_count += 1
                if timeout_restart_count > max_timeout_restarts:
                    print(f"\n⏱️  TIMEOUT: Exceeded max restarts ({max_timeout_restarts})")
                    print(f"   Failing item {item.id} after {timeout_restart_count - 1} timeout restart(s).\n")
                    _log_failure(run_logger, item_logger, request_count)
                    cleanup_worktree(item.id, force=True)
                    terminal_ui.ui.set_current_agent(None)
                    return _fail_result(request_count=request_count, stats=accumulated_stats,
                                        cleanup_agent_runs=cleanup_agent_runs, gate_agent_runs=gate_agent_runs)
                print(f"\n⏱️  TIMEOUT: Execution exceeded {timeout_hours} hours")
                print(f"   Restarting item {item.id} (attempt {timeout_restart_count}/{max_timeout_restarts})...\n")
                start_time = time.time()
                elapsed = 0

            remaining_timeout = timeout_seconds - elapsed

            # Append feedback if retrying
            if last_feedback:
                print("\n🔄 Restarting Work Agent with feedback...")
                item, work_agent_iteration = _apply_gate_feedback(item, last_feedback, work_agent_iteration)

            terminal_ui.ui.set_current_agent("Work Agent")
            from pokepoke.metrics_context import agent_type_context
            prompt_template = selected_prompt_template or "beads-item"
            work_prompt = build_prompt_from_work_item(item, template_name=prompt_template)
            with agent_type_context("work"):
                is_retry = work_agent_iteration > 1
                agent_id = f"{base_agent_id}-retry-{work_agent_iteration}" if is_retry else base_agent_id
                terminal_ui.ui.push_agent_status(agent_id, get_agent_name(default="pokepoke"),
                    iteration=work_agent_iteration, status="running", model=selected_model,
                    parent_agent_id=base_agent_id if is_retry else None,
                    work_item_id=item.id, work_item_title=item.title, agent_type="work",
                    agent_prompt=work_prompt)
                result = invoke_copilot(
                    item, prompt=work_prompt, timeout=remaining_timeout,
                    item_logger=item_logger, model=selected_model, cwd=worktree_cwd)
            request_count += result.attempt_count

            current_stats = _extract_agent_stats(result)
            if current_stats:
                accumulated_stats.accumulate(current_stats)

            if not result.success:
                copilot_failure_count += 1
                retry, feedback = _maybe_retry_copilot(
                    result, copilot_failure_count, config.max_copilot_failure_retries, run_logger, item.id)
                if retry:
                    last_feedback = feedback
                    continue
                break

            _log_commit_status(worktree_cwd)

            # Run cleanup loop with timeout checking
            cleanup_success, cleanup_runs = run_cleanup_with_timeout(
                item, result, pokepoke_root, start_time, timeout_seconds, timeout_hours, worktree_cwd,
                parent_agent_id=base_agent_id,
            )
            cleanup_agent_runs += cleanup_runs

            if not cleanup_success:
                # Cleanup failed (e.g. timeout), consider item failed or retry?
                # For now, if cleanup fails, we fail the cycle.
                result.success = False
                _log_failure(run_logger, item_logger, request_count)
                return _fail_result(request_count=request_count, stats=accumulated_stats,
                                    cleanup_agent_runs=cleanup_agent_runs, gate_agent_runs=gate_agent_runs)

            # --- GATE AGENT CHECK ---
            if not config.gate_agent_enabled:
                print("\n⏭️  Gate Agent disabled via config — skipping verification")
                gate_success = True
                break

            # Build handoff context so gate agent skips re-discovering the codebase
            from pokepoke.git_operations import build_handoff_context
            handoff_ctx = build_handoff_context(cwd=worktree_cwd)
            gate_iteration = gate_agent_runs + 1
            gate_agent_id = f"{base_agent_id}-gate-{gate_iteration}"
            try:
                with terminal_ui.ui.agent_output_for(gate_agent_id):
                    gate_success, gate_reason, gate_stats = run_gate_agent(
                        item, cwd=worktree_cwd, work_model=selected_model,
                        handoff_context=handoff_ctx,
                        agent_id=gate_agent_id, agent_iteration=gate_iteration,
                        parent_agent_id=base_agent_id,
                        item_logger=item_logger,
                    )
            except Exception as e:
                logger.warning(f"Gate agent raised exception: {e}", exc_info=True)
                gate_agent_runs += 1
                terminal_ui.ui.push_agent_status(gate_agent_id, "Gate Agent",
                    iteration=gate_agent_runs, status="failed",
                    parent_agent_id=base_agent_id, work_item_id=item.id, work_item_title=item.title,
                    agent_type="gate")
                raise
            gate_agent_runs += 1
            terminal_ui.ui.push_agent_status(gate_agent_id, "Gate Agent",
                iteration=gate_agent_runs, status="success" if gate_success else "failed",
                parent_agent_id=base_agent_id, work_item_id=item.id, work_item_title=item.title,
                agent_type="gate")

            if gate_success:
                print("\n✅ Gate Agent signed off!")
                break
            else:
                print(f"\n❌ Gate Agent rejected fix: {gate_reason}")
                add_comment(item.id, f"Gate Agent Rejection:\n{gate_reason}")
                last_feedback = gate_reason
                # Loop continues...

        final_result, finalized_successfully = _finalize_item_result(
            result, item, worktree_path, selected_model, start_time,
            request_count, accumulated_stats, cleanup_agent_runs, gate_agent_runs,
            gate_success, run_logger, item_logger, base_agent_id, run_beta_test,
        )
        return final_result

    finally:
        if worktree_path is not None and not finalized_successfully:
            try:
                cleanup_worktree(item.id, force=True)
            except Exception as e:
                logger.error("Failed to cleanup worktree for %s: %s", item.id, e)
                with contextlib.suppress(Exception):
                    from pokepoke.worktree_cleanup import add_uncleaned_worktree
                    add_uncleaned_worktree(item.id, str(worktree_path), f"Finally-block cleanup failed: {e}")
        if was_assigned and not finalized_successfully:
            try:
                unassign_with_retry(item.id)
            except Exception as e:
                logger.error("Failed to unassign item %s — item may be stuck in assigned state: %s", item.id, e)
        unregister_agent()


def _setup_worktree(
    item: BeadsWorkItem, lock_timeout: float = 300.0,
    run_logger: 'RunLogger | None' = None, item_logger: 'ItemLogger | None' = None,
) -> Path | None:
    """Create worktree, logging errors to both file logs and UI."""
    print(f"\n🌳 Creating worktree for {item.id}...")
    try:
        worktree_path = create_worktree(item.id, lock_timeout=lock_timeout)
        print(f"   Created at: {worktree_path}")
        return worktree_path
    except Exception as e:
        error_msg = f"Failed to create worktree for {item.id}: {e}"
        print(f"\n❌ {error_msg}")
        logger.error(error_msg)
        if run_logger:
            run_logger.log_orchestrator(error_msg, level="ERROR")
        if item_logger:
            item_logger.log_error(error_msg)
        return None


