"""Unit tests for orchestrator cleanup detection."""

from unittest.mock import Mock, patch

from src.pokepoke.orchestrator import run_orchestrator
from src.pokepoke.types import BeadsStats


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
    
    @patch('src.pokepoke.orchestrator.check_and_commit_main_repo')
    @patch('src.pokepoke.orchestrator.get_beads_stats')
    @patch('src.pokepoke.orchestrator.get_ready_work_items')
    def test_detects_beads_changes_without_autocommit(
        self,
        mock_get_items: Mock,
        mock_beads_stats: Mock,
        mock_check_repo: Mock
    ) -> None:
        """Test that beads-only changes are detected but NOT auto-committed.
        
        Beads has its own sync mechanism via 'bd sync' and daemon mode.
        The orchestrator should just detect and notify, not manually commit.
        """
        # Mock beads stats with proper BeadsStats object
        mock_beads_stats.return_value = BeadsStats(
            total_issues=10,
            open_issues=5,
            in_progress_issues=2,
            closed_issues=3,
            ready_issues=1
        )
        
        # Mock check_and_commit_main_repo returns success (no uncommitted changes)
        mock_check_repo.return_value = True
        
        # Mock no work items
        mock_get_items.return_value = []
        
        result = run_orchestrator(interactive=False, continuous=False)
        
        # Verify check_and_commit_main_repo was called
        mock_check_repo.assert_called_once()
        
        # Verify orchestrator completed successfully
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

