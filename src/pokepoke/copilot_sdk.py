"""GitHub Copilot SDK integration."""
import asyncio
import os
from typing import Optional, TYPE_CHECKING, Any

from copilot import CopilotClient  # type: ignore

DEFAULT_MODEL = "claude-opus-4.6"
FALLBACK_MODEL = "claude-sonnet-4.5"

from .config import get_config
from .types import BeadsWorkItem, CopilotResult, RetryConfig, AgentStats
from .prompts import PromptService
from . import terminal_ui
from .shutdown import is_shutting_down

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
    tried_fallback = False
    original_pythonioencoding = os.environ.get('PYTHONIOENCODING')
    os.environ['PYTHONIOENCODING'] = 'utf-8:replace'
    # Create SDK client with explicit working directory for thread safety
    client_opts: dict[str, Any] = {"cli_path": "copilot.cmd", "log_level": "info"}
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
        pending_tool_calls, idle_task = 0, None
        total_input_tokens = total_output_tokens = total_cache_read_tokens = 0
        total_cache_write_tokens = turn_count = total_tool_calls = 0
        def handle_event(event: Any) -> None:
            nonlocal total_input_tokens, total_output_tokens, total_cache_read_tokens
            nonlocal total_cache_write_tokens, turn_count, total_tool_calls
            nonlocal pending_tool_calls, idle_task
            
            event_type = event.type.value if hasattr(event.type, 'value') else str(event.type)
            
            if event_type == "assistant.message_delta":
                terminal_ui.ui.set_style("green")
                # Streaming message chunk
                delta = None
                if hasattr(event, 'data'):
                    delta = getattr(event.data, 'delta_content', None) or \
                            getattr(event.data, 'delta', None) or \
                            getattr(event.data, 'content', None)
                
                if delta:
                    print(delta, end="", flush=True)
                    output_lines.append(delta)
                    
            elif event_type == "assistant.message":
                terminal_ui.ui.set_style("green")
                # Complete message - may have text content or tool requests
                content = getattr(event.data, 'content', None) if hasattr(event, 'data') else None
                tool_requests = getattr(event.data, 'tool_requests', None) if hasattr(event, 'data') else None
                
                if content:
                    print(content)
                    output_lines.append(content)
                
                # Reset style for tool announcements
                terminal_ui.ui.set_style(None)
                # Show tool requests if present
                if tool_requests and len(tool_requests) > 0:
                    print(f"\n[Copilot] Calling {len(tool_requests)} tool(s)...")
                    
            elif event_type == "tool.execution_start":
                terminal_ui.ui.set_style(None)
                # Tool is being executed
                total_tool_calls += 1
                pending_tool_calls += 1
                
                # Cancel any pending idle check - we have activity
                if idle_task and not idle_task.done():
                    idle_task.cancel()
                    idle_task = None
                
                if hasattr(event, 'data'):
                    tool_name = getattr(event.data, 'tool_name', 'unknown')
                    arguments = getattr(event.data, 'arguments', {})
                    
                    # Format tool call nicely - show full arguments
                    args_str = str(arguments)
                    print(f"  🔧 {tool_name}({args_str})")
                    output_lines.append(f"\n[Tool] {tool_name}({args_str})\n")
                
            elif event_type == "tool.execution_complete":
                terminal_ui.ui.set_style(None)
                # Tool completed - show full result
                pending_tool_calls = max(0, pending_tool_calls - 1)
                
                if hasattr(event, 'data'):
                    tool_call_id = getattr(event.data, 'tool_call_id', '')
                    result = getattr(event.data, 'result', None)
                    success = getattr(event.data, 'success', True)
                    
                    if result:
                        # Result object has a 'content' attribute
                        result_content = getattr(result, 'content', str(result)) if hasattr(result, 'content') else str(result)
                        result_str = str(result_content)
                        
                        status = "✅" if success else "❌"
                        print(f"  {status} Result: {result_str}")
                        output_lines.append(f"[Result] {result_str}\n")
            
            elif event_type == "assistant.usage":
                terminal_ui.ui.set_style(None)
                # Track usage statistics
                if hasattr(event, 'data'):
                    total_input_tokens += getattr(event.data, 'input_tokens', 0) or 0
                    total_output_tokens += getattr(event.data, 'output_tokens', 0) or 0
                    total_cache_read_tokens += getattr(event.data, 'cache_read_tokens', 0) or 0
                    total_cache_write_tokens += getattr(event.data, 'cache_write_tokens', 0) or 0
            
            elif event_type == "assistant.turn_end":
                # Track turns
                turn_count += 1
                
            elif event_type == "session.idle":
                # Session idle - might mean thinking or complete
                # Cancel any previous idle check
                if idle_task and not idle_task.done():
                    idle_task.cancel()
                    # Don't await, just cancel and move on
                
                # If we have pending tool calls, don't start idle check
                if pending_tool_calls > 0:
                    print(f"\n[SDK] Session idle but {pending_tool_calls} tool(s) still executing - continuing...")
                    # Don't start idle check, just continue processing events
                else:
                    print("\n[SDK] Session idle - waiting to confirm completion...")
                    
                    # Use a delay to distinguish between "thinking" and "done"
                    async def check_still_idle() -> None:
                        try:
                            await asyncio.sleep(idle_timeout)  # Wait configured time
                            if not done.is_set() and pending_tool_calls == 0:
                                print("[SDK] Session confirmed idle - processing complete")
                                done.set()
                        except asyncio.CancelledError:
                            pass  # Task was cancelled, that's fine
                    
                    # Schedule the delayed check
                    idle_task = asyncio.create_task(check_still_idle())
                
            elif event_type == "session.error":
                nonlocal tried_fallback, current_model
                # Error occurred
                error_msg = getattr(event.data, 'message', 'Unknown error') if hasattr(event, 'data') else 'Unknown error'
                print(f"\n[SDK] ERROR: {error_msg}")
                
                # Check for rate limit error and try fallback model
                if not tried_fallback and current_model == DEFAULT_MODEL:
                    error_lower = error_msg.lower()
                    if 'rate' in error_lower and 'limit' in error_lower:
                        print(f"\n[SDK] Rate limit detected on {current_model}, will retry with {FALLBACK_MODEL}...")
                        tried_fallback = True
                        current_model = FALLBACK_MODEL
                        # Don't set done - let the retry happen
                        return
                
                errors.append(error_msg)
                done.set()
        
        session.on(handle_event)
        
        timed_out = False
        interrupted = False
        
        async def send_with_retry() -> bool:
            """Send message, returns True if should retry with fallback model."""
            nonlocal session, session_config, tried_fallback, current_model, timed_out, interrupted
            
            print("[SDK] Sending message...\n")
            await session.send({"prompt": final_prompt})
            
            # Wait for completion with timeout, checking shutdown every second
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
                        continue  # Check shutdown again
            except KeyboardInterrupt:
                print("\n\n[SDK] ⚠️  Interrupted by user (Ctrl+C)")
                try:
                    await session.abort()
                except Exception:
                    pass
                interrupted = True
                return False
            
            # Check if we need to retry with fallback model
            if tried_fallback and current_model == FALLBACK_MODEL and not done.is_set():
                # Rate limit occurred, need to retry with fallback
                print(f"\n[SDK] Retrying with fallback model: {FALLBACK_MODEL}")
                
                # Clean up current session
                try:
                    await session.destroy()
                except Exception:
                    pass
                
                # Create new session with fallback model
                session_config["model"] = FALLBACK_MODEL
                session = await client.create_session(session_config)  # type: ignore[arg-type]
                print(f"[SDK] New session created with {FALLBACK_MODEL}: {session.session_id}\n")
                
                # Reset state for retry
                done.clear()
                errors.clear()
                output_lines.clear()
                session.on(handle_event)
                
                return True  # Signal retry needed
            
            return False  # No retry needed
        
        with terminal_ui.ui.agent_output():
            # First attempt
            needs_retry = await send_with_retry()
            
            # Retry with fallback if rate limited
            if needs_retry:
                await send_with_retry()
        
        # Handle timeout/interrupt cases
        if timed_out:
            return CopilotResult(
                work_item_id=work_item.id,
                success=False,
                error=f"SDK timeout after {max_timeout}s",
                attempt_count=1
            )
        
        if interrupted:
            return CopilotResult(
                work_item_id=work_item.id,
                success=False,
                error="Interrupted by user",
                attempt_count=1
            )
        
        await session.destroy()
        
        output_text = "".join(output_lines)
        success = len(errors) == 0
        
        print(f"\n{'='*60}\n[SDK] Result: {'SUCCESS' if success else 'FAILURE'}\n{'='*60}")
        if turn_count > 0 or total_input_tokens > 0:
            print(f"\n📊 Stats: {turn_count} turns, {total_input_tokens:,}+{total_output_tokens:,} tokens")
        
        stats = AgentStats(
            input_tokens=total_input_tokens,
            output_tokens=total_output_tokens,
            premium_requests=turn_count,  # Approximation: 1 turn = 1 premium request
            tool_calls=total_tool_calls,
            api_duration=0.0,  # TODO: Track duration
            wall_duration=0.0  # TODO: Track duration
        )
        
        return CopilotResult(
            work_item_id=work_item.id,
            success=success,
            output=output_text,
            error="; ".join(errors) if errors else None,
            attempt_count=1,
            stats=stats,
            model=current_model
        )
        
    except KeyboardInterrupt:
        print(f"\n[SDK] ⚠️  Interrupted by user (Ctrl+C)")
        return CopilotResult(
            work_item_id=work_item.id,
            success=False,
            error="Interrupted by user",
            attempt_count=1
        )
        
    except Exception as e:
        print(f"\n[SDK] Exception: {e}")
        return CopilotResult(
            work_item_id=work_item.id,
            success=False,
            error=f"SDK exception: {e}",
            attempt_count=1
        )
        
    finally:
        # Always stop the client
        try:
            await client.stop()
            print("\n[SDK] Client stopped")
        except UnicodeDecodeError:
            # The Copilot subprocess may emit non-UTF-8 bytes when killed
            # during shutdown.  Swallow the encoding error so we get a
            # clean exit with stats printed.
            print("\n[SDK] Client stopped (encoding error suppressed)")
        except Exception as e:
            print(f"\n[SDK] Error stopping client: {e}")
        
        # Restore original encoding setting
        if original_pythonioencoding is not None:
            os.environ['PYTHONIOENCODING'] = original_pythonioencoding
        else:
            os.environ.pop('PYTHONIOENCODING', None)


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
