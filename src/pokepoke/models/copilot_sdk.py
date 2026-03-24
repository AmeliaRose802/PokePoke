"""GitHub Copilot SDK integration."""
import asyncio
import logging
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

try:
    from copilot import CopilotClient
    _HAS_COPILOT = True
except ImportError:
    _HAS_COPILOT = False

from pokepoke.config import DEFAULT_MODEL, FALLBACK_MODEL, get_config
from pokepoke.desktop import terminal_ui
from pokepoke.prompts.prompts import PromptService
from pokepoke.types import BeadsWorkItem, CopilotResult, RetryConfig
from pokepoke.utils.constants import DEFAULT_AGENT_TIMEOUT
from pokepoke.utils.process_utils import shutdown_copilot_client
from pokepoke.utils.shutdown import is_shutting_down

from .sdk_event_handler import RateLimitError, create_event_handler
from .sdk_event_handler import SessionStats as _SDKSessionStats
from .sdk_helpers import (
    _await_completion,
    _build_copilot_result,
    _build_session_config,
    _build_token_usage_callback,
    _check_abort_result,
    _check_early_exit,
    _fail_result,
    _summarize_output,
    build_resume_prompt,
)

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from pokepoke.utils.logging_utils import ItemLogger

def build_prompt_from_work_item(
    work_item: BeadsWorkItem,
    template_name: str = "beads-item",
    retry_feedback: list[str] | None = None,
) -> str:
    """Build a prompt from a work item using the template system.

    Args:
        work_item: The work item to build a prompt for.
        template_name: Name of the prompt template to use (default: ``"beads-item"``).
            Assignment rules may specify a custom template via ``prompt_template``.
        retry_feedback: Optional list of feedback strings from previous gate-agent
            rejections or copilot failures.  Rendered in a dedicated template section
            so that the original item description stays unmodified.
    """
    config = get_config()
    service = PromptService()
    # Build test data section from config
    test_data_lines = [
        f"When you need {k.replace('_', ' ').capitalize()}, use: {v}"
        for k, v in config.test_data.items()
    ]
    test_data_section = "\n\n".join(test_data_lines) if test_data_lines else None
    # Format retry feedback as a bullet list for the template
    retry_feedback_section: str | None = None
    if retry_feedback:
        bullets = "\n".join(f"- {fb}" for fb in retry_feedback)
        retry_feedback_section = bullets
    variables = {
        "item_id": work_item.id,
        "title": work_item.title,
        "description": work_item.description or "",
        "issue_type": work_item.issue_type,
        "priority": work_item.priority,
        "labels": ", ".join(work_item.labels) if work_item.labels else None,
        "mcp_enabled": config.mcp_server.enabled,
        "test_data_section": test_data_section,
        "command_timeout": config.command_timeout,
        "retry_feedback": retry_feedback_section,
    }

    return service.load_and_render(template_name, variables)

def _build_worker_env(cwd: str | None) -> dict[str, str]:
    """Build environment variables for a worker session."""
    env = {**os.environ, "PYTHONIOENCODING": "utf-8:replace"}
    if cwd:
        env["GIT_CEILING_DIRECTORIES"] = str(Path(cwd).parent)
    return env

def _build_add_dir_args(cwd: str) -> list[str]:
    """Return ``--add-dir`` CLI args so worktree agents can also access the main repo."""
    cwd_path = Path(cwd).resolve()
    # Pattern: <repo_root>/worktrees/task-<id>
    if cwd_path.parent.name == "worktrees":
        repo_root = str(cwd_path.parent.parent)
        return ["--add-dir", repo_root]
    return []

def _create_sdk_client(cwd: str | None) -> Any:
    """Create and configure a CopilotClient instance."""
    proj_config = get_config()
    cli_path = proj_config.ai_backend.copilot_cli_path
    # Resolve relative CLI names (e.g. "copilot.cmd") to absolute paths via PATH
    # so the SDK's os.path.exists() check succeeds.
    resolved = shutil.which(cli_path)
    if resolved:
        cli_path = resolved
    client_opts: dict[str, Any] = {
        "cli_path": cli_path,
        "log_level": "info",
        "env": _build_worker_env(cwd),
    }
    if cwd:
        client_opts["cwd"] = cwd
        add_dir_args = _build_add_dir_args(cwd)
        if add_dir_args:
            client_opts["cli_args"] = add_dir_args
    if not _HAS_COPILOT:
        raise ImportError(
            "The 'copilot' SDK package is required but not installed. "
            "Install it or use a different AI backend."
        )
    return CopilotClient(client_opts)  # type: ignore[arg-type]

@dataclass
class _AttemptResult:
    """Result of a single SDK session attempt."""
    abort_reason: str | None = None
    interrupted: bool = False
    elapsed: float = 0.0

async def _send_and_wait(
    session: Any, client: Any, handler: Any,
    final_prompt: str, done: asyncio.Event,
    max_timeout: float, stats: Any, inactivity_timeout: float, **kw: Any,
) -> str | None:
    """Send the prompt and wait for completion. Returns abort reason or None.

    Raises ``RateLimitError`` if the handler detected a rate limit.
    Raises ``KeyboardInterrupt`` if the user interrupts.
    """
    logger.info("[SDK] Sending message...\n")
    with terminal_ui.ui.agent_output():
        await session.send({"prompt": final_prompt})
        abort_reason = await _await_completion(
            session, client, done, max_timeout,
            stats=stats, inactivity_timeout=inactivity_timeout,
            handler=handler, **kw,
        )
        if handler.rate_limit_detected:
            raise RateLimitError()
        return abort_reason

async def _run_attempt(
    session: Any, client: Any, handler: Any,
    final_prompt: str, done: asyncio.Event,
    max_timeout: float, stats: Any, inactivity_timeout: float, **kw: Any,
) -> _AttemptResult:
    """Execute one send-and-wait attempt, handling interrupts and timing."""
    result = _AttemptResult()
    attempt_start = asyncio.get_event_loop().time()
    try:
        abort_reason = await _send_and_wait(
            session, client, handler, final_prompt, done,
            max_timeout, stats, inactivity_timeout, **kw,
        )
        result.abort_reason = abort_reason
        result.interrupted = abort_reason in (
            "shutdown", "timeout", "inactivity", "tool_timeout", "process_dead",
        )
    except KeyboardInterrupt:
        logger.info("\n\n[SDK] ⚡️  Interrupted by user (Ctrl+C)")
        try:
            await session.abort()
        except Exception as e:
            logger.debug(f"Failed to abort session on interrupt: {e}")
        result.interrupted = True
    finally:
        result.elapsed = asyncio.get_event_loop().time() - attempt_start
    return result


def _resolve_prompt(
    work_item: BeadsWorkItem,
    prompt: str | None,
    template_name: str | None,
    is_resume: bool,
    session_id: str | None,
) -> str:
    """Choose the right prompt: explicit > resume > full template."""
    if prompt:
        return prompt
    if is_resume and session_id:
        return build_resume_prompt(work_item)
    return build_prompt_from_work_item(work_item, template_name or "beads-item")


async def invoke_copilot_sdk(
    work_item: BeadsWorkItem,
    prompt: str | None = None,
    retry_config: RetryConfig | None = None,
    timeout: float | None = None,
    deny_write: bool = False,
    item_logger: 'ItemLogger | None' = None,
    idle_timeout: float | None = None,
    model: str | None = None,
    cwd: str | None = None,
    template_name: str | None = None,
    session_id: str | None = None,
    is_resume: bool = False,
) -> CopilotResult:
    """Invoke GitHub Copilot using the SDK. Falls back to Sonnet on rate limit.

    Args:
        session_id: Optional SDK session ID for resuming a timed-out session.
            When provided, the SDK will attempt to restore the previous
            conversation history.
        is_resume: When ``True``, the invocation is a resume after timeout.
            A shorter resume-oriented prompt is sent instead of the full
            template.
    """
    final_prompt = _resolve_prompt(work_item, prompt, template_name, is_resume, session_id)

    # Generate a stable session_id for this work item if none provided
    if session_id is None:
        session_id = f"pokepoke-{work_item.id}"

    max_timeout = timeout or DEFAULT_AGENT_TIMEOUT
    if idle_timeout is None:
        idle_timeout = float(get_config().idle_timeout_seconds)
    inactivity_timeout = float(get_config().session_inactivity_timeout)
    tool_call_timeout = float(get_config().tool_call_timeout)
    liveness_kw = {'process_output_timeout': float(get_config().process_output_timeout),
                   'max_ping_failures': int(get_config().max_ping_failures)}

    client = _create_sdk_client(cwd)

    try:
        logger.info("[SDK] Starting Copilot client...")
        await client.start()

        current_model = model or DEFAULT_MODEL
        total_wall_duration = 0.0
        total_api_duration = 0.0
        abort_reason: str | None = None

        # Explicit retry loop: at most 2 attempts (original + one fallback)
        max_attempts = 2
        output_lines: list[str] = []
        errors: list[str] = []
        handler = None
        stats: _SDKSessionStats | None = None
        session = None
        attempt_result = _AttemptResult()

        for attempt in range(max_attempts):
            session_config = _build_session_config(
                current_model, deny_write, session_id=session_id,
            )
            logger.info(f"[SDK] Using model: {current_model}")
            if is_resume:
                logger.info(f"[SDK] Resuming session: {session_id}")

            session = await client.create_session(session_config)
            logger.info(f"[SDK] Session created: {session.session_id}\n")

            done = asyncio.Event()
            output_lines.clear()
            errors.clear()

            on_token_usage = _build_token_usage_callback()

            if handler is None:
                handler, stats = create_event_handler(
                    done, output_lines, errors, item_logger, idle_timeout,
                    on_token_usage=on_token_usage,
                )
            else:
                handler.reset_for_retry(done, output_lines, errors)

            session.on(handler)

            try:
                attempt_result = await _run_attempt(
                    session, client, handler, final_prompt, done,
                    max_timeout, stats, inactivity_timeout,
                    tool_call_timeout=tool_call_timeout, **liveness_kw,
                )
                total_wall_duration += attempt_result.elapsed
                total_api_duration += attempt_result.elapsed
                abort_reason = attempt_result.abort_reason
                if attempt_result.interrupted:
                    break
                break  # Normal completion

            except RateLimitError:
                if attempt < max_attempts - 1 and current_model != FALLBACK_MODEL:
                    logger.info(f"\n[SDK] Retrying with fallback model: {FALLBACK_MODEL}")
                    try:
                        await session.disconnect()
                    except Exception as e:
                        logger.debug(f"Failed to disconnect session for fallback retry: {e}")
                    session = None
                    current_model = FALLBACK_MODEL
                    continue
                errors.append("Rate limit exceeded")
                break
            finally:
                if session is not None:
                    try:
                        await session.disconnect()
                    except Exception as e:
                        logger.debug(f"Failed to disconnect session during cleanup: {e}")
                    session = None

        # Handle timeout/interrupt/inactivity/tool_timeout/process_dead early exits
        timed_out = abort_reason == "timeout"
        interrupted = abort_reason == "shutdown" or (
            attempt_result.interrupted and abort_reason is None
        )
        inactivity_detected = abort_reason == "inactivity"
        tool_timed_out = abort_reason == "tool_timeout"
        process_dead = abort_reason == "process_dead"
        # Capture output summary for potential resume on next retry
        output_summary = _summarize_output(output_lines) if (
            timed_out or inactivity_detected or tool_timed_out or process_dead
        ) else None
        early = (
            _check_early_exit(
                work_item.id, timed_out, interrupted, max_timeout,
            )
            or _check_abort_result(
                work_item.id, inactivity_detected, inactivity_timeout,
                tool_timed_out, tool_call_timeout,
                process_dead=process_dead,
                last_output_summary=output_summary,
            )
        )
        if early is not None:
            early.session_id = session_id
            early.last_output_summary = output_summary
            return early

        assert stats is not None  # Always set in first loop iteration
        return _build_copilot_result(
            work_item=work_item,
            output_lines=output_lines,
            errors=errors,
            stats=stats,
            current_model=current_model,
            total_api_duration=total_api_duration,
            total_wall_duration=total_wall_duration,
            session_id=session_id,
        )

    except KeyboardInterrupt:
        error = "Session aborted due to application shutdown" if is_shutting_down() else "Interrupted by user"
        logger.error(f"\n[SDK] ⚡️  {error}")
        return _fail_result(work_item.id, error, session_id=session_id)
    except Exception as e:
        logger.info(f"\n[SDK] Exception: {e}")
        return _fail_result(work_item.id, f"SDK exception: {e}", session_id=session_id)
    finally:
        await shutdown_copilot_client(client)


def invoke_copilot_sdk_sync(
    work_item: BeadsWorkItem,
    prompt: str | None = None,
    retry_config: RetryConfig | None = None,
    timeout: float | None = None,
    deny_write: bool = False,
    item_logger: 'ItemLogger | None' = None,
    model: str | None = None,
    cwd: str | None = None,
    template_name: str | None = None,
    session_id: str | None = None,
    is_resume: bool = False,
) -> CopilotResult:
    """Synchronous wrapper around invoke_copilot_sdk."""
    return asyncio.run(invoke_copilot_sdk(
        work_item=work_item,
        prompt=prompt,
        retry_config=retry_config,
        timeout=timeout,
        deny_write=deny_write,
        item_logger=item_logger,
        model=model,
        cwd=cwd,
        template_name=template_name,
        session_id=session_id,
        is_resume=is_resume,
    ))
