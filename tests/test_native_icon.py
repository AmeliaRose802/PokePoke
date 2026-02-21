"""Tests for pokepoke.native_icon — Windows-specific native icon helper."""

import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch, call

import pokepoke.native_icon as native_icon_module
from pokepoke.native_icon import (
    set_native_window_icon,
    set_app_user_model_id,
    _apply_taskbar_icon,
)


def _make_shown_event() -> SimpleNamespace:
    """Create a fake ``shown`` event with a no-op wait."""
    return SimpleNamespace(wait=lambda _timeout: None)


def _make_events() -> SimpleNamespace:
    return SimpleNamespace(shown=_make_shown_event())


class TestSetNativeWindowIcon:
    def test_no_op_when_icon_missing(self, tmp_path) -> None:
        """Should silently return when the icon file doesn't exist."""
        window = SimpleNamespace(native=MagicMock(), events=_make_events())
        set_native_window_icon(window, tmp_path / "nonexistent.ico")

    def test_no_op_when_native_is_none(self, tmp_path) -> None:
        """Should silently return when window.native is not set."""
        icon = tmp_path / "pokepoke.ico"
        icon.write_bytes(b"")
        window = SimpleNamespace(events=_make_events())
        # Should not raise
        set_native_window_icon(window, icon)

    def test_no_op_on_non_windows(self, monkeypatch, tmp_path) -> None:
        """Should silently return on non-Windows platforms."""
        icon = tmp_path / "pokepoke.ico"
        icon.write_bytes(b"")
        window = SimpleNamespace(native=MagicMock(), events=_make_events())
        monkeypatch.setattr(native_icon_module.sys, "platform", "linux")
        set_native_window_icon(window, icon)

    def test_accepts_string_path(self, tmp_path) -> None:
        """Should accept string paths in addition to Path objects."""
        window = SimpleNamespace(events=_make_events())
        icon = tmp_path / "pokepoke.ico"
        icon.write_bytes(b"")
        # Should not raise with str path
        set_native_window_icon(window, str(icon))

    def test_waits_for_shown_event(self, tmp_path) -> None:
        """Should call shown.wait() before accessing native form."""
        icon = tmp_path / "pokepoke.ico"
        icon.write_bytes(b"")
        mock_shown = MagicMock()
        events = SimpleNamespace(shown=mock_shown)
        # No native — will return early after waiting
        window = SimpleNamespace(events=events)
        set_native_window_icon(window, icon)
        mock_shown.wait.assert_called_once_with(10)

    def test_ok_without_events(self, tmp_path) -> None:
        """Should handle window without events attribute gracefully."""
        icon = tmp_path / "pokepoke.ico"
        icon.write_bytes(b"")
        window = SimpleNamespace()  # no events, no native
        set_native_window_icon(window, icon)

    def test_sets_icon_via_invoke_when_required(self, tmp_path) -> None:
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
        window = SimpleNamespace(native=form, events=_make_events())

        with patch.dict(sys.modules, {
            "System.Drawing": mock_sys_drawing,
            "System": mock_system,
        }):
            set_native_window_icon(window, icon)

        mock_icon_cls.assert_called_once_with(str(icon))
        form.Invoke.assert_called_once()

    def test_sets_icon_directly_when_invoke_not_required(
        self, tmp_path
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
        window = SimpleNamespace(native=form, events=_make_events())

        with patch.dict(sys.modules, {
            "System.Drawing": mock_sys_drawing,
            "System": mock_system,
        }):
            set_native_window_icon(window, icon)

        mock_icon_cls.assert_called_once_with(str(icon))
        # Icon should be set directly, not via Invoke
        form.Invoke.assert_not_called()

    def test_swallows_exceptions(self, tmp_path) -> None:
        """Should not raise if .NET imports fail."""
        icon = tmp_path / "pokepoke.ico"
        icon.write_bytes(b"")

        form = MagicMock()
        window = SimpleNamespace(native=form, events=_make_events())

        # Force the .NET import to fail
        with patch.dict(sys.modules, {
            "System.Drawing": None,  # causes ImportError
        }):
            # Should not raise
            set_native_window_icon(window, icon)

    def test_sends_wm_seticon_after_setting_form_icon(self, tmp_path) -> None:
        """Should call _apply_taskbar_icon with the form's HWND."""
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
        form.Handle = 12345
        window = SimpleNamespace(native=form, events=_make_events())

        with patch.object(
            native_icon_module, "_apply_taskbar_icon"
        ) as mock_apply, patch.dict(sys.modules, {
            "System.Drawing": mock_sys_drawing,
            "System": mock_system,
        }):
            set_native_window_icon(window, icon)

        mock_apply.assert_called_once_with(12345, icon)


class TestSetAppUserModelId:
    def test_no_op_on_non_windows(self, monkeypatch) -> None:
        """Should silently return on non-Windows platforms."""
        monkeypatch.setattr(native_icon_module.sys, "platform", "linux")
        # Should not raise and should not call shell32
        with patch("ctypes.windll") as mock_windll:
            set_app_user_model_id()
            mock_windll.shell32.SetCurrentProcessExplicitAppUserModelID.assert_not_called()

    def test_calls_shell32_on_windows(self, monkeypatch) -> None:
        """Should call SetCurrentProcessExplicitAppUserModelID on Windows."""
        monkeypatch.setattr(native_icon_module.sys, "platform", "win32")
        mock_shell32 = MagicMock()
        with patch("ctypes.windll", create=True) as mock_windll:
            mock_windll.shell32 = mock_shell32
            set_app_user_model_id("Test.AppId")
        mock_shell32.SetCurrentProcessExplicitAppUserModelID.assert_called_once_with(
            "Test.AppId"
        )

    def test_uses_default_app_id(self, monkeypatch) -> None:
        """Should use APP_USER_MODEL_ID constant when no app_id provided."""
        monkeypatch.setattr(native_icon_module.sys, "platform", "win32")
        mock_shell32 = MagicMock()
        with patch("ctypes.windll", create=True) as mock_windll:
            mock_windll.shell32 = mock_shell32
            set_app_user_model_id()
        mock_shell32.SetCurrentProcessExplicitAppUserModelID.assert_called_once_with(
            native_icon_module.APP_USER_MODEL_ID
        )

    def test_swallows_exceptions(self, monkeypatch) -> None:
        """Should not raise if ctypes call fails."""
        monkeypatch.setattr(native_icon_module.sys, "platform", "win32")
        with patch("ctypes.windll", create=True) as mock_windll:
            mock_windll.shell32.SetCurrentProcessExplicitAppUserModelID.side_effect = (
                OSError("access denied")
            )
            # Should not raise
            set_app_user_model_id()


class TestApplyTaskbarIcon:
    def test_sends_wm_seticon_messages(self, tmp_path) -> None:
        """Should load icon and send WM_SETICON for both small and big."""
        icon = tmp_path / "pokepoke.ico"
        icon.write_bytes(b"")

        mock_user32 = MagicMock()
        mock_user32.LoadImageW.return_value = 999  # fake HICON

        with patch("ctypes.windll", create=True) as mock_windll:
            mock_windll.user32 = mock_user32
            _apply_taskbar_icon(12345, icon)

        mock_user32.LoadImageW.assert_called_once()
        # WM_SETICON = 0x0080, ICON_BIG = 1, ICON_SMALL = 0
        expected_calls = [
            call(12345, 0x0080, 1, 999),  # ICON_BIG
            call(12345, 0x0080, 0, 999),  # ICON_SMALL
        ]
        mock_user32.SendMessageW.assert_has_calls(expected_calls)

    def test_skips_when_load_image_fails(self, tmp_path) -> None:
        """Should not send WM_SETICON when LoadImageW returns 0."""
        icon = tmp_path / "pokepoke.ico"
        icon.write_bytes(b"")

        mock_user32 = MagicMock()
        mock_user32.LoadImageW.return_value = 0  # failure

        with patch("ctypes.windll", create=True) as mock_windll:
            mock_windll.user32 = mock_user32
            _apply_taskbar_icon(12345, icon)

        mock_user32.SendMessageW.assert_not_called()
