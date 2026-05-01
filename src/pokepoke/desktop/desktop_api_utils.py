"""Shared utilities for desktop API extension modules.

Consolidates helpers used by both ``desktop_api_ext`` and ``desktop_api_setup``
to avoid duplication.
"""
from __future__ import annotations

try:
    import yaml  # type: ignore[import-untyped]  # noqa: F401
    HAS_YAML = True
except ImportError:
    HAS_YAML = False


def coerce_process_output(output: str | None) -> str | None:
    """Normalise subprocess output: strip whitespace and convert blanks to ``None``."""
    if output is None:
        return None
    stripped = output.strip()
    return stripped or None
