"""Windows-specific native icon helper for pywebview.

pywebview's ``icon`` parameter in ``webview.start()`` is documented as
"Supported only on GTK/QT".  On Windows the WinForms backend extracts the
icon from ``sys.executable`` (python.exe → Python logo) via
``ExtractIconW`` and ignores the ``icon`` state entirely.

This module provides two workarounds:

1. :func:`set_app_user_model_id` — must be called **before** any window is
   created.  It calls ``SetCurrentProcessExplicitAppUserModelID`` so that
   Windows associates the process's taskbar button with the correct
   application identity, allowing the taskbar icon to be set independently
   of ``python.exe``.

2. :func:`set_native_window_icon` — called after the pywebview window is
   shown.  It sets ``Form.Icon`` via pythonnet *and* sends ``WM_SETICON``
   Win32 messages so both the title bar and the taskbar button show the
   correct icon.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

#: App User Model ID used to register the process with Windows shell.
APP_USER_MODEL_ID = "PokePoke.Desktop"


def set_app_user_model_id(app_id: str = APP_USER_MODEL_ID) -> None:
    """Set the Windows App User Model ID for the current process.

    Must be called **before** any windows are created so that Windows
    correctly associates the taskbar button with the application and
    displays the application icon rather than the ``python.exe`` icon.

    On non-Windows platforms this is a silent no-op.

    Parameters
    ----------
    app_id:
        The App User Model ID string (e.g. ``"PokePoke.Desktop"``).
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
    except Exception as e:
        logger.debug(f"Failed to set app user model ID: {e}")


def _apply_taskbar_icon(hwnd: int, icon_path: Path) -> None:
    """Send ``WM_SETICON`` to *hwnd* so the taskbar button shows *icon_path*.

    Uses ``LoadImageW`` to load the icon from disk and ``SendMessageW`` to
    push both the small (16×16) and large (32×32) icon variants.

    Parameters
    ----------
    hwnd:
        Native window handle (HWND) as a Python :class:`int`.
    icon_path:
        Path to the ``.ico`` file to load.
    """
    import ctypes

    LR_LOADFROMFILE = 0x00000010
    LR_DEFAULTSIZE = 0x00000040
    IMAGE_ICON = 1
    WM_SETICON = 0x0080
    ICON_SMALL = 0
    ICON_BIG = 1

    hicon = ctypes.windll.user32.LoadImageW(
        None, str(icon_path), IMAGE_ICON, 0, 0, LR_LOADFROMFILE | LR_DEFAULTSIZE
    )
    if not hicon:
        return
    ctypes.windll.user32.SendMessageW(hwnd, WM_SETICON, ICON_BIG, hicon)
    ctypes.windll.user32.SendMessageW(hwnd, WM_SETICON, ICON_SMALL, hicon)


def set_native_window_icon(window: Any, icon_path: str | Path) -> None:
    """Set the window icon on Windows via the native WinForms Form.

    Must be called after the pywebview window is fully created (e.g. in the
    ``func`` callback of ``webview.start()``).

    On non-Windows platforms or when the icon file is missing this is a
    silent no-op.

    Parameters
    ----------
    window:
        A pywebview ``Window`` object (returned by
        ``webview.create_window()``).
    icon_path:
        Filesystem path to a ``.ico`` file.
    """
    icon_path = Path(icon_path)
    if not icon_path.exists():
        return

    if sys.platform != "win32":
        return

    try:
        # The ``func`` callback of ``webview.start()`` fires on a background
        # thread *before* the WinForms Form is fully created.  We must wait
        # for the ``shown`` event so that ``window.native`` (the Form) is
        # available.
        shown = getattr(getattr(window, "events", None), "shown", None)
        if shown is not None and hasattr(shown, "wait"):
            shown.wait(10)

        form = getattr(window, "native", None)
        if form is None:
            return
        # Import .NET types (available because pywebview already loaded
        # pythonnet and System.Drawing on Windows).
        from System.Drawing import Icon as DotNetIcon  # type: ignore[import-not-found]
        from System import Action  # type: ignore[import-not-found]

        icon = DotNetIcon(str(icon_path))

        def _apply() -> None:
            form.Icon = icon

        # The func callback runs on a background thread, but WinForms
        # requires UI mutations on the UI thread.
        if form.InvokeRequired:
            form.Invoke(Action(_apply))
        else:
            _apply()

        # Send WM_SETICON via Win32 so the taskbar button also reflects the
        # custom icon.  Form.Icon alone does not always refresh the taskbar
        # entry; WM_SETICON ensures both title-bar and taskbar are updated.
        try:
            hwnd = int(form.Handle)
            _apply_taskbar_icon(hwnd, icon_path)
        except Exception as e:
            logger.debug(f"Failed to apply taskbar icon: {e}")
    except Exception as e:
        # Non-fatal — fall back to whatever icon pywebview set.
        logger.debug(f"Failed to set native window icon: {e}")
