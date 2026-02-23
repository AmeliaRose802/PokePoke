"""Test configuration for PokePoke tests."""
import sys
import os
import importlib.util
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_PATH = PROJECT_ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

# Fix Windows encoding issues with emojis in test output
# Set environment variable before any imports that might use stdout
if sys.platform == 'win32':
    # Set console code page to UTF-8 for Windows
    os.environ.setdefault('PYTHONIOENCODING', 'utf-8')

# Fail fast if pytest-timeout is not installed.  The timeout=10 setting in
# pyproject.toml is silently ignored without this plugin, which lets the full
# suite hang indefinitely in agent/CI contexts.
if importlib.util.find_spec("pytest_timeout") is None:
    raise RuntimeError(
        "pytest-timeout is required but not installed. "
        "Install it with: pip install pytest-timeout"
    )

# Fail fast if pytest-xdist is not installed.  The pre-commit coverage check
# uses '-n auto' for parallel test execution; without xdist the flag is
# silently rejected by pytest causing the check to fail.
if importlib.util.find_spec("xdist") is None:
    raise RuntimeError(
        "pytest-xdist is required but not installed. "
        "Install it with: pip install pytest-xdist"
    )

import pytest  # noqa: E402
from unittest.mock import patch  # noqa: E402

from pokepoke.types import BeadsWorkItem  # noqa: E402


@pytest.fixture(autouse=True)
def _suppress_terminal_banner(request):
    """Suppress SetConsoleTitleW during tests.

    The real call leaks emoji-laden title text into the agent's output
    stream, which floods the buffered pipe and makes the suite appear to
    hang.  Mocking it globally removes ~100 KB of noise per run.

    Tests in test_terminal_ui.py that directly test set_terminal_banner
    opt out via the ``real_terminal_banner`` marker.
    """
    if request.node.get_closest_marker("real_terminal_banner"):
        yield
    else:
        with patch("pokepoke.terminal_ui.set_terminal_banner"):
            yield


@pytest.fixture(autouse=True)
def _suppress_atexit():
    """Prevent tests from registering atexit handlers.

    Orchestrator tests register atexit handlers that print log paths.
    When many tests run, dozens of handlers fire at exit, producing
    large bursts of output that contribute to the perceived hang.
    """
    with patch("atexit.register"):
        yield


@pytest.fixture(autouse=True)
def _fast_repo_guard(monkeypatch):
    """Ensure maintenance tests never block on repo cleanliness."""
    monkeypatch.setattr(
        "pokepoke.maintenance_scheduler.wait_for_main_repo_clean",
        lambda *_, **__: True,
    )


@pytest.fixture(autouse=True)
def _mock_cleanup_lock_global(monkeypatch):
    """Prevent file locks from hitting the filesystem during tests.

    The real locks use filelock which hangs when orchestrator processes
    hold the lock or when xdist workers contend.  Replace with no-op
    context managers globally.
    """
    from contextlib import nullcontext

    monkeypatch.setattr("pokepoke.repo_state_guard.cleanup_lock", lambda: nullcontext())
    monkeypatch.setattr("pokepoke.repo_check.cleanup_lock", lambda: nullcontext())
    monkeypatch.setattr("pokepoke.worktree_finalization.merge_lock", lambda: nullcontext())


@pytest.fixture
def sample_work_item() -> BeadsWorkItem:
    """Create a sample work item for testing."""
    return BeadsWorkItem(
        id="test-123",
        title="Test work item",
        description="Test description",
        status="in_progress",
        priority=1,
        issue_type="task",
        labels=["testing", "coverage"]
    )

