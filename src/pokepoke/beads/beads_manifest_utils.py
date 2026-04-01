"""Shared manifest utilities for beads tracking.

Provides persistent tracking for failed unassign operations,
allowing recovery without creating circular dependencies between
beads_management and beads_recovery modules.
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import cast

from pokepoke.worktrees.coordination import manifest_lock

logger = logging.getLogger(__name__)


def _get_failed_unassign_manifest_path() -> Path:
    """Get the path to the failed unassigns manifest file."""
    return Path(".pokepoke") / "failed_unassigns.json"


def _load_failed_unassign_manifest() -> dict[str, dict[str, str]]:
    """Load the failed unassigns manifest."""
    manifest_path = _get_failed_unassign_manifest_path()
    if not manifest_path.exists():
        return {}
    try:
        with open(manifest_path, encoding='utf-8') as f:
            raw = json.load(f)
            if isinstance(raw, dict):
                return cast(dict[str, dict[str, str]], raw)
            return {}
    except (json.JSONDecodeError, OSError):
        return {}


def _save_failed_unassign_manifest(manifest: dict[str, dict[str, str]]) -> None:
    """Save the failed unassigns manifest."""
    manifest_path = _get_failed_unassign_manifest_path()
    try:
        manifest_path.parent.mkdir(exist_ok=True)
        # Write atomically via a temp file, then rename.
        tmp = manifest_path.with_suffix('.tmp')
        tmp.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding='utf-8')
        tmp.replace(manifest_path)
    except OSError as e:
        logger.warning('Failed to save unassign manifest: %s', e)


def add_failed_unassign(item_id: str, reason: str) -> None:
    """Track an item whose unassign failed for later recovery."""
    with manifest_lock():
        manifest = _load_failed_unassign_manifest()
        manifest[item_id] = {
            "reason": reason,
            "timestamp": datetime.now().isoformat(),
        }
        _save_failed_unassign_manifest(manifest)


def remove_failed_unassign(item_id: str) -> None:
    """Remove an item from the failed-unassign manifest after recovery."""
    with manifest_lock():
        manifest = _load_failed_unassign_manifest()
        if item_id in manifest:
            del manifest[item_id]
            _save_failed_unassign_manifest(manifest)
