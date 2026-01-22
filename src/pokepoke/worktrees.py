"""Git worktree management for PokePoke."""

import subprocess
from pathlib import Path


def get_main_repo_root() -> Path:
    """Get the main repository root directory (not a worktree)."""
    try:
        # Get the common git directory (points to main repo's .git)
        result = subprocess.run(
            ["git", "rev-parse", "--git-common-dir"],
            capture_output=True,
            text=True,
            encoding='utf-8',
            check=True
        )
        git_common_dir = Path(result.stdout.strip())
        
        # The main repo root is the parent of the .git directory
        if git_common_dir.name == ".git":
            return git_common_dir.parent
        else:
            # If git-common-dir returns an absolute path
            return git_common_dir.parent
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Not in a git repository: {e}")


def is_worktree_clean(worktree_path: Path) -> bool:
    """Check if a worktree has no uncommitted changes."""
    try:
        result = subprocess.run(
            ["git", "-C", str(worktree_path), "status", "--porcelain"],
            capture_output=True,
            text=True,
            encoding='utf-8',
            check=True
        )
        # Empty output means clean status
        return not bool(result.stdout.strip())
    except subprocess.CalledProcessError:
        return False


def verify_branch_pushed(branch_name: str) -> bool:
    """Verify that a branch exists on the remote."""
    try:
        result = subprocess.run(
            ["git", "ls-remote", "--heads", "origin", branch_name],
            capture_output=True,
            text=True,
            encoding='utf-8',
            check=True
        )
        # Non-empty output means branch exists on remote
        return bool(result.stdout.strip())
    except subprocess.CalledProcessError:
        return False


def create_worktree(item_id: str, base_branch: str = "ameliapayne/dev") -> Path:
    """Create a git worktree for a work item. Returns existing path if already exists."""
    # Worktree path: ./worktrees/task-{id}
    worktree_path = Path("worktrees") / f"task-{item_id}"
    
    # Branch name for the worktree
    branch_name = f"task/{item_id}"
    
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
        # Check if error is because branch already exists
        if e.stderr and ("already exists" in e.stderr.lower() or "already checked out" in e.stderr.lower()):
            # Try to find the existing worktree
            existing_worktrees = list_worktrees()
            for wt in existing_worktrees:
                if wt.get("branch", "").endswith(branch_name):
                    print(f"   ♻️  Reusing existing worktree at {wt['path']}")
                    return Path(wt["path"])
        # If we couldn't recover, re-raise the error
        raise
    
    return worktree_path


def is_worktree_merged(item_id: str, target_branch: str = "ameliapayne/dev") -> bool:
    """Check if a worktree's branch has been merged into the target branch."""
    branch_name = f"task/{item_id}"
    
    try:
        # Get list of branches merged into target
        result = subprocess.run(
            ["git", "branch", "--merged", target_branch],
            check=True,
            capture_output=True,
            text=True,
            encoding='utf-8'
        )
        
        # Check if our branch is in the list
        merged_branches = result.stdout.splitlines()
        return any(branch_name in branch for branch in merged_branches)
        
    except subprocess.CalledProcessError:
        return False


def merge_worktree(item_id: str, target_branch: str = "ameliapayne/dev", cleanup: bool = True) -> bool:
    """Merge a worktree's branch into the target branch and optionally clean up."""
    branch_name = f"task/{item_id}"
    worktree_path = Path("worktrees") / f"task-{item_id}"
    
    # PRE-MERGE VALIDATION: Verify worktree is clean
    if not is_worktree_clean(worktree_path):
        print("❌ Pre-merge validation failed: Worktree has uncommitted changes")
        return False
    
    print("✅ Pre-merge validation passed: Worktree is clean")
    
    try:
        # CRITICAL: Sync beads before merge to avoid uncommitted .beads files blocking checkout
        print("🔄 Syncing beads database before merge...")
        bd_sync_result = subprocess.run(
            ["bd", "sync"],
            capture_output=True,
            text=True,
            encoding='utf-8',
            timeout=30
        )
        if bd_sync_result.returncode != 0:
            print(f"⚠️  bd sync returned non-zero: {bd_sync_result.returncode}")
            print(f"   stdout: {bd_sync_result.stdout}")
            print(f"   stderr: {bd_sync_result.stderr}")
            # Continue anyway - sync may have partially succeeded
        
        # Verify main repo is clean before checkout
        main_status = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            encoding='utf-8',
            check=True
        ).stdout.strip()
        
        if main_status:
            print("⚠️  Main repo has uncommitted changes:")
            print(main_status)
            # Commit beads changes if present
            if ".beads/" in main_status:
                print("🔧 Committing beads database changes...")
                subprocess.run(["git", "add", ".beads/"], check=True, encoding='utf-8')
                subprocess.run(
                    ["git", "commit", "-m", f"chore: sync beads before merge of {branch_name}"],
                    check=True,
                    encoding='utf-8'
                )
                print("✅ Beads changes committed")
            else:
                print("❌ Cannot merge: main repo has uncommitted non-beads changes")
                return False
        
        # Switch to target branch
        subprocess.run(
            ["git", "checkout", target_branch],
            check=True,
            capture_output=True,
            text=True,
            encoding='utf-8'
        )
        
        # Pull latest changes
        subprocess.run(
            ["git", "pull", "--rebase"],
            check=True,
            capture_output=True,
            text=True,
            encoding='utf-8'
        )
        
        # Merge the work branch
        merge_result = subprocess.run(
            ["git", "merge", "--no-ff", branch_name, "-m", f"Merge {branch_name}"],
            check=True,
            capture_output=True,
            text=True,
            encoding='utf-8'
        )
        print(f"✅ Merged {branch_name} into {target_branch}")
        
        # POST-MERGE VALIDATION: Verify we're still on target branch and clean
        current_branch = subprocess.run(
            ["git", "branch", "--show-current"],
            capture_output=True,
            text=True,
            encoding='utf-8',
            check=True
        ).stdout.strip()
        
        if current_branch != target_branch:
            print(f"❌ Post-merge validation failed: Not on {target_branch} (on {current_branch})")
            return False
        
        # Verify target branch is clean after merge
        status_result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            encoding='utf-8',
            check=True
        )
        
        if status_result.stdout.strip():
            print(f"❌ Post-merge validation failed: {target_branch} has uncommitted changes")
            return False
        
        print(f"✅ Post-merge validation passed: {target_branch} is clean")
        
        # Push the merge
        push_result = subprocess.run(
            ["git", "push"],
            check=True,
            capture_output=True,
            text=True,
            encoding='utf-8'
        )
        print(f"✅ Pushed {target_branch} to remote")
        
        # MERGE CONFIRMATION: Verify branch is actually merged
        if not is_worktree_merged(item_id, target_branch):
            print(f"❌ Merge confirmation failed: {branch_name} not showing as merged")
            return False
        
        print(f"✅ Merge confirmed: {branch_name} is merged into {target_branch}")
        
        if cleanup:
            # Remove the worktree
            if worktree_path.exists():
                subprocess.run(
                    ["git", "worktree", "remove", str(worktree_path)],
                    check=True,
                    capture_output=True,
                    text=True,
                    encoding='utf-8'
                )
                print(f"✅ Removed worktree at {worktree_path}")
            
            # Delete the branch
            subprocess.run(
                ["git", "branch", "-d", branch_name],
                check=True,
                capture_output=True,
                text=True,
                encoding='utf-8'
            )
            print(f"✅ Deleted branch {branch_name}")
        
        return True
        
    except subprocess.CalledProcessError as e:
        error_msg = e.stderr if e.stderr else str(e)
        print(f"❌ Merge failed: {error_msg}")
        return False


def cleanup_worktree(item_id: str, force: bool = False) -> bool:
    """Remove a worktree and its associated branch."""
    branch_name = f"task/{item_id}"
    worktree_path = Path("worktrees") / f"task-{item_id}"
    
    try:
        # Remove worktree
        if worktree_path.exists():
            cmd = ["git", "worktree", "remove", str(worktree_path)]
            if force:
                cmd.append("--force")
            
            subprocess.run(
                cmd,
                check=True,
                capture_output=True,
                text=True,
                encoding='utf-8'
            )
        
        # Delete branch
        delete_flag = "-D" if force else "-d"
        subprocess.run(
            ["git", "branch", delete_flag, branch_name],
            check=True,
            capture_output=True,
            text=True,
            encoding='utf-8'
        )
        
        return True
        
    except subprocess.CalledProcessError as e:
        print(f"❌ Cleanup failed: {e.stderr if e.stderr else str(e)}")
        return False


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
