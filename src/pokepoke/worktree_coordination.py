"""Backward-compatibility shim -- consolidated into pokepoke.coordination.

All locking logic now lives in :mod:`pokepoke.coordination`.  This module
re-exports the public names so existing callers continue to work.
"""

from __future__ import annotations

from pathlib import Path

# Re-export the canonical implementations
from pokepoke.coordination import (  # noqa: F401
    _load_worktree_metrics as _load_metrics,
    _record_worktree_attempt as _record_attempt,
    _WORKTREE_METRICS_PATH as _METRICS_PATH,
    _WORKTREE_METRICS_DIR as _STATS_DIR,
    with_worktree_lock,
)

# Legacy constant kept for tests that reference it
_LOCK_DIR = Path(".pokepoke/locks")
_WORKTREE_LOCK_PATH = _LOCK_DIR / "worktree-setup.lock"
