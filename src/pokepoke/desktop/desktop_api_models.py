"""Desktop API extension for model discovery and sync."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pokepoke.desktop.desktop_api import DesktopAPI


def get_available_models(self: DesktopAPI) -> dict[str, Any]:
    """Return available models from the SDK model registry.

    Returns a dict with:
      - models: list of available model name strings
      - last_sync: ISO timestamp of last model sync or None
      - removed_from_config: list of models that were pruned from config
    """
    from pokepoke.models.model_sync import (
        get_available_model_names,
        get_registry_last_sync,
        prune_unavailable_from_config,
    )

    models = get_available_model_names()
    last_sync = get_registry_last_sync()

    removed: list[str] = []
    if models:
        removed = prune_unavailable_from_config()

    return {
        "models": models,
        "last_sync": last_sync,
        "removed_from_config": removed,
    }
