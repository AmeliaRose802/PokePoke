"""Tests for legacy desktop bridge stub."""

import pytest

from pokepoke.desktop_bridge import DesktopBridge, DEFAULT_WS_PORT


def test_desktop_bridge_removed() -> None:
    with pytest.raises(RuntimeError, match="removed"):
        DesktopBridge()


def test_desktop_bridge_removed_with_port() -> None:
    with pytest.raises(RuntimeError, match="removed"):
        DesktopBridge(port=DEFAULT_WS_PORT)
