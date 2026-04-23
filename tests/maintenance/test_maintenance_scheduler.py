"""Tests for MaintenanceScheduler singleton coordination."""

import threading
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from pokepoke.config import MaintenanceAgentConfig, MaintenanceConfig, ProjectConfig
from pokepoke.maintenance.maintenance_scheduler import (
    _EXCLUSIVE_AGENTS,
    _PARALLEL_SAFE_AGENTS,
    _SINGLETON_AGENTS,
    MaintenanceScheduler,
    get_maintenance_scheduler,
    run_periodic_maintenance,
)
from pokepoke.types import AgentStats, SessionStats


@pytest.fixture(autouse=True)
def _force_repo_clean(monkeypatch):
    """Ensure repo state guard always reports clean unless overridden."""
    monkeypatch.setattr(
        "pokepoke.maintenance.maintenance_scheduler.wait_for_main_repo_clean",
        lambda *_, **__: True,
    )


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

        assert hasattr(lock, 'acquire') and hasattr(lock, 'release')
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

    @patch("pokepoke.maintenance.maintenance_scheduler.get_config")
    def test_maybe_run_maintenance_skips_zero_items(self, mock_config):
        """Test that no agents run when items_completed is 0."""
        mock_config.return_value = _make_default_config()
        scheduler = MaintenanceScheduler()
        session_stats = SessionStats(agent_stats=AgentStats())
        run_logger = Mock()

        with patch.object(scheduler, '_maybe_run_agent') as mock_run:
            scheduler.maybe_run_maintenance(0, session_stats, run_logger)
            mock_run.assert_not_called()

    @patch("pokepoke.maintenance.maintenance_scheduler.get_config")
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

    @patch("pokepoke.maintenance.maintenance_scheduler.get_config")
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

    @patch("pokepoke.maintenance.maintenance_scheduler.terminal_ui")
    @patch("pokepoke.maintenance.maintenance_scheduler.get_config")
    def test_maybe_run_maintenance_skips_paused_agents(self, mock_config, mock_terminal_ui):
        """Test that paused agents are skipped during scheduling."""
        config = ProjectConfig()
        config.maintenance = MaintenanceConfig(agents=[
            MaintenanceAgentConfig(
                name="Janitor", prompt_file="janitor.md",
                frequency=2, enabled=True,
            ),
        ])
        mock_config.return_value = config
        mock_terminal_ui.ui.is_agent_paused.return_value = True
        scheduler = MaintenanceScheduler()
        session_stats = SessionStats(agent_stats=AgentStats())
        run_logger = Mock()

        with patch.object(scheduler, '_maybe_run_agent') as mock_run:
            scheduler.maybe_run_maintenance(2, session_stats, run_logger)
            mock_run.assert_not_called()
            run_logger.log_maintenance.assert_called_with(
                "janitor", "Skipping Janitor Agent - paused by user"
            )

    @patch("pokepoke.maintenance.maintenance_scheduler.wait_for_main_repo_clean")
    @patch("pokepoke.maintenance.maintenance_scheduler.terminal_ui")
    @patch("pokepoke.maintenance.maintenance_scheduler.get_config")
    def test_repo_clean_checked_once_for_entire_batch(self, mock_config, mock_terminal_ui, mock_wait):
        """wait_for_main_repo_clean must be called exactly once regardless of agent count."""
        mock_wait.return_value = True
        mock_terminal_ui.ui.is_agent_paused.return_value = False
        config = ProjectConfig()
        config.maintenance = MaintenanceConfig(agents=[
            MaintenanceAgentConfig(name="Janitor", prompt_file="janitor.md", frequency=2, enabled=True),
            MaintenanceAgentConfig(name="Backlog Cleanup", prompt_file="backlog.md", frequency=2, enabled=True),
            MaintenanceAgentConfig(name="Code Review", prompt_file="code-review.md", frequency=2, enabled=True),
            MaintenanceAgentConfig(name="Worktree Cleanup", prompt_file="worktree-cleanup.md", frequency=2, enabled=True),
        ])
        mock_config.return_value = config
        scheduler = MaintenanceScheduler()
        session_stats = SessionStats(agent_stats=AgentStats())
        run_logger = Mock()

        with patch.object(scheduler, '_maybe_run_agent'):
            scheduler.maybe_run_maintenance(2, session_stats, run_logger)

        # Must be called exactly once — not once per agent
        mock_wait.assert_called_once()

    @patch("pokepoke.maintenance.maintenance_scheduler.terminal_ui")
    @patch("pokepoke.maintenance.maintenance_scheduler.get_config")
    def test_maybe_run_maintenance_stops_mid_loop_on_shutdown(self, mock_config, mock_terminal_ui):
        """Test that agent dispatch stops when shutdown is requested mid-loop."""
        mock_terminal_ui.ui.is_agent_paused.return_value = False
        config = ProjectConfig()
        config.maintenance = MaintenanceConfig(agents=[
            MaintenanceAgentConfig(name="Tech Debt", prompt_file="tech-debt.md", frequency=2, enabled=True),
            MaintenanceAgentConfig(name="Code Review", prompt_file="code-review.md", frequency=2, enabled=True),
        ])
        mock_config.return_value = config
        scheduler = MaintenanceScheduler()
        session_stats = SessionStats(agent_stats=AgentStats())
        run_logger = Mock()

        with (
            patch.object(scheduler, '_maybe_run_agent') as mock_run,
            patch("pokepoke.utils.shutdown.is_shutting_down", return_value=True),
            patch("pokepoke.utils.shutdown.should_stop_after_current", return_value=False),
        ):
            scheduler.maybe_run_maintenance(2, session_stats, run_logger)
            mock_run.assert_not_called()

    @patch("pokepoke.maintenance.maintenance_scheduler.terminal_ui")
    @patch("pokepoke.maintenance.maintenance_scheduler.get_config")
    def test_maybe_run_maintenance_stops_mid_loop_on_stop_after_current(self, mock_config, mock_terminal_ui):
        """Test that agent dispatch stops when stop-after-current is requested mid-loop."""
        mock_terminal_ui.ui.is_agent_paused.return_value = False
        config = ProjectConfig()
        config.maintenance = MaintenanceConfig(agents=[
            MaintenanceAgentConfig(name="Tech Debt", prompt_file="tech-debt.md", frequency=2, enabled=True),
            MaintenanceAgentConfig(name="Code Review", prompt_file="code-review.md", frequency=2, enabled=True),
        ])
        mock_config.return_value = config
        scheduler = MaintenanceScheduler()
        session_stats = SessionStats(agent_stats=AgentStats())
        run_logger = Mock()

        with (
            patch.object(scheduler, '_maybe_run_agent') as mock_run,
            patch("pokepoke.utils.shutdown.is_shutting_down", return_value=False),
            patch("pokepoke.utils.shutdown.should_stop_after_current", return_value=True),
        ):
            scheduler.maybe_run_maintenance(2, session_stats, run_logger)
            mock_run.assert_not_called()
    @patch('pokepoke.utils.shutdown.is_shutting_down', return_value=True)
    @patch('pokepoke.utils.shutdown.should_stop_after_current', return_value=False)
    def test_maybe_run_agent_skips_when_shutting_down(self, _mock_stop, _mock_shutdown):
        """Test that _maybe_run_agent skips when orchestrator is shutting down."""
        scheduler = MaintenanceScheduler()
        agent_cfg = MaintenanceAgentConfig(name="Tech Debt", prompt_file="tech-debt.md", frequency=2)
        session_stats = SessionStats(agent_stats=AgentStats())
        run_logger = Mock()

        with patch.object(scheduler, '_run_agent_with_coordination') as mock_run:
            scheduler._maybe_run_agent("Tech Debt", agent_cfg, Mock(), session_stats, run_logger)
            mock_run.assert_not_called()

        run_logger.log_maintenance.assert_called_with(
            "tech_debt", "Skipping Tech Debt Agent - orchestrator is stopping"
        )

    @patch('pokepoke.utils.shutdown.is_shutting_down', return_value=False)
    @patch('pokepoke.utils.shutdown.should_stop_after_current', return_value=True)
    def test_maybe_run_agent_skips_when_stop_after_current(self, _mock_stop, _mock_shutdown):
        """Test that _maybe_run_agent skips when stop-after-current is requested."""
        scheduler = MaintenanceScheduler()
        agent_cfg = MaintenanceAgentConfig(name="Janitor", prompt_file="janitor.md", frequency=2)
        session_stats = SessionStats(agent_stats=AgentStats())
        run_logger = Mock()

        with patch.object(scheduler, '_run_with_singleton_guard') as mock_run:
            scheduler._maybe_run_agent("Janitor", agent_cfg, Mock(), session_stats, run_logger)
            mock_run.assert_not_called()

        run_logger.log_maintenance.assert_called_with(
            "janitor", "Skipping Janitor Agent - orchestrator is stopping"
        )

    @patch('pokepoke.utils.shutdown.is_shutting_down', return_value=True)
    @patch('pokepoke.utils.shutdown.should_stop_after_current', return_value=False)
    def test_run_agent_with_coordination_skips_when_shutting_down(self, _mock_stop, _mock_shutdown):
        """Test that _run_agent_with_coordination skips when orchestrator is shutting down."""
        scheduler = MaintenanceScheduler()
        agent_cfg = MaintenanceAgentConfig(name="Tech Debt", prompt_file="tech-debt.md", frequency=2)
        session_stats = SessionStats(agent_stats=AgentStats())
        run_logger = Mock()

        with patch('pokepoke.maintenance.maintenance_scheduler.run_maintenance_agent') as mock_agent:
            scheduler._run_agent_with_coordination("Tech Debt", agent_cfg, Mock(), session_stats, run_logger)
            mock_agent.assert_not_called()

        run_logger.log_maintenance.assert_called_with(
            "tech_debt", "Skipping Tech Debt Agent - orchestrator is stopping"
        )

    @patch('pokepoke.utils.shutdown.is_shutting_down', return_value=False)
    @patch('pokepoke.utils.shutdown.should_stop_after_current', return_value=True)
    def test_run_agent_with_coordination_skips_when_stop_after_current(self, _mock_stop, _mock_shutdown):
        """Test that _run_agent_with_coordination skips when stop-after-current is requested."""
        scheduler = MaintenanceScheduler()
        agent_cfg = MaintenanceAgentConfig(name="Janitor", prompt_file="janitor.md", frequency=2)
        session_stats = SessionStats(agent_stats=AgentStats())
        run_logger = Mock()

        with patch('pokepoke.maintenance.maintenance_scheduler._run_special_agent') as mock_agent:
            scheduler._run_agent_with_coordination("Janitor", agent_cfg, Mock(), session_stats, run_logger)
            mock_agent.assert_not_called()

        run_logger.log_maintenance.assert_called_with(
            "janitor", "Skipping Janitor Agent - orchestrator is stopping"
        )

    """Test singleton coordination logic."""

    @patch('pokepoke.maintenance.maintenance_scheduler.try_lock')
    @patch('pokepoke.maintenance.maintenance_scheduler._run_special_agent')
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

    @patch('pokepoke.maintenance.maintenance_scheduler.try_lock')
    @patch('pokepoke.maintenance.maintenance_scheduler._run_special_agent')
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

    @patch('pokepoke.maintenance.maintenance_scheduler.try_lock')
    @patch('pokepoke.maintenance.maintenance_scheduler._run_special_agent')
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

    @patch('pokepoke.maintenance.maintenance_scheduler.run_maintenance_agent')
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

        with patch('pokepoke.maintenance.maintenance_scheduler.try_lock') as mock_lock, \
                patch.object(scheduler, '_run_agent_with_coordination') as mock_run:
            mock_lock.return_value = Mock()  # Lock available

            scheduler._maybe_run_agent("Unknown Agent", agent_cfg, Mock(), session_stats, run_logger)

            # Should log warning and then run with coordination
            run_logger.log_maintenance.assert_called_with(
                "unknown_agent", "WARNING: Unknown agent classification for Unknown Agent, applying singleton guard"
            )
            mock_run.assert_called_once()


class TestRunAgentWithCoordination:
    """Test agent execution and statistics coordination."""

    @patch('pokepoke.maintenance.maintenance_scheduler.set_terminal_banner')
    @patch('pokepoke.maintenance.maintenance_scheduler.terminal_ui')
    @patch('pokepoke.maintenance.maintenance_scheduler._run_special_agent')
    def test_runs_special_agent(self, mock_special, mock_ui, mock_banner):
        """Test that special agents use their dedicated runners."""
        mock_special.return_value = AgentStats(input_tokens=100)

        scheduler = MaintenanceScheduler()
        agent_cfg = MaintenanceAgentConfig(name="Beta Tester", prompt_file="beta-tester.md", frequency=3)
        session_stats = SessionStats(agent_stats=AgentStats())
        run_logger = Mock()
        pokepoke_repo = Mock()

        scheduler._run_agent_with_coordination("Beta Tester", agent_cfg, pokepoke_repo, session_stats, run_logger)

        mock_special.assert_called_once_with("Beta Tester", pokepoke_repo, item_logger=run_logger.start_maintenance_log.return_value, parent_agent_id='maintenance-beta_tester')
        assert session_stats.beta_tester_agent_runs == 1
        assert session_stats.agent_stats.input_tokens == 100

    @patch('pokepoke.maintenance.maintenance_scheduler.set_terminal_banner')
    @patch('pokepoke.maintenance.maintenance_scheduler.terminal_ui')
    @patch('pokepoke.maintenance.maintenance_scheduler.run_maintenance_agent')
    def test_runs_generic_agent(self, mock_maintenance, mock_ui, mock_banner):
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
            needs_shell=False,
            merge_changes=True,
            model="claude-opus-4.6",
            item_logger=run_logger.start_maintenance_log.return_value,
            parent_agent_id="maintenance-janitor",
        )
        assert session_stats.janitor_agent_runs == 1
        assert session_stats.agent_stats.input_tokens == 50

    @patch('pokepoke.maintenance.maintenance_scheduler.set_terminal_banner')
    @patch('pokepoke.maintenance.maintenance_scheduler.terminal_ui')
    @patch('pokepoke.maintenance.maintenance_scheduler.run_maintenance_agent')
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

    @patch('pokepoke.maintenance.maintenance_scheduler.set_terminal_banner')
    @patch('pokepoke.maintenance.maintenance_scheduler.terminal_ui')
    @patch('pokepoke.maintenance.maintenance_scheduler.run_maintenance_agent')
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

    @patch('pokepoke.maintenance.maintenance_scheduler.set_terminal_banner')
    @patch('pokepoke.maintenance.maintenance_scheduler.terminal_ui')
    @patch('pokepoke.maintenance.maintenance_scheduler.run_maintenance_agent')
    def test_agent_exception_does_not_propagate(self, mock_maintenance, mock_ui, mock_banner):
        """Regression PokePoke-5arw: maintenance agent exceptions must not propagate.

        Previously the except clause re-raised the exception, which crashed the
        orchestrator with exit code 1 after all workers + maintenance finished.
        """
        mock_maintenance.side_effect = RuntimeError("janitor crashed")

        scheduler = MaintenanceScheduler()
        agent_cfg = MaintenanceAgentConfig(name="Janitor", prompt_file="janitor.md", frequency=2)
        session_stats = SessionStats(agent_stats=AgentStats())
        run_logger = Mock()

        # Must NOT raise - exception is swallowed and logged
        scheduler._run_agent_with_coordination("Janitor", agent_cfg, Mock(), session_stats, run_logger)

        # Exception should be logged, agent status set to failed
        mock_ui.ui.push_agent_status.assert_called_with(
            "maintenance-janitor", "Janitor Agent", iteration=1, status="failed", agent_type="janitor"
        )
        run_logger.log_maintenance.assert_any_call("janitor", "Janitor Agent raised exception")

    @patch('pokepoke.maintenance.maintenance_scheduler.set_terminal_banner')
    @patch('pokepoke.maintenance.maintenance_scheduler.terminal_ui')
    @patch('pokepoke.maintenance.maintenance_scheduler.run_maintenance_agent')
    def test_agent_exception_logs_to_maint_logger(self, mock_maintenance, mock_ui, mock_banner):
        """Regression PokePoke-e0xuy: exceptions must be logged to maint_logger.

        Previously the except clause only logged to run_logger and Python logger,
        leaving the agent's dedicated log file (e.g. code_review.log) empty.
        """
        mock_maintenance.side_effect = RuntimeError("agent crashed hard")

        scheduler = MaintenanceScheduler()
        agent_cfg = MaintenanceAgentConfig(name="Code Review", prompt_file="code-reviewer.md", frequency=2)
        session_stats = SessionStats(agent_stats=AgentStats())
        run_logger = Mock()
        maint_logger = Mock()
        run_logger.start_maintenance_log.return_value = maint_logger

        scheduler._run_agent_with_coordination("Code Review", agent_cfg, Mock(), session_stats, run_logger)

        # maint_logger must receive error and summary
        maint_logger.log_error.assert_called_once()
        error_msg = maint_logger.log_error.call_args[0][0]
        assert "Code Review" in error_msg
        assert "agent crashed hard" in error_msg
        maint_logger.log_summary.assert_called_once_with(False, request_count=0)


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

    @patch('pokepoke.maintenance.maintenance_scheduler.get_maintenance_scheduler')
    def test_run_periodic_maintenance_delegates_to_scheduler(self, mock_get_scheduler):
        """Test that the module-level function delegates to scheduler."""
        mock_scheduler = Mock()
        mock_get_scheduler.return_value = mock_scheduler

        session_stats = SessionStats(agent_stats=AgentStats())
        run_logger = Mock()

        run_periodic_maintenance(5, session_stats, run_logger)

        mock_scheduler.maybe_run_maintenance.assert_called_once_with(5, session_stats, run_logger, repo_id=None)

    @patch('pokepoke.utils.shutdown.is_shutting_down', return_value=False)
    @patch('pokepoke.utils.shutdown.should_stop_after_current', return_value=True)
    @patch('pokepoke.maintenance.maintenance_scheduler.get_maintenance_scheduler')
    def test_run_periodic_maintenance_skips_when_stop_requested(self, mock_get_scheduler, _mock_stop, _mock_shutdown):
        """Test that maintenance is skipped when stop-after-current is requested."""
        mock_scheduler = Mock()
        mock_get_scheduler.return_value = mock_scheduler

        session_stats = SessionStats(agent_stats=AgentStats())
        run_logger = Mock()

        run_periodic_maintenance(5, session_stats, run_logger)

        mock_scheduler.maybe_run_maintenance.assert_not_called()
        run_logger.log_orchestrator.assert_called_with(
            "Skipping maintenance - orchestrator is stopping"
        )

    @patch('pokepoke.utils.shutdown.is_shutting_down', return_value=True)
    @patch('pokepoke.utils.shutdown.should_stop_after_current', return_value=False)
    @patch('pokepoke.maintenance.maintenance_scheduler.get_maintenance_scheduler')
    def test_run_periodic_maintenance_skips_when_shutting_down(self, mock_get_scheduler, _mock_stop, _mock_shutdown):
        """Test that maintenance is skipped when shutdown has been requested."""
        mock_scheduler = Mock()
        mock_get_scheduler.return_value = mock_scheduler

        session_stats = SessionStats(agent_stats=AgentStats())
        run_logger = Mock()

        run_periodic_maintenance(5, session_stats, run_logger)

        mock_scheduler.maybe_run_maintenance.assert_not_called()
        run_logger.log_orchestrator.assert_called_with(
            "Skipping maintenance - orchestrator is stopping"
        )


class TestAgentClassification:
    """Test agent classification constants."""

    def test_singleton_agents_defined(self):
        """Test that singleton agents are properly defined."""
        expected_singleton = {"Beta Tester", "Janitor", "Worktree Cleanup"}
        assert expected_singleton == _SINGLETON_AGENTS

    def test_parallel_safe_agents_defined(self):
        """Test that parallel-safe agents are properly defined."""
        expected_parallel = {"Tech Debt", "Code Review", "Backlog Cleanup"}
        assert expected_parallel == _PARALLEL_SAFE_AGENTS

    def test_exclusive_agents_defined(self):
        """Test that exclusive agents are properly defined."""
        expected_exclusive = {"Janitor", "Worktree Cleanup"}
        assert expected_exclusive == _EXCLUSIVE_AGENTS

    def test_no_overlap_singleton_and_parallel(self):
        """Test that singleton and parallel-safe sets don't overlap."""
        assert len(_SINGLETON_AGENTS & _PARALLEL_SAFE_AGENTS) == 0

    def test_exclusive_is_subset_of_singleton(self):
        """Exclusive agents should always be a subset of singleton agents."""
        assert _EXCLUSIVE_AGENTS <= _SINGLETON_AGENTS


class TestConcurrentExecution:
    """Test concurrent execution scenarios."""

    def test_multiple_parallel_safe_agents_can_run_simultaneously(self):
        """Test that multiple Tech Debt agents can run at the same time."""
        scheduler = MaintenanceScheduler()

        results = []
        errors = []

        # Patch once at the test level so multiple threads don't race patch/unpatch.
        with patch('pokepoke.maintenance.maintenance_scheduler.run_maintenance_agent') as mock_run, \
                patch('pokepoke.maintenance.maintenance_scheduler.set_terminal_banner'), \
                patch('pokepoke.maintenance.maintenance_scheduler.terminal_ui'):
            mock_run.return_value = AgentStats()

            def run_agent(agent_name: str):
                try:
                    agent_cfg = MaintenanceAgentConfig(
                        name=agent_name,
                        prompt_file=f"{agent_name.lower().replace(' ', '-')}.md",
                        frequency=1,
                    )
                    session_stats = SessionStats(agent_stats=AgentStats())
                    run_logger = Mock()

                    scheduler._maybe_run_agent(agent_name, agent_cfg, Mock(), session_stats, run_logger)
                    results.append(f"{agent_name}_completed")
                except Exception as e:
                    errors.append(str(e))

            # Start multiple Tech Debt agents simultaneously
            threads = []
            for _i in range(3):
                t = threading.Thread(target=run_agent, args=("Tech Debt",))
                threads.append(t)
                t.start()

            # Wait for completion
            for t in threads:
                t.join(timeout=1.0)

        # All should complete successfully
        assert len(errors) == 0
        assert len(results) == 3

    def test_singleton_agents_block_each_other(self):
        """Test that singleton agents block each other from running simultaneously."""
        scheduler = MaintenanceScheduler()

        results = []
        skipped_messages = []

        def run_janitor():
            with patch('pokepoke.maintenance.maintenance_scheduler.run_maintenance_agent') as mock_run, \
                    patch('pokepoke.maintenance.maintenance_scheduler.try_lock') as mock_lock, \
                    patch('pokepoke.maintenance.maintenance_scheduler.set_terminal_banner'), \
                    patch('pokepoke.maintenance.maintenance_scheduler.terminal_ui'):
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
            for _i in range(3):
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

    @patch("pokepoke.maintenance.maintenance_scheduler.get_active_agent_count")
    def test_dirty_repo_skips_exclusive_agents_but_runs_parallel_safe(self, mock_active_count):
        """When repo stays dirty, exclusive agents are skipped but parallel-safe agents still run."""
        mock_active_count.return_value = 0
        scheduler = MaintenanceScheduler()
        session_stats = SessionStats(agent_stats=AgentStats())
        run_logger = Mock()

        with patch("pokepoke.maintenance.maintenance_scheduler.get_config") as mock_config, \
                patch("pokepoke.maintenance.maintenance_scheduler.wait_for_main_repo_clean", return_value=False) as mock_wait, \
                patch("pokepoke.maintenance.maintenance_scheduler.terminal_ui") as mock_ui:
            mock_ui.ui.is_agent_paused.return_value = False
            config = ProjectConfig()
            config.maintenance = MaintenanceConfig(agents=[
                MaintenanceAgentConfig(name="Janitor", prompt_file="janitor.md", frequency=2, enabled=True),
                MaintenanceAgentConfig(name="Backlog Cleanup", prompt_file="backlog.md", frequency=2, enabled=True),
            ])
            mock_config.return_value = config

            with patch.object(scheduler, '_maybe_run_agent') as mock_run:
                scheduler.maybe_run_maintenance(2, session_stats, run_logger)
                # Backlog Cleanup is parallel-safe — runs even with dirty repo
                assert mock_run.call_count == 1
                mock_run.assert_called_once_with(
                    "Backlog Cleanup", mock_run.call_args[0][1], mock_run.call_args[0][2],
                    session_stats, run_logger, repo_id=None,
                )

        # wait_for_main_repo_clean called once for the exclusive batch
        mock_wait.assert_called_once()
        run_logger.log_maintenance.assert_called_with(
            "maintenance",
            "Skipping 1 exclusive maintenance agent(s) - main repo still dirty after wait",
        )

    @patch("pokepoke.maintenance.maintenance_scheduler.get_active_agent_count")
    def test_dirty_repo_runs_non_exclusive_singletons(self, mock_active_count):
        """Non-exclusive singleton agents (Beta Tester, Model Sync) run despite dirty repo."""
        mock_active_count.return_value = 0
        scheduler = MaintenanceScheduler()
        session_stats = SessionStats(agent_stats=AgentStats())
        run_logger = Mock()

        with patch("pokepoke.maintenance.maintenance_scheduler.get_config") as mock_config, \
                patch("pokepoke.maintenance.maintenance_scheduler.wait_for_main_repo_clean", return_value=False) as mock_wait, \
                patch("pokepoke.maintenance.maintenance_scheduler.terminal_ui") as mock_ui:
            mock_ui.ui.is_agent_paused.return_value = False
            config = ProjectConfig()
            config.maintenance = MaintenanceConfig(agents=[
                MaintenanceAgentConfig(name="Beta Tester", prompt_file="beta.md", frequency=3, enabled=True),
                MaintenanceAgentConfig(name="Janitor", prompt_file="janitor.md", frequency=3, enabled=True),
            ])
            mock_config.return_value = config

            call_names: list[str] = []

            def track_agent(*args, **kwargs):
                call_names.append(args[0])

            with patch.object(scheduler, '_maybe_run_agent', side_effect=track_agent):
                scheduler.maybe_run_maintenance(3, session_stats, run_logger)

            # Beta Tester (non-exclusive singleton) runs; Janitor (exclusive) skipped
            assert "Beta Tester" in call_names
            assert "Janitor" not in call_names

        mock_wait.assert_called_once()

    @patch("pokepoke.maintenance.maintenance_scheduler.get_active_agent_count")
    def test_dirty_repo_skips_all_when_only_exclusive_agents_due(self, mock_active_count):
        """When repo stays dirty and only exclusive agents are due, all are skipped."""
        mock_active_count.return_value = 0
        scheduler = MaintenanceScheduler()
        session_stats = SessionStats(agent_stats=AgentStats())
        run_logger = Mock()

        with patch("pokepoke.maintenance.maintenance_scheduler.get_config") as mock_config, \
                patch("pokepoke.maintenance.maintenance_scheduler.wait_for_main_repo_clean", return_value=False) as mock_wait, \
                patch("pokepoke.maintenance.maintenance_scheduler.terminal_ui") as mock_ui:
            mock_ui.ui.is_agent_paused.return_value = False
            config = ProjectConfig()
            config.maintenance = MaintenanceConfig(agents=[
                MaintenanceAgentConfig(name="Janitor", prompt_file="janitor.md", frequency=2, enabled=True),
                MaintenanceAgentConfig(name="Worktree Cleanup", prompt_file="worktree-cleanup.md", frequency=2, enabled=True),
            ])
            mock_config.return_value = config

            with patch.object(scheduler, '_maybe_run_agent') as mock_run:
                scheduler.maybe_run_maintenance(2, session_stats, run_logger)
                mock_run.assert_not_called()

        mock_wait.assert_called_once()
        run_logger.log_maintenance.assert_called_with(
            "maintenance",
            "Skipping 2 exclusive maintenance agent(s) - main repo still dirty after wait",
        )

    @patch("pokepoke.maintenance.maintenance_scheduler.get_active_agent_count")
    def test_singleton_agent_deferred_when_agents_active(self, mock_active_count):
        """Exclusive agents should be deferred when other agents are retrying."""
        mock_active_count.return_value = 2
        scheduler = MaintenanceScheduler()
        agent_cfg = MaintenanceAgentConfig(name="Janitor", prompt_file="janitor.md", frequency=2)
        session_stats = SessionStats(agent_stats=AgentStats())
        run_logger = Mock()

        with patch.object(scheduler, '_run_with_singleton_guard') as mock_run:
            scheduler._maybe_run_agent("Janitor", agent_cfg, Path.cwd(), session_stats, run_logger)
            mock_run.assert_not_called()

        run_logger.log_maintenance.assert_called_with(
            "janitor",
            "Deferring Janitor Agent - 2 agent(s) still active",
        )

    @patch("pokepoke.maintenance.maintenance_scheduler.get_active_agent_count")
    def test_singleton_agent_runs_when_no_agents_active(self, mock_active_count):
        """Singleton agents should run normally when no agents are active."""
        mock_active_count.return_value = 0
        scheduler = MaintenanceScheduler()
        agent_cfg = MaintenanceAgentConfig(name="Janitor", prompt_file="janitor.md", frequency=2)
        session_stats = SessionStats(agent_stats=AgentStats())
        run_logger = Mock()

        with patch('pokepoke.maintenance.maintenance_scheduler.try_lock') as mock_lock, \
                patch.object(scheduler, '_run_agent_with_coordination') as mock_run:
            mock_lock.return_value = Mock()
            scheduler._maybe_run_agent("Janitor", agent_cfg, Path.cwd(), session_stats, run_logger)
            mock_run.assert_called_once()

    @patch("pokepoke.maintenance.maintenance_scheduler.get_active_agent_count")
    def test_non_exclusive_singleton_not_deferred_by_active_agents(self, mock_active_count):
        """Non-exclusive singletons (Beta Tester, Model Sync) should NOT be deferred by active agents."""
        mock_active_count.return_value = 3
        scheduler = MaintenanceScheduler()
        agent_cfg = MaintenanceAgentConfig(name="Beta Tester", prompt_file="beta.md", frequency=3)
        session_stats = SessionStats(agent_stats=AgentStats())
        run_logger = Mock()

        with patch('pokepoke.maintenance.maintenance_scheduler.try_lock') as mock_lock, \
                patch.object(scheduler, '_run_agent_with_coordination') as mock_run:
            mock_lock.return_value = Mock()
            scheduler._maybe_run_agent("Beta Tester", agent_cfg, Path.cwd(), session_stats, run_logger)
            mock_run.assert_called_once()

    @patch("pokepoke.maintenance.maintenance_scheduler.get_active_agent_count")
    def test_parallel_safe_agent_not_deferred_by_active_agents(self, mock_active_count):
        """Parallel-safe agents should NOT be deferred by active agents."""
        mock_active_count.return_value = 3
        scheduler = MaintenanceScheduler()
        agent_cfg = MaintenanceAgentConfig(name="Tech Debt", prompt_file="tech-debt.md", frequency=5)
        session_stats = SessionStats(agent_stats=AgentStats())
        run_logger = Mock()

        with patch.object(scheduler, '_run_agent_with_coordination') as mock_run:
            scheduler._maybe_run_agent("Tech Debt", agent_cfg, Path.cwd(), session_stats, run_logger)
            mock_run.assert_called_once()


class TestParallelSafeRepoBypass:
    """Test that parallel-safe agents bypass the repo cleanliness check."""

    @patch("pokepoke.maintenance.maintenance_scheduler.wait_for_main_repo_clean")
    @patch("pokepoke.maintenance.maintenance_scheduler.terminal_ui")
    @patch("pokepoke.maintenance.maintenance_scheduler.get_config")
    def test_no_repo_clean_check_when_only_parallel_safe_due(self, mock_config, mock_terminal_ui, mock_wait):
        """wait_for_main_repo_clean should NOT be called when only parallel-safe agents are due."""
        mock_terminal_ui.ui.is_agent_paused.return_value = False
        config = ProjectConfig()
        config.maintenance = MaintenanceConfig(agents=[
            MaintenanceAgentConfig(name="Code Review", prompt_file="code-review.md", frequency=2, enabled=True),
            MaintenanceAgentConfig(name="Backlog Cleanup", prompt_file="backlog.md", frequency=2, enabled=True),
        ])
        mock_config.return_value = config
        scheduler = MaintenanceScheduler()
        session_stats = SessionStats(agent_stats=AgentStats())
        run_logger = Mock()

        with patch.object(scheduler, '_maybe_run_agent') as mock_run:
            scheduler.maybe_run_maintenance(2, session_stats, run_logger)
            # Both parallel-safe agents should be dispatched
            assert mock_run.call_count == 2

        # No repo cleanliness check needed
        mock_wait.assert_not_called()

    @patch("pokepoke.maintenance.maintenance_scheduler.wait_for_main_repo_clean")
    @patch("pokepoke.maintenance.maintenance_scheduler.terminal_ui")
    @patch("pokepoke.maintenance.maintenance_scheduler.get_config")
    def test_parallel_safe_agents_run_before_repo_clean_check(self, mock_config, mock_terminal_ui, mock_wait):
        """All three tiers run in correct order: parallel-safe → singleton → repo clean → exclusive."""
        mock_wait.return_value = True
        mock_terminal_ui.ui.is_agent_paused.return_value = False
        config = ProjectConfig()
        config.maintenance = MaintenanceConfig(agents=[
            MaintenanceAgentConfig(name="Janitor", prompt_file="janitor.md", frequency=6, enabled=True),
            MaintenanceAgentConfig(name="Code Review", prompt_file="code-review.md", frequency=6, enabled=True),
            MaintenanceAgentConfig(name="Beta Tester", prompt_file="beta.md", frequency=6, enabled=True),
        ])
        mock_config.return_value = config
        scheduler = MaintenanceScheduler()
        session_stats = SessionStats(agent_stats=AgentStats())
        run_logger = Mock()

        call_order: list[str] = []

        def track_agent(*args, **kwargs):
            call_order.append(args[0])  # agent name is first arg

        def track_wait(*args, **kwargs):
            call_order.append("wait_for_main_repo_clean")
            return True

        mock_wait.side_effect = track_wait

        with patch.object(scheduler, '_maybe_run_agent', side_effect=track_agent):
            scheduler.maybe_run_maintenance(6, session_stats, run_logger)

        # Tier 1 (parallel-safe) → Tier 2 (singleton) → repo clean check → Tier 3 (exclusive)
        assert call_order == ["Code Review", "Beta Tester", "wait_for_main_repo_clean", "Janitor"]

    @patch("pokepoke.maintenance.maintenance_scheduler.wait_for_main_repo_clean")
    @patch("pokepoke.maintenance.maintenance_scheduler.terminal_ui")
    @patch("pokepoke.maintenance.maintenance_scheduler.get_config")
    def test_no_repo_clean_check_when_no_exclusive_agents_due(self, mock_config, mock_terminal_ui, mock_wait):
        """wait_for_main_repo_clean should NOT be called when no exclusive agents are due."""
        mock_terminal_ui.ui.is_agent_paused.return_value = False
        config = ProjectConfig()
        config.maintenance = MaintenanceConfig(agents=[
            MaintenanceAgentConfig(name="Code Review", prompt_file="code-review.md", frequency=2, enabled=True),
            MaintenanceAgentConfig(name="Beta Tester", prompt_file="beta.md", frequency=2, enabled=True),
        ])
        mock_config.return_value = config
        scheduler = MaintenanceScheduler()
        session_stats = SessionStats(agent_stats=AgentStats())
        run_logger = Mock()

        with patch.object(scheduler, '_maybe_run_agent') as mock_run:
            scheduler.maybe_run_maintenance(2, session_stats, run_logger)
            # Both agents should be dispatched (parallel-safe + non-exclusive singleton)
            assert mock_run.call_count == 2

        mock_wait.assert_not_called()


class TestConflictResolution:
    """Test conflict detection and deferral logic."""

    def test_agent_with_no_conflicts_runs_normally(self):
        """Test that agents without conflicts_with run without issues."""
        scheduler = MaintenanceScheduler()
        agent_cfg = MaintenanceAgentConfig(
            name="Tech Debt",
            prompt_file="tech-debt.md",
            frequency=5,
            conflicts_with=[],  # No conflicts
        )
        session_stats = SessionStats(agent_stats=AgentStats())
        run_logger = Mock()

        with patch.object(scheduler, '_run_agent_with_coordination') as mock_run:
            scheduler._maybe_run_agent("Tech Debt", agent_cfg, Path.cwd(), session_stats, run_logger)
            mock_run.assert_called_once()

    def test_agent_deferred_when_conflicting_agent_running(self):
        """Test that agent is deferred when a conflicting agent is running."""
        scheduler = MaintenanceScheduler()

        # Start Janitor running (add to running set)
        with scheduler._running_agents_lock:
            scheduler._running_agents.add("Janitor")

        try:
            # Try to run Worktree Cleanup which conflicts with Janitor
            agent_cfg = MaintenanceAgentConfig(
                name="Worktree Cleanup",
                prompt_file="worktree-cleanup.md",
                frequency=2,
                conflicts_with=["Janitor", "Backlog Cleanup"],
            )
            session_stats = SessionStats(agent_stats=AgentStats())
            run_logger = Mock()

            with patch.object(scheduler, '_run_agent_with_coordination') as mock_run:
                scheduler._maybe_run_agent("Worktree Cleanup", agent_cfg, Path.cwd(), session_stats, run_logger)
                mock_run.assert_not_called()

            # Should log deferral message
            run_logger.log_maintenance.assert_called_with(
                "worktree_cleanup",
                "Deferring Worktree Cleanup Agent - conflicts with running agent(s): Janitor",
            )
        finally:
            scheduler._running_agents.discard("Janitor")

    def test_agent_runs_when_no_conflicting_agents_running(self):
        """Test that agent runs when none of its conflicting agents are running."""
        scheduler = MaintenanceScheduler()

        # Add a non-conflicting agent to running set
        with scheduler._running_agents_lock:
            scheduler._running_agents.add("Tech Debt")

        try:
            agent_cfg = MaintenanceAgentConfig(
                name="Worktree Cleanup",
                prompt_file="worktree-cleanup.md",
                frequency=2,
                conflicts_with=["Janitor", "Backlog Cleanup"],  # Tech Debt not in list
            )
            session_stats = SessionStats(agent_stats=AgentStats())
            run_logger = Mock()

            with patch.object(scheduler, '_run_with_singleton_guard') as mock_run:
                scheduler._maybe_run_agent("Worktree Cleanup", agent_cfg, Path.cwd(), session_stats, run_logger)
                mock_run.assert_called_once()
        finally:
            scheduler._running_agents.discard("Tech Debt")

    def test_multiple_conflicting_agents_listed_in_defer_message(self):
        """Test that all conflicting agents are listed when multiple conflict."""
        scheduler = MaintenanceScheduler()

        # Start multiple conflicting agents
        with scheduler._running_agents_lock:
            scheduler._running_agents.add("Janitor")
            scheduler._running_agents.add("Backlog Cleanup")

        try:
            agent_cfg = MaintenanceAgentConfig(
                name="Worktree Cleanup",
                prompt_file="worktree-cleanup.md",
                frequency=2,
                conflicts_with=["Janitor", "Backlog Cleanup", "Beta Tester"],
            )
            session_stats = SessionStats(agent_stats=AgentStats())
            run_logger = Mock()

            with patch.object(scheduler, '_run_agent_with_coordination') as mock_run:
                scheduler._maybe_run_agent("Worktree Cleanup", agent_cfg, Path.cwd(), session_stats, run_logger)
                mock_run.assert_not_called()

            # Check message contains both conflicting agents
            call_args = run_logger.log_maintenance.call_args
            assert call_args is not None
            log_msg = call_args[0][1]
            assert "Backlog Cleanup" in log_msg
            assert "Janitor" in log_msg
            assert "conflicts with running agent(s):" in log_msg
        finally:
            scheduler._running_agents.discard("Janitor")
            scheduler._running_agents.discard("Backlog Cleanup")

    def test_tracking_context_manager_adds_and_removes_agent(self):
        """Test that _track_running_agent correctly registers and unregisters."""
        scheduler = MaintenanceScheduler()

        # Initially empty
        assert len(scheduler._get_running_agents()) == 0

        # Add agent via context manager
        with scheduler._track_running_agent("Janitor"):
            running = scheduler._get_running_agents()
            assert "Janitor" in running
            assert len(running) == 1

        # Should be removed after context exit
        assert len(scheduler._get_running_agents()) == 0

    def test_tracking_context_manager_removes_agent_on_exception(self):
        """Test that agent is unregistered even if exception occurs."""
        scheduler = MaintenanceScheduler()

        try:
            with scheduler._track_running_agent("Janitor"):
                assert "Janitor" in scheduler._get_running_agents()
                raise RuntimeError("Test exception")
        except RuntimeError:
            pass

        # Should still be removed despite exception
        assert len(scheduler._get_running_agents()) == 0

    @patch('pokepoke.maintenance.maintenance_scheduler.run_maintenance_agent')
    @patch('pokepoke.maintenance.maintenance_scheduler.set_terminal_banner')
    @patch('pokepoke.maintenance.maintenance_scheduler.terminal_ui')
    def test_agent_tracked_during_execution(self, mock_ui, mock_banner, mock_maintenance):
        """Test that agent is tracked as running during execution."""
        mock_maintenance.return_value = AgentStats()

        scheduler = MaintenanceScheduler()
        agent_cfg = MaintenanceAgentConfig(
            name="Janitor",
            prompt_file="janitor.md",
            frequency=2,
        )
        session_stats = SessionStats(agent_stats=AgentStats())
        run_logger = Mock()

        # Track whether agent was in running set during execution
        was_running = []

        def check_running(*args, **kwargs):
            was_running.append("Janitor" in scheduler._get_running_agents())
            return AgentStats()

        mock_maintenance.side_effect = check_running

        scheduler._run_agent_with_coordination("Janitor", agent_cfg, Path.cwd(), session_stats, run_logger)

        # Agent should have been in running set during execution
        assert len(was_running) > 0
        assert was_running[0] is True

        # Agent should be removed after execution
        assert "Janitor" not in scheduler._get_running_agents()


class TestPerRepoScheduling:
    """Test per-repo maintenance scheduling."""

    @patch("pokepoke.maintenance.maintenance_scheduler.get_config")
    def test_maybe_run_maintenance_accepts_repo_id(self, mock_config):
        """Test that maybe_run_maintenance accepts optional repo_id."""
        mock_config.return_value = _make_default_config()
        scheduler = MaintenanceScheduler()
        session_stats = SessionStats(agent_stats=AgentStats())
        run_logger = Mock()

        with patch.object(scheduler, '_maybe_run_agent') as mock_run:
            scheduler.maybe_run_maintenance(2, session_stats, run_logger, repo_id="repo-a")
            # Should pass repo_id down to _maybe_run_agent
            assert mock_run.called
            for call in mock_run.call_args_list:
                assert call.kwargs.get("repo_id") == "repo-a"

    @patch("pokepoke.maintenance.maintenance_scheduler.get_config")
    def test_independent_repo_frequencies(self, mock_config):
        """Maintenance for different repos uses independent counters."""
        config = ProjectConfig()
        config.maintenance = MaintenanceConfig(agents=[
            MaintenanceAgentConfig(name="Janitor", prompt_file="janitor.md", frequency=2, enabled=True),
        ])
        mock_config.return_value = config
        scheduler = MaintenanceScheduler()
        session_stats = SessionStats(agent_stats=AgentStats())
        run_logger = Mock()

        with patch.object(scheduler, '_maybe_run_agent') as mock_run:
            # Repo A at count 1 — not due (freq=2)
            scheduler.maybe_run_maintenance(1, session_stats, run_logger, repo_id="repo-a")
            assert not mock_run.called

            # Repo B at count 2 — due
            mock_run.reset_mock()
            scheduler.maybe_run_maintenance(2, session_stats, run_logger, repo_id="repo-b")
            assert mock_run.called

    @patch("pokepoke.maintenance.maintenance_scheduler.get_active_agent_count", return_value=0)
    @patch("pokepoke.maintenance.maintenance_scheduler.try_lock")
    def test_per_repo_file_locks_are_independent(self, mock_lock, _mock_active):
        """File locks include repo_id so different repos don't block each other."""
        mock_lock.return_value = Mock()  # Lock available

        scheduler = MaintenanceScheduler()
        agent_cfg = MaintenanceAgentConfig(name="Janitor", prompt_file="janitor.md", frequency=2)
        session_stats = SessionStats(agent_stats=AgentStats())
        run_logger = Mock()

        with patch.object(scheduler, '_run_agent_with_coordination'):
            scheduler._maybe_run_agent("Janitor", agent_cfg, Path.cwd(), session_stats, run_logger, repo_id="repo-a")
            scheduler._maybe_run_agent("Janitor", agent_cfg, Path.cwd(), session_stats, run_logger, repo_id="repo-b")

        # Should have been called with different lock names (repo_id is hashed)
        lock_names = [call.args[0] for call in mock_lock.call_args_list]
        assert len(lock_names) == 2
        assert lock_names[0] != lock_names[1]
        assert all(name.startswith("maintenance-janitor-") for name in lock_names)

    @patch("pokepoke.maintenance.maintenance_scheduler.record_maintenance_run")
    @patch("pokepoke.maintenance.maintenance_scheduler.get_config")
    def test_records_maintenance_run_for_repo(self, mock_config, mock_record):
        """Maintenance run timestamp is recorded per-repo after execution."""
        config = ProjectConfig()
        config.maintenance = MaintenanceConfig(agents=[
            MaintenanceAgentConfig(name="Tech Debt", prompt_file="tech-debt.md", frequency=1, enabled=True),
        ])
        mock_config.return_value = config
        scheduler = MaintenanceScheduler()
        session_stats = SessionStats(agent_stats=AgentStats())
        run_logger = Mock()

        with patch.object(scheduler, '_maybe_run_agent'):
            scheduler.maybe_run_maintenance(1, session_stats, run_logger, repo_id="repo-a")

        mock_record.assert_called_once_with("repo-a")

    @patch("pokepoke.maintenance.maintenance_scheduler.record_maintenance_run")
    @patch("pokepoke.maintenance.maintenance_scheduler.get_config")
    def test_no_record_when_repo_id_is_none(self, mock_config, mock_record):
        """No per-repo timestamp recorded when repo_id is None (legacy mode)."""
        config = ProjectConfig()
        config.maintenance = MaintenanceConfig(agents=[
            MaintenanceAgentConfig(name="Tech Debt", prompt_file="tech-debt.md", frequency=1, enabled=True),
        ])
        mock_config.return_value = config
        scheduler = MaintenanceScheduler()
        session_stats = SessionStats(agent_stats=AgentStats())
        run_logger = Mock()

        with patch.object(scheduler, '_maybe_run_agent'):
            scheduler.maybe_run_maintenance(1, session_stats, run_logger, repo_id=None)

        mock_record.assert_not_called()

    @patch('pokepoke.maintenance.maintenance_scheduler.get_maintenance_scheduler')
    def test_run_periodic_maintenance_passes_repo_id(self, mock_get_scheduler):
        """Test that run_periodic_maintenance passes repo_id through."""
        mock_scheduler = Mock()
        mock_get_scheduler.return_value = mock_scheduler

        session_stats = SessionStats(agent_stats=AgentStats())
        run_logger = Mock()

        run_periodic_maintenance(5, session_stats, run_logger, repo_id="my-repo")

        mock_scheduler.maybe_run_maintenance.assert_called_once_with(
            5, session_stats, run_logger, repo_id="my-repo"
        )
