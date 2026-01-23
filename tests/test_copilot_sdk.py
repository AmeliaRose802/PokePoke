"""Tests for copilot_sdk.py module (direct SDK integration)."""

import pytest
import subprocess
from unittest.mock import patch, MagicMock, AsyncMock
from pathlib import Path

from pokepoke.copilot_sdk import (
    get_allowed_directories,
    build_prompt_from_work_item
)
from pokepoke.types import BeadsWorkItem


@pytest.fixture
def sample_work_item():
    """Create a sample work item for testing."""
    return BeadsWorkItem(
        id="test-123",
        title="Test work item",
        description="Test description",
        status="in_progress",
        priority=1,
        issue_type="task",
        labels=["testing", "coverage"]
    )


class TestGetAllowedDirectoriesSDK:
    """Tests for get_allowed_directories function in SDK module."""
    
    @patch('pokepoke.copilot_sdk.subprocess.run')
    @patch('pokepoke.copilot_sdk.os.getcwd')
    def test_allowed_directories_with_git(self, mock_getcwd, mock_run):
        """Test allowed directories when git command succeeds."""
        mock_getcwd.return_value = "/current/dir"
        mock_run.return_value = MagicMock(
            stdout=".git\n",
            returncode=0
        )
        
        result = get_allowed_directories()
        
        assert "/current/dir" in result
        assert len(result) >= 1
    
    @patch('pokepoke.copilot_sdk.subprocess.run')
    @patch('pokepoke.copilot_sdk.os.getcwd')
    def test_allowed_directories_git_fails(self, mock_getcwd, mock_run):
        """Test allowed directories when git command fails."""
        mock_getcwd.return_value = "/current/dir"
        mock_run.side_effect = subprocess.CalledProcessError(1, "git")
        
        result = get_allowed_directories()
        
        # Should still return current directory
        assert result == ["/current/dir"]
    
    @patch('pokepoke.copilot_sdk.subprocess.run')
    @patch('pokepoke.copilot_sdk.os.getcwd')
    def test_allowed_directories_different_root(self, mock_getcwd, mock_run):
        """Test when worktree directory differs from repo root."""
        mock_getcwd.return_value = "/worktree/dir"
        mock_run.return_value = MagicMock(
            stdout="/repo/.git\n",
            returncode=0
        )
        
        result = get_allowed_directories()
        
        # Should contain both worktree and repo root
        assert "/worktree/dir" in result


class TestBuildPromptFromWorkItem:
    """Tests for build_prompt_from_work_item function."""
    
    @patch('pokepoke.copilot_sdk.PromptService')
    @patch('pokepoke.copilot_sdk.get_allowed_directories')
    def test_build_prompt_from_work_item(self, mock_get_dirs, mock_service_class, sample_work_item):
        """Test building prompt from work item."""
        mock_get_dirs.return_value = ["/allowed/dir1", "/allowed/dir2"]
        mock_service = MagicMock()
        mock_service.load_and_render.return_value = "Rendered prompt"
        mock_service_class.return_value = mock_service
        
        result = build_prompt_from_work_item(sample_work_item)
        
        assert result == "Rendered prompt"
        mock_service.load_and_render.assert_called_once()
        call_args = mock_service.load_and_render.call_args
        assert call_args[0][0] == "beads-item"
        variables = call_args[0][1]
        assert variables["item_id"] == "test-123"
        assert variables["title"] == "Test work item"
        assert variables["allowed_directories"] == ["/allowed/dir1", "/allowed/dir2"]
    
    @patch('pokepoke.copilot_sdk.PromptService')
    @patch('pokepoke.copilot_sdk.get_allowed_directories')
    def test_build_prompt_without_labels(self, mock_get_dirs, mock_service_class):
        """Test building prompt for work item without labels."""
        mock_get_dirs.return_value = ["/dir"]
        mock_service = MagicMock()
        mock_service.load_and_render.return_value = "Prompt"
        mock_service_class.return_value = mock_service
        
        work_item = BeadsWorkItem(
            id="test-456",
            title="No labels",
            description="Test",
            status="open",
            priority=2,
            issue_type="bug",
            labels=None
        )
        
        result = build_prompt_from_work_item(work_item)
        
        assert result == "Prompt"
        call_args = mock_service.load_and_render.call_args
        variables = call_args[0][1]
        assert variables["labels"] is None
