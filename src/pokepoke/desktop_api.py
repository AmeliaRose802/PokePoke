"""Python API exposed to the desktop frontend via pywebview.

Every public method on DesktopAPI is callable from JavaScript as:
    await window.pywebview.api.method_name(args)
"""
from __future__ import annotations

import threading
import time
from typing import Any, TYPE_CHECKING

from pokepoke.agent_registry import AgentRegistry
from pokepoke.metrics_context import get_current_agent_type
from pokepoke.repo_utils import get_repository_name

from pokepoke.shutdown import (
    request_stop_after_current as _request_stop_after_current,
    cancel_stop_after_current as _cancel_stop_after_current,
    should_stop_after_current as _should_stop_after_current,
)

from pokepoke import desktop_api_ext as _ext
from pokepoke import desktop_api_stats as _stats
from pokepoke import desktop_api_setup as _setup

if TYPE_CHECKING:
    from pokepoke.types import SessionStats


class DesktopAPI:
    """API surface exposed to the pywebview frontend.

    pywebview exposes every public method to JavaScript automatically.
    Methods run on a background thread — they won't block the UI.
    """

    def __init__(self) -> None:
        self._window: Any | None = None
        self._lock = threading.RLock()
        self._window_disposed = False

        # Buffered state — frontend can poll or get pushed updates
        self._log_buffer: list[dict[str, Any]] = []
        self._max_log_buffer = 2000
        self._current_work_item: dict[str, Any] | None = None
        self._current_agent_name: str = ""
        self._current_stats: dict[str, Any] | None = None
        self._current_progress: dict[str, Any] = {"active": False, "status": ""}
        self._repository_name: str = ""
        self._current_logs_dir: str | None = None

        # Session start time for dynamic elapsed_time computation
        self._session_start_time: float | None = None
        # Session end time to freeze the clock when agents complete
        self._session_end_time: float | None = None
        # Current session identifier for grouping agents
        self._current_session_id: str | None = None

        # Live reference to SessionStats — serialized fresh on each poll
        # so agent run counts, token stats, etc. update in real-time
        self._live_session_stats: SessionStats | None = None

        # Read index for incremental log fetching
        self._log_read_index: int = 0

        # Leaderboard cache for model performance stats
        self._leaderboard_cache: dict[str, Any] = {}
        self._leaderboard_cache_time: float = 0.0
        self._history_cache: list[dict[str, Any]] = []
        self._history_cache_limit: int = 200
        self._history_cache_time: float = 0.0

        # Running agents — keyed by agent_id
        self._agent_max_log_lines_internal = 20
        self._agent_detail_max_log_lines_internal: int | None = 500
        self._agent_registry = AgentRegistry(
            self._lock,
            preview_limit=self._agent_max_log_lines_internal,
            detail_limit=self._agent_detail_max_log_lines_internal,
        )
        _ext.seed_historical_agents(self)

        # Extract repository name at initialization
        self._repository_name = get_repository_name()

        # Setup wizard gating — orchestrator can wait for the UI to complete
        # first-time project initialization steps.
        self._setup_complete_event = threading.Event()

    def set_window(self, window: Any) -> None:
        """Called once after pywebview creates the window."""
        self._window = window

    def dispose(self) -> None:
        """Mark window as disposed to prevent ObjectDisposedException spam during teardown."""
        with self._lock:
            self._window_disposed = True
            self._window = None

    # Stats serialization — delegated to desktop_api_stats
    _snapshot_to_dict = staticmethod(_stats.snapshot_to_dict)
    _serialize_live_stats = _stats.serialize_live_stats
    _get_cached_leaderboard = _stats.get_cached_leaderboard
    get_model_leaderboard = _stats.get_model_leaderboard
    get_model_history = _stats.get_model_history
    push_stats = _stats.push_stats

    def get_state(self) -> dict[str, Any]:
        """Get the full current state snapshot. Called on frontend init."""
        from pokepoke.config import get_config

        with self._lock:
            config = get_config()
            return {
                "work_item": self._current_work_item,
                "agent_name": self._current_agent_name,
                "repository_name": self._repository_name,
                "stats": self._serialize_live_stats(),
                "progress": self._current_progress,
                "log_count": len(self._log_buffer),
                "model_leaderboard": self._get_cached_leaderboard(),
                "agents": self._agent_registry.serialize_all(),
                "stop_after_current": _should_stop_after_current(),
                "project_name": config.project_name,
                "current_session_id": self._current_session_id,
                "logs_dir": self._current_logs_dir,
            }

    def get_new_logs(self) -> list[dict[str, Any]]:
        """Get log entries added since the last call (incremental).

        The frontend polls this on a timer instead of receiving pushes,
        which avoids the complexity of evaluate_js and thread-safety
        issues with pywebview.
        """
        with self._lock:
            if self._log_read_index >= len(self._log_buffer):
                return []
            new_logs = self._log_buffer[self._log_read_index:]
            self._log_read_index = len(self._log_buffer)
            return new_logs
    def get_all_logs(self) -> list[dict[str, Any]]:
        """Get all buffered logs (for reconnect / initial load)."""
        with self._lock:
            self._log_read_index = len(self._log_buffer)
            return list(self._log_buffer)
    def get_work_item(self) -> dict[str, Any] | None:
        """Get the current work item."""
        with self._lock:
            return self._current_work_item

    def get_repository_name(self) -> str:
        """Get the repository name."""
        return self._repository_name

    def get_stats(self) -> dict[str, Any] | None:
        """Get the current session stats."""
        with self._lock:
            return self._serialize_live_stats()

    get_config = _ext.get_config
    save_config = _ext.save_config

    # ─── Python → State: Called by the orchestrator ───────────────────
    def push_log(
        self, message: str, target: str = "orchestrator", style: str | None = None
    ) -> None:
        """Add a log entry to the buffer."""
        with self._lock:
            if self._window_disposed:  # Silently ignore after window disposal
                return

            entry = {
                "message": message,
                "target": target,
                "style": style,
                "timestamp": time.time(),
            }
            self._log_buffer.append(entry)
            if len(self._log_buffer) > self._max_log_buffer:
                trim = len(self._log_buffer) - self._max_log_buffer
                self._log_buffer = self._log_buffer[trim:]
                self._log_read_index = max(0, self._log_read_index - trim)

    def push_work_item(
        self,
        item_id: str,
        title: str,
        status: str = "",
        labels: list[str] | None = None,
    ) -> None:
        """Update the current work item."""
        with self._lock:
            self._current_work_item = {
                "item_id": item_id,
                "title": title,
                "status": status,
                "labels": list(labels) if labels is not None else [],
            }

    def set_session_start_time(self, start_time: float) -> None:
        """Store session start time (enables live elapsed_time ticking)."""
        with self._lock:
            self._session_start_time = start_time
            self._current_session_id = str(start_time)

    def set_session_end_time(self, end_time: float) -> None:
        """Store session end time (freezes elapsed_time)."""
        with self._lock:
            self._session_end_time = end_time

    def set_live_session_stats(self, session_stats: SessionStats) -> None:
        """Store a live SessionStats reference for real-time polling."""
        with self._lock:
            self._live_session_stats = session_stats

    def push_agent_name(self, name: str) -> None:
        """Update the current agent name."""
        with self._lock:
            self._current_agent_name = name
    def push_progress(self, active: bool, status: str = "") -> None:
        """Update the progress indicator."""
        with self._lock:
            self._current_progress = {"active": active, "status": status}
    def set_logs_dir(self, logs_dir: str) -> None:
        """Set the current logs directory path."""
        with self._lock:
            self._current_logs_dir = logs_dir
    def clear_logs(self) -> None:
        """Clear the log buffer."""
        with self._lock:
            self._log_buffer.clear()
            self._log_read_index = 0
    @property
    def _agent_max_log_lines(self) -> int:
        return self._agent_max_log_lines_internal
    @_agent_max_log_lines.setter
    def _agent_max_log_lines(self, value: int) -> None:
        self._agent_max_log_lines_internal = value
        self._agent_registry.set_limits(value, self._agent_detail_max_log_lines_internal)
    @property
    def _agent_detail_max_log_lines(self) -> int | None:
        return self._agent_detail_max_log_lines_internal
    @_agent_detail_max_log_lines.setter
    def _agent_detail_max_log_lines(self, value: int | None) -> None:
        self._agent_detail_max_log_lines_internal = value
        self._agent_registry.set_limits(self._agent_max_log_lines_internal, value)

    def push_agent_status(
        self,
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
    ) -> None:
        """Register or update a running agent."""
        with self._lock:
            session_id = self._current_session_id
        resolved_type = agent_type or get_current_agent_type(default="")
        normalized_agent_type: str | None = resolved_type if resolved_type else None

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
            session_id=session_id,
            modified_files=modified_files,
            agent_type=normalized_agent_type,
        )

    def push_agent_log(self, agent_id: str, line: str) -> None:
        """Append a log line to an agent's recent log preview."""
        self._agent_registry.append_log(agent_id, line)

    def push_agent_tokens(
        self,
        agent_id: str,
        input_tokens: int,
        output_tokens: int,
        context_limit: int,
    ) -> None:
        """Update live token usage for an agent."""
        self._agent_registry.update_token_usage(
            agent_id, input_tokens, output_tokens, context_limit,
        )

    def remove_agent(self, agent_id: str) -> None:
        """Remove a finished agent from the tracked set."""
        self._agent_registry.remove(agent_id)

    def get_agents(self) -> list[dict[str, Any]]:
        """Return the list of currently tracked agents."""
        return self._agent_registry.serialize_all()

    def get_agent_detail(self, agent_id: str) -> dict[str, Any] | None:
        """Return a deep copy of a single agent's detail state."""
        return self._agent_registry.get_detail(agent_id)

    def pause_agent(self, agent_id: str) -> dict[str, Any]:
        """Pause an agent, preventing future scheduling."""
        success = self._agent_registry.pause(agent_id)
        if success:
            self.push_log(f"⏸️  Agent {agent_id} paused", "orchestrator", "yellow")
        return {"agent_id": agent_id, "paused": success}

    def resume_agent(self, agent_id: str) -> dict[str, Any]:
        """Resume a paused agent."""
        success = self._agent_registry.resume(agent_id)
        if success:
            self.push_log(f"▶️  Agent {agent_id} resumed", "orchestrator")
        return {"agent_id": agent_id, "resumed": success}

    def is_agent_paused(self, agent_id: str) -> bool:
        """Check if an agent is paused."""
        return self._agent_registry.is_paused(agent_id)

    def request_stop_after_current(self) -> dict[str, bool]:
        """Request orchestrator stop after the current item completes."""
        _request_stop_after_current()
        self.push_log("⏸️  Stop after current item requested", "orchestrator", "yellow")
        return {"stop_after_current": True}

    def cancel_stop_after_current(self) -> dict[str, bool]:
        """Cancel a pending stop-after-current request."""
        _cancel_stop_after_current()
        self.push_log("▶️  Stop after current item cancelled", "orchestrator")
        return {"stop_after_current": False}

    def spawn_agent(self) -> dict[str, Any]:
        """Spawn an additional agent if the orchestrator is running and below the limit.

        Returns a dict with:
          - success: bool — True if a spawn was requested
          - at_limit: bool — True if already at max_parallel_agents
          - active: int — number of currently running agents
          - max: int — effective max agents
        """
        from pokepoke.parallel import request_spawn_agent, get_effective_max_agents

        max_agents = get_effective_max_agents()

        with self._lock:
            running_agents = [
                a for a in self._agent_registry.serialize_all()
                if a.get("status") == "running"
            ]
        active_count = len(running_agents)

        if active_count >= max_agents:
            return {
                "success": False,
                "at_limit": True,
                "active": active_count,
                "max": max_agents,
            }

        request_spawn_agent()
        self.push_log(
            f"🚀 Spawn agent requested ({active_count + 1}/{max_agents})",
            "orchestrator",
        )
        return {
            "success": True,
            "at_limit": False,
            "active": active_count,
            "max": max_agents,
        }

    open_project = _ext.open_project
    browse_for_project = _ext.browse_for_project

    # First-time setup wizard API
    check_setup_status = _setup.check_setup_status
    git_init = _setup.git_init
    bd_init = _setup.bd_init
    create_default_config = _setup.create_default_config
    scaffold_prompt_overrides = _setup.scaffold_prompt_overrides
    complete_setup = _setup.complete_setup
    wait_for_setup_complete = _setup.wait_for_setup_complete

    list_prompts = _ext.list_prompts
    get_prompt = _ext.get_prompt
    save_prompt = _ext.save_prompt
    reset_prompt = _ext.reset_prompt
    add_work_item_label = _ext.add_work_item_label
    remove_work_item_label = _ext.remove_work_item_label
