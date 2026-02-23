"""Project-level validation utilities for directory/repo checks."""

from __future__ import annotations

import subprocess
from pathlib import Path


def is_git_repo(path: Path) -> bool:
    """Check if a directory is (or is inside) a git repository."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--git-dir"],
            capture_output=True,
            text=True,
            cwd=str(path),
            timeout=10,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def resolve_git_toplevel(path: Path) -> Path | None:
    """Resolve the git repository root for the given path."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            cwd=str(path),
            timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            return Path(result.stdout.strip()).resolve()
    except (subprocess.TimeoutExpired, OSError):
        pass
    return None


def has_pokepoke_config(project_path: Path) -> bool:
    """Check if .pokepoke/ contains an actual config file."""
    pokepoke_dir = project_path / ".pokepoke"
    if not pokepoke_dir.is_dir():
        return False
    return any(
        (pokepoke_dir / name).is_file()
        for name in ("config.yaml", "config.yml", "config.json")
    )


def check_beads_available(path: Path) -> bool:
    """Check if beads is initialized for the given project directory."""
    try:
        result = subprocess.run(
            ["bd", "info", "--json"],
            capture_output=True,
            text=True,
            cwd=str(path),
            timeout=10,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False
