"""Git operations utilities for status checks, commits, and repository management."""

import logging
import re
import subprocess
from pathlib import Path

from pokepoke.utils.constants import BEADS_DIR, WORKTREE_DIR

# Pre-built path prefixes for string matching in git status output
_BEADS_PATH = f"{BEADS_DIR}/"
_WT_PATH = f"{WORKTREE_DIR}/"

logger = logging.getLogger(__name__)

from .git_helpers import (
    _run_git_status_with_retry,
    list_worktrees,
    restore_beads_stash,
    run_git,
    validate_post_merge,
)

__all__ = [
    'build_handoff_context',
    'categorize_git_changes',
    'check_main_repo_ready_for_merge',
    'execute_merge_sequence',
    'get_status_porcelain_and_changes',
    'has_uncommitted_changes',
    'list_worktrees',
    'validate_post_merge',
]


def categorize_git_changes(lines: list[str]) -> dict[str, list[str]]:
    """Categorize git status --porcelain lines into beads, worktree, untracked, and other changes."""
    return {
        'beads': [line for line in lines if line and _BEADS_PATH in line],
        'worktree': [line for line in lines if line and _WT_PATH in line and not line.startswith('??')],
        'untracked': [line for line in lines if line and line.startswith('??')],
        'other': [
            line for line in lines
            if line and _BEADS_PATH not in line and _WT_PATH not in line and not line.startswith('??')
        ],
    }


def get_status_porcelain_and_changes(
    cwd: str | None = None,
    *,
    timeout: int = 10,
) -> tuple[str, dict[str, list[str]]]:
    """Return `git status --porcelain` output plus categorized change buckets."""
    status_result = _run_git_status_with_retry(
        ["git", "status", "--porcelain"],
        cwd=cwd,
        timeout=timeout,
    )
    uncommitted = status_result.stdout.strip()
    lines = uncommitted.splitlines() if uncommitted else []
    return uncommitted, categorize_git_changes(lines)


def has_uncommitted_changes(cwd: str | None = None) -> bool:
    """Check for uncommitted changes in cwd (assume dirty on failure)."""
    try:
        uncommitted, _ = get_status_porcelain_and_changes(cwd)
        return bool(uncommitted)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        logger.warning('Could not check uncommitted changes: %s', e)
        return True  # Assume dirty to prevent data loss


def commit_all_changes(
    message: str = "Auto-commit by PokePoke",
    cwd: str | None = None,
    tracked_only: bool = False,
) -> tuple[bool, str]:
    """Commit changes, triggering pre-commit hooks for validation.

    Args:
        message: Commit message.
        cwd: Working directory for git commands.
        tracked_only: If True, use ``git add -u`` (tracked files only) instead
            of ``git add -A``.  Callers operating in the **main repo** should
            pass ``True`` to avoid staging untracked files (e.g. .env, temp
            files).  Worktree callers may leave this ``False``.
    """
    add_flag = "-u" if tracked_only else "-A"
    try:
        run_git(
            ["git", "add", add_flag],
            timeout=240, cwd=cwd
        )

        result = run_git(
            ["git", "commit", "-m", message],
            timeout=300,
            cwd=cwd,
            check=False,
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
    """Return (is_clean, porcelain, non_beads_changes) for the repo."""
    try:
        status_result = _run_git_status_with_retry(
            ["git", "status", "--porcelain"],
            cwd=cwd,
        )
        uncommitted = status_result.stdout.strip()
        if uncommitted:
            changes = categorize_git_changes(uncommitted.split('\n'))
            relevant_untracked = [
                line for line in changes['untracked']
                if _BEADS_PATH not in line and _WT_PATH not in line
            ]
            non_beads = changes['other'] + relevant_untracked
            return len(non_beads) == 0, uncommitted, non_beads

        return True, "", []
    except Exception as e:
        raise RuntimeError(f"Error checking git status: {e}") from e


def handle_beads_auto_commit(cwd: str | None = None) -> None:
    """Commit beads database changes."""
    try:
        logger.info("🔧 Committing beads database changes in main repo...")
        run_git(["git", "add", f"{BEADS_DIR}/"], timeout=10, cwd=cwd)
        run_git(
            ["git", "commit", "-m", "chore: sync beads before worktree merge"],
            timeout=300,
            cwd=cwd,
        )
        logger.info("✅ Beads changes committed")
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"Beads commit timed out after {e.timeout} seconds") from e
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Failed to commit beads changes: {e}") from e


def check_main_repo_ready_for_merge(cwd: str | None = None) -> tuple[bool, str]:
    """Return (is_ready, error_message) for merging into the main repo."""
    try:
        is_clean, uncommitted, non_beads_changes = verify_main_repo_clean(cwd=cwd)

        if not is_clean:
            return False, f"Main repo has uncommitted non-beads changes:\n{chr(10).join(non_beads_changes)}"

        # If we have uncommitted changes, they must be beads-only
        if uncommitted:
            handle_beads_auto_commit(cwd=cwd)

        return True, ""
    except Exception as e:
        return False, f"Error checking main repo status: {e}"


def sanitize_branch_name(name: str) -> str:
    """Sanitize string to valid git branch name (replace invalid chars with hyphens)."""
    s = re.sub(r'[~^:?*\[\]\\@{}#<>|&;\s]+', '-', name)
    return re.sub(r'-+', '-', re.sub(r'\.\.+', '.', s)).strip('-.')


def branch_exists(branch_name: str, cwd: str | None = None) -> bool:
    """Check if a local branch exists."""
    try:
        result = run_git(
            ["git", "show-ref", "--verify", f"refs/heads/{branch_name}"],
            timeout=30, cwd=cwd, check=False)
        return result.returncode == 0
    except subprocess.CalledProcessError:
        return False

def get_default_branch(preferred: str | None = None, fallback: str | None = None, cwd: str | None = None) -> str:
    """Resolve the default branch name for the repo.

    Uses project config to determine preferred branch. Falls back to origin/HEAD
    or current branch if preferred not available.

    Args:
        preferred: Preferred branch name override.
        fallback: Fallback branch name override.
        cwd: Working directory for git commands (defaults to process CWD).
    """
    from pokepoke.config import get_config
    config = get_config()

    if preferred is None:
        preferred = config.git.get_preferred_branch()
    if fallback is None:
        fallback = config.git.fallback_branch
    if preferred:
        # Check local
        if branch_exists(preferred, cwd=cwd):
            return preferred

        # Check remote
        try:
            run_git(
                ["git", "show-ref", "--verify", f"refs/remotes/origin/{preferred}"],
                timeout=30,
                cwd=cwd,
            )
            # Found on remote, create local tracking branch
            logger.info(f"   ✨ Creating local tracking branch for {preferred}...")
            run_git(
                ["git", "branch", "--track", preferred, f"origin/{preferred}"],
                timeout=30,
                cwd=cwd,
            )
            return preferred
        except subprocess.CalledProcessError:
            pass

    try:
        result = run_git(
            ["git", "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD"],
            timeout=30,
            cwd=cwd,
        )
        ref = result.stdout.strip()
        if ref.startswith("origin/"):
            return ref.split("/", 1)[1]
    except subprocess.CalledProcessError:
        pass

    try:
        result = run_git(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            timeout=30,
            cwd=cwd,
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
        result = run_git(
            ["git", "rev-parse", "--git-common-dir"])
        return Path(result.stdout.strip()).parent
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Not in a git repository: {e}") from e

def is_worktree_clean(worktree_path: Path) -> bool:
    """Check if a worktree has no uncommitted changes."""
    try:
        result = run_git(
            ["git", "-C", str(worktree_path), "status", "--porcelain"])
        return not bool(result.stdout.strip())
    except subprocess.CalledProcessError:
        return False

def execute_merge_sequence(
    branch_name: str,
    target_branch: str,
    cwd: str | None = None,
) -> tuple[bool, str, list[str]]:
    """Execute the checkout, pull, and merge sequence.

    Args:
        branch_name: Branch to merge from.
        target_branch: Branch to merge into.
        cwd: Working directory for git commands (defaults to process CWD).

    Returns:
        Tuple of (success, error_message, unmerged_files)
        - If successful: (True, "", [])
        - If failed: (False, error_message, list_of_unmerged_files)
    """
    try:
        run_git(["git", "checkout", target_branch],
                     timeout=30, cwd=cwd)
    except subprocess.CalledProcessError as e:
        return False, f"Failed to checkout {target_branch}: {e.stderr or str(e)}", []
    except subprocess.TimeoutExpired:
        return False, f"Checkout of {target_branch} timed out after 30s", []

    # Stash beads daemon changes to avoid "unstaged changes" error during pull
    stashed = False
    try:
        status = run_git(
            ["git", "status", "--porcelain", f"{BEADS_DIR}/"],
            timeout=30, cwd=cwd,
        ).stdout.strip()
        if status:
            run_git(
                ["git", "stash", "push", "-m", "beads-daemon-changes-during-merge", "--", f"{BEADS_DIR}/"],
                timeout=30, cwd=cwd,
            )
            stashed = True
    except subprocess.CalledProcessError:
        pass  # Stash failed, will try pull anyway

    try:
        run_git(["git", "pull", "--rebase", "origin", target_branch],
                     timeout=120, cwd=cwd)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        # Rollback: abort the failed rebase to leave repo in a clean state
        try:
            run_git(["git", "rebase", "--abort"], timeout=30, cwd=cwd)
            logger.info("Rolled back failed rebase with git rebase --abort")
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as abort_err:
            logger.warning("Could not abort rebase during rollback: %s", abort_err)
        if stashed:
            restore_beads_stash("git pull --rebase failure")
        if isinstance(e, subprocess.TimeoutExpired):
            return False, "Pull --rebase timed out after 120s", []
        return False, f"Failed to pull with rebase: {e.stderr or str(e)}", []

    # Restore stashed beads changes after successful pull
    if stashed:
        restore_beads_stash("git pull --rebase")

    try:
        run_git(["git", "merge", "--no-ff", branch_name, "-m", f"Merge {branch_name}"],
                     timeout=60, cwd=cwd)
        return True, "", []
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        from .merge_conflict import get_unmerged_files, is_merge_in_progress
        repo_path_obj = Path(cwd) if cwd else None
        unmerged = get_unmerged_files(repo_path=repo_path_obj)
        is_merging = is_merge_in_progress(repo_path=repo_path_obj)

        # Rollback: abort the failed merge to leave repo in a clean state
        if is_merging:
            try:
                run_git(["git", "merge", "--abort"], timeout=30, cwd=cwd)
                logger.info("Rolled back failed merge with git merge --abort")
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as abort_err:
                logger.error("Failed to abort merge during rollback: %s", abort_err)

        if isinstance(e, subprocess.TimeoutExpired):
            return False, "Merge timed out after 60s", unmerged
        if unmerged:
            return False, f"Merge conflicts detected in {len(unmerged)} file(s)", unmerged
        else:
            return False, f"Merge failed: {e.stderr or str(e)}", unmerged

def has_commits_ahead(target_branch: str | None = None, cwd: str | None = None) -> int:
    """Count commits in current branch ahead of the target branch."""
    if target_branch is None:
        target_branch = get_default_branch()
    try:
        result = run_git(
            ["git", "rev-list", "--count", f"{target_branch}..HEAD"],
            timeout=10, cwd=cwd, check=False)
        if result.returncode == 0:
            return int(result.stdout.strip())
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, ValueError):
        pass
    return 0

from pokepoke.prompts.handoff_context import build_handoff_context  # Re-export for backward compat
