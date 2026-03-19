"""Shared fixtures for maintenance tests."""
from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def _mock_session_reconciler():
    """Prevent session_reconciler from touching real worktrees during tests.

    session_reconciler.run() scans for abandoned session journals and
    attempts to clean up real worktree directories.  When a stale
    directory is locked by another process (e.g. a VS Code terminal)
    the retry loop in force_remove_directory blocks for up to 30 s,
    causing tests to timeout under pytest-xdist.
    """
    with patch(
        "pokepoke.stats.session_reconciler.run",
        return_value=0,
    ):
        yield
