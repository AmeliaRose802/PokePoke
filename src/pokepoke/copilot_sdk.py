"""GitHub Copilot SDK integration."""
import asyncio
import contextlib
import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any
from copilot import CopilotClient  # type: ignore
from .config import get_config, DEFAULT_MODEL, FALLBACK_MODEL
from .types import BeadsWorkItem, CopilotResult, RetryConfig, AgentStats
from .prompts import PromptService
from . import terminal_ui
from .shutdown import is_shutting_down
from .process_utils import wait_for_process_cleanup
from .sdk_event_handler import create_event_handler

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from .logging_utils import ItemLogger


async def _activity_watchdog(
    log_path: Path,
    timeout_seconds: float,
    check_interval_seconds: float,
    abort_event: asyncio.Event
) -> bool:
    """Monitor log file activity and detect hung sessions.

    Args:
        log_path: Path to the item log file to monitor
        timeout_seconds: How long to wait with no activity before aborting
        check_interval_seconds: How often to check for activity
        abort_event: Event to signal when session should abort

    Returns:
        True if watchdog triggered abort, False if cancelled normally
    """
    try:
        last_mtime = log_path.stat().st_mtime if log_path.exists() else 0.0
        last_activity_time = asyncio.get_event_loop().time()

        while True:
            await asyncio.sleep(check_interval_seconds)

            # Check if log file was modified
            current_mtime = log_path.stat().st_mtime if log_path.exists() else 0.0
            current_time = asyncio.get_event_loop().time()

            if current_mtime > last_mtime:
                # Activity detected - reset timer
                last_mtime = current_mtime
                last_activity_time = current_time
            else:
                # No activity - check if we've exceeded threshold
                idle_duration = current_time - last_activity_time
                if idle_duration >= timeout_seconds:
                    print(f"\n⚠️  ACTIVITY WATCHDOG: No output for {int(idle_duration)}s (threshold: {int(timeout_seconds)}s)")
                    print("   Aborting hung session...")
                    abort_event.set()
                    return True

    except asyncio.CancelledError:
        # Normal cancellation - session completed
        return False
    except Exception as e:
        print(f"\n⚠️  Activity watchdog error: {e}")
        return False


def build_prompt_from_work_item(
    work_item: BeadsWorkItem,
    template_name: str = "beads-item",
) -> str:
    """Build a prompt from a work item using the template system.

    Args:
        work_item: The work item to build a prompt for.
        template_name: Name of the prompt template to use (default: ``"beads-item"``).
            Assignment rules may specify a custom template via ``prompt_template``.
    """
    config = get_config()
    service = PromptService()
    # Build test data section from config
    test_data_lines = [
        f"When you need {k.replace('_', ' ').capitalize()}, use: {v}"
        for k, v in config.test_data.items()
    ]
    test_data_section = "\n\n".join(test_data_lines) if test_data_lines else None
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
    }

    return service.load_and_render(template_name, variables)


def _fail_result(work_item_id: str, error: str) -> CopilotResult:
    """Create a failed CopilotResult."""
    return CopilotResult(work_item_id=work_item_id, success=False, error=error, attempt_count=1)


async def invoke_copilot_sdk(  # type: ignore[no-any-unimported]
    work_item: BeadsWorkItem,
    prompt: str | None = None,
    retry_config: RetryConfig | None = None,
    timeout: float | None = None,
    deny_write: bool = False,
    item_logger: 'ItemLogger | None' = None,
    idle_timeout: float = 10.0,
    model: str | None = None,
    cwd: str | None = None,
    template_name: str | None = None
) -> CopilotResult:
    """Invoke GitHub Copilot using the SDK. Falls back to Sonnet on rate limit."""
    final_prompt = prompt or build_prompt_from_work_item(work_item, template_name or "beads-item")
    max_timeout = timeout or 7200.0
    current_model = model or DEFAULT_MODEL
    watchdog_task: asyncio.Task[bool] | None = None  # Initialize early for finally block

    # Pass PYTHONIOENCODING via subprocess env (thread-safe, no global os.environ mutation)
    proj_config = get_config()
    client_opts: dict[str, Any] = {
        "cli_path": proj_config.ai_backend.copilot_cli_path,
        "log_level": "info",
        "env": {**os.environ, "PYTHONIOENCODING": "utf-8:replace"},
    }
    if cwd:
        client_opts["cwd"] = cwd
    client = CopilotClient(client_opts)  # type: ignore[arg-type]

    try:
        print("[SDK] Starting Copilot client...")
        await client.start()

        session_config = {"model": current_model, "streaming": True}
        print(f"[SDK] Using model: {current_model}")

        # Add tool restrictions if needed
        if deny_write:
            session_config["excluded_tools"] = ["write", "edit"]

        session = await client.create_session(session_config)  # type: ignore[arg-type]
        print(f"[SDK] Session created: {session.session_id}\n")

        done = asyncio.Event()
        output_lines: list[str] = []
        errors: list[str] = []
        handle_event, stats = create_event_handler(done, output_lines, errors, item_logger, idle_timeout)
        stats['current_model'] = current_model

        session.on(handle_event)
        timed_out = False
        interrupted = False
        activity_timeout = False
        total_wall_duration = 0.0
        total_api_duration = 0.0

        # Setup activity watchdog
        watchdog_abort = asyncio.Event()
        if item_logger and proj_config.activity_watchdog.enabled:
            log_path = Path(item_logger.log_path)
            watchdog_task = asyncio.create_task(
                _activity_watchdog(
                    log_path,
                    float(proj_config.activity_watchdog.timeout_seconds),
                    float(proj_config.activity_watchdog.check_interval_seconds),
                    watchdog_abort
                )
            )
            print(f"[SDK] Activity watchdog enabled (timeout: {proj_config.activity_watchdog.timeout_seconds}s)\n")

        async def send_with_retry() -> bool:
            """Send message, returns True if should retry with fallback model."""
            nonlocal session, session_config, current_model, timed_out, interrupted, activity_timeout, total_wall_duration, total_api_duration
            print("[SDK] Sending message...\n")
            attempt_start = asyncio.get_event_loop().time()
            try:
                await session.send({"prompt": final_prompt})
                deadline = asyncio.get_event_loop().time() + max_timeout
                while not done.is_set():
                    if is_shutting_down():
                        print("\n[SDK] Shutdown requested - aborting session...")
                        await session.abort()
                        interrupted = True
                        return False
                    if watchdog_abort.is_set():
                        print("\n[SDK] Activity watchdog triggered - aborting session...")
                        await session.abort()
                        activity_timeout = True
                        return False
                    remaining = deadline - asyncio.get_event_loop().time()
                    if remaining <= 0:
                        print(f"\n[SDK] TIMEOUT after {max_timeout}s")
                        await session.abort()
                        timed_out = True
                        return False
                    try:
                        await asyncio.wait_for(done.wait(), timeout=min(1.0, remaining))
                    except TimeoutError:
                        continue
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

        # Cancel watchdog if it's still running
        if watchdog_task and not watchdog_task.done():
            watchdog_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await watchdog_task

        # Handle timeout/interrupt cases
        if activity_timeout:
            return _fail_result(work_item.id, f"Activity timeout: no output for {proj_config.activity_watchdog.timeout_seconds}s")
        if timed_out:
            return _fail_result(work_item.id, f"SDK timeout after {max_timeout}s")
        if interrupted:
            error = "Session aborted due to application shutdown" if is_shutting_down() else "Interrupted by user"
            return _fail_result(work_item.id, error)

        await session.destroy()
        output_text = "".join(output_lines)
        success = len(errors) == 0
        print(f"\n{'='*60}\n[SDK] Result: {'SUCCESS' if success else 'FAILURE'}\n{'='*60}")
        if stats['turn_count'] > 0 or stats['total_input_tokens'] > 0:
            print(f"\n📊 Stats: {stats['turn_count']} turns, {stats['total_input_tokens']:,}+{stats['total_output_tokens']:,} tokens")
        agent_stats = AgentStats(
            input_tokens=stats['total_input_tokens'], output_tokens=stats['total_output_tokens'],
            premium_requests=stats['turn_count'], tool_calls=stats['total_tool_calls'],
            api_duration=total_api_duration, wall_duration=total_wall_duration,
            api_duration_by_model={current_model: total_api_duration},
        )
        return CopilotResult(
            work_item_id=work_item.id, success=success, output=output_text,
            error="; ".join(errors) if errors else None,
            attempt_count=1, stats=agent_stats, model=current_model,
        )

    except KeyboardInterrupt:
        error = "Session aborted due to application shutdown" if is_shutting_down() else "Interrupted by user"
        print(f"\n[SDK] ⚠️  {error}")
        return _fail_result(work_item.id, error)
    except Exception as e:
        print(f"\n[SDK] Exception: {e}")
        return _fail_result(work_item.id, f"SDK exception: {e}")
    finally:
        # Ensure watchdog is cancelled
        if watchdog_task and not watchdog_task.done():
            watchdog_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await watchdog_task

        try:
            print("\n[SDK] Initiating graceful client shutdown...")
            await asyncio.sleep(0.5)
            try:
                await asyncio.wait_for(client.stop(), timeout=10.0)
                print("[SDK] Client stopped gracefully")
                if os.name == 'nt':
                    wait_for_process_cleanup(max_wait=2.0)
            except TimeoutError:
                print("[SDK] Client stop timed out after 10s - forcing shutdown")
                try:
                    await client.stop()
                    if os.name == 'nt':
                        wait_for_process_cleanup(max_wait=1.0)
                except Exception as e:
                    logger.debug(f"Failed to force stop client: {e}")
        except UnicodeDecodeError:
            print("[SDK] Client stopped (encoding error suppressed)")
        except Exception as e:
            print(f"[SDK] Error stopping client: {e}")


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
