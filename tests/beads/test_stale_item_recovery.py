"""Tests for stale item recovery module."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from pokepoke.beads.stale_item_recovery import (
    build_resume_context,
    format_resume_context_for_prompt,
    get_modified_files_in_worktree,
    get_recent_commit_messages,
    get_stale_in_progress_items,
    get_worktree_commit_count,
    get_worktree_path_for_item,
    is_pokepoke_agent_name,
)
from pokepoke.types_beads import BeadsWorkItem


def _make_item(
    item_id: str = "test-item",
    assignee: str | None = None,
    status: str = "in_progress",
    priority: int = 1,
) -> BeadsWorkItem:
    """Create a test BeadsWorkItem with minimal required fields."""
    return BeadsWorkItem(
        id=item_id,
        title=f"Test Item {item_id}",
        status=status,
        priority=priority,
        issue_type="task",
        assignee=assignee,
    )


def _completed(returncode: int = 0, stdout: str = "", stderr: str = "") -> MagicMock:
    """Create a mock subprocess.CompletedProcess."""
    result = MagicMock()
    result.returncode = returncode
    result.stdout = stdout
    result.stderr = stderr
    return result


class TestIsPokePokAgentName:
    """Tests for is_pokepoke_agent_name function."""

    def test_valid_pokepoke_names(self) -> None:
        """Should recognize valid PokePoke agent names."""
        assert is_pokepoke_agent_name("pokepoke_swift_pika_a7f3")
        assert is_pokepoke_agent_name("pokepoke_clever_bulba_1234")
        assert is_pokepoke_agent_name("pokepoke_mighty_char_abcd")
        assert is_pokepoke_agent_name("pokepoke_swift_pika_a7f3-cobra-worker-1")
        assert is_pokepoke_agent_name("pokepoke_swift_pika_a7f3-rainbow_boa-worker-12")
        assert is_pokepoke_agent_name("POKEPOKE_SWIFT_PIKA_A7F3")  # Case insensitive

    def test_invalid_names(self) -> None:
        """Should reject non-PokePoke names."""
        assert not is_pokepoke_agent_name(None)
        assert not is_pokepoke_agent_name("")
        assert not is_pokepoke_agent_name("human_developer")
        assert not is_pokepoke_agent_name("pokepoke")  # Missing parts
        assert not is_pokepoke_agent_name("pokepoke_swift")  # Missing parts
        assert not is_pokepoke_agent_name("pokepoke_swift_pika")  # Missing hex
        assert not is_pokepoke_agent_name("pokepoke_swift_pika_xyz")  # Not hex
        assert not is_pokepoke_agent_name("other_prefix_swift_pika_a7f3")


class TestGetStaleInProgressItems:
    """Tests for get_stale_in_progress_items function."""

    def test_empty_list_when_no_items(self) -> None:
        """Should return empty list when no in-progress items."""
        result = get_stale_in_progress_items("pokepoke_current_agent_1234", [])
        assert result == []

    def test_empty_list_when_none_stale(self) -> None:
        """Should return empty list when all items are current agent's."""
        items = [
            _make_item("item-1", assignee="pokepoke_current_agent_1234"),
            _make_item("item-2", assignee="pokepoke_current_agent_1234"),
        ]
        result = get_stale_in_progress_items("pokepoke_current_agent_1234", items)
        assert result == []

    def test_excludes_current_run_worker_assignees(self) -> None:
        """Should not reclaim items assigned to this run's worker names."""
        base = "pokepoke_swift_pika_a7f3"
        items = [
            _make_item("item-1", assignee=f"{base}-cobra-worker-1"),
            _make_item("item-2", assignee=f"{base}-rainbow_boa-worker-2"),
            _make_item("item-3", assignee="pokepoke_clever_bulba_1234-cobra-worker-1"),
        ]
        result = get_stale_in_progress_items(base, items)
        assert [item.id for item in result] == ["item-3"]

    def test_excludes_explicit_current_worker_names(self) -> None:
        """Explicit current_worker_names should be excluded from reclamation."""
        base = "pokepoke_swift_pika_a7f3"
        current_workers = {
            f"{base}-cobra-worker-1",
            "custom-worker-name",
        }
        items = [
            _make_item("item-1", assignee=f"{base}-cobra-worker-1"),
            _make_item("item-2", assignee="custom-worker-name"),
            _make_item("item-3", assignee="pokepoke_clever_bulba_1234-cobra-worker-1"),
        ]
        result = get_stale_in_progress_items(
            base,
            items,
            current_worker_names=current_workers,
        )
        assert [item.id for item in result] == ["item-3"]

    def test_returns_stale_items(self) -> None:
        """Should return items assigned to defunct PokePoke agents."""
        items = [
            _make_item("item-1", assignee="pokepoke_old_agent_dead"),
            _make_item("item-2", assignee="pokepoke_current_agent_1234"),
            _make_item("item-3", assignee="pokepoke_another_old_beef"),
        ]
        result = get_stale_in_progress_items("pokepoke_current_agent_1234", items)

        assert len(result) == 2
        assert result[0].id == "item-1"
        assert result[1].id == "item-3"

    def test_skips_non_pokepoke_assignees(self) -> None:
        """Should skip items assigned to non-PokePoke names (e.g., human developers)."""
        items = [
            _make_item("item-1", assignee="human_developer"),
            _make_item("item-2", assignee="pokepoke_old_agent_dead"),
        ]
        result = get_stale_in_progress_items("pokepoke_current_agent_1234", items)

        assert len(result) == 1
        assert result[0].id == "item-2"

    def test_includes_unassigned_items(self) -> None:
        """Should include unassigned in_progress items."""
        items = [
            _make_item("item-1", assignee=None),
            _make_item("item-2", assignee=""),
        ]
        result = get_stale_in_progress_items("pokepoke_current_agent_1234", items)

        assert len(result) == 2

    def test_sorts_by_priority(self) -> None:
        """Should sort results by priority (lower number = higher priority)."""
        items = [
            _make_item("low-priority", assignee="pokepoke_old_agent_dead", priority=3),
            _make_item("high-priority", assignee="pokepoke_old_agent_cafe", priority=0),
            _make_item("med-priority", assignee="pokepoke_old_agent_beef", priority=2),
        ]
        result = get_stale_in_progress_items("pokepoke_current_agent_1234", items)

        assert len(result) == 3
        assert result[0].id == "high-priority"
        assert result[1].id == "med-priority"
        assert result[2].id == "low-priority"

    @patch("pokepoke.beads.beads_query.get_in_progress_items")
    def test_fetches_items_if_none_provided(self, mock_get_items: MagicMock) -> None:
        """Should fetch in-progress items if not provided."""
        mock_get_items.return_value = [
            _make_item("item-1", assignee="pokepoke_old_agent_dead"),
        ]

        result = get_stale_in_progress_items("pokepoke_current_agent_1234")

        mock_get_items.assert_called_once()
        assert len(result) == 1


class TestGetWorktreePathForItem:
    """Tests for get_worktree_path_for_item function."""

    @patch("pokepoke.git.git_operations.sanitize_branch_name")
    def test_returns_path_when_exists(
        self, mock_sanitize: MagicMock, tmp_path: Path
    ) -> None:
        """Should return path when worktree directory exists."""
        # Create the expected directory structure
        worktree_dir = tmp_path / "worktrees" / "task-test-item"
        worktree_dir.mkdir(parents=True)

        mock_sanitize.return_value = "test-item"
        result = get_worktree_path_for_item("test-item", tmp_path)

        assert result == worktree_dir

    @patch("pokepoke.git.git_operations.sanitize_branch_name")
    def test_returns_none_when_not_exists(
        self, mock_sanitize: MagicMock, tmp_path: Path
    ) -> None:
        """Should return None when worktree directory doesn't exist."""
        mock_sanitize.return_value = "test-item"
        result = get_worktree_path_for_item("test-item", tmp_path)

        assert result is None


class TestGetWorktreeCommitCount:
    """Tests for get_worktree_commit_count function."""

    @patch("pokepoke.git.git_helpers.run_git")
    def test_returns_commit_count(self, mock_run_git: MagicMock, tmp_path: Path) -> None:
        """Should return commit count from git rev-list."""
        mock_run_git.return_value = _completed(stdout="5\n")

        result = get_worktree_commit_count(tmp_path)

        assert result == 5
        mock_run_git.assert_called_once()

    @patch("pokepoke.git.git_helpers.run_git")
    def test_returns_zero_on_error(self, mock_run_git: MagicMock, tmp_path: Path) -> None:
        """Should return 0 when git command fails."""
        mock_run_git.return_value = _completed(returncode=1)

        result = get_worktree_commit_count(tmp_path)

        assert result == 0

    @patch("pokepoke.git.git_helpers.run_git")
    def test_returns_zero_on_exception(self, mock_run_git: MagicMock, tmp_path: Path) -> None:
        """Should return 0 when an exception occurs."""
        mock_run_git.side_effect = Exception("Git failed")

        result = get_worktree_commit_count(tmp_path)

        assert result == 0


class TestGetRecentCommitMessages:
    """Tests for get_recent_commit_messages function."""

    @patch("pokepoke.git.git_helpers.run_git")
    def test_returns_commit_messages(self, mock_run_git: MagicMock, tmp_path: Path) -> None:
        """Should return list of commit messages."""
        mock_run_git.return_value = _completed(stdout="Add feature\nFix bug\nUpdate docs\n")

        result = get_recent_commit_messages(tmp_path)

        assert result == ["Add feature", "Fix bug", "Update docs"]

    @patch("pokepoke.git.git_helpers.run_git")
    def test_returns_empty_on_error(self, mock_run_git: MagicMock, tmp_path: Path) -> None:
        """Should return empty list on error."""
        mock_run_git.return_value = _completed(returncode=1)

        result = get_recent_commit_messages(tmp_path)

        assert result == []


class TestGetModifiedFilesInWorktree:
    """Tests for get_modified_files_in_worktree function."""

    @patch("pokepoke.git.git_helpers.run_git")
    def test_returns_modified_files(self, mock_run_git: MagicMock, tmp_path: Path) -> None:
        """Should return list of modified files."""
        mock_run_git.return_value = _completed(stdout="src/main.py\nREADME.md\n")

        result = get_modified_files_in_worktree(tmp_path)

        assert result == ["src/main.py", "README.md"]

    @patch("pokepoke.git.git_helpers.run_git")
    def test_returns_empty_on_error(self, mock_run_git: MagicMock, tmp_path: Path) -> None:
        """Should return empty list on error."""
        mock_run_git.side_effect = Exception("Git failed")

        result = get_modified_files_in_worktree(tmp_path)

        assert result == []


class TestBuildResumeContext:
    """Tests for build_resume_context function."""

    @patch("pokepoke.beads.stale_item_recovery.get_modified_files_in_worktree")
    @patch("pokepoke.beads.stale_item_recovery.get_recent_commit_messages")
    @patch("pokepoke.beads.stale_item_recovery.get_worktree_commit_count")
    @patch("pokepoke.beads.stale_item_recovery.get_worktree_path_for_item")
    def test_builds_context_with_commits(
        self,
        mock_get_path: MagicMock,
        mock_commit_count: MagicMock,
        mock_commits: MagicMock,
        mock_files: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Should build context when worktree has commits."""
        mock_get_path.return_value = tmp_path / "worktree"
        mock_commit_count.return_value = 3
        mock_commits.return_value = ["Add feature", "Fix bug"]
        mock_files.return_value = ["src/main.py"]

        item = _make_item("test-item", assignee="pokepoke_old_agent_dead")
        result = build_resume_context(item, tmp_path)

        assert result is not None
        assert result["previous_assignee"] == "pokepoke_old_agent_dead"
        assert result["commit_count"] == 3
        assert result["commits"] == ["Add feature", "Fix bug"]
        assert result["modified_files"] == ["src/main.py"]

    @patch("pokepoke.beads.stale_item_recovery.get_worktree_path_for_item")
    def test_returns_none_when_no_worktree(
        self, mock_get_path: MagicMock, tmp_path: Path
    ) -> None:
        """Should return None when no worktree exists."""
        mock_get_path.return_value = None

        item = _make_item("test-item")
        result = build_resume_context(item, tmp_path)

        assert result is None

    @patch("pokepoke.beads.stale_item_recovery.get_worktree_commit_count")
    @patch("pokepoke.beads.stale_item_recovery.get_worktree_path_for_item")
    def test_returns_none_when_no_commits(
        self,
        mock_get_path: MagicMock,
        mock_commit_count: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Should return None when worktree has no commits ahead."""
        mock_get_path.return_value = tmp_path / "worktree"
        mock_commit_count.return_value = 0

        item = _make_item("test-item")
        result = build_resume_context(item, tmp_path)

        assert result is None


class TestFormatResumeContextForPrompt:
    """Tests for format_resume_context_for_prompt function."""

    def test_formats_basic_context(self) -> None:
        """Should format context with all fields."""
        context = {
            "previous_assignee": "pokepoke_old_agent_dead",
            "commit_count": 3,
            "commits": ["Add feature", "Fix bug"],
            "modified_files": ["src/main.py", "README.md"],
        }

        result = format_resume_context_for_prompt(context)

        assert "Previous agent: pokepoke_old_agent_dead" in result
        assert "Commits made: 3" in result
        assert "Add feature" in result
        assert "Fix bug" in result
        assert "src/main.py" in result
        assert "README.md" in result
        assert "Previous Work Session Context" in result

    def test_handles_empty_commits(self) -> None:
        """Should handle empty commits list."""
        context = {
            "previous_assignee": "pokepoke_old_agent_dead",
            "commit_count": 0,
            "commits": [],
            "modified_files": [],
        }

        result = format_resume_context_for_prompt(context)

        assert "Previous agent: pokepoke_old_agent_dead" in result
        assert "Recent commits" not in result

    def test_truncates_long_file_lists(self) -> None:
        """Should indicate truncation for many files."""
        context = {
            "previous_assignee": "pokepoke_old_agent_dead",
            "commit_count": 5,
            "commits": [],
            "modified_files": [f"file{i}.py" for i in range(15)],
        }

        result = format_resume_context_for_prompt(context)

        assert "... and 5 more files" in result
