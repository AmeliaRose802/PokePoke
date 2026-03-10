"""Event handler utilities for SDK client sessions."""

import asyncio
import logging
import time
from typing import Any, TypedDict

from collections.abc import Callable

from . import terminal_ui
from .hung_command_detector import HungCommandDetector
from .config import get_config, FALLBACK_MODEL
from .sdk_beads_tracker import extract_command, parse_created_items, record_items_created, is_beads_create

logger = logging.getLogger(__name__)


class RateLimitError(Exception):
    """Raised when the SDK session hits a rate limit."""

    def __init__(self, message: str = "Rate limit exceeded") -> None:
        super().__init__(message)


# Default hung command detection settings
DEFAULT_MAX_READ_RETRIES = 3  # After 3 reads with no new output, consider hung

_STREAMING_ATTRS = ("stdout", "stderr", "output", "chunk", "delta", "delta_content", "content", "message", "text")


class SessionStats(TypedDict):
    pending_tool_calls: int
    idle_task: asyncio.Task[None] | None
    total_input_tokens: int
    total_output_tokens: int
    total_cache_read_tokens: int
    total_cache_write_tokens: int
    turn_count: int
    total_tool_calls: int
    last_event_time: float
    event_count: int
    last_tool_activity_time: float


def _iter_streaming_chunks(event_obj: Any) -> list[tuple[str, str]]:
    """Extract text chunks from tool streaming/progress events."""
    data = getattr(event_obj, "data", None)
    if data is None:
        return []
    chunks: list[tuple[str, str]] = []
    for attr in _STREAMING_ATTRS:
        val = getattr(data, attr, None)
        if isinstance(val, str) and val:
            chunks.append((attr, val))
    return chunks


class _EventHandler:
    """Handles SDK session events, updating shared stats and output."""

    _MAX_STALE_IDLES = 2

    def __init__(
        self,
        done: asyncio.Event,
        output_lines: list[str],
        errors: list[str],
        stats: SessionStats,
        item_logger: Any | None,
        idle_timeout: float,
        hung_command_detector: HungCommandDetector,
        on_token_usage: Callable[[int, int], None] | None,
    ) -> None:
        self._done = done
        self._output_lines = output_lines
        self._errors = errors
        self._stats = stats
        self._item_logger = item_logger
        self._idle_timeout = idle_timeout
        self._hung = hung_command_detector
        self._on_token_usage = on_token_usage
        self._pending_tools: dict[str, dict[str, Any]] = {}
        self._received_deltas = False
        self._stale_idle_count = 0
        self._last_idle_pending: int | None = None
        self._rate_limit_detected = False

    @property
    def rate_limit_detected(self) -> bool:
        """True if the session ended due to a rate limit error."""
        return self._rate_limit_detected

    def reset_for_retry(
        self,
        done: asyncio.Event,
        output_lines: list[str],
        errors: list[str],
    ) -> None:
        """Reset handler state for a fallback retry attempt."""
        self._done = done
        self._output_lines = output_lines
        self._errors = errors
        self._rate_limit_detected = False
        self._received_deltas = False
        self._stale_idle_count = 0
        self._last_idle_pending = None
        self._pending_tools.clear()

    # -- public entry point --------------------------------------------------

    def __call__(self, event: Any) -> None:
        event_type = event.type.value if hasattr(event.type, 'value') else str(event.type)
        self._stats['event_count'] += 1
        self._stats['last_event_time'] = time.monotonic()

        handler = self._DISPATCH.get(event_type)
        if handler is not None:
            handler(self, event)
        elif event_type.startswith("tool."):
            self._on_tool_streaming(event)

    # -- per-event handlers ---------------------------------------------------

    def _on_message_delta(self, event: Any) -> None:
        self._received_deltas = True
        terminal_ui.ui.set_style("green")
        delta = None
        if hasattr(event, 'data'):
            delta = (getattr(event.data, 'delta_content', None)
                     or getattr(event.data, 'delta', None)
                     or getattr(event.data, 'content', None))
        if delta:
            print(delta, end="", flush=True)
            self._output_lines.append(delta)
            if self._item_logger:
                self._item_logger.log_copilot_output(delta)

    def _on_message(self, event: Any) -> None:
        terminal_ui.ui.set_style("green")
        content = getattr(event.data, 'content', None) if hasattr(event, 'data') else None
        tool_requests = getattr(event.data, 'tool_requests', None) if hasattr(event, 'data') else None
        if content and not self._received_deltas:
            print(content)
            self._output_lines.append(content)
            if self._item_logger:
                self._item_logger.log_copilot_output(content)
        self._received_deltas = False
        terminal_ui.ui.set_style(None)
        if tool_requests and len(tool_requests) > 0:
            print(f"\n[Copilot] Calling {len(tool_requests)} tool(s)...")

    def _on_tool_start(self, event: Any) -> None:
        terminal_ui.ui.set_style(None)
        if self._stats['idle_task'] and not self._stats['idle_task'].done():
            self._stats['idle_task'].cancel()
        self._stats['total_tool_calls'] += 1
        self._stats['pending_tool_calls'] += 1
        self._stats['last_tool_activity_time'] = time.monotonic()
        self._stale_idle_count = 0
        self._last_idle_pending = None
        if not hasattr(event, 'data'):
            return
        tool_name = getattr(event.data, 'tool_name', 'unknown')
        tool_args = getattr(event.data, 'arguments', {}) or {}
        args_str = str(tool_args)
        print(f"  🔧 {tool_name}({args_str})")
        self._output_lines.append(f"\n[Tool] {tool_name}({args_str})\n")
        if self._item_logger:
            self._item_logger.log_tool_call(tool_name, args_str)
        tool_id = getattr(event.data, 'tool_call_id', None) or id(event)
        self._pending_tools[str(tool_id)] = {'name': tool_name, 'args': tool_args}
        if tool_name == 'powershell':
            shell_id = tool_args.get('shellId')
            if shell_id:
                self._hung.record_powershell_start(shell_id)

    def _on_tool_complete(self, event: Any) -> None:
        terminal_ui.ui.set_style(None)
        self._stats['pending_tool_calls'] = max(0, self._stats['pending_tool_calls'] - 1)
        self._stats['last_tool_activity_time'] = time.monotonic()
        self._stale_idle_count = 0
        self._last_idle_pending = None
        if not hasattr(event, 'data'):
            return
        tool_name = getattr(event.data, 'tool_name', 'unknown')
        arguments = getattr(event.data, 'arguments', {})
        result = getattr(event.data, 'result', None)
        success = getattr(event.data, 'success', True)
        tool_id = getattr(event.data, 'tool_call_id', None)
        tool_info = self._pending_tools.pop(str(tool_id), {}) if tool_id else {}
        tool_args = tool_info.get('args', {})
        if not result:
            return
        result_content = getattr(result, 'content', str(result)) if hasattr(result, 'content') else str(result)
        status = "✅" if success else "❌"
        print(f"  {status} Result: {result_content}")
        self._output_lines.append(f"[Result] {result_content}\n")
        if self._item_logger:
            self._item_logger.log_tool_call(tool_name, '', result=result_content, success=success)
        self._check_hung_command(tool_name, tool_args, result_content)
        self._check_beads_creation(tool_name, tool_args or arguments, result_content, success)

    def _check_hung_command(self, tool_name: str, tool_args: dict[str, Any], result_content: str) -> None:
        if tool_name == 'read_powershell':
            shell_id = tool_args.get('shellId', '')
            delay = float(tool_args.get('delay', 30))
            is_hung, corrective_msg = self._hung.record_read_powershell(shell_id, delay, result_content)
            if is_hung and corrective_msg:
                print(f"\n{corrective_msg}")
                self._output_lines.append(f"\n{corrective_msg}\n")
                if self._item_logger:
                    self._item_logger.log_error(f"Hung command detected for shell {shell_id}")
        elif tool_name == 'stop_powershell':
            shell_id = tool_args.get('shellId', '')
            if shell_id:
                self._hung.record_stop_powershell(shell_id)

    @staticmethod
    def _check_beads_creation(tool_name: str, arguments: Any, result_content: str, success: bool) -> None:
        if success and str(tool_name).lower() == "powershell":
            cmd = extract_command(arguments)
            if is_beads_create(cmd):
                created = parse_created_items(result_content)
                record_items_created(created)

    def _on_tool_streaming(self, event: Any) -> None:
        stream_chunks = _iter_streaming_chunks(event)
        if not stream_chunks:
            return
        for source, text in stream_chunks:
            prefix = "[stderr] " if source == "stderr" else ""
            print(f"{prefix}{text}", end="" if text.endswith("\n") else "\n")
            self._output_lines.append(text)
            if self._item_logger:
                self._item_logger.log_copilot_output(text)

    def _on_usage(self, event: Any) -> None:
        terminal_ui.ui.set_style(None)
        if hasattr(event, 'data'):
            self._stats['total_input_tokens'] += getattr(event.data, 'input_tokens', 0) or 0
            self._stats['total_output_tokens'] += getattr(event.data, 'output_tokens', 0) or 0
            self._stats['total_cache_read_tokens'] += getattr(event.data, 'cache_read_tokens', 0) or 0
            self._stats['total_cache_write_tokens'] += getattr(event.data, 'cache_write_tokens', 0) or 0
            if self._on_token_usage is not None:
                self._on_token_usage(self._stats['total_input_tokens'], self._stats['total_output_tokens'])

    def _on_turn_end(self, _event: Any) -> None:
        self._stats['turn_count'] += 1
        logger.debug("Assistant turn ended (turn %d, pending=%d)",
                     self._stats['turn_count'], self._stats['pending_tool_calls'])
        self._stats['last_tool_activity_time'] = time.monotonic()

    def _on_session_idle(self, _event: Any) -> None:
        if self._stats['idle_task'] and not self._stats['idle_task'].done():
            self._stats['idle_task'].cancel()
        if self._stats['pending_tool_calls'] > 0:
            self._handle_stale_idle()
        else:
            self._schedule_idle_completion()

    def _handle_stale_idle(self) -> None:
        if self._last_idle_pending == self._stats['pending_tool_calls']:
            self._stale_idle_count += 1
        else:
            self._stale_idle_count = 1
            self._last_idle_pending = self._stats['pending_tool_calls']
        if self._stale_idle_count >= self._MAX_STALE_IDLES:
            print(f"\n[SDK] Session idle with {self._stats['pending_tool_calls']} stale pending tool(s) "
                  f"(idle x{self._stale_idle_count}) - forcing completion (process likely exited)")
            self._stats['pending_tool_calls'] = 0
            self._done.set()
        else:
            print(f"\n[SDK] Session idle but {self._stats['pending_tool_calls']} tool(s) still executing "
                  f"(stale idle {self._stale_idle_count}/{self._MAX_STALE_IDLES}) - continuing...")

    def _schedule_idle_completion(self) -> None:
        self._stale_idle_count = 0
        self._last_idle_pending = None
        logger.debug("Session idle with no pending tools - scheduling completion check")

        async def check_still_idle() -> None:
            try:
                await asyncio.sleep(self._idle_timeout)
                if not self._done.is_set() and self._stats['pending_tool_calls'] == 0:
                    print("[SDK] Session confirmed idle - processing complete")
                    self._done.set()
            except asyncio.CancelledError:
                pass

        self._stats['idle_task'] = asyncio.create_task(check_still_idle())

    def _on_session_end(self, _event: Any) -> None:
        print("[SDK] Agent signaled session complete")
        self._done.set()

    def _on_session_error(self, event: Any) -> None:
        error_msg = getattr(event.data, 'message', 'Unknown error') if hasattr(event, 'data') else 'Unknown error'
        print(f"\n[SDK] ERROR: {error_msg}")
        if self._item_logger:
            self._item_logger.log_error(error_msg)
        error_lower = error_msg.lower()
        if not self._rate_limit_detected and 'rate' in error_lower and 'limit' in error_lower:
            print(f"\n[SDK] Rate limit detected, will retry with {FALLBACK_MODEL}...")
            self._rate_limit_detected = True
            self._done.set()
            return
        self._errors.append(error_msg)
        self._done.set()

    _DISPATCH: dict[str, Callable[['_EventHandler', Any], None]] = {
        "assistant.message_delta": _on_message_delta,
        "assistant.message": _on_message,
        "tool.execution_start": _on_tool_start,
        "tool.execution_complete": _on_tool_complete,
        "assistant.usage": _on_usage,
        "assistant.turn_end": _on_turn_end,
        "session.idle": _on_session_idle,
        "session.end": _on_session_end,
        "session.error": _on_session_error,
    }


def create_event_handler(
    done: asyncio.Event,
    output_lines: list[str],
    errors: list[str],
    item_logger: Any | None = None,
    idle_timeout: float = 90.0,
    hung_command_detector: HungCommandDetector | None = None,
    on_token_usage: Callable[[int, int], None] | None = None,
) -> tuple['_EventHandler', SessionStats]:
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
    if hung_command_detector is None:
        config = get_config()
        hung_command_detector = HungCommandDetector(
            max_retries=DEFAULT_MAX_READ_RETRIES,
            cumulative_timeout=float(config.command_timeout),
        )

    stats: SessionStats = {
        'pending_tool_calls': 0,
        'idle_task': None,
        'total_input_tokens': 0,
        'total_output_tokens': 0,
        'total_cache_read_tokens': 0,
        'total_cache_write_tokens': 0,
        'turn_count': 0,
        'total_tool_calls': 0,
        'last_event_time': time.monotonic(),
        'event_count': 0,
        'last_tool_activity_time': 0.0,
    }

    handler = _EventHandler(
        done, output_lines, errors, stats, item_logger,
        idle_timeout, hung_command_detector, on_token_usage,
    )
    return handler, stats
