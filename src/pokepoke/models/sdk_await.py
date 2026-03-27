"""Await-completion and tool-watchdog helpers for the Copilot SDK integration.

The implementation now lives in :class:`~pokepoke.models.sdk_watchdog.SDKWatchdog`.
This module re-exports the class and backward-compatible module-level functions.
"""

from .sdk_watchdog import (
    _HB_INTERVAL as _HB_INTERVAL,
)
from .sdk_watchdog import (
    SDKWatchdog as SDKWatchdog,
)
from .sdk_watchdog import (
    _await_completion as _await_completion,
)
from .sdk_watchdog import (
    _check_tool_watchdog as _check_tool_watchdog,
)

__all__ = [
    "SDKWatchdog",
    "_await_completion",
    "_check_tool_watchdog",
    "_HB_INTERVAL",
]
