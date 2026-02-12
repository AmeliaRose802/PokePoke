"""Tests for PokePoke desktop UI adapter (pywebview)."""

import builtins
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pokepoke.desktop_ui as desktop_ui_module
import pokepoke.terminal_ui as terminal_ui_module
from pokepoke.desktop_ui import DesktopUI
from pokepoke.terminal_ui import use_desktop_ui


class FakeWebviewModule:
    def __init__(self) -> None:
        self.created_kwargs: dict[str, object] = {}
        self.started = False
        self.window = SimpleNamespace()

    def create_window(self, **kwargs):
        self.created_kwargs = dict(kwargs)
        return self.window

    def start(self, func=None, debug=False):
        self.started = True
        if func:
            func()


class FakeTimer:
    def __init__(self, _delay, func):
        self.func = func
        self.started = False
        self.daemon = False

    def start(self):
        self.started = True

    def cancel(self):
        return None


class TestFindFrontendDist:
    def test_returns_none_when_missing(self, monkeypatch, tmp_path) -> None:
        fake_src = tmp_path / "src" / "pokepoke"
        fake_src.mkdir(parents=True)
        fake_file = fake_src / "desktop_ui.py"
        fake_file.write_text("", encoding="utf-8")

        monkeypatch.setattr(desktop_ui_module, "__file__", str(fake_file))

        assert desktop_ui_module._find_frontend_dist() is None

    def test_returns_dist_when_present(self, monkeypatch, tmp_path) -> None:
        fake_src = tmp_path / "src" / "pokepoke"
        fake_src.mkdir(parents=True)
        fake_file = fake_src / "desktop_ui.py"
        fake_file.write_text("", encoding="utf-8")

        dist_dir = tmp_path / "desktop" / "dist"
        dist_dir.mkdir(parents=True)
        (dist_dir / "index.html").write_text("<html></html>", encoding="utf-8")

        monkeypatch.setattr(desktop_ui_module, "__file__", str(fake_file))

        assert desktop_ui_module._find_frontend_dist() == dist_dir


class TestDesktopUIOutputRouting:
    def test_output_contexts(self) -> None:
        ui = DesktopUI()
        assert ui._target_buffer == "orchestrator"
        with ui.agent_output():
            assert ui._target_buffer == "agent"
        assert ui._target_buffer == "orchestrator"

    def test_styled_output_context(self) -> None:
        ui = DesktopUI()
        assert ui._current_style is None
        with ui.styled_output("bold red"):
            assert ui._current_style == "bold red"
        assert ui._current_style is None

    def test_set_style(self) -> None:
        ui = DesktopUI()
        ui.set_style("green")
        assert ui._current_style == "green"
        ui.set_style(None)
        assert ui._current_style is None

    def test_print_redirect_routes_to_api(self) -> None:
        ui = DesktopUI()
        ui._api = MagicMock()
        ui._print_redirect("Hello, world!")
        ui._api.push_log.assert_called_once_with(
            "Hello, world!", "orchestrator", None
        )

    def test_print_redirect_respects_target_and_style(self) -> None:
        ui = DesktopUI()
        ui._api = MagicMock()
        ui._target_buffer = "agent"
        ui._current_style = "bold red"
        ui._print_redirect("boom")
        ui._api.push_log.assert_called_once_with("boom", "agent", "bold red")

    def test_print_redirect_passes_through_stderr(self) -> None:
        ui = DesktopUI()
        ui._api = MagicMock()
        ui._original_print = MagicMock()
        ui._print_redirect("err", file=sys.stderr)
        ui._api.push_log.assert_not_called()
        ui._original_print.assert_called_once()

    def test_print_redirect_flushes_buffer(self, monkeypatch) -> None:
        ui = DesktopUI()
        ui._api = MagicMock()
        monkeypatch.setattr(desktop_ui_module.threading, "Timer", FakeTimer)

        ui._print_redirect("partial", end="", flush=True)
        assert ui._flush_timer is not None
        assert ui._flush_timer.started is True

        ui._deferred_flush()
        ui._api.push_log.assert_called_once_with(
            "partial", "orchestrator", None
        )


class TestDesktopUIStateUpdates:
    def test_update_header(self) -> None:
        ui = DesktopUI()
        ui._api = MagicMock()
        ui.update_header("item-1", "Fix bug", "in_progress")
        ui._api.push_work_item.assert_called_once_with(
            "item-1", "Fix bug", "in_progress"
        )

    def test_set_current_agent(self) -> None:
        ui = DesktopUI()
        ui._api = MagicMock()
        ui.set_current_agent("pokepoke_agent_42")
        ui._api.push_agent_name.assert_called_once_with("pokepoke_agent_42")

    def test_update_stats(self) -> None:
        from pokepoke.types import SessionStats, AgentStats

        ui = DesktopUI()
        ui._api = MagicMock()
        stats = SessionStats(agent_stats=AgentStats())
        ui.update_stats(stats, 60.0)
        ui._api.push_stats.assert_called_once_with(stats, 60.0)

    def test_log_helpers(self) -> None:
        ui = DesktopUI()
        ui._api = MagicMock()
        ui.log_message("hello")
        ui.log_orchestrator("orch", "green")
        ui.log_agent("agent")
        assert ui._api.push_log.call_count == 3

    def test_set_session_start_time(self) -> None:
        ui = DesktopUI()
        ui._api = MagicMock()
        ui.set_session_start_time(1000.0)
        ui._api.set_session_start_time.assert_called_once_with(1000.0)


class TestDesktopUILifecycle:
    def test_start_stop_and_exit(self) -> None:
        ui = DesktopUI()
        original_print = builtins.print
        try:
            ui.start()
            assert ui.is_running is True
            assert builtins.print is not original_print
            ui.stop()
            assert ui.is_running is False
            assert builtins.print is original_print
            ui.stop_and_capture()
            assert ui.is_running is False
            ui.exit()
            assert ui.is_running is False
        finally:
            builtins.print = original_print


class TestDesktopUIRunWithOrchestrator:
    def test_run_with_orchestrator_success(self, monkeypatch, tmp_path) -> None:
        dist_dir = tmp_path / "dist"
        dist_dir.mkdir()
        (dist_dir / "index.html").write_text("<html></html>", encoding="utf-8")

        fake_webview = FakeWebviewModule()
        monkeypatch.setitem(sys.modules, "webview", fake_webview)
        monkeypatch.setattr(
            desktop_ui_module, "_find_frontend_dist", lambda: dist_dir
        )
        monkeypatch.setattr(desktop_ui_module, "request_shutdown", lambda: None)

        ui = DesktopUI()
        ui._api.set_window = MagicMock()
        original_print = builtins.print

        result = ui.run_with_orchestrator(lambda: 0)

        assert result == 0
        assert builtins.print is original_print
        assert fake_webview.started is True
        assert fake_webview.created_kwargs["url"].endswith("index.html")
        assert fake_webview.created_kwargs["js_api"] is ui._api
        ui._api.set_window.assert_called_once_with(fake_webview.window)

    def test_run_with_orchestrator_missing_frontend(self, monkeypatch) -> None:
        fake_webview = FakeWebviewModule()
        monkeypatch.setitem(sys.modules, "webview", fake_webview)
        monkeypatch.setattr(desktop_ui_module, "_find_frontend_dist", lambda: None)
        ui = DesktopUI()
        original_print = builtins.print

        result = ui.run_with_orchestrator(lambda: 0)

        assert result == 1
        assert builtins.print is original_print

    def test_run_with_orchestrator_exception(self, monkeypatch, tmp_path) -> None:
        dist_dir = tmp_path / "dist"
        dist_dir.mkdir()
        (dist_dir / "index.html").write_text("<html></html>", encoding="utf-8")

        fake_webview = FakeWebviewModule()
        monkeypatch.setitem(sys.modules, "webview", fake_webview)
        monkeypatch.setattr(
            desktop_ui_module, "_find_frontend_dist", lambda: dist_dir
        )
        monkeypatch.setattr(desktop_ui_module, "request_shutdown", lambda: None)

        ui = DesktopUI()
        ui._api = MagicMock()
        ui._api.set_window = MagicMock()

        def boom() -> int:
            raise RuntimeError("boom")

        result = ui.run_with_orchestrator(boom)

        assert result == 1
        assert ui._api.push_log.called

    def test_run_with_orchestrator_keyboard_interrupt(
        self, monkeypatch, tmp_path
    ) -> None:
        dist_dir = tmp_path / "dist"
        dist_dir.mkdir()
        (dist_dir / "index.html").write_text("<html></html>", encoding="utf-8")

        fake_webview = FakeWebviewModule()
        monkeypatch.setitem(sys.modules, "webview", fake_webview)
        monkeypatch.setattr(
            desktop_ui_module, "_find_frontend_dist", lambda: dist_dir
        )
        monkeypatch.setattr(desktop_ui_module, "request_shutdown", lambda: None)

        ui = DesktopUI()
        ui._api = MagicMock()
        ui._api.set_window = MagicMock()

        def interrupt() -> int:
            raise KeyboardInterrupt()

        result = ui.run_with_orchestrator(interrupt)

        assert result == 130


class TestUseDesktopUI:
    def test_switches_global_ui(self) -> None:
        original = terminal_ui_module.ui
        try:
            result = use_desktop_ui()
            assert isinstance(result, DesktopUI)
            assert terminal_ui_module.ui is result
        finally:
            terminal_ui_module.ui = original
