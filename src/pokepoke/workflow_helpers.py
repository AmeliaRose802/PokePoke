"""Helper functions extracted from workflow.py to keep that module within the 400-line limit."""

import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING

from pokepoke import terminal_ui
from pokepoke.agent_runner import run_beta_tester, run_gate_agent
from pokepoke.beads import assign_and_sync_item
from pokepoke.cleanup_agents import run_cleanup_loop
from pokepoke.git_operations import has_uncommitted_changes
from pokepoke.model_pricing import calculate_cost
from pokepoke.reconciliation import reconcile_completed_item
from pokepoke.terminal_ui import format_work_item_banner, set_terminal_banner
from pokepoke.types import AgentStats, BeadsWorkItem, CopilotResult, ModelCompletionRecord, WorkItemResult
from pokepoke.worktree_finalization import finalize_work_item
from pokepoke.worktrees import cleanup_worktree, create_worktree

if TYPE_CHECKING:
    from pokepoke.logging_utils import ItemLogger, RunLogger

logger = logging.getLogger(__name__)


# ── Small utility helpers (moved from workflow.py) ──────────────────────────


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
) -> WorkItemResult:
    """Create a failed WorkItemResult."""
    return WorkItemResult(
        success=False, request_count=request_count, stats=stats,
        cleanup_agent_runs=cleanup_agent_runs, gate_agent_runs=gate_agent_runs,
        model_completion=model_completion,
    )


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
        lines_removed=stats.lines_removed if stats else None,
    )


# ── Worktree + pre-loop setup helpers ────────────────────────────────────────


def _setup_worktree(
    item: BeadsWorkItem, lock_timeout: float = 300.0,
    run_logger: "RunLogger | None" = None, item_logger: "ItemLogger | None" = None,
) -> Path | None:
    """Create worktree, logging errors to both file logs and UI."""
    print(f"\n\U0001f333 Creating worktree for {item.id}...")
    try:
        worktree_path = create_worktree(item.id, lock_timeout=lock_timeout)
        print(f"   Created at: {worktree_path}")
        return worktree_path
    except Exception as e:
        error_msg = f"Failed to create worktree for {item.id}: {e}"
        print(f"\n\u274c {error_msg}")
        logger.error(error_msg)
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
            print("\u23ed\ufe0f  Skipped.")
            _log_failure(run_logger, item_logger)
            return _fail_result(), False, None, "", ""

    print("\n\U0001f512 Claiming work item...")
    if not assign_and_sync_item(item.id):
        print(f"\u274c Failed to assign work item {item.id}")
        _log_failure(run_logger, item_logger)
        return _fail_result(), False, None, "", ""

    worktree_path = _setup_worktree(
        item, lock_timeout=worktree_lock_timeout,
        run_logger=run_logger, item_logger=item_logger,
    )
    if worktree_path is None:
        print(f"\u21a9\ufe0f  Returning {item.id} to queue (unassigning due to worktree failure)...")
        _log_failure(run_logger, item_logger)
        return _fail_result(), True, None, "", ""

    pokepoke_root_cwd = str(Path.cwd())
    worktree_cwd = str(worktree_path)
    print(f"   Working directory: {worktree_cwd}\n")
    return None, True, worktree_path, pokepoke_root_cwd, worktree_cwd


# ── Gate agent helper ─────────────────────────────────────────────────────────


def _run_gate_check(
    item: BeadsWorkItem,
    worktree_cwd: str,
    selected_model: str,
    gate_agent_runs: int,
    base_agent_id: str,
) -> tuple[bool, str | None, int]:
    """Invoke the gate agent. Returns (gate_success, gate_reason, updated_gate_runs)."""
    from pokepoke.git_operations import build_handoff_context
    handoff_ctx = build_handoff_context(cwd=worktree_cwd)
    gate_iteration = gate_agent_runs + 1
    gate_agent_id = f"{base_agent_id}-gate-{gate_iteration}"
    try:
        with terminal_ui.ui.agent_output_for(gate_agent_id):
            gate_success, gate_reason, _ = run_gate_agent(
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
    return gate_success, gate_reason, gate_agent_runs


# ── Small loop-body helpers ──────────────────────────────────────────────────


def _extract_agent_stats(result: CopilotResult) -> AgentStats | None:
    """Parse stats from a CopilotResult (from structured stats or raw output)."""
    from pokepoke.stats import parse_agent_stats
    if result.stats:
        return result.stats
    if result.output:
        return parse_agent_stats(result.output)
    return None


def _apply_gate_feedback(
    item: BeadsWorkItem, last_feedback: str, work_agent_iteration: int,
) -> tuple[BeadsWorkItem, int]:
    """Append gate-agent feedback to item description; return updated (item, iteration)."""
    hdr = "**PREVIOUS GATE AGENT FEEDBACK:**"
    desc = item.description or ""
    base, sec = (desc.split(hdr, 1) if hdr in desc else (desc, ""))
    prev = [e for e in sec.strip().splitlines() if e.strip().startswith("- ")]
    base_stripped = base.rstrip()
    sep = "\n\n" if base_stripped else ""
    item.description = base_stripped + f"{sep}{hdr}\n" + "\n".join(prev[-2:] + [f"- {last_feedback}"])
    return item, work_agent_iteration + 1


def _log_commit_status(worktree_cwd: str) -> None:
    """Print a summary of committed/uncommitted state for the worktree."""
    from pokepoke.git_operations import has_commits_ahead, has_uncommitted_changes
    if has_uncommitted_changes(cwd=worktree_cwd):
        return
    ahead = has_commits_ahead(cwd=worktree_cwd)
    if ahead > 0:
        print(f"\n✅ All changes committed ({ahead} commit{'s' if ahead != 1 else ''} ahead) — skipping cleanup")
    else:
        print("\n✅ No changes made — work item may already be complete")


# ── Retry helper ─────────────────────────────────────────────────────────────


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
    print(f"\n🔄 Copilot attempt {failure_count} failed, retrying ({failure_count}/{max_retries})...")
    if run_logger:
        run_logger.log_orchestrator(
            f"Copilot failure on attempt {failure_count} for {item_id}, retrying with feedback",
        )
    return True, f"[Copilot failure] {feedback}"


# ── Cleanup helper (moved from workflow.py) ───────────────────────────────────


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
        if elapsed >= timeout_seconds:
            print(f"\n⏱️  TIMEOUT: Execution exceeded {timeout_hours} hours during cleanup")
            print(f"   Restarting item {item.id} in same worktree...\n")
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


# ── Post-loop finalisation helper ─────────────────────────────────────────────


def _finalize_item_result(  # noqa: C901 – inherently complex; see workflow.py process_work_item
    result: CopilotResult,
    item: BeadsWorkItem,
    worktree_path: Path | None,
    selected_model: str,
    start_time: float,
    request_count: int,
    accumulated_stats: AgentStats,
    cleanup_agent_runs: int,
    gate_agent_runs: int,
    gate_success: bool,
    run_logger: "RunLogger | None",
    item_logger: "ItemLogger | None",
    base_agent_id: str,
    run_beta_test: bool,
) -> tuple[WorkItemResult, bool]:
    """Handle post-loop outcome. Returns (WorkItemResult, finalized_successfully)."""
    if result.success:
        set_terminal_banner(format_work_item_banner(item.id, item.title, "Finalizing"))
        success = finalize_work_item(item, worktree_path, parent_agent_id=base_agent_id)
        item_stats = accumulated_stats
        set_terminal_banner(format_work_item_banner(item.id, item.title, "Completed" if success else "Failed"))
        if success and run_beta_test:
            set_terminal_banner(format_work_item_banner(item.id, item.title, "Beta Testing"))
            beta_stats = run_beta_tester()
            if beta_stats and item_stats:
                item_stats.accumulate(beta_stats)
            set_terminal_banner(format_work_item_banner(item.id, item.title, "Completed"))
        if run_logger and item_logger:
            item_logger.log_summary(success, request_count)
            run_logger.log_orchestrator(
                f"Completed work item with {request_count} agent requests - Status: {'SUCCESS' if success else 'FAILURE'}"
            )
        terminal_ui.ui.set_current_agent(None)
        gate_passed: bool | None = gate_success if gate_agent_runs > 0 else None
        dur = time.time() - start_time
        model_completion = _build_completion_record(
            item.id, selected_model, dur, success, gate_passed, item_stats, request_count,
        ) if success else None
        return WorkItemResult(
            success=success, request_count=request_count, stats=item_stats,
            cleanup_agent_runs=cleanup_agent_runs, gate_agent_runs=gate_agent_runs,
            model_completion=model_completion,
        ), success

    # Failure path — check if work is actually completed despite session failure
    try:
        reconciled, evidence = reconcile_completed_item(item, worktree_path, run_logger)
    except Exception as exc:  # pragma: no cover - best-effort
        logger.debug("Reconciliation check failed (non-fatal): %s", exc)
        reconciled, evidence = False, {}
    if reconciled:
        ev = evidence
        print(
            f"\n⚠️  Copilot session reported FAILURE but state shows work already completed."
            f"\n   Evidence: beads_closed={ev['beads_closed']}, "
            f"commits_on_default={ev['commits_on_default']}, "
            f"worktree_cleaned={ev['worktree_cleaned']}"
        )
        if run_logger and item_logger:
            item_logger.log_summary(True, request_count)
            run_logger.log_orchestrator(
                "Outcome reconciled after session failure: treating as SUCCESS", level="WARNING",
            )
        terminal_ui.ui.set_current_agent(None)
        dur = time.time() - start_time
        return WorkItemResult(
            success=True, request_count=request_count, stats=accumulated_stats,
            cleanup_agent_runs=cleanup_agent_runs, gate_agent_runs=gate_agent_runs,
            model_completion=_build_completion_record(
                item.id, selected_model, dur, True,
                gate_success if gate_agent_runs > 0 else None, accumulated_stats, request_count,
            ),
        ), True

    set_terminal_banner(format_work_item_banner(item.id, item.title, "Failed"))
    print(f"\n❌ Failed to complete work item: {result.error}")
    print("\n🧹 Cleaning up worktree...")
    cleanup_worktree(item.id, force=True)
    _log_failure(run_logger, item_logger, request_count)
    terminal_ui.ui.set_current_agent(None)
    dur = time.time() - start_time
    model_completion = _build_completion_record(
        item.id, selected_model, dur, False, False, accumulated_stats, request_count,
    )
    return _fail_result(
        request_count=request_count, cleanup_agent_runs=cleanup_agent_runs,
        gate_agent_runs=gate_agent_runs, model_completion=model_completion,
        stats=accumulated_stats,
    ), False
