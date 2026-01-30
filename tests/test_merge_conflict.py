"""Tests for merge_conflict module."""

import pytest
from unittest.mock import Mock, patch
import subprocess
from pathlib import Path

from pokepoke.merge_conflict import (
    is_merge_in_progress,
    get_unmerged_files,
    abort_merge,
    get_merge_conflict_details,
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
        
        result = get_unmerged_files(repo_path=Path("/some/path"))
        
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
        
        success, error = abort_merge(repo_path=Path("/some/path"))
        
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
    
    @patch('pokepoke.merge_conflict.get_unmerged_files')
    @patch('pokepoke.merge_conflict.is_merge_in_progress')
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

    @patch('pokepoke.merge_conflict.get_unmerged_files')
    @patch('pokepoke.merge_conflict.is_merge_in_progress')
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
