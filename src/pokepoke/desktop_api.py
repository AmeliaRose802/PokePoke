"""Python API exposed to the desktop frontend via pywebview.

Every public method on DesktopAPI is callable from JavaScript as:
    await window.pywebview.api.method_name(args)

This is NOT a server. pywebview calls these methods directly in-process.
"""

from __future__ import annotations

import threading
import time
from dataclasses import asdict
from typing import Any, Optional, TYPE_CHECKING

try:
    import yaml  # type: ignore[import-untyped]
    HAS_YAML = True
except ImportError:
    HAS_YAML = False

if TYPE_CHECKING:
    from pokepoke.types import SessionStats


class DesktopAPI:
    """API surface exposed to the pywebview frontend.

    pywebview exposes every public method to JavaScript automatically.
    Methods run on a background thread — they won't block the UI.
    """

    def __init__(self) -> None:
        self._window: Optional[Any] = None
        self._lock = threading.Lock()

        # Buffered state — frontend can poll or get pushed updates
        self._log_buffer: list[dict[str, Any]] = []
        self._max_log_buffer = 2000
        self._current_work_item: Optional[dict[str, str]] = None
        self._current_agent_name: str = ""
        self._current_stats: Optional[dict[str, Any]] = None
        self._current_progress: dict[str, Any] = {"active": False, "status": ""}

        # Session start time for dynamic elapsed_time computation
        self._session_start_time: Optional[float] = None

        # Live reference to SessionStats — serialized fresh on each poll
        # so agent run counts, token stats, etc. update in real-time
        self._live_session_stats: Optional["SessionStats"] = None

        # Read index for incremental log fetching
        self._log_read_index: int = 0

        # Leaderboard cache for model performance stats
        self._leaderboard_cache: dict[str, Any] = {}
        self._leaderboard_cache_time: float = 0.0

    def set_window(self, window: Any) -> None:
        """Called once after pywebview creates the window."""
        self._window = window

    # ─── JS → Python: Query methods ──────────────────────────────────

    def _serialize_live_stats(self) -> Optional[dict[str, Any]]:
        """Serialize session stats fresh on every poll.

        If a live SessionStats reference is stored, it is serialized
        on each call so agent run counts, token stats, retries, etc.
        update in real-time without needing explicit push_stats() calls.
        elapsed_time is also recomputed dynamically from session start.
        """
        stats: dict[str, Any] | None = None
        live = self._live_session_stats
        if live is not None:
            snapshot = live.snapshot()
            stats = {
                "agent_stats": asdict(snapshot.agent_stats),
                "items_completed": snapshot.items_completed,
                "work_agent_runs": snapshot.work_agent_runs,
                "gate_agent_runs": snapshot.gate_agent_runs,
                "tech_debt_agent_runs": snapshot.tech_debt_agent_runs,
                "janitor_agent_runs": snapshot.janitor_agent_runs,
                "backlog_cleanup_agent_runs": snapshot.backlog_cleanup_agent_runs,
                "cleanup_agent_runs": snapshot.cleanup_agent_runs,
                "beta_tester_agent_runs": snapshot.beta_tester_agent_runs,
                "code_review_agent_runs": snapshot.code_review_agent_runs,
                "worktree_cleanup_agent_runs": snapshot.worktree_cleanup_agent_runs,
                "model_completions": [
                    asdict(mc) for mc in snapshot.model_completions
                ],
            }
            # Carry forward elapsed_time from last push_stats snapshot
            cached = self._current_stats
            if cached is not None and "elapsed_time" in cached:
                stats["elapsed_time"] = cached["elapsed_time"]
        elif self._current_stats is not None:
            stats = dict(self._current_stats)

        # Override with live elapsed_time if session start is known
        if self._session_start_time is not None:
            elapsed = time.time() - self._session_start_time
            if stats is None:
                stats = {"elapsed_time": elapsed}
            else:
                stats["elapsed_time"] = elapsed

        return stats

    def get_state(self) -> dict[str, Any]:
        """Get the full current state snapshot. Called on frontend init."""
        with self._lock:
            return {
                "work_item": self._current_work_item,
                "agent_name": self._current_agent_name,
                "stats": self._serialize_live_stats(),
                "progress": self._current_progress,
                "log_count": len(self._log_buffer),
                "model_leaderboard": self._get_cached_leaderboard(),
            }

    def _get_cached_leaderboard(self) -> dict[str, Any]:
        """Return model leaderboard, cached for 5 seconds to avoid disk reads on every poll."""
        now = time.time()
        if now - self._leaderboard_cache_time > 5.0:
            from pokepoke.model_stats_store import get_model_summary
            self._leaderboard_cache = get_model_summary()
            self._leaderboard_cache_time = now
        return self._leaderboard_cache

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

    def get_work_item(self) -> Optional[dict[str, str]]:
        """Get the current work item."""
        return self._current_work_item

    def get_stats(self) -> Optional[dict[str, Any]]:
        """Get the current session stats."""
        with self._lock:
            return self._serialize_live_stats()

    def get_model_leaderboard(self) -> dict[str, Any]:
        """Get all-time model performance stats from persistent storage.

        Returns the per-model summary from .pokepoke/model_stats.json,
        enabling the desktop UI to show a historical leaderboard alongside
        the current session's model comparison row.
        """
        from pokepoke.model_stats_store import get_model_summary
        return get_model_summary()

    def get_config(self) -> dict[str, Any]:
        """Load the project config file as a JSON-serializable dict.

        The desktop UI uses this to populate the Settings page.
        """
        from pokepoke.config import _find_repo_root

        config_path = _find_repo_root() / ".pokepoke" / "config.yaml"
        if not config_path.exists():
            return {"path": str(config_path), "config": {}, "exists": False}

        if not HAS_YAML:
            raise ImportError(
                "PyYAML is required to load .yaml config files. Install it with: pip install pyyaml"
            )

        raw = config_path.read_text(encoding="utf-8")
        data = yaml.safe_load(raw)
        return {
            "path": str(config_path),
            "config": data if isinstance(data, dict) else {},
            "exists": True,
        }

    def save_config(self, config: Any) -> dict[str, Any]:
        """Persist a new project config to `.pokepoke/config.yaml`.

        Args:
            config: Typically a JS object passed via pywebview (dict-like).
        """
        from pokepoke.config import _find_repo_root, reset_config

        if not HAS_YAML:
            raise ImportError(
                "PyYAML is required to save .yaml config files. Install it with: pip install pyyaml"
            )

        # pywebview usually passes a dict, but allow YAML string for convenience.
        if isinstance(config, str):
            parsed = yaml.safe_load(config)
            if not isinstance(parsed, dict):
                raise ValueError("Config YAML must parse to an object")
            config_dict: dict[str, Any] = parsed
        elif isinstance(config, dict):
            config_dict = config
        else:
            raise ValueError("Config must be a dict or YAML string")

        config_path = _find_repo_root() / ".pokepoke" / "config.yaml"
        config_path.parent.mkdir(parents=True, exist_ok=True)

        dumped = yaml.safe_dump(
            config_dict,
            sort_keys=False,
            allow_unicode=True,
            default_flow_style=False,
        )
        if not dumped.endswith("\n"):
            dumped += "\n"

        with self._lock:
            config_path.write_text(dumped, encoding="utf-8")

        # Ensure subsequent orchestrator reads see the new values.
        reset_config()

        return {"path": str(config_path), "saved": True}

    # ─── Python → State: Called by the orchestrator ───────────────────

    def push_log(
        self, message: str, target: str = "orchestrator", style: Optional[str] = None
    ) -> None:
        """Add a log entry to the buffer."""
        entry = {
            "message": message,
            "target": target,
            "style": style,
            "timestamp": time.time(),
        }
        with self._lock:
            self._log_buffer.append(entry)
            if len(self._log_buffer) > self._max_log_buffer:
                # Trim oldest entries and adjust read index
                trim = len(self._log_buffer) - self._max_log_buffer
                self._log_buffer = self._log_buffer[trim:]
                self._log_read_index = max(0, self._log_read_index - trim)

    def push_work_item(self, item_id: str, title: str, status: str = "") -> None:
        """Update the current work item."""
        self._current_work_item = {
            "item_id": item_id,
            "title": title,
            "status": status,
        }

    def set_session_start_time(self, start_time: float) -> None:
        """Store the session start time for dynamic elapsed_time computation.

        Once set, every call to get_state()/get_stats() will recompute
        elapsed_time = now - start_time so the frontend timer ticks live.
        """
        self._session_start_time = start_time

    def set_live_session_stats(self, session_stats: "SessionStats") -> None:
        """Store a live reference to SessionStats for real-time polling.

        The live object is serialized fresh on every get_state()/get_stats()
        poll, so any mutations (agent run counts, token stats, retries)
        are reflected immediately without needing explicit push calls.
        """
        self._live_session_stats = session_stats

    def push_stats(
        self, session_stats: Optional["SessionStats"], elapsed_time: float = 0.0
    ) -> None:
        """Update session statistics (snapshot fallback).

        Prefer set_live_session_stats() for real-time updates.
        This method is kept for backwards compatibility and is used
        as a fallback when no live reference is set.
        """
        if session_stats:
            self._live_session_stats = session_stats
        stats_data: dict[str, Any] = {"elapsed_time": elapsed_time}
        if session_stats:
            snapshot = session_stats.snapshot()
            stats_data["agent_stats"] = asdict(snapshot.agent_stats)
            stats_data["items_completed"] = snapshot.items_completed
            stats_data["work_agent_runs"] = snapshot.work_agent_runs
            stats_data["gate_agent_runs"] = snapshot.gate_agent_runs
            stats_data["tech_debt_agent_runs"] = snapshot.tech_debt_agent_runs
            stats_data["janitor_agent_runs"] = snapshot.janitor_agent_runs
            stats_data["backlog_cleanup_agent_runs"] = snapshot.backlog_cleanup_agent_runs
            stats_data["cleanup_agent_runs"] = snapshot.cleanup_agent_runs
            stats_data["beta_tester_agent_runs"] = snapshot.beta_tester_agent_runs
            stats_data["code_review_agent_runs"] = snapshot.code_review_agent_runs
            stats_data["worktree_cleanup_agent_runs"] = snapshot.worktree_cleanup_agent_runs
            stats_data["model_completions"] = [
                asdict(mc) for mc in snapshot.model_completions
            ]
        self._current_stats = stats_data

    def push_agent_name(self, name: str) -> None:
        """Update the current agent name."""
        self._current_agent_name = name

    def push_progress(self, active: bool, status: str = "") -> None:
        """Update the progress indicator."""
        self._current_progress = {"active": active, "status": status}

    def clear_logs(self) -> None:
        """Clear the log buffer."""
        with self._lock:
            self._log_buffer.clear()
            self._log_read_index = 0

    # ─── Prompt management ────────────────────────────────────────────

    def list_prompts(self) -> list[dict[str, Any]]:
        """List all prompt templates with override metadata.

        Returns a list of dicts with keys: name, is_override, has_builtin, source.
        """
        from pokepoke.prompts import get_prompt_service

        service = get_prompt_service()
        return service.list_prompts()

    def get_prompt(self, name: str) -> dict[str, Any]:
        """Get a prompt template's content and metadata.

        Args:
            name: Template name (without .md extension).

        Returns:
            Dict with name, content, is_override, has_builtin, source,
            and template_variables.
        """
        from pokepoke.prompts import get_prompt_service

        service = get_prompt_service()
        return service.get_prompt_metadata(name)

    def save_prompt(self, name: str, content: str) -> dict[str, Any]:
        """Save a prompt override to the user prompts directory.

        Args:
            name: Template name (without .md extension).
            content: New template content.

        Returns:
            Dict with path and saved status.
        """
        from pokepoke.prompts import get_prompt_service

        service = get_prompt_service()
        return service.save_prompt(name, content)

    def reset_prompt(self, name: str) -> dict[str, Any]:
        """Reset a prompt to the built-in default by removing the user override.

        Args:
            name: Template name (without .md extension).

        Returns:
            Dict with reset and had_override status.
        """
        from pokepoke.prompts import get_prompt_service

        service = get_prompt_service()
        return service.reset_prompt(name)
