"""Child agent tracking utilities for parent-child agent relationships."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pokepoke.agents.agent_registry import AgentRecord


class ChildAgentTracker:
    """Tracks parent-child relationships between agents."""

    def __init__(self) -> None:
        self._parent_to_children: dict[str, set[str]] = {}

    def add_child(self, parent_id: str, child_id: str) -> None:
        """Register a child agent under a parent."""
        if parent_id not in self._parent_to_children:
            self._parent_to_children[parent_id] = set()
        self._parent_to_children[parent_id].add(child_id)

    def remove_child(self, parent_id: str, child_id: str) -> None:
        """Remove a child from a parent's tracking."""
        if parent_id in self._parent_to_children:
            self._parent_to_children[parent_id].discard(child_id)
            if not self._parent_to_children[parent_id]:
                del self._parent_to_children[parent_id]

    def remove_parent(self, parent_id: str) -> None:
        """Remove all tracking for a parent agent."""
        if parent_id in self._parent_to_children:
            del self._parent_to_children[parent_id]

    def clear(self) -> None:
        """Clear all parent-child tracking."""
        self._parent_to_children.clear()

    def has_active_children(
        self, parent_id: str, agents: dict[str, AgentRecord]
    ) -> bool:
        """Check if a parent has any active (running/pending) child agents."""
        child_ids = self._parent_to_children.get(parent_id, set())
        if not child_ids:
            return False
        for child_id in child_ids:
            child = agents.get(child_id)
            if child and child.status in ("running", "pending"):
                return True
        return False

    def get_active_children(
        self, parent_id: str, agents: dict[str, AgentRecord]
    ) -> list[str]:
        """Get list of active child agent IDs for a given parent."""
        child_ids = self._parent_to_children.get(parent_id, set())
        active = []
        for child_id in child_ids:
            child = agents.get(child_id)
            if child and child.status in ("running", "pending"):
                active.append(child_id)
        return active

    def get_most_recent_child_activity(
        self, parent_id: str, agents: dict[str, AgentRecord]
    ) -> float | None:
        """Get the most recent activity timestamp from any child agent.

        Returns the most recent last_log_at or last_updated timestamp
        from active children, or None if no active children exist.
        """
        child_ids = self._parent_to_children.get(parent_id, set())
        if not child_ids:
            return None

        most_recent = None
        for child_id in child_ids:
            child = agents.get(child_id)
            if not (child and child.status in ("running", "pending")):
                continue
            # Prefer last_log_at (indicates actual output) over last_updated
            child_time = child.last_log_at or child.last_updated
            if child_time and (most_recent is None or child_time > most_recent):
                most_recent = child_time
        return most_recent
