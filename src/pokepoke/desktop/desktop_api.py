"""Python API exposed to the desktop frontend via pywebview.

Every public method on DesktopAPI is callable from JavaScript as:
    await window.pywebview.api.method_name(args)
"""
from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pokepoke.agents.agent_registry import AgentRegistry
from pokepoke.git.repo_utils import get_repository_name
from pokepoke.utils.logging_utils import configure_logging
from pokepoke.utils.shutdown import (
    cancel_stop_after_current as _cancel_stop_after_current,
)
from pokepoke.utils.shutdown import (
    request_stop_after_current as _request_stop_after_current,
)
from pokepoke.utils.shutdown import (
    should_stop_after_current as _should_stop_after_current,
)

from . import desktop_api_agents as _agents
from . import desktop_api_ext as _ext
from . import desktop_api_models as _models
from . import desktop_api_session as _session
from . import desktop_api_setup as _setup
from . import desktop_api_stats as _stats

if TYPE_CHECKING:
    from pokepoke.types_stats import SessionStats

class DesktopAPI:
    """API surface exposed to the pywebview frontend.

    pywebview exposes every public method to JavaScript automatically.
    Methods run on a background thread — they won't block the UI.
    """

    def __init__(self) -> None:
        self._window: Any | None = None
        self._lock = threading.RLock()
        self._window_disposed = False

        from pokepoke.config import load_config as _load_config
        _cfg = _load_config()
        configure_logging(
            Path(".pokepoke/logs/desktop_api.log"), otel_config=_cfg.otel,
        )

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
        self._agent_max_log_lines_internal = 100
        self._agent_detail_max_log_lines_internal: int | None = 500
        self._agent_registry = AgentRegistry(
            self._lock,
            preview_limit=self._agent_max_log_lines_internal,
            detail_limit=self._agent_detail_max_log_lines_internal,
        )

        self._repository_name = get_repository_name()
        # Setup wizard gating — orchestrator waits for UI to complete init
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
    (_snapshot_to_dict, _serialize_live_stats, _get_cached_leaderboard,
     get_model_leaderboard, get_model_history, push_stats, get_repo_summary,
     get_lock_contention_stats, get_merge_queue_stats, get_operation_timings,
     get_performance_metrics, get_process_diagnostics,
     get_concurrency_timeline, get_gate_rejection_stats) = (
        staticmethod(_stats.snapshot_to_dict), _stats.serialize_live_stats,
        _stats.get_cached_leaderboard, _stats.get_model_leaderboard,
        _stats.get_model_history, _stats.push_stats, _stats.get_repo_summary,
        _stats.get_lock_contention_stats, _stats.get_merge_queue_stats,
        _stats.get_operation_timings, _stats.get_performance_metrics,
        _stats.get_process_diagnostics, _stats.get_concurrency_timeline,
        _stats.get_gate_rejection_stats)

    def get_merge_flow_state(self) -> dict[str, Any]:
        """Return the live merge workflow step tracker state for the UI."""
        from pokepoke.worktrees.merge_step_tracker import get_merge_step_tracker
        return get_merge_step_tracker().get_state()

    def get_state(self) -> dict[str, Any]:
        """State snapshot + new log entries since last poll (single IPC call)."""
        from pokepoke.config import get_config
        with self._lock:
            if self._log_read_index < len(self._log_buffer):
                new_logs = self._log_buffer[self._log_read_index:]
                self._log_read_index = len(self._log_buffer)
            else:
                new_logs = []
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
                "new_logs": new_logs,
            }

    def get_new_logs(self) -> list[dict[str, Any]]:
        """Return new log entries since last call; used by reconnect / test helpers."""
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
    get_config, save_config = _ext.get_config, _ext.save_config
    get_available_models = _models.get_available_models

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
            if self._window_disposed:  # Silently ignore after window disposal
                return

            self._current_work_item = {
                "item_id": item_id,
                "title": title,
                "status": status,
                "labels": list(labels) if labels is not None else [],
            }
    # Session timing — delegated to desktop_api_session
    set_session_start_time = _session.set_session_start_time
    set_session_end_time = _session.set_session_end_time
    set_live_session_stats = _session.set_live_session_stats

    def push_agent_name(self, name: str) -> None:
        """Update the current agent name."""
        with self._lock:
            if self._window_disposed:  # Silently ignore after window disposal
                return
            self._current_agent_name = name
    def push_progress(self, active: bool, status: str = "") -> None:
        """Update the progress indicator."""
        with self._lock:
            if self._window_disposed:  # Silently ignore after window disposal
                return
            self._current_progress = {"active": active, "status": status}
    def set_logs_dir(self, logs_dir: str) -> None:
        """Set the current logs directory path."""
        with self._lock:
            if self._window_disposed:  # Silently ignore after window disposal
                return
            self._current_logs_dir = logs_dir
    def clear_logs(self) -> None:
        """Clear the log buffer."""
        with self._lock:
            if self._window_disposed:  # Silently ignore after window disposal
                return
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

    # Agent registry methods — delegated to desktop_api_agents
    # Lock held for full duration of registry calls to prevent TOCTOU races
    (push_agent_status, push_agent_log, push_agent_tokens, remove_agent,
     get_agents, get_agent_detail, pause_agent, resume_agent,
     is_agent_paused, has_active_child_agents, get_child_agent_activity_time) = (
        _agents.push_agent_status, _agents.push_agent_log,
        _agents.push_agent_tokens, _agents.remove_agent,
        _agents.get_agents, _agents.get_agent_detail,
        _agents.pause_agent, _agents.resume_agent,
        _agents.is_agent_paused, _agents.has_active_child_agents,
        _agents.get_child_agent_activity_time)
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
        from pokepoke.agents.parallel import get_effective_max_agents, request_spawn_agent

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
    (check_setup_status, git_init, bd_init, create_default_config,
     scaffold_prompt_overrides, complete_setup, wait_for_setup_complete) = (
        _setup.check_setup_status, _setup.git_init, _setup.bd_init,
        _setup.create_default_config, _setup.scaffold_prompt_overrides,
        _setup.complete_setup, _setup.wait_for_setup_complete)

    (list_prompts, get_prompt, save_prompt, reset_prompt,
     add_work_item_label, remove_work_item_label) = (
        _ext.list_prompts, _ext.get_prompt, _ext.save_prompt, _ext.reset_prompt,
        _ext.add_work_item_label, _ext.remove_work_item_label)
