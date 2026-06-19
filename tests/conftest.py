"""Test configuration for PokePoke tests."""
import contextlib
import importlib.util
import os
import sys
import warnings
from pathlib import Path

# Suppress rm_rf PermissionError noise on Windows with xdist.
# xdist workers (spawned, not forked) may not fully release file handles
# before the controller tries to clean up temp dirs.  Monkeypatching rm_rf
# is necessary because pytest restores warning filters during unconfigure,
# before the cleanup that triggers these warnings.
if sys.platform == "win32":
    import _pytest.pathlib
    import _pytest.tmpdir
    _original_rm_rf = _pytest.pathlib.rm_rf

    def _quiet_rm_rf(path):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            with contextlib.suppress(PermissionError, OSError):
                _original_rm_rf(path)

    _pytest.pathlib.rm_rf = _quiet_rm_rf
    _pytest.tmpdir.rm_rf = _quiet_rm_rf

    # Also patch getbasetemp to tolerate pre-existing dirs that rm_rf
    # couldn't remove (stale xdist worker handles on Windows).
    _orig_getbasetemp = _pytest.tmpdir.TempPathFactory.getbasetemp

    def _resilient_getbasetemp(self):
        try:
            return _orig_getbasetemp(self)
        except (FileExistsError, OSError):
            # basetemp dir survived rm_rf due to locked handles.
            # Fall back: reuse the existing dir.
            if self._basetemp is not None:
                return self._basetemp
            basetemp = self._given_basetemp or Path(os.path.join(
                __import__("tempfile").gettempdir(), "pytest-fallback"))
            basetemp = Path(basetemp).resolve()
            basetemp.mkdir(mode=0o700, exist_ok=True)
            self._basetemp = basetemp
            return basetemp

    _pytest.tmpdir.TempPathFactory.getbasetemp = _resilient_getbasetemp

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_PATH = PROJECT_ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

# Fix Windows encoding issues with emojis in test output
# Set environment variable before any imports that might use stdout
if sys.platform == 'win32':
    # Set console code page to UTF-8 for Windows
    os.environ.setdefault('PYTHONIOENCODING', 'utf-8')
    # Reconfigure streams for the current process (env var only affects startup)
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    if hasattr(sys.stderr, 'reconfigure'):
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')

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

import logging as _logging
from unittest.mock import patch

import pytest

from pokepoke.beads.beads_query import (
    BD_CONFIG,
    BR_CONFIG,
    get_active_backend,
    set_active_backend,
)
from pokepoke.types import BeadsWorkItem


def _scrub_surrogates(s: str) -> str:
    """Replace surrogate characters that crash xdist serialization."""
    return s.encode("utf-8", errors="replace").decode("utf-8")


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """Scrub surrogate characters from test reports before xdist serialises.

    xdist serialises test report data (including captured stdout/stderr/log)
    via execnet which requires valid UTF-8.  Surrogate characters (e.g. from
    Windows paths decoded with surrogateescape) cause DumpError and crash
    the worker.  We scrub the sections list which backs capstdout/capstderr/caplog.
    """
    outcome = yield
    report = outcome.get_result()
    if hasattr(report, "sections"):
        report.sections = [
            (name, _scrub_surrogates(content)) for name, content in report.sections
        ]
    # Also scrub the longrepr if it's a string (assertion details)
    if isinstance(getattr(report, "longrepr", None), str):
        report.longrepr = _scrub_surrogates(report.longrepr)

# ---------------------------------------------------------------------------
# Route pokepoke logger output through print() so capsys/capsys-like capture
# works in tests.  Source code uses logger.info/warning/error instead of
# print(); this handler bridges the gap so existing test assertions on
# capsys.readouterr().out / .err keep working without modification.
# ---------------------------------------------------------------------------

class _PrintHandler(_logging.Handler):
    """Logging handler that routes records through builtins.print().

    Calls builtins.print() so that:
    - pytest's capsys fixture captures the output (capsys replaces sys.stdout)
    - tests that mock builtins.print via patch('builtins.print') capture calls
    WARNING+ goes to stderr, INFO and below to stdout — matching the
    original print() / print(file=sys.stderr) behaviour.
    """

    def emit(self, record: _logging.LogRecord) -> None:
        try:
            msg = record.getMessage()
            # Strip surrogate characters that crash xdist worker serialization
            msg = msg.encode("utf-8", errors="replace").decode("utf-8")
            if record.levelno >= _logging.WARNING:
                print(msg, file=sys.stderr)  # noqa: T201 - intentional: bridges logger→capsys
            else:
                print(msg)  # noqa: T201 - intentional: bridges logger→capsys
        except Exception:
            self.handleError(record)


_PRINT_HANDLER = _PrintHandler()


@pytest.fixture(autouse=True)
def _ensure_print_handler():
    """Ensure the _PrintHandler is always present on the pokepoke logger.

    Some tests (e.g. test_logging.py) clear and restore logger handlers.
    This fixture guarantees our handler is re-added before every test.
    """
    pokepoke_logger = _logging.getLogger("pokepoke")
    if _PRINT_HANDLER not in pokepoke_logger.handlers:
        pokepoke_logger.addHandler(_PRINT_HANDLER)
    pokepoke_logger.setLevel(_logging.DEBUG)
    yield
    # Re-add after test in case it was removed
    if _PRINT_HANDLER not in pokepoke_logger.handlers:
        pokepoke_logger.addHandler(_PRINT_HANDLER)


@pytest.fixture(params=[
    pytest.param(BD_CONFIG, id="bd"),
    pytest.param(BR_CONFIG, id="br"),
])
def backend_config(request):
    """Parametrized fixture for both bd and br backends.

    This fixture automatically runs tests twice - once with BD_CONFIG
    and once with BR_CONFIG. It properly saves and restores the original
    backend configuration.

    Usage:
        def test_something(backend_config):
            # Test runs twice: once with bd, once with br
            result = get_ready_work_items()
            assert result is not None
    """
    original = get_active_backend()
    set_active_backend(request.param)
    yield request.param
    set_active_backend(original)


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
        with patch("pokepoke.desktop.terminal_ui.set_terminal_banner"):
            yield


@pytest.fixture(autouse=True)
def _suppress_terminal_ui_lazy_init():
    """Prevent lazy initialization of DesktopUI during tests.

    terminal_ui.ui is resolved via __getattr__ and triggers DesktopUI()
    which calls subprocess.run for git repo detection. Mock the module-level
    _ui so get_ui() returns a stub instead of the real instance.
    """
    from unittest.mock import MagicMock

    fake_ui = MagicMock()
    with patch("pokepoke.desktop.terminal_ui._ui", fake_ui), \
         patch("pokepoke.desktop.terminal_ui.get_ui", return_value=fake_ui):
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
def _force_sequential_mode(monkeypatch):
    """Force max_parallel_agents=1 so orchestrator tests use the sequential loop.

    The on-disk config (.pokepoke/config.yaml) may set max_parallel_agents>1.
    Without this fixture, orchestrator tests route through the parallel loop
    in parallel.py, where test mocks (applied to pokepoke.orchestration.orchestrator) don't
    take effect.  The unmocked parallel loop then runs REAL git add/commit
    via check_and_commit_main_repo, silently auto-committing (and destroying)
    any staged work in the host repository.
    """
    from pokepoke.config import load_config as _real_load_config

    def _patched_load_config(*args, **kwargs):
        cfg = _real_load_config(*args, **kwargs)
        cfg.max_parallel_agents = 1
        return cfg

    monkeypatch.setattr("pokepoke.orchestration.orchestrator.load_config", _patched_load_config)
    # Also patch the pokepoke path used by worktree-coverage tests
    monkeypatch.setattr("pokepoke.config.load_config", _patched_load_config,
                        raising=False)


@pytest.fixture(autouse=True)
def _fast_repo_guard(monkeypatch):
    """Ensure maintenance tests never block on repo cleanliness."""
    monkeypatch.setattr(
        "pokepoke.maintenance.maintenance_scheduler.wait_for_main_repo_clean",
        lambda *_, **__: True,
    )


@pytest.fixture(autouse=True)
def _isolate_lock_dir(tmp_path, monkeypatch):
    """Redirect file locks to a per-test temp directory.

    All file locks flow through coordination._lock_dir() which defaults to
    .pokepoke/locks/ relative to the CWD.  This directory is shared across
    all git worktrees, so concurrent test runs contend on the same lock
    files and hang indefinitely.

    By redirecting to tmp_path we get complete per-test (and per-xdist-worker)
    isolation with zero cross-worktree contention.
    """
    lock_dir = tmp_path / ".pokepoke" / "locks"

    def _isolated_lock_dir():
        os.makedirs(lock_dir, exist_ok=True)
        return lock_dir

    monkeypatch.setattr("pokepoke.worktrees.coordination._lock_dir", _isolated_lock_dir)


@pytest.fixture(autouse=True, scope="session")
def _mock_cleanup_lock_global():
    """Prevent file locks from hitting the filesystem during tests.

    The real locks use filelock which hangs when orchestrator processes
    hold the lock or when xdist workers contend.  Replace with no-op
    context managers globally.

    This covers every module that imports a lock helper at the top level.
    Dynamic imports (e.g. worktree_cleanup importing manifest_lock inside
    a function body) are handled by _isolate_lock_dir which redirects the
    underlying lock directory to an isolated tmp path.

    Session-scoped for performance: these no-op replacements are the same
    for every test and don't need per-test setup/teardown.
    """
    from contextlib import nullcontext

    patches = [
        # --- context-manager locks ---
        patch("pokepoke.git.repo_state_guard.cleanup_lock", lambda: nullcontext()),
        patch("pokepoke.git.repo_check.cleanup_lock", lambda: nullcontext(), create=True),
        patch("pokepoke.worktrees.worktree_finalization.merge_lock", lambda: nullcontext(), create=True),
        patch("pokepoke.worktrees.worktree_merge_handler.cleanup_lock",
              lambda timeout=600.0: nullcontext(), create=True),
        patch("pokepoke.worktrees.worktree_merge_handler.merge_lock",
              lambda timeout=600.0: nullcontext(), create=True),
        patch("pokepoke.worktrees.worktrees.with_worktree_lock",
              lambda timeout=300.0: nullcontext(), create=True),
        # --- lock-active polling helpers (return False = not locked) ---
        patch("pokepoke.git.repo_check.merge_lock_active", lambda: False, create=True),
        patch("pokepoke.agents.cleanup_agents.merge_lock_active", lambda: False, create=True),
        patch("pokepoke.utils.shutdown.merge_lock_active", lambda: False, create=True),
        patch("pokepoke.git.repo_state_guard.cleanup_lock_active", lambda: False, create=True),
        patch("pokepoke.git.repo_state_guard.merge_lock_active", lambda: False, create=True),
    ]

    for p in patches:
        p.start()
    yield
    for p in patches:
        p.stop()


@pytest.fixture(autouse=True)
def _block_real_git_repair(request, monkeypatch):
    """CRITICAL: Prevent preflight/repo_check from running real git add/commit/stash.

    Without this guard, any test that triggers preflight self-repair will
    run real 'git add -A' + 'git commit' against the host repo, silently
    auto-committing (and thus destroying) unrelated staged/unstaged work.

    Tests that explicitly test repair functions can opt out with:
        @pytest.mark.allow_git_repair
    """
    if request.node.get_closest_marker("allow_git_repair"):
        yield
        return
    monkeypatch.setattr(
        "pokepoke.utils.preflight_repair.repair_git_status",
        lambda error, repo_path: False,
    )
    monkeypatch.setattr(
        "pokepoke.utils.preflight_health.repair_git_status",
        lambda error, repo_path: False,
    )
    # Also stub out run_preflight_checks so tests that call run_orchestrator()
    # don't run real health checks against the host repo (which would fail
    # when there are unstaged files and cause the orchestrator to exit early).
    from pokepoke.utils.preflight_health import HealthCheckResult
    _passing = HealthCheckResult(passed=True)
    monkeypatch.setattr(
        "pokepoke.utils.preflight_health.run_preflight_checks",
        lambda *args, **kwargs: _passing,
    )
    # Stub the Copilot CLI auth preflight so run_orchestrator() never probes the
    # real CLI via subprocess (which the SDK launches in client.start()).
    # Returning None means "auth ok / inconclusive - continue".
    monkeypatch.setattr(
        "pokepoke.orchestration.orchestrator.run_copilot_auth_preflight",
        lambda *args, **kwargs: None,
        raising=False,
    )
    yield


@pytest.fixture(autouse=True)
def _block_real_bd_subprocess(request, monkeypatch):
    """CRITICAL: Prevent _run_bd from spawning real 'bd' subprocess calls.

    Without this, any code path reaching beads_query._run_bd hangs
    indefinitely when the beads daemon holds file locks.

    Patches _run_bd (not subprocess.run) to avoid globally affecting
    subprocess.run which is used by git operations and test fixtures.

    Opt out with: @pytest.mark.allow_real_bd
    """
    if request.node.get_closest_marker("allow_real_bd"):
        yield
        return

    import subprocess as _sp

    def _blocked(args, **kw):
        return _sp.CompletedProcess(["bd", *list(args)], 1, "", "blocked by test fixture")

    monkeypatch.setattr("pokepoke.beads.beads_query._run_bd", _blocked, raising=False)
    monkeypatch.setattr("pokepoke.beads.beads_management._run_bd", _blocked, raising=False)
    monkeypatch.setattr("pokepoke.beads.beads_metadata._run_bd", _blocked, raising=False)
    monkeypatch.setattr("pokepoke.beads.beads_hierarchy._run_bd", _blocked, raising=False)
    monkeypatch.setattr("pokepoke.agents.decomposition_agent._run_bd", _blocked, raising=False)
    monkeypatch.setattr("pokepoke.agents.post_mortem_issue_creator._run_bd", _blocked, raising=False)
    monkeypatch.setattr("pokepoke.models.model_sync_beads._run_bd", _blocked, raising=False)
    yield


@pytest.fixture(autouse=True)
def _enforce_subprocess_timeout(request, monkeypatch):
    """CRITICAL: Block real subprocess calls in tests by default.

    Tests must mock subprocess.run and subprocess.Popen. Any unmocked call
    will raise RuntimeError, preventing CI hangs caused by forgotten mocks.

    Opt out with: @pytest.mark.allow_subprocess (or the existing
    @pytest.mark.allow_real_bd / @pytest.mark.allow_git_repair for known
    integration tests).
    """
    # Allow explicit opt-out markers for tests that need real subprocesses
    if (request.node.get_closest_marker("allow_subprocess") or
        request.node.get_closest_marker("allow_real_bd") or
        request.node.get_closest_marker("allow_git_repair")):
        yield
        return

    def _blocked_run(*args, **kwargs):
        raise RuntimeError(
            "Unmocked subprocess.run invoked during test. "
            "Mock subprocess.run or mark the test with @pytest.mark.allow_subprocess to opt out."
        )

    class _BlockedPopen:
        def __init__(self, *args, **kwargs):
            raise RuntimeError(
                "Unmocked subprocess.Popen invoked during test. "
                "Mock subprocess.Popen or mark the test with @pytest.mark.allow_subprocess to opt out."
            )

    monkeypatch.setattr("subprocess.run", _blocked_run)
    monkeypatch.setattr("subprocess.Popen", _BlockedPopen)
    yield


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

