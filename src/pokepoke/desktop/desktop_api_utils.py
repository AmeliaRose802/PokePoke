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


def require_yaml(action: str = "perform this operation") -> None:
    """Raise ``ImportError`` if PyYAML is not installed.

    Args:
        action: A short description of what needs YAML (used in the error message).
    """
    if not HAS_YAML:
        raise ImportError(
            f"PyYAML is required to {action}. Install it with: pip install pyyaml"
        )


def coerce_process_output(output: str | None) -> str | None:
    """Normalise subprocess output: strip whitespace and convert blanks to ``None``."""
    if output is None:
        return None
    stripped = output.strip()
    return stripped or None
