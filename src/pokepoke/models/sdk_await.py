"""Await-completion and tool-watchdog helpers for the Copilot SDK integration."""
import asyncio
import logging
import time
from typing import Any

from pokepoke.desktop import terminal_ui
from pokepoke.utils.process_utils import log_process_tree_snapshot as _log_process_tree_snapshot
from pokepoke.utils.shutdown import is_shutting_down

from .sdk_event_handler import SessionStats

logger = logging.getLogger(__name__)

_HB_INTERVAL = 30.0  # Heartbeat interval in seconds


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

            logger.info(f"\n[SDK] TOOL TIMEOUT: {timeout_msg} - aborting")
            logger.error(
                "Tool call watchdog triggered: tool_id=%s tool=%s args=%s elapsed=%.0fs limit=%.0fs",
                tool_id, tool_name, args_str, elapsed, tool_call_timeout,
            )

            _log_process_tree_snapshot(tool_name, args_str, elapsed, handler)

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
    last_event_gap_log = time.monotonic()

    while not done.is_set():
        if is_shutting_down():
            logger.info("\n[SDK] Shutdown requested - aborting session...")
            try:
                await session.abort()
            except OSError as e:
                logger.debug("Failed to abort session on shutdown: %s", e)
            return "shutdown"
        try:
            client_state = client.get_state()
            if client_state in ("disconnected", "error"):
                logger.info(f"\n[SDK] Client state is '{client_state}' - process has exited, forcing completion")
                done.set()
                break
        except Exception:
            logger.debug("Failed to check client state during heartbeat", exc_info=True)

        now = time.monotonic()

        # Log significant event gaps (>60s) for diagnostics
        if stats is not None and (now - last_event_gap_log) >= 30.0:
            gap = now - stats['last_event_time']
            if gap >= 60.0:
                pending = stats.get('pending_tool_calls', 0)
                logger.info(
                    "SDK_EVENT_GAP: %.0fs since last event, pending_tools=%d, "
                    "event_count=%d, turn_count=%d",
                    gap, pending, stats.get('event_count', 0),
                    stats.get('turn_count', 0),
                )
            last_event_gap_log = now

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
            except Exception as exc:
                logger.debug("SDK ping failed: %s: %s", type(exc).__name__, exc)
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
                has_done_work = stats.get('turn_count', 0) > 0
                no_pending = stats.get('pending_tool_calls', 0) == 0

                process_exited_ok = False
                try:
                    proc = getattr(client, '_process', None)
                    if proc is not None:
                        proc.poll()
                        if proc.returncode is not None:
                            process_exited_ok = proc.returncode == 0
                            logger.info(
                                "SDK process exited with code %d during ping failure evaluation",
                                proc.returncode,
                            )
                except Exception:
                    logger.debug("Failed to check process exit code", exc_info=True)

                if has_done_work and no_pending and process_exited_ok:
                    logger.warning(
                        "Pings failing but session completed (turns=%d, pending=%d, "
                        "process_exited_ok=%s) - treating as normal completion",
                        stats.get('turn_count', 0),
                        stats.get('pending_tool_calls', 0),
                        process_exited_ok,
                    )
                    done.set()
                    break
                should_abort = True
                reason = (f"PROCESS DEAD: {consecutive_ping_failures} consecutive "
                          f"ping failures (threshold: {max_ping_failures})")
            elif (process_output_timeout > 0 and gap >= process_output_timeout
                  and not ping_ok and stats.get('pending_tool_calls', 0) == 0):
                should_abort = True
                reason = (f"PROCESS UNRESPONSIVE: No events for {gap:.0f}s "
                          f"(threshold: {process_output_timeout:.0f}s) and ping failed")
            if should_abort:
                logger.info(f"\n[SDK] {reason} - aborting")
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
            tool_cooldown_grace = 60.0
            is_in_grace_period = since_last_tool < tool_cooldown_grace

            has_active_children = False
            child_activity_time: float | None = None
            try:
                agent_id: str | None = getattr(_thread_output, "agent_id", None)
                if agent_id:
                    has_active_children = terminal_ui.ui.has_active_child_agents(agent_id)
                    if has_active_children:
                        child_activity_time = terminal_ui.ui.get_child_agent_activity_time(agent_id)
            except Exception as e:
                logger.debug("Failed to check child agent activity: %s", e)

            effective_last_activity = stats['last_event_time']
            if has_active_children and child_activity_time:
                effective_last_activity = max(
                    stats['last_event_time'],
                    child_activity_time
                )
                since_last_event = time.monotonic() - effective_last_activity

            if since_last_event >= inactivity_timeout and not has_pending_tools and not is_in_grace_period and not has_active_children:
                debug_info = f"pending_tools={has_pending_tools}, grace={is_in_grace_period}, active_children={has_active_children}"
                logger.debug(
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
            logger.info(f"\n[SDK] TIMEOUT after {max_timeout}s")
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
