"""Beads integration helpers for Copilot model sync."""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from pokepoke.beads.beads_query import _parse_beads_json, _run_bd
from pokepoke.models.model_sync_parsing import CopilotModelSnapshot, is_beta_model

logger = logging.getLogger(__name__)


def _log(item_logger: Any | None, message: str) -> None:
    logger.info(message)
    if item_logger is not None:
        item_logger.log(message + "\n")


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


def _build_model_metadata(
    model: CopilotModelSnapshot, discovered_at: str, last_seen: str,
) -> dict[str, Any]:
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


def _sync_beads_items(  # noqa: PLR0913
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
                # Record in session stats so dashboard ADDED counter updates
                from pokepoke.beads.sdk_beads_tracker import parse_created_items, record_items_created
                items = parse_created_items(result.stdout or "")
                if not items:
                    items = [(f"model-sync-{model.name}", title)]
                record_items_created(items)
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
        result = _run_bd(
            ["close", str(item_id), "--reason", "Model no longer available"],
            check=False, cwd=cwd,
        )
        if result.returncode == 0:
            closed.append(model_name)
        else:
            _log(
                item_logger,
                f"⚠️  Failed to close beads item {item_id} for {model_name}: {result.stderr.strip()}",
            )
    return closed
