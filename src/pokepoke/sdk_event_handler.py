"""Event handler utilities for SDK client sessions."""

import asyncio
import json
import logging
import re
from typing import Any, TypedDict

from collections.abc import Callable

from . import terminal_ui
from .hung_command_detector import HungCommandDetector
from .config import get_config, DEFAULT_MODEL, FALLBACK_MODEL

logger = logging.getLogger(__name__)


_BEADS_CREATE_RE = re.compile(r"\bbd\s+create\b", re.IGNORECASE)
_ITEM_ID_RE = re.compile(r"\bPokePoke-[0-9A-Za-z_-]+\b")


def _extract_command(arguments: Any) -> str:
    if isinstance(arguments, dict):
        cmd = arguments.get("command")
        return cmd if isinstance(cmd, str) else str(arguments)
    return str(arguments)


def _parse_created_items(result_content: str) -> list[tuple[str, str]]:
    """Return list of (item_id, title) parsed from tool output."""
    if not result_content:
        return []

    # Prefer JSON output: `bd create ... --json`
    try:
        parsed = json.loads(result_content)
        if isinstance(parsed, dict):
            item_id = parsed.get("id")
            title = parsed.get("title")
            if isinstance(item_id, str) and item_id:
                return [(item_id, title if isinstance(title, str) else "")]
        if isinstance(parsed, list):
            out: list[tuple[str, str]] = []
            for entry in parsed:
                if not isinstance(entry, dict):
                    continue
                item_id = entry.get("id")
                title = entry.get("title")
                if isinstance(item_id, str) and item_id:
                    out.append((item_id, title if isinstance(title, str) else ""))
            if out:
                return out
    except Exception as e:
        logger.debug(f"Failed to parse created items from JSON, falling back to regex: {e}")

    # Fallback: regex scan
    ids = _ITEM_ID_RE.findall(result_content)
    return [(i, "") for i in ids]


def _record_items_created(items: list[tuple[str, str]]) -> None:
    if not items:
        return

    from pokepoke.beads_item_stats_store import record_item_created
    from pokepoke.metrics_context import get_current_agent_type
    from pokepoke.session_stats_registry import get_current_session_stats
    from pokepoke.types import BeadsCreatedItem

    agent_type = get_current_agent_type()
    stats = get_current_session_stats()

    latest_summary: dict[str, Any] | None = None
    for item_id, title in items:
        if stats is not None:
            stats.record_created_item(BeadsCreatedItem(id=item_id, title=title, agent_type=agent_type))
        latest_summary = record_item_created(item_id=item_id, agent_type=agent_type)

    if stats is not None and latest_summary:
        stats.set_lifetime_beads_item_totals(
            created=int(latest_summary.get("total_created", 0)),
            completed=int(latest_summary.get("total_completed", 0)),
        )

# Default hung command detection settings
DEFAULT_MAX_READ_RETRIES = 3  # After 3 reads with no new output, consider hung


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
    idle_timeout: float = 10.0,
    hung_command_detector: HungCommandDetector | None = None,
    on_token_usage: Callable[[int, int], None] | None = None,
) -> tuple[Callable[[Any], None], SessionStats]:
    """Create an event handler for SDK session events.

    Args:
        done: Event to signal session completion.
        output_lines: List to append output to.
        errors: List to append errors to.
        item_logger: Optional logger for item-specific logging.
        idle_timeout: Seconds to wait before confirming session is idle.
        hung_command_detector: Optional detector for hung commands. If None,
            a default one is created using config settings.
        on_token_usage: Optional callback invoked on each usage event with
            (total_input_tokens, total_output_tokens).

    Returns:
        tuple: (event_handler_function, stats_dict)
    """
    # Initialize hung command detector with config settings
    if hung_command_detector is None:
        config = get_config()
        hung_command_detector = HungCommandDetector(
            max_retries=DEFAULT_MAX_READ_RETRIES,
            cumulative_timeout=float(config.command_timeout),
        )

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

    # Track pending tool calls by name for hung detection
    pending_tools: dict[str, dict[str, Any]] = {}
    # Track whether message_delta events streamed content for the current
    # assistant turn so that the final assistant.message event does not
    # duplicate the same text into output_lines / item_logger.
    received_deltas = False
    # Track consecutive idle events with unchanged pending_tool_calls.
    # When the Copilot process exits mid-tool-call, pending_tool_calls
    # stays > 0 permanently.  After consecutive idles with the same
    # stale counter we force-set ``done`` to avoid hanging for 2 hours.
    _stale_idle_count = 0
    _last_idle_pending: int | None = None
    _MAX_STALE_IDLES = 2  # force-complete after this many consecutive stale idles

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
        nonlocal received_deltas, _stale_idle_count, _last_idle_pending
        event_type= event.type.value if hasattr(event.type, 'value') else str(event.type)

        if event_type == "assistant.message_delta":
            received_deltas = True
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
            if content and not received_deltas:
                # Only log the full message when it was NOT already streamed
                # via message_delta events (avoids writing content twice).
                print(content)
                output_lines.append(content)
                if item_logger:
                    item_logger.log_copilot_output(content)
            # Reset delta tracking for the next assistant turn.
            received_deltas = False
            terminal_ui.ui.set_style(None)
            if tool_requests and len(tool_requests) > 0:
                print(f"\n[Copilot] Calling {len(tool_requests)} tool(s)...")

        elif event_type == "tool.execution_start":
            terminal_ui.ui.set_style(None)
            stats['total_tool_calls'] += 1
            stats['pending_tool_calls'] += 1
            # Reset stale idle tracking whenever real tool activity occurs.
            _stale_idle_count = 0
            _last_idle_pending = None
            if stats['idle_task'] and not stats['idle_task'].done():
                stats['idle_task'].cancel()
                stats['idle_task'] = None
            if hasattr(event, 'data'):
                tool_name = getattr(event.data, 'tool_name', 'unknown')
                tool_args = getattr(event.data, 'arguments', {}) or {}
                args_str = str(tool_args)
                print(f"  🔧 {tool_name}({args_str})")
                output_lines.append(f"\n[Tool] {tool_name}({args_str})\n")
                if item_logger:
                    item_logger.log_tool_call(tool_name, args_str)

                # Track tool call for hung command detection
                tool_id = getattr(event.data, 'tool_call_id', None) or id(event)
                pending_tools[str(tool_id)] = {'name': tool_name, 'args': tool_args}

                # Track powershell tool starts for new shell sessions
                if tool_name == 'powershell':
                    shell_id = tool_args.get('shellId')
                    if shell_id:
                        hung_command_detector.record_powershell_start(shell_id)

        elif event_type == "tool.execution_complete":
            terminal_ui.ui.set_style(None)
            stats['pending_tool_calls'] = max(0, stats['pending_tool_calls'] - 1)
            # Reset stale idle tracking whenever real tool activity occurs.
            _stale_idle_count = 0
            _last_idle_pending = None
            if hasattr(event, 'data'):
                tool_name = getattr(event.data, 'tool_name', 'unknown')
                arguments = getattr(event.data, 'arguments', {})
                result = getattr(event.data, 'result', None)
                success = getattr(event.data, 'success', True)

                # Get the tool args from pending_tools
                tool_id = getattr(event.data, 'tool_call_id', None)
                tool_info = pending_tools.pop(str(tool_id), {}) if tool_id else {}
                tool_args = tool_info.get('args', {})

                if result:
                    result_content = getattr(result, 'content', str(result)) if hasattr(result, 'content') else str(result)
                    status = "✅" if success else "❌"
                    print(f"  {status} Result: {result_content}")
                    output_lines.append(f"[Result] {result_content}\n")
                    if item_logger:
                        item_logger.log_tool_call(tool_name, '', result=result_content, success=success)

                    # Check for hung commands on read_powershell completion
                    if tool_name == 'read_powershell':
                        shell_id = tool_args.get('shellId', '')
                        delay = float(tool_args.get('delay', 30))
                        is_hung, corrective_msg = hung_command_detector.record_read_powershell(
                            shell_id, delay, result_content
                        )
                        if is_hung and corrective_msg:
                            # Inject corrective feedback into output
                            print(f"\n{corrective_msg}")
                            output_lines.append(f"\n{corrective_msg}\n")
                            if item_logger:
                                item_logger.log_error(f"Hung command detected for shell {shell_id}")

                    # Clear state when shell is stopped
                    elif tool_name == 'stop_powershell':
                        shell_id = tool_args.get('shellId', '')
                        if shell_id:
                            hung_command_detector.record_stop_powershell(shell_id)

                    # Detect beads item creation via tool calls (agents run `bd create` in powershell).
                    if success and str(tool_name).lower() == "powershell":
                        cmd = _extract_command(arguments)
                        if _BEADS_CREATE_RE.search(cmd):
                            created = _parse_created_items(result_content)
                            _record_items_created(created)

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
                if on_token_usage is not None:
                    on_token_usage(stats['total_input_tokens'], stats['total_output_tokens'])

        elif event_type == "assistant.turn_end":
            stats['turn_count'] += 1

        elif event_type == "session.idle":
            if stats['idle_task'] and not stats['idle_task'].done():
                stats['idle_task'].cancel()
            if stats['pending_tool_calls'] > 0:
                # Track consecutive idles with unchanged pending count.
                # If Copilot exited without emitting tool.execution_complete,
                # the counter will never decrement and we'd hang for hours.
                if _last_idle_pending == stats['pending_tool_calls']:
                    _stale_idle_count += 1
                else:
                    _stale_idle_count = 1
                    _last_idle_pending = stats['pending_tool_calls']

                if _stale_idle_count >= _MAX_STALE_IDLES:
                    print(f"\n[SDK] Session idle with {stats['pending_tool_calls']} stale pending tool(s) "
                          f"(idle x{_stale_idle_count}) - forcing completion (process likely exited)")
                    stats['pending_tool_calls'] = 0
                    done.set()
                else:
                    print(f"\n[SDK] Session idle but {stats['pending_tool_calls']} tool(s) still executing "
                          f"(stale idle {_stale_idle_count}/{_MAX_STALE_IDLES}) - continuing...")
            else:
                _stale_idle_count = 0
                _last_idle_pending = None
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
