"""Event handler utilities for SDK client sessions."""
import asyncio
from typing import Any, Callable, List, Optional, Tuple, TypedDict

from . import terminal_ui

DEFAULT_MODEL = "claude-opus-4.6"
FALLBACK_MODEL = "claude-sonnet-4.5"


class SessionStats(TypedDict):
    pending_tool_calls: int
    idle_task: Optional[asyncio.Task[None]]
    total_input_tokens: int
    total_output_tokens: int
    total_cache_read_tokens: int
    total_cache_write_tokens: int
    turn_count: int
    total_tool_calls: int
    tried_fallback: bool
    current_model: str


def create_event_handler(
    done: asyncio.Event,
    output_lines: List[str],
    errors: List[str],
    item_logger: Optional[Any] = None
) -> Tuple[Callable[[Any], bool], SessionStats]:
    """Create an event handler for SDK session events.
    
    Returns:
        tuple: (event_handler_function, stats_dict)
    """
    # Shared state for event handler
    stats: SessionStats = {
        'pending_tool_calls': 0,
        'idle_task': None,
        'total_input_tokens': 0,
        'total_output_tokens': 0,
        'total_cache_read_tokens': 0,
        'total_cache_write_tokens': 0,
        'turn_count': 0,
        'total_tool_calls': 0,
        'tried_fallback': False,
        'current_model': DEFAULT_MODEL
    }
    
    def handle_event(event: Any) -> bool:
        """Handle SDK session events. Returns True if rate limit retry needed."""
        nonlocal stats
        
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
                if item_logger:
                    item_logger.log_copilot_output(delta)
                    
        elif event_type == "assistant.message":
            terminal_ui.ui.set_style("green")
            # Non-streaming message content
            if hasattr(event, 'data') and hasattr(event.data, 'content'):
                content = event.data.content
                print(content)
                output_lines.append(content)
                if item_logger:
                    item_logger.log_copilot_output(content)
                    
        elif event_type == "assistant.message_complete":
            # Complete message received - start waiting for idle
            if stats['idle_task']:
                stats['idle_task'].cancel()
                
            async def wait_for_idle() -> None:
                await asyncio.sleep(1.0)  # Wait 1 second for idle
                if stats['pending_tool_calls'] > 0:
                    print(f"\n[SDK] Session idle but {stats['pending_tool_calls']} tool(s) still executing - continuing...")
                else:
                    print("\n[SDK] Session idle - waiting to confirm completion...")
                    await asyncio.sleep(2.0)  # Wait another 2 seconds
                    try:
                        if stats['pending_tool_calls'] == 0:
                            print("[SDK] Session confirmed idle - processing complete")
                            done.set()
                    except Exception:
                        pass  # In case event loop is shutting down
                        
            stats['idle_task'] = asyncio.create_task(wait_for_idle())
            
        elif event_type == "assistant.error":
            terminal_ui.ui.set_style("red")
            error_msg = "Unknown error"
            if hasattr(event, 'data') and hasattr(event.data, 'error'):
                error_msg = event.data.error
            elif hasattr(event, 'error'):
                error_msg = str(event.error)
                
            print(f"\n[SDK] ERROR: {error_msg}")
            errors.append(error_msg)
            
            # Check for rate limit and try fallback
            if "rate limit" in error_msg.lower() or "too many requests" in error_msg.lower():
                if not stats['tried_fallback']:
                    print(f"\n[SDK] Rate limit detected on {stats['current_model']}, will retry with {FALLBACK_MODEL}...")
                    return True  # Signal rate limit for retry
            done.set()
            
        elif event_type == "assistant.tool_calls":
            stats['pending_tool_calls'] += 1
            stats['total_tool_calls'] += 1
            terminal_ui.ui.set_style("blue")
            
        elif event_type == "assistant.tool_execution_complete":
            stats['pending_tool_calls'] = max(0, stats['pending_tool_calls'] - 1)
            
        elif event_type in ["assistant.usage", "usage"]:
            # Track token usage
            if hasattr(event, 'data'):
                usage_data = event.data
                if hasattr(usage_data, 'input_tokens'):
                    stats['total_input_tokens'] += usage_data.input_tokens
                if hasattr(usage_data, 'output_tokens'):
                    stats['total_output_tokens'] += usage_data.output_tokens
                if hasattr(usage_data, 'cache_read_tokens'):
                    stats['total_cache_read_tokens'] += usage_data.cache_read_tokens
                if hasattr(usage_data, 'cache_write_tokens'):
                    stats['total_cache_write_tokens'] += usage_data.cache_write_tokens
                    
            stats['turn_count'] += 1
            
        return False  # No rate limit retry needed
    
    return handle_event, stats
