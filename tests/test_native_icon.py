"""Tests for pokepoke.native_icon — Windows-specific native icon helper."""

import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pokepoke.native_icon as native_icon_module
from pokepoke.native_icon import set_native_window_icon


class TestSetNativeWindowIcon:
    def test_no_op_when_icon_missing(self, tmp_path) -> None:
        """Should silently return when the icon file doesn't exist."""
        window = SimpleNamespace(native=MagicMock())
        set_native_window_icon(window, tmp_path / "nonexistent.ico")

    def test_no_op_when_native_is_none(self, tmp_path) -> None:
        """Should silently return when window.native is not set."""
        icon = tmp_path / "pokepoke.ico"
        icon.write_bytes(b"")
        window = SimpleNamespace()  # no 'native' attribute
        # Should not raise
        set_native_window_icon(window, icon)

    def test_no_op_on_non_windows(self, monkeypatch, tmp_path) -> None:
        """Should silently return on non-Windows platforms."""
        icon = tmp_path / "pokepoke.ico"
        icon.write_bytes(b"")
        window = SimpleNamespace(native=MagicMock())
        monkeypatch.setattr(native_icon_module.sys, "platform", "linux")
        set_native_window_icon(window, icon)

    def test_accepts_string_path(self, tmp_path) -> None:
        """Should accept string paths in addition to Path objects."""
        window = SimpleNamespace()  # no native attr → early return
        icon = tmp_path / "pokepoke.ico"
        icon.write_bytes(b"")
        # Should not raise with str path
        set_native_window_icon(window, str(icon))

    def test_sets_icon_via_invoke_when_required(self, monkeypatch, tmp_path) -> None:
        """Should use Form.Invoke when InvokeRequired is True."""
        icon = tmp_path / "pokepoke.ico"
        icon.write_bytes(b"")

        mock_icon_cls = MagicMock()
        mock_action_cls = MagicMock()
        mock_sys_drawing = MagicMock()
        mock_sys_drawing.Icon = mock_icon_cls
        mock_system = MagicMock()
        mock_system.Action = mock_action_cls

        form = MagicMock()
        form.InvokeRequired = True
        window = SimpleNamespace(native=form)

        with patch.dict(sys.modules, {
            "System.Drawing": mock_sys_drawing,
            "System": mock_system,
        }):
            set_native_window_icon(window, icon)

        mock_icon_cls.assert_called_once_with(str(icon))
        form.Invoke.assert_called_once()

    def test_sets_icon_directly_when_invoke_not_required(
        self, monkeypatch, tmp_path
    ) -> None:
        """Should set Form.Icon directly when on the UI thread."""
        icon = tmp_path / "pokepoke.ico"
        icon.write_bytes(b"")

        mock_icon_cls = MagicMock()
        mock_action_cls = MagicMock()
        mock_sys_drawing = MagicMock()
        mock_sys_drawing.Icon = mock_icon_cls
        mock_system = MagicMock()
        mock_system.Action = mock_action_cls

        form = MagicMock()
        form.InvokeRequired = False
        window = SimpleNamespace(native=form)

        with patch.dict(sys.modules, {
            "System.Drawing": mock_sys_drawing,
            "System": mock_system,
        }):
            set_native_window_icon(window, icon)

        mock_icon_cls.assert_called_once_with(str(icon))
        # Icon should be set directly, not via Invoke
        form.Invoke.assert_not_called()

    def test_swallows_exceptions(self, monkeypatch, tmp_path) -> None:
        """Should not raise if .NET imports fail."""
        icon = tmp_path / "pokepoke.ico"
        icon.write_bytes(b"")

        form = MagicMock()
        window = SimpleNamespace(native=form)

        # Force the .NET import to fail
        with patch.dict(sys.modules, {
            "System.Drawing": None,  # causes ImportError
        }):
            # Should not raise
            set_native_window_icon(window, icon)
