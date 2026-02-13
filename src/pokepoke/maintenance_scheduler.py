"""MaintenanceScheduler for singleton guard coordination of maintenance agents.

Prevents multiple instances of maintenance agents from running simultaneously,
which is critical for agents that modify shared state (like Janitor cleaning worktrees)
or could produce duplicate work (like Beta Tester filing the same issues twice).
"""

import threading
from pathlib import Path
from typing import Dict, Optional, Set

from pokepoke.config import get_config, MaintenanceAgentConfig
from pokepoke.coordination import try_lock
from pokepoke.types import SessionStats
from pokepoke.logging_utils import RunLogger
from pokepoke.maintenance import _run_special_agent
from pokepoke.agent_runner import run_maintenance_agent
from pokepoke.terminal_ui import set_terminal_banner
from pokepoke import terminal_ui


# Agents that require singleton guard (modify shared state or produce duplicates)
_SINGLETON_AGENTS: Set[str] = {
    "Beta Tester", 
    "Janitor", 
    "Backlog Cleanup", 
    "Worktree Cleanup"
}

# Agents that can safely run in parallel (beads-only, no conflicts)
_PARALLEL_SAFE_AGENTS: Set[str] = {
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
_SPECIAL_AGENTS = {"Beta Tester", "Worktree Cleanup"}


class MaintenanceScheduler:
    """Coordinated scheduler for maintenance agents with singleton guards."""
    
    def __init__(self) -> None:
        # In-process locks for thread coordination
        self._locks: Dict[str, threading.Lock] = {}
        self._lock_creation_lock = threading.Lock()
        
    def _get_agent_lock(self, agent_name: str) -> threading.Lock:
        """Get or create a threading lock for the given agent."""
        if agent_name not in self._locks:
            with self._lock_creation_lock:
                # Double-checked locking pattern
                if agent_name not in self._locks:
                    self._locks[agent_name] = threading.Lock()
        return self._locks[agent_name]
    
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

        for agent_cfg in agents:
            if not agent_cfg.enabled:
                continue
            if agent_cfg.frequency <= 0:
                continue
            if items_completed % agent_cfg.frequency != 0:
                continue

            # Agent is due to run - try to schedule it
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
        
        # Determine if this agent needs singleton protection
        if agent_name in _SINGLETON_AGENTS:
            # Use both file lock (cross-process) and thread lock (in-process)
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
                # Release file lock
                if file_lock is not None:
                    file_lock.release()
                # Release thread lock
                thread_lock.release()
                
        elif agent_name in _PARALLEL_SAFE_AGENTS:
            # Parallel-safe agents don't need singleton coordination
            self._run_agent_with_coordination(agent_name, agent_cfg, pokepoke_repo, session_stats, run_logger)
            
        else:
            # Unknown agent - log warning and apply singleton protection as safety measure
            run_logger.log_maintenance(log_key, f"WARNING: Unknown agent classification for {agent_name}, applying singleton guard")
            
            # Apply singleton protection for unknown agents
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
                # Release file lock
                if file_lock is not None:
                    file_lock.release()
                # Release thread lock
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
        
        set_terminal_banner(f"PokePoke - Synced {agent_name} Agent")
        terminal_ui.ui.update_header("MAINTENANCE", f"{agent_name} Agent", "Running")
        print(f"\n🔧 Running {agent_name} Agent...")
        run_logger.log_maintenance(log_key, f"Starting {agent_name} Agent")

        # Update run count on session stats if attribute exists (thread-safe)
        stat_attr = _AGENT_STAT_ATTRS.get(agent_name)
        if stat_attr and hasattr(session_stats, 'record_agent_run'):
            try:
                session_stats.record_agent_run(agent_name)
            except (AttributeError, ValueError):
                # Silently skip if method doesn't exist or agent name not recognized
                pass

        # Run the agent
        if agent_name in _SPECIAL_AGENTS:
            result = _run_special_agent(agent_name, pokepoke_repo)
        else:
            result = run_maintenance_agent(
                agent_name,
                agent_cfg.prompt_file,
                repo_root=pokepoke_repo,
                needs_worktree=agent_cfg.needs_worktree,
                merge_changes=agent_cfg.merge_changes,
                model=agent_cfg.model,
            )

        if result:
            session_stats.record_agent_stats(result)
            if agent_name == "Janitor":
                session_stats.record_janitor_lines_removed(result.lines_removed)
            run_logger.log_maintenance(log_key, f"{agent_name} Agent completed successfully")
        else:
            run_logger.log_maintenance(log_key, f"{agent_name} Agent failed")


# Global scheduler instance and initialization lock
_scheduler: Optional[MaintenanceScheduler] = None
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
    scheduler = get_maintenance_scheduler()
    scheduler.maybe_run_maintenance(items_completed, session_stats, run_logger)
