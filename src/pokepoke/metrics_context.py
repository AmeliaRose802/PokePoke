"""Thread-local context for attributing metrics to an agent type, repo, and work item."""

from __future__ import annotations

import threading
import time
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


def get_current_repo_name(default: str = "") -> str:
    """Return the repo name set on the current thread, or *default*."""
    val = getattr(_thread_local, "repo_name", None)
    if isinstance(val, str) and val:
        return val
    return default


def set_current_repo_name(repo_name: str | None) -> None:
    """Set the repo name for the current thread."""
    _thread_local.repo_name = repo_name


def get_current_work_item_id(default: str = "") -> str:
    """Return the work-item ID set on the current thread, or *default*."""
    val = getattr(_thread_local, "work_item_id", None)
    if isinstance(val, str) and val:
        return val
    return default


def set_current_work_item_id(work_item_id: str | None) -> None:
    """Set the work-item ID for the current thread."""
    _thread_local.work_item_id = work_item_id


@contextmanager
def repo_context(repo_name: str) -> Iterator[None]:
    """Context manager that sets the current repo name for the duration."""
    prev = getattr(_thread_local, "repo_name", None)
    _thread_local.repo_name = repo_name
    try:
        yield
    finally:
        _thread_local.repo_name = prev


@contextmanager
def work_item_context(work_item_id: str) -> Iterator[None]:
    """Context manager that sets the current work-item ID for the duration."""
    prev = getattr(_thread_local, "work_item_id", None)
    _thread_local.work_item_id = work_item_id
    try:
        yield
    finally:
        _thread_local.work_item_id = prev


@contextmanager
def agent_type_context(agent_type: str) -> Iterator[None]:
    prev = getattr(_thread_local, "agent_type", None)
    _thread_local.agent_type = agent_type
    start = time.monotonic()
    try:
        yield
    finally:
        elapsed = time.monotonic() - start
        _thread_local.agent_type = prev
        # Record elapsed time on the live session stats (if any)
        from pokepoke.session_stats_registry import get_current_session_stats
        stats = get_current_session_stats()
        if stats is not None:
            stats.record_agent_elapsed_time(agent_type, elapsed)
