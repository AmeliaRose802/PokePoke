"""Helper functions extracted from workflow.py to keep that module within the 400-line limit."""

import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING

from pokepoke.agents.agent_runner import run_gate_agent
from pokepoke.agents.cleanup_agents import run_cleanup_loop
from pokepoke.beads.beads import assign_and_sync_item
from pokepoke.desktop import terminal_ui
from pokepoke.desktop.terminal_ui import format_work_item_banner, set_terminal_banner
from pokepoke.git.git_operations import has_uncommitted_changes
from pokepoke.types import AgentStats, BeadsWorkItem, CopilotResult, ModelCompletionRecord, WorkItemResult
from pokepoke.worktrees.worktrees import create_worktree

if TYPE_CHECKING:
    from pokepoke.utils.logging_utils import ItemLogger, RunLogger

logger = logging.getLogger(__name__)


def _log_failure(
    run_logger: "RunLogger | None",
    item_logger: "ItemLogger | None",
    request_count: int = 0,
) -> None:
    """Log failure summary if loggers are available."""
    if run_logger and item_logger:
        item_logger.log_summary(False, request_count)
        run_logger.log_orchestrator(
            f"Completed work item with {request_count} agent requests - Status: FAILURE"
        )


def _fail_result(
    request_count: int = 0,
    stats: AgentStats | None = None,
    cleanup_agent_runs: int = 0,
    gate_agent_runs: int = 0,
    model_completion: ModelCompletionRecord | None = None,
    failure_reason: str | None = None,
) -> WorkItemResult:
    """Create a failed WorkItemResult."""
    return WorkItemResult(
        success=False, request_count=request_count, stats=stats,
        cleanup_agent_runs=cleanup_agent_runs, gate_agent_runs=gate_agent_runs,
        model_completion=model_completion, failure_reason=failure_reason,
    )


def setup_worktree(
    item: BeadsWorkItem, lock_timeout: float = 300.0,
    run_logger: "RunLogger | None" = None, item_logger: "ItemLogger | None" = None,
    repo_path: str | None = None,
) -> Path | None:
    """Create worktree, logging errors to both file logs and UI."""
    logger.info(f"\n\U0001f333 Creating worktree for {item.id}...")
    try:
        worktree_path = create_worktree(item.id, lock_timeout=lock_timeout, repo_path=repo_path)
        logger.info(f"   Created at: {worktree_path}")
        return worktree_path
    except Exception as e:
        error_msg = f"Failed to create worktree for {item.id}: {e}"
        logger.error(f"\n\u274c {error_msg}")
        if run_logger:
            run_logger.log_orchestrator(error_msg, level="ERROR")
        if item_logger:
            item_logger.log_error(error_msg)
        return None


def _pre_loop_validate(
    item: BeadsWorkItem,
    interactive: bool,
    worktree_lock_timeout: float,
    run_logger: "RunLogger | None",
    item_logger: "ItemLogger | None",
) -> "tuple[WorkItemResult | None, bool, Path | None, str, str]":
    """Interactive confirmation, assignment, and worktree creation.

    Returns (early_result, was_assigned, worktree_path, pokepoke_root_cwd, worktree_cwd).
    If *early_result* is not None the caller must return it immediately.
    """
    if interactive:
        terminal_ui.ui.stop()
        confirm = input("Proceed with this item? [Y/n]: ").strip().lower()
        terminal_ui.ui.start()
        if confirm and confirm != "y":
            logger.warning("\u23ed\ufe0f  Skipped.")
            _log_failure(run_logger, item_logger)
            return _fail_result(), False, None, "", ""

    logger.info("\n\U0001f512 Claiming work item...")
    if not assign_and_sync_item(item.id):
        logger.error(f"\u274c Failed to assign work item {item.id}")
        _log_failure(run_logger, item_logger)
        return _fail_result(), False, None, "", ""

    worktree_path = setup_worktree(
        item, lock_timeout=worktree_lock_timeout,
        run_logger=run_logger, item_logger=item_logger,
    )
    if worktree_path is None:
        logger.error(f"\u21a9\ufe0f  Returning {item.id} to queue (unassigning due to worktree failure)...")
        _log_failure(run_logger, item_logger)
        return _fail_result(), True, None, "", ""

    pokepoke_root_cwd = str(Path.cwd())
    worktree_cwd = str(worktree_path)
    logger.info(f"   Working directory: {worktree_cwd}\n")
    return None, True, worktree_path, pokepoke_root_cwd, worktree_cwd


def _run_gate_check(
    item: BeadsWorkItem,
    worktree_cwd: str,
    selected_model: str,
    gate_agent_runs: int,
    base_agent_id: str,
) -> tuple[bool, str | None, int, bool]:
    """Invoke the gate agent. Returns (gate_success, gate_reason, updated_gate_runs, crashed).

    ``crashed`` is True when the gate agent failed due to an infrastructure
    error rather than a deliberate code-quality rejection.
    """
    from pokepoke.git.git_operations import build_handoff_context
    handoff_ctx = build_handoff_context(cwd=worktree_cwd)
    gate_iteration = gate_agent_runs + 1
    gate_agent_id = f"{base_agent_id}-gate-{gate_iteration}"
    try:
        with terminal_ui.ui.agent_output_for(gate_agent_id):
            gate_success, gate_reason, _, gate_crashed = run_gate_agent(
                item, cwd=worktree_cwd, work_model=selected_model,
                handoff_context=handoff_ctx,
                agent_id=gate_agent_id, agent_iteration=gate_iteration,
                parent_agent_id=base_agent_id,
            )
    except Exception as e:
        logger.warning("Gate agent raised exception: %s", e, exc_info=True)
        gate_agent_runs += 1
        terminal_ui.ui.push_agent_status(
            gate_agent_id, "Gate Agent", iteration=gate_agent_runs, status="failed",
            parent_agent_id=base_agent_id, work_item_id=item.id,
            work_item_title=item.title, agent_type="gate",
        )
        raise
    gate_agent_runs += 1
    terminal_ui.ui.push_agent_status(
        gate_agent_id, "Gate Agent", iteration=gate_agent_runs,
        status="success" if gate_success else "failed",
        parent_agent_id=base_agent_id, work_item_id=item.id,
        work_item_title=item.title, agent_type="gate",
    )
    return gate_success, gate_reason, gate_agent_runs, gate_crashed


def _extract_agent_stats(result: CopilotResult) -> AgentStats | None:
    """Parse stats from a CopilotResult (from structured stats or raw output)."""
    from pokepoke.stats.stats import parse_agent_stats
    if result.stats:
        return result.stats
    if result.output:
        return parse_agent_stats(result.output)
    return None


def _apply_gate_feedback(
    new_feedback: str,
    accumulated_feedback: list[str],
    work_agent_iteration: int,
) -> tuple[list[str], int]:
    """Record gate-agent feedback without mutating the work item.

    Appends *new_feedback* to *accumulated_feedback* (keeping the last 3
    entries to bound prompt size) and bumps the iteration counter.

    Returns ``(updated_feedback_list, next_iteration)``.
    """
    accumulated_feedback = list(accumulated_feedback)  # defensive copy
    accumulated_feedback.append(new_feedback)
    # Keep only the most recent entries to avoid unbounded prompt growth
    accumulated_feedback = accumulated_feedback[-3:]
    return accumulated_feedback, work_agent_iteration + 1


def _log_commit_status(worktree_cwd: str) -> None:
    """Print a summary of committed/uncommitted state for the worktree."""
    from pokepoke.git.git_operations import has_commits_ahead
    if has_uncommitted_changes(cwd=worktree_cwd):
        return
    ahead = has_commits_ahead(cwd=worktree_cwd)
    if ahead > 0:
        logger.warning(f"\n✅ All changes committed ({ahead} commit{'s' if ahead != 1 else ''} ahead) — skipping cleanup")
    else:
        logger.info("\n✅ No changes made — work item may already be complete")


def _maybe_retry_copilot(
    result: CopilotResult,
    failure_count: int,
    max_retries: int,
    run_logger: "RunLogger | None",
    item_id: str,
) -> tuple[bool, str]:
    """Return (should_retry, feedback) after a Copilot invocation failure."""
    if failure_count > max_retries or result.is_rate_limited:
        return False, ""
    feedback = result.error or "Copilot agent did not complete the task"
    has_resume = result.session_id is not None and result.last_output_summary is not None
    resume_note = " (will resume session)" if has_resume else ""
    logger.error(f"\n🔄 Copilot attempt {failure_count} failed, retrying ({failure_count}/{max_retries}){resume_note}...")
    if run_logger:
        run_logger.log_orchestrator(
            f"Copilot failure on attempt {failure_count} for {item_id}, retrying with feedback{resume_note}",
        )
    return True, f"[Copilot failure] {feedback}"


def _maybe_decompose(
    item: BeadsWorkItem, copilot_failure_count: int,
    gate_rejection_count: int, config: object,
) -> None:
    """Check if a repeatedly failing item should be decomposed into sub-tasks."""
    from pokepoke.agents.decomposition_agent import run_decomposition, should_decompose
    total_failures = copilot_failure_count + gate_rejection_count
    threshold = int(getattr(config, 'decomposition_failure_threshold', 3))
    enabled = bool(getattr(config, 'decomposition_enabled', True))
    if should_decompose(item, total_failures, threshold, enabled):
        decomp_result = run_decomposition(item, total_failures)
        if decomp_result.success:
            logger.info("\n🔀 Item %s decomposed into %d sub-tasks",
                        item.id, len(decomp_result.child_ids))


def run_cleanup_with_timeout(
    item: BeadsWorkItem, result: CopilotResult, repo_root: Path, start_time: float,
    timeout_seconds: float, timeout_hours: float, cwd: str | None = None,
    parent_agent_id: str | None = None,
) -> tuple[bool, int]:
    """Run cleanup loop until no uncommitted changes remain or timeout is reached."""
    cleanup_agent_runs = 0
    cleanup_attempt = 0

    while result.success and has_uncommitted_changes(cwd=cwd):
        elapsed = time.time() - start_time
        if timeout_seconds > 0 and elapsed >= timeout_seconds:
            logger.info(f"\n⏱️  TIMEOUT: Execution exceeded {timeout_hours} hours during cleanup")
            logger.info(f"   Restarting item {item.id} in same worktree...\n")
            return False, cleanup_agent_runs

        cleanup_attempt += 1
        set_terminal_banner(format_work_item_banner(item.id, item.title, f"Cleanup #{cleanup_attempt}"))
        cleanup_success, cleanup_runs = run_cleanup_loop(
            item, result, cwd=cwd, parent_agent_id=parent_agent_id,
        )
        cleanup_agent_runs += cleanup_runs
        if not cleanup_success:
            break

    return result.success, cleanup_agent_runs
