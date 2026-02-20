"""Windows-specific native icon helper for pywebview.

pywebview's ``icon`` parameter in ``webview.start()`` is documented as
"Supported only on GTK/QT".  On Windows the WinForms backend extracts the
icon from ``sys.executable`` (python.exe → Python logo) via
``ExtractIconW`` and ignores the ``icon`` state entirely.

This module provides a workaround that accesses the underlying WinForms
Form (``window.native``) and sets its ``Icon`` property directly using the
.NET ``System.Drawing.Icon`` class.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any


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
    except Exception:
        # Non-fatal — fall back to whatever icon pywebview set.
        pass
