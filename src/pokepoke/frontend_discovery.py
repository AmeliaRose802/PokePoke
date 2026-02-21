"""Frontend asset discovery utilities for the desktop UI.

This module handles finding React frontend assets in different deployment scenarios:
- Hot reload mode: Proxies to Vite dev server (POKEPOKE_DEV=1)
- Development mode: Uses desktop/dist/ directory
- Package mode: Uses embedded src/pokepoke/static/ assets
- Bundled mode: Uses assets extracted from PyInstaller bundle
"""

from __future__ import annotations

import os
import sys
import subprocess
import tempfile
import shutil
import urllib.request
from pathlib import Path

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
    except Exception:
        return None


def find_frontend_dist() -> Path | None:
    """Locate the React frontend - prioritizing embedded assets for bundled apps."""

    # First, try to use embedded static assets from the package
    try:
        # Handle both regular Python execution and PyInstaller frozen execution
        if getattr(sys, 'frozen', False):
            # Running as PyInstaller bundle - resources should be extracted to filesystem
            import importlib.util
            pokepoke_spec = importlib.util.find_spec('pokepoke.static')
            if pokepoke_spec and pokepoke_spec.origin:
                static_dir = Path(pokepoke_spec.origin).parent
                if static_dir.is_dir() and (static_dir / "index.html").exists():
                    return static_dir
        else:
            # Regular Python execution - check filesystem location first
            # Get the directory of the desktop_ui module
            import pokepoke.desktop_ui as desktop_ui_module
            static_dir = Path(desktop_ui_module.__file__).resolve().parent / "static"
            if static_dir.is_dir() and (static_dir / "index.html").exists():
                return static_dir

            # If not on filesystem, try to extract from package resources
            try:
                import importlib.resources as pkg_resources
                static_ref = pkg_resources.files('pokepoke.static')

                # Check if the package resources exist and have index.html
                if static_ref and (static_ref / "index.html").is_file():
                    # Extract resources to a temporary directory for pywebview
                    temp_dir = Path(tempfile.gettempdir()) / "pokepoke_static"

                    # Check if already extracted and current
                    if temp_dir.is_dir() and (temp_dir / "index.html").exists():
                        return temp_dir

                    # Extract fresh copy
                    temp_dir.mkdir(exist_ok=True)
                    for resource in static_ref.iterdir():
                        if resource.is_file() and resource.name != "__init__.py":
                            with pkg_resources.as_file(resource) as resource_path:
                                shutil.copy2(resource_path, temp_dir / resource.name)
                        elif resource.is_dir():
                            # Handle subdirectories like assets/
                            dest_dir = temp_dir / resource.name
                            dest_dir.mkdir(exist_ok=True)
                            for subresource in resource.iterdir():
                                if subresource.is_file():
                                    with pkg_resources.as_file(subresource) as subresource_path:
                                        shutil.copy2(subresource_path, dest_dir / subresource.name)

                    if (temp_dir / "index.html").exists():
                        return temp_dir

            except (ImportError, AttributeError):
                pass
    except Exception as e:
        # If package resources fail, fall back to filesystem search
        print(f"Warning: Failed to load embedded frontend assets: {e}")

    # Fallback 1: Look relative to desktop_ui module (development mode)
    try:
        import pokepoke.desktop_ui as desktop_ui_module
        src_root = Path(desktop_ui_module.__file__).resolve().parent.parent.parent
        dist = src_root / "desktop" / "dist"
        if dist.is_dir() and (dist / "index.html").exists():
            return dist
    except Exception:
        pass

    # Fallback 2: If in a git worktree, try to find the main repo
    try:
        import pokepoke.desktop_ui as desktop_ui_module
        src_root = Path(desktop_ui_module.__file__).resolve().parent.parent.parent
        result = subprocess.run(
            ["git", "worktree", "list", "--porcelain"],
            cwd=src_root,
            capture_output=True,
            text=True,
            check=True,
        )
        # First worktree in the list is the main repo
        for line in result.stdout.splitlines():
            if line.startswith("worktree "):
                main_repo = Path(line.split(None, 1)[1])
                dist = main_repo / "desktop" / "dist"
                if dist.is_dir() and (dist / "index.html").exists():
                    return dist
                break
    except Exception:
        pass

    return None
