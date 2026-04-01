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
            if "name" in entry:
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
        result.append({"name": parts[0], "raw": line})
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
        entry.get("name")
        or entry.get("id")
        or entry.get("model")
        or entry.get("slug")
        or entry.get("identifier")
    )
    if not isinstance(name, str) or not name.strip():
        return None
    status = entry.get("status") or entry.get("tier") or entry.get("availability")
    if isinstance(status, str):
        status = status.strip()
    else:
        status = None
    capabilities = _normalize_capabilities(entry.get("capabilities") or entry.get("features"))
    tags = _normalize_tags(entry.get("tags") or entry.get("labels"))
    context_window = entry.get("context_window") or entry.get("contextWindow") or entry.get("context")
    try:
        context_value = int(context_window) if context_window is not None else None
    except (TypeError, ValueError):
        context_value = None
    pricing = entry.get("pricing") or entry.get("price")
    if not isinstance(pricing, dict):
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
