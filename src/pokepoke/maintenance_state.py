"""Persistent state tracking for maintenance agents."""

import json
from pathlib import Path
from dataclasses import dataclass, asdict

STATE_FILE = Path(".maintenance_state.json")

@dataclass
class MaintenanceState:
    """Persistent state for maintenance tracking."""
    total_items_completed: int = 0
    # Track when agents last ran (by item count)
    last_janitor_run: int = 0
    last_tech_debt_run: int = 0
    last_backlog_run: int = 0
    last_beta_run: int = 0

def load_state() -> MaintenanceState:
    """Load maintenance state from disk."""
    if STATE_FILE.exists():
        try:
            data = json.loads(STATE_FILE.read_text())
            return MaintenanceState(**data)
        except Exception:
            return MaintenanceState()
    return MaintenanceState()

def save_state(state: MaintenanceState) -> None:
    """Save maintenance state to disk."""
    STATE_FILE.write_text(json.dumps(asdict(state), indent=2))

def increment_items_completed() -> int:
    """Increment the total items completed counter and return new value."""
    state = load_state()
    state.total_items_completed += 1
    save_state(state)
    return state.total_items_completed
