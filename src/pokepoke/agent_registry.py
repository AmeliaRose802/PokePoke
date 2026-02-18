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
            self._agents[agent_id] = {
                "agent_id": agent_id,
                "name": name,
                "iteration": iteration,
                "status": status,
                "model": current_model,
                "parent_agent_id": current_parent,
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

    def remove(self, agent_id: str) -> None:
        with self._lock:
            self._agents.pop(agent_id, None)

    def serialize_all(self) -> list[dict[str, Any]]:
        with self._lock:
            return [self._copy_agent(agent) for agent in self._agents.values()]

    def get_detail(self, agent_id: str) -> dict[str, Any] | None:
        with self._lock:
            agent = self._agents.get(agent_id)
            if agent is None:
                return None
            return self._copy_agent(agent)

    @staticmethod
    def _copy_agent(agent: dict[str, Any]) -> dict[str, Any]:
        return {
            "agent_id": agent.get("agent_id"),
            "name": agent.get("name"),
            "iteration": agent.get("iteration", 1),
            "status": agent.get("status", "running"),
            "model": agent.get("model"),
            "parent_agent_id": agent.get("parent_agent_id"),
            "recent_logs": list(agent.get("recent_logs", [])),
            "log_lines": list(agent.get("log_lines", [])),
            "started_at": agent.get("started_at"),
            "last_updated": agent.get("last_updated"),
            "last_log_at": agent.get("last_log_at"),
        }
