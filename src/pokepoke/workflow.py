"""Workflow management for work item selection and processing."""

import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING

from pokepoke.copilot import invoke_copilot
from pokepoke.copilot_sdk import build_prompt_from_work_item
from pokepoke.types import BeadsWorkItem, AgentStats, CopilotResult, ModelCompletionRecord, WorkItemResult
from pokepoke.worktrees import create_worktree, cleanup_worktree
from pokepoke.model_pricing import calculate_cost
from pokepoke.git_operations import has_uncommitted_changes, has_commits_ahead
from pokepoke.beads import assign_and_sync_item, add_comment, unassign_with_retry
from pokepoke.agent_runner import run_cleanup_loop, run_beta_tester, run_gate_agent
from pokepoke.worktree_finalization import finalize_work_item
from pokepoke.work_item_selection import select_work_item  # noqa: F401  # re-exported
from pokepoke.stats import parse_agent_stats
from pokepoke.terminal_ui import set_terminal_banner, format_work_item_banner
from pokepoke import terminal_ui
from pokepoke.shutdown import is_shutting_down, register_agent, unregister_agent
from pokepoke.model_selection import select_model_for_item, get_assignment_for_item
from pokepoke.agent_context import get_agent_name
from pokepoke.config import get_config

if TYPE_CHECKING:
    from pokepoke.logging_utils import ItemLogger, RunLogger

logger = logging.getLogger(__name__)


def _log_failure(run_logger: 'RunLogger | None', item_logger: 'ItemLogger | None', request_count: int = 0) -> None:
    """Log failure summary if loggers are available."""
    if run_logger and item_logger:
        item_logger.log_summary(False, request_count)
        run_logger.log_orchestrator(f"Completed work item with {request_count} agent requests - Status: FAILURE")


def _fail_result(
    request_count: int = 0, stats: AgentStats | None = None,
    cleanup_agent_runs: int = 0, gate_agent_runs: int = 0,
    model_completion: ModelCompletionRecord | None = None,
) -> WorkItemResult:
    """Create a failed WorkItemResult."""
    return WorkItemResult(success=False, request_count=request_count, stats=stats,
        cleanup_agent_runs=cleanup_agent_runs, gate_agent_runs=gate_agent_runs,
        model_completion=model_completion)


def _build_completion_record(
    item_id: str, model: str, duration: float, success: bool,
    gate_passed: bool | None, stats: AgentStats | None, request_count: int,
) -> ModelCompletionRecord:
    """Build a ModelCompletionRecord from item processing results."""
    input_tokens = stats.input_tokens if stats else 0
    output_tokens = stats.output_tokens if stats else 0
    return ModelCompletionRecord(
        item_id=item_id, model=model, duration_seconds=duration,
        gate_passed=gate_passed, input_tokens=input_tokens, output_tokens=output_tokens,
        agent_turns=request_count, cost=calculate_cost(model, input_tokens, output_tokens),
        retry_attempts=max(0, request_count - 1),
        api_duration=stats.api_duration if stats else None,
        lines_added=stats.lines_added if stats else None,
        lines_removed=stats.lines_removed if stats else None)


def process_work_item(
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
        # Scale lock wait by agent count so the last agent in a large pool can wait through all preceding setups.
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
        assert worktree_path is not None
        worktree_cwd = str(worktree_path)
        print(f"   Working directory: {worktree_cwd}\n")
        last_feedback = ""
        accumulated_stats = AgentStats()
        gate_success = False
        timeout_restart_count = 0
        work_agent_iteration = 1

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

            # Append feedback if retrying, keeping only last 3 entries
            if last_feedback:
                print("\n🔄 Restarting Work Agent with feedback...")
                hdr = "**PREVIOUS GATE AGENT FEEDBACK:**"
                desc = item.description or ""
                base, sec = desc.split(hdr, 1) if hdr in desc else (desc, "")
                prev = [e for e in sec.strip().splitlines() if e.strip().startswith("- ")]

                base_stripped = base.rstrip()
                separator = "\n\n" if base_stripped else ""
                item.description = base_stripped + f"{separator}{hdr}\n" + "\n".join(
                    prev[-2:] + [f"- {last_feedback}"]
                )
                work_agent_iteration += 1

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

            current_stats = result.stats or (parse_agent_stats(result.output) if result.output else None)
            if current_stats:
                accumulated_stats.accumulate(current_stats)

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

        if result.success:
            set_terminal_banner(format_work_item_banner(item.id, item.title, "Finalizing"))
            success = finalize_work_item(item, worktree_path, parent_agent_id=base_agent_id)
            finalized_successfully = success
            # Use accumulated stats
            item_stats = accumulated_stats

            # Update banner based on finalization result
            status = "Completed" if success else "Failed"
            set_terminal_banner(format_work_item_banner(item.id, item.title, status))

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
            item_duration = time.time() - start_time
            gate_passed = gate_success if gate_agent_runs > 0 else None
            model_completion = _build_completion_record(
                item.id, selected_model, item_duration, success,
                gate_passed, item_stats, request_count) if success else None

            return WorkItemResult(success=success, request_count=request_count, stats=item_stats,
                                  cleanup_agent_runs=cleanup_agent_runs, gate_agent_runs=gate_agent_runs,
                                  model_completion=model_completion)
        else:
            set_terminal_banner(format_work_item_banner(item.id, item.title, "Failed"))
            print(f"\n\u274c Failed to complete work item: {result.error}")
            print("\n\U0001f9f9 Cleaning up worktree...")
            cleanup_worktree(item.id, force=True)
            _log_failure(run_logger, item_logger, request_count)
            terminal_ui.ui.set_current_agent(None)
            model_completion = _build_completion_record(
                item.id, selected_model, time.time() - start_time, False,
                False, accumulated_stats, request_count)
            return _fail_result(request_count=request_count, cleanup_agent_runs=cleanup_agent_runs,
                                gate_agent_runs=gate_agent_runs, model_completion=model_completion, stats=accumulated_stats)

    finally:
        # Best-effort worktree cleanup to prevent resource leaks on unhandled exceptions
        try:
            if worktree_path is not None and not finalized_successfully:
                cleanup_worktree(item.id, force=True)
        except Exception as e:
            logger.error("Failed to cleanup worktree for %s: %s", item.id, e)
            # Track orphaned worktree for later cleanup
            try:
                from pokepoke.worktree_cleanup import add_uncleaned_worktree
                add_uncleaned_worktree(item.id, str(worktree_path), f"Finally-block cleanup failed: {e}")
            except Exception:
                logger.error("Failed to track orphaned worktree %s in manifest", item.id)
        # Unassign item so other agents can pick it up again
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
            cwd=cwd,
            parent_agent_id=parent_agent_id,
        )
        cleanup_agent_runs += cleanup_runs

        if not cleanup_success:
            break

    return result.success, cleanup_agent_runs
