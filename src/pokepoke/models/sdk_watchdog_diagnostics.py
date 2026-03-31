"""Periodic process tree diagnostics for SDKWatchdog."""
import asyncio
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from pokepoke.utils.process_utils import log_process_tree_snapshot as _log_process_tree_snapshot

from .sdk_event_handler import SessionStats

logger = logging.getLogger(__name__)

_SNAPSHOT_INTERVAL = 60.0  # Periodic process tree snapshot interval in seconds


def resolve_diagnostics_log_path(handler: Any) -> Path | None:
    """Derive the tool_diagnostics.log path from the handler's item logger."""
    if handler and hasattr(handler, '_item_logger') and handler._item_logger:
        item_log_path = getattr(handler._item_logger, 'log_path', None)
        if item_log_path:
            # log_path is {run_dir}/items/{item}.log → run_dir is .parent.parent
            run_dir = Path(item_log_path).parent.parent
            return run_dir / "tool_diagnostics.log"
    return None


async def periodic_diagnostics_loop(
    stats: SessionStats,
    handler: Any,
    diag_log_path: Path | None,
    stop_event: asyncio.Event,
) -> None:
    """Background task: snapshot the process tree every 60s while tools are active."""
    while not stop_event.is_set():
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=_SNAPSHOT_INTERVAL)
            break  # stop_event was set
        except TimeoutError:
            pass  # interval elapsed, take a snapshot

        tool_times = stats.get('tool_start_times', {})
        if not tool_times:
            continue

        now = time.monotonic()
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        last_output = stats.get("last_tool_output")
        last_output_time = stats.get("last_tool_output_time", 0.0)
        output_age = None
        if last_output and last_output_time:
            output_age = max(0.0, now - float(last_output_time))
            last_output = " ".join(str(last_output).split())
            if len(last_output) > 200:
                last_output = last_output[:200] + "..."
        for tool_id, start_time in list(tool_times.items()):
            elapsed = now - start_time
            tool_name = "unknown"
            args_str = ""
            if handler and hasattr(handler, '_pending_tools'):
                tool_info = handler._pending_tools.get(tool_id, {})
                tool_name = tool_info.get('name', 'unknown')
                args_str = str(tool_info.get('args', {}))

            header = (
                f"[{ts}] SNAPSHOT tool_id={tool_id} tool={tool_name} "
                f"elapsed={elapsed:.0f}s"
            )
            if output_age is not None and last_output:
                logger.info(
                    "PERIODIC_DIAG: %s last_output_age=%.0fs last_output='%s'",
                    header, output_age, last_output,
                )
            else:
                logger.info("PERIODIC_DIAG: %s", header)

            # Capture the process tree via the existing utility
            _log_process_tree_snapshot(tool_name, args_str, elapsed, handler)

            # Append to dedicated diagnostics log
            if diag_log_path is None:
                continue
            try:
                with open(diag_log_path, 'a', encoding='utf-8') as f:
                    f.write(f"{header}\n")
                    f.write(f"  args: {args_str}\n")
                    if output_age is not None and last_output:
                        f.write(f"  last_output_age: {output_age:.0f}s\n")
                        f.write(f"  last_output: {last_output}\n")
                    f.write("\n")
            except Exception as e:
                logger.debug("Failed to write to diagnostics log: %s", e)
