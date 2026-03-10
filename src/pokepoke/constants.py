"""Shared constants for the PokePoke project.

Centralizes magic values that were previously scattered across many modules.
"""

from __future__ import annotations

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

# ── Agent timeout defaults ───────────────────────────────────────────────────
DEFAULT_AGENT_TIMEOUT: float = 7200.0  # 2 hours
