"""Frontend asset discovery utilities for the desktop UI.

This module handles finding React frontend assets in different deployment scenarios:
- Hot reload mode: Proxies to Vite dev server (POKEPOKE_DEV=1)
- Development mode: Uses desktop/dist/ directory
- Package mode: Uses embedded src/pokepoke/static/ assets
- Bundled mode: Uses assets extracted from PyInstaller bundle
"""

import logging
import os
import shutil
import sys
import tempfile
import urllib.request
from pathlib import Path

from pokepoke.git.git_helpers import run_git

logger = logging.getLogger(__name__)

# Default Vite dev server URL
VITE_DEV_SERVER_URL = "http://localhost:5173"


def find_dev_server_url() -> str | None:
    """Return the Vite dev server URL if dev mode is enabled and server is reachable.

    Set ``POKEPOKE_DEV=1`` to enable.  Optionally set ``POKEPOKE_DEV_URL``
    to override the default ``http://localhost:5173``.

    Returns the URL string when the dev server is running, or ``None``.
    """
    if os.environ.get("POKEPOKE_DEV", "").lower() not in ("1", "true"):
        return None

    url = os.environ.get("POKEPOKE_DEV_URL", VITE_DEV_SERVER_URL)

    try:
        req = urllib.request.Request(url, method="HEAD")
        with urllib.request.urlopen(req, timeout=2):
            return url
    except Exception as e:
        logger.debug(f"Dev server at {url} not available: {e}")
        return None


def _has_index_html(directory: Path) -> bool:
    """Check if a directory contains an index.html file."""
    return directory.is_dir() and (directory / "index.html").exists()


def _find_frozen_static() -> Path | None:
    """Find static assets in a PyInstaller frozen bundle."""
    meipass = Path(getattr(sys, '_MEIPASS', ''))
    static_dir = meipass / "pokepoke" / "static"
    return static_dir if _has_index_html(static_dir) else None


def _find_filesystem_static() -> Path | None:
    """Find static assets on the filesystem next to the desktop_ui module."""
    import pokepoke.desktop.desktop_ui as desktop_ui_module
    static_dir = Path(desktop_ui_module.__file__).resolve().parent / "static"
    return static_dir if _has_index_html(static_dir) else None


def _extract_package_resources() -> Path | None:
    """Extract frontend assets from package resources to a temp directory."""
    import importlib.resources as pkg_resources

    static_ref = pkg_resources.files('pokepoke.static')
    if not static_ref or not (static_ref / "index.html").is_file():
        return None

    temp_dir = Path(tempfile.gettempdir()) / "pokepoke_static"

    # Check if cached extraction is still valid by comparing index.html mtimes
    cached_index = temp_dir / "index.html"
    if _has_index_html(temp_dir):
        try:
            with pkg_resources.as_file(static_ref / "index.html") as src_index:
                if src_index.stat().st_mtime <= cached_index.stat().st_mtime:
                    return temp_dir
            # Source is newer — wipe stale cache and re-extract below
            logger.info("Frontend assets changed, clearing stale cache at %s", temp_dir)
            shutil.rmtree(temp_dir)
        except Exception:
            # Can't compare — re-extract to be safe
            logger.debug("Cache freshness check failed, re-extracting", exc_info=True)
            shutil.rmtree(temp_dir, ignore_errors=True)

    temp_dir.mkdir(exist_ok=True)
    for resource in static_ref.iterdir():
        if resource.is_file() and resource.name != "__init__.py":
            with pkg_resources.as_file(resource) as resource_path:
                shutil.copy2(resource_path, temp_dir / resource.name)
        elif resource.is_dir():
            dest_dir = temp_dir / resource.name
            dest_dir.mkdir(exist_ok=True)
            for subresource in resource.iterdir():
                if subresource.is_file():
                    with pkg_resources.as_file(subresource) as subresource_path:
                        shutil.copy2(subresource_path, dest_dir / subresource.name)

    return temp_dir if _has_index_html(temp_dir) else None


def _get_src_root() -> Path:
    """Get the source root directory relative to the desktop_ui module."""
    import pokepoke.desktop.desktop_ui as desktop_ui_module
    return Path(desktop_ui_module.__file__).resolve().parent.parent.parent


def _find_dev_dist() -> Path | None:
    """Find frontend dist in desktop/dist/ (development mode)."""
    try:
        dist = _get_src_root() / "desktop" / "dist"
        return dist if _has_index_html(dist) else None
    except Exception as e:
        logger.debug(f"Failed to locate dist folder relative to desktop_ui module: {e}")
        return None


def _find_worktree_dist() -> Path | None:
    """Find frontend dist in the main repo when running from a git worktree."""
    try:
        src_root = _get_src_root()
        result = run_git(
            ["git", "worktree", "list", "--porcelain"],
            cwd=str(src_root),
        )
        for line in result.stdout.splitlines():
            if line.startswith("worktree "):
                main_repo = Path(line.split(None, 1)[1])
                dist = main_repo / "desktop" / "dist"
                return dist if _has_index_html(dist) else None
    except Exception as e:
        logger.debug(f"Failed to locate dist folder from git worktree: {e}")
    return None


def find_frontend_dist() -> Path | None:
    """Locate the React frontend - prioritizing embedded assets for bundled apps."""

    # First, try to use embedded static assets from the package
    try:
        if getattr(sys, 'frozen', False):
            result = _find_frozen_static()
            if result:
                return result
        else:
            result = _find_filesystem_static()
            if result:
                return result

            try:
                result = _extract_package_resources()
                if result:
                    return result
            except (ImportError, AttributeError):
                pass  # pkg_resources unavailable; fall through to dev-mode paths
    except Exception as e:
        logger.error(f"Warning: Failed to load embedded frontend assets: {e}")

    # Fallback: development mode, then git worktree
    return _find_dev_dist() or _find_worktree_dist()
