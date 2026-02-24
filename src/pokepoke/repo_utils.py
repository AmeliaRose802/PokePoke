"""Utility functions for working with repository information."""

import logging
import re
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


def get_repository_name() -> str:
    """Extract repository name from git remote origin URL or fallback sources.

    Returns:
        Repository name extracted from git remote, config, or directory name.
        Falls back to "Unknown" if none are available.
    """
    # Try to get repository name from git remote origin URL
    repo_name = _get_repo_name_from_git()
    if repo_name:
        return repo_name

    # Fallback to project_name from config
    repo_name = _get_repo_name_from_config()
    if repo_name:
        return repo_name

    # Final fallback to current working directory name
    try:
        return Path.cwd().name
    except Exception as e:
        logger.warning(f"Failed to get current working directory name: {e}")
        return "Unknown"


def _get_repo_name_from_git() -> str | None:
    """Extract repository name from git remote origin URL."""
    try:
        result = subprocess.run(
            ["git", "config", "--get", "remote.origin.url"],
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=5
        )
        if result.returncode == 0 and result.stdout.strip():
            url = result.stdout.strip()
            # Extract repo name from URL patterns like:
            # https://github.com/user/repo.git -> repo
            # git@github.com:user/repo.git -> repo
            match = re.search(r'/([^/]+?)(?:\.git)?$', url)
            if match:
                return match.group(1)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return None


def _get_repo_name_from_config() -> str | None:
    """Extract repository name from project config."""
    try:
        from pokepoke.config import get_config
        config = get_config()
        if config.project_name:
            return config.project_name
    except Exception as e:
        logger.debug(f"Failed to get repository name from config: {e}")
    return None
