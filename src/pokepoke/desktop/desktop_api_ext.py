"""Extended Desktop API methods extracted to keep desktop_api.py under the line limit.

These are mixed in by DesktopAPI at import time.
"""
from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from pokepoke.desktop.desktop_api import DesktopAPI

logger = logging.getLogger(__name__)

from contextlib import suppress

from pokepoke.beads.beads_query import _run_bd_with_retry
from pokepoke.desktop.desktop_api_utils import HAS_YAML, coerce_process_output

with suppress(ImportError):
    import yaml  # type: ignore[import-untyped]


def get_config(self: DesktopAPI) -> dict[str, Any]:
    """Load and validate project config as a JSON-serializable dict."""
    from pokepoke.config import ProjectConfig, _find_repo_root, _load_config_file

    config_path = _find_repo_root() / ".pokepoke" / "config.yaml"
    if not config_path.exists():
        return {"path": str(config_path), "config": {}, "exists": False}

    if not HAS_YAML:
        raise ImportError(
            "PyYAML is required to load .yaml config files. Install it with: pip install pyyaml"
        )

    raw_data = _load_config_file(config_path)
    validated = ProjectConfig.from_dict(raw_data)
    return {
        "path": str(config_path),
        "config": validated.to_dict(),
        "exists": True,
    }


def save_config(self: DesktopAPI, config: Any) -> dict[str, Any]:
    """Validate and persist project config to `.pokepoke/config.yaml`."""
    from pokepoke.config import ProjectConfig, _find_repo_root, reset_config

    if not HAS_YAML:
        raise ImportError(
            "PyYAML is required to save .yaml config files. Install it with: pip install pyyaml"
        )

    if isinstance(config, str):
        parsed = yaml.safe_load(config)
        if not isinstance(parsed, dict):
            raise ValueError("Config YAML must parse to an object")
        config_dict: dict[str, Any] = parsed
    elif isinstance(config, dict):
        config_dict = config
    else:
        raise ValueError("Config must be a dict or YAML string")

    validated = ProjectConfig.from_dict(config_dict)
    canonical = validated.to_dict()

    config_path = _find_repo_root() / ".pokepoke" / "config.yaml"
    config_path.parent.mkdir(parents=True, exist_ok=True)

    dumped = yaml.safe_dump(
        canonical,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
    )
    if not dumped.endswith("\n"):
        dumped += "\n"

    with self._lock:
        config_path.write_text(dumped, encoding="utf-8")

    reset_config()

    # Auto-create prompt files for custom maintenance agents
    from pokepoke.desktop.desktop_api_prompts import ensure_custom_agent_prompts

    ensure_custom_agent_prompts(canonical)

    return {"path": str(config_path), "saved": True}


def list_prompts(self: DesktopAPI) -> list[dict[str, Any]]:
    """List all prompt templates with override metadata.

    Returns a list of dicts with keys: name, is_override, has_builtin, source.
    """
    from pokepoke.prompts.prompts import get_prompt_service

    service = get_prompt_service()
    return service.list_prompts()


def get_prompt(self: DesktopAPI, name: str) -> dict[str, Any]:
    """Get a prompt template's content and metadata.

    Args:
        name: Template name (without .md extension).

    Returns:
        Dict with name, content, is_override, has_builtin, source,
        and template_variables.
    """
    from pokepoke.prompts.prompts import get_prompt_service

    service = get_prompt_service()
    return service.get_prompt_metadata(name)


def save_prompt(self: DesktopAPI, name: str, content: str) -> dict[str, Any]:
    """Save a prompt override to the user prompts directory.

    Args:
        name: Template name (without .md extension).
        content: New template content.

    Returns:
        Dict with path and saved status.
    """
    from pokepoke.prompts.prompts import get_prompt_service

    service = get_prompt_service()
    return service.save_prompt(name, content)


def reset_prompt(self: DesktopAPI, name: str) -> dict[str, Any]:
    """Reset a prompt to the built-in default by removing the user override.

    Args:
        name: Template name (without .md extension).

    Returns:
        Dict with reset and had_override status.
    """
    from pokepoke.prompts.prompts import get_prompt_service

    service = get_prompt_service()
    return service.reset_prompt(name)


def _update_current_labels(self: DesktopAPI, item_id: str, label: str, action: str) -> list[str] | None:
    with self._lock:
        current = self._current_work_item
        if not current or current.get("item_id") != item_id:
            return None
        labels = list(current.get("labels") or [])
        if action == "add":
            if label not in labels:
                labels.append(label)
        elif action == "remove":
            labels = [existing for existing in labels if existing != label]
        else:
            raise ValueError(f"Unknown label action: {action}")
        current["labels"] = labels
        return labels



def _build_label_error_result(
    item_id: str,
    label: str,
    message: str,
    *,
    stderr: str | None = None,
    returncode: int | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "item_id": item_id,
        "label": label,
        "success": False,
        "error": message,
    }
    if stderr:
        result["stderr"] = stderr
    if returncode is not None:
        result["returncode"] = returncode
    return result


def _mutate_work_item_label(
    self: DesktopAPI,
    item_id: str,
    label: str,
    action: Literal["add", "remove"],
) -> dict[str, Any]:
    flag = "--add-label" if action == "add" else "--remove-label"
    command = ["update", item_id, flag, label, "--json"]
    try:
        _run_bd_with_retry(command, timeout=30)
    except subprocess.TimeoutExpired as exc:
        logger.warning(
            "Label %s for %s timed out after %ss",
            action,
            item_id,
            exc.timeout,
        )
        return _build_label_error_result(
            item_id,
            label,
            "Label update timed out",
            stderr=coerce_process_output(getattr(exc, "stderr", None)),
        )
    except subprocess.CalledProcessError as exc:
        stderr = coerce_process_output(exc.stderr)
        message = stderr or f"'bd update' failed with exit code {exc.returncode}"
        logger.warning(
            "Label %s for %s failed: %s",
            action,
            item_id,
            message,
        )
        return _build_label_error_result(
            item_id,
            label,
            message,
            stderr=stderr,
            returncode=exc.returncode,
        )
    except OSError as exc:
        message = f"Failed to execute 'bd': {exc}"
        logger.warning("Label %s for %s failed: %s", action, item_id, message)
        return _build_label_error_result(item_id, label, message)

    labels = _update_current_labels(self, item_id, label, action)
    return {"item_id": item_id, "label": label, "labels": labels or [], "success": True}


def _is_git_repo(path: Path) -> bool:
    from pokepoke.utils.project_utils import is_git_repo
    return is_git_repo(path)


def _resolve_git_toplevel(path: Path) -> Path | None:
    from pokepoke.utils.project_utils import resolve_git_toplevel
    return resolve_git_toplevel(path)


def _has_pokepoke_config(project_path: Path) -> bool:
    from pokepoke.utils.project_utils import has_pokepoke_config
    return has_pokepoke_config(project_path)


def _check_beads_available(path: Path) -> bool:
    from pokepoke.utils.project_utils import check_beads_available
    return check_beads_available(path)


def open_project(self: DesktopAPI, path: str) -> dict[str, Any]:
    """Open a project directory, validating it and updating internal state."""
    from pokepoke.config import load_config, reset_config
    from pokepoke.git.repo_utils import get_repository_name
    from pokepoke.utils.shutdown import cancel_stop_after_current, has_active_agents

    project_path = Path(path).resolve()

    if not project_path.is_dir():
        return {"success": False, "path": str(project_path), "error": "Directory does not exist"}

    if not _is_git_repo(project_path):
        return {"success": False, "path": str(project_path), "error": "Not a git repository"}

    # Prevent switching projects while agents are active (would break relative-path locks)
    if has_active_agents():
        return {"success": False, "path": str(project_path), "error": "Cannot switch projects while agents are running. Wait for agents to complete."}

    # Resolve to git repo root (handles subdirectory picks)
    repo_root = _resolve_git_toplevel(project_path)
    if repo_root is not None:
        project_path = repo_root

    has_config = _has_pokepoke_config(project_path)
    needs_beads_init = not _check_beads_available(project_path)

    # Compute explicit config path so load_config does not depend on CWD
    config_path = project_path / ".pokepoke" / "config.yaml"

    with self._lock:
        # os.chdir is process-global; holding the lock serialises it with
        # state reads in get_state() so other threads never observe a
        # partially-updated CWD + state combination.
        os.chdir(project_path)

        reset_config()
        config = load_config(config_path=config_path if config_path.exists() else None)
        repo_name = get_repository_name()
        cancel_stop_after_current()

        self._repository_name = repo_name
        self._current_work_item = None
        self._current_agent_name = ""
        self._current_stats = None
        self._current_progress = {"active": False, "status": ""}
        self._log_buffer.clear()
        self._log_read_index = 0
        self._session_start_time = None
        self._session_end_time = None
        self._current_session_id = None
        self._live_session_stats = None
        self._current_logs_dir = None

    self._agent_registry.clear()
    self.push_log(f"📂 Opened project: {repo_name} ({project_path})", "orchestrator")

    return {
        "success": True,
        "path": str(project_path),
        "project_name": config.project_name or repo_name,
        "needs_init": not has_config,
        "needs_beads_init": needs_beads_init,
    }


def browse_for_project(self: DesktopAPI) -> dict[str, Any]:
    """Open a native folder picker dialog and open the selected project.

    Uses pywebview's native folder dialog. If no folder is selected
    (user cancels), returns a cancelled result.

    Returns:
        Dict with success/cancelled status and project info on success.
    """
    window = self._window
    if window is None:
        return {"success": False, "error": "No window available"}

    try:
        result = window.create_file_dialog(
            dialog_type=20,  # webview.FOLDER_DIALOG
            directory="",
            allow_multiple=False,
        )
    except Exception as exc:
        return {"success": False, "error": f"Dialog failed: {exc}"}

    if not result:
        return {"success": False, "cancelled": True}

    # pywebview returns a tuple/list of selected paths
    selected = result[0] if isinstance(result, (list, tuple)) else result
    return open_project(self, str(selected))


def add_work_item_label(self: DesktopAPI, item_id: str, label: str) -> dict[str, Any]:
    """Add a label to a beads work item and update the cached UI state."""
    if not label.strip():
        raise ValueError("Label cannot be empty")
    return _mutate_work_item_label(self, item_id, label, "add")


def remove_work_item_label(self: DesktopAPI, item_id: str, label: str) -> dict[str, Any]:
    """Remove a label from a beads work item and update the cached UI state."""
    if not label.strip():
        raise ValueError("Label cannot be empty")
    return _mutate_work_item_label(self, item_id, label, "remove")
