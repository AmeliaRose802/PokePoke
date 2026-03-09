"""GitHub Copilot SDK integration."""
import asyncio
import logging
import os
from typing import TYPE_CHECKING, Any

try:
    from copilot import CopilotClient  # type: ignore
except ImportError:
    CopilotClient = None

from .config import get_config, DEFAULT_MODEL, FALLBACK_MODEL
from .types import BeadsWorkItem, CopilotResult, RetryConfig
from .prompts import PromptService
from . import terminal_ui
from .shutdown import is_shutting_down
from .process_utils import shutdown_copilot_client
from .sdk_event_handler import create_event_handler
from .sdk_helpers import (
    _fail_result, _build_token_usage_callback, _build_copilot_result,
    _build_session_config, _check_early_exit, _check_inactivity,
    _await_completion,
)

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from .logging_utils import ItemLogger


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
        from pathlib import Path
        env["GIT_CEILING_DIRECTORIES"] = str(Path(cwd).parent)
    return env


def _create_sdk_client(cwd: str | None) -> Any:
    """Create and configure a CopilotClient instance."""
    import shutil
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
    if CopilotClient is None:
        raise ImportError(
            "The 'copilot' SDK package is required but not installed. "
            "Install it or use a different AI backend."
        )
    return CopilotClient(client_opts)  # type: ignore[arg-type]


async def invoke_copilot_sdk(  # type: ignore[no-any-unimported]
    work_item: BeadsWorkItem,
    prompt: str | None = None,
    retry_config: RetryConfig | None = None,
    timeout: float | None = None,
    deny_write: bool = False,
    item_logger: 'ItemLogger | None' = None,
    idle_timeout: float | None = None,
    model: str | None = None,
    cwd: str | None = None,
    template_name: str | None = None
) -> CopilotResult:
    """Invoke GitHub Copilot using the SDK. Falls back to Sonnet on rate limit."""
    final_prompt = prompt or build_prompt_from_work_item(work_item, template_name or "beads-item")
    max_timeout = timeout or 7200.0
    if idle_timeout is None:
        idle_timeout = float(get_config().idle_timeout_seconds)
    inactivity_timeout = float(get_config().session_inactivity_timeout)
    current_model = model or DEFAULT_MODEL

    client = _create_sdk_client(cwd)

    try:
        print("[SDK] Starting Copilot client...")
        await client.start()

        session_config = _build_session_config(current_model, deny_write)
        print(f"[SDK] Using model: {current_model}")

        session = await client.create_session(session_config)  # type: ignore[arg-type]
        print(f"[SDK] Session created: {session.session_id}\n")

        done = asyncio.Event()
        output_lines: list[str] = []
        errors: list[str] = []

        # Build a token-usage callback that pushes live stats to the agent card.
        on_token_usage = _build_token_usage_callback()

        handle_event, stats = create_event_handler(
            done, output_lines, errors, item_logger, idle_timeout,
            on_token_usage=on_token_usage,
        )
        stats['current_model'] = current_model

        session.on(handle_event)
        timed_out = False
        interrupted = False
        inactivity_detected = False
        total_wall_duration = 0.0
        total_api_duration = 0.0

        async def send_with_retry() -> bool:
            """Send message, returns True if should retry with fallback model."""
            nonlocal session, session_config, current_model, timed_out, interrupted, inactivity_detected, total_wall_duration, total_api_duration
            print("[SDK] Sending message...\n")
            attempt_start = asyncio.get_event_loop().time()
            try:
                await session.send({"prompt": final_prompt})
                abort_reason = await _await_completion(
                    session, client, done, max_timeout,
                    stats=stats, inactivity_timeout=inactivity_timeout,
                )
                if abort_reason == "shutdown":
                    interrupted = True
                    return False
                if abort_reason == "timeout":
                    timed_out = True
                    return False
                if abort_reason == "inactivity":
                    inactivity_detected = True
                    return False
            except KeyboardInterrupt:
                print("\n\n[SDK] ⚠️  Interrupted by user (Ctrl+C)")
                try:
                    await session.abort()
                except Exception as e:
                    logger.debug(f"Failed to abort session on interrupt: {e}")
                interrupted = True
                return False
            finally:
                attempt_elapsed = asyncio.get_event_loop().time() - attempt_start
                total_wall_duration += attempt_elapsed
                # Copilot SDK does not emit separate API timing, so treat session time as API time.
                total_api_duration += attempt_elapsed
            # Check if we need to retry with fallback model
            if stats['tried_fallback'] and stats['current_model'] == FALLBACK_MODEL and not done.is_set():
                print(f"\n[SDK] Retrying with fallback model: {FALLBACK_MODEL}")
                try:
                    await session.destroy()
                except Exception as e:
                    logger.debug(f"Failed to destroy session for fallback retry: {e}")
                session_config["model"] = FALLBACK_MODEL
                session = await client.create_session(session_config)  # type: ignore[arg-type]
                print(f"[SDK] New session created with {FALLBACK_MODEL}: {session.session_id}\n")
                done.clear()
                errors.clear()
                output_lines.clear()
                session.on(handle_event)
                return True
            return False

        with terminal_ui.ui.agent_output():
            needs_retry = await send_with_retry()
            if needs_retry:
                await send_with_retry()

        # Handle timeout/interrupt cases
        early = _check_early_exit(
            work_item.id, timed_out, interrupted,
            max_timeout,
        )
        if early is not None:
            return early

        # Handle inactivity (dead session) detection
        inactivity_early = _check_inactivity(
            work_item.id, inactivity_detected, inactivity_timeout,
        )
        if inactivity_early is not None:
            return inactivity_early

        await session.destroy()
        return _build_copilot_result(
            work_item=work_item,
            output_lines=output_lines,
            errors=errors,
            stats=stats,
            current_model=current_model,
            total_api_duration=total_api_duration,
            total_wall_duration=total_wall_duration,
        )

    except KeyboardInterrupt:
        error = "Session aborted due to application shutdown" if is_shutting_down() else "Interrupted by user"
        print(f"\n[SDK] ⚠️  {error}")
        return _fail_result(work_item.id, error)
    except Exception as e:
        print(f"\n[SDK] Exception: {e}")
        return _fail_result(work_item.id, f"SDK exception: {e}")
    finally:
        await shutdown_copilot_client(client)


def invoke_copilot_sdk_sync(  # type: ignore[no-any-unimported]
    work_item: BeadsWorkItem,
    prompt: str | None = None,
    retry_config: RetryConfig | None = None,
    timeout: float | None = None,
    deny_write: bool = False,
    item_logger: 'ItemLogger | None' = None,
    model: str | None = None,
    cwd: str | None = None,
    template_name: str | None = None
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
        template_name=template_name
    ))
