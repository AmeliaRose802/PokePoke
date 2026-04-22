"""Repository status check and maintenance utilities."""

import logging
import shutil
import subprocess
import time
from pathlib import Path
from typing import TYPE_CHECKING

from pokepoke.git.git_operations import get_status_porcelain_and_changes
from pokepoke.git.repo_state_guard import cleanup_lock
from pokepoke.utils.constants import BEADS_DIR, CLEANUP_AGGREGATE_TIMEOUT, STATUS_IN_PROGRESS
from pokepoke.worktrees.coordination import main_repo_git_lock, merge_lock_active

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from pokepoke.utils.logging_utils import RunLogger

# Maximum number of cleanup agent retries before falling back to stash
MAX_CLEANUP_RETRIES = 3
BD_INFO_TIMEOUT = 30
BD_INIT_TIMEOUT = 120


def check_beads_available() -> bool:
    """Check that beads (bd) is installed and initialized in the current directory.

    Since beads v0.56+ uses a Dolt server, ``bd info --json`` fails when the
    server isn't running.  We check for the ``.beads/`` directory on disk
    instead, which is reliable regardless of server state.
    """
    if not shutil.which('bd'):
        logger.error("Error: 'bd' (beads) command not found.")
        logger.info("   PokePoke requires beads for work item tracking.")
        logger.info("   Install beads: pip install beads")
        logger.info("   Then initialize: bd init")
        return False

    beads_dir = Path.cwd() / BEADS_DIR
    if not beads_dir.is_dir():
        logger.error("\nError: This directory is not a beads repository.")
        logger.info("   Run 'bd init' to set up beads tracking.")
        return False

    # Verify it has at least a config file (not just an empty directory)
    has_marker = any(
        (beads_dir / name).exists()
        for name in ("config.yaml", "config.yml", "issues.jsonl", "beads.db")
    )
    if not has_marker:
        logger.error("\nError: .beads/ directory exists but appears incomplete.")
        logger.info("   Run 'bd init' to reinitialize beads tracking.")
        return False

    return True


def _run_bd_command(
    cmd: list[str],
    repo_path: Path,
    timeout: int,
    error_context: str,
) -> subprocess.CompletedProcess[str] | None:
    """Run a bd subprocess command with standard timeout/error handling.

    Returns the CompletedProcess on success, or None if an exception occurred.
    """
    try:
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            cwd=str(repo_path),
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        logger.error(f"\nError: '{' '.join(cmd)}' timed out ({error_context}).")
        return None
    except Exception as e:
        logger.error(f"\nError: {error_context}: {e}")
        return None


def initialize_beads_repo(repo_path: Path) -> bool:
    """Initialize beads in the given repository directory."""
    if not shutil.which('bd'):
        logger.error("Error: 'bd' (beads) command not found.")
        logger.info("   Install beads: pip install beads")
        return False

    # Already initialized?
    result = _run_bd_command(['bd', 'info', '--json'], repo_path, BD_INFO_TIMEOUT, "Failed to check beads status")
    if result is None:
        return False
    if result.returncode == 0:
        return True

    # Initialize
    result = _run_bd_command(['bd', 'init', '--quiet'], repo_path, BD_INIT_TIMEOUT, "Failed to run 'bd init'")
    if result is None:
        return False
    if result.returncode != 0:
        logger.error(f"\nError: Failed to initialize beads in: {repo_path}")
        details = (result.stderr or result.stdout or "").strip()
        if details:
            logger.info(details)
        logger.info("\nTry running manually:")
        logger.info("   bd init")
        return False

    # Verify
    result = _run_bd_command(['bd', 'info', '--json'], repo_path, BD_INFO_TIMEOUT, "Failed to verify beads initialization")
    if result is None:
        return False
    if result.returncode != 0:
        logger.error("\nError: Beads initialization did not complete successfully.")
        logger.info("   'bd info' still fails after initialization.")
        return False

    return True


def _try_auto_commit(repo_path: Path, run_logger: 'RunLogger') -> bool:
    """Attempt to auto-commit uncommitted changes with git add -u + git commit.

    Tried before the cleanup agent so trivial changes can be committed quickly.
    Returns True on success, False otherwise (e.g. pre-commit hooks reject).
    """
    with main_repo_git_lock():
        try:
            subprocess.run(
                ["git", "add", "-u"], check=True, capture_output=True,
                encoding='utf-8', errors='replace', cwd=str(repo_path), timeout=30,
            )
            result = subprocess.run(
                ["git", "commit", "-m", "chore: auto-commit uncommitted changes"],
                capture_output=True, text=True, encoding='utf-8', errors='replace',
                cwd=str(repo_path), timeout=120,
            )
            if result.returncode == 0:
                run_logger.log_orchestrator("Auto-committed uncommitted changes")
                return True
            run_logger.log_orchestrator(
                f"Auto-commit failed (will try cleanup agent): {result.stderr.strip() or 'unknown error'}",
                level="WARNING",
            )
        except subprocess.TimeoutExpired:
            run_logger.log_orchestrator("Auto-commit timed out", level="WARNING")
        except subprocess.CalledProcessError as e:
            run_logger.log_orchestrator(
                f"Auto-commit git add failed: {e.stderr.strip() if e.stderr else f'exit code {e.returncode}'}",
                level="WARNING",
            )
        except Exception as e:
            run_logger.log_orchestrator(f"Auto-commit failed: {e}", level="WARNING")
    return False


def _stash_uncommitted_changes(repo_path: Path, run_logger: 'RunLogger') -> bool:
    """Attempt to stash uncommitted changes as a fallback."""
    with main_repo_git_lock():
        try:
            subprocess.run(
                ["git", "add", "-u"], check=True, capture_output=True,
                encoding='utf-8', errors='replace', cwd=str(repo_path), timeout=30,
            )
            import datetime
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            stash_msg = f"pokepoke-auto-stash-{timestamp}: cleanup agent failed"
            result = subprocess.run(
                ["git", "stash", "push", "-m", stash_msg], capture_output=True,
                text=True, encoding='utf-8', errors='replace', cwd=str(repo_path), timeout=60,
            )
            if result.returncode == 0:
                run_logger.log_orchestrator(f"Stashed changes: {stash_msg}")
                return True
            run_logger.log_orchestrator(
                f"git stash failed: {result.stderr.strip() or 'unknown error'}", level="WARNING",
            )
        except subprocess.TimeoutExpired:
            run_logger.log_orchestrator("git stash timed out", level="WARNING")
        except subprocess.CalledProcessError as e:
            run_logger.log_orchestrator(
                f"git add for stash failed: {e.stderr.strip() if e.stderr else f'exit code {e.returncode}'}",
                level="WARNING",
            )
        except Exception as e:
            run_logger.log_orchestrator(f"Stash failed: {e}", level="WARNING")
    return False


def _run_cleanup_retries(repo_path: Path, run_logger: 'RunLogger') -> bool:
    """Run cleanup agent retries with aggregate timeout.

    Uses the merge-conflict-aware agent when conflict markers are detected.
    """
    from pokepoke.agents.cleanup_agents import invoke_cleanup_agent, invoke_merge_conflict_cleanup_agent
    from pokepoke.types import BeadsWorkItem

    cleanup_loop_start = time.monotonic()
    conflict_files = _detect_conflict_marker_files(repo_path)
    use_merge_agent = bool(conflict_files)

    if use_merge_agent:
        run_logger.log_orchestrator(
            f"Conflict markers detected in {len(conflict_files)} file(s) without MERGE_HEAD",
            level="WARNING",
        )

    for attempt in range(1, MAX_CLEANUP_RETRIES + 1):
        elapsed = time.monotonic() - cleanup_loop_start
        if elapsed >= CLEANUP_AGGREGATE_TIMEOUT:
            run_logger.log_orchestrator(
                f"Cleanup aggregate timeout ({CLEANUP_AGGREGATE_TIMEOUT:.0f}s) exceeded",
                level="WARNING",
            )
            return False

        cleanup_item = BeadsWorkItem(
            id=f"cleanup-main-repo-{attempt}",
            title="Clean up uncommitted changes in main repository",
            description="Auto-generated cleanup task for uncommitted changes",
            issue_type="task", priority=0, status=STATUS_IN_PROGRESS,
            labels=["cleanup", "auto-generated"],
        )

        item_logger = run_logger.start_item_log(
            cleanup_item.id, cleanup_item.title, agent_name="cleanup",
        )

        with cleanup_lock():
            if use_merge_agent:
                cleanup_success, _ = invoke_merge_conflict_cleanup_agent(
                    cleanup_item,
                    error_msg="Residual conflict markers found in working tree (MERGE_HEAD absent)",
                    unmerged_files=conflict_files, cwd=str(repo_path), wait_for_merge=False,
                    item_logger=item_logger,
                )
            else:
                cleanup_success, _ = invoke_cleanup_agent(
                    cleanup_item, cwd=str(repo_path), wait_for_merge=False,
                    item_logger=item_logger,
                )

        if cleanup_success:
            run_logger.log_orchestrator("Cleanup agent successfully resolved uncommitted changes")
            return True

        if attempt < MAX_CLEANUP_RETRIES:
            conflict_files = _detect_conflict_marker_files(repo_path)
            use_merge_agent = bool(conflict_files)
            wait_time = 2 ** attempt
            run_logger.log_orchestrator(f"Cleanup attempt {attempt} failed, retrying", level="WARNING")
            time.sleep(wait_time)

    return False


def _detect_conflict_marker_files(repo_path: Path) -> list[str]:
    """Return file paths under *repo_path* that have conflict markers."""
    from pokepoke.git.merge_conflict import detect_dirty_conflict_files
    return detect_dirty_conflict_files(repo_path)


def _restore_conflicted_files(repo_path: Path, run_logger: 'RunLogger') -> bool:
    """``git checkout -- <file>`` for files with residual conflict markers."""
    conflict_files = _detect_conflict_marker_files(repo_path)
    if not conflict_files:
        return False

    logger.warning(f"🔄 Restoring {len(conflict_files)} file(s) with conflict markers")
    run_logger.log_orchestrator(
        f"Restoring {len(conflict_files)} conflicted file(s) via git checkout", level="WARNING",
    )

    restored_any = False
    with main_repo_git_lock():
        for fpath in conflict_files:
            try:
                subprocess.run(
                    ["git", "checkout", "--", fpath], capture_output=True, text=True,
                    encoding='utf-8', errors='replace', cwd=str(repo_path), timeout=30,
                )
                logger.info(f"   Restored: {fpath}")
                restored_any = True
            except Exception as e:
                logger.warning(f"   Failed to restore {fpath}: {e}")
    if restored_any:
        run_logger.log_orchestrator("Conflicted files restored to last committed version")
    return restored_any


def _try_reset_working_tree(repo_path: Path, run_logger: 'RunLogger') -> bool:
    """Reset working tree to HEAD, discarding all unstaged modifications.

    Fast path for dirty merge residue: ``git checkout -- .`` reverts all
    tracked files to their last-committed state in seconds, avoiding the
    multi-minute cleanup-agent loop.
    """
    with main_repo_git_lock():
        try:
            subprocess.run(
                ["git", "checkout", "--", "."], check=True, capture_output=True,
                encoding='utf-8', errors='replace', cwd=str(repo_path), timeout=30,
            )
            # Verify the reset actually cleaned up
            uncommitted, _ = get_status_porcelain_and_changes(str(repo_path), timeout=10)
            if not uncommitted:
                run_logger.log_orchestrator("Working tree reset to HEAD")
                return True
            run_logger.log_orchestrator(
                f"Reset left {len(uncommitted.splitlines())} file(s) dirty", level="WARNING")
        except Exception as e:
            run_logger.log_orchestrator(f"Working tree reset failed: {e}", level="WARNING")
    return False


def _handle_other_changes(repo_path: Path, changes: dict[str, list[str]], run_logger: 'RunLogger') -> bool:
    """Handle non-beads, non-worktree uncommitted changes.

    Tries auto-commit → fast reset → cleanup agent → restore → stash.
    Returns False when all strategies fail, blocking agent dispatch to prevent
    wasting resources on a dirty master that will cause merge failures.
    """
    run_logger.log_orchestrator("Main repository has uncommitted changes", level="WARNING")
    for line in changes['other'][:10]:
        logger.info(f"   {line}")

    logger.info("\n🔄 Attempting to auto-commit changes...")
    if _try_auto_commit(repo_path, run_logger):
        return True

    # Fast path: reset working tree to HEAD.  Handles dirty merge residue
    # in seconds instead of the multi-minute cleanup agent loop.
    if _try_reset_working_tree(repo_path, run_logger):
        return True

    run_logger.log_orchestrator("Auto-commit and reset failed, launching cleanup agent")
    if merge_lock_active():
        run_logger.log_orchestrator("Deferring cleanup due to active merge operation")
        return True

    if _run_cleanup_retries(repo_path, run_logger):
        return True

    if _restore_conflicted_files(repo_path, run_logger):
        logger.info("✅ Conflicted files restored — retrying auto-commit")
        if _try_auto_commit(repo_path, run_logger):
            return True

    run_logger.log_orchestrator("Cleanup retries exhausted, attempting git stash", level="WARNING")
    if _stash_uncommitted_changes(repo_path, run_logger):
        run_logger.log_orchestrator("Uncommitted changes stashed successfully")
        return True

    run_logger.log_orchestrator(
        "All cleanup strategies failed — blocking dispatch until master is clean",
        level="CRITICAL",
    )
    return False


def check_and_commit_main_repo(repo_path: Path, run_logger: 'RunLogger') -> bool:
    """Check main repository status and commit beads changes if needed.

    Args:
        repo_path: Path to the main repository
        run_logger: Run logger instance

    Returns:
        True if ready to continue, False if should exit
    """
    try:
        uncommitted, changes = get_status_porcelain_and_changes(str(repo_path), timeout=30)
    except subprocess.CalledProcessError as e:
        # Handle git errors gracefully
        error_msg = e.stderr.strip() if e.stderr else f"exit code {e.returncode}"
        logger.error(f"⚠️  Warning: git status failed in {repo_path}: {error_msg}")
        run_logger.log_orchestrator(f"git status failed: {error_msg}", level="WARNING")
        # Check if this is a valid git repository
        git_dir = repo_path / ".git"
        if not git_dir.exists():
            logger.error(f"❌ Error: {repo_path} is not a git repository")
            run_logger.log_orchestrator(f"{repo_path} is not a git repository", level="ERROR")
            return False
        # For other git errors, try to continue
        logger.error("   Continuing despite git error...")
        return True

    if uncommitted:

        # Handle problematic changes that need agent intervention
        if changes['other']:
            return _handle_other_changes(repo_path, changes, run_logger)

        # Beads changes are handled by beads' own sync mechanism (bd sync)
        # Do NOT manually commit them - beads daemon handles this automatically
        if changes['beads']:
            logger.info("ℹ️  Beads database changes detected - will be synced by beads daemon")
            logger.info("ℹ️  Run 'bd sync' to force immediate sync if needed")

    return True
