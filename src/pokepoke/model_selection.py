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


def select_gate_model(work_model: str, item_id: str) -> str:
    """Select a different model for gate agent verification.
    
    Ensures the gate agent uses a different model than the work completion
    model to improve code review objectivity by preventing the same AI model
    from both implementing and validating its own work.
    
    Args:
        work_model: The model used for work completion.
        item_id: The work item ID (used for logging context).
        
    Returns:
        A different model name, never the same as work_model.
    """
    config = get_config()
    candidates = config.models.candidate_models
    
    # Filter out the work model from candidates
    available = [m for m in candidates if m != work_model]
    
    # If no candidates or only one candidate (which matches work_model),
    # use fallback model
    if not available:
        gate_model = config.models.fallback
        # If fallback is same as work model, use default
        if gate_model == work_model:
            gate_model = config.models.default
            # If default is also same as work model, we have a config issue
            # but proceed with default anyway (better than failing)
            if gate_model == work_model:
                print(f"   ⚠️  [Gate] No alternative model available to {work_model}, using same model")
                return gate_model
        print(f"   [Gate] Using fallback model '{gate_model}' (work model: {work_model})")
        return gate_model
    
    # Select from available models using performance weights
    historical = get_model_weights()
    weights = [historical.get(m, 1.0) for m in available]
    
    gate_model = random.choices(available, weights=weights, k=1)[0]
    
    # Determine if selection was weighted or uniform
    uniform = all(w == weights[0] for w in weights)
    mode = "uniform" if uniform else "weighted"
    print(f"   [Gate] Assigned model '{gate_model}' for verification "
          f"({mode}, {len(available)} candidates, excluding work model '{work_model}')")
    
    return gate_model
