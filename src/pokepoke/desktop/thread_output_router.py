"""Thread-local output routing for desktop UI."""
from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager

# Thread-local storage for per-thread output routing.
_thread_output = threading.local()


class ThreadOutputRouter:
    """Manages thread-local output routing for desktop UI.

    Provides context managers for routing output to different targets
    (orchestrator vs agent) and supports per-thread line buffering to
    prevent interleaving of output from parallel agents.
    """

    @staticmethod
    @contextmanager
    def orchestrator_output() -> Iterator[None]:
        """Route print output on this thread to orchestrator log."""
        prev = getattr(_thread_output, "target", None)
        _thread_output.target = "orchestrator"
        try:
            yield
        finally:
            _thread_output.target = prev

    @staticmethod
    @contextmanager
    def agent_output() -> Iterator[None]:
        """Route print output on this thread to agent log."""
        prev = getattr(_thread_output, "target", None)
        _thread_output.target = "agent"
        try:
            yield
        finally:
            _thread_output.target = prev

    @staticmethod
    @contextmanager
    def agent_output_for(agent_id: str) -> Iterator[None]:
        """Route print output on this thread to a specific agent's log buffer."""
        prev_agent_id = getattr(_thread_output, "agent_id", None)
        _thread_output.agent_id = agent_id
        try:
            yield
        finally:
            _thread_output.agent_id = prev_agent_id

    @staticmethod
    def get_thread_target() -> str | None:
        """Get the current thread's output target."""
        return getattr(_thread_output, "target", None)

    @staticmethod
    def get_thread_style() -> str | None:
        """Get the current thread's output style."""
        return getattr(_thread_output, "style", None)

    @staticmethod
    def get_thread_agent_id() -> str | None:
        """Get the current thread's agent ID."""
        return getattr(_thread_output, "agent_id", None)

    @staticmethod
    def get_thread_line_buffer() -> str:
        """Get the current thread's line buffer."""
        return getattr(_thread_output, "line_buffer", "")

    @staticmethod
    def set_thread_line_buffer(buffer: str) -> None:
        """Set the current thread's line buffer."""
        _thread_output.line_buffer = buffer

    @staticmethod
    def set_thread_style(style: str | None) -> None:
        """Set the current thread's output style."""
        _thread_output.style = style
