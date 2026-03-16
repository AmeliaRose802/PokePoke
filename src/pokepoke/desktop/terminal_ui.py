"""Terminal UI utilities for PowerShell display enhancements."""

from __future__ import annotations

import logging
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pokepoke.desktop.desktop_ui import DesktopUI

    # Declared for mypy; at runtime, __getattr__ provides lazy access.
    ui: DesktopUI

logger = logging.getLogger(__name__)


def set_terminal_banner(text: str) -> None:
    """Set the PowerShell window title to display a banner."""
    if sys.platform != 'win32':
        return
    try:
        import ctypes
        ctypes.windll.kernel32.SetConsoleTitleW(text)
    except Exception as e:
        logger.debug(f"Failed to set terminal banner: {e}")


def clear_terminal_banner() -> None:
    """Clear the terminal banner to default."""
    set_terminal_banner("PokePoke")


def format_work_item_banner(item_id: str, title: str, status: str = "In Progress") -> str:
    """Format a work item as a banner string."""
    max_title_length = 60
    if len(title) > max_title_length:
        title = title[:max_title_length - 3] + "..."
    return f"🚀 PokePoke: {item_id} - {title} [{status}]"


# Lazy-initialized global UI instance to avoid side effects at import time.
_ui: DesktopUI | None = None


def get_ui() -> DesktopUI:
    """Return the global DesktopUI, creating it on first access."""
    global _ui
    if _ui is None:
        from pokepoke.desktop.desktop_ui import DesktopUI
        _ui = DesktopUI()
    return _ui


def __getattr__(name: str) -> object:
    """Lazy module attribute for backward-compatible ``terminal_ui.ui`` access."""
    if name == "ui":
        return get_ui()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

