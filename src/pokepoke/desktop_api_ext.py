"""Extended Desktop API methods extracted to keep desktop_api.py under the line limit.

These are mixed in by DesktopAPI at import time.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

try:
    import yaml  # type: ignore[import-untyped]
    _HAS_YAML = True
except ImportError:
    _HAS_YAML = False


def seed_historical_agents(self: Any) -> None:
    """Load persisted agent logs from disk so the UI shows history on startup."""
    from pokepoke.agent_history import load_historical_agents

    log_roots = _discover_log_roots()
    if not log_roots:
        return
    try:
        records = load_historical_agents(
            log_roots=log_roots,
            preview_limit=self._agent_max_log_lines_internal,
            detail_limit=self._agent_detail_max_log_lines_internal,
        )
    except Exception as exc:  # Defensive: logs should never block startup
        self.push_log(f"⚠️ Failed to load historical logs: {exc}", "orchestrator", "yellow")
        return

    for record in records:
        try:
            self._agent_registry.register_historical_agent(record)
        except ValueError:
            continue


def _discover_log_roots() -> list[Path]:
    """Return candidate directories that may contain run log folders."""
    roots: list[Path] = []
    env_override = os.environ.get("POKEPOKE_LOGS_DIR")
    if env_override:
        roots.append(Path(env_override).expanduser().resolve())

    try:
        from pokepoke.config import _find_repo_root

        repo_root = _find_repo_root()
    except Exception:
        repo_root = Path.cwd()

    for candidate in (repo_root / ".pokepoke" / "logs", repo_root / "logs"):
        resolved = candidate.resolve()
        if resolved not in roots:
            roots.append(resolved)

    return [root for root in roots if root.is_dir()]


def get_config(self: Any) -> dict[str, Any]:
    """Load the project config file as a JSON-serializable dict."""
    from pokepoke.config import _find_repo_root

    config_path = _find_repo_root() / ".pokepoke" / "config.yaml"
    if not config_path.exists():
        return {"path": str(config_path), "config": {}, "exists": False}

    if not _HAS_YAML:
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


def save_config(self: Any, config: Any) -> dict[str, Any]:
    """Persist a new project config to `.pokepoke/config.yaml`.

    Args:
        config: Typically a JS object passed via pywebview (dict-like).
    """
    from pokepoke.config import _find_repo_root, reset_config

    if not _HAS_YAML:
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

    reset_config()

    return {"path": str(config_path), "saved": True}


def list_prompts(self: Any) -> list[dict[str, Any]]:
    """List all prompt templates with override metadata.

    Returns a list of dicts with keys: name, is_override, has_builtin, source.
    """
    from pokepoke.prompts import get_prompt_service

    service = get_prompt_service()
    return service.list_prompts()


def get_prompt(self: Any, name: str) -> dict[str, Any]:
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


def save_prompt(self: Any, name: str, content: str) -> dict[str, Any]:
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


def reset_prompt(self: Any, name: str) -> dict[str, Any]:
    """Reset a prompt to the built-in default by removing the user override.

    Args:
        name: Template name (without .md extension).

    Returns:
        Dict with reset and had_override status.
    """
    from pokepoke.prompts import get_prompt_service

    service = get_prompt_service()
    return service.reset_prompt(name)
