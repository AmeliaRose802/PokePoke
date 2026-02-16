"""GitHub Copilot SDK integration."""
import asyncio
import os
from typing import Optional, TYPE_CHECKING, Any
from copilot import CopilotClient  # type: ignore
from .config import get_config
from .types import BeadsWorkItem, CopilotResult, RetryConfig, AgentStats
from .prompts import PromptService
from . import terminal_ui
from .shutdown import is_shutting_down
from .process_utils import wait_for_process_cleanup
from .sdk_event_handler import create_event_handler

DEFAULT_MODEL = "claude-opus-4.6"
FALLBACK_MODEL = "claude-sonnet-4.5"

if TYPE_CHECKING:
    from .logging_utils import ItemLogger


def build_prompt_from_work_item(work_item: BeadsWorkItem) -> str:
    """Build a prompt from a work item using the template system."""
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
    }
    
    return service.load_and_render("beads-item", variables)


def _fail_result(work_item_id: str, error: str) -> CopilotResult:
    """Create a failed CopilotResult."""
    return CopilotResult(work_item_id=work_item_id, success=False, error=error, attempt_count=1)


async def invoke_copilot_sdk(  # type: ignore[no-any-unimported]
    work_item: BeadsWorkItem,
    prompt: Optional[str] = None,
    retry_config: Optional[RetryConfig] = None,
    timeout: Optional[float] = None,
    deny_write: bool = False,
    item_logger: Optional['ItemLogger'] = None,
    idle_timeout: float = 10.0,
    model: Optional[str] = None,
    cwd: Optional[str] = None
) -> CopilotResult:
    """Invoke GitHub Copilot using the SDK. Falls back to Sonnet on rate limit."""
    config = retry_config or RetryConfig()
    final_prompt = prompt or build_prompt_from_work_item(work_item)
    max_timeout = timeout or 7200.0
    current_model = model or DEFAULT_MODEL
    # Pass PYTHONIOENCODING via subprocess env (thread-safe, no global os.environ mutation)
    client_opts: dict[str, Any] = {"cli_path": "copilot.cmd", "log_level": "info", "env": {**os.environ, "PYTHONIOENCODING": "utf-8:replace"}}
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
        
        done, output_lines, errors = asyncio.Event(), [], []
        handle_event, stats = create_event_handler(done, output_lines, errors, item_logger, idle_timeout)
        stats['current_model'] = current_model
        
        session.on(handle_event)
        timed_out = False
        interrupted = False

        async def send_with_retry() -> bool:
            """Send message, returns True if should retry with fallback model."""
            nonlocal session, session_config, current_model, timed_out, interrupted
            print("[SDK] Sending message...\n")
            await session.send({"prompt": final_prompt})
            try:
                deadline = asyncio.get_event_loop().time() + max_timeout
                while not done.is_set():
                    if is_shutting_down():
                        print("\n[SDK] Shutdown requested - aborting session...")
                        await session.abort()
                        interrupted = True
                        return False
                    remaining = deadline - asyncio.get_event_loop().time()
                    if remaining <= 0:
                        print(f"\n[SDK] TIMEOUT after {max_timeout}s")
                        await session.abort()
                        timed_out = True
                        return False
                    try:
                        await asyncio.wait_for(done.wait(), timeout=min(1.0, remaining))
                    except asyncio.TimeoutError:
                        continue
            except KeyboardInterrupt:
                print("\n\n[SDK] ⚠️  Interrupted by user (Ctrl+C)")
                try:
                    await session.abort()
                except Exception:
                    pass
                interrupted = True
                return False
            # Check if we need to retry with fallback model
            if stats['tried_fallback'] and stats['current_model'] == FALLBACK_MODEL and not done.is_set():
                print(f"\n[SDK] Retrying with fallback model: {FALLBACK_MODEL}")
                try:
                    await session.destroy()
                except Exception:
                    pass
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
            api_duration=0.0, wall_duration=0.0,
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
        try:
            print("\n[SDK] Initiating graceful client shutdown...")
            await asyncio.sleep(0.5)
            try:
                await asyncio.wait_for(client.stop(), timeout=10.0)
                print("[SDK] Client stopped gracefully")
                if os.name == 'nt':
                    wait_for_process_cleanup(max_wait=2.0)
            except asyncio.TimeoutError:
                print("[SDK] Client stop timed out after 10s - forcing shutdown")
                try:
                    await client.stop()
                    if os.name == 'nt':
                        wait_for_process_cleanup(max_wait=1.0)
                except Exception:
                    pass
        except UnicodeDecodeError:
            print("[SDK] Client stopped (encoding error suppressed)")
        except Exception as e:
            print(f"[SDK] Error stopping client: {e}")


def invoke_copilot_sdk_sync(  # type: ignore[no-any-unimported]
    work_item: BeadsWorkItem,
    prompt: Optional[str] = None,
    retry_config: Optional[RetryConfig] = None,
    timeout: Optional[float] = None,
    deny_write: bool = False,
    item_logger: Optional['ItemLogger'] = None,
    model: Optional[str] = None,
    cwd: Optional[str] = None
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
        cwd=cwd
    ))
