"""Tests for DesktopLogHandler."""

import logging
import threading
from unittest.mock import MagicMock

import pokepoke.desktop.desktop_log_handler as handler_module
from pokepoke.desktop.desktop_log_handler import DesktopLogHandler


class TestDesktopLogHandler:
    def _make_handler(self):
        api = MagicMock()
        lock = threading.Lock()
        style_val = None
        handler = DesktopLogHandler(api, "orchestrator", lock, lambda: style_val)
        handler.setLevel(logging.DEBUG)
        return handler, api, lambda v: None  # style setter placeholder

    def test_emit_routes_to_push_log_without_agent_id(self):
        handler, api, _ = self._make_handler()
        # Ensure no agent_id on thread-local
        to = handler_module._get_thread_output()
        to.agent_id = None
        to.target = None
        to.style = None

        record = logging.LogRecord(
            "pokepoke.test", logging.INFO, "", 0, "hello world", (), None,
        )
        handler.emit(record)
        api.push_log.assert_called_once_with("hello world", "orchestrator", None)

    def test_emit_routes_to_push_agent_log_with_agent_id(self):
        handler, api, _ = self._make_handler()
        to = handler_module._get_thread_output()
        to.agent_id = "agent-1"
        to.log_line_buffer = ""

        try:
            record = logging.LogRecord(
                "pokepoke.test", logging.INFO, "", 0, "agent output", (), None,
            )
            handler.emit(record)
            api.push_agent_log.assert_called_once_with("agent-1", "agent output")
        finally:
            to.agent_id = None

    def test_emit_uses_thread_target_and_style(self):
        handler, api, _ = self._make_handler()
        to = handler_module._get_thread_output()
        to.agent_id = None
        to.target = "agent"
        to.style = "green"

        try:
            record = logging.LogRecord(
                "pokepoke.test", logging.INFO, "", 0, "styled msg", (), None,
            )
            handler.emit(record)
            api.push_log.assert_called_once_with("styled msg", "agent", "green")
        finally:
            to.target = None
            to.style = None

    def test_emit_handles_exception_gracefully(self):
        handler, api, _ = self._make_handler()
        to = handler_module._get_thread_output()
        to.agent_id = None
        api.push_log.side_effect = RuntimeError("boom")

        record = logging.LogRecord(
            "pokepoke.test", logging.INFO, "", 0, "will fail", (), None,
        )
        # Should not raise
        handler.emit(record)
