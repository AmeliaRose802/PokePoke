"""Model sync configuration parsing."""

from dataclasses import dataclass, field
from typing import Any

DEFAULT_MODEL_SYNC_LABELS = ["model", "beta", "copilot"]


@dataclass
class ModelSyncConfig:
    """Configuration for Copilot model discovery sync."""
    enabled: bool = True
    interval_minutes: int = 60
    beta_only: bool = True
    include_preview: bool = True
    prune_unavailable: bool = False
    create_beads_items: bool = True
    issue_type: str = "task"
    priority: int = 2
    labels: list[str] = field(default_factory=lambda: list(DEFAULT_MODEL_SYNC_LABELS))


def parse_model_sync_config(sync_data: dict[str, Any]) -> ModelSyncConfig:
    """Parse model sync config from a dictionary."""
    labels = sync_data.get("labels")
    if labels is None:
        label_list = list(DEFAULT_MODEL_SYNC_LABELS)
    elif isinstance(labels, str):
        label_list = [label.strip() for label in labels.split(",") if label.strip()]
    elif isinstance(labels, list):
        label_list = [str(label).strip() for label in labels if str(label).strip()]
    else:
        label_list = list(DEFAULT_MODEL_SYNC_LABELS)
    return ModelSyncConfig(
        enabled=bool(sync_data.get("enabled", True)),
        interval_minutes=max(1, int(sync_data.get("interval_minutes", 60))),
        beta_only=bool(sync_data.get("beta_only", True)),
        include_preview=bool(sync_data.get("include_preview", True)),
        prune_unavailable=bool(sync_data.get("prune_unavailable", False)),
        create_beads_items=bool(sync_data.get("create_beads_items", True)),
        issue_type=str(sync_data.get("issue_type", "task")),
        priority=int(sync_data.get("priority", 2)),
        labels=label_list,
    )
