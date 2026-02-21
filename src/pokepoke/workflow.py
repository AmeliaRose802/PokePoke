"""Workflow management for work item selection and processing."""

import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING

logger = logging.getLogger(__name__)

from filelock import Timeout

from pokepoke.copilot import invoke_copilot
from pokepoke.types import BeadsWorkItem, AgentStats, CopilotResult, ModelCompletionRecord
from pokepoke.worktrees import create_worktree, cleanup_worktree
from pokepoke.git_operations import has_uncommitted_changes, has_commits_ahead
from pokepoke.beads import assign_and_sync_item, unassign_item, add_comment
from pokepoke.agent_runner import run_cleanup_loop, run_beta_tester, run_gate_agent
from pokepoke.worktree_finalization import finalize_work_item
from pokepoke.work_item_selection import select_work_item  # noqa: F401  # re-exported
from pokepoke.stats import parse_agent_stats
from pokepoke.terminal_ui import set_terminal_banner, format_work_item_banner
from pokepoke import terminal_ui
from pokepoke.shutdown import is_shutting_down, register_agent, unregister_agent
from pokepoke.model_selection import select_model_for_item
from pokepoke.agent_context import get_agent_name
from pokepoke.config import get_config
from pokepoke.coordination import worktree_setup_lock

if TYPE_CHECKING:
    from pokepoke.logging_utils import RunLogger


def process_work_item(
    item: BeadsWorkItem,
    interactive: bool,
    timeout_hours: float = 2.0,
    run_beta_test: bool = False,
    run_logger: 'RunLogger | None' = None,
    max_timeout_restarts: int = 3,
    agent_id: str | None = None,
) -> tuple[bool, int, AgentStats | None, int, int, ModelCompletionRecord | None]:
    """Process a single work item with timeout protection.

    Args:
        item: Work item to process
        interactive: If True, prompt for confirmation before proceeding
        timeout_hours: Maximum hours before timing out and restarting (default: 2.0)
        run_beta_test: If True, run beta tester after completion (default: False)
        run_logger: Optional run logger instance for file logging
        max_timeout_restarts: Maximum number of timeout restarts before failing (default: 3)

    Returns:
        Tuple of (success, request_count, stats, cleanup_agent_runs, gate_agent_runs, model_completion)
    """
    # Register this agent for shutdown coordination
    register_agent()
    worktree_path: Path | None = None

    try:
        start_time = time.time()
        timeout_seconds = timeout_hours * 3600
        request_count = 0
        cleanup_agent_runs = 0
        gate_agent_runs = 0

        # Select model for this work item (A/B testing)
        config = get_config()
        selected_model = select_model_for_item(item.id)
        base_agent_id = agent_id or item.id
        backend_provider = config.ai_backend.provider
        worktree_lock_timeout = float(config.command_timeout)

        # Keep the Desktop UI agent card in sync with the selected model.
        terminal_ui.ui.push_agent_status(
            base_agent_id,
            get_agent_name(default="pokepoke"),
            iteration=1,
            status="running",
            model=selected_model,
            work_item_id=item.id,
            work_item_title=item.title,
        )

        print(f"\n🚀 Processing work item: {item.id}")
        print(f"   {item.title}")
        print(f"   🤖 Model: {selected_model}")
        print(f"   🧠 Backend: {backend_provider}")
        print(f"   ⏱️  Timeout: {timeout_hours} hours\n")

        # Start item logging
        item_logger = None
        if run_logger:
            item_logger = run_logger.start_item_log(item.id, item.title)

        if interactive:
            terminal_ui.ui.stop()
            confirm = input("Proceed with this item? [Y/n]: ").strip().lower()
            terminal_ui.ui.start()
            if confirm and confirm != 'y':
                print("⏭️  Skipped.")
                if run_logger and item_logger:
                    item_logger.log_summary(False, 0)
                    run_logger.log_orchestrator("Completed work item with 0 agent requests - Status: FAILURE")
                return False, 0, None, 0, 0, None

        # Assign and sync BEFORE creating worktree to prevent parallel conflicts
        print("\n🔒 Claiming work item...")
        try:
            with worktree_setup_lock(timeout=worktree_lock_timeout):
                if not assign_and_sync_item(item.id):
                    print(f"❌ Failed to assign work item {item.id}")
                    if run_logger and item_logger:
                        item_logger.log_summary(False, 0)
                        run_logger.log_orchestrator("Completed work item with 0 agent requests - Status: FAILURE")
                    return False, 0, None, 0, 0, None

                worktree_path = _setup_worktree(item)

                if worktree_path is None:
                    print(f"↩️  Returning {item.id} to queue (unassigning due to worktree failure)...")
                    unassign_item(item.id)
                    if run_logger and item_logger:
                        item_logger.log_summary(False, 0)
                        run_logger.log_orchestrator("Completed work item with 0 agent requests - Status: FAILURE")
                    return False, 0, None, 0, 0, None
        except Timeout:
            wait_seconds = int(worktree_lock_timeout)
            print(f"❌ Timed out waiting {wait_seconds}s for worktree setup lock (another agent is claiming an item).")
            if run_logger and item_logger:
                item_logger.log_summary(False, 0)
                run_logger.log_orchestrator("Completed work item with 0 agent requests - Status: FAILURE")
            return False, 0, None, 0, 0, None

        # Use current working directory as repo root
        pokepoke_root = Path.cwd()

        assert worktree_path is not None
        worktree_cwd = str(worktree_path)

        print(f"   Working directory: {worktree_cwd}\n")

        last_feedback = ""
        # Initialize accumulated stats
        accumulated_stats = AgentStats()
        gate_success = False  # Track last gate result for model completion record
        timeout_restart_count = 0
        work_agent_iteration = 1  # Track work agent retry iterations

        # Ensure result is always defined even if shutdown happens before the first loop iteration.
        result = CopilotResult(
            work_item_id=item.id,
            success=False,
            error="Session aborted due to application shutdown",
            attempt_count=0,
        )

        while not is_shutting_down():
            # Check timeout before invoking Copilot
            elapsed = time.time() - start_time
            if elapsed >= timeout_seconds:
                timeout_restart_count += 1
                if timeout_restart_count > max_timeout_restarts:
                    print(f"\n⏱️  TIMEOUT: Exceeded max restarts ({max_timeout_restarts})")
                    print(f"   Failing item {item.id} after {timeout_restart_count - 1} timeout restart(s).\n")
                    if run_logger and item_logger:
                        item_logger.log_summary(False, request_count)
                        run_logger.log_orchestrator(f"Completed work item with {request_count} agent requests - Status: FAILURE")
                    cleanup_worktree(item.id, force=True)
                    terminal_ui.ui.set_current_agent(None)
                    return False, request_count, accumulated_stats, cleanup_agent_runs, gate_agent_runs, None
                print(f"\n⏱️  TIMEOUT: Execution exceeded {timeout_hours} hours")
                print(f"   Restarting item {item.id} (attempt {timeout_restart_count}/{max_timeout_restarts})...\n")
                start_time = time.time()
                elapsed = 0

            remaining_timeout = timeout_seconds - elapsed

            # Append feedback if retrying
            if last_feedback:
                print("\n🔄 Restarting Work Agent with feedback...")
                current_desc = item.description or ""
                if "**PREVIOUS GATE AGENT FEEDBACK:**" not in current_desc:
                    current_desc += "\n\n**PREVIOUS GATE AGENT FEEDBACK:**\n"
                current_desc += f"\n- {last_feedback}"
                item.description = current_desc
                work_agent_iteration += 1
                terminal_ui.ui.push_agent_status(base_agent_id, get_agent_name(default="pokepoke"),
                    iteration=work_agent_iteration, status="running", model=selected_model,
                    work_item_id=item.id, work_item_title=item.title)

            terminal_ui.ui.set_current_agent("Work Agent")
            from pokepoke.metrics_context import agent_type_context
            with agent_type_context("work"):
                result = invoke_copilot(item, timeout=remaining_timeout, item_logger=item_logger,
                    model=selected_model, cwd=worktree_cwd)
            request_count += result.attempt_count

            # Aggregate stats
            current_stats = result.stats if result.stats else (parse_agent_stats(result.output) if result.output else None)
            if current_stats:
                accumulated_stats.accumulate(current_stats)

            # If work agent failed, break
            if not result.success:
                break

            if not has_uncommitted_changes(cwd=worktree_cwd):
                commits_ahead = has_commits_ahead(cwd=worktree_cwd)
                if commits_ahead > 0:
                    print(f"\n✅ All changes already committed ({commits_ahead} commit{'s' if commits_ahead != 1 else ''} ahead)")
                    print("   Skipping cleanup and commit steps")
                else:
                    print("\n✅ No changes made - work item may already be complete")
                    print("   Skipping cleanup and commit steps")

            # Run cleanup loop with timeout checking
            cleanup_success, cleanup_runs = _run_cleanup_with_timeout(
                item, result, pokepoke_root, start_time, timeout_seconds, timeout_hours, worktree_cwd,
                parent_agent_id=base_agent_id,
            )
            cleanup_agent_runs += cleanup_runs

            if not cleanup_success:
                # Cleanup failed (e.g. timeout), consider item failed or retry?
                # For now, if cleanup fails, we fail the cycle.
                result.success = False
                if run_logger and item_logger:
                    item_logger.log_summary(False, request_count)
                    run_logger.log_orchestrator(f"Completed work item with {request_count} agent requests - Status: FAILURE")
                return False, request_count, accumulated_stats, cleanup_agent_runs, gate_agent_runs, None

            # --- GATE AGENT CHECK ---
            # Build handoff context so gate agent skips re-discovering the codebase
            from pokepoke.git_operations import build_handoff_context
            handoff_ctx = build_handoff_context(cwd=worktree_cwd)

            gate_iteration = gate_agent_runs + 1
            gate_agent_id = f"{base_agent_id}-gate-{gate_iteration}"
            terminal_ui.ui.push_agent_status(
                gate_agent_id,
                "Gate Agent",
                iteration=gate_iteration,
                status="running",
                parent_agent_id=base_agent_id,
                work_item_id=item.id,
                work_item_title=item.title,
            )
            try:
                with terminal_ui.ui.agent_output_for(gate_agent_id):
                    gate_success, gate_reason, gate_stats = run_gate_agent(
                        item, cwd=worktree_cwd, work_model=selected_model,
                        handoff_context=handoff_ctx,
                    )
            except Exception as e:
                logger.warning(f"Gate agent raised exception: {e}", exc_info=True)
                gate_agent_runs += 1
                terminal_ui.ui.push_agent_status(
                    gate_agent_id,
                    "Gate Agent",
                    iteration=gate_agent_runs,
                    status="failed",
                    parent_agent_id=base_agent_id,
                    work_item_id=item.id,
                    work_item_title=item.title,
                )
                raise
            gate_agent_runs += 1
            terminal_ui.ui.push_agent_status(
                gate_agent_id,
                "Gate Agent",
                iteration=gate_agent_runs,
                status="success" if gate_success else "failed",
                parent_agent_id=base_agent_id,
                work_item_id=item.id,
                work_item_title=item.title,
            )

            if gate_success:
                print("\n✅ Gate Agent signed off!")
                break
            else:
                print(f"\n❌ Gate Agent rejected fix: {gate_reason}")
                add_comment(item.id, f"Gate Agent Rejection:\n{gate_reason}")
                last_feedback = gate_reason
                # Loop continues...

        if result.success:
            set_terminal_banner(format_work_item_banner(item.id, item.title, "Finalizing"))
            success = finalize_work_item(item, worktree_path, parent_agent_id=base_agent_id)
            # Use accumulated stats
            item_stats = accumulated_stats

            # Update banner based on finalization result
            if success:
                set_terminal_banner(format_work_item_banner(item.id, item.title, "Completed"))
            else:
                set_terminal_banner(format_work_item_banner(item.id, item.title, "Failed"))

            # Run beta tester after successful completion
            if success and run_beta_test:
                set_terminal_banner(format_work_item_banner(item.id, item.title, "Beta Testing"))
                beta_stats = run_beta_tester()
                if beta_stats and item_stats:
                    item_stats.accumulate(beta_stats)
                set_terminal_banner(format_work_item_banner(item.id, item.title, "Completed"))

            if run_logger and item_logger:
                item_logger.log_summary(success, request_count)
                run_logger.log_orchestrator(f"Completed work item with {request_count} agent requests - Status: {'SUCCESS' if success else 'FAILURE'}")

            terminal_ui.ui.set_current_agent(None)

            # Build model completion record for A/B tracking
            item_duration = time.time() - start_time
            model_completion = ModelCompletionRecord(
                item_id=item.id,
                model=selected_model,
                duration_seconds=item_duration,
                gate_passed=gate_success if gate_agent_runs > 0 else None,
            ) if success else None

            return success, request_count, item_stats, cleanup_agent_runs, gate_agent_runs, model_completion
        else:
            set_terminal_banner(format_work_item_banner(item.id, item.title, "Failed"))
            print(f"\n\u274c Failed to complete work item: {result.error}")
            print("\n\U0001f9f9 Cleaning up worktree...")
            cleanup_worktree(item.id, force=True)

            if run_logger and item_logger:
                item_logger.log_summary(False, request_count)
                run_logger.log_orchestrator(f"Completed work item with {request_count} agent requests - Status: FAILURE")

            terminal_ui.ui.set_current_agent(None)

            # Record failed completion too (gate_passed=False since work agent failed)
            item_duration = time.time() - start_time
            model_completion = ModelCompletionRecord(
                item_id=item.id,
                model=selected_model,
                duration_seconds=item_duration,
                gate_passed=False,
            )

            return False, request_count, None, cleanup_agent_runs, gate_agent_runs, model_completion

    finally:
        # Best-effort worktree cleanup to prevent resource leaks on unhandled exceptions
        try:
            if worktree_path is not None:
                cleanup_worktree(item.id, force=True)
        except Exception as e:
            logger.debug(f"Failed to cleanup worktree: {e}")
        # Always unregister agent when done, regardless of success/failure
        unregister_agent()


def _setup_worktree(item: BeadsWorkItem) -> Path | None:
    """Create worktree for work item processing."""
    print(f"\n🌳 Creating worktree for {item.id}...")
    try:
        worktree_path = create_worktree(item.id)
        print(f"   Created at: {worktree_path}")
        return worktree_path
    except Exception as e:
        print(f"\n❌ Failed to create worktree: {e}")
        return None


def _run_cleanup_with_timeout(
    item: BeadsWorkItem, result: CopilotResult, repo_root: Path, start_time: float,
    timeout_seconds: float, timeout_hours: float, cwd: str | None = None, parent_agent_id: str | None = None,
) -> tuple[bool, int]:
    """Run cleanup loop with timeout checking."""
    cleanup_agent_runs = 0
    cleanup_attempt = 0

    while result.success and has_uncommitted_changes(cwd=cwd):
        elapsed = time.time() - start_time
        if elapsed >= timeout_seconds:
            print(f"\n⏱️  TIMEOUT: Execution exceeded {timeout_hours} hours during cleanup")
            print(f"   Restarting item {item.id} in same worktree...\n")
            return False, cleanup_agent_runs

        cleanup_attempt += 1
        set_terminal_banner(format_work_item_banner(item.id, item.title, f"Cleanup #{cleanup_attempt}"))
        cleanup_success, cleanup_runs = run_cleanup_loop(
            item,
            result,
            repo_root,
            cwd=cwd,
            parent_agent_id=parent_agent_id,
        )
        cleanup_agent_runs += cleanup_runs

        if not cleanup_success:
            break

    return result.success, cleanup_agent_runs
