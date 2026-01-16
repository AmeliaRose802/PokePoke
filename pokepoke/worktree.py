"""Git worktree management for isolated task execution."""

import subprocess
import shutil
from pathlib import Path
from typing import Optional, Tuple


class WorktreeManager:
    """Manages git worktrees for isolated task execution."""
    
    def __init__(self, base_path: Optional[Path] = None):
        """Initialize worktree manager.
        
        Args:
            base_path: Base directory for worktrees (default: ./worktrees)
        """
        if base_path is None:
            # Get git root directory
            result = subprocess.run(
                ['git', 'rev-parse', '--show-toplevel'],
                capture_output=True,
                text=True,
                check=True
            )
            git_root = Path(result.stdout.strip())
            base_path = git_root / 'worktrees'
        
        self.base_path = base_path
        self.base_path.mkdir(exist_ok=True)
    
    def create_worktree(
        self,
        work_item_id: str,
        source_branch: str = "main"
    ) -> Tuple[bool, str, Optional[Path]]:
        """Create a new worktree for a work item.
        
        Args:
            work_item_id: The beads work item ID
            source_branch: Source branch to create worktree from
            
        Returns:
            Tuple of (success, message, worktree_path)
        """
        # Sanitize work item ID for branch name
        branch_name = f"task/{work_item_id}"
        worktree_path = self.base_path / f"task-{work_item_id}"
        
        # Check if worktree already exists
        if worktree_path.exists():
            return (
                False,
                f"Worktree already exists at {worktree_path}",
                None
            )
        
        try:
            # Create worktree with new branch
            subprocess.run(
                [
                    'git', 'worktree', 'add',
                    str(worktree_path),
                    '-b', branch_name,
                    source_branch
                ],
                capture_output=True,
                text=True,
                check=True
            )
            
            return (
                True,
                f"Created worktree at {worktree_path} from {source_branch}",
                worktree_path
            )
            
        except subprocess.CalledProcessError as e:
            return (
                False,
                f"Failed to create worktree: {e.stderr}",
                None
            )
    
    def cleanup_worktree(
        self,
        work_item_id: str,
        force: bool = False
    ) -> Tuple[bool, str]:
        """Clean up a worktree after task completion.
        
        Args:
            work_item_id: The beads work item ID
            force: Force removal even with uncommitted changes
            
        Returns:
            Tuple of (success, message)
        """
        worktree_path = self.base_path / f"task-{work_item_id}"
        branch_name = f"task/{work_item_id}"
        
        if not worktree_path.exists():
            return (
                False,
                f"Worktree does not exist at {worktree_path}"
            )
        
        try:
            # Remove worktree
            cmd = ['git', 'worktree', 'remove', str(worktree_path)]
            if force:
                cmd.append('--force')
            
            subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True
            )
            
            # Try to delete the branch (may fail if not merged, which is ok)
            try:
                subprocess.run(
                    ['git', 'branch', '-d', branch_name],
                    capture_output=True,
                    text=True,
                    check=False  # Don't raise on error
                )
            except Exception:
                pass  # Branch deletion is optional
            
            return (
                True,
                f"Removed worktree {worktree_path}"
            )
            
        except subprocess.CalledProcessError as e:
            return (
                False,
                f"Failed to remove worktree: {e.stderr}"
            )
    
    def list_worktrees(self) -> list[dict]:
        """List all git worktrees.
        
        Returns:
            List of worktree info dictionaries
        """
        try:
            result = subprocess.run(
                ['git', 'worktree', 'list', '--porcelain'],
                capture_output=True,
                text=True,
                check=True
            )
            
            worktrees = []
            current_worktree = {}
            
            for line in result.stdout.split('\n'):
                line = line.strip()
                if not line:
                    if current_worktree:
                        worktrees.append(current_worktree)
                        current_worktree = {}
                    continue
                
                if line.startswith('worktree '):
                    current_worktree['path'] = line[9:]
                elif line.startswith('HEAD '):
                    current_worktree['head'] = line[5:]
                elif line.startswith('branch '):
                    current_worktree['branch'] = line[7:]
                elif line == 'bare':
                    current_worktree['bare'] = True
            
            if current_worktree:
                worktrees.append(current_worktree)
            
            return worktrees
            
        except subprocess.CalledProcessError as e:
            return []
    
    def get_worktree_path(self, work_item_id: str) -> Optional[Path]:
        """Get the path to a worktree for a work item.
        
        Args:
            work_item_id: The beads work item ID
            
        Returns:
            Path to the worktree if it exists, None otherwise
        """
        worktree_path = self.base_path / f"task-{work_item_id}"
        return worktree_path if worktree_path.exists() else None
