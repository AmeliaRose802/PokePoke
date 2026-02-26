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

from pokepoke.git_operations import get_default_branch, list_worktrees, sanitize_branch_name

if TYPE_CHECKING:
    from pokepoke.types import BeadsWorkItem
    from pokepoke.logging_utils import RunLogger

logger = logging.getLogger(__name__)


def is_beads_item_closed(item_id: str) -> bool:
    """Return True if the beads item is already closed or completed."""
    try:
        result = subprocess.run(
            ["bd", "show", item_id, "--json"],
            capture_output=True, text=True,
            encoding="utf-8", errors="replace",
            check=True, timeout=30,
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
    branch_marker = f"task/{sanitized_id}"
    default_branch = get_default_branch()

    # Best-effort fetch; ignore failures to keep reconciliation non-fatal.
    with contextlib.suppress(Exception):
        subprocess.run(
            ["git", "fetch", "origin", default_branch],
            capture_output=True, text=True,
            encoding="utf-8", errors="replace",
            timeout=30, cwd=str(repo_root), check=False,
        )

    for ref in (f"origin/{default_branch}", default_branch):
        try:
            result = subprocess.run(
                ["git", "log", ref, "--max-count", "50",
                 "--grep", branch_marker, "--pretty=format:%H"],
                capture_output=True, text=True,
                encoding="utf-8", errors="replace",
                check=True, timeout=20, cwd=str(repo_root),
            )
            if result.stdout.strip():
                return True
        except subprocess.CalledProcessError:
            continue
    return False


def is_worktree_cleaned(item_id: str, worktree_path: Path | None) -> bool:
    """Return True if the worktree and branch for the item are already cleaned up."""
    sanitized_id = sanitize_branch_name(item_id)
    expected_path = (worktree_path or Path.cwd() / "worktrees" / f"task-{sanitized_id}").resolve()
    active = list_worktrees()

    for wt in active:
        branch = wt.get("branch", "")
        path_str = wt.get("path")
        if branch.endswith(f"task/{sanitized_id}"):
            return False
        if path_str:
            try:
                if Path(path_str).resolve() == expected_path:
                    return False
            except Exception:
                continue

    return not expected_path.exists()


def reconcile_completed_item(
    item: BeadsWorkItem,
    worktree_path: Path | None,
    run_logger: RunLogger | None,
) -> tuple[bool, dict[str, bool]]:
    """Detect whether work already landed even if the Copilot session failed."""
    repo_root = Path.cwd()
    evidence: dict[str, bool] = {
        "beads_closed": is_beads_item_closed(item.id),
        "commits_on_default": default_branch_has_merge_commit(item.id, repo_root),
        "worktree_cleaned": is_worktree_cleaned(item.id, worktree_path),
    }

    if run_logger:
        run_logger.log_orchestrator(
            f"Post-session reconciliation for {item.id}: {evidence}",
            level="WARNING" if all(evidence.values()) else "INFO",
        )

    return all(evidence.values()), evidence
