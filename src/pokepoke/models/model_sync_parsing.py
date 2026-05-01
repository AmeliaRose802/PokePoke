"""Model sync parsing helpers."""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CopilotModelSnapshot:
    """Normalized Copilot model metadata snapshot."""
    name: str
    status: str | None
    capabilities: list[str]
    context_window: int | None
    pricing: dict[str, Any] | None
    version: str | None
    tags: list[str]


def _is_valid_model_name(name: str) -> bool:
    """Check if a string looks like a valid model name.

    Rejects:
    - Empty/whitespace strings
    - Pure markdown table separators (lines like "|---|---|")
    - Markdown formatting markers
    - Common table headers/noise words
    """
    if not name or not name.strip():
        return False

    name = name.strip()

    # Reject pure separator lines (only pipes, dashes, equals, spaces, tabs)
    if all(c in "|-=- \t" for c in name):
        return False

    # Reject markdown formatting markers as the entire name
    if name in ("**", "__", "`", "~~"):
        return False

    # Reject common table artifacts/headers
    invalid_full_matches = [
        "|", "Use", "Current", "Model", "Tier", "Status", "ID", "Name"
    ]
    if name in invalid_full_matches:
        return False

    # Reject names starting with markdown formatting
    if name.startswith("**") or name.startswith("__") or name.startswith("~~"):
        return False

    # Valid model names should have at least one alphanumeric character
    # e.g., "claude-opus-4.6", "gpt-5.1-codex", "goldeneye"
    if not any(c.isalnum() for c in name):
        return False

    return True


def _normalize_capabilities(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, list):
        return [str(item).strip() for item in raw if str(item).strip()]
    if isinstance(raw, str):
        return [part.strip() for part in raw.split(",") if part.strip()]
    return [str(raw).strip()] if str(raw).strip() else []


def _normalize_tags(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, list):
        return [str(item).strip() for item in raw if str(item).strip()]
    if isinstance(raw, str):
        return [part.strip() for part in raw.split(",") if part.strip()]
    return [str(raw).strip()] if str(raw).strip() else []


def normalize_model_entry(entry: dict[str, Any]) -> CopilotModelSnapshot | None:
    name = (
        entry.get("id")
        or entry.get("name")
        or entry.get("model")
        or entry.get("slug")
        or entry.get("identifier")
    )
    if not isinstance(name, str) or not name.strip():
        return None
    status = entry.get("status") or entry.get("tier") or entry.get("availability")
    if status is None:
        policy = entry.get("policy")
        if isinstance(policy, dict):
            status = policy.get("state")
    if isinstance(status, str):
        status = status.strip()
    else:
        status = None
    capabilities = _normalize_capabilities(entry.get("capabilities") or entry.get("features"))
    tags = _normalize_tags(entry.get("tags") or entry.get("labels"))
    # Extract context window from SDK capabilities or flat fields
    context_window = entry.get("context_window") or entry.get("contextWindow") or entry.get("context")
    if context_window is None:
        caps = entry.get("capabilities")
        if isinstance(caps, dict):
            limits = caps.get("limits", {})
            context_window = limits.get("max_context_window_tokens")
    try:
        context_value = int(context_window) if context_window is not None else None
    except (TypeError, ValueError):
        context_value = None
    # Extract pricing from SDK billing or flat fields
    pricing = entry.get("pricing") or entry.get("price")
    if not isinstance(pricing, dict):
        billing = entry.get("billing")
        if isinstance(billing, dict) and "multiplier" in billing:
            pricing = {"multiplier": billing["multiplier"]}
        else:
            pricing = None
    version = entry.get("version") or entry.get("release")
    if isinstance(version, str):
        version = version.strip()
    else:
        version = None
    return CopilotModelSnapshot(
        name=name.strip(),
        status=status,
        capabilities=capabilities,
        context_window=context_value,
        pricing=pricing,
        version=version,
        tags=tags,
    )


def is_beta_model(model: CopilotModelSnapshot, include_preview: bool) -> bool:
    tokens = [
        model.status or "",
        model.name,
        " ".join(model.tags),
        " ".join(model.capabilities),
    ]
    haystack = " ".join(tokens).lower()
    keywords = ["beta", "experimental"]
    if include_preview:
        keywords.append("preview")
    return any(keyword in haystack for keyword in keywords)
