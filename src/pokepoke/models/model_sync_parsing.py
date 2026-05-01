"""Model sync parsing helpers."""

import json
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


def _extract_json_payload(output: str) -> Any | None:
    filtered_lines = [
        line for line in output.splitlines()
        if line.strip() and not line.strip().startswith(("Warning:", "Note:", "Hint:"))
    ]
    json_start = next(
        (i for i, line in enumerate(filtered_lines)
         if line.strip().startswith("[") or line.strip().startswith("{")),
        None,
    )
    if json_start is None:
        return None
    json_text = "\n".join(filtered_lines[json_start:])
    try:
        return json.loads(json_text)
    except json.JSONDecodeError:
        return None


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


def _parse_markdown_table(output: str) -> list[dict[str, Any]]:
    """Parse a markdown table into a list of dicts."""
    lines = output.splitlines()
    models: list[dict[str, Any]] = []

    # Find the header row (contains |)
    header_idx = None
    for i, line in enumerate(lines):
        if "|" in line and "Model" in line:
            header_idx = i
            break

    if header_idx is None:
        return []

    # Parse header to get column names
    header_line = lines[header_idx]
    headers = [h.strip() for h in header_line.split("|") if h.strip()]

    # Skip separator row (|---|---|)
    data_start = header_idx + 2

    for line in lines[data_start:]:
        if "|" not in line:
            continue
        # Stop at non-table content
        stripped = line.strip()

        # Skip separator rows (lines with only | - = characters)
        if all(c in "|-=- \t" for c in stripped):
            continue

        is_table_row = stripped.startswith("|") or stripped.endswith("|") or any(c == "|" for c in stripped)
        if not is_table_row:
            break
        cells = [c.strip().strip("`") for c in line.split("|") if c.strip()]
        if len(cells) >= 2:
            # Map to dict using headers
            entry: dict[str, Any] = {}
            for j, header in enumerate(headers):
                if j < len(cells):
                    key = header.lower().replace(" ", "_")
                    if key == "id":
                        entry["name"] = cells[j]
                    elif key == "model":
                        entry["display_name"] = cells[j]
                    elif key == "tier":
                        entry["status"] = cells[j]
                    else:
                        entry[key] = cells[j]
            # Validate the model name before adding
            if "name" in entry and _is_valid_model_name(entry["name"]):
                models.append(entry)
    return models


def _parse_models_from_text(output: str) -> list[dict[str, Any]]:
    # First try markdown table format (Copilot CLI returns this)
    if "|" in output and "Model" in output:
        table_models = _parse_markdown_table(output)
        if table_models:
            return table_models

    # Fallback to simple line-based parsing
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    if not lines:
        return []
    if any(token in lines[0].lower() for token in ("model", "name", "status")):
        lines = lines[1:]
    result: list[dict[str, Any]] = []
    for line in lines:
        parts = line.split()
        if not parts:
            continue
        model_name = parts[0]
        # Validate model names in fallback parser too
        if _is_valid_model_name(model_name):
            result.append({"name": model_name, "raw": line})
    return result


def parse_copilot_models_output(output: str) -> list[dict[str, Any]]:
    """Parse Copilot output into a list of model dicts."""
    payload = _extract_json_payload(output)
    if isinstance(payload, list):
        return [p for p in payload if isinstance(p, dict)]
    if isinstance(payload, dict):
        for key in ("models", "data", "items"):
            value = payload.get(key)
            if isinstance(value, list):
                return [p for p in value if isinstance(p, dict)]
    return _parse_models_from_text(output)


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
