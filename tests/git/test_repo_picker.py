"""Tests for repo_picker module."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

from pokepoke.git.repo_picker import LaunchConfig
from pokepoke.utils.project_utils import is_git_repo as _is_git_repo


class TestLaunchConfig:
    """Test LaunchConfig dataclass."""

    def test_defaults(self, tmp_path: Path) -> None:
        cfg = LaunchConfig(repo_path=tmp_path)
        assert cfg.repo_path == tmp_path
        assert cfg.max_agents == 1

    def test_custom_agents(self, tmp_path: Path) -> None:
        cfg = LaunchConfig(repo_path=tmp_path, max_agents=4)
        assert cfg.max_agents == 4


class TestIsGitRepo:
    """Test _is_git_repo helper."""

    @patch("pokepoke.utils.project_utils.subprocess.run")
    def test_returns_true_for_git_repo(self, mock_run: MagicMock, tmp_path: Path) -> None:
        mock_run.return_value = MagicMock(returncode=0)
        assert _is_git_repo(tmp_path) is True

    @patch("pokepoke.utils.project_utils.subprocess.run")
    def test_returns_false_for_non_git(self, mock_run: MagicMock, tmp_path: Path) -> None:
        mock_run.return_value = MagicMock(returncode=128)
        assert _is_git_repo(tmp_path) is False

    @patch("pokepoke.utils.project_utils.subprocess.run", side_effect=OSError("no git"))
    def test_returns_false_on_os_error(self, mock_run: MagicMock, tmp_path: Path) -> None:
        assert _is_git_repo(tmp_path) is False

    @patch("pokepoke.utils.project_utils.subprocess.run")
    def test_returns_false_on_timeout(self, mock_run: MagicMock, tmp_path: Path) -> None:
        import subprocess
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="git", timeout=5)
        assert _is_git_repo(tmp_path) is False


class TestPickRepoDirectory:
    """Test pick_repo_directory function."""

    def test_tkinter_launch(self, tmp_path: Path, monkeypatch) -> None:
        """Test the tkinter path with simulated Launch click."""
        from pokepoke.git import repo_picker

        captured_callbacks = {}

        class FakeVar:
            def __init__(self, value=""):
                self._value = value
            def get(self):
                return self._value
            def set(self, val):
                self._value = val

        class FakeRoot:
            def title(self, *a): pass
            def resizable(self, *a): pass
            def attributes(self, *a): pass
            def winfo_screenwidth(self): return 1920
            def winfo_screenheight(self): return 1080
            def geometry(self, *a): pass
            def protocol(self, event, cb): pass
            def destroy(self): pass
            def mainloop(self):
                if "launch" in captured_callbacks:
                    captured_callbacks["launch"]()

        class FakeFrame:
            def __init__(self, *a, **kw): pass
            def pack(self, **kw): pass

        class FakeLabel:
            def __init__(self, *a, **kw): pass
            def pack(self, **kw): pass

        class FakeEntry:
            def __init__(self, *a, **kw): pass
            def pack(self, **kw): pass

        class FakeButton:
            def __init__(self, *a, **kw):
                text = kw.get("text", "")
                cmd = kw.get("command")
                if text == "Launch" and cmd:
                    captured_callbacks["launch"] = cmd
            def pack(self, **kw): pass

        class FakeSpinbox:
            def __init__(self, *a, **kw): pass
            def pack(self, **kw): pass

        # Build mock tkinter modules
        mock_tk = MagicMock()
        mock_tk.Tk = FakeRoot
        mock_tk.StringVar = lambda value="": FakeVar(str(tmp_path))
        mock_tk.IntVar = lambda value=1: FakeVar(value)

        mock_ttk = MagicMock()
        mock_ttk.Frame = FakeFrame
        mock_ttk.Label = FakeLabel
        mock_ttk.Entry = FakeEntry
        mock_ttk.Button = FakeButton
        mock_ttk.Spinbox = FakeSpinbox

        mock_filedialog = MagicMock()

        # Link submodules as attributes for 'from tkinter import ...'
        mock_tk.filedialog = mock_filedialog
        mock_tk.ttk = mock_ttk

        # Inject mock modules
        monkeypatch.setitem(sys.modules, "tkinter", mock_tk)
        monkeypatch.setitem(sys.modules, "tkinter.filedialog", mock_filedialog)
        monkeypatch.setitem(sys.modules, "tkinter.ttk", mock_ttk)

        result = repo_picker.pick_repo_directory()

        assert result is not None
        assert result.repo_path == tmp_path.resolve()
        assert result.max_agents == 1

    def test_tkinter_cancel(self, tmp_path: Path, monkeypatch) -> None:
        """Test the tkinter path when user cancels (closes window)."""
        from pokepoke.git import repo_picker

        class FakeVar:
            def __init__(self, value=""):
                self._value = value
            def get(self):
                return self._value

        class FakeRoot:
            def title(self, *a): pass
            def resizable(self, *a): pass
            def attributes(self, *a): pass
            def winfo_screenwidth(self): return 1920
            def winfo_screenheight(self): return 1080
            def geometry(self, *a): pass
            def protocol(self, event, cb): pass
            def destroy(self): pass
            def mainloop(self):
                pass  # No button clicked → result stays None

        class FakeWidget:
            def __init__(self, *a, **kw): pass
            def pack(self, **kw): pass

        mock_tk = MagicMock()
        mock_tk.Tk = FakeRoot
        mock_tk.StringVar = lambda value="": FakeVar(str(tmp_path))
        mock_tk.IntVar = lambda value=1: FakeVar(value)

        mock_ttk = MagicMock()
        for w in ("Frame", "Label", "Entry", "Button", "Spinbox"):
            setattr(mock_ttk, w, FakeWidget)

        monkeypatch.setitem(sys.modules, "tkinter", mock_tk)
        monkeypatch.setitem(sys.modules, "tkinter.filedialog", MagicMock())
        monkeypatch.setitem(sys.modules, "tkinter.ttk", mock_ttk)

        result = repo_picker.pick_repo_directory()
        assert result is None

    def test_tkinter_tclerror_fallback(self, tmp_path: Path, monkeypatch) -> None:
        """Fallback to console when tkinter fails to initialize (headless)."""
        from pokepoke.git import repo_picker

        class FakeTclError(Exception):
            pass

        class FakeTkModule:
            TclError = FakeTclError

            class Tk:
                def __init__(self, *args, **kwargs):
                    raise FakeTclError("no display")

        mock_tk = FakeTkModule()

        monkeypatch.setitem(sys.modules, "tkinter", mock_tk)
        monkeypatch.setitem(sys.modules, "tkinter.filedialog", MagicMock())
        monkeypatch.setitem(sys.modules, "tkinter.ttk", MagicMock())

        inputs = iter([str(tmp_path)])
        monkeypatch.setattr("builtins.input", lambda _: next(inputs))

        result = repo_picker.pick_repo_directory()

        assert result is not None
        assert result.repo_path == tmp_path.resolve()
        assert result.max_agents == 1

    def test_console_fallback_quit(self, monkeypatch) -> None:
        """Test console fallback when tkinter is unavailable and user quits."""
        from pokepoke.git import repo_picker

        # Remove tkinter from sys.modules to trigger ImportError
        monkeypatch.setitem(sys.modules, "tkinter", None)

        monkeypatch.setattr("builtins.input", lambda _: "q")

        result = repo_picker.pick_repo_directory()
        assert result is None

    def test_console_fallback_valid_path(self, tmp_path: Path, monkeypatch) -> None:
        """Test console fallback with valid directory input."""
        from pokepoke.git import repo_picker

        monkeypatch.setitem(sys.modules, "tkinter", None)

        inputs = iter([str(tmp_path)])
        monkeypatch.setattr("builtins.input", lambda _: next(inputs))

        result = repo_picker.pick_repo_directory()
        assert result is not None
        assert result.repo_path == tmp_path.resolve()
        assert result.max_agents == 1

    def test_tkinter_runtime_failure_falls_back_to_console(self, tmp_path: Path, monkeypatch) -> None:
        """Test that a tkinter runtime error (e.g. no display) falls back to console."""
        from pokepoke.git import repo_picker

        # Make tkinter importable but crash at Tk() instantiation (no display)
        mock_tk = MagicMock()
        mock_tk.Tk.side_effect = RuntimeError("no display")
        mock_ttk = MagicMock()

        monkeypatch.setitem(sys.modules, "tkinter", mock_tk)
        monkeypatch.setitem(sys.modules, "tkinter.filedialog", MagicMock())
        monkeypatch.setitem(sys.modules, "tkinter.ttk", mock_ttk)

        inputs = iter([str(tmp_path)])
        monkeypatch.setattr("builtins.input", lambda _: next(inputs))

        result = repo_picker.pick_repo_directory()
        assert result is not None
        assert result.repo_path == tmp_path.resolve()
        assert result.max_agents == 1
