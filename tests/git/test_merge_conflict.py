"""Tests for merge_conflict module."""

import subprocess
from pathlib import Path
from unittest.mock import Mock, patch

from pokepoke.git.merge_conflict import (
    abort_merge,
    get_merge_conflict_details,
    get_unmerged_files,
    is_merge_in_progress,
)


class TestIsMergeInProgress:
    """Tests for is_merge_in_progress function."""

    @patch('subprocess.run')
    def test_merge_in_progress_true(self, mock_run: Mock) -> None:
        """Test when MERGE_HEAD exists."""
        mock_run.return_value = Mock(returncode=0)

        result = is_merge_in_progress()

        assert result is True
        mock_run.assert_called_once()

    @patch('subprocess.run')
    def test_merge_in_progress_false(self, mock_run: Mock) -> None:
        """Test when MERGE_HEAD does not exist."""
        mock_run.return_value = Mock(returncode=1)

        result = is_merge_in_progress()

        assert result is False

    @patch('subprocess.run')
    def test_merge_in_progress_with_path(self, mock_run: Mock) -> None:
        """Test with explicit repo path."""
        mock_run.return_value = Mock(returncode=0)

        result = is_merge_in_progress(repo_path=Path("/some/path"))

        assert result is True
        # Verify -C flag was used
        call_args = mock_run.call_args[0][0]
        assert "-C" in call_args
        # Path can be in different formats on different platforms
        path_index = call_args.index("-C") + 1
        assert "some" in call_args[path_index] and "path" in call_args[path_index]

    @patch('subprocess.run')
    def test_merge_in_progress_exception(self, mock_run: Mock) -> None:
        """Test when subprocess raises exception."""
        mock_run.side_effect = subprocess.CalledProcessError(1, "git")

        result = is_merge_in_progress()

        assert result is False


class TestGetUnmergedFiles:
    """Tests for get_unmerged_files function."""

    @patch('subprocess.run')
    def test_get_unmerged_files_with_conflicts(self, mock_run: Mock) -> None:
        """Test when there are merge conflicts."""
        mock_run.return_value = Mock(
            stdout="UU conflict1.py\nUU conflict2.py\nM  modified.py\n",
            returncode=0
        )

        result = get_unmerged_files()

        assert len(result) == 2
        assert "conflict1.py" in result
        assert "conflict2.py" in result

    @patch('subprocess.run')
    def test_get_unmerged_files_no_conflicts(self, mock_run: Mock) -> None:
        """Test when there are no merge conflicts."""
        mock_run.return_value = Mock(stdout="M  modified.py\n", returncode=0)

        result = get_unmerged_files()

        assert len(result) == 0

    @patch('subprocess.run')
    def test_get_unmerged_files_all_conflict_types(self, mock_run: Mock) -> None:
        """Test all conflict type patterns."""
        mock_run.return_value = Mock(
            stdout="UU both_modified.py\nAA both_added.py\nDD both_deleted.py\n",
            returncode=0
        )

        result = get_unmerged_files()

        assert len(result) == 3

    @patch('subprocess.run')
    def test_get_unmerged_files_with_path(self, mock_run: Mock) -> None:
        """Test with explicit repo path."""
        mock_run.return_value = Mock(stdout="", returncode=0)

        get_unmerged_files(repo_path=Path("/some/path"))

        call_args = mock_run.call_args[0][0]
        assert "-C" in call_args

    @patch('subprocess.run')
    def test_get_unmerged_files_exception(self, mock_run: Mock) -> None:
        """Test when subprocess raises exception."""
        mock_run.side_effect = subprocess.CalledProcessError(1, "git")

        result = get_unmerged_files()

        assert result == []


class TestAbortMerge:
    """Tests for abort_merge function."""

    @patch('subprocess.run')
    def test_abort_merge_success(self, mock_run: Mock) -> None:
        """Test successful merge abort."""
        mock_run.return_value = Mock(returncode=0)

        success, error = abort_merge()

        assert success is True
        assert error == ""

    @patch('subprocess.run')
    def test_abort_merge_failure(self, mock_run: Mock) -> None:
        """Test failed merge abort."""
        mock_run.return_value = Mock(returncode=1, stderr="error message")

        success, error = abort_merge()

        assert success is False
        assert "error message" in error

    @patch('subprocess.run')
    def test_abort_merge_with_path(self, mock_run: Mock) -> None:
        """Test with explicit repo path."""
        mock_run.return_value = Mock(returncode=0)

        success, _error = abort_merge(repo_path=Path("/some/path"))

        assert success is True
        call_args = mock_run.call_args[0][0]
        assert "-C" in call_args

    @patch('subprocess.run')
    def test_abort_merge_timeout(self, mock_run: Mock) -> None:
        """Test when merge abort times out."""
        mock_run.side_effect = subprocess.TimeoutExpired("git", 30)

        success, error = abort_merge()

        assert success is False
        assert "timed out" in error.lower()


class TestGetMergeConflictDetails:
    """Tests for get_merge_conflict_details function."""

    @patch('pokepoke.git.merge_conflict.get_unmerged_files')
    @patch('pokepoke.git.merge_conflict.is_merge_in_progress')
    @patch('subprocess.run')
    def test_get_details_with_conflict(
        self, mock_run: Mock, mock_is_merge: Mock, mock_get_unmerged: Mock
    ) -> None:
        """Test getting details when merge is in progress."""
        mock_is_merge.return_value = True
        mock_get_unmerged.return_value = ["file1.py", "file2.py"]
        mock_run.return_value = Mock(stdout="abc123\n", returncode=0)

        result = get_merge_conflict_details()

        assert result["is_merging"] is True
        assert result["conflict_count"] == 2
        assert "file1.py" in result["unmerged_files"]
        assert result["merge_head"] == "abc123"

    @patch('pokepoke.git.merge_conflict.get_unmerged_files')
    @patch('pokepoke.git.merge_conflict.is_merge_in_progress')
    def test_get_details_no_conflict(
        self, mock_is_merge: Mock, mock_get_unmerged: Mock
    ) -> None:
        """Test getting details when no merge is in progress."""
        mock_is_merge.return_value = False
        mock_get_unmerged.return_value = []

        result = get_merge_conflict_details()

        assert result["is_merging"] is False
        assert result["conflict_count"] == 0
        assert result["merge_head"] == ""

    @patch('pokepoke.git.merge_conflict.get_unmerged_files')
    @patch('pokepoke.git.merge_conflict.is_merge_in_progress')
    @patch('subprocess.run')
    def test_get_details_with_repo_path(
        self, mock_run: Mock, mock_is_merge: Mock, mock_get_unmerged: Mock
    ) -> None:
        """Test get_merge_conflict_details with explicit repo_path (line 124)."""
        mock_is_merge.return_value = True
        mock_get_unmerged.return_value = []
        mock_run.return_value = Mock(stdout="def456\n", returncode=0)

        result = get_merge_conflict_details(repo_path=Path("/my/repo"))

        assert result["merge_head"] == "def456"
        call_args = mock_run.call_args[0][0]
        assert "-C" in call_args

    @patch('pokepoke.git.merge_conflict.get_unmerged_files')
    @patch('pokepoke.git.merge_conflict.is_merge_in_progress')
    @patch('subprocess.run')
    def test_get_details_merge_head_exception(
        self, mock_run: Mock, mock_is_merge: Mock, mock_get_unmerged: Mock
    ) -> None:
        """Test get_merge_conflict_details when MERGE_HEAD retrieval fails (lines 135-136)."""
        mock_is_merge.return_value = True
        mock_get_unmerged.return_value = ["file.py"]
        mock_run.side_effect = Exception("git process error")

        result = get_merge_conflict_details()

        assert result["is_merging"] is True
        assert result["merge_head"] == ""
        assert result["conflict_count"] == 1


class TestAbortMergeGenericException:
    """Test abort_merge with a generic exception (lines 103-104)."""

    @patch('subprocess.run')
    def test_abort_merge_generic_exception(self, mock_run: Mock) -> None:
        """Test abort_merge handles generic exceptions gracefully."""
        mock_run.side_effect = OSError("system error")

        success, error = abort_merge()

        assert success is False
        assert "system error" in error


class TestScanFilesForConflictMarkers:
    """Tests for scan_files_for_conflict_markers function."""

    def test_detects_conflict_markers(self, tmp_path: Path) -> None:
        """Files with <<<<<<< / ======= / >>>>>>> are flagged."""
        from pokepoke.git.merge_conflict import scan_files_for_conflict_markers

        conflicted = tmp_path / "conflict.py"
        conflicted.write_text(
            "before\n<<<<<<< HEAD\nours\n=======\ntheirs\n>>>>>>> branch\nafter\n"
        )
        clean = tmp_path / "clean.py"
        clean.write_text("no markers here\n")

        result = scan_files_for_conflict_markers(
            ["conflict.py", "clean.py"], repo_path=tmp_path
        )

        assert result == ["conflict.py"]

    def test_no_conflict_markers(self, tmp_path: Path) -> None:
        """Files without markers return empty list."""
        from pokepoke.git.merge_conflict import scan_files_for_conflict_markers

        clean = tmp_path / "clean.py"
        clean.write_text("all good\n")

        result = scan_files_for_conflict_markers(["clean.py"], repo_path=tmp_path)

        assert result == []

    def test_nonexistent_file_skipped(self, tmp_path: Path) -> None:
        """Missing files are silently skipped."""
        from pokepoke.git.merge_conflict import scan_files_for_conflict_markers

        result = scan_files_for_conflict_markers(
            ["missing.py"], repo_path=tmp_path
        )

        assert result == []

    def test_unreadable_file_skipped(self, tmp_path: Path) -> None:
        """Files that raise OSError on read are skipped."""
        from pokepoke.git.merge_conflict import scan_files_for_conflict_markers

        bad = tmp_path / "bad.py"
        bad.write_text("dummy")

        with patch.object(Path, 'read_text', side_effect=OSError("perm")):
            result = scan_files_for_conflict_markers(
                ["bad.py"], repo_path=tmp_path
            )

        assert result == []

    def test_equals_only_marker(self, tmp_path: Path) -> None:
        """A file with only ======= markers is still detected."""
        from pokepoke.git.merge_conflict import scan_files_for_conflict_markers

        f = tmp_path / "partial.py"
        f.write_text("line\n=======\nother\n")

        result = scan_files_for_conflict_markers(["partial.py"], repo_path=tmp_path)

        assert result == ["partial.py"]

    def test_uses_cwd_when_no_repo_path(self, tmp_path: Path, monkeypatch) -> None:
        """Defaults to cwd when repo_path is None."""
        from pokepoke.git.merge_conflict import scan_files_for_conflict_markers

        monkeypatch.chdir(tmp_path)
        f = tmp_path / "file.py"
        f.write_text("<<<<<<< HEAD\nstuff\n")

        result = scan_files_for_conflict_markers(["file.py"])

        assert result == ["file.py"]


class TestDetectDirtyConflictFiles:
    """Tests for detect_dirty_conflict_files function."""

    def test_returns_empty_on_timeout(self) -> None:
        """Returns empty list when git status times out."""
        from pokepoke.git.merge_conflict import detect_dirty_conflict_files

        with patch('pokepoke.git.merge_conflict.get_status_porcelain_and_changes') as mock_status:
            mock_status.side_effect = subprocess.TimeoutExpired("git", 30)
            result = detect_dirty_conflict_files(Path("/fake/repo"))

        assert result == []

    def test_returns_empty_when_all_deleted(self) -> None:
        """Returns empty when all dirty entries are deletions."""
        from pokepoke.git.merge_conflict import detect_dirty_conflict_files

        with patch('pokepoke.git.merge_conflict.get_status_porcelain_and_changes') as mock_status:
            mock_status.return_value = (
                " D gone.py",
                {'other': [' D gone.py'], 'beads': [], 'worktree': [], 'untracked': []},
            )
            result = detect_dirty_conflict_files(Path("/fake/repo"))

        assert result == []

    def test_returns_empty_for_empty_entries(self) -> None:
        """Returns empty when entries are blank strings."""
        from pokepoke.git.merge_conflict import detect_dirty_conflict_files

        with patch('pokepoke.git.merge_conflict.get_status_porcelain_and_changes') as mock_status:
            mock_status.return_value = (
                "",
                {'other': ['', '  '], 'beads': [], 'worktree': [], 'untracked': []},
            )
            result = detect_dirty_conflict_files(Path("/fake/repo"))

        assert result == []
