"""Model selection for A/B testing different LLM models.

Selects models from a configured candidate pool using performance-weighted
random selection.  Models with higher historical success rates are chosen
more often, while models with insufficient data get equal opportunity.

When assignment rules are configured, the first matching rule determines the
model (and optionally the prompt template) for a work item.  If no rule
matches, the system falls back to weighted A/B selection.
"""

import random

from pokepoke.config import get_config, AssignmentRule
from pokepoke.model_stats_store import get_model_weights
from pokepoke.types import BeadsWorkItem


def _matches_rule(rule: AssignmentRule, item: BeadsWorkItem) -> bool:
    """Check whether a work item matches an assignment rule's criteria.

    All specified criteria must match (AND logic).  Criteria that are
    ``None`` are treated as wildcards (always match).
    """
    m = rule.match

    if m.issue_type is not None and item.issue_type != m.issue_type:
        return False

    if m.priority_max is not None and item.priority > m.priority_max:
        return False

    if m.labels is not None:
        item_labels = set(item.labels or [])
        if not item_labels.intersection(m.labels):
            return False

    return True


def get_assignment_for_item(item: BeadsWorkItem) -> tuple[str | None, str | None]:
    """Return (model, prompt_template) for *item* based on assignment rules.

    Returns ``(None, None)`` when no rule matches so the caller can fall
    back to default behaviour.
    """
    config = get_config()
    for rule in config.assignment.rules:
        if _matches_rule(rule, item):
            return rule.model, rule.prompt_template
    return None, None


def select_model_for_item(item: BeadsWorkItem) -> str:
    """Select a model for a work item.

    Evaluates assignment rules first; if a rule matches and specifies a
    model, that model is returned.  Otherwise falls back to
    performance-weighted random selection from the candidate pool.

    Args:
        item: The work item to select a model for.

    Returns:
        The model name string to use for this work item.
    """
    config = get_config()

    # Check assignment rules first
    rule_model, _ = get_assignment_for_item(item)
    if rule_model is not None:
        print(f"   [A/B] Assigned model '{rule_model}' to {item.id} "
              f"(matched assignment rule)")
        return rule_model

    # Check fallback setting
    fallback = config.assignment.fallback
    if fallback != "weighted":
        print(f"   [A/B] Assigned model '{fallback}' to {item.id} "
              f"(assignment fallback)")
        return fallback

    # Default: weighted A/B selection
    candidates = config.models.candidate_models

    if not candidates:
        # Synthesize from default + fallback so weighted selection still runs
        candidates = list(dict.fromkeys(
            [config.models.default, config.models.fallback]
        ))

    # Build weights for each candidate model
    historical = get_model_weights()
    weights = [historical.get(m, 1.0) for m in candidates]

    model = random.choices(candidates, weights=weights, k=1)[0]

    # Determine if selection was weighted or uniform
    uniform = all(w == weights[0] for w in weights)
    mode = "uniform" if uniform else "weighted"
    print(f"   [A/B] Assigned model '{model}' to {item.id} "
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

    if not candidates:
        # Synthesize from default + fallback so weighted selection still runs
        candidates = list(dict.fromkeys(
            [config.models.default, config.models.fallback]
        ))

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
