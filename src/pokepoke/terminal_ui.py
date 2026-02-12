"""Terminal UI utilities for PowerShell display enhancements and TUI."""

import sys
from typing import TYPE_CHECKING, Union

if TYPE_CHECKING:
    from pokepoke.textual_ui import TextualUI
    from pokepoke.desktop_ui import DesktopUI


def set_terminal_banner(text: str) -> None:
    """Set the PowerShell window title to display a banner."""
    if sys.platform != 'win32':
        return
    try:
        import ctypes
        ctypes.windll.kernel32.SetConsoleTitleW(text)
    except Exception:
        pass


def clear_terminal_banner() -> None:
    """Clear the terminal banner to default."""
    set_terminal_banner("PokePoke")


def format_work_item_banner(item_id: str, title: str, status: str = "In Progress") -> str:
    """Format a work item as a banner string."""
    max_title_length = 60
    if len(title) > max_title_length:
        title = title[:max_title_length - 3] + "..."
    return f"🚀 PokePoke: {item_id} - {title} [{status}]"


# Global UI instance - default to Textual UI, switchable to Desktop UI
from pokepoke.textual_ui import TextualUI

ui: Union["TextualUI", "DesktopUI"] = TextualUI()


def use_desktop_ui(port: int = 9160) -> "DesktopUI":
    """Switch the global UI to the desktop WebSocket-based UI.

    Call this before starting the orchestrator to use the desktop app
    instead of the terminal TUI.

    Args:
        port: WebSocket server port (default 9160).

    Returns:
        The DesktopUI instance that was installed as the global UI.
    """
    global ui
    from pokepoke.desktop_ui import DesktopUI
    desktop = DesktopUI(port=port)
    ui = desktop
    return desktop

