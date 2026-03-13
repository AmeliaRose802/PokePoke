"""Desktop API setup wizard methods.

Extracted from desktop_api_ext.py to keep file lengths under the limit.
These are mixed into DesktopAPI via attribute assignment in desktop_api.py.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from pokepoke.desktop_api import DesktopAPI

from contextlib import suppress

from pokepoke.desktop_api_utils import HAS_YAML, coerce_process_output
from pokepoke.git_helpers import run_git

with suppress(ImportError):
    import yaml  # type: ignore[import-untyped]


def check_setup_status(self: DesktopAPI) -> dict[str, Any]:
    """Return setup status for the current working directory.

    Used by the desktop first-time setup wizard.
    """
    from pokepoke.project_utils import (
        is_git_repo, resolve_git_toplevel,
        has_pokepoke_config, check_beads_available,
    )

    cwd = Path.cwd().resolve()
    git_root = resolve_git_toplevel(cwd)
    project_root = git_root or cwd

    is_git = is_git_repo(cwd)
    has_config = has_pokepoke_config(project_root)
    beads_initialized = check_beads_available(project_root)
    bd_installed = shutil.which("bd") is not None

    return {
        "cwd": str(cwd),
        "project_root": str(project_root),
        "is_git_repo": is_git,
        "beads_installed": bd_installed,
        "beads_initialized": beads_initialized,
        "config_exists": has_config,
        "config_path": str(project_root / ".pokepoke" / "config.yaml"),
        "needs_setup": (not is_git) or (not beads_initialized) or (not has_config),
    }


def git_init(self: DesktopAPI, default_branch: str | None = None) -> dict[str, Any]:
    """Initialize a git repository in the current working directory."""
    cwd = Path.cwd().resolve()
    command = ["git", "init"]
    if default_branch:
        command.extend(["-b", default_branch])

    try:
        result = run_git(
            command,
            cwd=str(cwd),
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "success": False,
            "error": "git init timed out",
            "stdout": coerce_process_output(getattr(exc, "stdout", None)),
            "stderr": coerce_process_output(getattr(exc, "stderr", None)),
        }
    except (subprocess.CalledProcessError, OSError) as exc:
        stderr = coerce_process_output(getattr(exc, "stderr", None))
        return {
            "success": False,
            "error": stderr or f"git init failed: {exc}",
            "stdout": coerce_process_output(getattr(exc, "stdout", None)),
            "stderr": stderr,
        }

    return {
        "success": True,
        "stdout": coerce_process_output(result.stdout),
        "stderr": coerce_process_output(result.stderr),
    }


def bd_init(self: DesktopAPI) -> dict[str, Any]:
    """Initialize beads in the current project (equivalent to running `bd init`)."""
    from pokepoke.project_utils import resolve_git_toplevel
    from pokepoke.repo_check import initialize_beads_repo

    project_root = resolve_git_toplevel(Path.cwd()) or Path.cwd()
    ok = initialize_beads_repo(project_root)
    return {"success": bool(ok)}


def create_default_config(self: DesktopAPI, config: Any) -> dict[str, Any]:
    """Create `.pokepoke/config.yaml` with sensible defaults."""
    from pokepoke.config import DEFAULT_MODEL, FALLBACK_MODEL, reset_config
    from pokepoke.project_utils import resolve_git_toplevel

    if not HAS_YAML:
        raise ImportError(
            "PyYAML is required to save .yaml config files. Install it with: pip install pyyaml"
        )

    if not isinstance(config, dict):
        raise ValueError("Config must be a dict")

    project_name = str(config.get("project_name") or config.get("projectName") or "").strip()
    default_model = str(config.get("default_model") or config.get("defaultModel") or DEFAULT_MODEL).strip()
    fallback_model = str(config.get("fallback_model") or config.get("fallbackModel") or FALLBACK_MODEL).strip()

    max_agents_raw = config.get("max_parallel_agents")
    if max_agents_raw is None:
        max_agents_raw = config.get("maxParallelAgents")
    max_parallel_agents = max(1, int(max_agents_raw or 1))

    default_branch = str(config.get("default_branch") or config.get("defaultBranch") or "").strip() or None

    config_dict: dict[str, Any] = {
        "project_name": project_name,
        "models": {
            "default": default_model,
            "fallback": fallback_model,
        },
        "max_parallel_agents": max_parallel_agents,
        "git": {
            "default_branch": default_branch,
        },
    }

    project_root = resolve_git_toplevel(Path.cwd()) or Path.cwd()
    config_path = project_root / ".pokepoke" / "config.yaml"
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

    reset_config()
    return {"path": str(config_path), "saved": True}


def scaffold_prompt_overrides(
    self: DesktopAPI,
    templates: list[str] | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Copy built-in prompt templates into `.pokepoke/prompts/` as user overrides."""
    from pokepoke.project_utils import resolve_git_toplevel
    from pokepoke.prompts import BUILTIN_PROMPTS_DIR

    project_root = resolve_git_toplevel(Path.cwd()) or Path.cwd()
    prompts_dir = project_root / ".pokepoke" / "prompts"
    prompts_dir.mkdir(parents=True, exist_ok=True)

    to_copy = templates or ["beads-item"]
    written: list[str] = []

    for name in to_copy:
        src = (BUILTIN_PROMPTS_DIR / f"{name}.md").resolve()
        dst = (prompts_dir / f"{name}.md").resolve()
        if not src.exists():
            continue
        if dst.exists() and not force:
            continue
        shutil.copyfile(src, dst)
        written.append(str(dst))

    return {"success": True, "written": written}


def complete_setup(self: DesktopAPI) -> dict[str, Any]:
    """Signal that the setup wizard is complete so the orchestrator may proceed."""
    event = getattr(self, "_setup_complete_event", None)
    if event is None:
        return {"success": False, "error": "setup event not initialized"}
    event.set()
    return {"success": True}


def wait_for_setup_complete(self: DesktopAPI, timeout: float | None = None) -> bool:
    """Wait until setup is complete; returns True if completed, False on timeout."""
    event = getattr(self, "_setup_complete_event", None)
    if event is None:
        return True
    return bool(event.wait(timeout))
