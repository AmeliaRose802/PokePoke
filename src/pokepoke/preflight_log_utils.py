"""Pre-flight health check logging, rate-limiting, and orchestration.

Prevents log spam when the same pre-flight failure repeats every poll cycle.
Logs on first occurrence and every Nth consecutive identical failure.
Also provides the handle_preflight_checks() entry point used by the orchestrator.
"""

from __future__ import annotations

from typing import Any

# Rate-limiting state for repeated preflight failure warnings
_preflight_fail_signature: str | None = None
_preflight_fail_count: int = 0
_PREFLIGHT_LOG_INTERVAL: int = 50


def format_preflight_errors(errors: list[Any]) -> str:
    """Format preflight errors into a concise summary string."""
    return "; ".join(f"{e.check_name}: {e.message}" for e in errors)


def should_log_preflight_warning(signature: str) -> bool:
    """Decide whether to log a preflight warning based on rate-limiting.

    Logs on first occurrence and every _PREFLIGHT_LOG_INTERVAL thereafter
    when the same error signature repeats consecutively.
    """
    global _preflight_fail_signature, _preflight_fail_count

    if signature != _preflight_fail_signature:
        _preflight_fail_signature = signature
        _preflight_fail_count = 1
        return True

    _preflight_fail_count += 1
    return _preflight_fail_count % _PREFLIGHT_LOG_INTERVAL == 0


def get_preflight_fail_count() -> int:
    """Return the current consecutive failure count."""
    return _preflight_fail_count


def reset_preflight_rate_limit() -> None:
    """Reset the rate-limiting state (e.g. after checks pass again)."""
    global _preflight_fail_signature, _preflight_fail_count
    _preflight_fail_signature = None
    _preflight_fail_count = 0


def handle_preflight_checks(
    main_repo_path: Any, run_logger: Any, cfg: Any = None,
) -> tuple[bool, bool]:
    """Run preflight health checks. Returns (should_continue, is_critical_failure)."""
    from pokepoke.preflight_health import run_preflight_checks
    if cfg is None:
        from pokepoke.config import get_config
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
        reset_preflight_rate_limit()
        print("✅ Pre-flight health checks passed")
        run_logger.log_orchestrator("Pre-flight health checks passed")
        for w in health_result.warnings:
            print(f"   ℹ️  {w}")
        return True, False

    details = format_preflight_errors(health_result.errors)
    print(f"\n❌ Pre-flight health checks failed ({len(health_result.errors)} error(s))")
    for e in health_result.errors:
        print(f"   • {e.check_name}: {e.message}")
    if health_result.self_repair_attempted:
        ok = health_result.self_repair_successful
        print(f"{'✅' if ok else '❌'} Self-repair {'completed successfully' if ok else 'failed'}")
    ph = cfg.preflight_health
    if health_result.has_critical_errors() and ph.fail_on_critical_errors:
        print("\n🚨 Critical health check failures detected - shutting down gracefully")
        run_logger.log_orchestrator(f"Critical health check failures - shutting down: {details}", level="ERROR")
        return False, True
    if health_result.has_environmental_errors() and ph.fail_on_environmental_errors:
        print("\n⚠️  Environmental health check failures detected - shutting down gracefully")
        run_logger.log_orchestrator(f"Environmental health check failures - shutting down: {details}", level="ERROR")
        if ph.graceful_shutdown_on_failure:
            return False, True
    for w in health_result.warnings:
        print(f"   ⚠️  Warning: {w}")
    if should_log_preflight_warning(details):
        count = get_preflight_fail_count()
        msg = f"Pre-flight checks failed but continuing: {details}"
        if count > 1:
            msg += f" (repeated {count} times, {count - 1} suppressed)"
        run_logger.log_orchestrator(msg, level="WARNING")
    return True, False
