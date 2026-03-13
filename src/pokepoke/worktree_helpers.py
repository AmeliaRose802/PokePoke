"""Extracted helpers for worktree management (file-length compliance)."""

import logging
import subprocess
from pathlib import Path

from pokepoke.beads_management import run_bd_sync_with_retry
from pokepoke.constants import BEADS_DIR, WORKTREE_DIR
from pokepoke.git_helpers import run_git
from pokepoke.git_operations import categorize_git_changes, commit_all_changes

logger = logging.getLogger(__name__)


def validate_worktree_integrity(worktree_path: Path, item_id: str) -> None:
    """Verify that a newly-created worktree has a working checkout.

    Raises RuntimeError when the worktree directory is empty or git reports
    it is not inside a work tree, so the caller can fail fast instead of
    dispatching an agent into a broken environment.
    """
    if not worktree_path.exists():
        raise RuntimeError(
            f"Worktree directory {worktree_path} does not exist after creation"
        )

    try:
        file_count = sum(1 for _ in worktree_path.iterdir())
    except OSError as exc:
        raise RuntimeError(f"Cannot read worktree directory {worktree_path}: {exc}") from exc

    if file_count == 0:
        raise RuntimeError(
            f"Worktree for {item_id} at {worktree_path} is empty (0 files) — "
            f"git checkout likely failed silently"
        )

    try:
        result = run_git(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=str(worktree_path),
            timeout=10,
            check=False,
        )
        if result.returncode != 0 or result.stdout.strip() != "true":
            raise RuntimeError(
                f"Worktree for {item_id} at {worktree_path} is not recognized by git "
                f"(rev-parse returned {result.returncode}: {result.stderr.strip()})"
            )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"git rev-parse timed out in worktree {worktree_path}") from exc

    logger.debug(f"Worktree integrity OK for {item_id}: {file_count} entries at {worktree_path}")


def sync_and_ensure_clean_main_repo(branch_name: str, cwd: str | None = None) -> bool:
    """Sync beads and ensure main repo is clean before merge.

    Args:
        branch_name: The branch about to be merged.
        cwd: Working directory for git commands (target repo root).
    """
    print("🔄 Syncing beads database before merge...")
    try:
        bd_sync_result = run_bd_sync_with_retry(timeout=30)
        if bd_sync_result.returncode != 0:
            print(f"⚠️  bd sync returned non-zero: {bd_sync_result.returncode}")
            print(f"   stdout: {bd_sync_result.stdout}")
            print(f"   stderr: {bd_sync_result.stderr}")
    except subprocess.TimeoutExpired:
        print("⚠️  bd sync timed out")
    try:
        main_status = run_git(
            ["git", "status", "--porcelain"], timeout=30, cwd=cwd,
        ).stdout.strip()
        if main_status:
            lines = main_status.split('\n')
            changes = categorize_git_changes(lines)
            if changes['other']:
                for line in changes['other'][:10]:
                    print(f"   ⚠️  pending: {line}")
                if len(changes['other']) > 10:
                    print(f"   ... and {len(changes['other']) - 10} more")
                ok, err = commit_all_changes(f"chore: commit pending changes before merge of {branch_name}", cwd=cwd, tracked_only=True)
                if not ok:
                    print(f"❌ Cannot merge: failed to commit pending changes: {err}")
                    return False
                print("✅ Pending main-branch changes committed")
            if changes['beads']:
                print("🔧 Committing beads database changes...")
                run_git(["git", "add", f"{BEADS_DIR}/"], cwd=cwd)
                run_git(
                    ["git", "commit", "-m", f"chore: sync beads before merge of {branch_name}"],
                    timeout=60, cwd=cwd,
                )
                print("✅ Beads changes committed")
            if changes['worktree']:
                print("🧹 Committing worktree cleanup changes...")
                run_git(["git", "add", f"{WORKTREE_DIR}/"], cwd=cwd)
                run_git(
                    ["git", "commit", "-m", "chore: cleanup deleted worktree directories"],
                    timeout=60, cwd=cwd,
                )
                print("✅ Worktree cleanup committed")
        return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        print(f"❌ Failed to check/clean main repo: {e}")
        return False
