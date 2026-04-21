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
from pokepoke.types import BeadsWorkItem
from pokepoke.types_agent import GateAgentResult
from pokepoke.utils.output_sanitizer import contains_process_monitor_noise, strip_process_monitor_lines

if TYPE_CHECKING:
    from pokepoke.utils.logging_utils import ItemLogger

logger = logging.getLogger(__name__)

__all__ = ['run_gate_agent']


def _parse_verdict(output: str) -> tuple[bool, str, bool]:
    """Parse the gate agent verdict from *output*.

    Returns ``(success, reason, crashed)``.

    The function tries three extraction strategies in order:
    1. Fenced JSON blocks (``\u0060\u0060\u0060json ... \u0060\u0060\u0060``)
    2. Unfenced raw JSON objects containing a ``"status"`` key
    3. Text-match keywords (``VERIFICATION SUCCESSFUL`` / ``NEW_WORK_VERIFIED``)

    When none succeed and ``[ProcessMonitor]`` noise is detected in the
    output, the verdict is classified as a crash (infrastructure failure)
    rather than a genuine code rejection, preventing false rejection
    cascades.
    """
    # ── Strategy 1: fenced JSON blocks ──
    json_blocks = list(re.finditer(
        r'```[jJ][sS][oO][nN]\s*(\{.*?\})\s*```', output, re.DOTALL,
    ))
    had_json_blocks = bool(json_blocks)
    for json_match in reversed(json_blocks):
        result = _try_parse_verdict_json(json_match.group(1))
        if result is not None:
            return result

    # ── Strategy 2: unfenced JSON objects ──
    # ProcessMonitor corruption can break the code-fence markers while
    # leaving the JSON payload intact.  Look for raw JSON objects that
    # contain a "status" field.
    unfenced_blocks = list(re.finditer(
        r'\{[^{}]*"status"\s*:[^{}]*\}', output, re.DOTALL,
    ))
    for json_match in reversed(unfenced_blocks):
        result = _try_parse_verdict_json(json_match.group(0))
        if result is not None:
            return result

    # ── Strategy 3: text-match keywords ──
    if "VERIFICATION SUCCESSFUL" in output.upper() or "NEW_WORK_VERIFIED" in output:
        return True, "Verification successful (text match)", False

    # ── No verdict found — classify the failure ──
    # If JSON blocks were present but ALL failed to parse, this is an
    # infrastructure issue (e.g. output corruption), not a genuine code
    # rejection.  Mark as crashed so the orchestrator retries instead of
    # counting it against the gate rejection cap.
    if had_json_blocks:
        logger.warning("Gate Agent output contained JSON blocks but none parsed successfully — treating as crash")
        return False, "Gate Agent verdict could not be parsed (output corrupted). Check logs.", True

    # If ProcessMonitor noise is present in the output, corruption likely
    # broke the code-fence markers entirely.  Treat as crash to avoid
    # false rejection cascades (the work agent would be restarted with
    # bogus "gate feedback" otherwise).
    if contains_process_monitor_noise(output):
        logger.warning(
            "Gate Agent output contained ProcessMonitor noise but no parseable verdict — treating as crash"
        )
        return False, "Gate Agent verdict could not be parsed (ProcessMonitor corruption). Check logs.", True

    return False, "Gate Agent did not explicitly approve the fix. Check logs.", False


def _try_parse_verdict_json(raw: str) -> tuple[bool, str, bool] | None:
    """Try to parse a single JSON fragment as a gate verdict.

    Returns ``(success, reason, crashed)`` on success, or ``None`` if
    the fragment is not a valid gate verdict.
    """
    cleaned = strip_process_monitor_lines(raw)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        return None

    status = data.get("status")
    # Normalize common fields
    reason_field = data.get("reason", "Verification failed")
    details = data.get("details", "")

    if status == "success":
        message = data.get("message", "Verification successful")
        recommendation = data.get("recommendation", "")
        full_message = message
        if reason_field:
            full_message = f"[{reason_field}] {message}"
        if recommendation:
            full_message += f"\nRecommendation: {recommendation}"
        return True, full_message, False

    # Special-case: too_large verdict (explicit signal to decompose)
    if status == "too_large":
        suggested = data.get("suggested_split") or data.get("suggested_splits")
        parts: list[str] = []
        if reason_field:
            parts.append(reason_field)
        if details:
            parts.append(f"Details: {details}")
        if suggested:
            if isinstance(suggested, list):
                parts.append("Suggested split: " + "; ".join(map(str, suggested)))
            else:
                parts.append("Suggested split: " + str(suggested))
        return False, "too_large: " + " \n".join(parts), False

    if status is not None:
        # Preserve prior behavior for generic failures: return the reason and details
        return False, f"{reason_field}\nDetails: {details}", False
    return None


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
    success, reason, crashed = _parse_verdict(output)
    return _finish(success, reason, crashed=crashed)
