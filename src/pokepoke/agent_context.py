"""Per-thread agent context for parallel agent isolation.

With parallel agents (max_parallel_agents > 1), multiple threads run
concurrently.  Each thread needs its own agent identity for:

1. Beads assignment filtering — ``beads_management.py`` checks the agent
   name to avoid claiming items assigned to other agents.
2. Worktree naming — ``agent_runner.py`` generates unique IDs that include
   the agent name.
3. Logging context — ``RunLogger`` / ``ItemLogger`` can tag output per agent.

This module provides a thin wrapper around ``threading.local()`` so that
every call-site reads the *thread-local* agent name first, falling back to
the process-wide ``os.environ['AGENT_NAME']`` when running sequentially
(single-threaded).
"""

import os
import threading
from typing import Optional


_thread_local = threading.local()


def get_agent_name(default: str = "agent") -> str:
    """Return the agent name for the current thread.

    Resolution order:
        1. Thread-local value set via :func:`set_agent_name`
        2. ``os.environ['AGENT_NAME']``
        3. *default* (``"agent"``)

    Args:
        default: Fallback value when neither thread-local nor env var is set.

    Returns:
        The agent name string.
    """
    # 1. Thread-local
    name: Optional[str] = getattr(_thread_local, "agent_name", None)
    if name is not None:
        return name

    # 2. Process-global environment variable
    env_name = os.environ.get("AGENT_NAME")
    if env_name:
        return env_name

    # 3. Fallback
    return default


def set_agent_name(name: str) -> None:
    """Set the agent name for the current thread.

    This should be called at the start of each worker thread so that
    downstream code (beads, logging, worktree naming) uses the correct
    identity instead of the process-global ``os.environ`` value.

    Args:
        name: Agent name to associate with this thread.
    """
    _thread_local.agent_name = name


def clear_agent_name() -> None:
    """Remove the thread-local agent name.

    After this call, :func:`get_agent_name` will fall back to
    ``os.environ['AGENT_NAME']`` again.
    """
    _thread_local.agent_name = None
