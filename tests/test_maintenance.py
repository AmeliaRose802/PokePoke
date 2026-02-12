"""Tests for the periodic maintenance module."""

import pytest
from unittest.mock import Mock, patch, MagicMock
from pokepoke.types import AgentStats, SessionStats
from pokepoke.config import MaintenanceConfig, MaintenanceAgentConfig, ProjectConfig
from pokepoke.maintenance import aggregate_stats, run_periodic_maintenance


def _make_default_config() -> ProjectConfig:
    """Create a ProjectConfig with default maintenance agents."""
    config = ProjectConfig()
    config.maintenance = MaintenanceConfig.defaults()
    return config


class TestAggregateStats:
    """Test aggregate_stats function."""
    
    def test_aggregates_all_fields(self) -> None:
        """Test that all stats fields are aggregated correctly."""
        session_stats = SessionStats(agent_stats=AgentStats(
            wall_duration=10.0,
            api_duration=5.0,
            input_tokens=100,
            output_tokens=50,
            lines_added=10,
            lines_removed=5,
            premium_requests=1,
            tool_calls=5,
            retries=0
        ))
        
        item_stats = AgentStats(
            wall_duration=5.0,
            api_duration=2.0,
            input_tokens=50,
            output_tokens=25,
            lines_added=5,
            lines_removed=2,
            premium_requests=1,
            tool_calls=3,
            retries=1
        )
        
        aggregate_stats(session_stats, item_stats)
        
        assert session_stats.agent_stats.wall_duration == 15.0
        assert session_stats.agent_stats.api_duration == 7.0
        assert session_stats.agent_stats.input_tokens == 150
        assert session_stats.agent_stats.output_tokens == 75
        assert session_stats.agent_stats.lines_added == 15
        assert session_stats.agent_stats.lines_removed == 7
        assert session_stats.agent_stats.premium_requests == 2
        assert session_stats.agent_stats.tool_calls == 8
        assert session_stats.agent_stats.retries == 1

    def test_aggregates_from_zero(self) -> None:
        """Test aggregation when session stats start at zero."""
        session_stats = SessionStats(agent_stats=AgentStats())
        
        item_stats = AgentStats(
            wall_duration=10.0,
            input_tokens=100,
            output_tokens=50
        )
        
        aggregate_stats(session_stats, item_stats)
        
        assert session_stats.agent_stats.wall_duration == 10.0
        assert session_stats.agent_stats.input_tokens == 100
        assert session_stats.agent_stats.output_tokens == 50

    def test_aggregates_multiple_items(self) -> None:
        """Test aggregation of multiple items."""
        session_stats = SessionStats(agent_stats=AgentStats())
        
        for i in range(3):
            item_stats = AgentStats(
                wall_duration=10.0,
                input_tokens=100
            )
            aggregate_stats(session_stats, item_stats)
        
        assert session_stats.agent_stats.wall_duration == 30.0
        assert session_stats.agent_stats.input_tokens == 300


class TestRunPeriodicMaintenance:
    """Test run_periodic_maintenance function."""
    
    @patch('pokepoke.maintenance.get_config')
    @patch('pokepoke.maintenance.run_maintenance_agent')
    @patch('pokepoke.agent_runner.run_beta_tester')
    @patch('pokepoke.agent_runner.run_worktree_cleanup')
    @patch('pokepoke.maintenance.set_terminal_banner')
    @patch('pokepoke.maintenance.ui')
    def test_skips_when_items_completed_zero(
        self,
        mock_ui: Mock,
        mock_banner: Mock,
        mock_worktree_cleanup: Mock,
        mock_beta_tester: Mock,
        mock_maintenance: Mock,
        mock_config: Mock
    ) -> None:
        """Test that no maintenance runs when items_completed is 0."""
        mock_config.return_value = _make_default_config()
        session_stats = SessionStats(agent_stats=AgentStats())
        run_logger = Mock()
        
        run_periodic_maintenance(0, session_stats, run_logger)
        
        mock_maintenance.assert_not_called()
        mock_beta_tester.assert_not_called()
        mock_worktree_cleanup.assert_not_called()

    @patch('pokepoke.maintenance.get_config')
    @patch('pokepoke.maintenance.run_maintenance_agent')
    @patch('pokepoke.agent_runner.run_beta_tester')
    @patch('pokepoke.agent_runner.run_worktree_cleanup')
    @patch('pokepoke.maintenance.set_terminal_banner')
    @patch('pokepoke.maintenance.ui')
    def test_runs_janitor_at_interval_2(
        self,
        mock_ui: Mock,
        mock_banner: Mock,
        mock_worktree_cleanup: Mock,
        mock_beta_tester: Mock,
        mock_maintenance: Mock,
        mock_config: Mock
    ) -> None:
        """Test that Janitor runs every 2 items."""
        mock_config.return_value = _make_default_config()
        session_stats = SessionStats(agent_stats=AgentStats())
        run_logger = Mock()
        mock_maintenance.return_value = None
        
        # Should run at 2, 4, 6, 8...
        run_periodic_maintenance(2, session_stats, run_logger)
        
        # Check Janitor was called (it runs at every 2 items)
        calls = [call for call in mock_maintenance.call_args_list 
                 if call[0][0] == "Janitor"]
        assert len(calls) == 1
        assert session_stats.janitor_agent_runs == 1

    @patch('pokepoke.maintenance.get_config')
    @patch('pokepoke.maintenance.run_maintenance_agent')
    @patch('pokepoke.agent_runner.run_beta_tester')
    @patch('pokepoke.agent_runner.run_worktree_cleanup')
    @patch('pokepoke.maintenance.set_terminal_banner')
    @patch('pokepoke.maintenance.ui')
    def test_runs_beta_tester_at_interval_3(
        self,
        mock_ui: Mock,
        mock_banner: Mock,
        mock_worktree_cleanup: Mock,
        mock_beta_tester: Mock,
        mock_maintenance: Mock,
        mock_config: Mock
    ) -> None:
        """Test that Beta Tester runs every 3 items."""
        mock_config.return_value = _make_default_config()
        session_stats = SessionStats(agent_stats=AgentStats())
        run_logger = Mock()
        mock_beta_tester.return_value = None
        mock_maintenance.return_value = None
        
        run_periodic_maintenance(3, session_stats, run_logger)
        
        mock_beta_tester.assert_called_once()
        assert session_stats.beta_tester_agent_runs == 1

    @patch('pokepoke.maintenance.get_config')
    @patch('pokepoke.maintenance.run_maintenance_agent')
    @patch('pokepoke.agent_runner.run_beta_tester')
    @patch('pokepoke.agent_runner.run_worktree_cleanup')
    @patch('pokepoke.maintenance.set_terminal_banner')
    @patch('pokepoke.maintenance.ui')
    def test_runs_worktree_cleanup_at_interval_4(
        self,
        mock_ui: Mock,
        mock_banner: Mock,
        mock_worktree_cleanup: Mock,
        mock_beta_tester: Mock,
        mock_maintenance: Mock,
        mock_config: Mock
    ) -> None:
        """Test that Worktree Cleanup runs every 4 items."""
        mock_config.return_value = _make_default_config()
        session_stats = SessionStats(agent_stats=AgentStats())
        run_logger = Mock()
        mock_worktree_cleanup.return_value = None
        mock_maintenance.return_value = None
        
        run_periodic_maintenance(4, session_stats, run_logger)
        
        mock_worktree_cleanup.assert_called_once()
        assert session_stats.worktree_cleanup_agent_runs == 1

    @patch('pokepoke.maintenance.get_config')
    @patch('pokepoke.maintenance.run_maintenance_agent')
    @patch('pokepoke.agent_runner.run_beta_tester')
    @patch('pokepoke.agent_runner.run_worktree_cleanup')
    @patch('pokepoke.maintenance.set_terminal_banner')
    @patch('pokepoke.maintenance.ui')
    def test_runs_tech_debt_at_interval_5(
        self,
        mock_ui: Mock,
        mock_banner: Mock,
        mock_worktree_cleanup: Mock,
        mock_beta_tester: Mock,
        mock_maintenance: Mock,
        mock_config: Mock
    ) -> None:
        """Test that Tech Debt and Code Review run every 5 items."""
        mock_config.return_value = _make_default_config()
        session_stats = SessionStats(agent_stats=AgentStats())
        run_logger = Mock()
        mock_maintenance.return_value = None
        
        run_periodic_maintenance(5, session_stats, run_logger)
        
        # Check Tech Debt and Code Review were called
        tech_debt_calls = [call for call in mock_maintenance.call_args_list 
                          if call[0][0] == "Tech Debt"]
        code_review_calls = [call for call in mock_maintenance.call_args_list 
                             if call[0][0] == "Code Review"]
        
        assert len(tech_debt_calls) == 1
        assert len(code_review_calls) == 1
        assert session_stats.tech_debt_agent_runs == 1
        assert session_stats.code_review_agent_runs == 1

    @patch('pokepoke.maintenance.get_config')
    @patch('pokepoke.maintenance.run_maintenance_agent')
    @patch('pokepoke.agent_runner.run_beta_tester')
    @patch('pokepoke.agent_runner.run_worktree_cleanup')
    @patch('pokepoke.maintenance.set_terminal_banner')
    @patch('pokepoke.maintenance.ui')
    def test_runs_backlog_cleanup_at_interval_7(
        self,
        mock_ui: Mock,
        mock_banner: Mock,
        mock_worktree_cleanup: Mock,
        mock_beta_tester: Mock,
        mock_maintenance: Mock,
        mock_config: Mock
    ) -> None:
        """Test that Backlog Cleanup runs every 7 items."""
        mock_config.return_value = _make_default_config()
        session_stats = SessionStats(agent_stats=AgentStats())
        run_logger = Mock()
        mock_maintenance.return_value = None
        
        run_periodic_maintenance(7, session_stats, run_logger)
        
        # Check Backlog Cleanup was called
        backlog_calls = [call for call in mock_maintenance.call_args_list 
                         if call[0][0] == "Backlog Cleanup"]
        
        assert len(backlog_calls) == 1
        assert session_stats.backlog_cleanup_agent_runs == 1

    @patch('pokepoke.maintenance.get_config')
    @patch('pokepoke.maintenance.run_maintenance_agent')
    @patch('pokepoke.agent_runner.run_beta_tester')
    @patch('pokepoke.agent_runner.run_worktree_cleanup')
    @patch('pokepoke.maintenance.set_terminal_banner')
    @patch('pokepoke.maintenance.ui')
    def test_aggregates_stats_from_successful_agents(
        self,
        mock_ui: Mock,
        mock_banner: Mock,
        mock_worktree_cleanup: Mock,
        mock_beta_tester: Mock,
        mock_maintenance: Mock,
        mock_config: Mock
    ) -> None:
        """Test that stats are aggregated from successful agent runs."""
        mock_config.return_value = _make_default_config()
        session_stats = SessionStats(agent_stats=AgentStats())
        run_logger = Mock()
        
        # Return stats from maintenance agent (Janitor runs at 2)
        mock_maintenance.return_value = AgentStats(
            wall_duration=10.0,
            input_tokens=100,
            lines_removed=50
        )
        
        run_periodic_maintenance(2, session_stats, run_logger)
        
        # Stats should be aggregated
        assert session_stats.agent_stats.wall_duration == 10.0
        assert session_stats.agent_stats.input_tokens == 100
        assert session_stats.janitor_lines_removed == 50

    @patch('pokepoke.maintenance.get_config')
    @patch('pokepoke.maintenance.run_maintenance_agent')
    @patch('pokepoke.agent_runner.run_beta_tester')
    @patch('pokepoke.agent_runner.run_worktree_cleanup')
    @patch('pokepoke.maintenance.set_terminal_banner')
    @patch('pokepoke.maintenance.ui')
    def test_handles_failed_agents_gracefully(
        self,
        mock_ui: Mock,
        mock_banner: Mock,
        mock_worktree_cleanup: Mock,
        mock_beta_tester: Mock,
        mock_maintenance: Mock,
        mock_config: Mock
    ) -> None:
        """Test that None return from agents is handled."""
        mock_config.return_value = _make_default_config()
        session_stats = SessionStats(agent_stats=AgentStats())
        run_logger = Mock()
        
        # All agents return None (failure)
        mock_maintenance.return_value = None
        mock_beta_tester.return_value = None
        mock_worktree_cleanup.return_value = None
        
        # Should not raise
        run_periodic_maintenance(10, session_stats, run_logger)
        
        # Counts should still be updated
        assert session_stats.janitor_agent_runs == 1
        assert session_stats.tech_debt_agent_runs == 1

    @patch('pokepoke.maintenance.get_config')
    @patch('pokepoke.maintenance.run_maintenance_agent')
    @patch('pokepoke.agent_runner.run_beta_tester')
    @patch('pokepoke.agent_runner.run_worktree_cleanup')
    @patch('pokepoke.maintenance.set_terminal_banner')
    @patch('pokepoke.maintenance.ui')
    def test_logs_maintenance_events(
        self,
        mock_ui: Mock,
        mock_banner: Mock,
        mock_worktree_cleanup: Mock,
        mock_beta_tester: Mock,
        mock_maintenance: Mock,
        mock_config: Mock
    ) -> None:
        """Test that maintenance events are logged."""
        mock_config.return_value = _make_default_config()
        session_stats = SessionStats(agent_stats=AgentStats())
        run_logger = Mock()
        mock_maintenance.return_value = AgentStats()
        
        run_periodic_maintenance(2, session_stats, run_logger)
        
        # Should have logged start and completion
        log_calls = run_logger.log_maintenance.call_args_list
        assert len(log_calls) >= 2  # At least start and end

    @patch('pokepoke.maintenance.get_config')
    @patch('pokepoke.maintenance.run_maintenance_agent')
    @patch('pokepoke.agent_runner.run_beta_tester')
    @patch('pokepoke.agent_runner.run_worktree_cleanup')
    @patch('pokepoke.maintenance.set_terminal_banner')
    @patch('pokepoke.maintenance.ui')
    def test_multiple_agents_at_same_interval(
        self,
        mock_ui: Mock,
        mock_banner: Mock,
        mock_worktree_cleanup: Mock,
        mock_beta_tester: Mock,
        mock_maintenance: Mock,
        mock_config: Mock
    ) -> None:
        """Test that multiple agents can run at the same interval."""
        mock_config.return_value = _make_default_config()
        session_stats = SessionStats(agent_stats=AgentStats())
        run_logger = Mock()
        mock_maintenance.return_value = None
        mock_beta_tester.return_value = None
        mock_worktree_cleanup.return_value = None
        
        # At 6: Janitor (2), Beta Tester (3), Backlog Cleanup (7-no)
        run_periodic_maintenance(6, session_stats, run_logger)
        
        assert session_stats.janitor_agent_runs == 1
        assert session_stats.beta_tester_agent_runs == 1
        mock_beta_tester.assert_called_once()

    @patch('pokepoke.maintenance.get_config')
    @patch('pokepoke.maintenance.run_maintenance_agent')
    @patch('pokepoke.agent_runner.run_beta_tester')
    @patch('pokepoke.agent_runner.run_worktree_cleanup')
    @patch('pokepoke.maintenance.set_terminal_banner')
    @patch('pokepoke.maintenance.ui')
    def test_code_review_uses_specific_model(
        self,
        mock_ui: Mock,
        mock_banner: Mock,
        mock_worktree_cleanup: Mock,
        mock_beta_tester: Mock,
        mock_maintenance: Mock,
        mock_config: Mock
    ) -> None:
        """Test that Code Review agent uses gpt-5.1-codex model."""
        mock_config.return_value = _make_default_config()
        session_stats = SessionStats(agent_stats=AgentStats())
        run_logger = Mock()
        mock_maintenance.return_value = None
        
        run_periodic_maintenance(5, session_stats, run_logger)
        
        # Find the Code Review call
        code_review_calls = [call for call in mock_maintenance.call_args_list 
                             if call[0][0] == "Code Review"]
        assert len(code_review_calls) == 1
        
        # Check that model parameter was passed
        call_kwargs = code_review_calls[0][1]
        assert call_kwargs.get('model') == "gpt-5.1-codex"

    @patch('pokepoke.maintenance.get_config')
    @patch('pokepoke.maintenance.run_maintenance_agent')
    @patch('pokepoke.agent_runner.run_beta_tester')
    @patch('pokepoke.agent_runner.run_worktree_cleanup')
    @patch('pokepoke.maintenance.set_terminal_banner')
    @patch('pokepoke.maintenance.ui')
    def test_backlog_cleanup_does_not_merge(
        self,
        mock_ui: Mock,
        mock_banner: Mock,
        mock_worktree_cleanup: Mock,
        mock_beta_tester: Mock,
        mock_maintenance: Mock,
        mock_config: Mock
    ) -> None:
        """Test that Backlog Cleanup runs with merge_changes=False."""
        mock_config.return_value = _make_default_config()
        session_stats = SessionStats(agent_stats=AgentStats())
        run_logger = Mock()
        mock_maintenance.return_value = None
        
        run_periodic_maintenance(7, session_stats, run_logger)
        
        # Find the Backlog Cleanup call
        backlog_calls = [call for call in mock_maintenance.call_args_list 
                         if call[0][0] == "Backlog Cleanup"]
        assert len(backlog_calls) == 1
        
        # Check that merge_changes=False was passed
        call_kwargs = backlog_calls[0][1]
        assert call_kwargs.get('merge_changes') is False

    @patch('pokepoke.maintenance.get_config')
    @patch('pokepoke.maintenance.run_maintenance_agent')
    @patch('pokepoke.maintenance._run_special_agent')
    @patch('pokepoke.maintenance.set_terminal_banner')
    @patch('pokepoke.maintenance.ui')
    def test_disabled_agent_is_skipped(
        self,
        mock_ui: Mock,
        mock_banner: Mock,
        mock_special: Mock,
        mock_maintenance: Mock,
        mock_config: Mock
    ) -> None:
        """Test that disabled agents are not run."""
        config = ProjectConfig()
        config.maintenance = MaintenanceConfig(agents=[
            MaintenanceAgentConfig(
                name="Janitor", prompt_file="janitor.md",
                frequency=2, enabled=False,
            ),
        ])
        mock_config.return_value = config
        session_stats = SessionStats(agent_stats=AgentStats())
        run_logger = Mock()

        run_periodic_maintenance(2, session_stats, run_logger)

        mock_maintenance.assert_not_called()
        mock_special.assert_not_called()

    @patch('pokepoke.maintenance.get_config')
    @patch('pokepoke.maintenance.run_maintenance_agent')
    @patch('pokepoke.maintenance._run_special_agent')
    @patch('pokepoke.maintenance.set_terminal_banner')
    @patch('pokepoke.maintenance.ui')
    def test_custom_frequency_from_config(
        self,
        mock_ui: Mock,
        mock_banner: Mock,
        mock_special: Mock,
        mock_maintenance: Mock,
        mock_config: Mock
    ) -> None:
        """Test that custom frequency from config is respected."""
        config = ProjectConfig()
        config.maintenance = MaintenanceConfig(agents=[
            MaintenanceAgentConfig(
                name="Tech Debt", prompt_file="tech-debt.md",
                frequency=10, needs_worktree=False,
            ),
        ])
        mock_config.return_value = config
        mock_maintenance.return_value = None
        session_stats = SessionStats(agent_stats=AgentStats())
        run_logger = Mock()

        # Should NOT run at 5 (default was 5, but now 10)
        run_periodic_maintenance(5, session_stats, run_logger)
        mock_maintenance.assert_not_called()

        # Should run at 10
        run_periodic_maintenance(10, session_stats, run_logger)
        calls = [c for c in mock_maintenance.call_args_list if c[0][0] == "Tech Debt"]
        assert len(calls) == 1
