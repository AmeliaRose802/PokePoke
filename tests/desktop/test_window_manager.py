"""Tests for DesktopWindowManager — frontend discovery, window creation, icon, lifecycle."""

import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pokepoke.desktop.window_manager as wm_module
from pokepoke.desktop.window_manager import DesktopWindowManager


class _FakeWebview:
    """Minimal stand-in for the ``webview`` package."""

    def __init__(self) -> None:
        self.created_kwargs: dict[str, object] = {}
        self.start_kwargs: dict[str, object] = {}
        self.started = False
        self.window = SimpleNamespace()

    def create_window(self, **kwargs):
        self.created_kwargs = dict(kwargs)
        return self.window

    def start(self, func=None, debug=False, **kwargs):
        self.start_kwargs = dict(kwargs)
        self.started = True
        if func:
            func()


# ── resolve_frontend ──────────────────────────────────────────────────


class TestResolveFrontend:
    def test_returns_none_when_no_frontend_found(self, monkeypatch) -> None:
        monkeypatch.setattr(wm_module, "find_dev_server_url", lambda: None)
        monkeypatch.setattr(wm_module, "find_frontend_dist", lambda: None)

        wm = DesktopWindowManager()
        assert wm.resolve_frontend() is None
        assert wm.dist_dir is None
        assert wm.icon_path is None

    def test_returns_dist_url_when_no_dev_server(self, monkeypatch, tmp_path) -> None:
        dist_dir = tmp_path / "dist"
        dist_dir.mkdir()
        (dist_dir / "index.html").write_text("<html></html>", encoding="utf-8")

        monkeypatch.setattr(wm_module, "find_dev_server_url", lambda: None)
        monkeypatch.setattr(wm_module, "find_frontend_dist", lambda: dist_dir)

        wm = DesktopWindowManager()
        result = wm.resolve_frontend()

        assert result is not None
        url, is_dev = result
        assert url == str(dist_dir / "index.html")
        assert is_dev is False
        assert wm.dist_dir == dist_dir
        assert wm.icon_path == dist_dir / "pokepoke.ico"

    def test_returns_dev_url_when_dev_server_available(self, monkeypatch, tmp_path) -> None:
        dist_dir = tmp_path / "dist"
        dist_dir.mkdir()

        monkeypatch.setattr(wm_module, "find_dev_server_url", lambda: "http://localhost:5173")
        monkeypatch.setattr(wm_module, "find_frontend_dist", lambda: dist_dir)

        wm = DesktopWindowManager()
        result = wm.resolve_frontend()

        assert result is not None
        url, is_dev = result
        assert url == "http://localhost:5173"
        assert is_dev is True
        assert wm.dist_dir == dist_dir
        assert wm.icon_path == dist_dir / "pokepoke.ico"

    def test_dev_mode_with_no_dist_sets_icon_none(self, monkeypatch) -> None:
        monkeypatch.setattr(wm_module, "find_dev_server_url", lambda: "http://localhost:5173")
        monkeypatch.setattr(wm_module, "find_frontend_dist", lambda: None)

        wm = DesktopWindowManager()
        result = wm.resolve_frontend()

        assert result is not None
        url, is_dev = result
        assert url == "http://localhost:5173"
        assert is_dev is True
        assert wm.icon_path is None


# ── create_window ─────────────────────────────────────────────────────


class TestCreateWindow:
    def test_creates_window_with_standard_settings(self, monkeypatch) -> None:
        fake_webview = _FakeWebview()
        monkeypatch.setitem(sys.modules, "webview", fake_webview)
        monkeypatch.setattr(wm_module, "set_app_user_model_id", lambda: None)

        wm = DesktopWindowManager()
        api = MagicMock()
        window = wm.create_window("http://example.com", api)

        assert window is fake_webview.window
        assert wm.window is fake_webview.window
        assert fake_webview.created_kwargs["url"] == "http://example.com"
        assert fake_webview.created_kwargs["js_api"] is api
        assert fake_webview.created_kwargs["width"] == 1280
        assert fake_webview.created_kwargs["height"] == 800
        assert fake_webview.created_kwargs["text_select"] is True

    def test_calls_set_app_user_model_id_before_create(self, monkeypatch) -> None:
        call_order: list[str] = []

        class _TrackingWebview(_FakeWebview):
            def create_window(self, **kwargs):
                call_order.append("create_window")
                return super().create_window(**kwargs)

        fake_webview = _TrackingWebview()
        monkeypatch.setitem(sys.modules, "webview", fake_webview)

        def tracking_set_id() -> None:
            call_order.append("set_app_user_model_id")

        monkeypatch.setattr(wm_module, "set_app_user_model_id", tracking_set_id)

        wm = DesktopWindowManager()
        wm.create_window("http://example.com", MagicMock())

        assert call_order == ["set_app_user_model_id", "create_window"]


# ── apply_window_icon ─────────────────────────────────────────────────


class TestApplyWindowIcon:
    def test_applies_icon_when_path_set(self, monkeypatch, tmp_path) -> None:
        mock_set_icon = MagicMock()
        monkeypatch.setattr(wm_module, "set_native_window_icon", mock_set_icon)

        wm = DesktopWindowManager()
        wm._icon_path = tmp_path / "pokepoke.ico"
        window = SimpleNamespace()

        wm.apply_window_icon(window)
        mock_set_icon.assert_called_once_with(window, wm._icon_path)

    def test_does_nothing_when_no_icon_path(self, monkeypatch) -> None:
        mock_set_icon = MagicMock()
        monkeypatch.setattr(wm_module, "set_native_window_icon", mock_set_icon)

        wm = DesktopWindowManager()
        wm.apply_window_icon(SimpleNamespace())
        mock_set_icon.assert_not_called()

    def test_uses_internal_window_when_no_argument(self, monkeypatch, tmp_path) -> None:
        mock_set_icon = MagicMock()
        monkeypatch.setattr(wm_module, "set_native_window_icon", mock_set_icon)

        wm = DesktopWindowManager()
        wm._icon_path = tmp_path / "pokepoke.ico"
        wm._window = SimpleNamespace()

        wm.apply_window_icon()
        mock_set_icon.assert_called_once_with(wm._window, wm._icon_path)


# ── start_event_loop ──────────────────────────────────────────────────


class TestStartEventLoop:
    def test_passes_icon_when_file_exists(self, monkeypatch, tmp_path) -> None:
        icon = tmp_path / "pokepoke.ico"
        icon.write_bytes(b"")

        fake_webview = _FakeWebview()
        monkeypatch.setitem(sys.modules, "webview", fake_webview)

        wm = DesktopWindowManager()
        wm._icon_path = icon

        wm.start_event_loop(debug=True)

        assert fake_webview.started is True
        assert fake_webview.start_kwargs["icon"] == str(icon)

    def test_omits_icon_when_path_missing(self, monkeypatch, tmp_path) -> None:
        fake_webview = _FakeWebview()
        monkeypatch.setitem(sys.modules, "webview", fake_webview)

        wm = DesktopWindowManager()
        wm._icon_path = tmp_path / "nonexistent.ico"

        wm.start_event_loop()

        assert fake_webview.started is True
        assert "icon" not in fake_webview.start_kwargs

    def test_omits_icon_when_icon_path_none(self, monkeypatch) -> None:
        fake_webview = _FakeWebview()
        monkeypatch.setitem(sys.modules, "webview", fake_webview)

        wm = DesktopWindowManager()
        wm.start_event_loop()

        assert fake_webview.started is True
        assert "icon" not in fake_webview.start_kwargs

    def test_calls_on_loaded_callback(self, monkeypatch) -> None:
        fake_webview = _FakeWebview()
        monkeypatch.setitem(sys.modules, "webview", fake_webview)

        wm = DesktopWindowManager()
        loaded = []
        wm.start_event_loop(on_loaded=lambda: loaded.append(True))

        assert loaded == [True]


# ── is_debug_requested ────────────────────────────────────────────────


class TestIsDebugRequested:
    def test_true_in_dev_mode(self, monkeypatch) -> None:
        monkeypatch.delenv("POKEPOKE_DEBUG", raising=False)
        wm = DesktopWindowManager()
        assert wm.is_debug_requested(is_dev_mode=True) is True

    def test_true_when_env_var_set(self, monkeypatch) -> None:
        monkeypatch.setenv("POKEPOKE_DEBUG", "1")
        wm = DesktopWindowManager()
        assert wm.is_debug_requested(is_dev_mode=False) is True

    def test_false_when_neither(self, monkeypatch) -> None:
        monkeypatch.delenv("POKEPOKE_DEBUG", raising=False)
        wm = DesktopWindowManager()
        assert wm.is_debug_requested(is_dev_mode=False) is False
