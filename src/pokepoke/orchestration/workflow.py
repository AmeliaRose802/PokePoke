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
from pokepoke.models.copilot_sdk import build_prompt_from_work_item  # noqa: F401  # kept for test patching
from pokepoke.models.model_selection import get_assignment_for_item, select_model_for_item
from pokepoke.models.sdk_helpers import build_resume_prompt  # noqa: F401  # kept for test patching
from pokepoke.orchestration.finalization import (
    ResultContext as ResultContext,
)
from pokepoke.orchestration.finalization import (
    _finalize_item_result as _finalize_item_result,
)
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
from pokepoke.orchestration.workflow_loop import run_workflow_loop
from pokepoke.protocols import BeadsClient
from pokepoke.stats.metrics_context import set_current_repo_name, set_current_work_item_id
from pokepoke.types import AgentStats, BeadsWorkItem, WorkItemResult
from pokepoke.utils.shutdown import is_shutting_down, register_agent, unregister_agent
from pokepoke.worktrees.worktrees import cleanup_worktree, create_worktree  # noqa: F401 — kept for test patching

if TYPE_CHECKING:
    from pokepoke.utils.logging_utils import RunLogger
logger = logging.getLogger(__name__)
_LOCK_TIMEOUT_PER_AGENT = 120.0
_BACKOFF_BASE_SECONDS, _BACKOFF_MAX_SECONDS = 30, 240
_FAIL_FAST_STATUSES = frozenset({"blocked", "needs_clarification", "too_large"})

@dataclass
class WorkItemConfig:
    """Configuration bundle for optional process_work_item parameters."""
    timeout_hours: float = 0
    run_beta_test: bool = False
    max_timeout_restarts: int = 3
    repo_path: str | None = None
    beads_client: BeadsClient | None = None

def process_work_item(
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
        _get_comments = cfg.beads_client.get_item_comments if cfg.beads_client else None
        prior_contexts = get_worker_contexts(item.id, get_comments_fn=_get_comments)
        previous_worker_context = format_worker_context_for_prompt(prior_contexts)
        worktree_resume_context = _load_resume_contexts(item, worktree_path, pokepoke_root)
        accumulated_stats = AgentStats()

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

        loop_result = run_workflow_loop(
            item=item,
            cfg=cfg,
            base_agent_id=base_agent_id,
            selected_model=selected_model,
            selected_prompt_template=selected_prompt_template,
            global_config=global_config,
            backend_provider=backend_provider,
            start_time=start_time,
            timeout_seconds=timeout_seconds,
            max_gate_rejections=max_gate_rejections,
            worktree_cwd=worktree_cwd,
            pokepoke_root=pokepoke_root,
            run_logger=run_logger,
            item_logger=item_logger,
            session=_session,
            previous_worker_context=previous_worker_context,
            worktree_resume_context=worktree_resume_context,
            comment_fn=_comment,
            block_fn=_block,
            defer_fn=_defer,
            invoke_copilot_fn=invoke_copilot,
            run_cleanup_with_timeout_fn=run_cleanup_with_timeout,
            is_shutting_down_fn=is_shutting_down,
            apply_gate_feedback_fn=_apply_gate_feedback,
            check_sdk_invariant_fn=_check_sdk_invariant,
            combine_resume_contexts_fn=_combine_resume_contexts,
            extract_agent_stats_fn=_extract_agent_stats,
            fail_result_fn=_fail_result,
            handle_fail_fast_outcome_fn=_handle_fail_fast_outcome,
            log_commit_status_fn=_log_commit_status,
            log_failure_fn=_log_failure,
            maybe_decompose_fn=_maybe_decompose,
            maybe_retry_copilot_fn=_maybe_retry_copilot,
            ui_module=terminal_ui,
            get_agent_name_fn=get_agent_name,
            verify_worktree_branch_fn=verify_worktree_branch,
        )
        if loop_result.immediate_result is not None:
            return loop_result.immediate_result

        result = loop_result.result
        start_time = loop_result.start_time
        request_count = loop_result.request_count
        cleanup_agent_runs = loop_result.cleanup_agent_runs
        gate_agent_runs = loop_result.gate_agent_runs
        accumulated_stats = loop_result.accumulated_stats
        gate_success = loop_result.gate_success
        work_agent_iteration = loop_result.work_agent_iteration
        accumulated_feedback = loop_result.accumulated_feedback

        # Save worker context for future workers when this attempt failed
        if not result.success:
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

