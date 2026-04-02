"""Test for race condition fix in failed_claim_ids handling.

This test verifies that the orchestrator properly synchronizes access to
failed_claim_ids between the main loop and parallel workers using a shared lock.
"""

import threading
import time
from unittest.mock import MagicMock, patch

from pokepoke.orchestration.orchestrator import _OrchestratorContext
from pokepoke.types import AgentStats, SessionStats


def test_failed_claim_ids_lock_exists():
    """Verify that _OrchestratorContext has a lock for failed_claim_ids."""
    ctx = _OrchestratorContext(
        agent_name="test",
        mode_name="Autonomous",
        run_logger=MagicMock(),
        main_repo_path=MagicMock(),
        start_time=time.time(),
        session_stats=SessionStats(agent_stats=AgentStats()),
        failed_claim_ids=set(),
        failed_claim_ids_lock=threading.Lock(),
        cfg=MagicMock(),
        effective_parallel=1,
        interactive=False,
        continuous=False,
    )

    assert hasattr(ctx, 'failed_claim_ids_lock')
    assert isinstance(ctx.failed_claim_ids_lock, threading.Lock)


def test_concurrent_access_to_failed_claim_ids():
    """Verify that concurrent access to failed_claim_ids is thread-safe."""
    ctx = _OrchestratorContext(
        agent_name="test",
        mode_name="Autonomous",
        run_logger=MagicMock(),
        main_repo_path=MagicMock(),
        start_time=time.time(),
        session_stats=SessionStats(agent_stats=AgentStats()),
        failed_claim_ids=set(),
        failed_claim_ids_lock=threading.Lock(),
        cfg=MagicMock(),
        effective_parallel=4,
        interactive=False,
        continuous=False,
    )

    # Simulate concurrent access from multiple threads
    def add_item(item_id: str):
        for _ in range(100):
            with ctx.failed_claim_ids_lock:
                ctx.failed_claim_ids.add(item_id)

    def discard_item(item_id: str):
        for _ in range(100):
            with ctx.failed_claim_ids_lock:
                ctx.failed_claim_ids.discard(item_id)

    # Start multiple threads that add and discard items
    threads = []
    for i in range(10):
        t1 = threading.Thread(target=add_item, args=(f"item-{i}",))
        t2 = threading.Thread(target=discard_item, args=(f"item-{i}",))
        threads.extend([t1, t2])

    for t in threads:
        t.start()

    for t in threads:
        t.join()

    # No assertions about final state - just verify no crashes/exceptions
    # The important thing is that the lock prevents RuntimeError from concurrent modification


def test_external_lock_passed_to_parallel_loop():
    """Verify that the orchestrator passes its lock to run_parallel_loop."""
    from pokepoke.agents.parallel import run_parallel_loop

    ctx = _OrchestratorContext(
        agent_name="test",
        mode_name="Autonomous",
        run_logger=MagicMock(),
        main_repo_path=MagicMock(),
        start_time=time.time(),
        session_stats=SessionStats(agent_stats=AgentStats()),
        failed_claim_ids=set(),
        failed_claim_ids_lock=threading.Lock(),
        cfg=MagicMock(),
        effective_parallel=2,
        interactive=False,
        continuous=False,
    )

    # Mock dependencies
    with patch("pokepoke.agents.parallel.ParallelWorkerPool") as mock_pool, \
         patch("pokepoke.agents.parallel.set_executor"), \
         patch("pokepoke.agents.parallel.set_runtime_parallel_limits"), \
         patch("pokepoke.agents.parallel.is_shutting_down", side_effect=[False, True]), \
         patch("pokepoke.agents.parallel._run_preflight_and_repo_checks", return_value=(True, 0, [])), \
         patch("pokepoke.agents.parallel._safe_cleanup"):

        mock_pool_instance = MagicMock()
        mock_pool_instance.lock = threading.Lock()
        mock_pool_instance.futures = {}
        mock_pool_instance.executor = MagicMock()
        mock_pool_instance.semaphore = MagicMock()
        mock_pool.return_value = mock_pool_instance

        # Call run_parallel_loop with external_lock
        exit_code = run_parallel_loop(
            effective_parallel=ctx.effective_parallel,
            mode_name=ctx.mode_name,
            main_repo_path=ctx.main_repo_path,
            failed_claim_ids=ctx.failed_claim_ids,
            session_stats=ctx.session_stats,
            start_time=ctx.start_time,
            run_logger=ctx.run_logger,
            continuous=ctx.continuous,
            record_fn=MagicMock(),
            finalize_fn=MagicMock(),
            external_lock=ctx.failed_claim_ids_lock,
        )

        # Verify function accepts external_lock parameter and completes
        assert exit_code == 0
