"""Repository status check and maintenance utilities."""

import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING

from pokepoke.git_operations import categorize_git_changes
from pokepoke.repo_state_guard import cleanup_lock

if TYPE_CHECKING:
    from pokepoke.logging_utils import RunLogger

# Maximum number of cleanup agent retries before falling back to stash
MAX_CLEANUP_RETRIES = 3


def check_beads_available() -> bool:
    """Check that beads (bd) is installed and initialized in the current directory.

    Returns:
        True if beads is available and initialized, False otherwise.
    """
    if not shutil.which('bd'):
        print("\nError: 'bd' (beads) command not found.", file=sys.stderr)
        print("   PokePoke requires beads for work item tracking.", file=sys.stderr)
        print("   Install beads: pip install beads", file=sys.stderr)
        print("   Then initialize: bd init", file=sys.stderr)
        return False

    try:
        result = subprocess.run(
            ['bd', 'info', '--json'],
            capture_output=True, text=True, encoding='utf-8',
            timeout=10
        )
        if result.returncode != 0:
            print("\nError: This directory is not a beads repository.", file=sys.stderr)
            print("   Run 'bd init' to set up beads tracking.", file=sys.stderr)
            return False
    except subprocess.TimeoutExpired:
        print("\nError: 'bd info' timed out. Beads may not be configured correctly.", file=sys.stderr)
        return False
    except Exception as e:
        print(f"\nError: Failed to check beads status: {e}", file=sys.stderr)
        print("   Ensure beads is installed and initialized: bd init", file=sys.stderr)
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
    """Attempt to stash uncommitted changes as a fallback.
    
    Args:
        repo_path: Path to the repository
        run_logger: Run logger instance
    
    Returns:
        True if stash succeeded, False otherwise
    """
    try:
        # First, add all changes so untracked files can be stashed
        subprocess.run(
            ["git", "add", "--all"],
            check=True,
            capture_output=True,
            encoding='utf-8',
            errors='replace',
            cwd=str(repo_path),
            timeout=30
        )
        
        # Create a descriptive stash message
        import datetime
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        stash_msg = f"pokepoke-auto-stash-{timestamp}: cleanup agent failed"
        
        # Stash all staged changes
        result = subprocess.run(
            ["git", "stash", "push", "-m", stash_msg],
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            cwd=str(repo_path),
            timeout=60
        )
        
        if result.returncode == 0:
            run_logger.log_orchestrator(f"Stashed changes: {stash_msg}")
            return True
        
        # Stash failed
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


def check_and_commit_main_repo(repo_path: Path, run_logger: 'RunLogger') -> bool:
    """Check main repository status and commit beads changes if needed.
    
    Args:
        repo_path: Path to the main repository
        run_logger: Run logger instance
    
    Returns:
        True if ready to continue, False if should exit
    """
    try:
        status_result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            encoding='utf-8',
            check=True,
            cwd=str(repo_path),
            timeout=30
        )
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
    
    uncommitted = status_result.stdout.strip()
    if uncommitted:
        lines = uncommitted.split('\n')
        changes = categorize_git_changes(lines)
        
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
            
            from pokepoke.agent_runner import invoke_cleanup_agent
            from pokepoke.types import BeadsWorkItem
            
            cleanup_success = False
            for attempt in range(1, MAX_CLEANUP_RETRIES + 1):
                # Create a temporary work item for the cleanup agent
                cleanup_item = BeadsWorkItem(
                    id=f"cleanup-main-repo-{attempt}",
                    title="Clean up uncommitted changes in main repository",
                    description="Auto-generated cleanup task for uncommitted changes",
                    issue_type="task",
                    priority=0,
                    status="in_progress",
                    labels=["cleanup", "auto-generated"]
                )
                
                with cleanup_lock():
                    cleanup_success, cleanup_stats = invoke_cleanup_agent(cleanup_item, repo_path)
                
                if cleanup_success:
                    print("✅ Cleanup agent successfully resolved uncommitted changes")
                    run_logger.log_orchestrator("Cleanup agent successfully resolved uncommitted changes")
                    return True  # Continue processing
                
                if attempt < MAX_CLEANUP_RETRIES:
                    wait_time = 2 ** attempt  # Exponential backoff: 2, 4, 8 seconds
                    print(f"⚠️  Cleanup attempt {attempt}/{MAX_CLEANUP_RETRIES} failed, retrying in {wait_time}s...")
                    run_logger.log_orchestrator(f"Cleanup attempt {attempt} failed, retrying", level="WARNING")
                    time.sleep(wait_time)
            
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
            subprocess.run(["git", "add", "worktrees/"], check=True, encoding='utf-8', errors='replace', cwd=str(repo_path), timeout=30)
            subprocess.run(
                ["git", "commit", "-m", "chore: cleanup deleted worktree directories"],
                check=True,
                capture_output=True,
                encoding='utf-8',
                errors='replace',
                cwd=str(repo_path),
                timeout=60
            )
            print("✅ Worktree cleanup committed")
    
    return True
