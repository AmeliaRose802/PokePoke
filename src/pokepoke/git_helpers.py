"""Shared Git helper utilities."""

from __future__ import annotations

import contextlib
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
            errors='replace',
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
    """Apply stashed .beads/ changes, logging conflicts and cleaning up stale entries.

    On pop failure, force-applies .beads/ paths from the stash (local beads
    state is authoritative) and only drops the stash after successful recovery.
    If recovery also fails the stash is preserved for manual inspection.
    """
    try:
        subprocess.run(
            ["git", "stash", "pop", "--index"],
            check=True,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=30
        )
    except subprocess.CalledProcessError as pop_error:
        print(f"⚠️ Stash pop conflict after {context}. Attempting to force-apply .beads/ changes.")
        _print_command_output([pop_error.stdout or "", pop_error.stderr or ""])

        # Reset any partially-applied pop so checkout doesn't hit conflicts
        with contextlib.suppress(subprocess.CalledProcessError):
            subprocess.run(
                ["git", "checkout", "--", "."],
                check=True, capture_output=True, text=True,
                encoding='utf-8', errors='replace', timeout=30
            )

        # Force-apply .beads/ paths from the stash (theirs-wins strategy)
        try:
            subprocess.run(
                ["git", "checkout", "stash@{0}", "--", ".beads/"],
                check=True,
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace',
                timeout=30
            )
            print("✅ Force-applied .beads/ changes from stash.")
            # Only drop the stash after successful recovery
            try:
                subprocess.run(
                    ["git", "stash", "drop"],
                    check=True, capture_output=True, text=True,
                    encoding='utf-8', errors='replace', timeout=30
                )
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
        result = subprocess.run(
            ["git", "stash", "list", "-1"],
            capture_output=True, text=True,
            encoding='utf-8', errors='replace',
            timeout=10
        )
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
