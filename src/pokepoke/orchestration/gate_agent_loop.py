"""Gate agent invocation loop with crash/timeout retry and rejection handling.

Extracted from workflow.py to keep that file under the 400-line limit.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pokepoke.agents.agent_runner import run_gate_agent
from pokepoke.desktop import terminal_ui
from pokepoke.orchestration.gate_step_tracker import GateStepTracker

if TYPE_CHECKING:
    from pokepoke.types_agent import CopilotResult
    from pokepoke.types_beads import BeadsWorkItem

logger = logging.getLogger(__name__)

_MAX_GATE_CRASH_RETRIES = 3
_MAX_GATE_TIMEOUT_RETRIES = 3


@dataclass
class GateLoopContext:
    """All inputs the gate loop needs from the outer workflow."""

    item: BeadsWorkItem
    result: CopilotResult
    worktree_cwd: str
    pokepoke_root: Path
    selected_model: str
    base_agent_id: str
    max_gate_rejections: int
    gate_rejection_count: int
    gate_agent_runs: int
    item_logger: Any | None
    comment_fn: Callable[[str, str], Any]
    defer_fn: Callable[[str, str], Any]
    resume_session_id: str | None = None
    resume_reason: str | None = None
    resume_output_summary: str | None = None
    resume_feedback: str | None = None


@dataclass
class GateLoopResult:
    """Outputs from the gate loop back to the outer workflow."""

    gate_success: bool
    gate_rejection_count: int
    gate_agent_runs: int
    feedback: str | None = None
    exceeded_max: bool = False
    session_id: str | None = None
    last_output_summary: str | None = None


@dataclass
class GateOutcomeDetails:
    gate_agent_runs: int
    session_id: str | None
    last_output_summary: str | None
    gate_reason: str = ""
    timed_out: bool = False


def run_gate_loop(ctx: GateLoopContext, gt: GateStepTracker) -> GateLoopResult:
    """Run the gate agent with crash/timeout retry and rejection handling.

    Returns a GateLoopResult describing the outcome. The caller decides
    whether to break or retry the work agent.
    """
    gate_crash_attempts = gate_timeout_attempts = 0
    gate_resume_session_id: str | None = ctx.resume_session_id
    gate_resume_reason: str | None = ctx.resume_reason
    gate_resume_output_summary: str | None = ctx.resume_output_summary
    gate_resume_feedback: str | None = ctx.resume_feedback
    gate_success = False
    gate_reason = ""
    gate_crashed = gate_timed_out = False
    gate_agent_runs = ctx.gate_agent_runs

    while gate_crash_attempts < _MAX_GATE_CRASH_RETRIES:
        from pokepoke.git.git_operations import build_handoff_context

        handoff_ctx = build_handoff_context(
            cwd=ctx.worktree_cwd, work_agent_outcome=ctx.result.work_agent_outcome
        )
        gate_iteration = gate_agent_runs + 1
        gate_agent_id = f"{ctx.base_agent_id}-gate-{gate_iteration}"
        gate_is_resume = gate_resume_session_id is not None
        resume_in_place = gate_is_resume
        gate_crashed = gate_timed_out = False

        try:
            with terminal_ui.ui.agent_output_for(gate_agent_id):
                if resume_in_place:
                    terminal_ui.ui.push_agent_status(
                        gate_agent_id, "Gate Agent",
                        iteration=gate_iteration, status="running",
                        parent_agent_id=ctx.base_agent_id,
                        work_item_id=ctx.item.id, work_item_title=ctx.item.title,
                        agent_type="gate", resume_in_place=True,
                    )
                gate_result = run_gate_agent(
                    ctx.item, cwd=ctx.worktree_cwd, work_model=ctx.selected_model,
                    handoff_context=handoff_ctx,
                    previous_output_summary=gate_resume_output_summary,
                    agent_id=gate_agent_id, agent_iteration=gate_iteration,
                    parent_agent_id=ctx.base_agent_id,
                    item_logger=ctx.item_logger,
                    session_id=gate_resume_session_id,
                    is_resume=gate_is_resume,
                    resume_reason=gate_resume_reason,
                    resume_feedback=gate_resume_feedback,
                )
            gate_success = gate_result.success
            gate_reason = gate_result.reason
            gate_crashed = gate_result.crashed
            gate_timed_out = gate_result.is_timeout
        except Exception as e:
            logger.warning(f"Gate agent raised exception: {e}", exc_info=True)
            gate_agent_runs += 1
            gate_crash_attempts += 1
            terminal_ui.ui.push_agent_status(
                gate_agent_id, "Gate Agent",
                iteration=gate_agent_runs, status="failed",
                parent_agent_id=ctx.base_agent_id,
                work_item_id=ctx.item.id, work_item_title=ctx.item.title,
                agent_type="gate",
            )
            if gate_crash_attempts < _MAX_GATE_CRASH_RETRIES:
                logger.error(f"\n⚠️  Gate crashed ({gate_crash_attempts}/{_MAX_GATE_CRASH_RETRIES}): {e}, retrying...")
                gate_resume_session_id = None
                continue
            logger.error(f"\n❌ Gate Agent crashed {gate_crash_attempts} times — giving up")
            raise

        gate_agent_runs += 1
        terminal_ui.ui.push_agent_status(
            gate_agent_id, "Gate Agent",
            iteration=gate_agent_runs,
            status="success" if gate_success else "failed",
            parent_agent_id=ctx.base_agent_id,
            work_item_id=ctx.item.id, work_item_title=ctx.item.title,
            agent_type="gate",
        )

        if gate_timed_out:
            gate_timeout_attempts += 1
            if gate_timeout_attempts < _MAX_GATE_TIMEOUT_RETRIES:
                gate_resume_session_id = gate_result.session_id
                gate_resume_reason = "timeout"
                gate_resume_output_summary = gate_result.last_output_summary
                gt.begin_step("5T", f"Timeout {gate_timeout_attempts}/{_MAX_GATE_TIMEOUT_RETRIES}")
                logger.info(
                    f"\n⏱️  Gate timed out ({gate_timeout_attempts}/{_MAX_GATE_TIMEOUT_RETRIES}), "
                    f"{'resuming' if gate_resume_session_id else 'retrying'}..."
                )
                continue
            gt.fail_step("5T", f"Timed out {gate_timeout_attempts} times")
            logger.error(f"\n❌ Gate Agent timed out {gate_timeout_attempts} times — giving up")
            ctx.comment_fn(ctx.item.id, f"Gate Agent timed out {gate_timeout_attempts} times:\n{gate_reason}")
            break

        if gate_crashed:
            gate_crash_attempts += 1
            gate_resume_session_id = None
            if gate_crash_attempts < _MAX_GATE_CRASH_RETRIES:
                gt.begin_step("5C", f"Crash {gate_crash_attempts}/{_MAX_GATE_CRASH_RETRIES}")
                logger.error(f"\n⚠️  Gate crashed ({gate_crash_attempts}/{_MAX_GATE_CRASH_RETRIES}): {gate_reason}, retrying...")
                continue
            gt.fail_step("5C", f"Crashed {gate_crash_attempts} times")
            logger.error(f"\n❌ Gate Agent crashed {gate_crash_attempts} times — giving up")
            ctx.comment_fn(ctx.item.id, f"Gate Agent crashed {gate_crash_attempts} times:\n{gate_reason}")

        break  # Not a crash/timeout — exit the retry loop

    # ── Post-loop: evaluate outcome ──────────────────────────────────
    if gate_success:
        logger.info("\n✅ Gate Agent signed off!")
        gt.mark_success("5", "6")
        return GateLoopResult(
            gate_success=True, gate_rejection_count=ctx.gate_rejection_count,
            gate_agent_runs=gate_agent_runs, session_id=gate_result.session_id,
            last_output_summary=gate_result.last_output_summary,
        )

    if gate_crashed or gate_timed_out:
        return _handle_gate_infra_failure(
            ctx,
            gt,
            GateOutcomeDetails(
                gate_agent_runs=gate_agent_runs,
                session_id=gate_result.session_id,
                last_output_summary=gate_result.last_output_summary,
                timed_out=gate_timed_out,
            ),
        )

    return _handle_gate_verdict(
        ctx,
        gt,
        GateOutcomeDetails(
            gate_agent_runs=gate_agent_runs,
            session_id=gate_result.session_id,
            last_output_summary=gate_result.last_output_summary,
            gate_reason=gate_reason,
        ),
    )


def _handle_gate_infra_failure(
    ctx: GateLoopContext, gt: GateStepTracker, details: GateOutcomeDetails,
) -> GateLoopResult:
    """Handle gate crash/timeout — fallback accept if worktree has commits."""
    from pokepoke.beads.reconciliation import worktree_branch_has_commits

    if worktree_branch_has_commits(ctx.item.id, ctx.pokepoke_root):
        fail_mode = "timed out" if details.timed_out else "crashed"
        logger.warning("\n⚠️  Gate Agent %s but worktree has valid commits — fallback accept", fail_mode)
        ctx.comment_fn(ctx.item.id, f"Gate Agent {fail_mode} but worktree has valid commits. Accepting via fallback.")
        gt.mark_success("5", "6")
        return GateLoopResult(
            gate_success=True, gate_rejection_count=ctx.gate_rejection_count,
            gate_agent_runs=details.gate_agent_runs, session_id=details.session_id,
            last_output_summary=details.last_output_summary,
        )

    gt.mark_failure("5")
    return GateLoopResult(
        gate_success=False, gate_rejection_count=ctx.gate_rejection_count,
        gate_agent_runs=details.gate_agent_runs, session_id=details.session_id,
        last_output_summary=details.last_output_summary,
    )


def _handle_gate_verdict(
    ctx: GateLoopContext, gt: GateStepTracker, details: GateOutcomeDetails,
) -> GateLoopResult:
    """Handle a definite gate verdict (approval, unclear, or rejection)."""
    from pokepoke.beads.reconciliation import worktree_branch_has_commits

    # Unclear verdict — fallback accept if there are commits
    if ("Gate Agent did not explicitly approve" in details.gate_reason or "could not be parsed" in details.gate_reason) and \
            worktree_branch_has_commits(ctx.item.id, ctx.pokepoke_root):
        logger.warning("\n⚠️  Gate verdict unclear but worktree has valid commits — fallback accept")
        ctx.comment_fn(
            ctx.item.id,
            f"Gate Agent verdict unclear: {details.gate_reason}\n"
            "However, worktree has valid commits that passed pre-commit hooks. Accepting via fallback.",
        )
        gt.mark_success("5", "6")
        return GateLoopResult(
            gate_success=True, gate_rejection_count=ctx.gate_rejection_count,
            gate_agent_runs=details.gate_agent_runs, session_id=details.session_id,
            last_output_summary=details.last_output_summary,
        )

    # Genuine rejection
    gt.complete_step("5")
    gt.fail_step("6", f"Rejected: {details.gate_reason[:100]}")

    from pokepoke.beads.beads_management import increment_gate_rejection_count

    new_count = increment_gate_rejection_count(ctx.item.id)
    rejection_count = new_count if new_count >= 0 else ctx.gate_rejection_count + 1

    logger.error(f"\n❌ Gate Agent rejected ({rejection_count}/{ctx.max_gate_rejections}): {details.gate_reason}")
    ctx.comment_fn(ctx.item.id, f"Gate Agent Rejection ({rejection_count}/{ctx.max_gate_rejections}):\n{details.gate_reason}")

    if rejection_count >= ctx.max_gate_rejections:
        logger.error(f"\n❌ Exceeded max gate rejections ({rejection_count}/{ctx.max_gate_rejections}) for {ctx.item.id}")
        gt.gate_rejected_max(rejection_count)
        ctx.defer_fn(
            ctx.item.id,
            f"Auto-deferred after {rejection_count} gate rejections (cap: {ctx.max_gate_rejections}). "
            f"Item likely too complex for a single agent session. Last rejection:\n{details.gate_reason}",
        )
        return GateLoopResult(
            gate_success=False, gate_rejection_count=rejection_count,
            gate_agent_runs=details.gate_agent_runs, exceeded_max=True,
            session_id=details.session_id, last_output_summary=details.last_output_summary,
        )

    gt.gate_rejected_retry(rejection_count, details.gate_reason)
    return GateLoopResult(
        gate_success=False, gate_rejection_count=rejection_count,
        gate_agent_runs=details.gate_agent_runs, feedback=details.gate_reason,
        session_id=details.session_id, last_output_summary=details.last_output_summary,
    )
