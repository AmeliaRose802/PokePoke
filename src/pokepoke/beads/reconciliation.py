"""Post-session reconciliation logic.

Detects whether work for a beads item already landed (merged, closed,
worktree cleaned) even when the Copilot CLI session reported failure.
"""

from __future__ import annotations

import contextlib
import json
import logging
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from pokepoke.beads.beads_query import _run_bd_with_retry
from pokepoke.git.git_helpers import run_git
from pokepoke.git.git_operations import get_default_branch, list_worktrees, sanitize_branch_name
from pokepoke.utils.constants import BRANCH_PREFIX, WORKTREE_DIR, WORKTREE_TASK_PREFIX

if TYPE_CHECKING:
    from pokepoke.types import BeadsWorkItem
    from pokepoke.utils.logging_utils import RunLogger

logger = logging.getLogger(__name__)


def is_beads_item_closed(item_id: str) -> bool:
    """Return True if the beads item is already closed or completed."""
    try:
        result = _run_bd_with_retry(
            ["show", item_id, "--json"],
            timeout=30,
        )
        items = json.loads(result.stdout or "[]")
        if not items:
            return False
        status = (items[0].get("status") or "").lower()
        return status in {"closed", "completed"}
    except Exception as exc:  # pragma: no cover - defensive guard
        logger.warning("Failed to check beads status for %s: %s", item_id, exc)
        return False


def default_branch_has_merge_commit(item_id: str, repo_root: Path) -> bool:
    """Check whether origin/default branch contains the worktree merge commit."""
    sanitized_id = sanitize_branch_name(item_id)
    branch_marker = f"{BRANCH_PREFIX}{sanitized_id}"
    default_branch = get_default_branch()

    # Best-effort fetch; ignore failures to keep reconciliation non-fatal.
    with contextlib.suppress(Exception):
        run_git(
            ["git", "fetch", "origin", default_branch],
            timeout=30, cwd=str(repo_root), check=False,
        )

    for ref in (f"origin/{default_branch}", default_branch):
        try:
            result = run_git(
                ["git", "log", ref, "--max-count", "50",
                 "--grep", branch_marker, "--pretty=format:%H"],
                timeout=20, cwd=str(repo_root),
            )
            if result.stdout.strip():
                return True
        except subprocess.CalledProcessError:
            continue
    return False


def worktree_branch_has_commits(item_id: str, repo_root: Path) -> bool:
    """Check whether the worktree branch for *item_id* has commits beyond the default branch."""
    sanitized_id = sanitize_branch_name(item_id)
    branch_name = f"{BRANCH_PREFIX}{sanitized_id}"
    default_branch = get_default_branch()

    for ref in (branch_name, f"refs/heads/{branch_name}"):
        try:
            result = run_git(
                ["git", "log", f"{default_branch}..{ref}", "--max-count", "1",
                 "--pretty=format:%H"],
                timeout=20, cwd=str(repo_root),
            )
            if result.stdout.strip():
                return True
        except subprocess.CalledProcessError:
            continue
    return False


def is_worktree_cleaned(item_id: str, worktree_path: Path | None) -> bool:
    """Return True if the worktree and branch for the item are already cleaned up."""
    sanitized_id = sanitize_branch_name(item_id)
    expected_path = (worktree_path or Path.cwd() / WORKTREE_DIR / f"{WORKTREE_TASK_PREFIX}{sanitized_id}").resolve()
    active = list_worktrees()

    for wt in active:
        branch = wt.get("branch", "")
        path_str = wt.get("path")
        if branch.endswith(f"{BRANCH_PREFIX}{sanitized_id}"):
            return False
        if path_str:
            try:
                if Path(path_str).resolve() == expected_path:
                    return False
            except OSError as exc:
                logger.warning("Failed to resolve worktree path %s: %s", path_str, exc)
                return False

    return not expected_path.exists()


def reconcile_completed_item(
    item: BeadsWorkItem,
    worktree_path: Path | None,
    run_logger: RunLogger | None,
) -> tuple[bool, dict[str, bool]]:
    """Detect whether work already landed even if the Copilot session failed.

    Reconciliation is considered successful only when:
    - ``beads_closed`` is True, and
    - ``commits_on_default`` is True.

    This prevents false positives where an item was closed but commits remain
    unmerged on a worktree branch.
    """
    repo_root = Path.cwd()
    evidence: dict[str, bool] = {
        "beads_closed": is_beads_item_closed(item.id),
        "commits_on_default": default_branch_has_merge_commit(item.id, repo_root),
        "commits_on_worktree_branch": worktree_branch_has_commits(item.id, repo_root),
        "worktree_cleaned": is_worktree_cleaned(item.id, worktree_path),
    }

    reconciled = evidence["beads_closed"] and evidence["commits_on_default"]

    if run_logger:
        run_logger.log_orchestrator(
            f"Post-session reconciliation for {item.id}: {evidence}",
            level="WARNING" if reconciled else "INFO",
        )

    return reconciled, evidence
