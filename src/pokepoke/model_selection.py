"""Model selection for A/B testing different LLM models.

Selects models from a configured candidate pool using performance-weighted
random selection.  Models with higher historical success rates are chosen
more often, while models with insufficient data get equal opportunity.
"""

import random

from pokepoke.config import get_config
from pokepoke.model_stats_store import get_model_weights


def select_model_for_item(item_id: str) -> str:
    """Select a model for a work item from the configured candidate list.

    Uses performance-weighted random selection when historical data is
    available.  Models with fewer than ``min_attempts`` runs are given
    a neutral weight of 1.0 so they still get sampled.

    Args:
        item_id: The work item ID (used for logging context).

    Returns:
        The model name string to use for this work item.
    """
    config = get_config()
    candidates = config.models.candidate_models

    if not candidates:
        return config.models.default

    # Build weights for each candidate model
    historical = get_model_weights()
    weights = [historical.get(m, 1.0) for m in candidates]

    model = random.choices(candidates, weights=weights, k=1)[0]

    # Determine if selection was weighted or uniform
    uniform = all(w == weights[0] for w in weights)
    mode = "uniform" if uniform else "weighted"
    print(f"   [A/B] Assigned model '{model}' to {item_id} "
          f"({mode}, {len(candidates)} candidates)")
    return model
