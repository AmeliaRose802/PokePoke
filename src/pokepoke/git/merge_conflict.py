"""Merge Conflict Detection and Resolution - Utilities for detecting and handling git merge conflicts."""

import logging
import subprocess
from pathlib import Path

from .git_helpers import run_git
from .git_operations import get_status_porcelain_and_changes

logger = logging.getLogger(__name__)


def is_merge_in_progress(repo_path: Path | None = None) -> bool:
    """Check if a merge is currently in progress (unfinished merge).

    A merge is in progress when MERGE_HEAD exists, meaning we're between
    'git merge' starting and completing (either via commit or abort).
    """
    try:
        cmd = ["git", "rev-parse", "--verify", "MERGE_HEAD"]
        if repo_path:
            cmd = ["git", "-C", str(repo_path), "rev-parse", "--verify", "MERGE_HEAD"]
        result = run_git(cmd, timeout=10, check=False)
        return result.returncode == 0
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return False


def get_unmerged_files(repo_path: Path | None = None) -> list[str]:
    """Get list of files with merge conflicts (unmerged entries).

    Uses git status --porcelain to find files with merge conflict indicators:
    - UU: Both modified (most common)
    - AA: Both added
    - DD: Both deleted
    - AU/UA: Added by us/them, modified by other
    - DU/UD: Deleted by us/them, modified by other

    Returns:
        List of file paths with unmerged conflicts
    """
    try:
        cmd = ["git", "status", "--porcelain"]
        if repo_path:
            cmd = ["git", "-C", str(repo_path), "status", "--porcelain"]
        result = run_git(cmd, timeout=10)

        unmerged = []
        # Unmerged file indicators in git status --porcelain
        conflict_patterns = {'UU', 'AA', 'DD', 'AU', 'UA', 'DU', 'UD'}

        for line in result.stdout.strip().split('\n'):
            if not line:
                continue
            # Format is "XY filename" where X and Y are two-character status codes
            status = line[:2]
            if status in conflict_patterns:
                # Extract filename (after the status and space)
                filename = line[3:]
                unmerged.append(filename)

        return unmerged
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return []


def abort_merge(repo_path: Path | None = None) -> tuple[bool, str]:
    """Abort an in-progress merge, returning to the state before the merge started.

    Returns:
        Tuple of (success, error_message)
    """
    try:
        cmd = ["git", "merge", "--abort"]
        if repo_path:
            cmd = ["git", "-C", str(repo_path), "merge", "--abort"]
        result = run_git(cmd, timeout=30, check=False)
        if result.returncode == 0:
            return True, ""
        else:
            return False, result.stderr.strip() if result.stderr else "Unknown error"
    except subprocess.TimeoutExpired:
        return False, "Merge abort timed out"
    except Exception as e:
        return False, str(e)


def scan_files_for_conflict_markers(
    file_paths: list[str],
    repo_path: Path | None = None,
) -> list[str]:
    """Scan working-tree files for residual merge conflict markers.

    Detects ``<<<<<<<``, ``=======``, and ``>>>>>>>`` lines that indicate
    unresolved merge conflicts — even when ``MERGE_HEAD`` is absent (e.g.
    the merge was completed with conflict markers baked in).

    Args:
        file_paths: Relative file paths (as returned by ``git status``).
        repo_path: Repository root; defaults to cwd.

    Returns:
        Subset of *file_paths* that contain at least one conflict marker.
    """
    import re

    marker_re = re.compile(r'^(<{7}|={7}|>{7})', re.MULTILINE)
    base = Path(repo_path) if repo_path else Path.cwd()
    conflicted: list[str] = []

    for rel in file_paths:
        full = base / rel
        if not full.is_file():
            continue
        try:
            text = full.read_text(encoding='utf-8', errors='replace')
        except OSError:
            logger.debug("Could not read %s for conflict scan", rel)
            continue
        if marker_re.search(text):
            conflicted.append(rel)

    return conflicted


def detect_dirty_conflict_files(repo_path: Path) -> list[str]:
    """Return dirty file paths under *repo_path* that contain conflict markers.

    Combines ``git status --porcelain`` with :func:`scan_files_for_conflict_markers`
    to identify tracked files whose working-tree content has ``<<<<<<<``,
    ``=======``, or ``>>>>>>>`` lines.  Deleted entries are skipped.
    """
    try:
        _uncommitted, changes = get_status_porcelain_and_changes(str(repo_path), timeout=30)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return []

    dirty = changes.get('other', [])
    if not dirty:
        return []

    file_paths = []
    for entry in dirty:
        entry = entry.strip()
        if not entry:
            continue
        if 'D' in entry[:2]:
            continue
        parts = entry.split(None, 1)
        if len(parts) >= 2:
            file_paths.append(parts[1])

    if not file_paths:
        return []

    return scan_files_for_conflict_markers(file_paths, repo_path=repo_path)
