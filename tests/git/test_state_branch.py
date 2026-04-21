"""Tests for state branch auto-commit functionality."""
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

from pokepoke.config import StateBranchConfig
from pokepoke.git.state_branch import (
    _branch_exists,
    _create_state_branch_if_needed,
    _has_state_changes,
    commit_state_branch,
)


class TestBranchHelpers:
    """Test git branch helper functions."""

    @patch('pokepoke.git.state_branch._git_plumbing')
    def test_branch_exists_true(self, mock_plumbing: Mock) -> None:
        """Returns True when branch exists."""
        mock_plumbing.return_value = "abc123"
        assert _branch_exists("pokepoke-state") is True

    @patch('pokepoke.git.state_branch._git_plumbing')
    def test_branch_exists_false(self, mock_plumbing: Mock) -> None:
        """Returns False when branch doesn't exist."""
        mock_plumbing.side_effect = subprocess.CalledProcessError(1, "git")
        assert _branch_exists("pokepoke-state") is False


class TestStateBranchCreation:
    """Test state branch creation logic."""

    @patch('pokepoke.git.state_branch.subprocess.run')
    @patch('pokepoke.git.state_branch._branch_exists')
    def test_create_state_branch_success(self, mock_exists: Mock, mock_run: Mock) -> None:
        """Creates orphan state branch with empty initial commit."""
        mock_exists.return_value = False
        mock_run.return_value = Mock(stdout="abc123\n", returncode=0)

        _create_state_branch_if_needed()

        # Should create empty tree, commit, and update ref
        assert mock_run.call_count == 3

    @patch('pokepoke.git.state_branch._branch_exists')
    def test_create_state_branch_idempotent(self, mock_exists: Mock) -> None:
        """Does nothing if branch already exists."""
        mock_exists.return_value = True

        _create_state_branch_if_needed()

        # Should only check if branch exists
        mock_exists.assert_called_once()


class TestStateChangesDetection:
    """Test state change detection logic."""

    @patch('pokepoke.git.state_branch._branch_exists')
    def test_has_state_changes_no_branch(self, mock_exists: Mock, tmp_path: Path) -> None:
        """Detects new state files when branch doesn't exist."""
        mock_exists.return_value = False

        # Create a state file
        pokepoke_dir = tmp_path / ".pokepoke"
        pokepoke_dir.mkdir()
        (pokepoke_dir / "maintenance_state.json").write_text('{"test": "data"}')

        result = _has_state_changes(
            state_files=(".pokepoke/maintenance_state.json",),
            branch_name="pokepoke-state",
            cwd=tmp_path,
        )

        assert result is True

    @patch('pokepoke.git.state_branch._git_plumbing')
    @patch('pokepoke.git.state_branch._branch_exists')
    def test_has_state_changes_no_changes(
        self, mock_exists: Mock, mock_plumbing: Mock, tmp_path: Path
    ) -> None:
        """Returns False when state files unchanged."""
        mock_exists.return_value = True
        mock_plumbing.side_effect = [
            None,  # cat-file -e (file exists)
            '{"test": "data"}',  # show file content
        ]

        # Create matching state file
        pokepoke_dir = tmp_path / ".pokepoke"
        pokepoke_dir.mkdir()
        (pokepoke_dir / "maintenance_state.json").write_text('{"test": "data"}')

        result = _has_state_changes(
            state_files=(".pokepoke/maintenance_state.json",),
            branch_name="pokepoke-state",
            cwd=tmp_path,
        )

        assert result is False

    @patch('pokepoke.git.state_branch._git_plumbing')
    @patch('pokepoke.git.state_branch._branch_exists')
    def test_has_state_changes_modified_file(
        self, mock_exists: Mock, mock_plumbing: Mock, tmp_path: Path
    ) -> None:
        """Detects modified state files."""
        mock_exists.return_value = True
        mock_plumbing.side_effect = [
            None,  # cat-file -e (file exists)
            '{"test": "old_data"}',  # show file content (old version)
        ]

        # Create modified state file
        pokepoke_dir = tmp_path / ".pokepoke"
        pokepoke_dir.mkdir()
        (pokepoke_dir / "maintenance_state.json").write_text('{"test": "new_data"}')

        result = _has_state_changes(
            state_files=(".pokepoke/maintenance_state.json",),
            branch_name="pokepoke-state",
            cwd=tmp_path,
        )

        assert result is True


class TestCommitStateBranch:
    """Test main commit_state_branch function."""

    def test_commit_state_branch_disabled(self) -> None:
        """Returns False when disabled in config."""
        config = StateBranchConfig(enabled=False)
        result = commit_state_branch(config=config)
        assert result is False

    @patch('pokepoke.git.state_branch.subprocess.run')
    @patch('pokepoke.git.state_branch._has_state_changes')
    @patch('pokepoke.git.state_branch._create_state_branch_if_needed')
    @patch('pokepoke.git.state_branch.main_repo_git_lock')
    def test_commit_state_branch_success(
        self,
        mock_lock: Mock,
        mock_create: Mock,
        mock_has_changes: Mock,
        mock_run: Mock,
        tmp_path: Path,
    ) -> None:
        """Successfully commits state files to branch."""
        mock_lock.return_value.__enter__ = Mock()
        mock_lock.return_value.__exit__ = Mock()
        mock_has_changes.return_value = True
        mock_run.return_value = Mock(stdout="abc123\n", returncode=0)

        # Create .git directory
        git_dir = tmp_path / ".git"
        git_dir.mkdir()

        # Create state files
        pokepoke_dir = tmp_path / ".pokepoke"
        pokepoke_dir.mkdir()
        (pokepoke_dir / "maintenance_state.json").write_text('{"test": "data"}')

        config = StateBranchConfig(enabled=True)
        result = commit_state_branch(config=config, cwd=tmp_path)

        assert result is True
        mock_create.assert_called_once()

    @patch('pokepoke.git.state_branch._has_state_changes')
    @patch('pokepoke.git.state_branch._create_state_branch_if_needed')
    @patch('pokepoke.git.state_branch.main_repo_git_lock')
    def test_commit_state_branch_skip_unchanged(
        self, mock_lock: Mock, mock_create: Mock, mock_has_changes: Mock
    ) -> None:
        """Skips commit when no changes detected."""
        mock_lock.return_value.__enter__ = Mock()
        mock_lock.return_value.__exit__ = Mock()
        mock_has_changes.return_value = False

        config = StateBranchConfig(enabled=True)
        result = commit_state_branch(config=config, force=False)

        assert result is False

    @patch('pokepoke.git.state_branch.subprocess.run')
    @patch('pokepoke.git.state_branch._has_state_changes')
    @patch('pokepoke.git.state_branch._create_state_branch_if_needed')
    @patch('pokepoke.git.state_branch.main_repo_git_lock')
    def test_commit_state_branch_force(
        self,
        mock_lock: Mock,
        mock_create: Mock,
        mock_has_changes: Mock,
        mock_run: Mock,
        tmp_path: Path,
    ) -> None:
        """Force flag bypasses change detection."""
        mock_lock.return_value.__enter__ = Mock()
        mock_lock.return_value.__exit__ = Mock()
        mock_has_changes.return_value = False  # No changes
        mock_run.return_value = Mock(stdout="abc123\n", returncode=0)

        # Create .git directory
        git_dir = tmp_path / ".git"
        git_dir.mkdir()

        # Create state files
        pokepoke_dir = tmp_path / ".pokepoke"
        pokepoke_dir.mkdir()
        (pokepoke_dir / "maintenance_state.json").write_text('{"test": "data"}')

        config = StateBranchConfig(enabled=True)
        result = commit_state_branch(config=config, cwd=tmp_path, force=True)

        # Should commit even though has_state_changes returned False
        assert result is True

    @patch('pokepoke.git.state_branch._create_state_branch_if_needed')
    @patch('pokepoke.git.state_branch.main_repo_git_lock')
    def test_commit_state_branch_uses_lock(self, mock_lock: Mock, mock_create: Mock) -> None:
        """Acquires main repo git lock during commit."""
        mock_context = MagicMock()
        mock_lock.return_value = mock_context

        config = StateBranchConfig(enabled=True)
        commit_state_branch(config=config)

        # Should acquire lock
        mock_lock.assert_called_once()
        mock_context.__enter__.assert_called_once()

    @patch('pokepoke.git.state_branch._create_state_branch_if_needed')
    @patch('pokepoke.git.state_branch.main_repo_git_lock')
    def test_commit_state_branch_error_handling(self, mock_lock: Mock, mock_create: Mock) -> None:
        """Returns False on errors."""
        mock_lock.return_value.__enter__ = Mock()
        mock_lock.return_value.__exit__ = Mock()
        mock_create.side_effect = subprocess.CalledProcessError(1, "git")

        config = StateBranchConfig(enabled=True)
        result = commit_state_branch(config=config)

        assert result is False
