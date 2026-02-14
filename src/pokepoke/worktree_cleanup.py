"""Windows-safe directory removal utilities for worktree cleanup."""

import json
import os
import shutil
import stat
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, cast

# Retry settings for worktree removal on Windows
_CLEANUP_MAX_RETRIES = 3
_CLEANUP_RETRY_DELAY_SECONDS = 2.0


def _handle_remove_readonly(func: object, path: str, exc_info: object) -> None:
    """Error handler for shutil.rmtree that clears read-only flags on Windows."""
    os.chmod(path, stat.S_IWRITE)
    func(path)  # type: ignore[operator]


def force_remove_directory(dir_path: Path) -> bool:
    """Force-remove a directory, handling Windows permission issues.

    Retries with delays to allow file handles to be released,
    then falls back to shutil.rmtree with read-only flag clearing.
    Returns True if the directory was removed.
    """
    for attempt in range(_CLEANUP_MAX_RETRIES):
        try:
            subprocess.run(
                ["git", "worktree", "remove", "--force", str(dir_path)],
                check=True, capture_output=True, text=True, encoding='utf-8'
            )
            return True
        except subprocess.CalledProcessError:
            pass

        # Fallback: direct directory removal
        try:
            shutil.rmtree(str(dir_path), onerror=_handle_remove_readonly)
            # Clean up git worktree bookkeeping after manual removal
            subprocess.run(
                ["git", "worktree", "prune"],
                check=False, capture_output=True, text=True, encoding='utf-8'
            )
            return True
        except (OSError, PermissionError):
            if attempt < _CLEANUP_MAX_RETRIES - 1:
                time.sleep(_CLEANUP_RETRY_DELAY_SECONDS)

    return False


def get_worktree_manifest_path() -> Path:
    """Get the path to the uncleaned worktrees manifest file."""
    pokepoke_dir = Path(".pokepoke")
    pokepoke_dir.mkdir(exist_ok=True)
    return pokepoke_dir / "uncleaned_worktrees.json"


def load_worktree_manifest() -> Dict[str, Dict[str, str]]:
    """Load the uncleaned worktrees manifest."""
    manifest_path = get_worktree_manifest_path()
    if not manifest_path.exists():
        return {}

    try:
        with open(manifest_path, 'r', encoding='utf-8') as f:
            raw = json.load(f)
            if isinstance(raw, dict):
                return cast(Dict[str, Dict[str, str]], raw)
            return {}
    except (json.JSONDecodeError, IOError):
        return {}


def save_worktree_manifest(manifest: Dict[str, Dict[str, str]]) -> None:
    """Save the uncleaned worktrees manifest."""
    manifest_path = get_worktree_manifest_path()
    try:
        with open(manifest_path, 'w', encoding='utf-8') as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)
    except IOError:
        pass  # Silently fail to avoid disrupting main operations


def add_uncleaned_worktree(worktree_id: str, worktree_path: str, reason: str) -> None:
    """Add a worktree to the uncleaned manifest."""
    manifest = load_worktree_manifest()
    manifest[worktree_id] = {
        "path": worktree_path,
        "reason": reason,
        "timestamp": datetime.now().isoformat()
    }
    save_worktree_manifest(manifest)


def remove_from_manifest(worktree_id: str) -> None:
    """Remove a worktree from the uncleaned manifest."""
    manifest = load_worktree_manifest()
    if worktree_id in manifest:
        del manifest[worktree_id]
        save_worktree_manifest(manifest)


def get_stale_worktrees(max_age_days: int = 7) -> Dict[str, Dict[str, str]]:
    """Get worktrees from manifest that are older than max_age_days."""
    manifest = load_worktree_manifest()
    stale_worktrees = {}
    cutoff_time = datetime.now().timestamp() - (max_age_days * 24 * 60 * 60)

    for worktree_id, info in manifest.items():
        try:
            timestamp = datetime.fromisoformat(info["timestamp"]).timestamp()
            if timestamp < cutoff_time:
                stale_worktrees[worktree_id] = info
        except (ValueError, KeyError):
            # Invalid timestamp or missing field - consider it stale
            stale_worktrees[worktree_id] = info

    return stale_worktrees
