"""Agent registry utilities for desktop UI state."""

from __future__ import annotations

import dataclasses
import re
import threading
import time
from typing import Any


@dataclasses.dataclass
class AgentRecord:
    """Typed representation of a tracked agent."""

    agent_id: str
    base_agent_id: str
    card_id: str
    name: str
    iteration: int = 1
    status: str = "running"
    parent_card_id: str | None = None
    model: str | None = None
    parent_agent_id: str | None = None
    work_item_id: str | None = None
    work_item_title: str | None = None
    agent_prompt: str | None = None
    session_id: str | None = None
    agent_type: str | None = None
    modified_files: list[str] = dataclasses.field(default_factory=list)
    recent_logs: list[str] = dataclasses.field(default_factory=list)
    log_lines: list[str] = dataclasses.field(default_factory=list)
    started_at: float | None = None
    last_updated: float | None = None
    last_log_at: float | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    paused: bool = False
    is_history_entry: bool = False

    def to_dict(self, *, include_log_lines: bool = False) -> dict[str, Any]:
        """Serialize to a plain dict for the external API.

        *include_log_lines* controls whether the potentially large ``log_lines``
        list is included.  ``serialize_all()`` omits it to keep poll payloads
        small; ``get_detail()`` includes it.
        """
        result: dict[str, Any] = {
            "agent_id": self.agent_id,
            "base_agent_id": self.base_agent_id,
            "card_id": self.card_id,
            "parent_card_id": self.parent_card_id,
            "name": self.name,
            "iteration": self.iteration,
            "status": self.status,
            "model": self.model,
            "parent_agent_id": self.parent_agent_id,
            "work_item_id": self.work_item_id,
            "work_item_title": self.work_item_title,
            "agent_prompt": self.agent_prompt,
            "session_id": self.session_id,
            "agent_type": self.agent_type,
            "modified_files": list(self.modified_files),
            "recent_logs": list(self.recent_logs),
            "started_at": self.started_at,
            "last_updated": self.last_updated,
            "last_log_at": self.last_log_at,
            "paused": self.paused,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "is_history_entry": self.is_history_entry,
        }
        if include_log_lines:
            result["log_lines"] = list(self.log_lines)
        return result

    def copy(
        self,
        *,
        paused: bool | None = None,
        is_history: bool | None = None,
        include_log_lines: bool = True,
    ) -> AgentRecord:
        """Return a deep-enough copy with optional overrides."""
        return AgentRecord(
            agent_id=self.agent_id,
            base_agent_id=self.base_agent_id,
            card_id=self.card_id,
            parent_card_id=self.parent_card_id,
            name=self.name,
            iteration=self.iteration,
            status=self.status,
            model=self.model,
            parent_agent_id=self.parent_agent_id,
            work_item_id=self.work_item_id,
            work_item_title=self.work_item_title,
            agent_prompt=self.agent_prompt,
            session_id=self.session_id,
            agent_type=self.agent_type,
            modified_files=list(self.modified_files),
            recent_logs=list(self.recent_logs),
            log_lines=list(self.log_lines) if include_log_lines else [],
            started_at=self.started_at,
            last_updated=self.last_updated,
            last_log_at=self.last_log_at,
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
            paused=paused if paused is not None else self.paused,
            is_history_entry=is_history if is_history is not None else self.is_history_entry,
        )


class AgentRegistry:
    """Tracks running agents and their log buffers."""

    def __init__(
        self,
        lock: threading.RLock,
        preview_limit: int = 100,
        detail_limit: int | None = None,
    ) -> None:
        self._lock = lock
        self._agents: dict[str, AgentRecord] = {}
        self._agent_history: dict[str, list[AgentRecord]] = {}
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
        agent_prompt: str | None = None,
        session_id: str | None = None,
        modified_files: list[str] | None = None,
        agent_type: str | None = None,
        resume_in_place: bool = False,
    ) -> None:
        now = time.time()
        with self._lock:
            existing = self._agents.get(agent_id)
            is_retry_iteration = (
                existing is not None
                and iteration > existing.iteration
            )

            # Determine how to handle logs, card_id, and started_at
            if is_retry_iteration and resume_in_place:
                # In-place resume (e.g. timeout retry): keep logs, card, start time
                assert existing is not None
                recent_logs = list(existing.recent_logs)
                log_lines = list(existing.log_lines or recent_logs)
                existing_started_at = existing.started_at or now
            elif is_retry_iteration:
                assert existing is not None
                self._archive_attempt(agent_id, existing)
                recent_logs = []
                log_lines = []
                existing_started_at = now
            else:
                recent_logs = list(existing.recent_logs) if existing else []
                log_lines = (
                    list(existing.log_lines or recent_logs) if existing else []
                )
                existing_started_at = (existing.started_at or now) if existing else now

            current_model = model if model is not None else (existing.model if existing else None)
            current_parent = (
                parent_agent_id
                if parent_agent_id is not None
                else (existing.parent_agent_id if existing else None)
            )
            current_work_item_id = (
                work_item_id
                if work_item_id is not None
                else (existing.work_item_id if existing else None)
            )
            current_work_item_title = (
                work_item_title
                if work_item_title is not None
                else (existing.work_item_title if existing else None)
            )
            current_prompt = (
                agent_prompt
                if agent_prompt is not None
                else (existing.agent_prompt if existing else None)
            )
            current_session_id = (
                session_id
                if session_id is not None
                else (existing.session_id if existing else None)
            )
            current_modified_files = (
                modified_files
                if modified_files is not None
                else (existing.modified_files if existing else None)
            )
            current_agent_type = self._normalize_agent_type(agent_type) or (
                self._normalize_agent_type(existing.agent_type) if existing else None
            )

            # Card ID: keep existing for in-place resume or same-iteration update
            if is_retry_iteration and resume_in_place and existing:
                card_id = existing.card_id
            elif existing and not is_retry_iteration:
                card_id = existing.card_id
            else:
                card_id = self._build_card_id(agent_id, iteration)

            # Parent card ID: preserve existing for in-place resume
            if resume_in_place and existing:
                parent_card_id = existing.parent_card_id
            else:
                parent_card_id = None
                if current_parent:
                    parent_entry = self._agents.get(current_parent)
                    if parent_entry:
                        parent_card_id = parent_entry.card_id
                    else:
                        history = self._agent_history.get(current_parent) or []
                        if history:
                            parent_card_id = history[-1].card_id

            # Preserve last_log_at for in-place resume
            if is_retry_iteration and resume_in_place:
                last_log_at = existing.last_log_at if existing else None
            elif is_retry_iteration:
                last_log_at = None
            else:
                last_log_at = existing.last_log_at if existing else None

            self._agents[agent_id] = AgentRecord(
                agent_id=agent_id,
                base_agent_id=agent_id,
                card_id=card_id,
                parent_card_id=parent_card_id,
                name=name,
                iteration=iteration,
                status=status,
                model=current_model,
                parent_agent_id=current_parent,
                work_item_id=current_work_item_id,
                work_item_title=current_work_item_title,
                agent_prompt=current_prompt,
                session_id=current_session_id,
                modified_files=current_modified_files or [],
                agent_type=current_agent_type,
                recent_logs=recent_logs,
                log_lines=log_lines,
                started_at=existing_started_at,
                last_updated=now,
                last_log_at=last_log_at,
            )

    def update_token_usage(
        self,
        agent_id: str,
        input_tokens: int,
        output_tokens: int,
    ) -> None:
        """Update cumulative token usage for an agent."""
        with self._lock:
            agent = self._agents.get(agent_id)
            if agent is None:
                return
            agent.input_tokens = input_tokens
            agent.output_tokens = output_tokens

    def append_log(self, agent_id: str, line: str) -> None:
        with self._lock:
            agent = self._agents.get(agent_id)
            if agent is None:
                return
            agent.recent_logs.append(line)
            if len(agent.recent_logs) > self._preview_limit:
                agent.recent_logs = agent.recent_logs[-self._preview_limit :]
            agent.log_lines.append(line)
            if self._detail_limit is not None and len(agent.log_lines) > self._detail_limit:
                agent.log_lines = agent.log_lines[-self._detail_limit :]
            now = time.time()
            agent.last_log_at = now
            agent.last_updated = now

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
            agents: list[dict[str, Any]] = []
            for attempts in self._agent_history.values():
                for attempt in attempts:
                    agents.append(attempt.to_dict(include_log_lines=True))
            for agent in self._agents.values():
                agents.append(
                    agent.copy(paused=agent.agent_id in self._paused_agents)
                    .to_dict(include_log_lines=False)
                )
        agents.sort(
            key=lambda a: a.get("started_at") or 0.0,
            reverse=True,
        )
        return agents

    def get_detail(self, agent_id: str) -> dict[str, Any] | None:
        with self._lock:
            agent = self._agents.get(agent_id)
            if agent is None:
                for live_agent in self._agents.values():
                    if live_agent.card_id == agent_id:
                        return (
                            live_agent.copy(paused=live_agent.agent_id in self._paused_agents)
                            .to_dict(include_log_lines=True)
                        )
                for attempts in self._agent_history.values():
                    for attempt in attempts:
                        if attempt.card_id == agent_id or attempt.agent_id == agent_id:
                            return attempt.to_dict(include_log_lines=True)
                return None
            return (
                agent.copy(paused=agent_id in self._paused_agents)
                .to_dict(include_log_lines=True)
            )

    @staticmethod
    def _build_card_id(agent_id: str, iteration: int) -> str:
        safe_iteration = iteration if iteration > 0 else 1
        return f"{agent_id}::v{safe_iteration}"

    def _archive_attempt(self, agent_id: str, attempt: AgentRecord) -> None:
        """Persist a completed attempt so it remains visible after retries."""
        snapshot = attempt.copy(
            paused=agent_id in self._paused_agents,
            is_history=True,
            include_log_lines=True,
        )
        if snapshot.status == "running":
            snapshot.status = "failed"
        history = self._agent_history.setdefault(agent_id, [])
        history.append(snapshot)

    @staticmethod
    def _normalize_agent_type(agent_type: str | None) -> str | None:
        if not agent_type:
            return None
        normalized = re.sub(r"[^a-z0-9]+", "_", agent_type.strip().lower()).strip("_")
        return normalized or None

