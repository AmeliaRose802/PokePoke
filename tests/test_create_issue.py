"""Unit tests for create_issue function."""

import subprocess
import json
from unittest.mock import Mock, patch
import pytest

from src.pokepoke.beads import create_issue


class TestCreateIssue:
    """Test create_issue function."""
    
    @patch('src.pokepoke.beads.subprocess.run')
    def test_create_issue_basic(self, mock_run: Mock) -> None:
        """Test creating a basic issue."""
        mock_run.return_value = Mock(
            stdout=json.dumps({"id": "task-123", "title": "New Task"}),
            returncode=0
        )
        
        issue_id = create_issue("New Task", issue_type="task", priority=1)
        
        assert issue_id == "task-123"
        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        assert 'bd' in call_args
        assert 'create' in call_args
        assert 'New Task' in call_args
    
    @patch('src.pokepoke.beads.subprocess.run')
    def test_create_issue_with_description(self, mock_run: Mock) -> None:
        """Test creating issue with description."""
        mock_run.return_value = Mock(
            stdout=json.dumps({"id": "task-456"}),
            returncode=0
        )
        
        issue_id = create_issue(
            "Task with desc",
            description="Detailed description",
            priority=2
        )
        
        assert issue_id == "task-456"
        call_args = mock_run.call_args[0][0]
        assert '-d' in call_args
        assert 'Detailed description' in call_args
    
    @patch('src.pokepoke.beads.subprocess.run')
    def test_create_issue_with_parent(self, mock_run: Mock) -> None:
        """Test creating issue with parent dependency."""
        mock_run.return_value = Mock(
            stdout=json.dumps({"id": "task-789"}),
            returncode=0
        )
        
        issue_id = create_issue(
            "Child task",
            parent_id="feature-1",
            priority=1
        )
        
        assert issue_id == "task-789"
        call_args = mock_run.call_args[0][0]
        assert '--deps' in call_args
        assert 'parent:feature-1' in call_args
    
    @patch('src.pokepoke.beads.subprocess.run')
    def test_create_issue_with_labels(self, mock_run: Mock) -> None:
        """Test creating issue with labels."""
        # Mock two calls: create and label add
        mock_run.side_effect = [
            Mock(stdout=json.dumps({"id": "task-999"}), returncode=0),  # create
            Mock(stdout="", returncode=0)  # label add
        ]
        
        issue_id = create_issue(
            "Labeled task",
            labels=["bug", "urgent"],
            priority=0
        )
        
        assert issue_id == "task-999"
        assert mock_run.call_count == 2
        
        # Check label command was called
        label_call = mock_run.call_args_list[1][0][0]
        assert 'bd' in label_call
        assert 'label' in label_call
        assert 'add' in label_call
        assert 'task-999' in label_call
        assert 'bug' in label_call
        assert 'urgent' in label_call
    
    @patch('src.pokepoke.beads.subprocess.run')
    def test_create_issue_subprocess_error(self, mock_run: Mock) -> None:
        """Test create_issue handles subprocess errors gracefully."""
        mock_run.side_effect = subprocess.CalledProcessError(1, 'bd')
        
        issue_id = create_issue("Failed task")
        
        assert issue_id is None
    
    @patch('src.pokepoke.beads.subprocess.run')
    def test_create_issue_json_parse_error(self, mock_run: Mock) -> None:
        """Test create_issue handles JSON parse errors gracefully."""
        mock_run.return_value = Mock(
            stdout="Not valid JSON",
            returncode=0
        )
        
        issue_id = create_issue("Task")
        
        assert issue_id is None
    
    @patch('src.pokepoke.beads.subprocess.run')
    def test_create_issue_array_response(self, mock_run: Mock) -> None:
        """Test create_issue handles array response."""
        mock_run.return_value = Mock(
            stdout=json.dumps([{"id": "task-111", "title": "Task"}]),
            returncode=0
        )
        
        issue_id = create_issue("Task from array")
        
        assert issue_id == "task-111"
    
    @patch('src.pokepoke.beads.subprocess.run')
    def test_create_issue_empty_response(self, mock_run: Mock) -> None:
        """Test create_issue handles empty response."""
        mock_run.return_value = Mock(
            stdout="",
            returncode=0
        )
        
        issue_id = create_issue("Task")
        
        assert issue_id is None
