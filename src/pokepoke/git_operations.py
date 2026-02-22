"""Git operations utilities for status checks, commits, and repository management."""

import logging
import re
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

# Re-export merge conflict utilities for backward compatibility
from .merge_conflict import (  # noqa: E402
    is_merge_in_progress,
    get_unmerged_files,
    abort_merge,
    get_merge_conflict_details,
)

from .git_helpers import restore_beads_stash  # noqa: E402

__all__ = [
    'is_merge_in_progress', 'get_unmerged_files', 'abort_merge',
    'get_merge_conflict_details', 'has_uncommitted_changes',
    'execute_merge_sequence', 'check_main_repo_ready_for_merge',
    'categorize_git_changes', 'build_handoff_context',
]


def categorize_git_changes(lines: list[str]) -> dict[str, list[str]]:
    """Categorize git status --porcelain lines into beads, worktree, untracked, and other changes."""
    return {
        'beads': [line for line in lines if line and '.beads/' in line],
        'worktree': [line for line in lines if line and 'worktrees/' in line and not line.startswith('??')],
        'untracked': [line for line in lines if line and line.startswith('??')],
        'other': [
            line for line in lines
            if line
            and '.beads/' not in line
            and 'worktrees/' not in line
            and not line.startswith('??')
        ],
    }

def has_uncommitted_changes(cwd: str | None = None) -> bool:
    """Check if there are uncommitted changes in the given directory.

    Returns True if changes exist or git status cannot be verified.
    Assumes dirty state on failure to prevent data loss during merge operations.
    """
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True, text=True, encoding='utf-8',
            errors='replace', check=True, timeout=10, cwd=cwd
        )
        return bool(result.stdout.strip())
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        logger.warning('Could not check uncommitted changes: %s', e)
        return True  # Assume dirty to prevent data loss


def commit_all_changes(message: str = "Auto-commit by PokePoke", cwd: str | None = None) -> tuple[bool, str]:
    """Commit all changes, triggering pre-commit hooks for validation."""
    try:
        subprocess.run(
            ["git", "add", "-A"], check=True, capture_output=True,
            text=True, encoding='utf-8', errors='replace',
            timeout=240, cwd=cwd
        )

        result = subprocess.run(
            ["git", "commit", "-m", message],
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=300,  # 5 minutes for pre-commit hooks
            cwd=cwd
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


def verify_main_repo_clean(cwd: str | None = None) -> tuple[bool, str, list[str]]:
    """Verify repository has no uncommitted non-beads changes.

    Returns (is_clean, uncommitted_output, non_beads_changes).
    """
    try:
        status_result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True, text=True, encoding='utf-8',
            errors='replace', check=True, timeout=10, cwd=cwd
        )

        uncommitted = status_result.stdout.strip()
        if uncommitted:
            changes = categorize_git_changes(uncommitted.split('\n'))
            # Exclude untracked files under .beads/ and worktrees/
            relevant_untracked = [
                line for line in changes['untracked']
                if '.beads/' not in line and 'worktrees/' not in line
            ]
            non_beads = changes['other'] + relevant_untracked
            return len(non_beads) == 0, uncommitted, non_beads

        return True, "", []
    except Exception as e:
        raise RuntimeError(f"Error checking git status: {e}") from e


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
        raise RuntimeError(f"Beads commit timed out after {e.timeout} seconds") from e
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Failed to commit beads changes: {e}") from e


def check_main_repo_ready_for_merge() -> tuple[bool, str]:
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
            encoding='utf-8',
            timeout=30
        )
        return result.returncode == 0
    except subprocess.CalledProcessError:
        return False

def get_default_branch(preferred: str | None = None, fallback: str | None = None) -> str:
    """Resolve the default branch name for the repo.

    Uses project config to determine preferred branch. Falls back to origin/HEAD
    or current branch if preferred not available.
    """
    from .config import get_config
    config = get_config()

    if preferred is None:
        preferred = config.git.get_preferred_branch()
    if fallback is None:
        fallback = config.git.fallback_branch
    if preferred:
        # Check local
        if branch_exists(preferred):
            return preferred

        # Check remote
        try:
            subprocess.run(
                ["git", "show-ref", "--verify", f"refs/remotes/origin/{preferred}"],
                capture_output=True,
                check=True,
                timeout=30
            )

            # Found on remote, create local tracking branch
            print(f"   ✨ Creating local tracking branch for {preferred}...")
            subprocess.run(
                ["git", "branch", "--track", preferred, f"origin/{preferred}"],
                capture_output=True,
                check=True,
                timeout=30
            )
            return preferred
        except subprocess.CalledProcessError:
            pass

    try:
        result = subprocess.run(
            ["git", "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD"],
            capture_output=True,
            text=True,
            encoding='utf-8',
            check=True,
            timeout=30
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
            check=True,
            timeout=30
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
            capture_output=True, text=True, encoding='utf-8', check=True,
            timeout=30
        )
        git_common_dir = Path(result.stdout.strip())
        return git_common_dir.parent
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Not in a git repository: {e}") from e

def is_worktree_clean(worktree_path: Path) -> bool:
    """Check if a worktree has no uncommitted changes."""
    try:
        result = subprocess.run(
            ["git", "-C", str(worktree_path), "status", "--porcelain"],
            capture_output=True,
            text=True,
            encoding='utf-8',
            check=True,
            timeout=30
        )
        # Empty output means clean status
        return not bool(result.stdout.strip())
    except subprocess.CalledProcessError:
        return False

def execute_merge_sequence(branch_name: str, target_branch: str) -> tuple[bool, str, list[str]]:
    """Execute the checkout, pull, and merge sequence.

    Returns:
        Tuple of (success, error_message, unmerged_files)
        - If successful: (True, "", [])
        - If failed: (False, error_message, list_of_unmerged_files)
    """
    try:
        subprocess.run(["git", "checkout", target_branch],
                     check=True, capture_output=True, text=True, encoding='utf-8',
                     timeout=30)
    except subprocess.CalledProcessError as e:
        return False, f"Failed to checkout {target_branch}: {e.stderr or str(e)}", []

    # Stash any beads daemon changes before pull to avoid "unstaged changes" error
    # The beads daemon continuously updates .beads/issues.jsonl which can cause
    # git pull --rebase to fail if changes happen between our commit and the pull
    stashed = False
    try:
        status = subprocess.run(
            ["git", "status", "--porcelain", ".beads/"],
            capture_output=True, text=True, encoding='utf-8', check=True,
            timeout=30
        ).stdout.strip()
        if status:
            subprocess.run(
                ["git", "stash", "push", "-m", "beads-daemon-changes-during-merge", "--", ".beads/"],
                check=True, capture_output=True, text=True, encoding='utf-8',
                timeout=30
            )
            stashed = True
    except subprocess.CalledProcessError:
        pass  # Stash failed, will try pull anyway

    try:
        subprocess.run(["git", "pull", "--rebase", "origin", target_branch],
                     check=True, capture_output=True, text=True, encoding='utf-8',
                     timeout=120)
    except subprocess.CalledProcessError as e:
        # Restore stash if we had one
        if stashed:
            restore_beads_stash("git pull --rebase failure")
        return False, f"Failed to pull with rebase: {e.stderr or str(e)}", []

    # Restore stashed beads changes after successful pull
    if stashed:
        restore_beads_stash("git pull --rebase")

    try:
        subprocess.run(["git", "merge", "--no-ff", branch_name, "-m", f"Merge {branch_name}"],
                     check=True, capture_output=True, text=True, encoding='utf-8',
                     timeout=60)
        return True, "", []
    except subprocess.CalledProcessError as e:
        # Check if this is a merge conflict
        unmerged = get_unmerged_files()
        is_merging = is_merge_in_progress()

        if is_merging and unmerged:
            return False, f"Merge conflicts detected in {len(unmerged)} file(s)", unmerged
        else:
            return False, f"Merge failed: {e.stderr or str(e)}", unmerged

def validate_post_merge(target_branch: str) -> bool:
    """Validate repository state after merge."""
    current_branch = subprocess.run(
        ["git", "branch", "--show-current"],
        capture_output=True, text=True, encoding='utf-8', check=True,
        timeout=30
    ).stdout.strip()

    if current_branch != target_branch:
        print(f"❌ Post-merge validation failed: Not on {target_branch} (on {current_branch})")
        return False

    status_result = subprocess.run(
        ["git", "status", "--porcelain"],
        capture_output=True, text=True, encoding='utf-8', check=True,
        timeout=30
    )

    if status_result.stdout.strip():
        print(f"❌ Post-merge validation failed: {target_branch} has uncommitted changes")
        return False

    return True

def has_commits_ahead(target_branch: str | None = None, cwd: str | None = None) -> int:
    """Count commits in current branch ahead of the target branch."""
    if target_branch is None:
        target_branch = get_default_branch()

    try:
        result = subprocess.run(
            ["git", "rev-list", "--count", f"{target_branch}..HEAD"],
            capture_output=True, text=True, encoding='utf-8',
            timeout=10,
            cwd=cwd
        )
        if result.returncode == 0:
            return int(result.stdout.strip())
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, ValueError):
        pass
    return 0

# Re-export handoff context builder for backward compatibility
from .handoff_context import build_handoff_context  # noqa: E402,F401
