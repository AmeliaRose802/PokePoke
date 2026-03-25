"""Shared constants for the PokePoke project.

Centralizes magic values that were previously scattered across many modules.
"""

from pathlib import Path

# ── Directory paths ──────────────────────────────────────────────────────────
POKEPOKE_DIR = Path(".pokepoke")
WORKTREE_DIR: str = "worktrees"
BEADS_DIR: str = ".beads"

# ── Branch / worktree naming ────────────────────────────────────────────────
BRANCH_PREFIX: str = "task/"
WORKTREE_TASK_PREFIX: str = "task-"

# ── Beads status literals ───────────────────────────────────────────────────
STATUS_IN_PROGRESS: str = "in_progress"
COMPLETED_STATUSES: tuple[str, ...] = ("done", "closed", "resolved")

# ── Human-identity keywords (for distinguishing human vs. bot authors) ──────
HUMAN_IDENTIFIERS: tuple[str, ...] = ("amelia", "payne")

# ── Subprocess defaults ──────────────────────────────────────────────────────
DEFAULT_GIT_TIMEOUT: int = 30
DEFAULT_ENCODING: str = "utf-8"
DEFAULT_ENCODING_ERRORS: str = "replace"

# ── Beads backend selection ──────────────────────────────────────────────────
DEFAULT_BEADS_BACKEND: str = "bd"
BEADS_BINARY_BD: str = "bd"
BEADS_BINARY_BR: str = "br"
DEFAULT_BEADS_TIMEOUT: int = 30
DEFAULT_BEADS_LOCK_TIMEOUT: float = 180.0

# ── Agent timeout defaults ───────────────────────────────────────────────────
DEFAULT_AGENT_TIMEOUT: float = 7200.0  # 2 hours
CLEANUP_AGENT_TIMEOUT: float = 600.0  # 10 minutes per cleanup invocation
CLEANUP_AGGREGATE_TIMEOUT: float = 1800.0  # 30 minutes total for all cleanup retries
