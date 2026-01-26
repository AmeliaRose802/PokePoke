"""Git Operations - Utilities for git status checks, commits, and repository management."""

import re
import subprocess
from pathlib import Path
from typing import Optional, Tuple


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


def sanitize_branch_name(name: str) -> str:
    """Sanitize string to valid git branch name (replace invalid chars with hyphens)."""
    sanitized = re.sub(r'[~^:?*\[\]\\@{}#<>|&;\s]+', '-', name)
    sanitized = re.sub(r'\.\.+', '.', sanitized)
    sanitized = re.sub(r'-+', '-', sanitized)
    return sanitized.strip('-.')


def branch_exists(branch_name: str) -> bool:
    """Check if a local branch exists."""
    try:
        result = subprocess.run(
            ["git", "show-ref", "--verify", f"refs/heads/{branch_name}"],
            capture_output=True,
            text=True,
            encoding='utf-8'
        )
        return result.returncode == 0
    except subprocess.CalledProcessError:
        return False


def get_default_branch(preferred: str = "ameliapayne/dev", fallback: str = "master") -> str:
    """Resolve the default branch name for the repo.

    Prefers ameliapayne/dev when it exists, otherwise uses origin/HEAD or current branch.
    """
    if preferred and branch_exists(preferred):
        return preferred

    try:
        result = subprocess.run(
            ["git", "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD"],
            capture_output=True,
            text=True,
            encoding='utf-8',
            check=True
        )
        ref = result.stdout.strip()
        if ref.startswith("origin/"):
            return ref.split("/", 1)[1]
    except subprocess.CalledProcessError:
        pass

    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            encoding='utf-8',
            check=True
        )
        branch = result.stdout.strip()
        if branch:
            return branch
    except subprocess.CalledProcessError:
        pass

    return fallback


def get_main_repo_root() -> Path:
    """Get the main repository root directory (not a worktree)."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--git-common-dir"],
            capture_output=True, text=True, encoding='utf-8', check=True
        )
        git_common_dir = Path(result.stdout.strip())
        return git_common_dir.parent
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Not in a git repository: {e}")


def is_worktree_clean(worktree_path: Path) -> bool:
    """Check if a worktree has no uncommitted changes."""
    try:
        result = subprocess.run(
            ["git", "-C", str(worktree_path), "status", "--porcelain"],
            capture_output=True,
            text=True,
            encoding='utf-8',
            check=True
        )
        # Empty output means clean status
        return not bool(result.stdout.strip())
    except subprocess.CalledProcessError:
        return False


def verify_branch_pushed(branch_name: str) -> bool:
    """Verify that a branch exists on the remote."""
    try:
        result = subprocess.run(
            ["git", "ls-remote", "--heads", "origin", branch_name],
            capture_output=True,
            text=True,
            encoding='utf-8',
            check=True
        )
        # Non-empty output means branch exists on remote
        return bool(result.stdout.strip())
    except subprocess.CalledProcessError:
        return False

def execute_merge_sequence(branch_name: str, target_branch: str) -> None:
    """Execute the checkout, pull, and merge sequence."""
    subprocess.run(["git", "checkout", target_branch],
                 check=True, capture_output=True, text=True, encoding='utf-8')
    subprocess.run(["git", "pull", "--rebase"],
                 check=True, capture_output=True, text=True, encoding='utf-8')
    subprocess.run(["git", "merge", "--no-ff", branch_name, "-m", f"Merge {branch_name}"],
                 check=True, capture_output=True, text=True, encoding='utf-8')

def validate_post_merge(target_branch: str) -> bool:
    """Validate repository state after merge."""
    current_branch = subprocess.run(
        ["git", "branch", "--show-current"],
        capture_output=True, text=True, encoding='utf-8', check=True
    ).stdout.strip()
    
    if current_branch != target_branch:
        print(f"❌ Post-merge validation failed: Not on {target_branch} (on {current_branch})")
        return False
    
    status_result = subprocess.run(
        ["git", "status", "--porcelain"],
        capture_output=True, text=True, encoding='utf-8', check=True
    )
    
    if status_result.stdout.strip():
        print(f"❌ Post-merge validation failed: {target_branch} has uncommitted changes")
        return False
    
    return True
