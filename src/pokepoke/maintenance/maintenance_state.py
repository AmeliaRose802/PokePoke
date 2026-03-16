"""Persistent state tracking for maintenance agents.

Supports per-repo tracking so each repository can have independent
maintenance cadences and thresholds.  The legacy global counter is
preserved for backward compatibility (repo_id="_global").
"""

import json
import logging
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path

logger = logging.getLogger(__name__)

STATE_FILE = Path(".pokepoke") / "maintenance_state.json"

_DEFAULT_REPO = "_global"


@dataclass
class RepoMaintenanceState:
    """Per-repo maintenance counters and timestamps."""
    items_completed: int = 0
    last_run_timestamp: float = 0.0


@dataclass
class MaintenanceState:
    """Persistent state for maintenance tracking.

    ``total_items_completed`` is the legacy global counter kept for
    backward compatibility.  ``repos`` maps repo identifiers to their
    independent maintenance state.
    """
    total_items_completed: int = 0
    repos: dict[str, RepoMaintenanceState] = field(default_factory=dict)


def _state_to_dict(state: MaintenanceState) -> dict[str, object]:
    """Serialize MaintenanceState to a JSON-safe dict."""
    return {
        "total_items_completed": state.total_items_completed,
        "repos": {k: asdict(v) for k, v in state.repos.items()},
    }


def _state_from_dict(data: dict[str, object]) -> MaintenanceState:
    """Deserialize a dict into a MaintenanceState, tolerating old formats."""
    raw_total = data.get("total_items_completed", 0)
    total = int(raw_total) if isinstance(raw_total, (int, float, str)) else 0
    raw_repos = data.get("repos", {})
    repos: dict[str, RepoMaintenanceState] = {}
    if isinstance(raw_repos, dict):
        for repo_id, repo_data in raw_repos.items():
            if isinstance(repo_data, dict):
                repos[repo_id] = RepoMaintenanceState(
                    items_completed=int(repo_data.get("items_completed", 0) or 0),
                    last_run_timestamp=float(repo_data.get("last_run_timestamp", 0.0) or 0.0),
                )
    return MaintenanceState(total_items_completed=total, repos=repos)


def load_state() -> MaintenanceState:
    """Load maintenance state from disk."""
    if STATE_FILE.exists():
        try:
            data = json.loads(STATE_FILE.read_text(encoding='utf-8'))
            return _state_from_dict(data)
        except Exception as e:
            logger.warning(f"Failed to load maintenance state from {STATE_FILE}: {e}")
            return MaintenanceState()
    return MaintenanceState()


def save_state(state: MaintenanceState) -> None:
    """Save maintenance state to disk."""
    STATE_FILE.write_text(json.dumps(_state_to_dict(state), indent=2))


def get_repo_state(state: MaintenanceState, repo_id: str) -> RepoMaintenanceState:
    """Return the per-repo state, creating it lazily if needed."""
    if repo_id not in state.repos:
        state.repos[repo_id] = RepoMaintenanceState()
    return state.repos[repo_id]


def increment_items_completed(repo_id: str | None = None) -> int:
    """Increment the items-completed counter and return the new value.

    When *repo_id* is provided the per-repo counter is incremented **and**
    the global counter is bumped (so the legacy total stays accurate).
    The returned value is the **per-repo** count when a repo_id is given,
    or the global count otherwise.
    """
    state = load_state()
    state.total_items_completed += 1

    if repo_id is not None:
        repo = get_repo_state(state, repo_id)
        repo.items_completed += 1
        save_state(state)
        return repo.items_completed

    # Legacy global-only path
    repo = get_repo_state(state, _DEFAULT_REPO)
    repo.items_completed += 1
    save_state(state)
    return state.total_items_completed


def record_maintenance_run(repo_id: str) -> None:
    """Record that a maintenance cycle just ran for *repo_id*."""
    state = load_state()
    repo = get_repo_state(state, repo_id)
    repo.last_run_timestamp = time.time()
    save_state(state)


def get_items_completed_for_repo(repo_id: str) -> int:
    """Return the items-completed count for *repo_id* (0 if unknown)."""
    state = load_state()
    return state.repos.get(repo_id, RepoMaintenanceState()).items_completed
