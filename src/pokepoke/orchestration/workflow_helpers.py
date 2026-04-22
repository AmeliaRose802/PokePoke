"""Helper functions extracted from workflow.py to keep that module within the 400-line limit."""

import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING

from pokepoke.agents.cleanup_agents import run_cleanup_loop
from pokepoke.desktop.terminal_ui import format_work_item_banner, set_terminal_banner
from pokepoke.git.git_operations import has_uncommitted_changes
from pokepoke.types import WorkItemResult
from pokepoke.types_agent import CopilotResult
from pokepoke.types_beads import BeadsWorkItem
from pokepoke.types_stats import AgentStats, ModelCompletionRecord
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
    *, too_large_context: str | None = None,
) -> None:
    """Check if a repeatedly failing item should be decomposed into sub-tasks."""
    from pokepoke.agents.decomposition_agent import run_decomposition, should_decompose
    total_failures = copilot_failure_count + gate_rejection_count
    threshold = int(getattr(config, 'decomposition_failure_threshold', 3))
    enabled = bool(getattr(config, 'decomposition_enabled', True))
    force = too_large_context is not None
    if should_decompose(item, total_failures, threshold, enabled, force=force):
        decomp_result = run_decomposition(item, total_failures, too_large_context=too_large_context)
        if decomp_result.success:
            logger.info("\n🔀 Item %s decomposed into %d sub-tasks",
                        item.id, len(decomp_result.child_ids))


def run_cleanup_with_timeout(
    item: BeadsWorkItem, result: CopilotResult, repo_root: Path, start_time: float,
    timeout_seconds: float, timeout_hours: float, cwd: str | None = None,
    parent_agent_id: str | None = None, item_logger: 'ItemLogger | None' = None,
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
            item_logger=item_logger,
        )
        cleanup_agent_runs += cleanup_runs
        if not cleanup_success:
            break

    return result.success, cleanup_agent_runs


def _combine_resume_contexts(
    worktree_context: str | None,
    worker_context: str | None,
) -> str | None:
    """Combine worktree resume context with worker context for the prompt.

    Worktree context (from git history) takes precedence as it's more detailed
    about what was actually committed. Worker context (from beads comments)
    supplements with failure reasons and gate feedback.

    Args:
        worktree_context: Resume context from existing worktree commits.
        worker_context: Previous worker context from beads comments.

    Returns:
        Combined context string, or None if both are empty.
    """
    if not worktree_context and not worker_context:
        return None
    if not worktree_context:
        return worker_context
    if not worker_context:
        return worktree_context
    # Both present - combine with worktree context first (more authoritative)
    return f"{worktree_context}\n\n{worker_context}"
