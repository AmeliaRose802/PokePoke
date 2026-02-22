"""Auto-update checker for PokePoke desktop app.

Checks GitHub Releases for newer versions and returns update info.
"""
from __future__ import annotations

import importlib.metadata
import json
import logging
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

GITHUB_REPO = "AmeliaRose802/PokePoke"
RELEASES_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
RELEASES_PAGE_URL = f"https://github.com/{GITHUB_REPO}/releases"


def get_current_version() -> str:
    """Return the installed PokePoke version from package metadata."""
    try:
        return importlib.metadata.version("pokepoke")
    except importlib.metadata.PackageNotFoundError:
        return "0.0.0"


def _parse_version(version: str) -> tuple[int, ...]:
    """Parse a version string into a tuple of integers for comparison."""
    version = version.lstrip("v")
    parts: list[int] = []
    for part in version.split("."):
        try:
            parts.append(int(part))
        except ValueError:
            parts.append(0)
    return tuple(parts)


def check_for_updates(timeout: int = 10) -> dict[str, Any]:
    """Check GitHub Releases for a newer version of PokePoke.

    Args:
        timeout: HTTP request timeout in seconds.

    Returns:
        Dict with keys:
          - current_version: str — the installed version
          - latest_version: str | None — latest release tag (None on error)
          - update_available: bool — True if a newer version exists
          - download_url: str — GitHub releases page URL or direct installer link
          - error: str | None — error message if the check failed
    """
    current = get_current_version()
    result: dict[str, Any] = {
        "current_version": current,
        "latest_version": None,
        "update_available": False,
        "download_url": RELEASES_PAGE_URL,
        "error": None,
    }

    try:
        req = Request(
            RELEASES_API_URL,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": f"PokePoke/{current}",
            },
        )
        with urlopen(req, timeout=timeout) as resp:
            data: dict[str, Any] = json.loads(resp.read().decode("utf-8"))

        tag: str = data.get("tag_name", "")
        if not tag:
            result["error"] = "No release tag found"
            return result

        latest = tag.lstrip("v")
        result["latest_version"] = latest

        if _parse_version(latest) > _parse_version(current):
            result["update_available"] = True

        # Prefer installer asset URL if available
        assets: list[dict[str, Any]] = data.get("assets", [])
        for asset in assets:
            name: str = asset.get("name", "")
            if name.lower().endswith((".exe", ".msi")):
                result["download_url"] = asset.get("browser_download_url", RELEASES_PAGE_URL)
                break

    except URLError as exc:
        reason = getattr(exc, "reason", str(exc))
        logger.warning("Update check failed (network): %s", exc)
        result["error"] = f"Network error: {reason}"
    except TimeoutError:
        logger.warning("Update check timed out")
        result["error"] = "Request timed out"
    except Exception as exc:
        logger.warning("Update check failed: %s", exc)
        result["error"] = str(exc)

    return result
