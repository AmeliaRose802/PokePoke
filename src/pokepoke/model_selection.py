"""Model selection for A/B testing different LLM models.

Randomly assigns work items to one of a configured set of candidate models,
enabling comparison of quality and performance across models.
"""

import random
from typing import Optional

from pokepoke.config import get_config


def select_model_for_item(item_id: str) -> str:
    """Select a model for a work item from the configured candidate list.

    If candidate_models is configured and non-empty, randomly picks one.
    Otherwise falls back to the default model from config.

    Args:
        item_id: The work item ID (used for logging context).

    Returns:
        The model name string to use for this work item.
    """
    config = get_config()
    candidates = config.models.candidate_models

    if candidates:
        model = random.choice(candidates)
        print(f"   [A/B] Assigned model '{model}' to {item_id} "
              f"(from {len(candidates)} candidates)")
        return model

    return config.models.default
