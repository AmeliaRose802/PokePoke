"""Tests for copilot.py module (SDK-based implementation)."""

import pytest
import subprocess
import os
from unittest.mock import patch, MagicMock
from pathlib import Path

from pokepoke.copilot import (
    get_allowed_directories,
    build_prompt_from_template,
    build_prompt,
    invoke_copilot
)
from pokepoke.types import BeadsWorkItem, CopilotResult


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


@pytest.fixture
def sample_work_item_no_labels():
    """Create a work item without labels."""
    return BeadsWorkItem(
        id="test-456",
        title="No labels item",
        description="Item without labels",
        status="in_progress",
        priority=2,
        issue_type="bug",
        labels=None
    )


class TestGetAllowedDirectories:
    """Tests for get_allowed_directories function."""
    
    @patch('pokepoke.copilot.subprocess.run')
    @patch('pokepoke.copilot.os.getcwd')
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
    
    @patch('pokepoke.copilot.subprocess.run')
    @patch('pokepoke.copilot.os.getcwd')
    def test_allowed_directories_git_fails(self, mock_getcwd, mock_run):
        """Test allowed directories when git command fails."""
        mock_getcwd.return_value = "/current/dir"
        mock_run.side_effect = subprocess.CalledProcessError(1, "git")
        
        result = get_allowed_directories()
        
        # Should still return current directory
        assert result == ["/current/dir"]
    
    @patch('pokepoke.copilot.subprocess.run')
    @patch('pokepoke.copilot.os.getcwd')
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


class TestBuildPromptFromTemplate:
    """Tests for build_prompt_from_template function."""
    
    @patch('pokepoke.copilot.PromptService')
    def test_build_prompt_from_template(self, mock_service_class, sample_work_item):
        """Test building prompt from template."""
        mock_service = MagicMock()
        mock_service.load_and_render.return_value = "Rendered prompt"
        mock_service_class.return_value = mock_service
        
        result = build_prompt_from_template(sample_work_item)
        
        assert result == "Rendered prompt"
        mock_service.load_and_render.assert_called_once()
        call_args = mock_service.load_and_render.call_args
        assert call_args[0][0] == "beads-item"
        variables = call_args[0][1]
        assert variables["item_id"] == "test-123"
        assert variables["title"] == "Test work item"


class TestBuildPrompt:
    """Tests for build_prompt function."""
    
    def test_build_prompt_with_labels(self, sample_work_item):
        """Test building prompt with labels."""
        prompt = build_prompt(sample_work_item)
        
        assert "test-123" in prompt
        assert "Test work item" in prompt
        assert "Test description" in prompt
        assert "**Labels:** testing, coverage" in prompt
    
    def test_build_prompt_without_labels(self, sample_work_item_no_labels):
        """Test building prompt without labels."""
        prompt = build_prompt(sample_work_item_no_labels)
        
        assert "test-456" in prompt
        assert "No labels item" in prompt
        # Should not include labels section
        assert "Labels:" not in prompt


class TestInvokeCopilot:
    """Tests for invoke_copilot function (SDK-based)."""
    
    @patch('pokepoke.copilot.invoke_copilot_sdk_sync')
    def test_invoke_copilot_success(self, mock_sdk, sample_work_item):
        """Test successful invocation."""
        expected_result = CopilotResult(
            work_item_id="test-123",
            success=True,
            output="Success",
            attempt_count=1
        )
        mock_sdk.return_value = expected_result
        
        result = invoke_copilot(sample_work_item)
        
        assert result == expected_result
        mock_sdk.assert_called_once()
    
    @patch('pokepoke.copilot.invoke_copilot_sdk_sync')
    def test_invoke_copilot_with_params(self, mock_sdk, sample_work_item):
        """Test invocation with custom parameters."""
        expected_result = CopilotResult(
            work_item_id="test-123",
            success=True,
            output="Success",
            attempt_count=1
        )
        mock_sdk.return_value = expected_result
        
        result = invoke_copilot(
            sample_work_item,
            prompt="custom prompt",
            timeout=3600.0,
            deny_write=True
        )
        
        assert result == expected_result
        mock_sdk.assert_called_once_with(
            work_item=sample_work_item,
            prompt="custom prompt",
            retry_config=None,
            timeout=3600.0,
            deny_write=True,
            item_logger=None
        )

