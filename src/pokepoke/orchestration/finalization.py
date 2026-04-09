"""Post-loop finalization helpers for work item processing."""

import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from pokepoke.agents.agent_runner import run_beta_tester
from pokepoke.beads.reconciliation import reconcile_completed_item
from pokepoke.desktop import terminal_ui
from pokepoke.desktop.terminal_ui import format_work_item_banner, set_terminal_banner
from pokepoke.orchestration.workflow_helpers import _fail_result, _log_failure
from pokepoke.types import AgentStats, BeadsWorkItem, CopilotResult, ModelCompletionRecord, WorkItemResult
from pokepoke.worktrees.worktree_finalization import finalize_work_item

if TYPE_CHECKING:
    from pokepoke.utils.logging_utils import ItemLogger, RunLogger

logger = logging.getLogger(__name__)


@dataclass
class ResultContext:
    """Bundles the parameters for _finalize_item_result to reduce argument count."""

    result: CopilotResult
    item: BeadsWorkItem
    worktree_path: Path | None
    selected_model: str
    start_time: float
    request_count: int
    accumulated_stats: AgentStats
    cleanup_agent_runs: int
    gate_agent_runs: int
    gate_success: bool
    run_logger: "RunLogger | None"
    item_logger: "ItemLogger | None"
    base_agent_id: str
    run_beta_test: bool
    repo_path: str | None = None


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
        agent_turns=request_count,
        retry_attempts=max(0, request_count - 1),
        api_duration=stats.api_duration if stats else None,
        lines_added=stats.lines_added if stats else None,
        lines_removed=stats.lines_removed if stats else None,
    )


def _finalize_item_result(
    ctx: ResultContext,
) -> tuple[WorkItemResult, bool]:
    """Handle post-loop outcome. Returns (WorkItemResult, finalized_successfully)."""
    if ctx.result.success:
        return _handle_success(ctx)
    return _handle_failure(ctx)


def _handle_success(ctx: ResultContext) -> tuple[WorkItemResult, bool]:
    """Handle the success branch of finalization."""
    set_terminal_banner(format_work_item_banner(ctx.item.id, ctx.item.title, "Finalizing"))
    assert ctx.worktree_path is not None, "worktree_path must be set when result is successful"
    success = finalize_work_item(
        ctx.item, ctx.worktree_path, parent_agent_id=ctx.base_agent_id, repo_path=ctx.repo_path,
    )
    if success:
        _store_discoveries(ctx.item, ctx.worktree_path)
    item_stats = ctx.accumulated_stats
    set_terminal_banner(format_work_item_banner(
        ctx.item.id, ctx.item.title, "Completed" if success else "Failed",
    ))
    if success and ctx.run_beta_test:
        set_terminal_banner(format_work_item_banner(ctx.item.id, ctx.item.title, "Beta Testing"))
        beta_stats = run_beta_tester()
        if beta_stats and item_stats:
            item_stats.accumulate(beta_stats)
        set_terminal_banner(format_work_item_banner(ctx.item.id, ctx.item.title, "Completed"))
    if ctx.run_logger and ctx.item_logger:
        ctx.item_logger.log_summary(success, ctx.request_count)
        ctx.run_logger.log_orchestrator(
            f"Completed work item with {ctx.request_count} agent requests"
            f" - Status: {'SUCCESS' if success else 'FAILURE'}"
        )
    terminal_ui.ui.set_current_agent(None)
    gate_passed: bool | None = ctx.gate_success if ctx.gate_agent_runs > 0 else None
    dur = time.time() - ctx.start_time
    model_completion = _build_completion_record(
        ctx.item.id, ctx.selected_model, dur, success, gate_passed,
        item_stats, ctx.request_count,
    ) if success else None
    return WorkItemResult(
        success=success, request_count=ctx.request_count, stats=item_stats,
        cleanup_agent_runs=ctx.cleanup_agent_runs, gate_agent_runs=ctx.gate_agent_runs,
        model_completion=model_completion,
    ), success


def _handle_failure(ctx: ResultContext) -> tuple[WorkItemResult, bool]:
    """Handle the failure branch — reconcile or record failure."""
    try:
        reconciled, evidence = reconcile_completed_item(ctx.item, ctx.worktree_path, ctx.run_logger)
    except Exception as exc:  # pragma: no cover - best-effort
        logger.debug("Reconciliation check failed (non-fatal): %s", exc)
        reconciled, evidence = False, {}

    if reconciled:
        return _reconcile_as_success(ctx, evidence)

    set_terminal_banner(format_work_item_banner(ctx.item.id, ctx.item.title, "Failed"))
    failure_reason = ctx.result.error or "Unknown failure"
    logger.error("\n❌ Failed to complete work item: %s", failure_reason)

    from pokepoke.beads.beads_management import fail_task
    fail_task(ctx.item.id, failure_reason)

    logger.warning("\n⚠️  Preserving worktree for %s (work may be recoverable)", ctx.item.id)
    _log_failure(ctx.run_logger, ctx.item_logger, ctx.request_count)
    terminal_ui.ui.set_current_agent(None)
    dur = time.time() - ctx.start_time
    model_completion = _build_completion_record(
        ctx.item.id, ctx.selected_model, dur, False, False,
        ctx.accumulated_stats, ctx.request_count,
    )
    return _fail_result(
        request_count=ctx.request_count, cleanup_agent_runs=ctx.cleanup_agent_runs,
        gate_agent_runs=ctx.gate_agent_runs, model_completion=model_completion,
        stats=ctx.accumulated_stats, failure_reason=failure_reason,
    ), False


def _reconcile_as_success(
    ctx: ResultContext, evidence: dict[str, bool],
) -> tuple[WorkItemResult, bool]:
    """Handle the case where a failed session is reconciled as actually successful."""
    logger.error(
        "\n⚠️  Copilot session reported FAILURE but state shows work already completed."
        "\n   Evidence: beads_closed=%s, commits_on_default=%s, "
        "commits_on_worktree_branch=%s, worktree_cleaned=%s",
        evidence.get("beads_closed"), evidence.get("commits_on_default"),
        evidence.get("commits_on_worktree_branch"), evidence.get("worktree_cleaned"),
    )
    if ctx.run_logger and ctx.item_logger:
        ctx.item_logger.log_summary(True, ctx.request_count)
        ctx.run_logger.log_orchestrator(
            "Outcome reconciled after session failure: treating as SUCCESS", level="WARNING",
        )
    terminal_ui.ui.set_current_agent(None)
    dur = time.time() - ctx.start_time
    return WorkItemResult(
        success=True, request_count=ctx.request_count, stats=ctx.accumulated_stats,
        cleanup_agent_runs=ctx.cleanup_agent_runs, gate_agent_runs=ctx.gate_agent_runs,
        model_completion=_build_completion_record(
            ctx.item.id, ctx.selected_model, dur, True,
            ctx.gate_success if ctx.gate_agent_runs > 0 else None,
            ctx.accumulated_stats, ctx.request_count,
        ),
    ), True


def _store_discoveries(item: BeadsWorkItem, worktree_path: Path | None) -> None:
    """Store discoveries in memory after successful work completion."""
    from pokepoke.config import get_config
    config = get_config()
    if not config.mcp_server.memory_enabled:
        return
    try:
        from pokepoke.models.memory_helpers import auto_discover_from_prompt, store_agent_discoveries
        from pokepoke.models.sdk_helpers import build_prompt_from_work_item
        work_prompt = build_prompt_from_work_item(item)
        discoveries = auto_discover_from_prompt(work_prompt, item)
        if discoveries:
            store_agent_discoveries(
                item, discoveries, repo_root=worktree_path.parent if worktree_path else None,
            )
            logger.debug("Stored %d discoveries in memory for item %s", len(discoveries), item.id)
    except Exception as e:
        logger.warning("Failed to store memories after completion: %s", e)
