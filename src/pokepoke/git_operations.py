"""Git Operations - Utilities for git status checks, commits, and repository management."""

import subprocess
from typing import Tuple


def has_uncommitted_changes() -> bool:
    """Check if there are uncommitted changes in the current directory."""
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            check=True,
            timeout=10
        )
        return bool(result.stdout.strip())
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return False


def commit_all_changes(message: str = "Auto-commit by PokePoke") -> tuple[bool, str]:
    """Commit all changes, triggering pre-commit hooks for validation."""
    try:
        subprocess.run(
            ["git", "add", "-A"],
            check=True,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=240
        )
        
        result = subprocess.run(
            ["git", "commit", "-m", message],
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=300  # 5 minutes for pre-commit hooks
        )
        
        if result.returncode == 0:
            return True, ""
        else:
            error_lines = result.stderr.strip().split('\n') if result.stderr else []
            if error_lines:
                errors = [line for line in error_lines if line.strip() and not line.startswith('hint:')][:5]
                return False, '\n   '.join(errors) if errors else "Commit failed"
            return False, "Commit failed (unknown reason)"
    except subprocess.TimeoutExpired as e:
        return False, f"Commit timed out after {e.timeout} seconds (pre-commit hooks may be hanging)"
    except subprocess.CalledProcessError as e:
        return False, f"Commit error: {e.stderr if e.stderr else str(e)}"


def verify_main_repo_clean() -> Tuple[bool, str, list[str]]:
    """Verify main repository has no uncommitted non-beads changes.
    
    Returns:
        Tuple of (is_clean, uncommitted_output, non_beads_changes)
        - is_clean: True if only beads changes or clean
        - uncommitted_output: Raw git status output
        - non_beads_changes: List of non-beads changed files
    """
    try:
        status_result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            check=True,
            timeout=10
        )
        
        uncommitted = status_result.stdout.strip()
        if uncommitted:
            lines = uncommitted.split('\n')
            # Exclude .beads/ and worktrees/ from uncommitted changes check
            non_beads_changes = [line for line in lines if line and '.beads/' not in line and 'worktrees/' not in line]
            return len(non_beads_changes) == 0, uncommitted, non_beads_changes
        
        return True, "", []
    except Exception as e:
        raise RuntimeError(f"Error checking git status: {e}")


def handle_beads_auto_commit() -> None:
    """Automatically commit beads database changes.
    
    Raises:
        RuntimeError: If commit fails
    """
    try:
        print("🔧 Committing beads database changes in main repo...")
        subprocess.run(["git", "add", ".beads/"], check=True, encoding='utf-8', errors='replace', timeout=10)
        subprocess.run(
            ["git", "commit", "-m", "chore: sync beads before worktree merge"],
            check=True,
            capture_output=True,
            encoding='utf-8',
            errors='replace',
            timeout=300
        )
        print("✅ Beads changes committed")
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"Beads commit timed out after {e.timeout} seconds")
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Failed to commit beads changes: {e}")


def check_main_repo_ready_for_merge() -> Tuple[bool, str]:
    """Check if main repo is ready for worktree merge.
    
    Returns:
        (is_ready, error_message) tuple
    """
    try:
        is_clean, uncommitted, non_beads_changes = verify_main_repo_clean()
        
        if not is_clean:
            return False, f"Main repo has uncommitted non-beads changes:\n{chr(10).join(non_beads_changes)}"
        
        # If we have uncommitted changes, they must be beads-only
        if uncommitted:
            handle_beads_auto_commit()
        
        return True, ""
    except Exception as e:
        return False, f"Error checking main repo status: {e}"
