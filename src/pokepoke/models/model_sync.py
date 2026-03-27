"""Copilot model discovery sync and beads integration."""

from __future__ import annotations

import json
import logging
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pokepoke.beads.beads_management import run_bd_sync_with_retry
from pokepoke.beads.beads_query import _get_main_repo_root
from pokepoke.config import get_config
from pokepoke.models.model_sync_beads import (
    _find_model_items,
    _list_existing_model_items,
    _prune_unavailable_models,
    _sync_beads_items,
)
from pokepoke.models.model_sync_parsing import (
    CopilotModelSnapshot,
    normalize_model_entry,
    parse_copilot_models_output,
)
from pokepoke.types import AgentStats

logger = logging.getLogger(__name__)

REGISTRY_PATH = Path(".pokepoke") / "model_registry.json"


def _log(item_logger: Any | None, message: str) -> None:
    logger.info(message)
    if item_logger is not None:
        item_logger.log(message + "\n")




def _run_copilot_models(cli_path: str, timeout: int = 30) -> list[dict[str, Any]]:
    commands = [
        [cli_path, "models", "list", "--json"],
        [cli_path, "models", "list", "--output", "json"],
        [cli_path, "models", "list", "--format", "json"],
        [cli_path, "models", "list"],
    ]
    for cmd in commands:
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            continue
        if result.returncode != 0:
            continue
        models = parse_copilot_models_output(result.stdout)
        if models:
            return models
    return []


def load_registry(path: Path | None = None) -> dict[str, Any]:
    registry_path = path or REGISTRY_PATH
    if not registry_path.exists():
        return {"last_sync": None, "models": {}}
    try:
        data = json.loads(registry_path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and "models" in data:
            return data
    except json.JSONDecodeError:
        pass
    return {"last_sync": None, "models": {}}


def save_registry(data: dict[str, Any], path: Path | None = None) -> None:
    registry_path = path or REGISTRY_PATH
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    registry_path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def get_available_model_names(registry_path: Path | None = None) -> list[str]:
    """Return sorted list of model names currently marked available in the registry."""
    registry = load_registry(path=registry_path)
    models = registry.get("models", {})
    return sorted(
        name
        for name, entry in models.items()
        if isinstance(entry, dict) and entry.get("available") is True
    )


def get_registry_last_sync(registry_path: Path | None = None) -> str | None:
    """Return the ISO timestamp of the last model sync, or None."""
    registry = load_registry(path=registry_path)
    last_sync = registry.get("last_sync")
    return last_sync if isinstance(last_sync, str) else None


def update_registry(
    models: list[CopilotModelSnapshot],
    registry: dict[str, Any],
    now: datetime,
) -> tuple[dict[str, Any], set[str], set[str]]:
    model_store: dict[str, Any] = registry.get("models", {})
    available_now: set[str] = set()
    newly_available: set[str] = set()
    became_unavailable: set[str] = set()

    for model in models:
        name = model.name
        available_now.add(name)
        previous = model_store.get(name)
        first_seen = previous.get("first_seen") if isinstance(previous, dict) else None
        if not first_seen:
            first_seen = now.isoformat()
            newly_available.add(name)
        model_store[name] = {
            "name": name,
            "status": model.status,
            "capabilities": model.capabilities,
            "context_window": model.context_window,
            "pricing": model.pricing,
            "version": model.version,
            "tags": model.tags,
            "first_seen": first_seen,
            "last_seen": now.isoformat(),
            "available": True,
        }

    for name, entry in model_store.items():
        if name in available_now:
            continue
        if isinstance(entry, dict) and entry.get("available") is True:
            entry["available"] = False
            entry["last_seen"] = entry.get("last_seen") or now.isoformat()
            became_unavailable.add(name)

    registry["last_sync"] = now.isoformat()
    registry["models"] = model_store
    return registry, newly_available, became_unavailable


def _should_skip_sync(sync_cfg: Any, registry: dict[str, Any], item_logger: Any | None) -> bool:
    """Check if sync should be skipped due to config or recent run."""
    if not sync_cfg.enabled:
        _log(item_logger, "ℹ️  Model sync disabled in config; skipping.")
        return True

    last_sync = registry.get("last_sync")
    if isinstance(last_sync, str):
        try:
            last_dt = datetime.fromisoformat(last_sync)
            if last_dt.tzinfo is None:
                last_dt = last_dt.replace(tzinfo=UTC)
            elapsed_minutes = (datetime.now(UTC) - last_dt).total_seconds() / 60.0
            if elapsed_minutes < sync_cfg.interval_minutes:
                _log(item_logger, f"ℹ️  Model sync last ran {elapsed_minutes:.1f}m ago; skipping.")
                return True
        except ValueError:
            pass
    return False


def _fetch_and_normalize_models(
    cli_path: str, timeout: int, item_logger: Any | None
) -> list[CopilotModelSnapshot] | None:
    """Fetch models from Copilot and normalize them. Returns None on failure."""
    raw_models = _run_copilot_models(cli_path, timeout=timeout)
    if not raw_models:
        _log(item_logger, "⚠️  No models returned from Copilot.")
        return None

    normalized = [normalize_model_entry(m) for m in raw_models]
    models = [m for m in normalized if m is not None]
    if not models:
        _log(item_logger, "⚠️  Copilot model list parsed with no valid entries.")
        return None
    return models


def prune_unavailable_from_config(
    registry_path: Path | None = None,
    item_logger: Any | None = None,
) -> list[str]:
    """Remove unavailable models from the saved project config.

    Checks ``candidate_models`` against the model registry and removes any
    that are no longer available.  Persists the updated config and returns
    the list of model names that were removed.
    """
    available = set(get_available_model_names(registry_path=registry_path))
    if not available:
        return []

    from pokepoke.config import (
        ProjectConfig,
        _find_repo_root,
        _load_config_file,
        reset_config,
    )

    config_path = _find_repo_root() / ".pokepoke" / "config.yaml"
    if not config_path.exists():
        return []

    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError:
        return []

    raw_data = _load_config_file(config_path)
    validated = ProjectConfig.from_dict(raw_data)

    candidates = validated.models.candidate_models
    if not candidates:
        return []

    pruned = [m for m in candidates if m not in available]
    if not pruned:
        return []

    validated.models.candidate_models = [m for m in candidates if m in available]

    canonical = validated.to_dict()
    dumped = yaml.safe_dump(canonical, sort_keys=False, allow_unicode=True, default_flow_style=False)
    if not dumped.endswith("\n"):
        dumped += "\n"
    config_path.write_text(dumped, encoding="utf-8")
    reset_config()

    for model_name in pruned:
        _log(item_logger, f"🗑️  Removed unavailable model '{model_name}' from config")
    return pruned


def sync_copilot_models(item_logger: Any | None = None, force: bool = False) -> AgentStats | None:
    """Sync Copilot models into beads and update local registry.

    Args:
        item_logger: Optional logger for output messages
        force: If True, skip the interval check and always run the sync
    """
    config = get_config()
    sync_cfg = config.model_sync
    start_time = time.time()

    registry = load_registry()
    if not force and _should_skip_sync(sync_cfg, registry, item_logger):
        return AgentStats()

    models = _fetch_and_normalize_models(config.ai_backend.copilot_cli_path, config.command_timeout, item_logger)
    if models is None:
        return None

    now = datetime.now(UTC)
    registry, _new_models, removed_models = update_registry(models, registry, now)
    save_registry(registry)

    repo_root = _get_main_repo_root()
    cwd = str(repo_root) if repo_root else None
    existing_items = _find_model_items(_list_existing_model_items(cwd=cwd))
    created: list[str] = []
    updated: list[str] = []
    closed: list[str] = []

    if sync_cfg.create_beads_items:
        created, updated = _sync_beads_items(models, sync_cfg, existing_items, now, cwd, item_logger)

    if sync_cfg.prune_unavailable and removed_models:
        closed = _prune_unavailable_models(removed_models, existing_items, cwd, item_logger)

    # Auto-prune unavailable models from saved config
    config_pruned = prune_unavailable_from_config(item_logger=item_logger)

    if created or updated or closed:
        run_bd_sync_with_retry()

    if created:
        _log(item_logger, f"✅ New beta models added: {', '.join(created)}")
    if updated:
        _log(item_logger, f"♻️  Updated model metadata: {', '.join(updated)}")
    if closed:
        _log(item_logger, f"🧹 Closed unavailable models: {', '.join(closed)}")
    if config_pruned:
        _log(item_logger, f"🗑️  Pruned from config: {', '.join(config_pruned)}")
    if not created and not updated and not closed and not config_pruned:
        _log(item_logger, "✅ Model sync complete (no changes).")

    elapsed = time.time() - start_time
    return AgentStats(wall_duration=elapsed)

