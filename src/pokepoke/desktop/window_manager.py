"""Window management for PokePoke desktop UI.

Encapsulates frontend discovery, pywebview window creation,
native icon management, and the pywebview event-loop lifecycle.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pokepoke.desktop.frontend_discovery import find_dev_server_url, find_frontend_dist
from pokepoke.desktop.native_icon import set_app_user_model_id, set_native_window_icon

logger = logging.getLogger(__name__)


class DesktopWindowManager:
    """Manages pywebview window creation, frontend discovery, icon setup, and lifecycle."""

    def __init__(self) -> None:
        self._window: Any = None
        self._icon_path: Path | None = None
        self._dist_dir: Path | None = None

    # ── Properties ────────────────────────────────────────────────────

    @property
    def window(self) -> Any:
        """The pywebview window object, or ``None`` before creation."""
        return self._window

    @property
    def icon_path(self) -> Path | None:
        """Path to the PokePoke icon, set by :meth:`resolve_frontend`."""
        return self._icon_path

    @property
    def dist_dir(self) -> Path | None:
        """Frontend dist directory discovered by :meth:`resolve_frontend`."""
        return self._dist_dir

    # ── Frontend Discovery ────────────────────────────────────────────

    def resolve_frontend(self) -> tuple[str, bool] | None:
        """Find the frontend URL and determine whether dev mode is active.

        Returns ``(window_url, is_dev_mode)`` on success, or ``None``
        when no usable frontend can be located.  Also sets
        :attr:`icon_path` and :attr:`dist_dir` as side effects.
        """
        dev_url = find_dev_server_url()
        if dev_url:
            self._dist_dir = find_frontend_dist()  # still needed for icon
            self._icon_path = (
                self._dist_dir / "pokepoke.ico" if self._dist_dir else None
            )
            return dev_url, True

        self._dist_dir = find_frontend_dist()
        if self._dist_dir is None:
            return None

        self._icon_path = self._dist_dir / "pokepoke.ico"
        return str(self._dist_dir / "index.html"), False

    # ── Window Creation ───────────────────────────────────────────────

    def create_window(self, url: str, js_api: Any) -> Any:
        """Create a pywebview window with standard PokePoke settings.

        Calls :func:`set_app_user_model_id` before creating the window
        so Windows associates the correct taskbar identity.
        """
        import webview

        set_app_user_model_id()
        self._window = webview.create_window(
            title="PokePoke - Autonomous Workflow Manager",
            url=url,
            js_api=js_api,
            width=1280,
            height=800,
            min_size=(900, 600),
            text_select=True,
        )
        return self._window

    # ── Icon Management ───────────────────────────────────────────────

    def apply_window_icon(self, window: Any | None = None) -> None:
        """Apply the native PokePoke icon to *window*.

        Falls back to the internally stored window reference when
        *window* is not provided.
        """
        target = window if window is not None else self._window
        if self._icon_path is not None and target is not None:
            set_native_window_icon(target, self._icon_path)

    # ── Pywebview Lifecycle ───────────────────────────────────────────

    def start_event_loop(
        self,
        on_loaded: Callable[[], None] | None = None,
        *,
        debug: bool = False,
    ) -> None:
        """Run the pywebview main loop (blocks until the window closes).

        If an icon file exists on disk it is passed to ``webview.start``
        so that the taskbar / dock shows the PokePoke icon.
        """
        import webview

        start_kwargs: dict[str, Any] = {
            "func": on_loaded,
            "debug": debug,
        }
        if self._icon_path and self._icon_path.exists():
            start_kwargs["icon"] = str(self._icon_path)

        webview.start(**start_kwargs)

    def is_debug_requested(self, is_dev_mode: bool) -> bool:
        """Return whether debug mode should be enabled for the webview."""
        return is_dev_mode or os.environ.get(
            "POKEPOKE_DEBUG", ""
        ).lower() in ("1", "true")
