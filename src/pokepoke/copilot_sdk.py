"""GitHub Copilot SDK integration - Proof of Concept.

This module demonstrates using the GitHub Copilot SDK instead of subprocess calls.
"""

import asyncio
import os
from typing import Optional, TYPE_CHECKING, Any

from copilot import CopilotClient  # type: ignore[import-not-found]

from .types import BeadsWorkItem, CopilotResult, RetryConfig
from .prompts import PromptService

if TYPE_CHECKING:
    from .logging import ItemLogger  # type: ignore[import-untyped]


def build_prompt_from_work_item(work_item: BeadsWorkItem) -> str:
    """Build a prompt from a work item using the template system.
    
    Args:
        work_item: The beads work item
        
    Returns:
        Rendered prompt string
    """
    service = PromptService()
    
    # Build variables dictionary
    variables = {
        "item_id": work_item.id,
        "title": work_item.title,
        "description": work_item.description or "",
        "issue_type": work_item.issue_type,
        "priority": work_item.priority,
        "labels": ", ".join(work_item.labels) if work_item.labels else None,
    }
    
    return service.load_and_render("beads-item", variables)


async def invoke_copilot_sdk(  # type: ignore[no-any-unimported]
    work_item: BeadsWorkItem,
    prompt: Optional[str] = None,
    retry_config: Optional[RetryConfig] = None,
    timeout: Optional[float] = None,
    deny_write: bool = False,
    item_logger: Optional['ItemLogger'] = None,
    idle_timeout: float = 10.0
) -> CopilotResult:
    """Invoke GitHub Copilot using the SDK (async).
    
    Args:
        work_item: The beads work item to process.
        prompt: Optional pre-built prompt (if not provided, will build one from template).
        retry_config: Retry configuration (uses defaults if not provided).
        timeout: Maximum execution time in seconds (default: 7200 = 2 hours).
        deny_write: If True, deny file write tools (for beads-only agents).
        item_logger: Optional item logger for file logging (currently unused in SDK mode).
        idle_timeout: Seconds to wait after session.idle before considering complete (default: 10.0).
        
    Returns:
        Result of the Copilot invocation.
    """
    config = retry_config or RetryConfig()
    final_prompt = prompt or build_prompt_from_work_item(work_item)
    max_timeout = timeout or 7200.0
    
    # Configure environment to handle encoding errors gracefully in SDK subprocess
    # The SDK spawns copilot.cmd as a subprocess, and tool results may contain non-UTF-8 data
    original_pythonioencoding = os.environ.get('PYTHONIOENCODING')
    os.environ['PYTHONIOENCODING'] = 'utf-8:replace'
    
    print(f"\n[WORK_ITEM] Invoking Copilot SDK for work item: {work_item.id}")
    print(f"   Title: {work_item.title}")
    print(f"   [TIMEOUT]  Max timeout: {max_timeout/60:.1f} minutes\n")
    print("=" * 60)
    print("\n[DEBUG] Full Prompt Being Sent:")
    print("=" * 60)
    print(final_prompt)
    print("=" * 60)
    print()
    
    # Create SDK client with explicit CLI path
    # The SDK looks for 'copilot' in PATH, but we need to ensure it finds the right one
    client = CopilotClient({
        "cli_path": "copilot.cmd",  # Use .cmd on Windows to ensure it finds the npm-installed version
        "log_level": "info",
    })
    
    try:
        # Start the client
        print("[SDK] Starting Copilot client...")
        await client.start()
        print("[SDK] Client started successfully\n")
        
        # Create session with appropriate configuration
        session_config = {
            "model": "gpt-4.1",  # Use GPT-4.1 (more stable than GPT-5)
            "streaming": True,  # Enable streaming for real-time output
        }
        
        # Add tool restrictions if needed
        if deny_write:
            session_config["excluded_tools"] = ["write", "edit"]
        
        session = await client.create_session(session_config)
        print(f"[SDK] Session created: {session.session_id}\n")
        
        # Track completion
        done = asyncio.Event()
        output_lines = []
        errors = []
        
        # Track tool execution state
        pending_tool_calls = 0  # Tools currently executing
        idle_task: Optional[asyncio.Task[None]] = None  # Current idle check task
        
        # Track statistics from usage events
        total_input_tokens = 0
        total_output_tokens = 0
        total_cache_read_tokens = 0
        total_cache_write_tokens = 0
        total_cost = 0.0
        turn_count = 0
        
        # Event handler for streaming output
        def handle_event(event: Any) -> None:
            nonlocal total_input_tokens, total_output_tokens, total_cache_read_tokens
            nonlocal total_cache_write_tokens, total_cost, turn_count
            nonlocal pending_tool_calls, idle_task
            
            event_type = event.type.value if hasattr(event.type, 'value') else str(event.type)
            
            if event_type == "assistant.message_delta":
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
                # Complete message - may have text content or tool requests
                content = getattr(event.data, 'content', None) if hasattr(event, 'data') else None
                tool_requests = getattr(event.data, 'tool_requests', None) if hasattr(event, 'data') else None
                
                if content:
                    print(content)
                    output_lines.append(content)
                
                # Show tool requests if present
                if tool_requests and len(tool_requests) > 0:
                    print(f"\n[Copilot] Calling {len(tool_requests)} tool(s)...")
                    
            elif event_type == "tool.execution_start":
                # Tool is being executed
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
                # Track usage statistics
                if hasattr(event, 'data'):
                    total_input_tokens += getattr(event.data, 'input_tokens', 0) or 0
                    total_output_tokens += getattr(event.data, 'output_tokens', 0) or 0
                    total_cache_read_tokens += getattr(event.data, 'cache_read_tokens', 0) or 0
                    total_cache_write_tokens += getattr(event.data, 'cache_write_tokens', 0) or 0
                    total_cost += getattr(event.data, 'cost', 0.0) or 0.0
            
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
                # Error occurred
                error_msg = getattr(event.data, 'message', 'Unknown error') if hasattr(event, 'data') else 'Unknown error'
                print(f"\n[SDK] ERROR: {error_msg}")
                errors.append(error_msg)
                done.set()
        
        # Subscribe to events
        session.on(handle_event)
        
        # Send the message
        print("[SDK] Sending message...\n")
        await session.send({"prompt": final_prompt})
        
        # Wait for completion with timeout
        try:
            await asyncio.wait_for(done.wait(), timeout=max_timeout)
        except asyncio.TimeoutError:
            print(f"\n[SDK] TIMEOUT after {max_timeout}s")
            await session.abort()
            return CopilotResult(
                work_item_id=work_item.id,
                success=False,
                error=f"SDK timeout after {max_timeout}s",
                attempt_count=1
            )
        except KeyboardInterrupt:
            print("\n\n[SDK] ⚠️  Interrupted by user (Ctrl+C)")
            try:
                await session.abort()
            except Exception:
                pass  # Best effort cleanup
            return CopilotResult(
                work_item_id=work_item.id,
                success=False,
                error="Interrupted by user",
                attempt_count=1
            )
        
        # Clean up session
        await session.destroy()
        
        # Determine success
        output_text = "".join(output_lines)
        success = len(errors) == 0
        
        print("\n" + "=" * 60)
        print(f"[SDK] Result: {'SUCCESS' if success else 'FAILURE'}")
        print("=" * 60)
        
        # Display statistics
        if turn_count > 0 or total_input_tokens > 0:
            print("\n📊 Session Statistics:")
            print(f"   Turns: {turn_count}")
            print(f"   Input tokens: {total_input_tokens:,}")
            print(f"   Output tokens: {total_output_tokens:,}")
            if total_cache_read_tokens > 0:
                print(f"   Cache read tokens: {total_cache_read_tokens:,}")
            if total_cache_write_tokens > 0:
                print(f"   Cache write tokens: {total_cache_write_tokens:,}")
            print(f"   Total tokens: {total_input_tokens + total_output_tokens:,}")
            if total_cost > 0:
                print(f"   Estimated cost: ${total_cost:.4f}")
            print()
        
        return CopilotResult(
            work_item_id=work_item.id,
            success=success,
            output=output_text,
            error="; ".join(errors) if errors else None,
            attempt_count=1
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
        except Exception as e:
            print(f"\n[SDK] Error stopping client: {e}")
        
        # Restore original encoding setting
        if original_pythonioencoding is not None:
            os.environ['PYTHONIOENCODING'] = original_pythonioencoding
        else:
            os.environ.pop('PYTHONIOENCODING', None)


# Synchronous wrapper for compatibility
def invoke_copilot_sdk_sync(  # type: ignore[no-any-unimported]
    work_item: BeadsWorkItem,
    prompt: Optional[str] = None,
    retry_config: Optional[RetryConfig] = None,
    timeout: Optional[float] = None,
    deny_write: bool = False,
    item_logger: Optional['ItemLogger'] = None
) -> CopilotResult:
    """Synchronous wrapper around invoke_copilot_sdk.
    
    This allows the SDK version to be used as a drop-in replacement
    for the current subprocess-based implementation.
    
    Args:
        work_item: The beads work item to process.
        prompt: Optional pre-built prompt (if not provided, will build one from template).
        retry_config: Retry configuration (uses defaults if not provided).
        timeout: Maximum execution time in seconds (default: 7200 = 2 hours).
        deny_write: If True, deny file write tools (for beads-only agents).
        item_logger: Optional item logger for file logging (currently unused in SDK mode).
        
    Returns:
        Result of the Copilot invocation.
    """
    return asyncio.run(invoke_copilot_sdk(
        work_item=work_item,
        prompt=prompt,
        retry_config=retry_config,
        timeout=timeout,
        deny_write=deny_write,
        item_logger=item_logger
    ))
