"""Support functions extracted from parallel.py for file length compliance."""

import concurrent.futures
import logging
import time
from typing import Any

from pokepoke.process_utils import kill_orphaned_copilot_processes
from pokepoke.types import BeadsWorkItem, SessionStats, WorkItemResult
from pokepoke.logging_utils import RunLogger
from pokepoke import terminal_ui

logger = logging.getLogger(__name__)

_Future = concurrent.futures.Future[WorkItemResult]


def handle_preflight_checks(
    main_repo_path: Any, run_logger: RunLogger,
) -> tuple[bool, bool]:
    """Run preflight health checks. Returns (should_continue, is_critical_failure)."""
    from pokepoke.config import get_config
    from pokepoke.preflight_health import run_preflight_checks

    cfg = get_config()
    if not cfg.preflight_health.enabled:
        print("⏭️  Pre-flight health checks disabled via config")
        run_logger.log_orchestrator("Pre-flight health checks disabled via config")
        return True, False

    health_config = {k: getattr(cfg.preflight_health, k) for k in (
        'min_disk_space_gb', 'lock_timeout_seconds', 'worktree_test_timeout',
        'max_orphan_worktrees', 'git_operation_timeout', 'enable_self_repair',
        'max_repair_attempts',
    )}
    health_result = run_preflight_checks(repo_path=main_repo_path, config=health_config)

    if health_result.passed:
        print("✅ Pre-flight health checks passed")
        run_logger.log_orchestrator("Pre-flight health checks passed")
        for w in health_result.warnings:
            print(f"   ℹ️  {w}")
        return True, False

    print(f"\n❌ Pre-flight health checks failed ({len(health_result.errors)} error(s))")
    for e in health_result.errors:
        print(f"   • {e.check_name}: {e.message}")

    if health_result.self_repair_attempted:
        status = "completed successfully" if health_result.self_repair_successful else "failed"
        emoji = "✅" if health_result.self_repair_successful else "❌"
        print(f"{emoji} Self-repair {status}")

    if health_result.has_critical_errors() and cfg.preflight_health.fail_on_critical_errors:
        print("\n🚨 Critical health check failures detected - shutting down gracefully")
        run_logger.log_orchestrator("Critical health check failures - shutting down", level="ERROR")
        return False, True

    if health_result.has_environmental_errors() and cfg.preflight_health.fail_on_environmental_errors:
        print("\n⚠️  Environmental health check failures detected - shutting down gracefully")
        run_logger.log_orchestrator("Environmental health check failures - shutting down", level="ERROR")
        if cfg.preflight_health.graceful_shutdown_on_failure:
            return False, True

    for w in health_result.warnings:
        print(f"   ⚠️  Warning: {w}")
    run_logger.log_orchestrator(
        f"Pre-flight checks failed but continuing (errors: {len(health_result.errors)})", level="WARNING")
    return True, False


def finalize_workers(
    futures: dict[_Future, BeadsWorkItem],
    session_stats: SessionStats,
    start_time: float,
    total_requests: int,
    run_logger: RunLogger,
    record_fn: Any,
) -> tuple[int, bool]:
    """Wait for remaining workers and collect results."""
    timeout_occurred = False
    if not futures:
        return total_requests, timeout_occurred
    run_logger.log_orchestrator(f"Waiting for {len(futures)} active workers")
    try:
        for fut in concurrent.futures.as_completed(list(futures.keys()), timeout=300):
            item = futures.pop(fut, BeadsWorkItem(id="?", title="?", status="?", priority=0, issue_type="?"))
            try:
                result = fut.result()
                run_logger.log_orchestrator(f"Worker completed {item.id}")
            except Exception as e:
                run_logger.log_orchestrator(f"Worker failed {item.id}: {e}", level="ERROR")
                result = WorkItemResult(success=False, request_count=0)
            total_requests += result.request_count
            try:
                record_fn(item, result, session_stats, run_logger)
            except Exception as exc:
                logger.warning(f"record_fn failed {item.id}: {exc}", exc_info=True)
                run_logger.log_orchestrator(f"record_fn error {item.id}: {exc}", level="ERROR")
            terminal_ui.ui.update_stats(session_stats, time.time() - start_time)
    except concurrent.futures.TimeoutError:
        cancelled = sum(1 for fut in list(futures.keys()) if fut.cancel())
        run_logger.log_orchestrator(f"Cancelled {cancelled} workers; timeout waiting", level="WARNING")
        timeout_occurred = True
    run_logger.log_orchestrator("Workers completed")
    kill_orphaned_copilot_processes(expected_count=0)
    terminal_ui.ui.update_stats(session_stats, time.time() - start_time)
    return total_requests, timeout_occurred
