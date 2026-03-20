"""Helper functions for the Copilot SDK integration."""
import asyncio
import logging
import time
from collections.abc import Callable
from typing import Any

try:
    from copilot import PermissionHandler
    _approve_all: Any = PermissionHandler.approve_all
except (ImportError, AttributeError):
    _approve_all = None

from pokepoke.utils.shutdown import is_shutting_down
from pokepoke.types import AgentStats, BeadsWorkItem, CopilotResult
from .sdk_event_handler import SessionStats
from pokepoke.desktop import terminal_ui

logger = logging.getLogger(__name__)

_HB_INTERVAL = 30.0  # Heartbeat interval in seconds


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
    work_item_id: str, timed_out: bool, interrupted: bool, max_timeout: float,
) -> CopilotResult | None:
    """Return a failure result if the session ended abnormally, else None."""
    if timed_out:
        return _fail_result(work_item_id, f"SDK timeout after {max_timeout}s")
    if interrupted:
        error = "Session aborted due to application shutdown" if is_shutting_down() else "Interrupted by user"
        return _fail_result(work_item_id, error)
    return None


def _check_abort_result(
    work_item_id: str,
    inactivity_detected: bool, inactivity_timeout: float,
    tool_timed_out: bool, tool_call_timeout: float,
    process_dead: bool = False,
    last_output_summary: str | None = None,
) -> CopilotResult | None:
    """Return a failure result for inactivity, tool timeout, or process death, else None."""
    if process_dead:
        return _fail_result(
            work_item_id, "Process died: consecutive ping failures or output timeout",
            last_output_summary=last_output_summary,
        )
    if inactivity_detected:
        return _fail_result(work_item_id, f"Session died: no SDK events for {inactivity_timeout:.0f}s")
    if tool_timed_out:
        return _fail_result(
            work_item_id, f"Tool call stuck: exceeded {tool_call_timeout:.0f}s watchdog timeout",
            last_output_summary=last_output_summary,
        )
    return None


async def _check_tool_watchdog(
    session: Any, stats: SessionStats | None, tool_call_timeout: float,
    handler: Any = None,
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
            # Look up tool name and args from event handler
            tool_name = "unknown"
            args_str = ""
            if handler and hasattr(handler, '_pending_tools'):
                tool_info = handler._pending_tools.get(tool_id, {})
                tool_name = tool_info.get('name', 'unknown')
                tool_args = tool_info.get('args', {})
                args_str = str(tool_args)

            timeout_msg = (
                f"Tool timeout: {tool_name}({args_str}) exceeded {tool_call_timeout:.0f}s watchdog timeout "
                f"(elapsed: {elapsed:.0f}s)"
            )

            print(f"\n[SDK] TOOL TIMEOUT: {timeout_msg} - aborting")
            logger.error(
                "Tool call watchdog triggered: tool_id=%s tool=%s args=%s elapsed=%.0fs limit=%.0fs",
                tool_id, tool_name, args_str, elapsed, tool_call_timeout,
            )

            # Log to item log if available
            if handler and hasattr(handler, '_item_logger') and handler._item_logger:
                handler._item_logger.log_error(timeout_msg)

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
    handler: Any = None,
    process_output_timeout: float = 300.0,
    max_ping_failures: int = 3,
) -> str | None:
    """Poll until the session finishes or an abort condition is met.

    Returns ``None`` on normal completion, or a reason string
    (``"shutdown"``, ``"timeout"``, ``"inactivity"``, ``"tool_timeout"``,
    ``"process_dead"``) on abort.
    """
    from pokepoke.desktop.desktop_ui import _thread_output
    deadline = asyncio.get_event_loop().time() + max_timeout
    last_hb = time.monotonic()
    last_hb_events = stats.get('event_count', 0) if stats else 0
    consecutive_ping_failures = 0

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

        now = time.monotonic()

        # Periodic heartbeat with ping to distinguish live-but-silent from dead
        if stats is not None and (now - last_hb) >= _HB_INTERVAL:
            evts = stats['event_count'] - last_hb_events
            gap = now - stats['last_event_time']
            remaining_wall = deadline - asyncio.get_event_loop().time()
            ping_ok = False
            try:
                await client.ping()
                ping_ok = True
                consecutive_ping_failures = 0
            except Exception:
                consecutive_ping_failures += 1
            logger.info(
                "SDK heartbeat: ping=%s, event_gap=%.0fs, pending=%d, "
                "events_delta=%d (total=%d), turns=%d, remaining=%.0fs, "
                "ping_failures=%d/%d",
                "ok" if ping_ok else "FAIL", gap,
                stats.get('pending_tool_calls', 0), evts, stats['event_count'],
                stats.get('turn_count', 0), remaining_wall,
                consecutive_ping_failures, max_ping_failures,
            )
            last_hb = now
            last_hb_events = stats['event_count']

            # Process-level liveness checks
            should_abort, reason = False, ""
            if consecutive_ping_failures >= max_ping_failures:
                should_abort = True
                reason = (f"PROCESS DEAD: {consecutive_ping_failures} consecutive "
                          f"ping failures (threshold: {max_ping_failures})")
            elif (process_output_timeout > 0 and gap >= process_output_timeout
                  and not ping_ok and stats.get('pending_tool_calls', 0) == 0):
                should_abort = True
                reason = (f"PROCESS UNRESPONSIVE: No events for {gap:.0f}s "
                          f"(threshold: {process_output_timeout:.0f}s) and ping failed")
            if should_abort:
                print(f"\n[SDK] {reason} - aborting")
                logger.error("SDK process liveness: %s (event_count=%d)", reason,
                             stats.get('event_count', 0))
                try:
                    await session.abort()
                except Exception as e:
                    logger.debug("Failed to abort session on process death: %s", e)
                return "process_dead"

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
        #
        # Child agent consideration: If this agent has active child agents
        # (e.g., spawned via task tool), check their activity timestamps
        # as well. A parent agent may appear idle while child agents are
        # actively working.
        if stats is not None and inactivity_timeout > 0:
            has_pending_tools = stats.get('pending_tool_calls', 0) > 0
            since_last_event = time.monotonic() - stats['last_event_time']
            since_last_tool = time.monotonic() - stats.get('last_tool_activity_time', 0)
            tool_cooldown_grace = 60.0  # Seconds to wait after tool activity before enforcing inactivity timeout
            is_in_grace_period = since_last_tool < tool_cooldown_grace

            # Check if this agent has active children
            has_active_children = False
            child_activity_time: float | None = None
            try:
                # Access agent_id from thread-local storage
                agent_id: str | None = getattr(_thread_output, "agent_id", None)
                if agent_id:
                    has_active_children = terminal_ui.ui.has_active_child_agents(agent_id)
                    if has_active_children:
                        child_activity_time = terminal_ui.ui.get_child_agent_activity_time(agent_id)
            except Exception as e:
                # Swallow errors from child checking - don't break timeout logic
                logger.debug("Failed to check child agent activity: %s", e)

            # Consider child activity when determining if session is truly idle
            effective_last_activity = stats['last_event_time']
            if has_active_children and child_activity_time:
                # Use whichever is more recent: parent or child activity
                effective_last_activity = max(
                    stats['last_event_time'],
                    child_activity_time
                )
                since_last_event = time.monotonic() - effective_last_activity

            if since_last_event >= inactivity_timeout and not has_pending_tools and not is_in_grace_period and not has_active_children:
                debug_info = f"pending_tools={has_pending_tools}, grace={is_in_grace_period}, active_children={has_active_children}"
                print(
                    f"\n[SDK] SESSION DEAD: No events received for {since_last_event:.0f}s "
                    f"(threshold: {inactivity_timeout:.0f}s) — aborting ({debug_info})"
                )
                logger.error(
                    "SDK session inactivity detected: no events for %.0fs "
                    "(event_count=%d, last_tool_activity=%.0fs ago, has_children=%s)",
                    since_last_event,
                    stats.get('event_count', 0),
                    time.monotonic() - stats.get('last_tool_activity_time', 0),
                    has_active_children,
                )
                try:
                    await session.abort()
                except Exception as e:
                    logger.debug("Failed to abort dead session: %s", e)
                return "inactivity"
        # Per-tool-call watchdog
        result = await _check_tool_watchdog(session, stats, tool_call_timeout, handler)
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


# Re-export resume helpers for backward compatibility
from pokepoke.models.sdk_resume import (  # noqa: E402
    _summarize_output as _summarize_output,
    build_gate_resume_prompt as build_gate_resume_prompt,
    build_resume_prompt as build_resume_prompt,
)
