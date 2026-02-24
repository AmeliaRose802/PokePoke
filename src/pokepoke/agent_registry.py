"""Agent registry utilities for desktop UI state."""

from __future__ import annotations

import re
import threading
import time
from typing import Any


class AgentRegistry:
    """Tracks running agents and their log buffers."""

    def __init__(
        self,
        lock: threading.RLock,
        preview_limit: int = 20,
        detail_limit: int | None = None,
    ) -> None:
        self._lock = lock
        self._agents: dict[str, dict[str, Any]] = {}
        self._agent_history: dict[str, list[dict[str, Any]]] = {}
        self._preview_limit = preview_limit
        self._detail_limit = detail_limit
        self._paused_agents: set[str] = set()

    def set_limits(self, preview_limit: int, detail_limit: int | None) -> None:
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
        agent_type: str | None = None,
    ) -> None:
        now = time.time()
        with self._lock:
            existing = self._agents.get(agent_id)
            is_retry_iteration = (
                existing is not None
                and iteration > existing.get("iteration", 1)
            )
            recent_logs: list[str] = list(existing["recent_logs"]) if existing else []
            log_lines: list[str] = (
                list(existing.get("log_lines", recent_logs)) if existing else []
            )
            if is_retry_iteration:
                # Snapshot the previous attempt so it remains visible as its own card.
                assert existing is not None  # guaranteed by is_retry_iteration check
                self._archive_attempt(agent_id, existing)
                recent_logs = []
                log_lines = []
                existing_started_at = now
            else:
                existing_started_at = existing.get("started_at", now) if existing else now

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
            current_agent_type = self._normalize_agent_type(agent_type) or (
                self._normalize_agent_type(existing.get("agent_type")) if existing else None
            )
            card_id = (
                existing.get("card_id")
                if existing and not is_retry_iteration
                else self._build_card_id(agent_id, iteration)
            )
            parent_card_id = None
            if current_parent:
                parent_entry = self._agents.get(current_parent)
                if parent_entry:
                    parent_card_id = parent_entry.get("card_id")
                else:
                    # Fall back to the most recent archived attempt if the parent has already finished.
                    history = self._agent_history.get(current_parent) or []
                    if history:
                        parent_card_id = history[-1].get("card_id")

            self._agents[agent_id] = {
                "agent_id": agent_id,
                 "base_agent_id": agent_id,
                 "card_id": card_id,
                 "parent_card_id": parent_card_id,
                "name": name,
                "iteration": iteration,
                "status": status,
                "model": current_model,
                "parent_agent_id": current_parent,
                "work_item_id": current_work_item_id,
                "work_item_title": current_work_item_title,
                "session_id": current_session_id,
                "modified_files": current_modified_files,
                "agent_type": current_agent_type,
                "recent_logs": recent_logs,
                "log_lines": log_lines,
                "started_at": existing_started_at,
                "last_updated": now,
                "last_log_at": None if is_retry_iteration else (existing.get("last_log_at") if existing else None),
            }

    def update_token_usage(
        self,
        agent_id: str,
        input_tokens: int,
        output_tokens: int,
        context_limit: int,
    ) -> None:
        """Update cumulative token usage for an agent."""
        with self._lock:
            agent = self._agents.get(agent_id)
            if agent is None:
                return
            agent["input_tokens"] = input_tokens
            agent["output_tokens"] = output_tokens
            agent["context_limit"] = context_limit

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
            if self._detail_limit is not None and len(detail_logs) > self._detail_limit:
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

    def clear(self) -> None:
        """Clear all agents, history, and paused state."""
        with self._lock:
            self._agents.clear()
            self._agent_history.clear()
            self._paused_agents.clear()

    def remove(self, agent_id: str) -> None:
        with self._lock:
            self._agents.pop(agent_id, None)
            self._paused_agents.discard(agent_id)

    def serialize_all(self) -> list[dict[str, Any]]:
        with self._lock:
            agents = []
            for attempts in self._agent_history.values():
                for attempt in attempts:
                    # Stored attempts are already sanitized copies, but copy again to avoid accidental mutation.
                    agents.append(dict(attempt))
            for agent in self._agents.values():
                agents.append(self._copy_agent(agent, agent.get("agent_id") in self._paused_agents))
        agents.sort(
            key=lambda agent: agent.get("started_at") or 0.0,
            reverse=True,
        )
        return agents

    def get_detail(self, agent_id: str) -> dict[str, Any] | None:
        with self._lock:
            agent = self._agents.get(agent_id)
            if agent is None:
                # Allow lookups by card_id for archived attempts or selected retries.
                for live_agent in self._agents.values():
                    if live_agent.get("card_id") == agent_id:
                        return self._copy_agent(
                            live_agent,
                            live_agent.get("agent_id") in self._paused_agents,
                        )
                for attempts in self._agent_history.values():
                    for attempt in attempts:
                        if attempt.get("card_id") == agent_id or attempt.get("agent_id") == agent_id:
                            return dict(attempt)
                return None
            return self._copy_agent(agent, agent_id in self._paused_agents)

    @staticmethod
    def _copy_agent(agent: dict[str, Any], paused: bool = False, *, is_history: bool = False) -> dict[str, Any]:
        return {
            "agent_id": agent.get("agent_id"),
             "base_agent_id": agent.get("base_agent_id", agent.get("agent_id")),
            "card_id": agent.get("card_id"),
            "parent_card_id": agent.get("parent_card_id"),
            "name": agent.get("name"),
            "iteration": agent.get("iteration", 1),
            "status": agent.get("status", "running"),
            "model": agent.get("model"),
            "parent_agent_id": agent.get("parent_agent_id"),
            "work_item_id": agent.get("work_item_id"),
            "work_item_title": agent.get("work_item_title"),
            "session_id": agent.get("session_id"),
            "agent_type": agent.get("agent_type"),
            "modified_files": list(agent.get("modified_files") or []),
            "recent_logs": list(agent.get("recent_logs", [])),
            "log_lines": list(agent.get("log_lines", [])),
            "started_at": agent.get("started_at"),
            "last_updated": agent.get("last_updated"),
            "last_log_at": agent.get("last_log_at"),
            "paused": paused,
            "input_tokens": agent.get("input_tokens", 0),
            "output_tokens": agent.get("output_tokens", 0),
            "context_limit": agent.get("context_limit", 0),
            "is_history_entry": is_history,
        }

    @staticmethod
    def _build_card_id(agent_id: str, iteration: int) -> str:
        safe_iteration = iteration if iteration > 0 else 1
        return f"{agent_id}::v{safe_iteration}"

    def _archive_attempt(self, agent_id: str, attempt: dict[str, Any]) -> None:
        """Persist a completed attempt so it remains visible after retries."""
        snapshot = self._copy_agent(
            attempt,
            paused=agent_id in self._paused_agents,
            is_history=True,
        )
        if snapshot.get("status") == "running":
            snapshot["status"] = "failed"
        history = self._agent_history.setdefault(agent_id, [])
        history.append(snapshot)

    @staticmethod
    def _normalize_agent_type(agent_type: str | None) -> str | None:
        if not agent_type:
            return None
        normalized = re.sub(r"[^a-z0-9]+", "_", agent_type.strip().lower()).strip("_")
        return normalized or None

