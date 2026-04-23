"""Workflow management for work item selection and processing."""
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from pokepoke.agents.agent_context import get_agent_name
from pokepoke.beads.beads import add_comment, assign_and_sync_item, block_item, defer_item
from pokepoke.config import get_config
from pokepoke.desktop import terminal_ui
from pokepoke.git.git_helpers import verify_worktree_branch
from pokepoke.models.ai_backends import invoke_copilot
from pokepoke.models.copilot_sdk import build_prompt_from_work_item
from pokepoke.models.model_selection import get_assignment_for_item, select_model_for_item
from pokepoke.models.sdk_helpers import build_resume_prompt
from pokepoke.orchestration.finalization import (
    ResultContext as ResultContext,
)
from pokepoke.orchestration.finalization import (
    _finalize_item_result as _finalize_item_result,
)
from pokepoke.orchestration.gate_agent_loop import GateLoopContext, run_gate_loop
from pokepoke.orchestration.gate_step_tracker import get_gate_step_tracker
from pokepoke.orchestration.work_item_selection import select_work_item  # noqa: F401  # re-exported
from pokepoke.orchestration.work_item_session import WorkItemSession
from pokepoke.orchestration.worker_context import (
    format_worker_context_for_prompt,
    get_worker_contexts,
    save_worker_context,
)
from pokepoke.orchestration.workflow_helpers import (
    _apply_gate_feedback,
    _check_sdk_invariant,
    _combine_resume_contexts,
    _extract_agent_stats,
    _fail_result,
    _finalize_and_flag_merge_retry,
    _handle_fail_fast_outcome,
    _load_resume_contexts,
    _log_commit_status,
    _log_failure,
    _maybe_decompose,
    _maybe_retry_copilot,
    run_cleanup_with_timeout,
    setup_worktree,
    try_merge_retry_fast_path,
)
from pokepoke.protocols import BeadsClient
from pokepoke.stats.metrics_context import set_current_repo_name, set_current_work_item_id
from pokepoke.types import AgentStats, BeadsWorkItem, WorkItemResult
from pokepoke.types_agent import CopilotResult
from pokepoke.utils.shutdown import is_shutting_down, register_agent, unregister_agent
from pokepoke.worktrees.worktrees import cleanup_worktree, create_worktree  # noqa: F401 — kept for test patching

if TYPE_CHECKING:
    from pokepoke.utils.logging_utils import RunLogger
logger = logging.getLogger(__name__)
_FAIL_FAST_STATUSES = frozenset({"blocked", "needs_clarification", "too_large"})
_LOCK_TIMEOUT_PER_AGENT, _BACKOFF_BASE_SECONDS, _BACKOFF_MAX_SECONDS = 120.0, 30, 240

@dataclass
class WorkItemConfig:
    """Configuration bundle for optional process_work_item parameters."""
    timeout_hours: float = 0
    run_beta_test: bool = False
    max_timeout_restarts: int = 3
    repo_path: str | None = None
    beads_client: BeadsClient | None = None

def process_work_item(  # noqa: C901
    item: BeadsWorkItem, interactive: bool, run_logger: 'RunLogger | None' = None,
    agent_id: str | None = None, config: WorkItemConfig | None = None,
) -> WorkItemResult:
    """Process a single work item with timeout protection."""
    register_agent()
    cfg = config or WorkItemConfig()
    _assign = cfg.beads_client.assign_and_sync_item if cfg.beads_client else assign_and_sync_item
    _comment = cfg.beads_client.add_comment if cfg.beads_client else add_comment
    _block = cfg.beads_client.block_item if cfg.beads_client else block_item
    _defer = cfg.beads_client.defer_item if cfg.beads_client else defer_item
    _session: WorkItemSession | None = None
    try:
        start_time, timeout_seconds = time.time(), cfg.timeout_hours * 3600
        request_count = cleanup_agent_runs = gate_agent_runs = 0
        global_config = get_config()
        selected_model = select_model_for_item(item)
        _, selected_prompt_template = get_assignment_for_item(item)
        base_agent_id = agent_id or item.id
        backend_provider = global_config.ai_backend.provider
        worktree_lock_timeout = max(float(global_config.command_timeout), _LOCK_TIMEOUT_PER_AGENT * max(1, int(global_config.max_parallel_agents)))
        set_current_work_item_id(item.id)
        set_current_repo_name(Path(cfg.repo_path).name if cfg.repo_path else Path.cwd().name)

        terminal_ui.ui.push_agent_status(base_agent_id, get_agent_name(default="pokepoke"),
            iteration=1, status="running", model=selected_model,
            work_item_id=item.id, work_item_title=item.title, agent_type="work")

        timeout_str = f'{cfg.timeout_hours}h' if cfg.timeout_hours > 0 else 'unlimited'
        logger.info(f"\n🚀 Processing work item: {item.id} — {item.title}\n   🤖 Model: {selected_model} | 🧠 Backend: {backend_provider} | ⏱️  Timeout: {timeout_str}\n")

        item_logger = run_logger.start_item_log(item.id, item.title) if run_logger else None
        max_gate_rejections = global_config.max_gate_rejections_per_item

        if interactive:
            terminal_ui.ui.stop()
            confirm = input("Proceed with this item? [Y/n]: ").strip().lower()
            terminal_ui.ui.start()
            if confirm and confirm != 'y':
                _log_failure(run_logger, item_logger)
                return _fail_result(failure_reason="Skipped by user")

        logger.info("\n\U0001f512 Claiming work item...")
        if not _assign(item.id):
            _log_failure(run_logger, item_logger)
            return _fail_result(failure_reason="Failed to assign work item")
        _session = WorkItemSession(item_id=item.id, agent_name=get_agent_name(default="pokepoke"))
        _session._assigned = True
        worktree_path = setup_worktree(item, lock_timeout=worktree_lock_timeout,
            run_logger=run_logger, item_logger=item_logger, repo_path=cfg.repo_path)
        if worktree_path is None:
            _log_failure(run_logger, item_logger)
            return _fail_result(failure_reason="Failed to create worktree")
        _session.worktree_path = str(worktree_path)
        _session._worktree_created = _session._branch_created = True
        pokepoke_root = Path(cfg.repo_path) if cfg.repo_path else Path.cwd()
        worktree_cwd = str(worktree_path)
        last_feedback = ""
        accumulated_feedback: list[str] = []
        accumulated_stats, gate_success = AgentStats(), False
        timeout_restart_count = copilot_failure_count = 0
        backoff_delay = _BACKOFF_BASE_SECONDS
        work_agent_iteration = 1
        gate_rejection_count = int((item.metadata or {}).get('gate_rejection_count', 0))
        gate_resume_session_id = gate_resume_output_summary = gate_resume_feedback = None
        last_retry_was_gate_feedback, current_work_agent_id = False, base_agent_id
        resume_session_id = resume_output_summary = None
        result = CopilotResult(work_item_id=item.id, success=False,
            error="Session aborted due to application shutdown", attempt_count=0)

        # Load previous worker context from beads comments (persists across sessions)
        _get_comments = cfg.beads_client.get_item_comments if cfg.beads_client else None
        prior_contexts = get_worker_contexts(item.id, get_comments_fn=_get_comments)
        previous_worker_context = format_worker_context_for_prompt(prior_contexts)

        # Check for resume context from existing worktree (for reclaimed stale items)
        worktree_resume_context = _load_resume_contexts(item, worktree_path, pokepoke_root)

        _gt = get_gate_step_tracker()
        gate_resume_enabled = global_config.gate_reverify_resume_enabled

        # ── Merge-retry fast-path ──────────────────────────────────────
        # If a previous attempt passed the gate but failed only at merge,
        # the worktree already has validated, committed work. Skip work +
        # gate agents and jump directly to finalization (merge step).
        fast_result = try_merge_retry_fast_path(
            item, worktree_path, worktree_cwd, selected_model, start_time,
            accumulated_stats, run_logger, item_logger, base_agent_id,
            cfg.run_beta_test, cfg.repo_path,
        )
        if fast_result is not None:
            if getattr(fast_result, '_merge_retry_finalized', False):
                _session = None
            return fast_result

        while not is_shutting_down():
            elapsed = time.time() - start_time
            _gt.start_work(base_agent_id, item.id, work_agent_iteration, gate_rejection_count)
            if timeout_seconds > 0 and elapsed >= timeout_seconds:
                timeout_restart_count += 1
                if timeout_restart_count > cfg.max_timeout_restarts:
                    _log_failure(run_logger, item_logger, request_count)
                    terminal_ui.ui.set_current_agent(None)
                    return _fail_result(request_count=request_count, stats=accumulated_stats,
                                        cleanup_agent_runs=cleanup_agent_runs, gate_agent_runs=gate_agent_runs,
                                        failure_reason=f"Exceeded max timeout restarts ({cfg.max_timeout_restarts})")
                logger.info(f"\n\u23f1\ufe0f  TIMEOUT: Restarting {item.id} (attempt {timeout_restart_count}/{cfg.max_timeout_restarts}), backing off {backoff_delay}s")
                time.sleep(backoff_delay)
                backoff_delay = min(backoff_delay * 2, _BACKOFF_MAX_SECONDS)
                start_time = time.time()
                elapsed = 0

            remaining_timeout = (timeout_seconds - elapsed) if timeout_seconds > 0 else None

            # Append feedback if retrying
            if last_feedback:
                if last_retry_was_gate_feedback:
                    logger.info("\n🔄 Restarting Work Agent with feedback...")
                else:
                    logger.info("\n⏱️  Resuming Work Agent after timeout...")
                accumulated_feedback, work_agent_iteration = _apply_gate_feedback(
                    last_feedback, accumulated_feedback, work_agent_iteration)
            terminal_ui.ui.set_current_agent("Work Agent")
            from pokepoke.stats.metrics_context import agent_type_context
            prompt_template = selected_prompt_template or "beads-item"
            is_resume = resume_session_id is not None

            # Combine worktree resume context with worker context
            combined_context = _combine_resume_contexts(
                worktree_resume_context, previous_worker_context
            )

            if is_resume:
                work_prompt = build_resume_prompt(
                    item,
                    previous_output_summary=resume_output_summary,
                    retry_feedback=accumulated_feedback or None,
                )
            else:
                work_prompt = build_prompt_from_work_item(
                    item, template_name=prompt_template,
                    retry_feedback=accumulated_feedback or None,
                    previous_worker_context=combined_context)
            with agent_type_context("work"):
                is_retry = work_agent_iteration > 1
                if is_retry and not last_retry_was_gate_feedback:
                    # Timeout/crash retry: reuse the existing agent card
                    agent_id = current_work_agent_id
                    resume_in_place = True
                    parent_for_status = None
                else:
                    # First attempt or gate rejection retry: new card
                    agent_id = f"{base_agent_id}-retry-{work_agent_iteration}" if is_retry else base_agent_id
                    current_work_agent_id = agent_id
                    resume_in_place = False
                    parent_for_status = base_agent_id if is_retry else None
                terminal_ui.ui.push_agent_status(agent_id, get_agent_name(default="pokepoke"),
                    iteration=work_agent_iteration, status="running", model=selected_model,
                    parent_agent_id=parent_for_status,
                    work_item_id=item.id, work_item_title=item.title, agent_type="work",
                    agent_prompt=work_prompt, resume_in_place=resume_in_place)

                branch_error = verify_worktree_branch(item.id, worktree_cwd)
                if branch_error:
                    logger.error(f"\n❌ {branch_error}")
                    _log_failure(run_logger, item_logger, request_count)
                    terminal_ui.ui.set_current_agent(None)
                    return _fail_result(request_count=request_count, stats=accumulated_stats,
                                      cleanup_agent_runs=cleanup_agent_runs, gate_agent_runs=gate_agent_runs,
                                      failure_reason=branch_error)
                with terminal_ui.ui.agent_output_for(agent_id):
                    result = invoke_copilot(
                        item, prompt=work_prompt, timeout=remaining_timeout,
                        item_logger=item_logger, model=selected_model, cwd=worktree_cwd,
                        session_id=resume_session_id, is_resume=is_resume)
            request_count += result.attempt_count
            _gt.work_done()

            current_stats = _extract_agent_stats(result)
            if current_stats:
                accumulated_stats.accumulate(current_stats)

            # Invariant: Copilot SDK backend always sets session_id on all exit paths.
            if _check_sdk_invariant(backend_provider, result, item.id):
                break

            is_process_crash = result.error and (
                "process died" in result.error.lower() or "exited unexpectedly" in result.error.lower())

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

                retry, feedback = _maybe_retry_copilot(
                    result, copilot_failure_count, global_config.max_copilot_failure_retries, run_logger, item.id)
                if retry:
                    last_feedback = feedback
                    last_retry_was_gate_feedback = False  # Not a gate rejection
                    _gt.finish_run("failed")
                    continue
                _maybe_decompose(item, copilot_failure_count, gate_rejection_count, global_config)
                _gt.finish_run("failed")
                break

            _log_commit_status(worktree_cwd)

            outcome = result.work_agent_outcome
            if outcome and outcome.status in _FAIL_FAST_STATUSES:
                ff_result, too_large_ctx = _handle_fail_fast_outcome(
                    outcome, item, _comment, _block, _session,
                    run_logger, item_logger, request_count,
                    accumulated_stats, cleanup_agent_runs, gate_agent_runs, _gt,
                )
                if ff_result is not None:
                    terminal_ui.ui.set_current_agent(None)
                    return ff_result
                if too_large_ctx:
                    _maybe_decompose(
                        item, copilot_failure_count, gate_rejection_count, global_config,
                        too_large_context=too_large_ctx,
                    )
                break

            from pokepoke.beads.reconciliation import is_beads_item_closed
            if is_beads_item_closed(item.id):
                logger.warning("\n✅ Agent already closed beads item — skipping cleanup and gate checks")
                _gt.item_closed()
                gate_success = True
                break

            _gt.cleanup_done()
            cleanup_success, cleanup_runs = run_cleanup_with_timeout(
                item, result, pokepoke_root, start_time, timeout_seconds, cfg.timeout_hours,
                worktree_cwd, parent_agent_id=base_agent_id, item_logger=item_logger)
            cleanup_agent_runs += cleanup_runs

            if not cleanup_success:
                _gt.mark_failure("3")
                result.success = False
                _log_failure(run_logger, item_logger, request_count)
                return _fail_result(request_count=request_count, stats=accumulated_stats,
                                    cleanup_agent_runs=cleanup_agent_runs, gate_agent_runs=gate_agent_runs,
                                    failure_reason="Cleanup agent failed to resolve uncommitted changes")

            _gt.complete_step("3")
            if not global_config.gate_agent_enabled:
                logger.warning("\n⏭️  Gate Agent disabled via config — skipping verification")
                _gt.gate_disabled()
                gate_success = True
                break

            _gt.gate_start()
            gate_loop_result = run_gate_loop(GateLoopContext(
                item=item, result=result, worktree_cwd=worktree_cwd,
                pokepoke_root=pokepoke_root, selected_model=selected_model,
                base_agent_id=base_agent_id, max_gate_rejections=max_gate_rejections,
                gate_rejection_count=gate_rejection_count, gate_agent_runs=gate_agent_runs,
                item_logger=item_logger, comment_fn=_comment, defer_fn=_defer,
                resume_session_id=gate_resume_session_id if gate_resume_enabled else None,
                resume_reason="reverify" if gate_resume_enabled and last_retry_was_gate_feedback else None,
                resume_output_summary=gate_resume_output_summary if gate_resume_enabled else None,
                resume_feedback=gate_resume_feedback if gate_resume_enabled else None,
            ), _gt)
            gate_agent_runs = gate_loop_result.gate_agent_runs
            gate_rejection_count = gate_loop_result.gate_rejection_count
            if gate_loop_result.gate_success:
                gate_success = True
                backoff_delay = _BACKOFF_BASE_SECONDS
                break
            if gate_loop_result.exceeded_max:
                _maybe_decompose(item, copilot_failure_count, gate_rejection_count, config)
                result.gate_rejected = True
                result.error = f"Exceeded max gate rejections ({max_gate_rejections})"
                _log_failure(run_logger, item_logger, request_count)
                break
            if gate_loop_result.feedback:
                resume_session_id = None
                resume_output_summary = None
                last_feedback = gate_loop_result.feedback
                last_retry_was_gate_feedback = True
                gate_resume_session_id = gate_loop_result.session_id
                gate_resume_output_summary = gate_loop_result.last_output_summary
                gate_resume_feedback = gate_loop_result.feedback
            else:
                break  # Gate infra failure with no fallback

        # Save worker context for future workers when this attempt failed
        if not result.success or result.gate_rejected:
            save_worker_context(
                item.id,
                attempt_number=work_agent_iteration,
                failure_reason=result.error or "Unknown failure",
                gate_feedback=accumulated_feedback or None,
                error_summary=result.last_output_summary,
                add_comment_fn=_comment,
            )

        final_result, finalized = _finalize_and_flag_merge_retry(
            result=result, item=item, worktree_path=worktree_path,
            selected_model=selected_model, start_time=start_time,
            request_count=request_count, accumulated_stats=accumulated_stats,
            cleanup_agent_runs=cleanup_agent_runs, gate_agent_runs=gate_agent_runs,
            gate_success=gate_success, run_logger=run_logger, item_logger=item_logger,
            base_agent_id=base_agent_id, run_beta_test=cfg.run_beta_test, repo_path=cfg.repo_path,
        )
        if finalized:
            _session = None  # Finalization succeeded — skip cleanup
        return final_result

    finally:
        set_current_work_item_id(None)
        set_current_repo_name(None)
        if _session is not None and not is_shutting_down():
            try:
                _session.cleanup_on_failure()
            except Exception as exc:
                logger.error("Cleanup failed in finally block: %s", exc, exc_info=True)
        unregister_agent()

