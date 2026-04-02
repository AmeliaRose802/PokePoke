"""Shared Git helper utilities."""

import contextlib
import logging
import subprocess

from pokepoke.types import RetryConfig
from pokepoke.utils.constants import BEADS_DIR, DEFAULT_GIT_TIMEOUT
from pokepoke.utils.retry_utils import sleep_with_backoff

logger = logging.getLogger(__name__)

__all__ = [
    "_run_git_status_with_retry",
    "get_commits_behind",
    "list_worktrees",
    "restore_beads_stash",
    "run_git",
    "run_git_with_retry",
    "validate_post_merge",
    "verify_branch_pushed",
    "verify_worktree_branch",
]


def run_git(
    cmd: list[str],
    *,
    timeout: int = DEFAULT_GIT_TIMEOUT,
    cwd: str | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    """Run a git command with standard encoding and timeout handling."""
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=check,
        timeout=timeout,
        cwd=cwd,
    )


def run_git_with_retry(
    cmd: list[str],
    *,
    timeout: int = DEFAULT_GIT_TIMEOUT,
    cwd: str | None = None,
    max_retries: int = 3,
    initial_delay: float = 2.0,
    context: str = "git command",
) -> subprocess.CompletedProcess[str]:
    """Run a git command with exponential-backoff retry on transient failures.

    Retries on both CalledProcessError and TimeoutExpired. Returns
    the CompletedProcess on success or re-raises the last exception
    after all retries are exhausted.
    """
    retry_config = RetryConfig(
        max_retries=max_retries,
        initial_delay=initial_delay,
        backoff_factor=2.0,
        jitter=True,
    )
    last_exc: Exception | None = None
    for attempt in range(max_retries):
        try:
            return run_git(cmd, timeout=timeout, cwd=cwd)
        except subprocess.TimeoutExpired as exc:
            last_exc = exc
            logger.warning(
                "%s timed out (attempt %d/%d, timeout=%ds)",
                context, attempt + 1, max_retries, timeout,
            )
        except subprocess.CalledProcessError as exc:
            last_exc = exc
            logger.warning(
                "%s failed (attempt %d/%d, exit %d): %s",
                context, attempt + 1, max_retries,
                exc.returncode, exc.stderr or str(exc),
            )
        if attempt < max_retries - 1:
            delay = sleep_with_backoff(attempt, retry_config, context)
            logger.info(
                "%s retry %d/%d in %.1fs",
                context, attempt + 1, max_retries, delay,
            )
    assert last_exc is not None
    raise last_exc


def verify_branch_pushed(branch_name: str) -> bool:
    """Return True when the given branch exists on origin."""
    try:
        result = run_git(
            ["git", "ls-remote", "--heads", "origin", branch_name],
            timeout=120,
        )
        return bool(result.stdout.strip())
    except subprocess.CalledProcessError:
        return False


def _print_command_output(lines: list[str]) -> None:
    for line in lines:
        text = line.strip()
        if text:
            logger.info(text)


def restore_beads_stash(context: str) -> None:
    """Apply stashed .beads/ changes, logging conflicts and cleaning up stale entries.

    On pop failure, force-applies .beads/ paths from the stash (local beads
    state is authoritative) and only drops the stash after successful recovery.
    If recovery also fails the stash is preserved for manual inspection.
    """
    try:
        run_git(["git", "stash", "pop", "--index"])
    except subprocess.CalledProcessError as pop_error:
        logger.warning(f"⚠️ Stash pop conflict after {context}. Attempting to force-apply .beads/ changes.")
        _print_command_output([pop_error.stdout or "", pop_error.stderr or ""])

        # Reset only .beads/ from the partially-applied pop so the
        # checkout from stash doesn't hit conflicts.  Previously this
        # ran `git checkout -- .` which wiped the ENTIRE working tree.
        with contextlib.suppress(subprocess.CalledProcessError):
            run_git(["git", "checkout", "--", f"{BEADS_DIR}/"])

        # Force-apply .beads/ paths from the stash (theirs-wins strategy)
        try:
            run_git(["git", "checkout", "stash@{0}", "--", f"{BEADS_DIR}/"])
            logger.info("✅ Force-applied .beads/ changes from stash.")
            # Only drop the stash after successful recovery
            try:
                run_git(["git", "stash", "drop"])
            except subprocess.CalledProcessError:
                logger.warning("⚠️ Could not drop stash after recovery. Run `git stash list` to clean up.")
        except subprocess.CalledProcessError as checkout_error:
            # Recovery failed — preserve the stash for manual inspection
            _print_command_output([checkout_error.stdout or "", checkout_error.stderr or ""])
            stash_ref = _get_stash_ref()
            ref_msg = f" (ref: {stash_ref})" if stash_ref else ""
            logger.warning(
                f"⚠️ Could not recover .beads/ from stash{ref_msg}. "
                "Stash preserved — run `git stash list` to inspect."
            )


def _get_stash_ref() -> str:
    """Return the first stash entry label, or empty string on failure."""
    try:
        result = run_git(["git", "stash", "list", "-1"], timeout=10, check=False)
        return result.stdout.strip()
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return ""


def _run_git_status_with_retry(
    args: list[str], cwd: str | None = None,
    max_retries: int = 3, base_delay: float = 0.5, timeout: int = 10,
) -> subprocess.CompletedProcess[str]:
    """Run git status with exponential-backoff retry on index.lock contention."""
    retry_config = RetryConfig(
        max_retries=max_retries,
        initial_delay=base_delay,
        backoff_factor=2.0,
        jitter=True,
    )
    last_exc: Exception | None = None
    for attempt in range(max_retries):
        try:
            return run_git(args, cwd=cwd, timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            last_exc = exc
        except subprocess.CalledProcessError as exc:
            if 'index.lock' not in (exc.stderr or '') or attempt >= max_retries - 1:
                raise
            last_exc = exc
        if attempt < max_retries - 1:
            delay = sleep_with_backoff(attempt, retry_config, 'git status index.lock contention')
            logger.warning('git status retry %d/%d in %.1fs (index.lock contention)', attempt + 1, max_retries, delay)
    assert last_exc is not None
    raise last_exc


def validate_post_merge(target_branch: str, cwd: str | None = None) -> bool:
    """Validate repository state after merge."""
    current_branch = run_git(
        ["git", "branch", "--show-current"], cwd=cwd).stdout.strip()
    if current_branch != target_branch:
        logger.error(f"❌ Post-merge validation failed: Not on {target_branch} (on {current_branch})")
        return False
    status = run_git(
        ["git", "status", "--porcelain"], cwd=cwd).stdout.strip()
    if status:
        logger.error(f"❌ Post-merge validation failed: {target_branch} has uncommitted changes")
        return False
    return True


def get_commits_behind(branch: str, target: str, *, cwd: str | None = None) -> int | None:
    """Get the number of commits that a branch is behind the target branch.

    Args:
        branch: Branch to check (e.g., "task/feature-branch")
        target: Target branch to compare against (e.g., "master", "main")
        cwd: Working directory for the git command (defaults to process CWD).

    Returns:
        Number of commits behind, or None if unable to determine.
    """
    try:
        result = run_git(
            ["git", "rev-list", f"{branch}..{target}", "--count"],
            cwd=cwd,
            check=False
        )
        if result.returncode == 0:
            count_str = result.stdout.strip()
            if count_str.isdigit():
                return int(count_str)
        return None
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, ValueError):
        return None


def list_worktrees(cwd: str | None = None) -> list[dict[str, str]]:
    """List all active worktrees.

    Args:
        cwd: Working directory for the git command (defaults to process CWD).
    """
    try:
        result = run_git(
            ["git", "worktree", "list", "--porcelain"], cwd=cwd)
        worktrees: list[dict[str, str]] = []
        current: dict[str, str] = {}
        for line in result.stdout.splitlines():
            if line.startswith("worktree "):
                if current:
                    worktrees.append(current)
                current = {"path": line.split(" ", 1)[1]}
            elif line.startswith("branch "):
                current["branch"] = line.split(" ", 1)[1]
            elif line.startswith("HEAD "):
                current["commit"] = line.split(" ", 1)[1]
        if current:
            worktrees.append(current)
        return worktrees
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return []


def verify_worktree_branch(item_id: str, worktree_cwd: str) -> str | None:
    """Check the worktree is on the expected task branch; return error message or None."""
    from pathlib import Path

    from pokepoke.git.git_operations import sanitize_branch_name
    from pokepoke.utils.constants import BRANCH_PREFIX

    if not Path(worktree_cwd).exists():
        return None

    expected = f"{BRANCH_PREFIX}{sanitize_branch_name(item_id)}"
    try:
        proc = run_git(["git", "branch", "--show-current"], cwd=worktree_cwd, timeout=10, check=False)
        if proc.returncode == 0:
            branch = proc.stdout.strip()
            if branch and branch not in ("true", expected):
                return (
                    f"FATAL: Worktree for {item_id} is on wrong branch '{branch}' "
                    f"(expected '{expected}'). Refusing to invoke agent. "
                    "This prevents committing to the default branch."
                )
    except Exception as e:
        return f"FATAL: Failed to verify worktree branch: {e}"
    return None
