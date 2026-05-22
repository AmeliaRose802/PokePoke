"""Helper functions for the Copilot SDK integration."""
import logging
from collections.abc import Callable, Sequence
from typing import Any

_PERMISSION_RESULT_CLS: type | None = None
try:
    from copilot.types import PermissionRequestResult
    _PERMISSION_RESULT_CLS = PermissionRequestResult
except ImportError:
    _PERMISSION_RESULT_CLS = None

try:
    from copilot import PermissionHandler
    _approve_all: Any = PermissionHandler.approve_all
except (ImportError, AttributeError):
    # SDK v0.1.0+ on Python 3.13: PermissionHandler is a type alias,
    # not a class with approve_all. Build an inline approval handler.
    if _PERMISSION_RESULT_CLS is not None:
        def _approve_all(req: Any, _ctx: Any = None) -> Any:
            assert _PERMISSION_RESULT_CLS is not None
            return _PERMISSION_RESULT_CLS(kind="approved", rules=[])
    else:
        _approve_all = None

from pokepoke.desktop import terminal_ui
from pokepoke.types import AgentStats, BeadsWorkItem, parse_work_agent_outcome
from pokepoke.types_agent import CopilotResult
from pokepoke.utils.command_validator import validate_and_rewrite_powershell_tool_args
from pokepoke.utils.prompt_sanitizer import sanitize_prompt_input, sanitize_short
from pokepoke.utils.shutdown import is_shutting_down

from .sdk_event_handler import SdkSessionStats

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
        from pokepoke.desktop.thread_output_router import _thread_output
        agent_id: str | None = getattr(_thread_output, "agent_id", None)
        if agent_id:
            terminal_ui.ui.push_agent_tokens(agent_id, input_tokens, output_tokens)

    return _on_token_usage

# Keep at most 512 KB of output text in the result object.
# Full output is already written to the item log file on disk.
_MAX_RESULT_OUTPUT_BYTES = 512 * 1024

def _build_copilot_result(
    work_item: BeadsWorkItem,
    output_lines: Sequence[str],
    errors: list[str],
    stats: SdkSessionStats,
    current_model: str,
    total_api_duration: float,
    total_wall_duration: float,
    session_id: str | None = None,
) -> CopilotResult:
    """Assemble the final CopilotResult and print summary statistics."""
    output_text = "".join(output_lines)
    if len(output_text) > _MAX_RESULT_OUTPUT_BYTES:
        output_text = output_text[-_MAX_RESULT_OUTPUT_BYTES:]
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
        work_agent_outcome=parse_work_agent_outcome(output_text),
    )

def _set_tool_args_on_request(req: Any, new_args: Any) -> None:
    if isinstance(req, dict):
        if "args" in req or "arguments" not in req:
            req["args"] = new_args
        else:
            req["arguments"] = new_args
        return

    if hasattr(req, "args"):
        req.args = new_args
        return
    if hasattr(req, "arguments"):
        req.arguments = new_args
        return
    # Unknown request shape: ignore.


def _extract_tool_request(req: Any) -> tuple[str | None, Any, Callable[[Any], None]]:
    """Return (tool_name, tool_args, set_tool_args)."""
    if isinstance(req, dict):
        tool_name = req.get("tool_name") or req.get("tool")
        tool_args = req.get("args") if "args" in req else req.get("arguments")
        full_command = req.get("full_command_text")
    else:
        tool_name = getattr(req, "tool_name", None) or getattr(req, "tool", None)
        tool_args = getattr(req, "args", None) or getattr(req, "arguments", None)
        full_command = getattr(req, "full_command_text", None)

    def set_tool_args(new_args: Any) -> None:
        _set_tool_args_on_request(req, new_args)

    if tool_args is None and full_command:
        if not tool_name:
            tool_name = "powershell"
        tool_args = {"command": full_command}
        set_tool_args(tool_args)

    return tool_name, tool_args, set_tool_args


def _build_permission_handler(
    item_logger: Any | None = None,
    *,
    required_cwd: str | None = None,
) -> Callable[[Any, Any], Any] | None:
    """Build a permission handler that rejects/rewrites unsafe tool commands."""
    if _approve_all is None and _PERMISSION_RESULT_CLS is None:
        return None

    def handler(req: Any, ctx: Any = None) -> Any:
        # CRITICAL: any unhandled exception here causes the SDK to return
        # PermissionRequestResult() (default kind="denied-no-approval-rule-
        # and-could-not-request-from-user") which the CLI reports as
        # "unexpected user permission response".  We MUST always return
        # an approved result except for explicitly denied commands.
        try:
            tool_name, tool_args, set_tool_args = _extract_tool_request(req)
            if tool_name and str(tool_name).lower() == "powershell":
                validation = validate_and_rewrite_powershell_tool_args(
                    tool_args,
                    required_cwd=required_cwd,
                )
                if validation.denied_reason:
                    violation = validation.denied_reason
                    message = f"Denied tool request: {violation}"
                    logger.warning(message)
                    if item_logger:
                        item_logger.log_error(message)
                    if _PERMISSION_RESULT_CLS is not None:
                        return _PERMISSION_RESULT_CLS(
                            kind="denied-by-rules",
                            rules=[],
                            feedback=violation,
                            message=message,
                        )

                if validation.rewritten_tool_args is not None:
                    set_tool_args(validation.rewritten_tool_args)
        except Exception:
            # Never let handler errors bubble up — the SDK catch-all
            # converts them into permission denials.
            logger.debug("Permission handler error (approving anyway)", exc_info=True)

        return _approve_all(req, ctx) if _approve_all is not None else (_PERMISSION_RESULT_CLS(kind="approved") if _PERMISSION_RESULT_CLS is not None else None)

    return handler


def _build_session_config(
    model: str,
    deny_write: bool,
    session_id: str | None = None,
    item_logger: Any | None = None,
    *,
    cwd: str | None = None,
) -> dict[str, Any]:
    """Build the SDK session configuration dict."""
    config: dict[str, Any] = {"model": model, "streaming": True}
    # Use the SDK's built-in approve_all handler directly.  Our custom handler
    # wrapped approve_all with PowerShell command validation, but the overhead
    # was causing intermittent "unexpected user permission response" errors in
    # gate agent sub-processes.  The COPILOT_ALLOW_ALL env var + CLI flags
    # handle the heavy lifting; the SDK handler just needs to say "approved".
    if _approve_all is not None:
        config["on_permission_request"] = _approve_all
    elif _PERMISSION_RESULT_CLS is not None:
        config["on_permission_request"] = lambda req, ctx=None: _PERMISSION_RESULT_CLS(kind="approved")
    if cwd:
        config["working_directory"] = cwd
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
    build_gate_reverify_prompt as build_gate_reverify_prompt,
)
from pokepoke.models.sdk_resume import (
    build_resume_prompt as build_resume_prompt,
)


def build_prompt_from_work_item(
    work_item: BeadsWorkItem,
    template_name: str = "beads-item",
    retry_feedback: list[str] | None = None,
    previous_worker_context: str | None = None,
) -> str:
    """Build a prompt from a work item using the template system.

    Supports label-based template selection: if the work item has labels that
    match entries in the ``prompt_templates`` config, the corresponding template
    will be used instead of the default.

    Args:
        work_item: The work item to build a prompt for.
        template_name: Name of the prompt template to use (default: ``"beads-item"``).
            This can be overridden by label-based template selection.
        retry_feedback: Optional list of feedback strings from previous gate-agent
            rejections or copilot failures.
        previous_worker_context: Pre-formatted context from previous worker
            attempts (fetched from beads comments).
    """
    from pokepoke.config import get_config
    from pokepoke.prompts.prompts import PromptService
    config = get_config()
    service = PromptService()

    # Check for label-based template override
    if work_item.labels and isinstance(config.prompt_templates, dict) and config.prompt_templates:
        for label in work_item.labels:
            if label in config.prompt_templates:
                template_name = config.prompt_templates[label]
                logger.info(f"Using label-specific template '{template_name}' for label '{label}'")
                break

    # Retrieve relevant memories if enabled
    memory_context: str | None = None
    if config.mcp_server.memory_enabled:
        try:
            from pokepoke.models.memory_helpers import retrieve_relevant_memories
            memory_context = retrieve_relevant_memories(work_item)
        except Exception as e:
            logger.warning(f"Failed to retrieve memories: {e}")

    test_data_lines = [
        f"When you need {k.replace('_', ' ').capitalize()}, use: {v}"
        for k, v in config.test_data.items()
    ]
    test_data_section = "\n\n".join(test_data_lines) if test_data_lines else None
    retry_feedback_section: str | None = None
    if retry_feedback:
        bullets = "\n".join(f"- {fb}" for fb in retry_feedback)
        retry_feedback_section = bullets
    variables = {
        "item_id": work_item.id,
        "title": sanitize_short(work_item.title, "title"),
        "description": sanitize_prompt_input(
            work_item.description, field_name="description",
        ),
        "issue_type": sanitize_short(work_item.issue_type, "issue_type"),
        "priority": work_item.priority,
        "labels": sanitize_short(
            ", ".join(work_item.labels) if work_item.labels else None, "labels",
        ),
        "mcp_enabled": config.mcp_server.enabled,
        "memory_context": memory_context,
        "test_data_section": test_data_section,
        "command_timeout": config.command_timeout,
        "retry_feedback": retry_feedback_section,
        "previous_worker_context": previous_worker_context,
    }
    return service.load_and_render(template_name, variables)
