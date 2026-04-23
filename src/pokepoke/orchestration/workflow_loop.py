"""Execution loop for work agent, cleanup, and gate processing."""

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pokepoke.models.copilot_sdk import build_prompt_from_work_item
from pokepoke.models.sdk_helpers import build_resume_prompt
from pokepoke.orchestration.gate_agent_loop import GateLoopContext, run_gate_loop
from pokepoke.orchestration.gate_step_tracker import get_gate_step_tracker
from pokepoke.orchestration.work_item_session import WorkItemSession
from pokepoke.types import AgentStats, BeadsWorkItem, WorkItemResult
from pokepoke.types_agent import CopilotResult

logger = logging.getLogger(__name__)
_FAIL_FAST_STATUSES = frozenset({"blocked", "needs_clarification", "too_large"})
_BACKOFF_BASE_SECONDS, _BACKOFF_MAX_SECONDS = 30, 240


@dataclass
class LoopExecutionResult:
    """Mutable state returned by the work+cleanup+gate loop."""

    immediate_result: WorkItemResult | None
    result: CopilotResult
    start_time: float
    request_count: int
    cleanup_agent_runs: int
    gate_agent_runs: int
    accumulated_stats: AgentStats = field(default_factory=AgentStats)
    gate_success: bool = False
    work_agent_iteration: int = 1
    accumulated_feedback: list[str] = field(default_factory=list)


def run_workflow_loop(  # noqa: C901, PLR0912, PLR0913
    *,
    item: BeadsWorkItem,
    cfg: Any,
    base_agent_id: str,
    selected_model: str,
    selected_prompt_template: str | None,
    global_config: Any,
    backend_provider: str,
    start_time: float,
    timeout_seconds: float,
    max_gate_rejections: int,
    worktree_cwd: str,
    pokepoke_root: Path,
    run_logger: Any,
    item_logger: Any,
    session: WorkItemSession | None,
    previous_worker_context: str | None,
    worktree_resume_context: str | None,
    comment_fn: Any,
    block_fn: Any,
    defer_fn: Any,
    invoke_copilot_fn: Any,
    run_cleanup_with_timeout_fn: Any,
    is_shutting_down_fn: Any,
    apply_gate_feedback_fn: Any,
    check_sdk_invariant_fn: Any,
    combine_resume_contexts_fn: Any,
    extract_agent_stats_fn: Any,
    fail_result_fn: Any,
    handle_fail_fast_outcome_fn: Any,
    log_commit_status_fn: Any,
    log_failure_fn: Any,
    maybe_decompose_fn: Any,
    maybe_retry_copilot_fn: Any,
    ui_module: Any,
    get_agent_name_fn: Any,
    verify_worktree_branch_fn: Any,
) -> LoopExecutionResult:
    """Run the work agent loop, cleanup, and gate verification pipeline."""

    request_count = cleanup_agent_runs = gate_agent_runs = 0
    accumulated_stats, gate_success = AgentStats(), False
    timeout_restart_count = copilot_failure_count = 0
    backoff_delay = _BACKOFF_BASE_SECONDS
    work_agent_iteration = 1
    gate_rejection_count = int((item.metadata or {}).get("gate_rejection_count", 0))
    gate_resume_session_id = gate_resume_output_summary = gate_resume_feedback = None
    last_retry_was_gate_feedback, current_work_agent_id = False, base_agent_id
    resume_session_id = resume_output_summary = None
    last_feedback = ""
    accumulated_feedback: list[str] = []
    result = CopilotResult(
        work_item_id=item.id,
        success=False,
        error="Session aborted due to application shutdown",
        attempt_count=0,
    )

    gt = get_gate_step_tracker()
    gate_resume_enabled = global_config.gate_reverify_resume_enabled

    while not is_shutting_down_fn():
        elapsed = time.time() - start_time
        gt.start_work(base_agent_id, item.id, work_agent_iteration, gate_rejection_count)
        if timeout_seconds > 0 and elapsed >= timeout_seconds:
            timeout_restart_count += 1
            if timeout_restart_count > cfg.max_timeout_restarts:
                log_failure_fn(run_logger, item_logger, request_count)
                ui_module.ui.set_current_agent(None)
                return LoopExecutionResult(
                    immediate_result=fail_result_fn(
                        request_count=request_count,
                        stats=accumulated_stats,
                        cleanup_agent_runs=cleanup_agent_runs,
                        gate_agent_runs=gate_agent_runs,
                        failure_reason=f"Exceeded max timeout restarts ({cfg.max_timeout_restarts})",
                    ),
                    result=result,
                    start_time=start_time,
                    request_count=request_count,
                    cleanup_agent_runs=cleanup_agent_runs,
                    gate_agent_runs=gate_agent_runs,
                    accumulated_stats=accumulated_stats,
                    gate_success=gate_success,
                    work_agent_iteration=work_agent_iteration,
                    accumulated_feedback=accumulated_feedback,
                )
            logger.info(
                f"\n⏱️  TIMEOUT: Restarting {item.id} (attempt {timeout_restart_count}/{cfg.max_timeout_restarts}), "
                f"backing off {backoff_delay}s"
            )
            time.sleep(backoff_delay)
            backoff_delay = min(backoff_delay * 2, _BACKOFF_MAX_SECONDS)
            start_time = time.time()
            elapsed = 0

        remaining_timeout = (timeout_seconds - elapsed) if timeout_seconds > 0 else None
        if last_feedback:
            logger.info(
                "\n🔄 Restarting Work Agent with feedback..."
                if last_retry_was_gate_feedback
                else "\n⏱️  Resuming Work Agent after timeout..."
            )
            accumulated_feedback, work_agent_iteration = apply_gate_feedback_fn(
                last_feedback, accumulated_feedback, work_agent_iteration
            )

        ui_module.ui.set_current_agent("Work Agent")
        from pokepoke.stats.metrics_context import agent_type_context

        prompt_template = selected_prompt_template or "beads-item"
        is_resume = resume_session_id is not None
        combined_context = combine_resume_contexts_fn(worktree_resume_context, previous_worker_context)
        if is_resume:
            work_prompt = build_resume_prompt(
                item,
                previous_output_summary=resume_output_summary,
                retry_feedback=accumulated_feedback or None,
            )
        else:
            work_prompt = build_prompt_from_work_item(
                item,
                template_name=prompt_template,
                retry_feedback=accumulated_feedback or None,
                previous_worker_context=combined_context,
            )

        with agent_type_context("work"):
            is_retry = work_agent_iteration > 1
            if is_retry and not last_retry_was_gate_feedback:
                agent_id = current_work_agent_id
                resume_in_place = True
                parent_for_status = None
            else:
                agent_id = f"{base_agent_id}-retry-{work_agent_iteration}" if is_retry else base_agent_id
                current_work_agent_id = agent_id
                resume_in_place = False
                parent_for_status = base_agent_id if is_retry else None
            ui_module.ui.push_agent_status(
                agent_id,
                get_agent_name_fn(default="pokepoke"),
                iteration=work_agent_iteration,
                status="running",
                model=selected_model,
                parent_agent_id=parent_for_status,
                work_item_id=item.id,
                work_item_title=item.title,
                agent_type="work",
                agent_prompt=work_prompt,
                resume_in_place=resume_in_place,
            )

            branch_error = verify_worktree_branch_fn(item.id, worktree_cwd)
            if branch_error:
                logger.error(f"\n❌ {branch_error}")
                log_failure_fn(run_logger, item_logger, request_count)
                ui_module.ui.set_current_agent(None)
                return LoopExecutionResult(
                    immediate_result=fail_result_fn(
                        request_count=request_count,
                        stats=accumulated_stats,
                        cleanup_agent_runs=cleanup_agent_runs,
                        gate_agent_runs=gate_agent_runs,
                        failure_reason=branch_error,
                    ),
                    result=result,
                    start_time=start_time,
                    request_count=request_count,
                    cleanup_agent_runs=cleanup_agent_runs,
                    gate_agent_runs=gate_agent_runs,
                    accumulated_stats=accumulated_stats,
                    gate_success=gate_success,
                    work_agent_iteration=work_agent_iteration,
                    accumulated_feedback=accumulated_feedback,
                )

            with ui_module.ui.agent_output_for(agent_id):
                result = invoke_copilot_fn(
                    item,
                    prompt=work_prompt,
                    timeout=remaining_timeout,
                    item_logger=item_logger,
                    model=selected_model,
                    cwd=worktree_cwd,
                    session_id=resume_session_id,
                    is_resume=is_resume,
                )
        request_count += result.attempt_count
        gt.work_done()

        if current_stats := extract_agent_stats_fn(result):
            accumulated_stats.accumulate(current_stats)
        if check_sdk_invariant_fn(backend_provider, result, item.id):
            break

        is_process_crash = bool(
            result.error
            and ("process died" in result.error.lower() or "exited unexpectedly" in result.error.lower())
        )
        if not result.success:
            copilot_failure_count += 1
            if result.session_id:
                resume_session_id = result.session_id
                resume_output_summary = result.last_output_summary
                logger.info(f"\n📎 Session state saved for retry (session: {resume_session_id})")
            else:
                resume_session_id = None
                resume_output_summary = None
            if is_process_crash:
                logger.warning(f"\n⚠️  CLI process crashed: {result.error}")
            retry, feedback = maybe_retry_copilot_fn(
                result, copilot_failure_count, global_config.max_copilot_failure_retries, run_logger, item.id
            )
            if retry:
                last_feedback = feedback
                last_retry_was_gate_feedback = False
                gt.finish_run("failed")
                continue
            maybe_decompose_fn(item, copilot_failure_count, gate_rejection_count, global_config)
            gt.finish_run("failed")
            break

        log_commit_status_fn(worktree_cwd)
        outcome = result.work_agent_outcome
        if outcome and outcome.status in _FAIL_FAST_STATUSES:
            ff_result, too_large_ctx = handle_fail_fast_outcome_fn(
                outcome,
                item,
                comment_fn,
                block_fn,
                session,
                run_logger,
                item_logger,
                request_count,
                accumulated_stats,
                cleanup_agent_runs,
                gate_agent_runs,
                gt,
            )
            if ff_result is not None:
                ui_module.ui.set_current_agent(None)
                return LoopExecutionResult(
                    immediate_result=ff_result,
                    result=result,
                    start_time=start_time,
                    request_count=request_count,
                    cleanup_agent_runs=cleanup_agent_runs,
                    gate_agent_runs=gate_agent_runs,
                    accumulated_stats=accumulated_stats,
                    gate_success=gate_success,
                    work_agent_iteration=work_agent_iteration,
                    accumulated_feedback=accumulated_feedback,
                )
            if too_large_ctx:
                maybe_decompose_fn(
                    item,
                    copilot_failure_count,
                    gate_rejection_count,
                    global_config,
                    too_large_context=too_large_ctx,
                )
            break

        from pokepoke.beads.reconciliation import is_beads_item_closed

        if is_beads_item_closed(item.id):
            logger.warning("\n✅ Agent already closed beads item — skipping cleanup and gate checks")
            gt.item_closed()
            gate_success = True
            break

        gt.cleanup_done()
        cleanup_success, cleanup_runs = run_cleanup_with_timeout_fn(
            item,
            result,
            pokepoke_root,
            start_time,
            timeout_seconds,
            cfg.timeout_hours,
            worktree_cwd,
            parent_agent_id=base_agent_id,
            item_logger=item_logger,
        )
        cleanup_agent_runs += cleanup_runs
        if not cleanup_success:
            gt.mark_failure("3")
            result.success = False
            log_failure_fn(run_logger, item_logger, request_count)
            return LoopExecutionResult(
                immediate_result=fail_result_fn(
                    request_count=request_count,
                    stats=accumulated_stats,
                    cleanup_agent_runs=cleanup_agent_runs,
                    gate_agent_runs=gate_agent_runs,
                    failure_reason="Cleanup agent failed to resolve uncommitted changes",
                ),
                result=result,
                start_time=start_time,
                request_count=request_count,
                cleanup_agent_runs=cleanup_agent_runs,
                gate_agent_runs=gate_agent_runs,
                accumulated_stats=accumulated_stats,
                gate_success=gate_success,
                work_agent_iteration=work_agent_iteration,
                accumulated_feedback=accumulated_feedback,
            )

        gt.complete_step("3")
        if not global_config.gate_agent_enabled:
            logger.warning("\n⏭️  Gate Agent disabled via config — skipping verification")
            gt.gate_disabled()
            gate_success = True
            break

        gt.gate_start()
        gate_loop_result = run_gate_loop(
            GateLoopContext(
                item=item,
                result=result,
                worktree_cwd=worktree_cwd,
                pokepoke_root=pokepoke_root,
                selected_model=selected_model,
                base_agent_id=base_agent_id,
                max_gate_rejections=max_gate_rejections,
                gate_rejection_count=gate_rejection_count,
                gate_agent_runs=gate_agent_runs,
                item_logger=item_logger,
                comment_fn=comment_fn,
                defer_fn=defer_fn,
                resume_session_id=gate_resume_session_id if gate_resume_enabled else None,
                resume_reason="reverify" if gate_resume_enabled and last_retry_was_gate_feedback else None,
                resume_output_summary=gate_resume_output_summary if gate_resume_enabled else None,
                resume_feedback=gate_resume_feedback if gate_resume_enabled else None,
            ),
            gt,
        )
        gate_agent_runs = gate_loop_result.gate_agent_runs
        gate_rejection_count = gate_loop_result.gate_rejection_count
        if gate_loop_result.gate_success:
            gate_success = True
            break
        if gate_loop_result.exceeded_max:
            maybe_decompose_fn(item, copilot_failure_count, gate_rejection_count, global_config)
            result.success = False
            result.error = f"Exceeded max gate rejections ({max_gate_rejections})"
            log_failure_fn(run_logger, item_logger, request_count)
            break
        if gate_loop_result.feedback:
            resume_session_id = None
            resume_output_summary = None
            last_feedback = gate_loop_result.feedback
            last_retry_was_gate_feedback = True
            gate_resume_session_id = gate_loop_result.session_id
            gate_resume_output_summary = gate_loop_result.last_output_summary
            gate_resume_feedback = gate_loop_result.feedback
            continue
        break

    return LoopExecutionResult(
        immediate_result=None,
        result=result,
        start_time=start_time,
        request_count=request_count,
        cleanup_agent_runs=cleanup_agent_runs,
        gate_agent_runs=gate_agent_runs,
        accumulated_stats=accumulated_stats,
        gate_success=gate_success,
        work_agent_iteration=work_agent_iteration,
        accumulated_feedback=accumulated_feedback,
    )
