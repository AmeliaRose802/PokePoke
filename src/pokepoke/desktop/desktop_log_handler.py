"""Logging handler that routes log records to the desktop API."""
from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pokepoke.desktop.desktop_api import DesktopAPI

# Re-use the thread-local from desktop_ui (set by context managers there).
# Imported lazily to avoid circular imports at module level.
_thread_output: threading.local | None = None


def _get_thread_output() -> threading.local:
    global _thread_output
    if _thread_output is None:
        from pokepoke.desktop.desktop_ui import _thread_output as _to
        _thread_output = _to
    return _thread_output


class DesktopLogHandler(logging.Handler):
    """Logging handler that routes log records to the desktop API.

    When a thread has set ``_thread_output.agent_id`` (via
    :meth:`DesktopUI.agent_output_for`), output goes to the per-agent
    log buffer.  Otherwise it goes to the shared orchestrator/agent log
    stream — the same routing that ``_print_redirect`` provides for
    ``print()`` calls.
    """

    def __init__(self, api: DesktopAPI, target_buffer: str, buffer_lock: threading.Lock, get_style: Any) -> None:
        super().__init__()
        self._api = api
        self._target_buffer = target_buffer
        self._buffer_lock = buffer_lock
        self._get_style = get_style

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            # Strip surrogate characters that crash xdist worker serialization
            msg = msg.encode("utf-8", errors="replace").decode("utf-8")
            to = _get_thread_output()
            agent_id: str | None = getattr(to, "agent_id", None)
            if agent_id:
                line_buf: str = getattr(to, "log_line_buffer", "")
                line_buf += msg + "\n"
                while "\n" in line_buf:
                    line, line_buf = line_buf.split("\n", 1)
                    if line:
                        self._api.push_agent_log(agent_id, line)
                to.log_line_buffer = line_buf
            else:
                target: str = getattr(to, "target", None) or self._target_buffer
                style: str | None = getattr(to, "style", None)
                if style is None:
                    with self._buffer_lock:
                        style = self._get_style()
                self._api.push_log(msg, target, style)
        except Exception:
            self.handleError(record)
