"""Tests for MaintenanceScheduler singleton coordination."""

import threading
import time
from unittest.mock import Mock, patch, MagicMock
import pytest

from pokepoke.maintenance_scheduler import (
    MaintenanceScheduler, 
    get_maintenance_scheduler, 
    run_periodic_maintenance,
    _SINGLETON_AGENTS,
    _PARALLEL_SAFE_AGENTS
)
from pokepoke.types import AgentStats, SessionStats
from pokepoke.config import MaintenanceConfig, MaintenanceAgentConfig, ProjectConfig


def _make_default_config() -> ProjectConfig:
    """Create a ProjectConfig with default maintenance agents."""
    config = ProjectConfig()
    config.maintenance = MaintenanceConfig.defaults()
    return config


class TestMaintenanceScheduler:
    """Test MaintenanceScheduler class."""
    
    def test_init_creates_empty_locks(self):
        """Test that scheduler initializes with empty lock dict."""
        scheduler = MaintenanceScheduler()
        assert scheduler._locks == {}
    
    def test_get_agent_lock_creates_new_lock(self):
        """Test that getting a lock creates it if it doesn't exist."""
        scheduler = MaintenanceScheduler()
        
        lock = scheduler._get_agent_lock("Janitor")
        
        assert isinstance(lock, threading.Lock)
        assert "Janitor" in scheduler._locks
        assert scheduler._locks["Janitor"] is lock
    
    def test_get_agent_lock_returns_same_lock(self):
        """Test that getting the same lock twice returns the same instance."""
        scheduler = MaintenanceScheduler()
        
        lock1 = scheduler._get_agent_lock("Janitor")
        lock2 = scheduler._get_agent_lock("Janitor")
        
        assert lock1 is lock2
    
    def test_get_agent_lock_thread_safe(self):
        """Test that lock creation is thread-safe."""
        scheduler = MaintenanceScheduler()
        locks_created = []
        
        def create_lock(name: str):
            lock = scheduler._get_agent_lock(name)
            locks_created.append(lock)
        
        # Create multiple threads trying to create the same lock
        threads = []
        for _ in range(5):
            t = threading.Thread(target=create_lock, args=("Janitor",))
            threads.append(t)
            t.start()
        
        # Wait for all threads
        for t in threads:
            t.join()
        
        # All should have gotten the same lock instance
        assert len(locks_created) == 5
        assert all(lock is locks_created[0] for lock in locks_created)
    
    @patch('pokepoke.maintenance_scheduler.get_config')
    def test_maybe_run_maintenance_skips_zero_items(self, mock_config):
        """Test that no agents run when items_completed is 0."""
        mock_config.return_value = _make_default_config()
        scheduler = MaintenanceScheduler()
        session_stats = SessionStats(agent_stats=AgentStats())
        run_logger = Mock()
        
        with patch.object(scheduler, '_maybe_run_agent') as mock_run:
            scheduler.maybe_run_maintenance(0, session_stats, run_logger)
            mock_run.assert_not_called()
    
    @patch('pokepoke.maintenance_scheduler.get_config')
    def test_maybe_run_maintenance_respects_frequency(self, mock_config):
        """Test that agents only run at their configured frequency."""
        mock_config.return_value = _make_default_config()
        scheduler = MaintenanceScheduler()
        session_stats = SessionStats(agent_stats=AgentStats())
        run_logger = Mock()
        
        with patch.object(scheduler, '_maybe_run_agent') as mock_run:
            # Janitor runs every 2 items
            scheduler.maybe_run_maintenance(1, session_stats, run_logger)  # Not due
            assert not any("Janitor" in str(call) for call in mock_run.call_args_list)
            
            mock_run.reset_mock()
            scheduler.maybe_run_maintenance(2, session_stats, run_logger)  # Due
            assert any("Janitor" in str(call) for call in mock_run.call_args_list)
    
    @patch('pokepoke.maintenance_scheduler.get_config')
    def test_maybe_run_maintenance_skips_disabled_agents(self, mock_config):
        """Test that disabled agents are skipped."""
        config = ProjectConfig()
        config.maintenance = MaintenanceConfig(agents=[
            MaintenanceAgentConfig(
                name="Janitor", prompt_file="janitor.md",
                frequency=2, enabled=False,
            ),
        ])
        mock_config.return_value = config
        scheduler = MaintenanceScheduler()
        session_stats = SessionStats(agent_stats=AgentStats())
        run_logger = Mock()
        
        with patch.object(scheduler, '_maybe_run_agent') as mock_run:
            scheduler.maybe_run_maintenance(2, session_stats, run_logger)
            mock_run.assert_not_called()


class TestSingletonCoordination:
    """Test singleton coordination logic."""
    
    @patch('pokepoke.maintenance_scheduler.try_lock')
    @patch('pokepoke.maintenance_scheduler._run_special_agent')
    def test_singleton_agent_skips_when_thread_locked(self, mock_special, mock_file_lock):
        """Test that singleton agent skips when thread lock is held."""
        scheduler = MaintenanceScheduler()
        agent_cfg = MaintenanceAgentConfig(name="Janitor", prompt_file="janitor.md", frequency=2)
        session_stats = SessionStats(agent_stats=AgentStats())
        run_logger = Mock()
        
        # Acquire the thread lock manually
        lock = scheduler._get_agent_lock("Janitor")
        lock.acquire()
        
        try:
            scheduler._maybe_run_agent("Janitor", agent_cfg, Mock(), session_stats, run_logger)
            
            # Should skip and log
            run_logger.log_maintenance.assert_called_with(
                "janitor", "Skipping Janitor Agent - already running in this process"
            )
            mock_file_lock.assert_not_called()
            mock_special.assert_not_called()
        finally:
            lock.release()
    
    @patch('pokepoke.maintenance_scheduler.try_lock')
    @patch('pokepoke.maintenance_scheduler._run_special_agent')
    def test_singleton_agent_skips_when_file_locked(self, mock_special, mock_file_lock):
        """Test that singleton agent skips when file lock is held."""
        mock_file_lock.return_value = None  # Lock held by another process
        
        scheduler = MaintenanceScheduler()
        agent_cfg = MaintenanceAgentConfig(name="Janitor", prompt_file="janitor.md", frequency=2)
        session_stats = SessionStats(agent_stats=AgentStats())
        run_logger = Mock()
        
        scheduler._maybe_run_agent("Janitor", agent_cfg, Mock(), session_stats, run_logger)
        
        # Should skip and log
        run_logger.log_maintenance.assert_called_with(
            "janitor", "Skipping Janitor Agent - already running in another process"
        )
        mock_special.assert_not_called()
    
    @patch('pokepoke.maintenance_scheduler.try_lock')
    @patch('pokepoke.maintenance_scheduler._run_special_agent')
    def test_singleton_agent_runs_when_locks_available(self, mock_special, mock_file_lock):
        """Test that singleton agent runs when both locks are available."""
        mock_file_lock.return_value = Mock()  # Lock acquired
        mock_special.return_value = AgentStats()
        
        scheduler = MaintenanceScheduler()
        agent_cfg = MaintenanceAgentConfig(name="Janitor", prompt_file="janitor.md", frequency=2)
        session_stats = SessionStats(agent_stats=AgentStats())
        run_logger = Mock()
        
        with patch.object(scheduler, '_run_agent_with_coordination') as mock_run:
            scheduler._maybe_run_agent("Janitor", agent_cfg, Mock(), session_stats, run_logger)
            mock_run.assert_called_once()
    
    @patch('pokepoke.maintenance_scheduler.run_maintenance_agent')
    def test_parallel_safe_agent_runs_without_locking(self, mock_maintenance):
        """Test that parallel-safe agents run without lock coordination."""
        mock_maintenance.return_value = AgentStats()
        
        scheduler = MaintenanceScheduler()
        agent_cfg = MaintenanceAgentConfig(name="Tech Debt", prompt_file="tech-debt.md", frequency=5)
        session_stats = SessionStats(agent_stats=AgentStats())
        run_logger = Mock()
        
        with patch.object(scheduler, '_run_agent_with_coordination') as mock_run:
            scheduler._maybe_run_agent("Tech Debt", agent_cfg, Mock(), session_stats, run_logger)
            mock_run.assert_called_once()
    
    def test_unknown_agent_gets_singleton_protection(self):
        """Test that unknown agents get singleton protection as a safety measure."""
        scheduler = MaintenanceScheduler()
        agent_cfg = MaintenanceAgentConfig(name="Unknown Agent", prompt_file="unknown.md", frequency=5)
        session_stats = SessionStats(agent_stats=AgentStats())
        run_logger = Mock()
        
        with patch('pokepoke.maintenance_scheduler.try_lock') as mock_lock:
            with patch.object(scheduler, '_run_agent_with_coordination') as mock_run:
                mock_lock.return_value = Mock()  # Lock available
                
                scheduler._maybe_run_agent("Unknown Agent", agent_cfg, Mock(), session_stats, run_logger)
                
                # Should log warning and then run with coordination
                run_logger.log_maintenance.assert_called_with(
                    "unknown_agent", "WARNING: Unknown agent classification for Unknown Agent, applying singleton guard"
                )
                mock_run.assert_called_once()


class TestRunAgentWithCoordination:
    """Test agent execution and statistics coordination."""
    
    @patch('pokepoke.maintenance_scheduler.set_terminal_banner')
    @patch('pokepoke.maintenance_scheduler.terminal_ui')
    @patch('pokepoke.maintenance_scheduler._run_special_agent')
    @patch('pokepoke.maintenance_scheduler.aggregate_stats')
    def test_runs_special_agent(self, mock_aggregate, mock_special, mock_ui, mock_banner):
        """Test that special agents use their dedicated runners."""
        mock_special.return_value = AgentStats(input_tokens=100)
        
        scheduler = MaintenanceScheduler()
        agent_cfg = MaintenanceAgentConfig(name="Beta Tester", prompt_file="beta-tester.md", frequency=3)
        session_stats = SessionStats(agent_stats=AgentStats())
        run_logger = Mock()
        pokepoke_repo = Mock()
        
        scheduler._run_agent_with_coordination("Beta Tester", agent_cfg, pokepoke_repo, session_stats, run_logger)
        
        mock_special.assert_called_once_with("Beta Tester", pokepoke_repo)
        assert session_stats.beta_tester_agent_runs == 1
        mock_aggregate.assert_called_once_with(session_stats, AgentStats(input_tokens=100))
    
    @patch('pokepoke.maintenance_scheduler.set_terminal_banner')
    @patch('pokepoke.maintenance_scheduler.terminal_ui')
    @patch('pokepoke.maintenance_scheduler.run_maintenance_agent')
    @patch('pokepoke.maintenance_scheduler.aggregate_stats')
    def test_runs_generic_agent(self, mock_aggregate, mock_maintenance, mock_ui, mock_banner):
        """Test that generic agents use run_maintenance_agent."""
        mock_maintenance.return_value = AgentStats(input_tokens=50)
        
        scheduler = MaintenanceScheduler()
        agent_cfg = MaintenanceAgentConfig(
            name="Janitor", 
            prompt_file="janitor.md", 
            frequency=2,
            needs_worktree=True,
            merge_changes=True,
            model="claude-opus-4.6"
        )
        session_stats = SessionStats(agent_stats=AgentStats())
        run_logger = Mock()
        pokepoke_repo = Mock()
        
        scheduler._run_agent_with_coordination("Janitor", agent_cfg, pokepoke_repo, session_stats, run_logger)
        
        mock_maintenance.assert_called_once_with(
            "Janitor",
            "janitor.md", 
            repo_root=pokepoke_repo,
            needs_worktree=True,
            merge_changes=True,
            model="claude-opus-4.6"
        )
        assert session_stats.janitor_agent_runs == 1
        mock_aggregate.assert_called_once_with(session_stats, AgentStats(input_tokens=50))
    
    @patch('pokepoke.maintenance_scheduler.set_terminal_banner')
    @patch('pokepoke.maintenance_scheduler.terminal_ui')
    @patch('pokepoke.maintenance_scheduler.run_maintenance_agent')
    def test_handles_janitor_special_stats(self, mock_maintenance, mock_ui, mock_banner):
        """Test that Janitor agent gets special lines_removed tracking."""
        mock_maintenance.return_value = AgentStats(lines_removed=25)
        
        scheduler = MaintenanceScheduler()
        agent_cfg = MaintenanceAgentConfig(name="Janitor", prompt_file="janitor.md", frequency=2)
        session_stats = SessionStats(agent_stats=AgentStats())
        run_logger = Mock()
        
        scheduler._run_agent_with_coordination("Janitor", agent_cfg, Mock(), session_stats, run_logger)
        
        assert session_stats.janitor_lines_removed == 25
        assert session_stats.agent_stats.lines_removed == 25  # Also aggregated
    
    @patch('pokepoke.maintenance_scheduler.set_terminal_banner')
    @patch('pokepoke.maintenance_scheduler.terminal_ui')
    @patch('pokepoke.maintenance_scheduler.run_maintenance_agent')
    def test_handles_failed_agent(self, mock_maintenance, mock_ui, mock_banner):
        """Test that failed agents (returning None) are handled gracefully."""
        mock_maintenance.return_value = None
        
        scheduler = MaintenanceScheduler()
        agent_cfg = MaintenanceAgentConfig(name="Janitor", prompt_file="janitor.md", frequency=2)
        session_stats = SessionStats(agent_stats=AgentStats())
        run_logger = Mock()
        
        # Should not raise exception
        scheduler._run_agent_with_coordination("Janitor", agent_cfg, Mock(), session_stats, run_logger)
        
        run_logger.log_maintenance.assert_any_call("janitor", "Janitor Agent failed")
        assert session_stats.janitor_agent_runs == 1  # Count still incremented


class TestGlobalScheduler:
    """Test global scheduler singleton."""
    
    def test_get_maintenance_scheduler_returns_same_instance(self):
        """Test that get_maintenance_scheduler returns the same instance."""
        scheduler1 = get_maintenance_scheduler()
        scheduler2 = get_maintenance_scheduler()
        
        assert scheduler1 is scheduler2
    
    def test_get_maintenance_scheduler_creates_instance(self):
        """Test that get_maintenance_scheduler creates a MaintenanceScheduler."""
        scheduler = get_maintenance_scheduler()
        assert isinstance(scheduler, MaintenanceScheduler)


class TestBackwardCompatibility:
    """Test backward compatibility with existing maintenance.py interface."""
    
    @patch('pokepoke.maintenance_scheduler.get_maintenance_scheduler')
    def test_run_periodic_maintenance_delegates_to_scheduler(self, mock_get_scheduler):
        """Test that the module-level function delegates to scheduler."""
        mock_scheduler = Mock()
        mock_get_scheduler.return_value = mock_scheduler
        
        session_stats = SessionStats(agent_stats=AgentStats())
        run_logger = Mock()
        
        run_periodic_maintenance(5, session_stats, run_logger)
        
        mock_scheduler.maybe_run_maintenance.assert_called_once_with(5, session_stats, run_logger)


class TestAgentClassification:
    """Test agent classification constants."""
    
    def test_singleton_agents_defined(self):
        """Test that singleton agents are properly defined."""
        expected_singleton = {"Beta Tester", "Janitor", "Backlog Cleanup", "Worktree Cleanup"}
        assert _SINGLETON_AGENTS == expected_singleton
    
    def test_parallel_safe_agents_defined(self):
        """Test that parallel-safe agents are properly defined."""
        expected_parallel = {"Tech Debt", "Code Review"}
        assert _PARALLEL_SAFE_AGENTS == expected_parallel
    
    def test_no_overlap_in_classifications(self):
        """Test that singleton and parallel-safe sets don't overlap."""
        assert len(_SINGLETON_AGENTS & _PARALLEL_SAFE_AGENTS) == 0


class TestConcurrentExecution:
    """Test concurrent execution scenarios."""
    
    def test_multiple_parallel_safe_agents_can_run_simultaneously(self):
        """Test that multiple Tech Debt agents can run at the same time."""
        scheduler = MaintenanceScheduler()
        
        results = []
        errors = []
        
        def run_agent(agent_name: str):
            try:
                with patch('pokepoke.maintenance_scheduler.run_maintenance_agent') as mock_run:
                    with patch('pokepoke.maintenance_scheduler.set_terminal_banner'):
                        with patch('pokepoke.maintenance_scheduler.terminal_ui'):
                            mock_run.return_value = AgentStats()
                            
                            agent_cfg = MaintenanceAgentConfig(name=agent_name, prompt_file=f"{agent_name.lower().replace(' ', '-')}.md", frequency=1)
                            session_stats = SessionStats(agent_stats=AgentStats())
                            run_logger = Mock()
                            
                            scheduler._maybe_run_agent(agent_name, agent_cfg, Mock(), session_stats, run_logger)
                            results.append(f"{agent_name}_completed")
            except Exception as e:
                errors.append(str(e))
        
        # Start multiple Tech Debt agents simultaneously  
        threads = []
        for i in range(3):
            t = threading.Thread(target=run_agent, args=("Tech Debt",))
            threads.append(t)
            t.start()
        
        # Wait for completion
        for t in threads:
            t.join()
        
        # All should complete successfully
        assert len(errors) == 0
        assert len(results) == 3
    
    def test_singleton_agents_block_each_other(self):
        """Test that singleton agents block each other from running simultaneously."""
        scheduler = MaintenanceScheduler()
        
        results = []
        skipped_messages = []
        
        def run_janitor():
            with patch('pokepoke.maintenance_scheduler.run_maintenance_agent') as mock_run:
                with patch('pokepoke.maintenance_scheduler.try_lock') as mock_lock:
                    with patch('pokepoke.maintenance_scheduler.set_terminal_banner'):
                        with patch('pokepoke.maintenance_scheduler.terminal_ui'):
                            mock_run.return_value = AgentStats()
                            mock_lock.return_value = Mock()  # File lock available
                            
                            agent_cfg = MaintenanceAgentConfig(name="Janitor", prompt_file="janitor.md", frequency=1)
                            session_stats = SessionStats(agent_stats=AgentStats())
                            
                            # Capture log messages
                            run_logger = Mock()
                            
                            scheduler._maybe_run_agent("Janitor", agent_cfg, Mock(), session_stats, run_logger)
                            
                            # Check if this run was skipped
                            if any("already running in this process" in str(call) for call in run_logger.log_maintenance.call_args_list):
                                skipped_messages.append("skipped")
                            else:
                                results.append("janitor_completed")
        
        # Get the lock for Janitor upfront to ensure blocking
        lock = scheduler._get_agent_lock("Janitor") 
        lock.acquire()
        
        try:
            # Start multiple Janitor agents simultaneously - they should all be blocked
            threads = []
            for i in range(3):
                t = threading.Thread(target=run_janitor)
                threads.append(t) 
                t.start()
            
            # Wait for completion with reasonable timeout
            for t in threads:
                t.join(timeout=1.0)
        finally:
            lock.release()
        
        # All should be skipped because lock was held
        assert len(results) == 0  # None should complete
        assert len(skipped_messages) == 3  # All should be skipped