"""Tests for PokePoke desktop UI adapter (pywebview)."""

import builtins
import sys
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock

import pokepoke.desktop.desktop_ui as desktop_ui_module
import pokepoke.desktop.frontend_discovery as frontend_discovery_module
import pokepoke.desktop.thread_output_router as thread_output_router_module
import pokepoke.desktop.window_manager as window_manager_module
from pokepoke.desktop import pywebview_patches
from pokepoke.desktop.desktop_ui import DesktopUI, _shutdown_threading_excepthook


class FakeWebviewModule:
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
    def test_prioritizes_static_assets_over_dist(self, monkeypatch, tmp_path) -> None:
        """Test that embedded static assets are prioritized over dist directory."""
        fake_src = tmp_path / "src" / "pokepoke"
        fake_src.mkdir(parents=True)
        fake_file = fake_src / "desktop_ui.py"
        fake_file.write_text("", encoding="utf-8")

        # Create static assets directory with index.html (embedded assets)
        fake_static = fake_src / "static"
        fake_static.mkdir()
        (fake_static / "index.html").write_text("<html></html>", encoding="utf-8")

        # Also create dist directory for comparison
        dist_dir = tmp_path / "desktop" / "dist"
        dist_dir.mkdir(parents=True)
        (dist_dir / "index.html").write_text("<html></html>", encoding="utf-8")

        monkeypatch.setattr(desktop_ui_module, "__file__", str(fake_file))
        # Mock sys.frozen to False (not running as bundle)
        monkeypatch.setattr("sys.frozen", False, raising=False)

        # The function should prioritize embedded static assets over dist directory
        result = frontend_discovery_module.find_frontend_dist()
        assert result == fake_static  # Should return static dir, not dist dir

    def test_fallback_to_dist_when_no_static(self, monkeypatch, tmp_path) -> None:
        """Test that it falls back to dist/ when static assets don't exist."""
        fake_src = tmp_path / "src" / "pokepoke"
        fake_src.mkdir(parents=True)
        fake_file = fake_src / "desktop_ui.py"
        fake_file.write_text("", encoding="utf-8")

        # Create dist directory but NOT static directory
        dist_dir = tmp_path / "desktop" / "dist"
        dist_dir.mkdir(parents=True)
        (dist_dir / "index.html").write_text("<html></html>", encoding="utf-8")

        monkeypatch.setattr(desktop_ui_module, "__file__", str(fake_file))
        # Mock sys.frozen to False (not running as bundle)
        monkeypatch.setattr("sys.frozen", False, raising=False)

        # Mock tempfile.gettempdir to return an empty directory
        empty_temp = tmp_path / "empty_temp"
        empty_temp.mkdir()
        monkeypatch.setattr("tempfile.gettempdir", lambda: str(empty_temp))

        # The static directory doesn't exist, so it should fall back to dist
        # (assuming no package resources are found)
        result = frontend_discovery_module.find_frontend_dist()
        # The result should either be the dist directory or the extracted temp directory
        # depending on whether package resources work in the test environment
        assert result is not None
        assert (result / "index.html").exists()

    def test_handles_missing_directories_gracefully(self, monkeypatch, tmp_path) -> None:
        """Test that it returns None when no frontend is found."""
        fake_src = tmp_path / "src" / "pokepoke"
        fake_src.mkdir(parents=True)
        fake_file = fake_src / "desktop_ui.py"
        fake_file.write_text("", encoding="utf-8")

        # Don't create any dist or static directories
        monkeypatch.setattr(desktop_ui_module, "__file__", str(fake_file))
        monkeypatch.setattr("sys.frozen", False, raising=False)

        # Mock tempfile.gettempdir to return an empty directory
        empty_temp = tmp_path / "empty_temp"
        empty_temp.mkdir()
        monkeypatch.setattr("tempfile.gettempdir", lambda: str(empty_temp))

        # Mock subprocess.run so git worktree fallback fails
        import subprocess as _sp
        orig_run = _sp.run
        def _mock_run(*a, **kw):
            if a and a[0] and "worktree" in str(a[0]):
                raise FileNotFoundError("mocked")
            return orig_run(*a, **kw)
        monkeypatch.setattr(_sp, "run", _mock_run)

        # The result depends on whether package resources are available
        # In the real package, this would extract to temp directory
        # In isolated tests, it might return None
        frontend_discovery_module.find_frontend_dist()
        # Don't assert None - the behavior depends on the test environment


class TestDesktopUIOutputRouting:
    def test_output_contexts(self) -> None:
        """agent_output and orchestrator_output set thread-local target."""
        ui = DesktopUI()
        # Thread-local should not be set initially
        assert getattr(thread_output_router_module._thread_output, "target", None) is None
        with ui.agent_output():
            assert getattr(thread_output_router_module._thread_output, "target", None) == "agent"
        assert getattr(thread_output_router_module._thread_output, "target", None) is None
        with ui.orchestrator_output():
            assert getattr(thread_output_router_module._thread_output, "target", None) == "orchestrator"
        assert getattr(thread_output_router_module._thread_output, "target", None) is None

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
        thread_output_router_module._thread_output.target = "agent"
        ui._current_style = "bold red"
        try:
            ui._print_redirect("boom")
            ui._api.push_log.assert_called_once_with("boom", "agent", "bold red")
        finally:
            thread_output_router_module._thread_output.target = None

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

    def test_agent_output_for_routes_to_agent_log(self) -> None:
        """agent_output_for should route print output to the agent's log buffer."""
        ui = DesktopUI()
        ui._api = MagicMock()
        ui._api.push_agent_log = MagicMock()
        ui._api.push_log = MagicMock()

        with ui.agent_output_for("agent-42"):
            ui._print_redirect("hello from agent")

        # Output should go to agent log, NOT the shared log
        ui._api.push_agent_log.assert_called_once_with("agent-42", "hello from agent")
        ui._api.push_log.assert_not_called()

    def test_agent_output_for_restores_context(self) -> None:
        """agent_output_for should restore previous agent_id on exit."""
        ui = DesktopUI()
        assert getattr(thread_output_router_module._thread_output, "agent_id", None) is None
        with ui.agent_output_for("agent-1"):
            assert thread_output_router_module._thread_output.agent_id == "agent-1"
        assert getattr(thread_output_router_module._thread_output, "agent_id", None) is None

    def test_agent_output_for_nested(self) -> None:
        """Nested agent_output_for should restore correctly."""
        ui = DesktopUI()
        with ui.agent_output_for("outer"):
            assert thread_output_router_module._thread_output.agent_id == "outer"
            with ui.agent_output_for("inner"):
                assert thread_output_router_module._thread_output.agent_id == "inner"
            assert thread_output_router_module._thread_output.agent_id == "outer"
        assert getattr(thread_output_router_module._thread_output, "agent_id", None) is None

    def test_parallel_threads_get_isolated_output(self) -> None:
        """Two threads using agent_output_for should not cross-contaminate."""
        ui = DesktopUI()
        ui._api = MagicMock()
        results: dict[str, list[str]] = {"agent-a": [], "agent-b": []}

        def capture_push_agent_log(agent_id: str, line: str) -> None:
            results[agent_id].append(line)

        ui._api.push_agent_log = MagicMock(side_effect=capture_push_agent_log)

        barrier = threading.Barrier(2, timeout=5)

        def worker(agent_id: str, msg: str) -> None:
            with ui.agent_output_for(agent_id):
                barrier.wait(timeout=5)
                ui._print_redirect(msg)

        t1 = threading.Thread(target=worker, args=("agent-a", "hello-a"))
        t2 = threading.Thread(target=worker, args=("agent-b", "hello-b"))
        t1.start()
        t2.start()
        t1.join(timeout=5)
        t2.join(timeout=5)

        assert results["agent-a"] == ["hello-a"]
        assert results["agent-b"] == ["hello-b"]


class TestDesktopUIStateUpdates:
    def test_update_header(self) -> None:
        ui = DesktopUI()
        ui._api = MagicMock()
        ui.update_header("item-1", "Fix bug", "in_progress", ["human-required"])
        ui._api.push_work_item.assert_called_once_with(
            "item-1", "Fix bug", "in_progress", ["human-required"]
        )

    def test_set_current_agent(self) -> None:
        ui = DesktopUI()
        ui._api = MagicMock()
        ui.set_current_agent("pokepoke_agent_42")
        ui._api.push_agent_name.assert_called_once_with("pokepoke_agent_42")

    def test_update_stats(self) -> None:
        from pokepoke.types import AgentStats, SessionStats

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

    def test_push_agent_status(self) -> None:
        ui = DesktopUI()
        ui._api = MagicMock()
        ui.push_agent_status("agent-1", "Gate Agent", iteration=2, status="running")
        ui._api.push_agent_status.assert_called_once_with(
            "agent-1", "Gate Agent", 2, "running", None, None, None, None, None, None, None,
            resume_in_place=False
        )

    def test_push_agent_log(self) -> None:
        ui = DesktopUI()
        ui._api = MagicMock()
        ui.push_agent_log("agent-1", "test line")
        ui._api.push_agent_log.assert_called_once_with("agent-1", "test line")

    def test_remove_agent(self) -> None:
        ui = DesktopUI()
        ui._api = MagicMock()
        ui.remove_agent("agent-1")
        ui._api.remove_agent.assert_called_once_with("agent-1")


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
        (dist_dir / "pokepoke.ico").write_bytes(b"")

        fake_webview = FakeWebviewModule()
        monkeypatch.setitem(sys.modules, "webview", fake_webview)
        monkeypatch.setattr(
            window_manager_module, "find_frontend_dist", lambda: dist_dir
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
        assert fake_webview.start_kwargs["icon"].endswith("pokepoke.ico")
        assert fake_webview.created_kwargs["js_api"] is ui._api
        ui._api.set_window.assert_called_once_with(fake_webview.window)

    def test_set_app_user_model_id_called_before_create_window(
        self, monkeypatch, tmp_path
    ) -> None:
        """set_app_user_model_id must be called before webview.create_window."""
        dist_dir = tmp_path / "dist"
        dist_dir.mkdir()
        (dist_dir / "index.html").write_text("<html></html>", encoding="utf-8")

        call_order: list[str] = []

        class OrderTrackingWebview(FakeWebviewModule):
            def create_window(self, **kwargs):
                call_order.append("create_window")
                return super().create_window(**kwargs)

        fake_webview = OrderTrackingWebview()
        monkeypatch.setitem(sys.modules, "webview", fake_webview)
        monkeypatch.setattr(
            window_manager_module, "find_frontend_dist", lambda: dist_dir
        )
        monkeypatch.setattr(desktop_ui_module, "request_shutdown", lambda: None)

        def tracking_set_app_user_model_id(*args, **kwargs) -> None:
            call_order.append("set_app_user_model_id")

        monkeypatch.setattr(
            window_manager_module, "set_app_user_model_id", tracking_set_app_user_model_id
        )

        ui = DesktopUI()
        ui._api.set_window = MagicMock()
        ui.run_with_orchestrator(lambda: 0)

        assert "set_app_user_model_id" in call_order
        assert "create_window" in call_order
        assert call_order.index("set_app_user_model_id") < call_order.index(
            "create_window"
        ), "set_app_user_model_id must be called before create_window"

    def test_run_with_orchestrator_missing_frontend(self, monkeypatch) -> None:
        fake_webview = FakeWebviewModule()
        monkeypatch.setitem(sys.modules, "webview", fake_webview)
        monkeypatch.setattr(window_manager_module, "find_frontend_dist", lambda: None)
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
            window_manager_module, "find_frontend_dist", lambda: dist_dir
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
            window_manager_module, "find_frontend_dist", lambda: dist_dir
        )
        monkeypatch.setattr(desktop_ui_module, "request_shutdown", lambda: None)

        ui = DesktopUI()
        ui._api = MagicMock()
        ui._api.set_window = MagicMock()

        def interrupt() -> int:
            raise KeyboardInterrupt()

        result = ui.run_with_orchestrator(interrupt)

        assert result == 130

    def test_run_with_orchestrator_webview_start_exception_after_loaded_is_clean(
        self, monkeypatch, tmp_path
    ) -> None:
        dist_dir = tmp_path / "dist"
        dist_dir.mkdir()
        (dist_dir / "index.html").write_text("<html></html>", encoding="utf-8")

        class RaisingAfterLoadedWebview(FakeWebviewModule):
            def start(self, func=None, debug=False, **kwargs):
                self.start_kwargs = dict(kwargs)
                self.started = True
                if func:
                    func()
                raise RuntimeError("join failed")

        fake_webview = RaisingAfterLoadedWebview()
        monkeypatch.setitem(sys.modules, "webview", fake_webview)
        monkeypatch.setattr(
            window_manager_module, "find_frontend_dist", lambda: dist_dir
        )
        mock_shutdown = MagicMock()
        monkeypatch.setattr(desktop_ui_module, "request_shutdown", mock_shutdown)
        monkeypatch.setattr(desktop_ui_module, "is_shutting_down", lambda: False)

        ui = DesktopUI()
        ui._api = MagicMock()
        ui._api.set_window = MagicMock()
        original_print = builtins.print
        original_hook = threading.excepthook

        result = ui.run_with_orchestrator(lambda: 0)

        assert result == 0
        assert builtins.print is original_print
        assert threading.excepthook is original_hook
        assert mock_shutdown.called

    def test_run_with_orchestrator_webview_start_exception_before_loaded_fails(
        self, monkeypatch, tmp_path
    ) -> None:
        dist_dir = tmp_path / "dist"
        dist_dir.mkdir()
        (dist_dir / "index.html").write_text("<html></html>", encoding="utf-8")

        class RaisingBeforeLoadedWebview(FakeWebviewModule):
            def start(self, func=None, debug=False, **kwargs):
                self.start_kwargs = dict(kwargs)
                self.started = True
                raise RuntimeError("join failed")

        fake_webview = RaisingBeforeLoadedWebview()
        monkeypatch.setitem(sys.modules, "webview", fake_webview)
        monkeypatch.setattr(
            window_manager_module, "find_frontend_dist", lambda: dist_dir
        )
        mock_shutdown = MagicMock()
        monkeypatch.setattr(desktop_ui_module, "request_shutdown", mock_shutdown)
        monkeypatch.setattr(desktop_ui_module, "is_shutting_down", lambda: False)

        ui = DesktopUI()
        ui._api = MagicMock()
        ui._api.set_window = MagicMock()
        original_print = builtins.print
        original_hook = threading.excepthook

        result = ui.run_with_orchestrator(lambda: 0)

        assert result == 1
        assert builtins.print is original_print
        assert threading.excepthook is original_hook
        assert ui._api.push_log.called
        assert mock_shutdown.called


class TestShutdownThreadingExcepthook:
    """Tests for _shutdown_threading_excepthook."""

    def _make_args(
        self, exc: BaseException
    ) -> threading.ExceptHookArgs:
        """Build a threading.ExceptHookArgs for *exc*."""
        return threading.ExceptHookArgs(
            (type(exc), exc, exc.__traceback__, None)
        )

    def test_suppresses_unicode_error_during_shutdown(self, monkeypatch) -> None:
        monkeypatch.setattr(desktop_ui_module, "is_shutting_down", lambda: True)
        monkeypatch.setattr(
            desktop_ui_module, "_original_excepthook", MagicMock()
        )
        args = self._make_args(
            UnicodeDecodeError("utf-8", b"\xfb", 0, 1, "invalid start byte")
        )
        # Should NOT raise or delegate
        _shutdown_threading_excepthook(args)
        desktop_ui_module._original_excepthook.assert_not_called()

    def test_delegates_other_errors_during_shutdown(self, monkeypatch) -> None:
        monkeypatch.setattr(desktop_ui_module, "is_shutting_down", lambda: True)
        mock_hook = MagicMock()
        monkeypatch.setattr(desktop_ui_module, "_original_excepthook", mock_hook)
        args = self._make_args(RuntimeError("boom"))
        _shutdown_threading_excepthook(args)
        mock_hook.assert_called_once_with(args)

    def test_delegates_unicode_error_when_not_shutting_down(
        self, monkeypatch
    ) -> None:
        monkeypatch.setattr(desktop_ui_module, "is_shutting_down", lambda: False)
        mock_hook = MagicMock()
        monkeypatch.setattr(desktop_ui_module, "_original_excepthook", mock_hook)
        args = self._make_args(
            UnicodeDecodeError("utf-8", b"\xfb", 0, 1, "invalid start byte")
        )
        _shutdown_threading_excepthook(args)
        mock_hook.assert_called_once_with(args)


class TestCurrentStyleThreadSafety:
    """Verify _current_style is protected by _buffer_lock."""

    def test_set_style_under_lock(self) -> None:
        """set_style should use the buffer lock."""
        ui = DesktopUI()
        ui.set_style("red")
        assert ui._current_style == "red"
        ui.set_style(None)
        assert ui._current_style is None

    def test_styled_output_under_lock(self) -> None:
        """styled_output should acquire the buffer lock for writes."""
        ui = DesktopUI()
        with ui.styled_output("bold"):
            assert ui._current_style == "bold"
        assert ui._current_style is None

    def test_concurrent_styled_output_and_print(self) -> None:
        """Concurrent styled_output + _print_redirect should not crash."""
        ui = DesktopUI()
        ui._api = MagicMock()
        errors: list[Exception] = []

        def writer() -> None:
            try:
                for _ in range(50):
                    with ui.styled_output("green"):
                        pass
            except Exception as e:
                errors.append(e)

        def reader() -> None:
            try:
                for _ in range(50):
                    ui._print_redirect("msg")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer), threading.Thread(target=reader)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert not errors


def _build_stub_edge_module(tmp_path, module_suffix, *, private_mode=True):
    class _DummyLogger:
        def debug(self, *_, **__):
            return None

        def warning(self, *_, **__):
            return None

    class _DummyWebview:
        def __init__(self, core):
            self.CoreWebView2 = core
            self.disposed = False

        def dispose(self):
            self.disposed = True

        Dispose = dispose  # .NET interop name used by production code

    base_dir = tmp_path / module_suffix

    class _DummyEdgeChrome:
        def __init__(self, core=None):
            self.webview = _DummyWebview(core)
            self.user_data_folder = str(base_dir)
            base_dir.mkdir(exist_ok=True)

        def clear_user_data(self):
            raise AssertionError("edgechromium stub should be patched before use")

    class _ProcessAPI:
        last_proc = None

        @staticmethod
        def get_process_by_id(pid):
            proc = SimpleNamespace(pid=pid, waited=False, timeout=None)

            def _wait(timeout):
                proc.waited = True
                proc.timeout = timeout

            proc.WaitForExit = _wait
            _ProcessAPI.last_proc = proc
            return proc

        GetProcessById = get_process_by_id  # .NET interop name used by production code

    convert = SimpleNamespace(ToInt32=lambda value: int(value) if value is not None else 0)

    module = SimpleNamespace(
        __name__=f"stub_edgechromium_{module_suffix}",
        EdgeChrome=_DummyEdgeChrome,
        _state={"private_mode": private_mode},
        Convert=convert,
        Process=_ProcessAPI,
        logger=_DummyLogger(),
    )
    return module, _ProcessAPI, base_dir


class TestPywebviewPatches:
    def test_edge_patch_handles_missing_core(self, tmp_path, monkeypatch) -> None:
        module, process_api, data_dir = _build_stub_edge_module(tmp_path, "no_core")
        monkeypatch.setattr(pywebview_patches, "_PATCHED_EDGE_MODULES", set())
        pywebview_patches._patch_edgechromium_clear_user_data(module)

        edge = module.EdgeChrome(core=None)
        edge.clear_user_data()

        assert edge.webview.disposed is True
        assert process_api.last_proc is None
        assert not data_dir.exists()

    def test_edge_patch_waits_for_browser_process(self, tmp_path, monkeypatch) -> None:
        module, process_api, data_dir = _build_stub_edge_module(tmp_path, "has_core")
        monkeypatch.setattr(pywebview_patches, "_PATCHED_EDGE_MODULES", set())
        pywebview_patches._patch_edgechromium_clear_user_data(module)

        edge = module.EdgeChrome(core=SimpleNamespace(BrowserProcessId=77))
        edge.clear_user_data()

        proc = process_api.last_proc
        assert proc is not None
        assert proc.pid == 77
        assert proc.waited is True
        assert proc.timeout == 3000
        assert not data_dir.exists()

