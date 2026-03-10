"""Helper functions for the Copilot SDK integration."""
import asyncio
import logging
import time
from collections.abc import Callable
from typing import Any

from .shutdown import is_shutting_down
from .types import AgentStats, BeadsWorkItem, CopilotResult
from .sdk_event_handler import SessionStats
from . import terminal_ui

logger = logging.getLogger(__name__)


def _fail_result(work_item_id: str, error: str) -> CopilotResult:
    """Create a failed CopilotResult."""
    return CopilotResult(work_item_id=work_item_id, success=False, error=error, attempt_count=1)


def _build_token_usage_callback() -> Callable[[int, int], None]:
    """Create a token-usage callback that pushes live stats to the agent card."""
    def _on_token_usage(input_tokens: int, output_tokens: int) -> None:
        from .desktop_ui import _thread_output
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
    )


def _build_session_config(
    model: str, deny_write: bool,
) -> dict[str, Any]:
    """Build the SDK session configuration dict."""
    config: dict[str, Any] = {"model": model, "streaming": True}
    config["on_permission_request"] = lambda _req, _ctx: {"kind": "approved"}
    if deny_write:
        config["excluded_tools"] = ["write", "edit"]
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


async def _await_completion(
    session: Any, client: Any, done: asyncio.Event,
    max_timeout: float,
    stats: SessionStats | None = None,
    inactivity_timeout: float = 600.0,
) -> str | None:
    """Poll until the session finishes or an abort condition is met.

    Returns ``None`` on normal completion, or a reason string
    (``"shutdown"``, ``"timeout"``, ``"inactivity"``) on abort.
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
        # Detect dead sessions: no SDK events for inactivity_timeout seconds
        if stats is not None and inactivity_timeout > 0:
            since_last_event = time.monotonic() - stats['last_event_time']
            if since_last_event >= inactivity_timeout:
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
