"""Session activity watchdog helpers."""

import asyncio
from collections.abc import Callable
from pathlib import Path
from typing import Any


def maybe_start_activity_watchdog(
    item_logger: Any | None,
    proj_config: Any,
    get_last_activity_time: Callable[[], float] | None = None,
) -> tuple[asyncio.Task[bool] | None, asyncio.Event]:
    """Start the activity watchdog if enabled, returning (task, abort_event)."""
    watchdog_abort: asyncio.Event = asyncio.Event()
    watchdog_task: asyncio.Task[bool] | None = None

    if item_logger and proj_config.activity_watchdog.enabled:
        log_path = Path(item_logger.log_path)
        watchdog_task = asyncio.create_task(
            activity_watchdog(
                log_path,
                float(proj_config.activity_watchdog.timeout_seconds),
                float(proj_config.activity_watchdog.check_interval_seconds),
                watchdog_abort,
                get_last_activity_time=get_last_activity_time,
            )
        )
        print(f"[SDK] Activity watchdog enabled (timeout: {proj_config.activity_watchdog.timeout_seconds}s)\n")

    return watchdog_task, watchdog_abort


async def cancel_watchdog(watchdog_task: asyncio.Task[bool] | None) -> None:
    """Cancel watchdog task if it is still running."""
    if watchdog_task and not watchdog_task.done():
        watchdog_task.cancel()
        await asyncio.gather(watchdog_task, return_exceptions=True)


async def activity_watchdog(
    log_path: Path,
    timeout_seconds: float,
    check_interval_seconds: float,
    abort_event: asyncio.Event,
    get_last_activity_time: Callable[[], float] | None = None,
) -> bool:
    """Monitor activity and detect hung sessions."""
    try:
        loop = asyncio.get_event_loop()
        last_mtime = log_path.stat().st_mtime if log_path.exists() else 0.0
        last_activity_time = (
            get_last_activity_time() if get_last_activity_time is not None else loop.time()
        )

        while True:
            await asyncio.sleep(check_interval_seconds)
            current_mtime = log_path.stat().st_mtime if log_path.exists() else 0.0
            current_time = loop.time()

            if get_last_activity_time is not None:
                current_activity_time = get_last_activity_time()
                if current_activity_time > last_activity_time:
                    last_activity_time = current_activity_time
                else:
                    idle_duration = current_time - last_activity_time
                    if idle_duration >= timeout_seconds:
                        print(f"\n⚠️  ACTIVITY WATCHDOG: No output for {int(idle_duration)}s (threshold: {int(timeout_seconds)}s)")
                        print("   Aborting hung session...")
                        abort_event.set()
                        return True
            elif current_mtime > last_mtime:
                last_mtime = current_mtime
                last_activity_time = current_time
            else:
                idle_duration = current_time - last_activity_time
                if idle_duration >= timeout_seconds:
                    print(f"\n⚠️  ACTIVITY WATCHDOG: No output for {int(idle_duration)}s (threshold: {int(timeout_seconds)}s)")
                    print("   Aborting hung session...")
                    abort_event.set()
                    return True

    except asyncio.CancelledError:
        return False
    except Exception as e:
        print(f"\n⚠️  Activity watchdog error: {e}")
        return False
