"""Agent registry methods for DesktopAPI.

Extracted to keep desktop_api.py under the line limit.
All methods hold _lock for the full duration of registry calls,
preventing TOCTOU races with window disposal.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pokepoke.stats.metrics_context import get_current_agent_type

if TYPE_CHECKING:
    from pokepoke.desktop.desktop_api import DesktopAPI


def push_agent_status(  # noqa: PLR0913
    self: DesktopAPI,
    agent_id: str,
    name: str,
    iteration: int = 1,
    status: str = "running",
    model: str | None = None,
    parent_agent_id: str | None = None,
    work_item_id: str | None = None,
    work_item_title: str | None = None,
    agent_prompt: str | None = None,
    modified_files: list[str] | None = None,
    agent_type: str | None = None,
    resume_in_place: bool = False,
) -> None:
    """Register or update a running agent."""
    resolved_type = agent_type or get_current_agent_type(default="")
    normalized_agent_type: str | None = resolved_type if resolved_type else None
    with self._lock:
        if self._window_disposed:
            return
        self._agent_registry.update_status(
            agent_id,
            name,
            iteration,
            status,
            model=model,
            parent_agent_id=parent_agent_id,
            work_item_id=work_item_id,
            work_item_title=work_item_title,
            agent_prompt=agent_prompt,
            session_id=self._current_session_id,
            modified_files=modified_files,
            agent_type=normalized_agent_type,
            resume_in_place=resume_in_place,
        )


def push_agent_log(self: DesktopAPI, agent_id: str, line: str) -> None:
    """Append a log line to an agent's recent log preview."""
    with self._lock:
        if self._window_disposed:
            return
        self._agent_registry.append_log(agent_id, line)


def push_agent_tokens(
    self: DesktopAPI,
    agent_id: str,
    input_tokens: int,
    output_tokens: int,
) -> None:
    """Update live token usage for an agent."""
    with self._lock:
        if self._window_disposed:
            return
        self._agent_registry.update_token_usage(
            agent_id, input_tokens, output_tokens,
        )


def remove_agent(self: DesktopAPI, agent_id: str) -> None:
    """Remove a finished agent from the tracked set."""
    with self._lock:
        if self._window_disposed:
            return
        self._agent_registry.remove(agent_id)


def get_agents(self: DesktopAPI) -> list[dict[str, Any]]:
    """Return the list of currently tracked agents."""
    with self._lock:
        return self._agent_registry.serialize_all()


def get_agent_detail(self: DesktopAPI, agent_id: str) -> dict[str, Any] | None:
    """Return a deep copy of a single agent's detail state."""
    with self._lock:
        return self._agent_registry.get_detail(agent_id)


def pause_agent(self: DesktopAPI, agent_id: str) -> dict[str, Any]:
    """Pause an agent, preventing future scheduling."""
    with self._lock:
        if self._window_disposed:
            return {"agent_id": agent_id, "paused": False}
        success = self._agent_registry.pause(agent_id)
    if success:
        self.push_log(f"⏸️  Agent {agent_id} paused", "orchestrator", "yellow")
    return {"agent_id": agent_id, "paused": success}


def resume_agent(self: DesktopAPI, agent_id: str) -> dict[str, Any]:
    """Resume a paused agent."""
    with self._lock:
        if self._window_disposed:
            return {"agent_id": agent_id, "resumed": False}
        success = self._agent_registry.resume(agent_id)
    if success:
        self.push_log(f"▶️  Agent {agent_id} resumed", "orchestrator")
    return {"agent_id": agent_id, "resumed": success}


def is_agent_paused(self: DesktopAPI, agent_id: str) -> bool:
    """Check if an agent is paused."""
    with self._lock:
        return self._agent_registry.is_paused(agent_id)


def has_active_child_agents(self: DesktopAPI, agent_id: str) -> bool:
    """Check if an agent has any active (running/pending) child agents."""
    with self._lock:
        if self._window_disposed:
            return False
        return self._agent_registry.has_active_children(agent_id)


def get_child_agent_activity_time(self: DesktopAPI, agent_id: str) -> float | None:
    """Get the most recent activity timestamp from any child agent.

    Returns the most recent last_log_at or last_updated timestamp
    from active children, or None if no active children exist.
    """
    with self._lock:
        if self._window_disposed:
            return None
        return self._agent_registry.get_most_recent_child_activity(agent_id)
