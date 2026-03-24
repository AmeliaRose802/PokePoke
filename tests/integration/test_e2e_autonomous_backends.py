"""E2E validation for PokePoke autonomous mode with both backends.

Tests that autonomous mode works identically with both bd and br backends.
This is the final acceptance test for the backend abstraction layer.
"""
import subprocess
from unittest.mock import patch

import pytest

from pokepoke.beads.beads_query import BD_CONFIG, BR_CONFIG, get_active_backend, set_active_backend
from pokepoke.orchestration.work_item_selection import autonomous_selection
from pokepoke.types import BeadsWorkItem


def _make_item(
    item_id: str,
    title: str = "Test Task",
    priority: int = 1,
    issue_type: str = "task",
    status: str = "open",
    labels: list[str] | None = None,
) -> BeadsWorkItem:
    """Helper to create a BeadsWorkItem for testing."""
    return BeadsWorkItem(
        id=item_id,
        title=title,
        status=status,
        priority=priority,
        issue_type=issue_type,
        description=f"Description for {item_id}",
        labels=labels or [],
    )


@pytest.mark.parametrize("backend_config", [BD_CONFIG, BR_CONFIG], ids=["bd", "br"])
def test_autonomous_selection_with_backend(backend_config):
    """Test autonomous work item selection works with both backends."""
    original = get_active_backend()
    try:
        set_active_backend(backend_config)

        # Create test items
        items = [
            _make_item("test-1", priority=2),
            _make_item("test-2", priority=1),  # Higher priority (lower number)
            _make_item("test-3", priority=3),
        ]

        # Autonomous selection should pick highest priority (test-2)
        selected = autonomous_selection(items)

        assert selected is not None
        assert selected.id == "test-2"
        assert get_active_backend() == backend_config

    finally:
        set_active_backend(original)


@pytest.mark.parametrize("backend_config", [BD_CONFIG, BR_CONFIG], ids=["bd", "br"])
def test_backend_query_operations(backend_config, monkeypatch: pytest.MonkeyPatch):
    """Test that query operations work with both backends."""
    original = get_active_backend()
    try:
        set_active_backend(backend_config)

        from pokepoke.beads import beads_query

        # Mock subprocess to avoid actual CLI calls
        mock_result = subprocess.CompletedProcess(
            args=[backend_config.binary, "ready", "--json"],
            returncode=0,
            stdout='[{"id": "mock-1", "title": "Mock", "status": "open", "priority": 1, "issue_type": "task", "description": "Mock item", "labels": []}]',
            stderr="",
        )

        # Mock _run_bd directly
        with patch.object(beads_query, "_run_bd", return_value=mock_result) as mock_run:
            items = beads_query.get_ready_work_items()

            # Verify the mock was called
            assert mock_run.called

            # Verify correct command was used
            call_args = mock_run.call_args[0][0]
            assert call_args == ["ready", "--json"]

            # Verify items were parsed correctly
            assert len(items) == 1
            assert items[0].id == "mock-1"

    finally:
        set_active_backend(original)


@pytest.mark.parametrize("backend_config", [BD_CONFIG, BR_CONFIG], ids=["bd", "br"])
def test_backend_sync_strategy_selection(backend_config):
    """Test that setting backend automatically selects correct sync strategy."""
    original = get_active_backend()
    try:
        set_active_backend(backend_config)

        from pokepoke.beads.sync_strategy import DaemonSync, ExplicitSync, get_active_sync_strategy

        strategy = get_active_sync_strategy()

        # bd uses DaemonSync, br uses ExplicitSync
        if backend_config.binary == "bd":
            assert isinstance(strategy, DaemonSync)
        elif backend_config.binary == "br":
            assert isinstance(strategy, ExplicitSync)

        assert strategy._backend == backend_config

    finally:
        set_active_backend(original)


def test_backend_switching():
    """Test that switching backends updates all state correctly."""
    original = get_active_backend()
    try:
        from pokepoke.beads.sync_strategy import DaemonSync, ExplicitSync, get_active_sync_strategy

        # Switch to bd
        set_active_backend(BD_CONFIG)
        assert get_active_backend() == BD_CONFIG
        assert isinstance(get_active_sync_strategy(), DaemonSync)

        # Switch to br
        set_active_backend(BR_CONFIG)
        assert get_active_backend() == BR_CONFIG
        assert isinstance(get_active_sync_strategy(), ExplicitSync)

        # Switch back to bd
        set_active_backend(BD_CONFIG)
        assert get_active_backend() == BD_CONFIG
        assert isinstance(get_active_sync_strategy(), DaemonSync)

    finally:
        set_active_backend(original)


def test_concurrent_backend_operations():
    """Test that backend state remains consistent under concurrent access.

    Multiple threads rapidly switch the active backend and verify that
    ``get_active_backend()`` always returns a valid config and the sync
    strategy stays in agreement with it.
    """
    import concurrent.futures
    import threading

    original = get_active_backend()
    errors: list[str] = []
    lock = threading.Lock()
    iterations_per_thread = 50

    def _switch_loop(config):  # type: CLIBackendConfig
        from pokepoke.beads.sync_strategy import get_active_sync_strategy
        for _ in range(iterations_per_thread):
            set_active_backend(config)
            active = get_active_backend()
            strategy = get_active_sync_strategy()

            # The active backend must always be one of the two valid configs
            if active not in (BD_CONFIG, BR_CONFIG):
                with lock:
                    errors.append(f"Invalid active backend: {active}")

            # The strategy must reference a valid backend
            if strategy._backend not in (BD_CONFIG, BR_CONFIG):
                with lock:
                    errors.append(f"Invalid strategy backend: {strategy._backend}")

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            futures = [
                pool.submit(_switch_loop, BD_CONFIG),
                pool.submit(_switch_loop, BR_CONFIG),
                pool.submit(_switch_loop, BD_CONFIG),
                pool.submit(_switch_loop, BR_CONFIG),
            ]
            concurrent.futures.wait(futures)
            # Re-raise any exception from a worker thread
            for f in futures:
                f.result()

        assert not errors, "Concurrent errors detected:\n" + "\n".join(errors)

        # After all threads finish, state must still be consistent
        final = get_active_backend()
        assert final in (BD_CONFIG, BR_CONFIG)
        from pokepoke.beads.sync_strategy import get_active_sync_strategy
        assert get_active_sync_strategy()._backend == final

    finally:
        set_active_backend(original)
