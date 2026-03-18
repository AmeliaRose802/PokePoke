"""Helper functions for the Copilot SDK integration."""
import asyncio
import logging
import time
from collections.abc import Callable
from typing import Any

try:
    from copilot import PermissionHandler
    _approve_all: Any = PermissionHandler.approve_all
except ImportError:
    _approve_all = None

from pokepoke.utils.shutdown import is_shutting_down
from pokepoke.types import AgentStats, BeadsWorkItem, CopilotResult
from .sdk_event_handler import SessionStats
from pokepoke.desktop import terminal_ui

logger = logging.getLogger(__name__)


def _fail_result(
    work_item_id: str,
    error: str,
    session_id: str | None = None,
    last_output_summary: str | None = None,
) -> CopilotResult:
    """Create a failed CopilotResult."""
    return CopilotResult(
        work_item_id=work_item_id, success=False, error=error, attempt_count=1,
        session_id=session_id, last_output_summary=last_output_summary,
    )


def _build_token_usage_callback() -> Callable[[int, int], None]:
    """Create a token-usage callback that pushes live stats to the agent card."""
    def _on_token_usage(input_tokens: int, output_tokens: int) -> None:
        from pokepoke.desktop.desktop_ui import _thread_output
        agent_id: str | None = getattr(_thread_output, "agent_id", None)
        if agent_id:
            terminal_ui.ui.push_agent_tokens(agent_id, input_tokens, output_tokens)

    return _on_token_usage


def _build_copilot_result(
    work_item: BeadsWorkItem,
    output_lines: list[str],
    errors: list[str],
    stats: SessionStats,
    current_model: str,
    total_api_duration: float,
    total_wall_duration: float,
    session_id: str | None = None,
) -> CopilotResult:
    """Assemble the final CopilotResult and print summary statistics."""
    output_text = "".join(output_lines)
    success = len(errors) == 0
    print(f"\n{'='*60}\n[SDK] Result: {'SUCCESS' if success else 'FAILURE'}\n{'='*60}")
    if stats["turn_count"] > 0 or stats["total_input_tokens"] > 0:
        print(
            f"\n📊 Stats: {stats['turn_count']} turns, "
            f"{stats['total_input_tokens']:,}+{stats['total_output_tokens']:,} tokens"
        )
    agent_stats = AgentStats(
        input_tokens=stats["total_input_tokens"],
        output_tokens=stats["total_output_tokens"],
        premium_requests=stats["turn_count"],
        tool_calls=stats["total_tool_calls"],
        api_duration=total_api_duration,
        wall_duration=total_wall_duration,
    )
    return CopilotResult(
        work_item_id=work_item.id,
        success=success,
        output=output_text,
        error="; ".join(errors) if errors else None,
        attempt_count=1,
        stats=agent_stats,
        model=current_model,
        session_id=session_id,
    )


def _build_session_config(
    model: str, deny_write: bool, session_id: str | None = None,
) -> dict[str, Any]:
    """Build the SDK session configuration dict."""
    config: dict[str, Any] = {"model": model, "streaming": True}
    if _approve_all is not None:
        config["on_permission_request"] = _approve_all
    if deny_write:
        config["excluded_tools"] = ["write", "edit"]
    if session_id:
        config["session_id"] = session_id
    return config


def _check_early_exit(
    work_item_id: str,
    timed_out: bool,
    interrupted: bool,
    max_timeout: float,
) -> CopilotResult | None:
    """Return a failure result if the session ended abnormally, else None."""
    if timed_out:
        return _fail_result(work_item_id, f"SDK timeout after {max_timeout}s")
    if interrupted:
        error = "Session aborted due to application shutdown" if is_shutting_down() else "Interrupted by user"
        return _fail_result(work_item_id, error)
    return None


def _check_inactivity(
    work_item_id: str,
    inactivity_detected: bool,
    inactivity_timeout: float,
) -> CopilotResult | None:
    """Return a failure result if session died from inactivity, else None."""
    if inactivity_detected:
        return _fail_result(
            work_item_id,
            f"Session died: no SDK events for {inactivity_timeout:.0f}s",
        )
    return None


def _check_tool_timeout(
    work_item_id: str,
    tool_timed_out: bool,
    tool_call_timeout: float,
    last_output_summary: str | None = None,
) -> CopilotResult | None:
    """Return a failure result if a tool call exceeded the watchdog, else None."""
    if tool_timed_out:
        return _fail_result(
            work_item_id,
            f"Tool call stuck: exceeded {tool_call_timeout:.0f}s watchdog timeout",
            last_output_summary=last_output_summary,
        )
    return None


async def _check_tool_watchdog(
    session: Any, stats: SessionStats | None, tool_call_timeout: float,
) -> str | None:
    """Check if any tool call exceeds the watchdog timeout. Returns 'tool_timeout' or None."""
    if stats is None or tool_call_timeout <= 0:
        return None
    tool_times = stats.get('tool_start_times', {})
    if not tool_times:
        return None
    now = time.monotonic()
    for tool_id, start_time in tool_times.items():
        elapsed = now - start_time
        if elapsed >= tool_call_timeout:
            print(
                f"\n[SDK] TOOL TIMEOUT: tool call {tool_id} "
                f"running for {elapsed:.0f}s "
                f"(limit: {tool_call_timeout:.0f}s) \u2014 aborting"
            )
            logger.error(
                "Tool call watchdog triggered: tool_id=%s elapsed=%.0fs limit=%.0fs",
                tool_id, elapsed, tool_call_timeout,
            )
            try:
                await session.abort()
            except Exception as e:
                logger.debug("Failed to abort session on tool timeout: %s", e)
            return "tool_timeout"
    return None


async def _await_completion(
    session: Any, client: Any, done: asyncio.Event,
    max_timeout: float,
    stats: SessionStats | None = None,
    inactivity_timeout: float = 600.0,
    tool_call_timeout: float = 600.0,
) -> str | None:
    """Poll until the session finishes or an abort condition is met.

    Returns ``None`` on normal completion, or a reason string
    (``"shutdown"``, ``"timeout"``, ``"inactivity"``, ``"tool_timeout"``)
    on abort.
    """
    deadline = asyncio.get_event_loop().time() + max_timeout
    while not done.is_set():
        if is_shutting_down():
            print("\n[SDK] Shutdown requested - aborting session...")
            try:
                await session.abort()
            except OSError as e:
                logger.debug("Failed to abort session on shutdown: %s", e)
            return "shutdown"
        try:
            client_state = client.get_state()
            if client_state in ("disconnected", "error"):
                print(f"\n[SDK] Client state is '{client_state}' - process has exited, forcing completion")
                done.set()
                break
        except Exception:
            pass
        # Detect dead sessions: no SDK events for inactivity_timeout seconds.
        # Skip when tools are actively running — the SDK doesn't emit
        # streaming events while a subprocess (e.g. git commit with
        # pre-commit hooks) executes, so silence is expected.  The
        # per-item hard deadline (max_timeout) protects against truly
        # stuck sessions.
        #
        # Grace period after tool completion: If a tool just finished
        # (last_tool_activity_time is recent), give the session 60s to emit
        # the next SDK event before declaring it dead. This prevents killing
        # sessions immediately after long tool calls complete.
        if stats is not None and inactivity_timeout > 0:
            has_pending_tools = stats.get('pending_tool_calls', 0) > 0
            since_last_event = time.monotonic() - stats['last_event_time']
            since_last_tool = time.monotonic() - stats.get('last_tool_activity_time', 0)
            tool_cooldown_grace = 60.0  # Seconds to wait after tool activity before enforcing inactivity timeout
            is_in_grace_period = since_last_tool < tool_cooldown_grace
            if since_last_event >= inactivity_timeout and not has_pending_tools and not is_in_grace_period:
                print(
                    f"\n[SDK] SESSION DEAD: No events received for {since_last_event:.0f}s "
                    f"(threshold: {inactivity_timeout:.0f}s) — aborting"
                )
                logger.error(
                    "SDK session inactivity detected: no events for %.0fs "
                    "(event_count=%d, last_tool_activity=%.0fs ago)",
                    since_last_event,
                    stats.get('event_count', 0),
                    time.monotonic() - stats.get('last_tool_activity_time', 0),
                )
                try:
                    await session.abort()
                except Exception as e:
                    logger.debug("Failed to abort dead session: %s", e)
                return "inactivity"
        # Per-tool-call watchdog
        result = await _check_tool_watchdog(session, stats, tool_call_timeout)
        if result is not None:
            return result
        remaining = deadline - asyncio.get_event_loop().time()
        if remaining <= 0:
            print(f"\n[SDK] TIMEOUT after {max_timeout}s")
            try:
                await session.abort()
            except OSError as e:
                logger.debug("Failed to abort session on timeout: %s", e)
            return "timeout"
        try:
            await asyncio.wait_for(done.wait(), timeout=min(1.0, remaining))
        except TimeoutError:
            continue
    return None


# ── Session resume helpers ───────────────────────────────────────────────────

# Maximum characters to include in an output summary for resume context
_MAX_OUTPUT_SUMMARY_LEN = 2000


def _summarize_output(
    output_lines: list[str], max_length: int = _MAX_OUTPUT_SUMMARY_LEN,
) -> str | None:
    """Extract a truncated summary from agent output lines.

    Keeps the most recent output (tail), which represents the agent's
    latest progress and is most useful for resume context.

    Returns ``None`` if there is no meaningful output.
    """
    text = "".join(output_lines).strip()
    if not text:
        return None
    if len(text) <= max_length:
        return text
    return "...(earlier output truncated)...\n" + text[-max_length:]



def build_gate_resume_prompt(
    work_item: BeadsWorkItem,
    handoff_context: str | None = None,
    previous_output_summary: str | None = None,
    default_branch: str = "master",
) -> str:
    """Build a prompt for resuming a timed-out gate agent session."""
    lines = [
        f"## Gate Agent Session Resume \u2014 {work_item.id}: {work_item.title}",
        "",
        "Your previous **gate verification session timed out** before",
        "reaching a verdict.  You are being resumed in the same SDK session",
        "so your earlier tool results and reasoning should still be available.",
        "",
        "**Continue your verification from where you left off.**",
        "",
        f"**Item:** {work_item.id} \u2014 {work_item.title}",
        f"**Type:** {work_item.issue_type} | **Priority:** {work_item.priority}",
    ]
    if work_item.description:
        lines.extend(["", "**Description:**", work_item.description])
    if handoff_context:
        lines.extend(["", "### Handoff Context", "", handoff_context])
    if previous_output_summary:
        lines.extend(["", "### Previous Progress", "", "Here is the tail of your previous gate session output:", "", "```", previous_output_summary, "```"])
    lines.extend([
        "", "### Your Task", "",
        "You are the **Gate Agent** \u2014 a read-only verification agent.",
        f"Review the changes on this branch compared to `{default_branch}`.",
        "Run tests, check code quality, and verify the implementation.",
        "", "Respond with a JSON verdict:",
        '```json', '{{"status": "success", "message": "...", "reason": "..."}}', '```',
        "or", '```json', '{{"status": "failure", "reason": "...", "details": "..."}}', '```',
    ])
    return "\n".join(lines)


def build_resume_prompt(
    work_item: BeadsWorkItem,
    previous_output_summary: str | None = None,
    retry_feedback: list[str] | None = None,
) -> str:
    """Build a prompt for resuming a timed-out session.

    The prompt is shorter than a full ``beads-item`` prompt since the SDK
    may have restored the conversation history.  It includes enough
    context for the agent to orient itself if the session did *not*
    actually resume.
    """
    lines = [
        f"## Session Resume — {work_item.id}: {work_item.title}",
        "",
        "Your previous session **timed out** before completing the task.",
        "You are being resumed in the same SDK session so your earlier",
        "tool results, file reads, and reasoning should still be available.",
        "",
        "**Continue from where you left off and complete the task.**",
        "",
        f"**Item:** {work_item.id} — {work_item.title}",
        f"**Type:** {work_item.issue_type} | **Priority:** {work_item.priority}",
    ]
    if work_item.description:
        lines.extend(["", "**Description:**", work_item.description])
    if previous_output_summary:
        lines.extend([
            "",
            "### Previous Progress",
            "",
            "Here is the tail of your previous session output for context:",
            "",
            "```",
            previous_output_summary,
            "```",
        ])
    if retry_feedback:
        lines.extend(["", "### Feedback from Previous Attempts", ""])
        for fb in retry_feedback:
            lines.append(f"- {fb}")

    lines.extend([
        "",
        "**Success Criteria:**",
        "- Provided item is fully implemented",
        "- All pre-commit validation passes successfully",
        "- All changes are committed and the worktree has been merged",
    ])
    return "\n".join(lines)
