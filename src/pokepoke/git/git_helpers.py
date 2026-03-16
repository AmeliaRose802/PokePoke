"""Shared Git helper utilities."""

from __future__ import annotations

import contextlib
import logging
import subprocess
import time

from pokepoke.utils.constants import BEADS_DIR, DEFAULT_GIT_TIMEOUT

logger = logging.getLogger(__name__)

__all__ = [
    "run_git", "verify_branch_pushed", "restore_beads_stash",
    "_run_git_status_with_retry", "validate_post_merge", "list_worktrees",
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
            print(text)


def restore_beads_stash(context: str) -> None:
    """Apply stashed .beads/ changes, logging conflicts and cleaning up stale entries.

    On pop failure, force-applies .beads/ paths from the stash (local beads
    state is authoritative) and only drops the stash after successful recovery.
    If recovery also fails the stash is preserved for manual inspection.
    """
    try:
        run_git(["git", "stash", "pop", "--index"])
    except subprocess.CalledProcessError as pop_error:
        print(f"⚠️ Stash pop conflict after {context}. Attempting to force-apply .beads/ changes.")
        _print_command_output([pop_error.stdout or "", pop_error.stderr or ""])

        # Reset only .beads/ from the partially-applied pop so the
        # checkout from stash doesn't hit conflicts.  Previously this
        # ran `git checkout -- .` which wiped the ENTIRE working tree.
        with contextlib.suppress(subprocess.CalledProcessError):
            run_git(["git", "checkout", "--", f"{BEADS_DIR}/"])

        # Force-apply .beads/ paths from the stash (theirs-wins strategy)
        try:
            run_git(["git", "checkout", "stash@{0}", "--", f"{BEADS_DIR}/"])
            print("✅ Force-applied .beads/ changes from stash.")
            # Only drop the stash after successful recovery
            try:
                run_git(["git", "stash", "drop"])
            except subprocess.CalledProcessError:
                print("⚠️ Could not drop stash after recovery. Run `git stash list` to clean up.")
        except subprocess.CalledProcessError as checkout_error:
            # Recovery failed — preserve the stash for manual inspection
            _print_command_output([checkout_error.stdout or "", checkout_error.stderr or ""])
            stash_ref = _get_stash_ref()
            ref_msg = f" (ref: {stash_ref})" if stash_ref else ""
            print(
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
            delay = base_delay * (2 ** attempt)
            logger.warning('git status retry %d/%d in %.1fs (index.lock contention)', attempt + 1, max_retries, delay)
            time.sleep(delay)
    assert last_exc is not None
    raise last_exc


def validate_post_merge(target_branch: str, cwd: str | None = None) -> bool:
    """Validate repository state after merge."""
    current_branch = run_git(
        ["git", "branch", "--show-current"], cwd=cwd).stdout.strip()
    if current_branch != target_branch:
        print(f"❌ Post-merge validation failed: Not on {target_branch} (on {current_branch})")
        return False
    status = run_git(
        ["git", "status", "--porcelain"], cwd=cwd).stdout.strip()
    if status:
        print(f"❌ Post-merge validation failed: {target_branch} has uncommitted changes")
        return False
    return True


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
