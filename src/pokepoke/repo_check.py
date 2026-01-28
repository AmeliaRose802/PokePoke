"""Repository status check and maintenance utilities."""

import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pokepoke.logging_utils import RunLogger


def check_and_commit_main_repo(repo_path: Path, run_logger: 'RunLogger') -> bool:
    """Check main repository status and commit beads changes if needed.
    
    Args:
        repo_path: Path to the main repository
        run_logger: Run logger instance
    
    Returns:
        True if ready to continue, False if should exit
    """
    status_result = subprocess.run(
        ["git", "status", "--porcelain"],
        capture_output=True,
        text=True,
        encoding='utf-8',
        check=True,
        cwd=str(repo_path)
    )
    
    uncommitted = status_result.stdout.strip()
    if uncommitted:
        lines = uncommitted.split('\n')
        # Categorize changes for proper handling
        beads_changes = [line for line in lines if line and '.beads/' in line]
        worktree_changes = [line for line in lines if line and 'worktrees/' in line and not line.startswith('??')]
        untracked_files = [line for line in lines if line and line.startswith('??')]
        other_changes = [
            line for line in lines
            if line
            and '.beads/' not in line
            and 'worktrees/' not in line
            and not line.startswith('??')
        ]
        
        # Handle problematic changes that need agent intervention
        if other_changes:
            print("\n⚠️  Main repository has uncommitted changes:")
            run_logger.log_orchestrator("Main repository has uncommitted changes", level="WARNING")
            for line in other_changes[:10]:
                print(f"   {line}")
            if len(other_changes) > 10:
                print(f"   ... and {len(other_changes) - 10} more")
            
            # Immediately run cleanup agent instead of delegating
            print("\n🤖 Launching cleanup agent to resolve uncommitted changes...")
            run_logger.log_orchestrator("Launching cleanup agent for uncommitted changes")
            
            from pokepoke.agent_runner import invoke_cleanup_agent
            from pokepoke.types import BeadsWorkItem
            
            # Create a temporary work item for the cleanup agent
            cleanup_item = BeadsWorkItem(
                id="cleanup-main-repo",
                title="Clean up uncommitted changes in main repository",
                description="Auto-generated cleanup task for uncommitted changes",
                issue_type="task",
                priority=0,
                status="in_progress",
                labels=["cleanup", "auto-generated"]
            )
            
            cleanup_success, cleanup_stats = invoke_cleanup_agent(cleanup_item, repo_path)
            
            if cleanup_success:
                print("✅ Cleanup agent successfully resolved uncommitted changes")
                run_logger.log_orchestrator("Cleanup agent successfully resolved uncommitted changes")
                return True  # Continue processing
            else:
                print("❌ Cleanup agent failed to resolve uncommitted changes")
                print("   Please manually resolve and try again")
                run_logger.log_orchestrator("Cleanup agent failed to resolve uncommitted changes", level="ERROR")
                return False
        
        # Beads changes are handled by beads' own sync mechanism (bd sync)
        # Do NOT manually commit them - beads daemon handles this automatically
        if beads_changes:
            print("ℹ️  Beads database changes detected - will be synced by beads daemon")
            print("ℹ️  Run 'bd sync' to force immediate sync if needed")
        
        # Auto-resolve worktree cleanup deletions
        if worktree_changes:
            print("🧹 Committing worktree cleanup changes...")
            subprocess.run(["git", "add", "worktrees/"], check=True, encoding='utf-8', errors='replace', cwd=str(repo_path))
            subprocess.run(
                ["git", "commit", "-m", "chore: cleanup deleted worktree directories"],
                check=True,
                capture_output=True,
                encoding='utf-8',
                errors='replace',
                cwd=str(repo_path)
            )
            print("✅ Worktree cleanup committed")
    
    return True
