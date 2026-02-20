"""Thread-local context for attributing metrics to an agent type."""

from __future__ import annotations

import threading
from contextlib import contextmanager
from collections.abc import Iterator


_thread_local = threading.local()


def get_current_agent_type(default: str = "unknown") -> str:
    val = getattr(_thread_local, "agent_type", None)
    if isinstance(val, str) and val:
        return val
    return default


def set_current_agent_type(agent_type: str | None) -> None:
    _thread_local.agent_type = agent_type


@contextmanager
def agent_type_context(agent_type: str) -> Iterator[None]:
    prev = getattr(_thread_local, "agent_type", None)
    _thread_local.agent_type = agent_type
    try:
        yield
    finally:
        _thread_local.agent_type = prev
