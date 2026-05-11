"""Helper functions for merge operations in worktree management."""

import logging
import subprocess
from pathlib import Path

from pokepoke.git.git_helpers import run_git as _run_git
from pokepoke.git.git_operations import get_default_branch, sanitize_branch_name, validate_post_merge
from pokepoke.utils.constants import BRANCH_PREFIX
from pokepoke.worktrees.merge_result import MergeResult

logger = logging.getLogger(__name__)

# Maximum non-blank lines allowed per Python source file.
# Must match the threshold in .githooks/check-file-length.ps1.
MAX_PYTHON_LINES = 400
MAX_DESKTOP_LINES = 500


def log_merge_failure(merge_error: str | None, unmerged_files: list[str]) -> None:
    """Log details about a merge failure."""
    if unmerged_files:
        logger.error(f"❌ Merge conflicts detected in {len(unmerged_files)} file(s):")
        for f in unmerged_files[:10]:
            logger.info(f"   - {f}")
        if len(unmerged_files) > 10:
            logger.info(f"   ... and {len(unmerged_files) - 10} more")
    else:
        logger.error(f"❌ Merge failed: {merge_error}")


def validate_post_merge_or_rollback(target_branch: str, cwd: str | None = None) -> MergeResult | None:
    """Run post-merge validation.  Failure is a CRITICAL invariant violation.

    After a successful ``git merge --no-ff`` the repo MUST be on the target
    branch with no uncommitted changes.  If either check fails it indicates
    git state corruption, a filesystem issue, or a bug in the merge sequence.

    On failure the repo state is **preserved** (no rollback) so it can be
    inspected manually, and a CRITICAL log with diagnostics is emitted.
    The returned MergeResult has ``halt_required=True`` to signal the
    orchestrator to stop processing further items.

    Returns None if validation passed, or a failure MergeResult otherwise.
    """
    try:
        if not validate_post_merge(target_branch, cwd=cwd):
            _log_post_merge_diagnostics(target_branch, cwd)
            return MergeResult(success=False, halt_required=True)
    except Exception as e:
        logger.critical(
            "POST-MERGE VALIDATION EXCEPTION — repo state preserved for investigation: %s",
            e, exc_info=True,
        )
        _log_post_merge_diagnostics(target_branch, cwd)
        return MergeResult(success=False, halt_required=True)
    return None


def _log_post_merge_diagnostics(target_branch: str, cwd: str | None) -> None:
    """Emit CRITICAL-level diagnostics after a post-merge invariant violation."""
    diag_parts: list[str] = []
    try:
        status = _run_git(["git", "status", "--short"], cwd=cwd).stdout.strip()
        diag_parts.append(f"git status:\n{status or '(clean)'}")
    except Exception:
        diag_parts.append("git status: <unavailable>")
    try:
        log_out = _run_git(
            ["git", "log", "--oneline", "-5"], cwd=cwd,
        ).stdout.strip()
        diag_parts.append(f"git log -5:\n{log_out}")
    except Exception:
        diag_parts.append("git log: <unavailable>")
    try:
        branch = _run_git(
            ["git", "branch", "--show-current"], cwd=cwd,
        ).stdout.strip()
        diag_parts.append(f"current branch: {branch}")
    except Exception:
        diag_parts.append("current branch: <unavailable>")

    diagnostics = "\n".join(diag_parts)
    logger.critical(
        "🚨 POST-MERGE INVARIANT VIOLATION — repo state preserved (no rollback).\n"
        "Expected to be on '%s' with clean status after merge.\n"
        "This indicates git state corruption or a merge sequence bug.\n"
        "The orchestrator will halt. Manual investigation required.\n\n%s",
        target_branch, diagnostics,
    )


def is_worktree_merged(item_id: str, target_branch: str | None = None, repo_path: str | None = None) -> bool:
    """Check if a worktree's branch has been merged into the target branch."""
    sanitized_id = sanitize_branch_name(item_id)
    branch_name = f"{BRANCH_PREFIX}{sanitized_id}"
    if target_branch is None:
        target_branch = get_default_branch(cwd=repo_path)
    try:
        result = _run_git(["git", "branch", "--merged", target_branch], cwd=repo_path)
        return any(branch_name in branch for branch in result.stdout.splitlines())
    except subprocess.CalledProcessError:
        return False


def integrate_target_into_worktree(
    worktree_path: Path,
    target_branch: str,
) -> MergeResult:
    """Merge target branch INTO the worktree branch so conflicts resolve in isolation.

    After a successful integration the worktree branch is a superset of the
    target, making the subsequent merge to the target guaranteed conflict-free.
    Master is never left dirty — only the expendable worktree is touched.
    """
    from pokepoke.git.git_operations import _auto_resolve_pokepoke_conflicts
    from pokepoke.git.merge_conflict import abort_merge, get_unmerged_files, is_merge_in_progress

    wt = str(worktree_path)
    try:
        _run_git(
            ["git", "merge", target_branch, "--no-verify",
             "-m", f"Integrate {target_branch} before merge to mainline"],
            cwd=wt, timeout=120,
        )
        logger.info(
            "✅ Pre-merge integration: %s merged into worktree branch", target_branch,
        )
        return MergeResult(success=True)
    except subprocess.CalledProcessError:
        unmerged = get_unmerged_files(repo_path=worktree_path)

        # Auto-resolve .pokepoke/ runtime state conflicts
        if is_merge_in_progress(repo_path=worktree_path) and unmerged:
            remaining = _auto_resolve_pokepoke_conflicts(unmerged, cwd=wt)
            if not remaining:
                try:
                    _run_git(
                        ["git", "commit", "--no-verify", "--no-edit"],
                        cwd=wt, timeout=120,
                    )
                    logger.info(
                        "✅ Pre-merge integration: auto-resolved .pokepoke/ conflicts",
                    )
                    return MergeResult(success=True)
                except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
                    logger.warning(
                        "Failed to complete integration after auto-resolving "
                        ".pokepoke/ conflicts: %s", exc,
                    )
            unmerged = remaining

        # Abort the merge in the worktree — master is untouched
        if is_merge_in_progress(repo_path=worktree_path):
            ok, msg = abort_merge(repo_path=worktree_path)
            if ok:
                logger.info("Aborted integration merge in worktree (master is clean)")
            else:
                logger.error(
                    "Failed to abort integration merge in worktree: %s", msg,
                )

        logger.warning(
            "❌ Pre-merge integration failed: %d conflict(s) in worktree "
            "(master untouched)",
            len(unmerged),
        )
        return MergeResult(success=False, unmerged_files=unmerged)
    except subprocess.TimeoutExpired:
        if is_merge_in_progress(repo_path=worktree_path):
            abort_merge(repo_path=worktree_path)
        logger.warning("❌ Pre-merge integration timed out in worktree")
        return MergeResult(success=False)


def _count_non_blank_lines(file_path: Path) -> int:
    """Count non-blank lines in a file (mirrors .githooks/check-file-length.ps1)."""
    try:
        text = file_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return 0
    return sum(1 for line in text.splitlines() if line.strip())


def validate_pre_merge_quality(
    worktree_path: Path,
    target_branch: str,
) -> list[str]:
    """Run lightweight quality gates on worktree files before merging to main.

    Checks the files that differ between the target branch and the worktree
    branch HEAD against the same thresholds enforced by pre-commit hooks
    (file-length limits).  ``git merge`` does not trigger pre-commit hooks,
    so this is the last line of defence before bad code lands on main.

    Returns a list of human-readable violation descriptions (empty = pass).
    """
    wt = str(worktree_path)
    violations: list[str] = []

    # Get files changed on the worktree branch vs the target
    try:
        result = _run_git(
            ["git", "diff", "--name-only", target_branch, "HEAD"],
            cwd=wt, timeout=30,
        )
        changed_files = [f for f in result.stdout.strip().splitlines() if f]
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        logger.warning("Pre-merge quality check: unable to diff changed files, skipping")
        return []

    for rel_path in changed_files:
        full_path = worktree_path / rel_path
        if not full_path.is_file():
            continue

        # Python files: 400 non-blank line limit
        if rel_path.endswith(".py") and not rel_path.startswith("tests/"):
            count = _count_non_blank_lines(full_path)
            if count > MAX_PYTHON_LINES:
                violations.append(
                    f"{rel_path}: {count} non-blank lines (limit {MAX_PYTHON_LINES}, +{count - MAX_PYTHON_LINES})"
                )

        # Desktop JS/TS files: 500 non-blank line limit
        if rel_path.startswith("desktop/src/") and any(
            rel_path.endswith(ext) for ext in (".ts", ".tsx", ".js", ".jsx")
        ):
            count = _count_non_blank_lines(full_path)
            if count > MAX_DESKTOP_LINES:
                violations.append(
                    f"{rel_path}: {count} non-blank lines (limit {MAX_DESKTOP_LINES}, +{count - MAX_DESKTOP_LINES})"
                )

    if violations:
        logger.error(
            "❌ Pre-merge quality gate FAILED — %d file(s) exceed line limits:\n  %s",
            len(violations),
            "\n  ".join(violations),
        )
    else:
        logger.info("✅ Pre-merge quality gate passed")

    return violations
