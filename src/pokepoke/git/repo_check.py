"""Repository status check and maintenance utilities."""

import logging
import shutil
import subprocess
import time
from pathlib import Path
from typing import TYPE_CHECKING

from pokepoke.git.git_helpers import run_git
from pokepoke.git.git_operations import get_status_porcelain_and_changes
from pokepoke.git.repo_state_guard import cleanup_lock
from pokepoke.utils.constants import BEADS_DIR, CLEANUP_AGGREGATE_TIMEOUT, STATUS_IN_PROGRESS, WORKTREE_DIR
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
    """Attempt to auto-commit uncommitted changes with git add + git commit.

    This is tried before launching the cleanup agent so that trivial changes
    (e.g., modified tracking files) can be committed quickly without wasting
    tokens on an AI agent.

    Args:
        repo_path: Path to the repository
        run_logger: Run logger instance

    Returns:
        True if auto-commit succeeded, False otherwise (e.g., pre-commit hooks reject)
    """
    with main_repo_git_lock():
        try:
            # Use -u (tracked only) to avoid staging untracked files like
            # .pokepoke/ runtime state which could cause merge conflicts
            subprocess.run(
                ["git", "add", "-u"],
                check=True,
                capture_output=True,
                encoding='utf-8',
                errors='replace',
                cwd=str(repo_path),
                timeout=30
            )

            result = subprocess.run(
                ["git", "commit", "-m", "chore: auto-commit uncommitted changes"],
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace',
                cwd=str(repo_path),
                timeout=120
            )

            if result.returncode == 0:
                run_logger.log_orchestrator("Auto-committed uncommitted changes")
                return True

            # Commit failed (e.g., pre-commit hooks rejected)
            error_msg = result.stderr.strip() if result.stderr else "unknown error"
            run_logger.log_orchestrator(
                f"Auto-commit failed (will try cleanup agent): {error_msg}",
                level="WARNING"
            )
            return False

        except subprocess.TimeoutExpired:
            run_logger.log_orchestrator("Auto-commit timed out", level="WARNING")
            return False
        except subprocess.CalledProcessError as e:
            error_msg = e.stderr.strip() if e.stderr else f"exit code {e.returncode}"
            run_logger.log_orchestrator(
                f"Auto-commit git add failed: {error_msg}", level="WARNING"
            )
            return False
        except Exception as e:
            run_logger.log_orchestrator(f"Auto-commit failed: {e}", level="WARNING")
            return False


def _stash_uncommitted_changes(repo_path: Path, run_logger: 'RunLogger') -> bool:
    """Attempt to stash uncommitted changes as a fallback."""
    with main_repo_git_lock():
        try:
            # Use -u (tracked only) to avoid staging untracked files like
            # .pokepoke/ runtime state which could cause merge conflicts
            subprocess.run(
                ["git", "add", "-u"], check=True, capture_output=True,
                encoding='utf-8', errors='replace', cwd=str(repo_path), timeout=30
            )
            import datetime
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            stash_msg = f"pokepoke-auto-stash-{timestamp}: cleanup agent failed"
            result = subprocess.run(
                ["git", "stash", "push", "-m", stash_msg], capture_output=True,
                text=True, encoding='utf-8', errors='replace', cwd=str(repo_path), timeout=60
            )
            if result.returncode == 0:
                run_logger.log_orchestrator(f"Stashed changes: {stash_msg}")
                return True
            error_msg = result.stderr.strip() if result.stderr else "unknown error"
            logger.error(f"⚠️  git stash failed: {error_msg}")
            run_logger.log_orchestrator(f"git stash failed: {error_msg}", level="WARNING")
            return False
        except subprocess.TimeoutExpired:
            logger.warning("⚠️  git stash timed out")
            run_logger.log_orchestrator("git stash timed out", level="WARNING")
            return False
        except subprocess.CalledProcessError as e:
            error_msg = e.stderr.strip() if e.stderr else f"exit code {e.returncode}"
            logger.error(f"⚠️  git add failed: {error_msg}")
            run_logger.log_orchestrator(f"git add for stash failed: {error_msg}", level="WARNING")
            return False
        except Exception as e:
            logger.error(f"⚠️  Stash failed with unexpected error: {e}")
            run_logger.log_orchestrator(f"Stash failed: {e}", level="WARNING")
            return False


def _run_cleanup_retries(
    repo_path: Path,
    run_logger: 'RunLogger',
) -> bool:
    """Run cleanup agent retries with aggregate timeout.

    Returns True if cleanup succeeded, False if all retries exhausted or timed out.
    """
    from pokepoke.agents.cleanup_agents import invoke_cleanup_agent
    from pokepoke.types import BeadsWorkItem

    cleanup_loop_start = time.monotonic()
    for attempt in range(1, MAX_CLEANUP_RETRIES + 1):
        # Enforce aggregate timeout across all cleanup retries
        elapsed = time.monotonic() - cleanup_loop_start
        if elapsed >= CLEANUP_AGGREGATE_TIMEOUT:
            logger.info(f"\n⏰ Cleanup aggregate timeout reached ({elapsed:.0f}s) - stopping retries")
            run_logger.log_orchestrator(
                f"Cleanup aggregate timeout ({CLEANUP_AGGREGATE_TIMEOUT:.0f}s) exceeded",
                level="WARNING",
            )
            return False

        cleanup_item = BeadsWorkItem(
            id=f"cleanup-main-repo-{attempt}",
            title="Clean up uncommitted changes in main repository",
            description="Auto-generated cleanup task for uncommitted changes",
            issue_type="task",
            priority=0,
            status=STATUS_IN_PROGRESS,
            labels=["cleanup", "auto-generated"]
        )

        with cleanup_lock():
            cleanup_success, _cleanup_stats = invoke_cleanup_agent(
                cleanup_item, wait_for_merge=False
            )

        if cleanup_success:
            logger.info("✅ Cleanup agent successfully resolved uncommitted changes")
            run_logger.log_orchestrator("Cleanup agent successfully resolved uncommitted changes")
            return True

        if attempt < MAX_CLEANUP_RETRIES:
            wait_time = 2 ** attempt  # Exponential backoff: 2, 4, 8 seconds
            logger.error(f"⚠️  Cleanup attempt {attempt}/{MAX_CLEANUP_RETRIES} failed, retrying in {wait_time}s...")
            run_logger.log_orchestrator(f"Cleanup attempt {attempt} failed, retrying", level="WARNING")
            time.sleep(wait_time)

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
            logger.warning("\n⚠️  Main repository has uncommitted changes:")
            run_logger.log_orchestrator("Main repository has uncommitted changes", level="WARNING")
            for line in changes['other'][:10]:
                logger.info(f"   {line}")
            if len(changes['other']) > 10:
                logger.info(f"   ... and {len(changes['other']) - 10} more")

            # Try auto-commit first before launching the heavyweight cleanup agent
            logger.info("\n🔄 Attempting to auto-commit changes...")
            if _try_auto_commit(repo_path, run_logger):
                logger.info("✅ Auto-committed uncommitted changes")
                return True

            # Auto-commit failed - fall back to cleanup agent
            logger.error("\n🤖 Auto-commit failed, launching cleanup agent...")
            run_logger.log_orchestrator("Auto-commit failed, launching cleanup agent")

            # Check if merge operation is active - defer cleanup if so
            if merge_lock_active():
                logger.info("   ⏳ Merge operation in progress - deferring maintenance cleanup")
                logger.info("   Workers use isolated worktrees, continuing with orchestration for now")
                run_logger.log_orchestrator("Deferring cleanup due to active merge operation")
                return True  # Continue processing - merge has priority

            if _run_cleanup_retries(repo_path, run_logger):
                return True

            # All cleanup retries failed - try stashing as last resort
            logger.error(f"\n⚠️  All {MAX_CLEANUP_RETRIES} cleanup attempts failed")
            logger.info("🔄 Attempting to stash uncommitted changes as fallback...")
            run_logger.log_orchestrator("Cleanup retries exhausted, attempting git stash", level="WARNING")

            stash_success = _stash_uncommitted_changes(repo_path, run_logger)
            if stash_success:
                logger.info("✅ Changes stashed successfully - continuing with orchestration")
                run_logger.log_orchestrator("Uncommitted changes stashed successfully")
                return True

            # Stash failed - but workers use isolated worktrees, so continue anyway
            logger.warning("\n⚠️  Could not resolve uncommitted changes in main repo")
            logger.info("   Workers use isolated worktrees - continuing anyway")
            run_logger.log_orchestrator(
                "Cleanup and stash both failed, but continuing (workers use worktrees)",
                level="WARNING"
            )
            return True  # Continue processing - workers are isolated

        # Beads changes are handled by beads' own sync mechanism (bd sync)
        # Do NOT manually commit them - beads daemon handles this automatically
        if changes['beads']:
            logger.info("ℹ️  Beads database changes detected - will be synced by beads daemon")
            logger.info("ℹ️  Run 'bd sync' to force immediate sync if needed")

        # Auto-resolve worktree cleanup deletions
        if changes['worktree']:
            logger.info("🧹 Committing worktree cleanup changes...")
            with main_repo_git_lock():
                run_git(["git", "add", f"{WORKTREE_DIR}/"], cwd=str(repo_path))
                run_git(
                    ["git", "commit", "-m", "chore: cleanup deleted worktree directories"],
                    cwd=str(repo_path),
                    timeout=60,
                )
            logger.info("✅ Worktree cleanup committed")

    return True
