"""Repository status check and maintenance utilities."""

import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING

from pokepoke.constants import BEADS_DIR, CLEANUP_AGGREGATE_TIMEOUT, STATUS_IN_PROGRESS, WORKTREE_DIR
from pokepoke.git_helpers import run_git
from pokepoke.git_operations import get_status_porcelain_and_changes
from pokepoke.repo_state_guard import cleanup_lock
from pokepoke.coordination import merge_lock_active

if TYPE_CHECKING:
    from pokepoke.logging_utils import RunLogger

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
        print("\nError: 'bd' (beads) command not found.", file=sys.stderr)
        print("   PokePoke requires beads for work item tracking.", file=sys.stderr)
        print("   Install beads: pip install beads", file=sys.stderr)
        print("   Then initialize: bd init", file=sys.stderr)
        return False

    beads_dir = Path.cwd() / BEADS_DIR
    if not beads_dir.is_dir():
        print("\nError: This directory is not a beads repository.", file=sys.stderr)
        print("   Run 'bd init' to set up beads tracking.", file=sys.stderr)
        return False

    # Verify it has at least a config file (not just an empty directory)
    has_marker = any(
        (beads_dir / name).exists()
        for name in ("config.yaml", "config.yml", "issues.jsonl", "beads.db")
    )
    if not has_marker:
        print("\nError: .beads/ directory exists but appears incomplete.", file=sys.stderr)
        print("   Run 'bd init' to reinitialize beads tracking.", file=sys.stderr)
        return False

    return True


def initialize_beads_repo(repo_path: Path) -> bool:
    """Initialize beads in the given repository directory."""
    if not shutil.which('bd'):
        print("\nError: 'bd' (beads) command not found.", file=sys.stderr)
        print("   Install beads: pip install beads", file=sys.stderr)
        return False

    # Already initialized?
    try:
        info_result = subprocess.run(
            ['bd', 'info', '--json'],
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            cwd=str(repo_path),
            timeout=BD_INFO_TIMEOUT,
        )
        if info_result.returncode == 0:
            return True
    except subprocess.TimeoutExpired:
        print("\nError: 'bd info' timed out. Beads may not be configured correctly.", file=sys.stderr)
        return False
    except Exception as e:
        print(f"\nError: Failed to check beads status: {e}", file=sys.stderr)
        return False

    # Initialize
    try:
        init_result = subprocess.run(
            ['bd', 'init', '--quiet'],
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            cwd=str(repo_path),
            timeout=BD_INIT_TIMEOUT,
        )
        if init_result.returncode != 0:
            print(f"\nError: Failed to initialize beads in: {repo_path}", file=sys.stderr)
            details = (init_result.stderr or init_result.stdout or "").strip()
            if details:
                print(details, file=sys.stderr)
            print("\nTry running manually:", file=sys.stderr)
            print("   bd init", file=sys.stderr)
            return False
    except subprocess.TimeoutExpired:
        print("\nError: 'bd init' timed out.", file=sys.stderr)
        return False
    except Exception as e:
        print(f"\nError: Failed to run 'bd init': {e}", file=sys.stderr)
        return False

    # Verify
    try:
        verify_result = subprocess.run(
            ['bd', 'info', '--json'],
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            cwd=str(repo_path),
            timeout=BD_INFO_TIMEOUT,
        )
        if verify_result.returncode != 0:
            print("\nError: Beads initialization did not complete successfully.", file=sys.stderr)
            print("   'bd info' still fails after initialization.", file=sys.stderr)
            return False
    except subprocess.TimeoutExpired:
        print("\nError: 'bd info' timed out after initialization.", file=sys.stderr)
        return False
    except Exception as e:
        print(f"\nError: Failed to verify beads initialization: {e}", file=sys.stderr)
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
    try:
        subprocess.run(
            ["git", "add", "--all"],
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
    try:
        subprocess.run(
            ["git", "add", "--all"], check=True, capture_output=True,
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
        print(f"⚠️  git stash failed: {error_msg}")
        run_logger.log_orchestrator(f"git stash failed: {error_msg}", level="WARNING")
        return False
    except subprocess.TimeoutExpired:
        print("⚠️  git stash timed out")
        run_logger.log_orchestrator("git stash timed out", level="WARNING")
        return False
    except subprocess.CalledProcessError as e:
        error_msg = e.stderr.strip() if e.stderr else f"exit code {e.returncode}"
        print(f"⚠️  git add failed: {error_msg}")
        run_logger.log_orchestrator(f"git add for stash failed: {error_msg}", level="WARNING")
        return False
    except Exception as e:
        print(f"⚠️  Stash failed with unexpected error: {e}")
        run_logger.log_orchestrator(f"Stash failed: {e}", level="WARNING")
        return False


def _run_cleanup_retries(
    repo_path: Path,
    run_logger: 'RunLogger',
) -> bool:
    """Run cleanup agent retries with aggregate timeout.

    Returns True if cleanup succeeded, False if all retries exhausted or timed out.
    """
    from pokepoke.cleanup_agents import invoke_cleanup_agent
    from pokepoke.types import BeadsWorkItem

    cleanup_loop_start = time.monotonic()
    for attempt in range(1, MAX_CLEANUP_RETRIES + 1):
        # Enforce aggregate timeout across all cleanup retries
        elapsed = time.monotonic() - cleanup_loop_start
        if elapsed >= CLEANUP_AGGREGATE_TIMEOUT:
            print(f"\n⏰ Cleanup aggregate timeout reached ({elapsed:.0f}s) - stopping retries")
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
            cleanup_success, cleanup_stats = invoke_cleanup_agent(
                cleanup_item, wait_for_merge=False
            )

        if cleanup_success:
            print("✅ Cleanup agent successfully resolved uncommitted changes")
            run_logger.log_orchestrator("Cleanup agent successfully resolved uncommitted changes")
            return True

        if attempt < MAX_CLEANUP_RETRIES:
            wait_time = 2 ** attempt  # Exponential backoff: 2, 4, 8 seconds
            print(f"⚠️  Cleanup attempt {attempt}/{MAX_CLEANUP_RETRIES} failed, retrying in {wait_time}s...")
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
        print(f"⚠️  Warning: git status failed in {repo_path}: {error_msg}")
        run_logger.log_orchestrator(f"git status failed: {error_msg}", level="WARNING")
        # Check if this is a valid git repository
        git_dir = repo_path / ".git"
        if not git_dir.exists():
            print(f"❌ Error: {repo_path} is not a git repository")
            run_logger.log_orchestrator(f"{repo_path} is not a git repository", level="ERROR")
            return False
        # For other git errors, try to continue
        print("   Continuing despite git error...")
        return True

    if uncommitted:

        # Handle problematic changes that need agent intervention
        if changes['other']:
            print("\n⚠️  Main repository has uncommitted changes:")
            run_logger.log_orchestrator("Main repository has uncommitted changes", level="WARNING")
            for line in changes['other'][:10]:
                print(f"   {line}")
            if len(changes['other']) > 10:
                print(f"   ... and {len(changes['other']) - 10} more")

            # Try auto-commit first before launching the heavyweight cleanup agent
            print("\n🔄 Attempting to auto-commit changes...")
            if _try_auto_commit(repo_path, run_logger):
                print("✅ Auto-committed uncommitted changes")
                return True

            # Auto-commit failed - fall back to cleanup agent
            print("\n🤖 Auto-commit failed, launching cleanup agent...")
            run_logger.log_orchestrator("Auto-commit failed, launching cleanup agent")

            # Check if merge operation is active - defer cleanup if so
            if merge_lock_active():
                print("   ⏳ Merge operation in progress - deferring maintenance cleanup")
                print("   Workers use isolated worktrees, continuing with orchestration for now")
                run_logger.log_orchestrator("Deferring cleanup due to active merge operation")
                return True  # Continue processing - merge has priority

            if _run_cleanup_retries(repo_path, run_logger):
                return True

            # All cleanup retries failed - try stashing as last resort
            print(f"\n⚠️  All {MAX_CLEANUP_RETRIES} cleanup attempts failed")
            print("🔄 Attempting to stash uncommitted changes as fallback...")
            run_logger.log_orchestrator("Cleanup retries exhausted, attempting git stash", level="WARNING")

            stash_success = _stash_uncommitted_changes(repo_path, run_logger)
            if stash_success:
                print("✅ Changes stashed successfully - continuing with orchestration")
                run_logger.log_orchestrator("Uncommitted changes stashed successfully")
                return True

            # Stash failed - but workers use isolated worktrees, so continue anyway
            print("\n⚠️  Could not resolve uncommitted changes in main repo")
            print("   Workers use isolated worktrees - continuing anyway")
            run_logger.log_orchestrator(
                "Cleanup and stash both failed, but continuing (workers use worktrees)",
                level="WARNING"
            )
            return True  # Continue processing - workers are isolated

        # Beads changes are handled by beads' own sync mechanism (bd sync)
        # Do NOT manually commit them - beads daemon handles this automatically
        if changes['beads']:
            print("ℹ️  Beads database changes detected - will be synced by beads daemon")
            print("ℹ️  Run 'bd sync' to force immediate sync if needed")

        # Auto-resolve worktree cleanup deletions
        if changes['worktree']:
            print("🧹 Committing worktree cleanup changes...")
            run_git(["git", "add", f"{WORKTREE_DIR}/"], cwd=str(repo_path))
            run_git(
                ["git", "commit", "-m", "chore: cleanup deleted worktree directories"],
                cwd=str(repo_path),
                timeout=60,
            )
            print("✅ Worktree cleanup committed")

    return True
