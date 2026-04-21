"""Model selection for A/B testing different LLM models.

Selects models from a configured candidate pool using performance-weighted
random selection.  Models with higher historical success rates are chosen
more often, while models with insufficient data get equal opportunity.

When assignment rules are configured, the first matching rule determines the
model (and optionally the prompt template) for a work item.  If no rule
matches, the system falls back to weighted A/B selection.
"""

import logging
import random

from pokepoke.config import AssignmentRule, get_config
from pokepoke.models.model_stats_store import get_model_weights
from pokepoke.types import BeadsWorkItem

logger = logging.getLogger(__name__)

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


def _get_registry_candidates() -> list[str]:
    """Get candidate models from the registry when no explicit candidates configured.

    Returns:
        List of available model names from the registry, or empty list if
        no registry data is available.
    """
    from pokepoke.models.model_sync import get_available_model_names

    available = get_available_model_names()
    if available:
        logger.info(
            f"   [Selection] Using {len(available)} models from registry as candidates"
        )
    return available


def _filter_available_models(candidates: list[str]) -> list[str]:
    """Filter candidate models to only those currently available in the registry.

    Args:
        candidates: List of model names to filter.

    Returns:
        Filtered list containing only models marked as available in the registry.
        If no models are available, returns the original list to avoid breaking
        the selection logic (better to try an unavailable model than to crash).
    """
    from pokepoke.models.model_sync import get_available_model_names

    available = set(get_available_model_names())
    if not available:
        # No registry data available, pass through candidates
        logger.debug("   [Selection] No model registry data; using all candidates")
        return candidates

    filtered = [m for m in candidates if m in available]

    if not filtered:
        # None of the candidates are available - log warning but return originals
        # to avoid breaking the system
        logger.warning(
            f"   ⚠️  [Selection] No candidates are available in registry. "
            f"Candidates: {candidates}, Available: {sorted(available)[:5]}..."
        )
        return candidates

    if len(filtered) < len(candidates):
        removed = set(candidates) - set(filtered)
        logger.info(
            f"   [Selection] Filtered out {len(removed)} unavailable model(s): {sorted(removed)}"
        )

    return filtered


def select_model_for_item(item: BeadsWorkItem) -> str:
    """Select a model for a work item.

    Evaluates assignment rules first; if a rule matches and specifies a
    model, that model is returned.  Otherwise falls back to
    performance-weighted random selection from the candidate pool.

    Only selects from models that are currently marked as available in the
    model registry to avoid invocation failures on deprecated/removed models.

    Args:
        item: The work item to select a model for.

    Returns:
        The model name string to use for this work item.
    """
    config = get_config()

    # Check assignment rules first
    rule_model, _ = get_assignment_for_item(item)
    if rule_model is not None:
        logger.info(f"   [A/B] Assigned model '{rule_model}' to {item.id} "
              f"(matched assignment rule)")
        return rule_model

    # Check economy mode routing
    if config.economy_mode.enabled:
        complexity = get_item_complexity(item)

        if complexity == "simple":
            economy_model = config.economy_mode.simple_model
        elif complexity == "medium":
            economy_model = config.economy_mode.medium_model
        else:  # complex
            economy_model = config.economy_mode.complex_model

        logger.info(f"   [Economy] Assigned model '{economy_model}' to {item.id} "
              f"(complexity: {complexity}, economy mode enabled)")
        return economy_model

    # Check fallback setting
    fallback = config.assignment.fallback
    if fallback != "weighted":
        logger.info(f"   [A/B] Assigned model '{fallback}' to {item.id} "
              f"(assignment fallback)")
        return fallback

    # Default: weighted A/B selection
    candidates = config.models.candidate_models

    if not candidates:
        # Try registry-discovered models first, then fall back to default+fallback
        candidates = _get_registry_candidates()
        if not candidates:
            candidates = list(dict.fromkeys(
                [config.models.default, config.models.fallback]
            ))

    # Filter to only available models
    candidates = _filter_available_models(candidates)

    # Build weights for each candidate model
    historical = get_model_weights()
    weights = [historical.get(m, 1.0) for m in candidates]

    model = random.choices(candidates, weights=weights, k=1)[0]

    # Determine if selection was weighted or uniform
    uniform = all(w == weights[0] for w in weights)
    mode = "uniform" if uniform else "weighted"
    logger.info(f"   [A/B] Assigned model '{model}' to {item.id} "
          f"({mode}, {len(candidates)} candidates)")
    return model


def select_gate_model(work_model: str, item_id: str) -> str:
    """Select a different model for gate agent verification.

    Ensures the gate agent uses a different model than the work completion
    model to improve code review objectivity by preventing the same AI model
    from both implementing and validating its own work.

    Only selects from models that are currently marked as available in the
    model registry to avoid invocation failures on deprecated/removed models.

    Args:
        work_model: The model used for work completion.
        item_id: The work item ID (used for logging context).

    Returns:
        A different model name, never the same as work_model.
    """
    config = get_config()
    candidates = config.models.candidate_models

    if not candidates:
        # Try registry-discovered models first, then fall back to default+fallback
        candidates = _get_registry_candidates()
        if not candidates:
            candidates = list(dict.fromkeys(
                [config.models.default, config.models.fallback]
            ))

    # Filter to only available models
    candidates = _filter_available_models(candidates)

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
                logger.warning(f"   ⚠️  [Gate] No alternative model available to {work_model}, using same model")
                return gate_model
        logger.info(f"   [Gate] Using fallback model '{gate_model}' (work model: {work_model})")
        return gate_model

    # Select from available models using performance weights
    historical = get_model_weights()
    weights = [historical.get(m, 1.0) for m in available]

    gate_model = random.choices(available, weights=weights, k=1)[0]

    # Determine if selection was weighted or uniform
    uniform = all(w == weights[0] for w in weights)
    mode = "uniform" if uniform else "weighted"
    logger.info(f"   [Gate] Assigned model '{gate_model}' for verification "
          f"({mode}, {len(available)} candidates, excluding work model '{work_model}')")

    return gate_model


def get_item_complexity(item: BeadsWorkItem) -> str:
    """Determine complexity level of a work item from labels or heuristics.

    Checks for explicit complexity tags in item labels first, then falls back
    to heuristics based on item properties like priority and issue type.

    Args:
        item: The work item to analyze.

    Returns:
        Complexity level: "simple", "medium", or "complex".
    """
    # Check for explicit complexity tags in labels
    if item.labels:
        for label in item.labels:
            label_lower = label.lower().strip()

            # Support both "complexity:simple" and "simple" formats
            if label_lower in ("complexity:simple", "simple"):
                return "simple"
            elif label_lower in ("complexity:medium", "medium"):
                return "medium"
            elif label_lower in ("complexity:complex", "complex"):
                return "complex"

    # Fallback heuristics based on item properties
    # Priority-based classification (lower priority = higher urgency = simpler fixes)
    if item.priority <= 1:
        return "simple"  # High priority = urgent simple fixes
    elif item.priority <= 3:
        return "medium"  # Medium priority = standard work
    else:
        return "complex"  # Low priority = complex features

    # Note: Could extend heuristics based on issue_type, title keywords, etc.
    # For now, priority-based classification provides reasonable defaults
