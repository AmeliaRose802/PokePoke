"""Project-level validation utilities for directory/repo checks."""

from __future__ import annotations

import subprocess
from pathlib import Path

from .constants import BEADS_DIR


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
    """Check if beads is initialized for the given project directory.

    Since beads v0.56+ uses a Dolt server, ``bd info --json`` fails when the
    server isn't running.  Instead we check for the ``.beads/`` directory
    which is a reliable filesystem indicator that ``bd init`` has been run.
    """
    beads_dir = path / BEADS_DIR
    if not beads_dir.is_dir():
        return False
    # Verify it has at least a config file (not just an empty directory)
    return any(
        (beads_dir / name).exists()
        for name in ("config.yaml", "config.yml", "issues.jsonl", "beads.db")
    )


def ensure_project_ready(
    interactive: bool,
    desktop_ui: object | None = None,
) -> bool:
    """Check that the project environment is set up and ready.

    When running in desktop mode and setup is needed, waits for the
    setup wizard to complete. In CLI interactive mode, offers to run
    ``bd init`` if beads is not available.

    Args:
        interactive: Whether the orchestrator is in interactive mode.
        desktop_ui: A DesktopUI instance (or None for CLI mode).

    Returns:
        True if the project is ready to run.
    """
    from pokepoke.repo_check import (
        check_beads_available as check_beads_cli,
        initialize_beads_repo,
    )

    cwd = Path.cwd().resolve()
    git_root = resolve_git_toplevel(cwd)
    project_root = git_root or cwd

    needs_setup = (
        (not is_git_repo(cwd))
        or (not has_pokepoke_config(project_root))
        or (not check_beads_available(project_root))
    )

    # Desktop mode: delegate to the setup wizard UI
    if needs_setup and desktop_ui is not None:
        wait_fn = getattr(desktop_ui, "wait_for_setup_complete", None)
        if wait_fn is None:
            return False
        ok = wait_fn(None)
        if not ok:
            return False

        cwd = Path.cwd().resolve()
        git_root = resolve_git_toplevel(cwd)
        project_root = git_root or cwd
        return (
            is_git_repo(cwd)
            and has_pokepoke_config(project_root)
            and check_beads_available(project_root)
        )

    # CLI mode: check beads availability
    if not check_beads_cli():
        if not interactive:
            return False
        choice = input(
            "\nThis directory is not initialized for beads. "
            "Run 'bd init' here now? [Y/n]: "
        ).strip().lower() or "y"
        if choice not in ("y", "yes"):
            return False
        return bool(initialize_beads_repo(Path.cwd()) and check_beads_cli())

    return True
