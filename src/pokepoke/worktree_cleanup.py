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

    Retries with backoff to allow file handles to be released,
    then falls back to shutil.rmtree with read-only flag clearing.
    Returns True if the directory was removed.
    """
    for attempt in range(_CLEANUP_MAX_RETRIES):
        try:
            subprocess.run(
                ["git", "worktree", "remove", "--force", str(dir_path)],
                check=True, capture_output=True, text=True, encoding='utf-8',
                timeout=30
            )
            return True
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            pass

        # Fallback: direct directory removal
        try:
            shutil.rmtree(str(dir_path), onerror=_handle_remove_readonly)
            # Clean up git worktree bookkeeping after manual removal
            subprocess.run(
                ["git", "worktree", "prune"],
                check=False, capture_output=True, text=True, encoding='utf-8',
                timeout=30
            )
            return True
        except (OSError, PermissionError):
            if attempt < _CLEANUP_MAX_RETRIES - 1:
                time.sleep(_CLEANUP_RETRY_DELAY_SECONDS * (2 ** attempt))

    return False


def get_worktree_manifest_path() -> Path:
    """Get the path to the uncleaned worktrees manifest file."""
    pokepoke_dir = Path(".pokepoke")
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
        manifest_path.parent.mkdir(exist_ok=True)
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


def cleanup_after_merge(worktree_path: Path, branch_name: str) -> None:
    """Cleanup worktree and branch after successful merge."""
    if worktree_path.exists():
        try:
            subprocess.run(
                ["git", "worktree", "remove", str(worktree_path)],
                check=True, capture_output=True, text=True, encoding='utf-8',
                timeout=30
            )
            print(f"\u2705 Removed worktree at {worktree_path}")
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            stderr = getattr(e, 'stderr', None) or str(e)
            stderr_lower = stderr.lower()

            if any(s in stderr_lower for s in [
                "permission denied",
                "being used by another process",
                "invalid argument",
            ]):
                print("\u26a0\ufe0f  Worktree removal failed (likely locked). Retrying with force removal...")
                if force_remove_directory(worktree_path):
                    print(f"\u2705 Force-removed worktree at {worktree_path}")
                    if branch_name.startswith("task/"):
                        remove_from_manifest(branch_name.split("/", 1)[1])
                else:
                    print(f"\u26a0\ufe0f  Could not remove worktree after retries: {worktree_path}")
                    print("   Merge successful - worktree cleanup can be done later")
                    worktree_id = branch_name.split("/", 1)[1] if branch_name.startswith("task/") else worktree_path.name
                    add_uncleaned_worktree(worktree_id, str(worktree_path), f"Post-merge cleanup failed: {stderr}")
            else:
                print(f"\u26a0\ufe0f  Could not remove worktree: {stderr}")
                print("   Merge successful - worktree cleanup can be done later")
                worktree_id = branch_name.split("/", 1)[1] if branch_name.startswith("task/") else worktree_path.name
                add_uncleaned_worktree(worktree_id, str(worktree_path), f"Post-merge cleanup warning: {stderr}")

    try:
        subprocess.run(
            ["git", "branch", "-d", branch_name],
            check=True, capture_output=True, text=True, encoding='utf-8',
            timeout=30
        )
        print(f"\u2705 Deleted branch {branch_name}")
    except subprocess.CalledProcessError as e:
        print(f"\u26a0\ufe0f  Could not delete branch: {e.stderr or e}")
