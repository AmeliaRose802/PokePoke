"""Auto-commit runtime state files to a dedicated git branch.

Similar to beads' sync-branch pattern, this module auto-commits PokePoke runtime
state files (model_registry.json, maintenance_state.json, failed_unassigns.json)
to a dedicated branch to preserve git-backed versioning without interfering with
code merges.

All commits use git plumbing (update-index, write-tree, commit-tree) to avoid
working directory interference. Writes are serialized through main_repo_git_lock
to prevent index.lock conflicts.
"""

import contextlib
import logging
import os
import subprocess
from pathlib import Path

from pokepoke.config import StateBranchConfig
from pokepoke.constants import STATE_BRANCH_NAME
from pokepoke.utils.constants import STATE_BRANCH_FILES
from pokepoke.worktrees.coordination import main_repo_git_lock

logger = logging.getLogger(__name__)


def _git_plumbing(args: list[str], cwd: Path | None = None, timeout: int = 30) -> str:
    """Run a git plumbing command and return stdout.

    Args:
        args: Git command and arguments (e.g., ['git', 'rev-parse', 'HEAD'])
        cwd: Working directory (defaults to current directory)
        timeout: Command timeout in seconds

    Returns:
        stdout stripped of whitespace

    Raises:
        subprocess.CalledProcessError: If git command fails
        subprocess.TimeoutExpired: If command times out
    """
    result = subprocess.run(
        args,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=True,
    )
    return result.stdout.strip()


def _branch_exists(branch_name: str, cwd: Path | None = None) -> bool:
    """Check if a branch exists."""
    try:
        _git_plumbing(["git", "rev-parse", "--verify", branch_name], cwd=cwd)
        return True
    except subprocess.CalledProcessError:
        return False


def _create_state_branch_if_needed(
    branch_name: str = STATE_BRANCH_NAME,
    cwd: Path | None = None,
) -> None:
    """Create the state branch if it doesn't exist.

    Creates an orphan branch with an initial empty commit. Uses plumbing commands
    to avoid disturbing the working directory or current branch.

    Args:
        branch_name: Name of the state branch
        cwd: Repository root directory
    """
    if _branch_exists(branch_name, cwd=cwd):
        logger.debug(f"State branch '{branch_name}' already exists")
        return

    logger.info(f"Creating state branch '{branch_name}'...")

    try:
        # Create an empty tree using mktree with no input
        empty_tree = subprocess.run(
            ["git", "mktree"],
            cwd=cwd,
            capture_output=True,
            text=True,
            input="",  # Empty input creates empty tree
            timeout=30,
            check=True,
        ).stdout.strip()

        # Create initial commit with empty tree
        commit_msg = "Initialize pokepoke-state branch"
        new_commit = subprocess.run(
            ["git", "commit-tree", empty_tree, "-m", commit_msg],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        ).stdout.strip()

        # Create branch ref pointing to new commit
        subprocess.run(
            ["git", "update-ref", f"refs/heads/{branch_name}", new_commit],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )

        logger.info(f"State branch '{branch_name}' created successfully")

    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        logger.error(f"Failed to create state branch '{branch_name}': {e}")


def _has_state_changes(
    state_files: tuple[str, ...] = STATE_BRANCH_FILES,
    branch_name: str = STATE_BRANCH_NAME,
    cwd: Path | None = None,
) -> bool:
    """Check if any state files have changed since the last state branch commit.

    Args:
        state_files: Tuple of state file paths relative to repo root
        branch_name: Name of the state branch
        cwd: Repository root directory

    Returns:
        True if any state files have changed or are new
    """
    if not _branch_exists(branch_name, cwd=cwd):
        # Branch doesn't exist yet; any existing files are new
        repo_root = Path(cwd) if cwd else Path.cwd()
        return any((repo_root / f).exists() for f in state_files)

    # Check if files differ from the state branch
    try:
        for state_file in state_files:
            # Normalize path for git (forward slashes)
            git_path = state_file.replace("\\", "/")

            # Check if file exists in state branch
            try:
                _git_plumbing(
                    ["git", "cat-file", "-e", f"{branch_name}:{git_path}"],
                    cwd=cwd,
                )
                # File exists in branch; check for differences
                branch_content = _git_plumbing(
                    ["git", "show", f"{branch_name}:{git_path}"],
                    cwd=cwd,
                )
            except subprocess.CalledProcessError:
                # File doesn't exist in branch
                branch_content = ""

            # Get current file content
            repo_root = Path(cwd) if cwd else Path.cwd()
            file_path = repo_root / state_file
            if file_path.exists():
                current_content = file_path.read_text(encoding="utf-8")
            else:
                current_content = ""

            # Compare
            if branch_content != current_content:
                logger.debug(f"State file changed: {state_file}")
                return True

        return False

    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as e:
        logger.warning(f"Error checking state changes, assuming changed: {e}")
        return True  # Assume changes on error to ensure state is captured


def commit_state_branch(
    config: StateBranchConfig | None = None,
    cwd: Path | None = None,
    force: bool = False,
) -> bool:
    """Commit runtime state files to the dedicated state branch.

    This function uses git plumbing commands to commit state files without
    disturbing the working directory or current branch. It acquires the
    main_repo_git_lock to prevent concurrent git operations.

    Args:
        config: State branch configuration (uses defaults if None)
        cwd: Repository root directory (defaults to current directory)
        force: Force commit even if no changes detected

    Returns:
        True if state was committed, False if skipped (disabled, no changes, or error)
    """
    # Use default config if none provided
    if config is None:
        config = StateBranchConfig()

    if not config.enabled:
        logger.debug("State branch commits disabled in config")
        return False

    # Serialize all git operations through the main repo lock
    with main_repo_git_lock():
        try:
            # Ensure state branch exists
            _create_state_branch_if_needed(config.branch_name, cwd=cwd)

            # Check for changes (skip if nothing changed)
            if not force and not _has_state_changes(STATE_BRANCH_FILES, config.branch_name, cwd=cwd):
                logger.debug("No state changes to commit")
                return False

            # Get current HEAD of state branch
            try:
                parent_commit = _git_plumbing(
                    ["git", "rev-parse", config.branch_name],
                    cwd=cwd,
                )
            except subprocess.CalledProcessError:
                # Branch doesn't exist yet (shouldn't happen after create, but handle it)
                parent_commit = None

            # Create a temporary index for state files only
            repo_root = Path(cwd) if cwd else Path.cwd()
            temp_index = repo_root / ".git" / "state-branch-index.tmp"

            # Set GIT_INDEX_FILE to use temporary index
            env = {"GIT_INDEX_FILE": str(temp_index)}

            # Read state branch tree into temp index
            if parent_commit:
                subprocess.run(
                    ["git", "read-tree", config.branch_name],
                    cwd=cwd,
                    env={**os.environ, **env},
                    capture_output=True,
                    text=True,
                    timeout=30,
                    check=True,
                )

            # Update temp index with current state files
            existing_files = []
            for state_file in STATE_BRANCH_FILES:
                file_path = repo_root / state_file
                if file_path.exists():
                    subprocess.run(
                        ["git", "update-index", "--add", "--", state_file],
                        cwd=cwd,
                        env={**os.environ, **env},
                        capture_output=True,
                        text=True,
                        timeout=30,
                        check=True,
                    )
                    existing_files.append(state_file)

            # Write tree from temp index
            state_tree = subprocess.run(
                ["git", "write-tree"],
                cwd=cwd,
                env={**os.environ, **env},
                capture_output=True,
                text=True,
                timeout=30,
                check=True,
            ).stdout.strip()

            # Clean up temp index
            with contextlib.suppress(OSError):
                temp_index.unlink()

            # Create commit object
            commit_msg = f"Auto-commit PokePoke runtime state\n\nUpdated: {', '.join(existing_files)}"

            commit_cmd = ["git", "commit-tree", state_tree, "-m", commit_msg]
            if parent_commit:
                commit_cmd.extend(["-p", parent_commit])

            new_commit = subprocess.run(
                commit_cmd,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=30,
                check=True,
            ).stdout.strip()

            # Update state branch ref to point to new commit
            subprocess.run(
                ["git", "update-ref", f"refs/heads/{config.branch_name}", new_commit],
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=30,
                check=True,
            )

            logger.info(
                f"Committed state to branch '{config.branch_name}': {new_commit[:8]} "
                f"({len(existing_files)} files)"
            )
            return True

        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as e:
            logger.error(f"Failed to commit state branch: {e}", exc_info=True)
            return False

