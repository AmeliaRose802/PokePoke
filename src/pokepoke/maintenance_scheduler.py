"""MaintenanceScheduler for singleton guard coordination of maintenance agents.

Prevents multiple instances of maintenance agents from running simultaneously,
which is critical for agents that modify shared state (like Janitor cleaning worktrees)
or could produce duplicate work (like Beta Tester filing the same issues twice).
"""

import contextlib
import logging
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

from pokepoke.config import get_config, MaintenanceAgentConfig
from pokepoke.coordination import try_lock
from pokepoke.types import SessionStats
from pokepoke.logging_utils import RunLogger
from pokepoke.maintenance import _run_special_agent
from pokepoke.agent_runner import run_maintenance_agent
from pokepoke.repo_state_guard import wait_for_main_repo_clean
from pokepoke.shutdown import get_active_agent_count
from pokepoke.terminal_ui import set_terminal_banner
from pokepoke import terminal_ui


# Agents that require singleton guard (modify shared state or produce duplicates)
_SINGLETON_AGENTS: set[str] = {
    "Beta Tester",
    "Janitor",
    "Backlog Cleanup",
    "Worktree Cleanup",
    "Model Sync",
}

# Agents that can safely run in parallel (beads-only, no conflicts)
_PARALLEL_SAFE_AGENTS: set[str] = {
    "Tech Debt",
    "Code Review"
}

# Map of agent stat attribute names by agent name
_AGENT_STAT_ATTRS = {
    "Tech Debt": "tech_debt_agent_runs",
    "Janitor": "janitor_agent_runs",
    "Backlog Cleanup": "backlog_cleanup_agent_runs",
    "Beta Tester": "beta_tester_agent_runs",
    "Code Review": "code_review_agent_runs",
    "Worktree Cleanup": "worktree_cleanup_agent_runs",
}

# Agents that have special runner functions instead of the generic one
_SPECIAL_AGENTS = {"Beta Tester", "Worktree Cleanup", "Model Sync"}


class MaintenanceScheduler:
    """Coordinated scheduler for maintenance agents with singleton guards."""

    def __init__(self) -> None:
        # In-process locks for thread coordination
        self._locks: dict[str, threading.Lock] = {}
        self._lock_creation_lock = threading.Lock()
        # Track currently running agents (for conflict detection)
        self._running_agents: set[str] = set()
        self._running_agents_lock = threading.Lock()

    def _get_agent_lock(self, agent_name: str) -> threading.Lock:
        """Get or create a threading lock for the given agent."""
        if agent_name not in self._locks:
            with self._lock_creation_lock:
                # Double-checked locking pattern
                if agent_name not in self._locks:
                    self._locks[agent_name] = threading.Lock()
        return self._locks[agent_name]

    @contextlib.contextmanager
    def _track_running_agent(self, agent_name: str):
        """Context manager to track a running agent and auto-unregister on exit."""
        with self._running_agents_lock:
            self._running_agents.add(agent_name)
        try:
            yield
        finally:
            with self._running_agents_lock:
                self._running_agents.discard(agent_name)

    def _get_running_agents(self) -> set[str]:
        """Get a snapshot of currently running agents (thread-safe)."""
        with self._running_agents_lock:
            return self._running_agents.copy()

    def maybe_run_maintenance(self, items_completed: int, session_stats: SessionStats, run_logger: RunLogger) -> None:
        """Run maintenance agents that are due, with singleton coordination.

        Args:
            items_completed: Number of items completed (for frequency calculation)
            session_stats: Session statistics to update
            run_logger: Logger for maintenance events
        """
        pokepoke_repo = Path.cwd()

        if items_completed == 0:
            return

        config = get_config()
        agents = config.maintenance.agents

        # Collect agents that are due to run this cycle.
        due_agents: list[MaintenanceAgentConfig] = []
        for agent_cfg in agents:
            if not agent_cfg.enabled:
                continue
            if agent_cfg.frequency <= 0:
                continue
            if items_completed % agent_cfg.frequency != 0:
                continue

            # Check if agent is paused in the UI
            log_key = agent_cfg.name.lower().replace(" ", "_")
            agent_id = f"maintenance-{log_key}"
            if terminal_ui.ui.is_agent_paused(agent_id) is True:
                run_logger.log_maintenance(log_key, f"Skipping {agent_cfg.name} Agent - paused by user")
                continue

            due_agents.append(agent_cfg)

        if not due_agents:
            return

        # Check repo cleanliness ONCE for the entire batch.  Previously each
        # agent called wait_for_main_repo_clean independently, so a dirty repo
        # caused 4+ agents to each time-out after 3 minutes — wasting 12+ min
        # per cycle with no useful work.
        def _batch_log(msg: str) -> None:
            run_logger.log_maintenance("maintenance", msg)

        if not wait_for_main_repo_clean(
            pokepoke_repo,
            timeout=180.0,
            poll_interval=2.0,
            log_fn=_batch_log,
        ):
            run_logger.log_maintenance(
                "maintenance",
                f"Skipping {len(due_agents)} maintenance agent(s) - main repo still dirty after wait",
            )
            return

        for agent_cfg in due_agents:
            self._maybe_run_agent(agent_cfg.name, agent_cfg, pokepoke_repo, session_stats, run_logger)

    def _maybe_run_agent(self, agent_name: str, agent_cfg: MaintenanceAgentConfig, pokepoke_repo: Path, session_stats: SessionStats, run_logger: RunLogger) -> None:
        """Try to run a single maintenance agent with appropriate locking.

        Args:
            agent_name: Name of the agent to run
            agent_cfg: Agent configuration
            pokepoke_repo: Repository path
            session_stats: Session statistics to update
            run_logger: Logger for maintenance events
        """
        log_key = agent_name.lower().replace(" ", "_")

        # Defer singleton agents when other agents are actively processing
        # (e.g. retrying after gate failures) to avoid interfering with
        # in-progress work.
        if agent_name in _SINGLETON_AGENTS:
            active_count = get_active_agent_count()
            if active_count > 0:
                run_logger.log_maintenance(
                    log_key,
                    f"Deferring {agent_name} Agent - {active_count} agent(s) still active",
                )
                return

        # Check for conflicts with currently running agents
        if agent_cfg.conflicts_with:
            running = self._get_running_agents()
            conflicts = set(agent_cfg.conflicts_with) & running
            if conflicts:
                conflict_list = ", ".join(sorted(conflicts))
                run_logger.log_maintenance(
                    log_key,
                    f"Deferring {agent_name} Agent - conflicts with running agent(s): {conflict_list}",
                )
                return

        if agent_name in _PARALLEL_SAFE_AGENTS:
            # Parallel-safe agents don't need singleton coordination
            self._run_agent_with_coordination(agent_name, agent_cfg, pokepoke_repo, session_stats, run_logger)
            return

        # Singleton or unknown agents need lock protection
        if agent_name not in _SINGLETON_AGENTS:
            run_logger.log_maintenance(log_key, f"WARNING: Unknown agent classification for {agent_name}, applying singleton guard")

        self._run_with_singleton_guard(agent_name, agent_cfg, pokepoke_repo, session_stats, run_logger)

    def _run_with_singleton_guard(self, agent_name: str, agent_cfg: MaintenanceAgentConfig, pokepoke_repo: Path, session_stats: SessionStats, run_logger: RunLogger) -> None:
        """Run an agent with both thread and file lock singleton protection."""
        log_key = agent_name.lower().replace(" ", "_")
        file_lock = None
        thread_lock = self._get_agent_lock(agent_name)

        # Try to acquire thread lock first (non-blocking)
        thread_acquired = thread_lock.acquire(blocking=False)
        if not thread_acquired:
            run_logger.log_maintenance(log_key, f"Skipping {agent_name} Agent - already running in this process")
            return

        try:
            # Try to acquire file lock (cross-process)
            file_lock = try_lock(f"maintenance-{agent_name.lower().replace(' ', '-')}")
            if file_lock is None:
                run_logger.log_maintenance(log_key, f"Skipping {agent_name} Agent - already running in another process")
                return

            # Both locks acquired - run the agent
            self._run_agent_with_coordination(agent_name, agent_cfg, pokepoke_repo, session_stats, run_logger)

        finally:
            if file_lock is not None:
                file_lock.release()
            thread_lock.release()

    def _run_agent_with_coordination(self, agent_name: str, agent_cfg: MaintenanceAgentConfig, pokepoke_repo: Path, session_stats: SessionStats, run_logger: RunLogger) -> None:
        """Run a maintenance agent and handle statistics coordination.

        Args:
            agent_name: Name of the agent to run
            agent_cfg: Agent configuration
            pokepoke_repo: Repository path
            session_stats: Session statistics to update
            run_logger: Logger for maintenance events
        """
        log_key = agent_name.lower().replace(" ", "_")

        # Register maintenance agent in the Agents panel
        agent_id = f"maintenance-{log_key}"
        terminal_ui.ui.push_agent_status(agent_id, f"{agent_name} Agent", iteration=1, status="running", agent_type=log_key)

        set_terminal_banner(f"PokePoke - Synced {agent_name} Agent")
        terminal_ui.ui.update_header("MAINTENANCE", f"{agent_name} Agent", "Running")
        print(f"\n🔧 Running {agent_name} Agent...")
        run_logger.log_maintenance(log_key, f"Starting {agent_name} Agent")

        # Update run count on session stats if attribute exists (thread-safe)
        stat_attr = _AGENT_STAT_ATTRS.get(agent_name)
        if stat_attr and hasattr(session_stats, 'record_agent_run'):
            with contextlib.suppress(AttributeError, ValueError):
                session_stats.record_agent_run(agent_name)

        # Create a dedicated log file for the maintenance agent output
        maint_logger = run_logger.start_maintenance_log(agent_name)

        # Run the agent with proper output routing and track as running
        try:
            with self._track_running_agent(agent_name), terminal_ui.ui.agent_output_for(agent_id):
                if agent_name in _SPECIAL_AGENTS:
                    result = _run_special_agent(agent_name, pokepoke_repo, item_logger=maint_logger, parent_agent_id=agent_id)
                else:
                    result = run_maintenance_agent(
                        agent_name,
                        agent_cfg.prompt_file,
                        repo_root=pokepoke_repo,
                        needs_worktree=agent_cfg.needs_worktree,
                        merge_changes=agent_cfg.merge_changes,
                        model=agent_cfg.model,
                        item_logger=maint_logger,
                        parent_agent_id=agent_id,
                    )

            success = result is not None

            # Update agent status based on result
            status = "success" if success else "failed"
            terminal_ui.ui.push_agent_status(agent_id, f"{agent_name} Agent", iteration=1, status=status, agent_type=log_key)

            maint_logger.log_summary(success, request_count=0)

            if result:
                session_stats.record_agent_stats(result)
                if agent_name == "Janitor":
                    session_stats.record_janitor_lines_removed(result.lines_removed)
                run_logger.log_maintenance(log_key, f"{agent_name} Agent completed successfully")
            else:
                run_logger.log_maintenance(log_key, f"{agent_name} Agent failed")

        except Exception as e:
            logger.warning(f"Maintenance agent {agent_name} raised exception: {e}", exc_info=True)
            terminal_ui.ui.push_agent_status(agent_id, f"{agent_name} Agent", iteration=1, status="failed", agent_type=log_key)
            run_logger.log_maintenance(log_key, f"{agent_name} Agent raised exception")


# Global scheduler instance and initialization lock
_scheduler: MaintenanceScheduler | None = None
_scheduler_lock = threading.Lock()


def get_maintenance_scheduler() -> MaintenanceScheduler:
    """Get the global MaintenanceScheduler instance with thread-safe initialization."""
    global _scheduler
    if _scheduler is None:
        with _scheduler_lock:
            # Double-checked locking pattern to prevent TOCTOU race
            if _scheduler is None:
                _scheduler = MaintenanceScheduler()
    return _scheduler


def run_periodic_maintenance(items_completed: int, session_stats: SessionStats, run_logger: RunLogger) -> None:
    """Run periodic maintenance agents based on config and completion count.

    This is a backward-compatible wrapper that delegates to the MaintenanceScheduler.

    Args:
        items_completed: Number of completed work items
        session_stats: Session statistics to update
        run_logger: Logger for maintenance events
    """
    from pokepoke.shutdown import should_stop_after_current
    if should_stop_after_current():
        run_logger.log_orchestrator("Skipping maintenance - stop after current item requested")
        return

    scheduler = get_maintenance_scheduler()
    scheduler.maybe_run_maintenance(items_completed, session_stats, run_logger)
