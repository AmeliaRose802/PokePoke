"""Legacy desktop bridge (WebSocket) removed.

The desktop UI now uses pywebview with direct in-process calls.
This module is kept as a stub to prevent accidental imports of
the removed WebSocket implementation.
"""

from __future__ import annotations

DEFAULT_WS_PORT = 9160


class DesktopBridge:
    """Legacy class placeholder. The WebSocket bridge has been removed."""

    def __init__(self, port: int = DEFAULT_WS_PORT) -> None:
        raise RuntimeError(
            "DesktopBridge has been removed. "
            "Use DesktopAPI (pywebview) instead."
        )
