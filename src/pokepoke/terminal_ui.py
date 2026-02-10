"""Terminal UI utilities for PowerShell display enhancements and TUI."""

import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pokepoke.textual_ui import TextualUI


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


# Global UI instance - use Textual UI
from pokepoke.textual_ui import TextualUI

ui: "TextualUI" = TextualUI()

