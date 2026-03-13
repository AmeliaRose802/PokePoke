"""Copilot model discovery sync and beads integration."""

from __future__ import annotations

import json
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pokepoke.config import get_config
from pokepoke.model_sync_parsing import (
    CopilotModelSnapshot,
    parse_copilot_models_output,
    normalize_model_entry,
    is_beta_model,
)
from pokepoke.types import AgentStats
from pokepoke.beads_query import _parse_beads_json, _run_bd, _get_main_repo_root
from pokepoke.beads_management import run_bd_sync_with_retry

REGISTRY_PATH = Path(".pokepoke") / "model_registry.json"


def _log(item_logger: Any | None, message: str) -> None:
    print(message)
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


def _build_issue_title(model_name: str) -> str:
    return f"Beta test Copilot model: {model_name}"


def _build_issue_description(model: CopilotModelSnapshot, discovered_at: str) -> str:
    lines = [
        "## Copilot Model Beta",
        "",
        f"**Model:** {model.name}",
        f"**Discovered:** {discovered_at}",
    ]
    if model.status:
        lines.append(f"**Status:** {model.status}")
    if model.version:
        lines.append(f"**Version:** {model.version}")
    if model.context_window:
        lines.append(f"**Context window:** {model.context_window:,} tokens")
    if model.capabilities:
        lines.append(f"**Capabilities:** {', '.join(model.capabilities)}")
    if model.tags:
        lines.append(f"**Tags:** {', '.join(model.tags)}")
    if model.pricing:
        lines.append(f"**Pricing:** {json.dumps(model.pricing, ensure_ascii=False)}")
    lines.extend([
        "",
        "## Beta Testing",
        "- Validate model availability in Copilot",
        "- Exercise core workflows and report regressions",
        "- Update notes with findings",
    ])
    return "\n".join(lines)


def _build_model_metadata(model: CopilotModelSnapshot, discovered_at: str, last_seen: str) -> dict[str, Any]:
    return {
        "copilot_model": model.name,
        "model_sync": {
            "discovered_at": discovered_at,
            "last_seen": last_seen,
            "status": model.status,
            "capabilities": model.capabilities,
            "context_window": model.context_window,
            "pricing": model.pricing,
            "version": model.version,
            "tags": model.tags,
            "source": "copilot",
        },
    }


def _list_existing_model_items(cwd: str | None = None) -> list[dict[str, Any]]:
    result = _run_bd(["list", "--json"], check=False, cwd=cwd)
    if result.returncode != 0 or not result.stdout:
        return []
    data = _parse_beads_json(result.stdout)
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict)]


def _find_model_items(items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    model_items: dict[str, dict[str, Any]] = {}
    for item in items:
        metadata = item.get("metadata")
        model_name = None
        if isinstance(metadata, dict):
            model_name = metadata.get("copilot_model")
        if not model_name:
            title = str(item.get("title", ""))
            if title.startswith("Beta test Copilot model: "):
                model_name = title.replace("Beta test Copilot model: ", "", 1).strip()
        if model_name:
            model_items[str(model_name)] = item
    return model_items


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


def _sync_beads_items(
    models: list[CopilotModelSnapshot],
    sync_cfg: Any,
    existing_items: dict[str, dict[str, Any]],
    now: datetime,
    cwd: str | None,
    item_logger: Any | None,
) -> tuple[list[str], list[str]]:
    """Create or update beads items for models. Returns (created, updated) lists."""
    created: list[str] = []
    updated: list[str] = []

    for model in models:
        if sync_cfg.beta_only and not is_beta_model(model, sync_cfg.include_preview):
            continue

        title = _build_issue_title(model.name)
        discovered_at = now.isoformat()
        metadata = _build_model_metadata(model, discovered_at, discovered_at)
        description = _build_issue_description(model, discovered_at)
        existing = existing_items.get(model.name)
        labels = ",".join(sync_cfg.labels)

        if existing is None:
            cmd = [
                "create", title,
                "--type", sync_cfg.issue_type,
                "--priority", str(sync_cfg.priority),
                "--description", description,
                "--metadata", json.dumps(metadata, ensure_ascii=False),
                "--json",
            ]
            if labels:
                cmd.extend(["--labels", labels])
            result = _run_bd(cmd, check=False, cwd=cwd)
            if result.returncode == 0:
                created.append(model.name)
            else:
                _log(item_logger, f"⚠️  Failed to create beads item for {model.name}: {result.stderr.strip()}")
        else:
            item_id = existing.get("id")
            if not item_id:
                continue
            cmd = [
                "update", str(item_id),
                "--metadata", json.dumps(metadata, ensure_ascii=False),
                "--description", description,
            ]
            result = _run_bd(cmd, check=False, cwd=cwd)
            if result.returncode == 0:
                updated.append(model.name)
            else:
                _log(item_logger, f"⚠️  Failed to update beads item {item_id} for {model.name}: {result.stderr.strip()}")

    return created, updated


def _prune_unavailable_models(
    removed_models: set[str],
    existing_items: dict[str, dict[str, Any]],
    cwd: str | None,
    item_logger: Any | None,
) -> list[str]:
    """Close beads items for models that are no longer available."""
    closed: list[str] = []
    for model_name in removed_models:
        item = existing_items.get(model_name)
        if not item:
            continue
        item_id = item.get("id")
        if not item_id:
            continue
        result = _run_bd(["close", str(item_id), "--reason", "Model no longer available"], check=False, cwd=cwd)
        if result.returncode == 0:
            closed.append(model_name)
        else:
            _log(item_logger, f"⚠️  Failed to close beads item {item_id} for {model_name}: {result.stderr.strip()}")
    return closed


def sync_copilot_models(item_logger: Any | None = None) -> AgentStats | None:
    """Sync Copilot models into beads and update local registry."""
    config = get_config()
    sync_cfg = config.model_sync
    start_time = time.time()

    registry = load_registry()
    if _should_skip_sync(sync_cfg, registry, item_logger):
        return AgentStats()

    models = _fetch_and_normalize_models(config.ai_backend.copilot_cli_path, config.command_timeout, item_logger)
    if models is None:
        return None

    now = datetime.now(UTC)
    registry, new_models, removed_models = update_registry(models, registry, now)
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

    if created or updated or closed:
        run_bd_sync_with_retry()

    if created:
        _log(item_logger, f"✅ New beta models added: {', '.join(created)}")
    if updated:
        _log(item_logger, f"♻️  Updated model metadata: {', '.join(updated)}")
    if closed:
        _log(item_logger, f"🧹 Closed unavailable models: {', '.join(closed)}")
    if not created and not updated and not closed:
        _log(item_logger, "✅ Model sync complete (no changes).")

    elapsed = time.time() - start_time
    return AgentStats(wall_duration=elapsed)

