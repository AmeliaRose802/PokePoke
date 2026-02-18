"""Event handler utilities for SDK client sessions."""
import asyncio
from typing import Any, TypedDict

from collections.abc import Callable

from . import terminal_ui

DEFAULT_MODEL = "claude-opus-4.6"
FALLBACK_MODEL = "claude-sonnet-4.5"


class SessionStats(TypedDict):
    pending_tool_calls: int
    idle_task: asyncio.Task[None] | None
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
    output_lines: list[str],
    errors: list[str],
    item_logger: Any | None = None,
    idle_timeout: float = 10.0
) -> tuple[Callable[[Any], None], SessionStats]:
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
    
    def _iter_streaming_chunks(event_obj: Any) -> list[tuple[str, str]]:
        """Extract text chunks from tool streaming/progress events."""
        data = getattr(event_obj, "data", None)
        if data is None:
            return []
        chunks: list[tuple[str, str]] = []
        for attr in ("stdout", "stderr", "output", "chunk", "delta", "delta_content", "content", "message", "text"):
            val = getattr(data, attr, None)
            if isinstance(val, str) and val:
                chunks.append((attr, val))
        return chunks
    
    def handle_event(event: Any) -> None:
        """Handle SDK session events."""
        nonlocal stats
        
        event_type = event.type.value if hasattr(event.type, 'value') else str(event.type)
        
        if event_type == "assistant.message_delta":
            terminal_ui.ui.set_style("green")
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
            content = getattr(event.data, 'content', None) if hasattr(event, 'data') else None
            tool_requests = getattr(event.data, 'tool_requests', None) if hasattr(event, 'data') else None
            if content:
                print(content)
                output_lines.append(content)
                if item_logger:
                    item_logger.log_copilot_output(content)
            terminal_ui.ui.set_style(None)
            if tool_requests and len(tool_requests) > 0:
                print(f"\n[Copilot] Calling {len(tool_requests)} tool(s)...")

        elif event_type == "tool.execution_start":
            terminal_ui.ui.set_style(None)
            stats['total_tool_calls'] += 1
            stats['pending_tool_calls'] += 1
            if stats['idle_task'] and not stats['idle_task'].done():
                stats['idle_task'].cancel()
                stats['idle_task'] = None
            if hasattr(event, 'data'):
                tool_name = getattr(event.data, 'tool_name', 'unknown')
                args_str = str(getattr(event.data, 'arguments', {}))
                print(f"  🔧 {tool_name}({args_str})")
                output_lines.append(f"\n[Tool] {tool_name}({args_str})\n")
                if item_logger:
                    item_logger.log_tool_call(tool_name, args_str)

        elif event_type == "tool.execution_complete":
            terminal_ui.ui.set_style(None)
            stats['pending_tool_calls'] = max(0, stats['pending_tool_calls'] - 1)
            if hasattr(event, 'data'):
                result = getattr(event.data, 'result', None)
                success = getattr(event.data, 'success', True)
                if result:
                    result_content = getattr(result, 'content', str(result)) if hasattr(result, 'content') else str(result)
                    status = "✅" if success else "❌"
                    print(f"  {status} Result: {result_content}")
                    output_lines.append(f"[Result] {result_content}\n")
                    if item_logger:
                        item_logger.log_tool_call(
                            getattr(event.data, 'tool_name', 'unknown'),
                            '', result=result_content, success=success
                        )

        elif event_type.startswith("tool.") and event_type not in ("tool.execution_start", "tool.execution_complete"):
            stream_chunks = _iter_streaming_chunks(event)
            if not stream_chunks:
                return
            for source, text in stream_chunks:
                prefix = "[stderr] " if source == "stderr" else ""
                print(f"{prefix}{text}", end="" if text.endswith("\n") else "\n")
                output_lines.append(text)
                if item_logger:
                    item_logger.log_copilot_output(text)

        elif event_type == "assistant.usage":
            terminal_ui.ui.set_style(None)
            if hasattr(event, 'data'):
                stats['total_input_tokens'] += getattr(event.data, 'input_tokens', 0) or 0
                stats['total_output_tokens'] += getattr(event.data, 'output_tokens', 0) or 0
                stats['total_cache_read_tokens'] += getattr(event.data, 'cache_read_tokens', 0) or 0
                stats['total_cache_write_tokens'] += getattr(event.data, 'cache_write_tokens', 0) or 0

        elif event_type == "assistant.turn_end":
            stats['turn_count'] += 1
            
        elif event_type == "session.idle":
            if stats['idle_task'] and not stats['idle_task'].done():
                stats['idle_task'].cancel()
            if stats['pending_tool_calls'] > 0:
                print(f"\n[SDK] Session idle but {stats['pending_tool_calls']} tool(s) still executing - continuing...")
            else:
                print("\n[SDK] Session idle - waiting to confirm completion...")
                async def check_still_idle() -> None:
                    try:
                        await asyncio.sleep(idle_timeout)
                        if not done.is_set() and stats['pending_tool_calls'] == 0:
                            print("[SDK] Session confirmed idle - processing complete")
                            done.set()
                    except asyncio.CancelledError:
                        pass
                stats['idle_task'] = asyncio.create_task(check_still_idle())

        elif event_type == "session.error":
            error_msg = getattr(event.data, 'message', 'Unknown error') if hasattr(event, 'data') else 'Unknown error'
            print(f"\n[SDK] ERROR: {error_msg}")
            if item_logger:
                item_logger.log_error(error_msg)
            if not stats['tried_fallback'] and stats['current_model'] == DEFAULT_MODEL:
                error_lower = error_msg.lower()
                if 'rate' in error_lower and 'limit' in error_lower:
                    print(f"\n[SDK] Rate limit detected, will retry with {FALLBACK_MODEL}...")
                    stats['tried_fallback'] = True
                    stats['current_model'] = FALLBACK_MODEL
                    return
            errors.append(error_msg)
            done.set()
    
    return handle_event, stats
