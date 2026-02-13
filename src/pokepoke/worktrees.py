"""Git worktree management for PokePoke."""

import subprocess
from pathlib import Path
from typing import Optional

from pokepoke.git_operations import (
    sanitize_branch_name,
    get_default_branch,
    is_worktree_clean,
    branch_exists,
    execute_merge_sequence,
    validate_post_merge,
)
from pokepoke.beads_management import run_bd_sync_with_retry











def create_worktree(item_id: str, base_branch: Optional[str] = None) -> Path:
    """Create a git worktree for a work item. Returns existing path if already exists."""
    # Sanitize the item_id for use in branch names
    sanitized_id = sanitize_branch_name(item_id)
    
    # Worktree path: ./worktrees/task-{sanitized_id}
    worktree_path = Path("worktrees") / f"task-{sanitized_id}"
    
    # Branch name for the worktree
    branch_name = f"task/{sanitized_id}"
    
    # Check if worktree already exists
    existing_worktrees = list_worktrees()
    for wt in existing_worktrees:
        wt_path = Path(wt.get("path", ""))
        # Check if this is our worktree (by path or branch)
        if wt_path == worktree_path.resolve() or wt.get("branch", "").endswith(branch_name):
            print(f"   ♻️  Reusing existing worktree at {wt_path}")
            return wt_path
    
    # Create worktrees directory if it doesn't exist
    Path("worktrees").mkdir(exist_ok=True)
    
    # Resolve default base branch if not provided
    if base_branch is None:
        base_branch = get_default_branch()

    # Create the worktree
    try:
        subprocess.run(
            ["git", "worktree", "add", str(worktree_path), "-b", branch_name, base_branch],
            check=True,
            capture_output=True,
            text=True,
            encoding='utf-8'
        )
    except subprocess.CalledProcessError as e:
        # Log the actual error for debugging
        print(f"   ⚠️  Git error: {e.stderr if e.stderr else 'No stderr'}")
        
        # Check if error is because branch already exists
        if e.stderr and ("already exists" in e.stderr.lower() or "already checked out" in e.stderr.lower()):
            # Try to find the existing worktree
            existing_worktrees = list_worktrees()
            for wt in existing_worktrees:
                if wt.get("branch", "").endswith(branch_name):
                    print(f"   ♻️  Reusing existing worktree at {wt['path']}")
                    return Path(wt["path"])
        
        # Check if the base branch doesn't exist
        if e.stderr and ("invalid reference" in e.stderr.lower() or "not a valid" in e.stderr.lower()):
            raise RuntimeError(f"Base branch '{base_branch}' does not exist. Please create it first or specify a different base branch.")
        
        # If we couldn't recover, re-raise the error with more context
        raise RuntimeError(f"Failed to create worktree: {e.stderr if e.stderr else str(e)}") from e
    
    return worktree_path


def is_worktree_merged(item_id: str, target_branch: Optional[str] = None) -> bool:
    """Check if a worktree's branch has been merged into the target branch."""
    sanitized_id = sanitize_branch_name(item_id)
    branch_name = f"task/{sanitized_id}"
    if target_branch is None:
        target_branch = get_default_branch()
    try:
        result = subprocess.run(
            ["git", "branch", "--merged", target_branch],
            check=True, capture_output=True, text=True, encoding='utf-8'
        )
        return any(branch_name in branch for branch in result.stdout.splitlines())
    except subprocess.CalledProcessError:
        return False


def merge_worktree(item_id: str, target_branch: Optional[str] = None, cleanup: bool = True) -> tuple[bool, list[str]]:
    """Merge a worktree's branch into the target branch and optionally clean up.
    
    Returns:
        Tuple of (success: bool, unmerged_files: list[str])
        - If successful: (True, [])
        - If failed due to conflicts: (False, list_of_conflicted_files)
        - If failed for other reasons: (False, [])
    """
    sanitized_id = sanitize_branch_name(item_id)
    branch_name = f"task/{sanitized_id}"
    worktree_path = Path("worktrees") / f"task-{sanitized_id}"


    if target_branch is None:
        target_branch = get_default_branch()
    
    # PRE-MERGE VALIDATION: Verify worktree is clean
    if not is_worktree_clean(worktree_path):
        print("❌ Pre-merge validation failed: Worktree has uncommitted changes")
        return False, []
    
    print("✅ Pre-merge validation passed: Worktree is clean")
    
    if not _sync_and_ensure_clean_main_repo(branch_name):
        return False, []
    
    # Execute merge sequence with proper error handling
    merge_success, merge_error, unmerged_files = execute_merge_sequence(branch_name, target_branch)
    
    if not merge_success:
        if unmerged_files:
            print(f"❌ Merge conflicts detected in {len(unmerged_files)} file(s):")
            for f in unmerged_files[:10]:
                print(f"   - {f}")
            if len(unmerged_files) > 10:
                print(f"   ... and {len(unmerged_files) - 10} more")
        else:
            print(f"❌ Merge failed: {merge_error}")
        return False, unmerged_files
    
    print(f"✅ Merged {branch_name} into {target_branch}")
    
    if not validate_post_merge(target_branch):
        return False, []
    
    print(f"✅ Post-merge validation passed: {target_branch} is clean")
    
    try:
        subprocess.run(["git", "push"], check=True, capture_output=True, text=True, encoding='utf-8')
        print(f"✅ Pushed {target_branch} to remote")
    except subprocess.CalledProcessError as e:
        print(f"❌ Push failed: {e.stderr if e.stderr else str(e)}")
        return False, []
    
    # MERGE CONFIRMATION: Verify branch is actually merged
    if not is_worktree_merged(item_id, target_branch):
        print(f"❌ Merge confirmation failed: {branch_name} not showing as merged")
        return False, []
    
    print(f"✅ Merge confirmed: {branch_name} is merged into {target_branch}")
    
    if cleanup:
        _cleanup_after_merge(worktree_path, branch_name)
    
    return True, []  # Merge completed


def cleanup_worktree(item_id: str, force: bool = False) -> bool:
    """Remove a worktree and its associated branch.
    
    Handles both sanitized and unsanitized worktree paths by searching
    for the actual worktree associated with this item_id.
    
    Returns True if cleanup succeeds or if the worktree/branch don't exist.
    """
    sanitized_id = sanitize_branch_name(item_id)
    branch_name = f"task/{sanitized_id}"
    expected_worktree_path = Path("worktrees") / f"task-{sanitized_id}"
    
    # Find the actual worktree for this item (might have unsanitized path if created before fix)
    actual_worktree_path = None
    existing_worktrees = list_worktrees()
    
    # Search by branch name first
    for wt in existing_worktrees:
        wt_branch = wt.get("branch", "")
        if wt_branch.endswith(branch_name):
            actual_worktree_path = Path(wt["path"])
            break
    
    # If not found by branch, check if expected path exists
    if actual_worktree_path is None and expected_worktree_path.exists():
        actual_worktree_path = expected_worktree_path
    
    # Also check for unsanitized path (for backwards compatibility)
    if actual_worktree_path is None:
        unsanitized_path = Path("worktrees") / f"task-{item_id}"
        if unsanitized_path.exists():
            actual_worktree_path = unsanitized_path
    
    # Remove worktree if found
    if actual_worktree_path and actual_worktree_path.exists():
        try:
            cmd = ["git", "worktree", "remove", str(actual_worktree_path)]
            if force:
                cmd.append("--force")
            
            subprocess.run(
                cmd,
                check=True,
                capture_output=True,
                text=True,
                encoding='utf-8'
            )
        except subprocess.CalledProcessError as e:
            # Check if error is because worktree doesn't exist
            if e.stderr and ("not a working tree" in e.stderr.lower() or "no such file" in e.stderr.lower()):
                # Already gone, that's fine
                pass
            else:
                print(f"⚠️  Worktree removal warning: {e.stderr if e.stderr else str(e)}")
                # Continue to try branch deletion
    
    # Delete branch (try both sanitized and unsanitized branch names)
    delete_flag = "-D" if force else "-d"
    
    # Try sanitized branch name first
    try:
        subprocess.run(
            ["git", "branch", delete_flag, branch_name],
            check=True,
            capture_output=True,
            text=True,
            encoding='utf-8'
        )
    except subprocess.CalledProcessError as e:
        # Try unsanitized branch name as fallback
        try:
            unsanitized_branch = f"task/{item_id}"
            subprocess.run(
                ["git", "branch", delete_flag, unsanitized_branch],
                check=True,
                capture_output=True,
                text=True,
                encoding='utf-8'
            )
        except subprocess.CalledProcessError as e2:
            # Check if branch doesn't exist
            if e2.stderr and ("not found" in e2.stderr.lower() or "does not exist" in e2.stderr.lower()):
                # Already gone, that's fine
                pass
            else:
                print(f"⚠️  Branch deletion warning: {e2.stderr if e2.stderr else str(e2)}")
                # If both worktree and branch operations failed, return False
                if actual_worktree_path is not None:
                    return False
    
    return True


def list_worktrees() -> list[dict[str, str]]:
    """List all active worktrees."""
    try:
        result = subprocess.run(
            ["git", "worktree", "list", "--porcelain"],
            check=True,
            capture_output=True,
            text=True,
            encoding='utf-8'
        )
        
        worktrees = []
        current: dict[str, str] = {}
        
        for line in result.stdout.splitlines():
            if line.startswith("worktree "):
                if current:
                    worktrees.append(current)
                current = {"path": line.split(" ", 1)[1]}
            elif line.startswith("branch "):
                current["branch"] = line.split(" ", 1)[1]
            elif line.startswith("HEAD "):
                current["commit"] = line.split(" ", 1)[1]
        
        if current:
            worktrees.append(current)
        
        return worktrees
        
    except subprocess.CalledProcessError:
        return []

def _sync_and_ensure_clean_main_repo(branch_name: str) -> bool:
    """Sync beads and ensure main repo is clean before merge."""
    # CRITICAL: Sync beads before merge to avoid uncommitted .beads files blocking checkout
    print("🔄 Syncing beads database before merge...")
    try:
        bd_sync_result = run_bd_sync_with_retry(timeout=30)
        if bd_sync_result.returncode != 0:
            print(f"⚠️  bd sync returned non-zero: {bd_sync_result.returncode}")
            print(f"   stdout: {bd_sync_result.stdout}")
            print(f"   stderr: {bd_sync_result.stderr}")
    except subprocess.TimeoutExpired:
        print("⚠️  bd sync timed out")

    # Verify main repo is clean before checkout
    try:
        main_status = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            encoding='utf-8',
            check=True
        ).stdout.strip()
        
        if main_status:
            # Categorize changes for proper handling
            lines = main_status.split('\n')
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
            
            # Block merge if there are problematic changes
            if other_changes:
                print("⚠️  Main repo has uncommitted changes:")
                for line in other_changes[:10]:
                    print(f"   {line}")
                if len(other_changes) > 10:
                    print(f"   ... and {len(other_changes) - 10} more")
                print("❌ Cannot merge: main repo has uncommitted non-beads changes")
                return False
            
            if beads_changes:
                print("🔧 Committing beads database changes...")
                subprocess.run(["git", "add", ".beads/"], check=True, encoding='utf-8', errors='replace')
                subprocess.run(["git", "commit", "-m", f"chore: sync beads before merge of {branch_name}"],
                             check=True, encoding='utf-8', errors='replace')
                print("✅ Beads changes committed")
            
            if worktree_changes:
                print("🧹 Committing worktree cleanup changes...")
                subprocess.run(["git", "add", "worktrees/"], check=True, encoding='utf-8', errors='replace')
                subprocess.run(["git", "commit", "-m", "chore: cleanup deleted worktree directories"],
                             check=True, encoding='utf-8', errors='replace')
                print("✅ Worktree cleanup committed")
                
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ Failed to check/clean main repo: {e}")
        return False

def _cleanup_after_merge(worktree_path: Path, branch_name: str) -> None:
    """Cleanup worktree and branch after successful merge."""
    if worktree_path.exists():
        try:
            subprocess.run(
                ["git", "worktree", "remove", str(worktree_path)],
                check=True, capture_output=True, text=True, encoding='utf-8'
            )
            print(f"✅ Removed worktree at {worktree_path}")
        except subprocess.CalledProcessError as e:
            print(f"⚠️  Could not remove worktree: {e.stderr or e}")
            print(f"   Merge successful - worktree cleanup can be done later")
    
    try:
        subprocess.run(
            ["git", "branch", "-d", branch_name],
            check=True, capture_output=True, text=True, encoding='utf-8'
        )
        print(f"✅ Deleted branch {branch_name}")
    except subprocess.CalledProcessError as e:
        print(f"⚠️  Could not delete branch: {e.stderr or e}")
