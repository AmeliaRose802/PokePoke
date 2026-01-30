"""Unit tests for orchestrator cleanup detection."""

import subprocess
from unittest.mock import Mock, patch, MagicMock
import pytest
from pathlib import Path

from src.pokepoke.orchestrator import run_orchestrator
from src.pokepoke.types import BeadsWorkItem


class TestOrchestratorCleanupDetection:
    """Test orchestrator's main repo cleanup detection."""
    
    @patch('pokepoke.agent_runner.invoke_cleanup_agent')
    @patch('src.pokepoke.orchestrator.get_ready_work_items')
    @patch('subprocess.run')
    def test_detects_uncommitted_changes_and_invokes_cleanup(
        self,
        mock_subprocess: Mock,
        mock_get_items: Mock,
        mock_cleanup: Mock
    ) -> None:
        """Test that uncommitted non-beads changes invoke cleanup agent."""
        # Mock git status showing uncommitted files
        mock_subprocess.return_value = Mock(
            stdout=" M src/pokepoke/orchestrator.py\n M src/pokepoke/beads.py",
            returncode=0
        )
        
        # Mock cleanup agent failure (so orchestrator won't proceed)
        mock_cleanup.return_value = (False, None)
        
        result = run_orchestrator(interactive=False, continuous=False)
        
        # Verify orchestrator returned error code when cleanup fails
        assert result == 1
        
        # Verify cleanup agent was invoked
        mock_cleanup.assert_called_once()
        
        # Verify get_ready_work_items was never called (since cleanup failed)
        mock_get_items.assert_not_called()
    
    @patch('src.pokepoke.orchestrator.get_ready_work_items')
    @patch('subprocess.run')
    def test_detects_beads_changes_without_autocommit(
        self,
        mock_subprocess: Mock,
        mock_get_items: Mock
    ) -> None:
        """Test that beads-only changes are detected but NOT auto-committed.
        
        Beads has its own sync mechanism via 'bd sync' and daemon mode.
        The orchestrator should just detect and notify, not manually commit.
        """
        # Mock git status showing only beads changes
        mock_subprocess.side_effect = [
            Mock(stdout='{"summary": {"total_issues": 10}}', returncode=0),  # bd stats for starting beads stats
            Mock(stdout=" M .beads/issues.jsonl", returncode=0),  # git status check
            Mock(stdout='{"summary": {"total_issues": 10}}', returncode=0),  # bd stats for ending beads stats
        ]
        
        # Mock no work items
        mock_get_items.return_value = []
        
        result = run_orchestrator(interactive=False, continuous=False)
        
        # Verify we called bd stats (start), git status, and bd stats (end) - no git add/commit
        assert mock_subprocess.call_count == 3
        
        # Verify no git add or commit calls were made
        add_calls = [
            call for call in mock_subprocess.call_args_list
            if len(call[0]) > 0 and 'add' in str(call[0][0])
        ]
        commit_calls = [
            call for call in mock_subprocess.call_args_list
            if len(call[0]) > 0 and 'commit' in str(call[0][0])
        ]
        assert len(add_calls) == 0
        assert len(commit_calls) == 0
        assert result == 0
    
    @patch('src.pokepoke.orchestrator.get_ready_work_items')
    @patch('subprocess.run')
    def test_clean_repo_proceeds_to_work(
        self,
        mock_subprocess: Mock,
        mock_get_items: Mock
    ) -> None:
        """Test that clean repo proceeds to normal work processing."""
        # Mock git status showing clean repo
        mock_subprocess.return_value = Mock(
            stdout="",
            returncode=0
        )
        
        # Mock no work items
        mock_get_items.return_value = []
        
        result = run_orchestrator(interactive=False, continuous=False)
        
        # Verify we proceeded to get work items
        mock_get_items.assert_called_once()
        assert result == 0

