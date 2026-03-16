"""Runtime patches for pywebview quirks we encounter on Windows."""

from __future__ import annotations

import logging
import shutil
import sys
from typing import TYPE_CHECKING, Any
from types import ModuleType

if TYPE_CHECKING:

    class _EdgeChromeInstance:
        """Minimal type for EdgeChrome instance."""

        webview: Any

logger = logging.getLogger(__name__)

_PATCHED_EDGE_MODULES: set[str] = set()


def apply_runtime_patches() -> None:
    """Apply any pywebview workarounds needed for the current platform."""
    if sys.platform != "win32":
        return

    _patch_edgechromium_clear_user_data()


def _patch_edgechromium_clear_user_data(edge_module: ModuleType | None = None) -> None:
    """Ensure EdgeChromium shutdown tolerates a missing CoreWebView2 instance."""
    module = edge_module
    if module is None:
        try:
            from webview.platforms import edgechromium as module
        except Exception as exc:
            logger.debug("pywebview EdgeChromium patch skipped: %s", exc)
            return

    module_id = getattr(module, "__name__", "webview.platforms.edgechromium")
    if module_id in _PATCHED_EDGE_MODULES:
        return

    EdgeChrome = getattr(module, "EdgeChrome", None)
    if EdgeChrome is None:
        _PATCHED_EDGE_MODULES.add(module_id)
        return

    edge_logger = getattr(module, "logger", logger)
    convert = getattr(module, "Convert", None)
    process_cls = getattr(module, "Process", None)
    state = getattr(module, "_state", {})

    def _safe_clear_user_data(self: _EdgeChromeInstance) -> None:
        if not state.get("private_mode"):
            return

        webview_obj = getattr(self, "webview", None)
        core = getattr(webview_obj, "CoreWebView2", None) if webview_obj else None
        process = None

        if core is not None and convert is not None and process_cls is not None:
            try:
                process_id = convert.ToInt32(core.BrowserProcessId)
                process = process_cls.GetProcessById(process_id)
            except Exception as exc:  # pragma: no cover - best-effort logging
                edge_logger.debug(
                    "pywebview patch: failed to capture BrowserProcessId: %s", exc
                )
        else:
            edge_logger.debug(
                "pywebview patch: CoreWebView2 missing during shutdown; skipping process wait"
            )

        try:
            if webview_obj is not None:
                webview_obj.Dispose()
        except Exception as exc:  # pragma: no cover - best-effort logging
            edge_logger.debug(
                "pywebview patch: failed to dispose WebView2 control: %s", exc
            )

        if process is not None:
            try:
                process.WaitForExit(3000)
            except Exception as exc:  # pragma: no cover - best-effort logging
                edge_logger.debug(
                    "pywebview patch: failed waiting for WebView2 browser exit: %s", exc
                )

        try:
            shutil.rmtree(self.user_data_folder)
        except Exception as exc:  # pragma: no cover - best-effort logging
            edge_logger.warning(f"Failed to delete user data folder: {exc}")

    EdgeChrome.clear_user_data = _safe_clear_user_data
    _PATCHED_EDGE_MODULES.add(module_id)


__all__ = ["apply_runtime_patches"]
