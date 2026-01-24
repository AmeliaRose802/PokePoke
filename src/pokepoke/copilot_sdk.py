"""GitHub Copilot SDK integration - Proof of Concept.

This module demonstrates using the GitHub Copilot SDK instead of subprocess calls.
"""

import asyncio
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
    item_logger: Optional['ItemLogger'] = None
) -> CopilotResult:
    """Invoke GitHub Copilot using the SDK (async).
    
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
    config = retry_config or RetryConfig()
    final_prompt = prompt or build_prompt_from_work_item(work_item)
    max_timeout = timeout or 7200.0
    
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
        
        # Event handler for streaming output
        def handle_event(event: Any) -> None:
            # Debug: Print raw event structure to understand what we're receiving
            event_type = event.type.value if hasattr(event.type, 'value') else str(event.type)
            
            # Debug output to see actual event structure
            print(f"[SDK DEBUG] Event type: {event_type}")
            if hasattr(event, 'data'):
                print(f"[SDK DEBUG] Event data type: {type(event.data)}")
                print(f"[SDK DEBUG] Event data: {event.data}")
            
            if event_type == "assistant.message_delta":
                # Streaming message chunk - try multiple possible field names
                delta = None
                if hasattr(event, 'data'):
                    delta = getattr(event.data, 'delta_content', None) or \
                            getattr(event.data, 'delta', None) or \
                            getattr(event.data, 'content', None) or \
                            getattr(event.data, 'text', None)
                
                if delta:
                    print(delta, end="", flush=True)
                    output_lines.append(delta)
                    
            elif event_type == "assistant.message":
                # Final complete message - try multiple possible field names
                content = None
                if hasattr(event, 'data'):
                    content = getattr(event.data, 'content', None) or \
                              getattr(event.data, 'text', None) or \
                              getattr(event.data, 'message', None)
                
                print(f"\n[SDK] Message complete ({len(content) if content else 0} chars)")
                if content and not output_lines:
                    # If we didn't get deltas, use the complete message
                    print(content)  # Print the content so we can see it
                    output_lines.append(content)
                    
            elif event_type == "tool.call":
                # Tool being invoked
                tool_name = getattr(event.data, 'tool_name', 'unknown') if hasattr(event, 'data') else 'unknown'
                print(f"\n[SDK] Tool call: {tool_name}")
                
            elif event_type == "tool.result":
                # Tool completed
                if hasattr(event, 'data'):
                    tool_name = getattr(event.data, 'tool_name', 'unknown')
                    result_type = getattr(event.data, 'result_type', 'unknown')
                    print(f"[SDK] Tool result: {tool_name} -> {result_type}")
                
            elif event_type == "session.idle":
                # Session finished
                print("\n[SDK] Session idle - processing complete")
                done.set()
                
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
        
        # Clean up session
        await session.destroy()
        
        # Determine success
        output_text = "".join(output_lines)
        success = len(errors) == 0
        
        print("\n" + "=" * 60)
        print(f"[SDK] Result: {'SUCCESS' if success else 'FAILURE'}")
        print("=" * 60)
        
        return CopilotResult(
            work_item_id=work_item.id,
            success=success,
            output=output_text,
            error="; ".join(errors) if errors else None,
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
