"""Gate agent executor for verifying work items."""
import json
import logging
import re
from typing import TYPE_CHECKING

from pokepoke.config import get_config
from pokepoke.desktop import terminal_ui
from pokepoke.git.git_operations import get_default_branch
from pokepoke.models.ai_backends import invoke_copilot
from pokepoke.models.model_selection import select_gate_model
from pokepoke.models.sdk_helpers import build_gate_resume_prompt
from pokepoke.prompts.prompts import PromptService
from pokepoke.stats.gate_rejection_tracker import record_gate_check
from pokepoke.stats.metrics_context import agent_type_context
from pokepoke.stats.stats import parse_agent_stats
from pokepoke.types import BeadsWorkItem, GateAgentResult

if TYPE_CHECKING:
    from pokepoke.utils.logging_utils import ItemLogger

logger = logging.getLogger(__name__)

__all__ = ['run_gate_agent']


def run_gate_agent(
    item: BeadsWorkItem,
    cwd: str | None = None,
    work_model: str | None = None,
    handoff_context: str | None = None,
    agent_id: str | None = None,
    agent_iteration: int = 1,
    parent_agent_id: str | None = None,
    item_logger: 'ItemLogger | None' = None,
    session_id: str | None = None,
    is_resume: bool = False,
) -> 'GateAgentResult':
    """Run the Gate Agent to verify a fixed work item."""
    terminal_ui.ui.set_current_agent("Gate Agent")
    logger.info(f"\n{'='*60}\n🕵️ Running Gate Agent on {item.id}\n{'='*60}")
    gate_model = None
    if work_model:
        gate_model = select_gate_model(work_model, item.id)
    # Build prompt: use resume prompt if continuing a timed-out session
    if is_resume and session_id:
        final_prompt = build_gate_resume_prompt(
            item,
            handoff_context=handoff_context,
            previous_output_summary=None,
            default_branch=get_default_branch(),
        )
    else:
        service = PromptService()
        try:
            config = get_config()
            final_prompt = service.load_and_render("gate-agent", {
                "item_id": item.id,
                "title": item.title,
                "description": item.description or "",
                "handoff_context": handoff_context or "",
                "default_branch": get_default_branch(),
                "command_timeout": config.command_timeout,
            })
        except Exception as e:
            return GateAgentResult(
                success=False, reason=f"Failed to render prompt: {e}",
                crashed=True,
            )
    with agent_type_context("gate"):
        if agent_id:
            terminal_ui.ui.push_agent_status(
                agent_id, "Gate Agent", iteration=agent_iteration, status="running",
                parent_agent_id=parent_agent_id, work_item_id=item.id, work_item_title=item.title,
                agent_type="gate",
                agent_prompt=final_prompt,
            )
        result = invoke_copilot(
            item, prompt=final_prompt, deny_write=True, cwd=cwd,
            model=gate_model, item_logger=item_logger,
            session_id=session_id, is_resume=is_resume,
            add_parent_dir=True,
        )

    stats = parse_agent_stats(result.output) if result.output else None
    # Determine gate outcome and record for rejection rate tracking
    def _finish(success: bool, reason: str, crashed: bool,
                is_timeout: bool = False) -> 'GateAgentResult':
        if gate_model and not crashed:
            record_gate_check(gate_model, item.id, success, reason=reason if not success else "")
        return GateAgentResult(
            success=success, reason=reason, stats=stats, crashed=crashed,
            is_timeout=is_timeout,
            session_id=result.session_id,
            last_output_summary=result.last_output_summary,
        )
    if not result.success:
        # Distinguish timeout from generic crash
        is_timeout = bool(
            result.error
            and ("timeout" in result.error.lower()
                 or "inactivity" in result.error.lower())
        )
        return _finish(
            False, f"Gate Agent execution failed: {result.error}",
            crashed=not is_timeout, is_timeout=is_timeout,
        )
    output = result.output or ""
    # Find ALL ```json blocks (case-insensitive) and try each, last-first,
    # since the verdict is expected at the end of the response.
    json_blocks = list(re.finditer(
        r'```[jJ][sS][oO][nN]\s*(\{.*?\})\s*```', output, re.DOTALL,
    ))
    for json_match in reversed(json_blocks):
        try:
            data = json.loads(json_match.group(1))
            status = data.get("status")
            if status == "success":
                message = data.get("message", "Verification successful")
                reason = data.get("reason", "")
                recommendation = data.get("recommendation", "")
                # Build success message with context
                full_message = message
                if reason:
                    full_message = f"[{reason}] {message}"
                if recommendation:
                    full_message += f"\nRecommendation: {recommendation}"
                return _finish(True, full_message, crashed=False)
            elif status is not None:
                reason = data.get("reason", "Verification failed")
                details = data.get("details", "")
                full_reason = f"{reason}\nDetails: {details}"
                return _finish(False, full_reason, crashed=False)
            # No "status" key — skip this block, try the next one
        except json.JSONDecodeError:
            continue
    if "VERIFICATION SUCCESSFUL" in output.upper() or "NEW_WORK_VERIFIED" in output:
        return _finish(True, "Verification successful (text match)", crashed=False)
    return _finish(False, "Gate Agent did not explicitly approve the fix. Check logs.", crashed=False)
