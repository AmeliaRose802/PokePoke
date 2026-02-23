"""Shared Git helper utilities."""

from __future__ import annotations

import logging
import subprocess
import time

logger = logging.getLogger(__name__)

__all__ = ["verify_branch_pushed", "restore_beads_stash", "_run_git_status_with_retry"]


def verify_branch_pushed(branch_name: str) -> bool:
    """Return True when the given branch exists on origin."""
    try:
        result = subprocess.run(
            ["git", "ls-remote", "--heads", "origin", branch_name],
            capture_output=True,
            text=True,
            encoding='utf-8',
            check=True,
            timeout=120
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
    """Apply stashed .beads/ changes, logging conflicts and cleaning up stale entries."""
    try:
        subprocess.run(
            ["git", "stash", "pop", "--index"],
            check=True,
            capture_output=True,
            text=True,
            encoding='utf-8',
            timeout=30
        )
    except subprocess.CalledProcessError as pop_error:
        print(f"⚠️ Failed to re-apply beads stash after {context}. Inspect .beads/ changes manually.")
        _print_command_output([pop_error.stdout or "", pop_error.stderr or ""])
        try:
            subprocess.run(
                ["git", "stash", "drop"],
                check=True,
                capture_output=True,
                text=True,
                encoding='utf-8',
                timeout=30
            )
            print("⚠️ Dropped beads stash entry to avoid accumulation.")
        except subprocess.CalledProcessError as drop_error:
            print("⚠️ Additionally failed to drop beads stash entry. Run `git stash list` to clean up manually.")
            _print_command_output([drop_error.stdout or "", drop_error.stderr or ""])


def _run_git_status_with_retry(
    args: list[str], cwd: str | None = None,
    max_retries: int = 3, base_delay: float = 0.5, timeout: int = 10,
) -> subprocess.CompletedProcess[str]:
    """Run git status with exponential-backoff retry on index.lock contention."""
    last_exc: Exception | None = None
    for attempt in range(max_retries):
        try:
            return subprocess.run(
                args, capture_output=True, text=True, encoding='utf-8',
                errors='replace', check=True, timeout=timeout, cwd=cwd,
            )
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
