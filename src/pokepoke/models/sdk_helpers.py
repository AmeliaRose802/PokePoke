"""Helper functions for the Copilot SDK integration."""
import logging
from collections.abc import Callable
from typing import Any

try:
    from copilot import PermissionHandler
    _approve_all: Any = PermissionHandler.approve_all
except (ImportError, AttributeError):
    # SDK v0.1.0+ on Python 3.13: PermissionHandler is a type alias,
    # not a class with approve_all. Build an inline approval handler.
    try:
        from copilot.types import PermissionRequestResult
        def _approve_all(req: Any, _ctx: Any = None) -> Any:
            return PermissionRequestResult(kind="approved", rules=[])
    except ImportError:
        _approve_all = None

from pokepoke.desktop import terminal_ui
from pokepoke.types import AgentStats, BeadsWorkItem, CopilotResult
from pokepoke.utils.shutdown import is_shutting_down

from .sdk_event_handler import SessionStats

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
    logger.error(f"\n{'='*60}\n[SDK] Result: {'SUCCESS' if success else 'FAILURE'}\n{'='*60}")
    if stats["turn_count"] > 0 or stats["total_input_tokens"] > 0:
        logger.info(
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


# Re-export await/watchdog helpers (extracted to sdk_watchdog.py via sdk_await.py)
from pokepoke.models.sdk_await import (
    SDKWatchdog as SDKWatchdog,
)
from pokepoke.models.sdk_await import (
    _await_completion as _await_completion,
)
from pokepoke.models.sdk_await import (
    _check_tool_watchdog as _check_tool_watchdog,
)

# Re-export resume helpers for backward compatibility
from pokepoke.models.sdk_resume import (
    _summarize_output as _summarize_output,
)
from pokepoke.models.sdk_resume import (
    build_gate_resume_prompt as build_gate_resume_prompt,
)
from pokepoke.models.sdk_resume import (
    build_resume_prompt as build_resume_prompt,
)
