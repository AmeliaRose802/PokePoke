"""Shared Git helper utilities."""

from __future__ import annotations

import subprocess
from typing import List

__all__ = ["verify_branch_pushed", "restore_beads_stash"]


def verify_branch_pushed(branch_name: str) -> bool:
    """Return True when the given branch exists on origin."""
    try:
        result = subprocess.run(
            ["git", "ls-remote", "--heads", "origin", branch_name],
            capture_output=True,
            text=True,
            encoding='utf-8',
            check=True
        )
        return bool(result.stdout.strip())
    except subprocess.CalledProcessError:
        return False


def _print_command_output(lines: List[str]) -> None:
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
            encoding='utf-8'
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
                encoding='utf-8'
            )
            print("⚠️ Dropped beads stash entry to avoid accumulation.")
        except subprocess.CalledProcessError as drop_error:
            print("⚠️ Additionally failed to drop beads stash entry. Run `git stash list` to clean up manually.")
            _print_command_output([drop_error.stdout or "", drop_error.stderr or ""])
