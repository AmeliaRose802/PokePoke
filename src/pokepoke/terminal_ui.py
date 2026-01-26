"""Terminal UI utilities for PowerShell display enhancements."""

import os
import sys
from typing import Optional


def set_terminal_banner(text: str) -> None:
    """Set the PowerShell window title to display a banner.
    
    Args:
        text: Text to display in the terminal title bar
    """
    # Only works on Windows with PowerShell
    if sys.platform != 'win32':
        return
    
    try:
        # Use PowerShell Host.UI.RawUI.WindowTitle to set the title
        # This works in both Windows PowerShell and PowerShell Core
        import ctypes
        ctypes.windll.kernel32.SetConsoleTitleW(text)
    except Exception:
        # Silently fail if we can't set the title
        pass


def clear_terminal_banner() -> None:
    """Clear the terminal banner by resetting to a neutral title."""
    set_terminal_banner("PokePoke")


def format_work_item_banner(item_id: str, title: str, status: str = "In Progress") -> str:
    """Format a work item as a banner string.
    
    Args:
        item_id: Beads work item ID
        title: Work item title
        status: Current status (default: "In Progress")
    
    Returns:
        Formatted banner string
    """
    # Truncate title if too long to fit in typical terminal title
    max_title_length = 60
    if len(title) > max_title_length:
        title = title[:max_title_length - 3] + "..."
    
    return f"🚀 PokePoke: {item_id} - {title} [{status}]"
