"""Legacy desktop bridge (WebSocket) removed.

The desktop UI now uses pywebview with direct in-process calls.
This module is kept as a stub to prevent accidental imports of
the removed WebSocket implementation.
"""

from __future__ import annotations

from typing import Optional

DEFAULT_WS_PORT = 9160


class DesktopBridge:
    """Legacy class placeholder. The WebSocket bridge has been removed."""

    def __init__(self, port: int = DEFAULT_WS_PORT) -> None:
        raise RuntimeError(
            "DesktopBridge has been removed. "
            "Use DesktopAPI (pywebview) instead."
        )

    @property
    def is_running(self) -> bool:  # pragma: no cover - never used
        return False

    @property
    def client_count(self) -> int:  # pragma: no cover - never used
        return 0

    def start(self) -> None:  # pragma: no cover - never used
        raise RuntimeError("DesktopBridge has been removed.")

    def stop(self) -> None:  # pragma: no cover - never used
        raise RuntimeError("DesktopBridge has been removed.")

    def send_log(
        self, message: str, target: str = "orchestrator", style: Optional[str] = None
    ) -> None:  # pragma: no cover - never used
        raise RuntimeError("DesktopBridge has been removed.")
