"""Event handler utilities for SDK client sessions."""

import asyncio
import logging
import threading
import time
from collections.abc import Callable
from typing import Any, TypedDict

from pokepoke.beads.sdk_beads_tracker import extract_command, is_beads_create, parse_created_items, record_items_created
from pokepoke.config import FALLBACK_MODEL, get_config
from pokepoke.desktop import terminal_ui
from pokepoke.utils.hung_command_detector import HungCommandDetector

from .sdk_event_handler_utils import iter_streaming_chunks, record_tool_output

logger = logging.getLogger(__name__)

class RateLimitError(Exception):
    """Raised when the SDK session hits a rate limit."""

    def __init__(self, message: str = "Rate limit exceeded") -> None:
        super().__init__(message)

DEFAULT_MAX_READ_RETRIES = 3

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
    last_tool_output_time: float
    last_tool_output: str | None
    tool_start_times: dict[str, float]

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
        self._pending_tools_lock = threading.Lock()
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
        with self._pending_tools_lock:
            self._pending_tools.clear()
            self._stats['tool_start_times'].clear()
            self._stats['pending_tool_calls'] = 0
        self._stats['last_tool_output_time'] = 0.0
        self._stats['last_tool_output'] = None

    def __call__(self, event: Any) -> None:
        event_type = event.type.value if hasattr(event.type, 'value') else str(event.type)
        now = time.monotonic()
        gap = now - self._stats['last_event_time']
        self._stats['event_count'] += 1
        self._stats['last_event_time'] = now

        if gap > 30:
            logger.info("SDK event '%s' after %.1fs silence (events=%d, pending=%d, turns=%d)",
                        event_type, gap, self._stats['event_count'],
                        self._stats['pending_tool_calls'], self._stats['turn_count'])

        handler = self._DISPATCH.get(event_type)
        if handler is not None:
            handler(self, event)
        elif event_type.startswith("tool."):
            self._on_tool_streaming(event)
        else:
            logger.debug("Unhandled SDK event: %s", event_type)

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
            logger.info(delta)
            self._output_lines.append(delta)
            if self._item_logger:
                self._item_logger.log_copilot_output(delta)

    def _on_message(self, event: Any) -> None:
        terminal_ui.ui.set_style("green")
        content = getattr(event.data, 'content', None) if hasattr(event, 'data') else None
        tool_requests = getattr(event.data, 'tool_requests', None) if hasattr(event, 'data') else None
        if content and not self._received_deltas:
            logger.info(content)
            self._output_lines.append(content)
            if self._item_logger:
                self._item_logger.log_copilot_output(content)
        self._received_deltas = False
        terminal_ui.ui.set_style(None)
        if tool_requests and len(tool_requests) > 0:
            logger.info(f"\n[Copilot] Calling {len(tool_requests)} tool(s)...")

    def _on_tool_start(self, event: Any) -> None:
        terminal_ui.ui.set_style(None)
        if self._stats['idle_task'] and not self._stats['idle_task'].done():
            self._stats['idle_task'].cancel()
        self._stats['total_tool_calls'] += 1
        self._stats['last_tool_activity_time'] = time.monotonic()
        self._stale_idle_count = 0
        self._last_idle_pending = None
        if not hasattr(event, 'data'):
            return
        tool_name = getattr(event.data, 'tool_name', 'unknown')
        tool_args = getattr(event.data, 'arguments', {}) or {}
        args_str = str(tool_args)
        logger.info(f"  🔧 {tool_name}({args_str})")
        self._output_lines.append(f"\n[Tool] {tool_name}({args_str})\n")
        if self._item_logger:
            self._item_logger.log_tool_call(tool_name, args_str)
        tool_id = getattr(event.data, 'tool_call_id', None) or id(event)
        with self._pending_tools_lock:
            self._pending_tools[str(tool_id)] = {'name': tool_name, 'args': tool_args}
            self._stats['tool_start_times'][str(tool_id)] = time.monotonic()
            self._stats['pending_tool_calls'] += 1
        if tool_name == 'powershell':
            shell_id = tool_args.get('shellId')
            if shell_id:
                self._hung.record_powershell_start(shell_id)

    def _on_tool_complete(self, event: Any) -> None:
        terminal_ui.ui.set_style(None)
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
        with self._pending_tools_lock:
            tool_info = self._pending_tools.pop(str(tool_id), {}) if tool_id else {}
            start_time = self._stats['tool_start_times'].pop(str(tool_id), None)
            self._stats['pending_tool_calls'] = max(0, self._stats['pending_tool_calls'] - 1)
        tool_args = tool_info.get('args', {})

        if start_time is not None:
            latency = time.monotonic() - start_time
            if latency >= 10.0:
                logger.info("TOOL_LATENCY: %s latency=%.1fs success=%s args=%s",
                            tool_name, latency, success, str(tool_args)[:200])

        if not result:
            return
        result_content = getattr(result, 'content', str(result)) if hasattr(result, 'content') else str(result)
        status = "✅" if success else "❌"
        logger.info(f"  {status} Result: {result_content}")
        self._output_lines.append(f"[Result] {result_content}\n")
        if self._item_logger:
            self._item_logger.log_tool_call(tool_name, '', result=result_content, success=success)
        record_tool_output(self._stats, result_content)
        self._check_hung_command(tool_name, tool_args, result_content)
        self._check_beads_creation(tool_name, tool_args or arguments, result_content, success)

    def _check_hung_command(self, tool_name: str, tool_args: dict[str, Any], result_content: str) -> None:
        if tool_name == 'read_powershell':
            shell_id = tool_args.get('shellId', '')
            delay = float(tool_args.get('delay', 30))
            is_hung, corrective_msg = self._hung.record_read_powershell(shell_id, delay, result_content)
            if is_hung and corrective_msg:
                logger.info(f"\n{corrective_msg}")
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
        stream_chunks = iter_streaming_chunks(event)
        if not stream_chunks:
            return
        for source, text in stream_chunks:
            prefix = "[stderr] " if source == "stderr" else ""
            logger.info(f"{prefix}{text}")
            self._output_lines.append(text)
            if self._item_logger:
                self._item_logger.log_copilot_output(text)
            record_tool_output(self._stats, text)

    def _on_usage(self, event: Any) -> None:
        terminal_ui.ui.set_style(None)
        if hasattr(event, 'data'):
            self._stats['total_input_tokens'] += getattr(event.data, 'input_tokens', 0) or 0
            self._stats['total_output_tokens'] += getattr(event.data, 'output_tokens', 0) or 0
            self._stats['total_cache_read_tokens'] += getattr(event.data, 'cache_read_tokens', 0) or 0
            self._stats['total_cache_write_tokens'] += getattr(event.data, 'cache_write_tokens', 0) or 0
            if self._on_token_usage is not None:
                self._on_token_usage(self._stats['total_input_tokens'], self._stats['total_output_tokens'])

    def _on_turn_start(self, _event: Any) -> None:
        self._stats['last_tool_activity_time'] = time.monotonic()
        logger.info("Turn %d started (pending=%d)", self._stats['turn_count'] + 1, self._stats['pending_tool_calls'])

    def _on_turn_end(self, _event: Any) -> None:
        self._stats['turn_count'] += 1
        self._stats['last_tool_activity_time'] = time.monotonic()
        logger.info("Turn %d ended (pending=%d)", self._stats['turn_count'], self._stats['pending_tool_calls'])

    def _on_context_reduction(self, _event: Any) -> None:
        logger.warning("Session context reduction (events=%d, in=%d tok)",
                       self._stats['event_count'], self._stats['total_input_tokens'])

    def _on_model_change(self, event: Any) -> None:
        model = getattr(event.data, 'model', None) if hasattr(event, 'data') else None
        logger.warning("Model changed to: %s", model)

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
            logger.warning("[SDK] Session idle with %d stale pending tool(s) (idle x%d) - forcing completion",
                          self._stats['pending_tool_calls'], self._stale_idle_count)
            with self._pending_tools_lock:
                self._stats['pending_tool_calls'] = 0
            self._done.set()
        else:
            logger.info("[SDK] Session idle but %d tool(s) still executing (stale %d/%d) - continuing...",
                       self._stats['pending_tool_calls'], self._stale_idle_count, self._MAX_STALE_IDLES)

    def _schedule_idle_completion(self) -> None:
        self._stale_idle_count = 0
        self._last_idle_pending = None
        logger.debug("Session idle with no pending tools - scheduling completion check")

        async def check_still_idle() -> None:
            try:
                await asyncio.sleep(self._idle_timeout)
                if not self._done.is_set() and self._stats['pending_tool_calls'] == 0:
                    logger.info("[SDK] Session confirmed idle - processing complete")
                    self._done.set()
            except asyncio.CancelledError:
                pass  # task cancelled during idle check — expected on shutdown

        self._stats['idle_task'] = asyncio.create_task(check_still_idle())

    def _on_noop(self, _event: Any) -> None:
        """Silently ignore informational SDK events that need no processing."""

    def _on_session_end(self, _event: Any) -> None:
        logger.info("[SDK] Agent signaled session complete")
        self._done.set()

    def _on_session_error(self, event: Any) -> None:
        error_msg = getattr(event.data, 'message', 'Unknown error') if hasattr(event, 'data') else 'Unknown error'
        logger.error(f"\n[SDK] ERROR: {error_msg}")
        if self._item_logger:
            self._item_logger.log_error(error_msg)
        error_lower = error_msg.lower()
        if not self._rate_limit_detected and 'rate' in error_lower and 'limit' in error_lower:
            logger.info(f"\n[SDK] Rate limit detected, will retry with {FALLBACK_MODEL}...")
            self._rate_limit_detected = True
            self._done.set()
            return
        self._errors.append(error_msg)
        self._done.set()

    _DISPATCH: dict[str, Callable[['_EventHandler', Any], None]] = {
        "assistant.message_delta": _on_message_delta,
        "assistant.streaming_delta": _on_message_delta,
        "assistant.message": _on_message,
        "assistant.turn_start": _on_turn_start,
        "assistant.turn_end": _on_turn_end,
        "assistant.usage": _on_usage,
        "assistant.reasoning_delta": _on_noop,
        "tool.execution_start": _on_tool_start,
        "tool.execution_complete": _on_tool_complete,
        "session.idle": _on_session_idle,
        "session.end": _on_session_end,
        "session.error": _on_session_error,
        "session.compaction_start": _on_context_reduction,
        "session.compaction_complete": _on_context_reduction,
        "session.truncation": _on_context_reduction,
        "session.model_change": _on_model_change,
        "session.usage_info": _on_usage,
        "pending_messages.modified": _on_noop,
        "permission.completed": _on_noop,
        "unknown": _on_noop,
        "user.message": _on_noop,
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
    """Create an event handler and stats dict for SDK session events."""
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
        'last_tool_output_time': 0.0,
        'last_tool_output': None,
        'tool_start_times': {},
    }

    handler = _EventHandler(
        done, output_lines, errors, stats, item_logger,
        idle_timeout, hung_command_detector, on_token_usage,
    )
    return handler, stats
