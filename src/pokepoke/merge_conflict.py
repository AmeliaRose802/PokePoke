"""Merge Conflict Detection and Resolution - Utilities for detecting and handling git merge conflicts."""

import subprocess
from pathlib import Path
from typing import Optional, Tuple, List


def is_merge_in_progress(repo_path: Optional[Path] = None) -> bool:
    """Check if a merge is currently in progress (unfinished merge).
    
    A merge is in progress when MERGE_HEAD exists, meaning we're between
    'git merge' starting and completing (either via commit or abort).
    """
    try:
        cmd = ["git", "rev-parse", "--verify", "MERGE_HEAD"]
        if repo_path:
            cmd = ["git", "-C", str(repo_path), "rev-parse", "--verify", "MERGE_HEAD"]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=10
        )
        return result.returncode == 0
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return False


def get_unmerged_files(repo_path: Optional[Path] = None) -> List[str]:
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
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            check=True,
            timeout=10
        )
        
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


def abort_merge(repo_path: Optional[Path] = None) -> Tuple[bool, str]:
    """Abort an in-progress merge, returning to the state before the merge started.
    
    Returns:
        Tuple of (success, error_message)
    """
    try:
        cmd = ["git", "merge", "--abort"]
        if repo_path:
            cmd = ["git", "-C", str(repo_path), "merge", "--abort"]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=30
        )
        if result.returncode == 0:
            return True, ""
        else:
            return False, result.stderr.strip() if result.stderr else "Unknown error"
    except subprocess.TimeoutExpired:
        return False, "Merge abort timed out"
    except Exception as e:
        return False, str(e)


def get_merge_conflict_details(repo_path: Optional[Path] = None) -> dict[str, object]:
    """Get detailed information about the current merge conflict state.
    
    Returns a dictionary with:
    - is_merging: bool - whether a merge is in progress
    - unmerged_files: list - files with conflicts
    - merge_head: str - the commit being merged (if available)
    - conflict_count: int - number of conflicted files
    """
    is_merging = is_merge_in_progress(repo_path)
    unmerged = get_unmerged_files(repo_path)
    
    merge_head = ""
    if is_merging:
        try:
            cmd = ["git", "rev-parse", "--short", "MERGE_HEAD"]
            if repo_path:
                cmd = ["git", "-C", str(repo_path), "rev-parse", "--short", "MERGE_HEAD"]
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace',
                timeout=10
            )
            if result.returncode == 0:
                merge_head = result.stdout.strip()
        except:
            pass
    
    return {
        "is_merging": is_merging,
        "unmerged_files": unmerged,
        "merge_head": merge_head,
        "conflict_count": len(unmerged)
    }
