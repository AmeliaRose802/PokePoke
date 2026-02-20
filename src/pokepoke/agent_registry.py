"""Agent registry utilities for desktop UI state."""

from __future__ import annotations

import threading
import time
from typing import Any


class AgentRegistry:
    """Tracks running agents and their log buffers."""

    def __init__(
        self,
        lock: threading.RLock,
        preview_limit: int = 20,
        detail_limit: int = 200,
    ) -> None:
        self._lock = lock
        self._agents: dict[str, dict[str, Any]] = {}
        self._preview_limit = preview_limit
        self._detail_limit = detail_limit
        self._paused_agents: set[str] = set()

    def set_limits(self, preview_limit: int, detail_limit: int) -> None:
        with self._lock:
            self._preview_limit = preview_limit
            self._detail_limit = detail_limit

    def update_status(
        self,
        agent_id: str,
        name: str,
        iteration: int,
        status: str,
        model: str | None = None,
        parent_agent_id: str | None = None,
        work_item_id: str | None = None,
        work_item_title: str | None = None,
        session_id: str | None = None,
        modified_files: list[str] | None = None,
    ) -> None:
        now = time.time()
        with self._lock:
            existing = self._agents.get(agent_id)
            recent_logs: list[str] = list(existing["recent_logs"]) if existing else []
            log_lines: list[str] = (
                list(existing.get("log_lines", recent_logs)) if existing else []
            )
            current_model = model if model is not None else (existing.get("model") if existing else None)
            current_parent = (
                parent_agent_id
                if parent_agent_id is not None
                else (existing.get("parent_agent_id") if existing else None)
            )
            current_work_item_id = (
                work_item_id
                if work_item_id is not None
                else (existing.get("work_item_id") if existing else None)
            )
            current_work_item_title = (
                work_item_title
                if work_item_title is not None
                else (existing.get("work_item_title") if existing else None)
            )
            current_session_id = (
                session_id
                if session_id is not None
                else (existing.get("session_id") if existing else None)
            )
            current_modified_files = (
                modified_files
                if modified_files is not None
                else (existing.get("modified_files") if existing else None)
            )
            self._agents[agent_id] = {
                "agent_id": agent_id,
                "name": name,
                "iteration": iteration,
                "status": status,
                "model": current_model,
                "parent_agent_id": current_parent,
                "work_item_id": current_work_item_id,
                "work_item_title": current_work_item_title,
                "session_id": current_session_id,
                "modified_files": current_modified_files,
                "recent_logs": recent_logs,
                "log_lines": log_lines,
                "started_at": existing.get("started_at", now) if existing else now,
                "last_updated": now,
                "last_log_at": existing.get("last_log_at") if existing else None,
            }

    def append_log(self, agent_id: str, line: str) -> None:
        with self._lock:
            agent = self._agents.get(agent_id)
            if agent is None:
                return
            logs = list(agent.get("recent_logs", []))
            logs.append(line)
            if len(logs) > self._preview_limit:
                logs = logs[-self._preview_limit :]
            detail_logs = list(agent.get("log_lines", []))
            detail_logs.append(line)
            if len(detail_logs) > self._detail_limit:
                detail_logs = detail_logs[-self._detail_limit :]
            now = time.time()
            agent.update(
                {
                    "recent_logs": logs,
                    "log_lines": detail_logs,
                    "last_log_at": now,
                    "last_updated": now,
                }
            )

    def pause(self, agent_id: str) -> bool:
        """Mark an agent as paused. Returns True if the agent exists."""
        with self._lock:
            if agent_id not in self._agents:
                return False
            self._paused_agents.add(agent_id)
            return True

    def resume(self, agent_id: str) -> bool:
        """Mark an agent as resumed. Returns True if the agent was paused."""
        with self._lock:
            if agent_id in self._paused_agents:
                self._paused_agents.discard(agent_id)
                return True
            return False

    def is_paused(self, agent_id: str) -> bool:
        """Check if an agent is paused."""
        with self._lock:
            return agent_id in self._paused_agents

    def remove(self, agent_id: str) -> None:
        with self._lock:
            self._agents.pop(agent_id, None)
            self._paused_agents.discard(agent_id)

    def serialize_all(self) -> list[dict[str, Any]]:
        with self._lock:
            agents = [self._copy_agent(agent, agent.get("agent_id") in self._paused_agents) for agent in self._agents.values()]
        agents.sort(
            key=lambda agent: agent.get("last_updated")
            or agent.get("last_log_at")
            or agent.get("started_at")
            or 0.0,
            reverse=True,
        )
        return agents

    def get_detail(self, agent_id: str) -> dict[str, Any] | None:
        with self._lock:
            agent = self._agents.get(agent_id)
            if agent is None:
                return None
            return self._copy_agent(agent, agent_id in self._paused_agents)

    @staticmethod
    def _copy_agent(agent: dict[str, Any], paused: bool = False) -> dict[str, Any]:
        return {
            "agent_id": agent.get("agent_id"),
            "name": agent.get("name"),
            "iteration": agent.get("iteration", 1),
            "status": agent.get("status", "running"),
            "model": agent.get("model"),
            "parent_agent_id": agent.get("parent_agent_id"),
            "work_item_id": agent.get("work_item_id"),
            "work_item_title": agent.get("work_item_title"),
            "session_id": agent.get("session_id"),
            "modified_files": list(agent.get("modified_files") or []),
            "recent_logs": list(agent.get("recent_logs", [])),
            "log_lines": list(agent.get("log_lines", [])),
            "started_at": agent.get("started_at"),
            "last_updated": agent.get("last_updated"),
            "last_log_at": agent.get("last_log_at"),
            "paused": paused,
        }

    def register_historical_agent(self, agent_state: dict[str, Any]) -> None:
        """Insert a pre-existing agent (loaded from disk) into the registry."""
        agent_id = agent_state.get("agent_id")
        if not agent_id:
            raise ValueError("agent_state must include agent_id")

        recent_logs = list(agent_state.get("recent_logs", []))
        log_lines = list(agent_state.get("log_lines", recent_logs))

        if len(recent_logs) > self._preview_limit:
            recent_logs = recent_logs[-self._preview_limit :]
        if len(log_lines) > self._detail_limit:
            log_lines = log_lines[-self._detail_limit :]

        sanitized = {
            "agent_id": agent_id,
            "name": agent_state.get("name") or agent_id,
            "iteration": agent_state.get("iteration", 1) or 1,
            "status": agent_state.get("status", "success"),
            "model": agent_state.get("model"),
            "parent_agent_id": agent_state.get("parent_agent_id"),
            "work_item_id": agent_state.get("work_item_id"),
            "work_item_title": agent_state.get("work_item_title"),
            "recent_logs": recent_logs,
            "log_lines": log_lines,
            "started_at": agent_state.get("started_at"),
            "last_updated": agent_state.get("last_updated") or agent_state.get("started_at"),
            "last_log_at": agent_state.get("last_log_at") or agent_state.get("last_updated"),
        }

        with self._lock:
            if agent_id not in self._agents:
                self._agents[agent_id] = sanitized
