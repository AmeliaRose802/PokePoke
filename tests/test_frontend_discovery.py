"""Tests for frontend discovery functionality."""

from unittest.mock import MagicMock, patch

import pokepoke.frontend_discovery as frontend_discovery_module


class TestFindDevServerUrl:
    """Test the find_dev_server_url function."""

    def test_returns_none_when_env_not_set(self, monkeypatch) -> None:
        """find_dev_server_url returns None when POKEPOKE_DEV is not set."""
        monkeypatch.delenv("POKEPOKE_DEV", raising=False)
        monkeypatch.delenv("POKEPOKE_DEV_URL", raising=False)
        result = frontend_discovery_module.find_dev_server_url()
        assert result is None

    def test_returns_none_when_env_is_false(self, monkeypatch) -> None:
        """find_dev_server_url returns None when POKEPOKE_DEV=0."""
        monkeypatch.setenv("POKEPOKE_DEV", "0")
        result = frontend_discovery_module.find_dev_server_url()
        assert result is None

    def test_returns_url_when_server_reachable(self, monkeypatch) -> None:
        """find_dev_server_url returns URL when dev server is running."""
        monkeypatch.setenv("POKEPOKE_DEV", "1")
        monkeypatch.delenv("POKEPOKE_DEV_URL", raising=False)

        with patch("pokepoke.frontend_discovery.urllib.request.urlopen"):
            result = frontend_discovery_module.find_dev_server_url()
        assert result == "http://localhost:5173"

    def test_returns_none_when_server_unreachable(self, monkeypatch) -> None:
        """find_dev_server_url returns None when dev server is not running."""
        monkeypatch.setenv("POKEPOKE_DEV", "1")

        with patch(
            "pokepoke.frontend_discovery.urllib.request.urlopen",
            side_effect=ConnectionRefusedError,
        ):
            result = frontend_discovery_module.find_dev_server_url()
        assert result is None

    def test_custom_url_via_env(self, monkeypatch) -> None:
        """find_dev_server_url respects POKEPOKE_DEV_URL."""
        monkeypatch.setenv("POKEPOKE_DEV", "true")
        monkeypatch.setenv("POKEPOKE_DEV_URL", "http://localhost:3000")

        with patch("pokepoke.frontend_discovery.urllib.request.urlopen"):
            result = frontend_discovery_module.find_dev_server_url()
        assert result == "http://localhost:3000"

    def test_case_insensitive_env_value(self, monkeypatch) -> None:
        """POKEPOKE_DEV accepts 'True', 'TRUE', etc."""
        monkeypatch.setenv("POKEPOKE_DEV", "True")

        with patch("pokepoke.frontend_discovery.urllib.request.urlopen"):
            result = frontend_discovery_module.find_dev_server_url()
        assert result == "http://localhost:5173"


class TestFindFrontendDist:
    """Test the find_frontend_dist function."""

    def test_frozen_execution_mode(self, monkeypatch, tmp_path) -> None:
        """Test behavior when running as frozen executable (PyInstaller)."""
        # Mock sys.frozen to True
        monkeypatch.setattr("sys.frozen", True, raising=False)

        # Mock importlib.util.find_spec
        fake_spec = MagicMock()
        fake_spec.origin = str(tmp_path / "pokepoke" / "static" / "__init__.py")

        def mock_find_spec(name):
            if name == 'pokepoke.static':
                return fake_spec
            return None

        monkeypatch.setattr("importlib.util.find_spec", mock_find_spec)

        # Create the static directory structure
        static_dir = tmp_path / "pokepoke" / "static"
        static_dir.mkdir(parents=True)
        (static_dir / "index.html").write_text("<html>frozen</html>", encoding="utf-8")

        result = frontend_discovery_module.find_frontend_dist()
        assert result == static_dir
        assert (result / "index.html").read_text(encoding="utf-8") == "<html>frozen</html>"

    def test_frozen_mode_no_static_found(self, monkeypatch, tmp_path) -> None:
        """Test frozen mode when static directory doesn't exist."""
        # Mock sys.frozen to True
        monkeypatch.setattr("sys.frozen", True, raising=False)

        # Mock importlib.util.find_spec to return None
        def mock_find_spec(name):
            return None

        monkeypatch.setattr("importlib.util.find_spec", mock_find_spec)

        # Create dist directory for fallback
        with patch('pokepoke.desktop_ui') as mock_desktop_ui:
            mock_desktop_ui.__file__ = str(tmp_path / "src" / "pokepoke" / "desktop_ui.py")

            dist_dir = tmp_path / "desktop" / "dist"
            dist_dir.mkdir(parents=True)
            (dist_dir / "index.html").write_text("<html>fallback</html>", encoding="utf-8")

            result = frontend_discovery_module.find_frontend_dist()
            assert result == dist_dir

    def test_package_resources_extraction_success(self, monkeypatch, tmp_path) -> None:
        """Test successful extraction from package resources."""
        # Mock sys.frozen to False
        monkeypatch.setattr("sys.frozen", False, raising=False)

        # Mock the desktop_ui module
        with patch('pokepoke.desktop_ui') as mock_desktop_ui:
            mock_desktop_ui.__file__ = str(tmp_path / "src" / "pokepoke" / "desktop_ui.py")

            # Ensure no static directory exists on filesystem
            fake_src = tmp_path / "src" / "pokepoke"
            fake_src.mkdir(parents=True)

            # Mock tempfile.gettempdir
            temp_dir = tmp_path / "temp"
            temp_dir.mkdir()
            monkeypatch.setattr("tempfile.gettempdir", lambda: str(temp_dir))

            # Mock importlib.resources
            fake_resource = MagicMock()
            fake_resource.name = "index.html"
            fake_resource.is_file.return_value = True
            fake_resource.is_dir.return_value = False

            fake_static_ref = MagicMock()
            fake_static_ref.__truediv__ = lambda self, name: fake_resource if name == "index.html" else MagicMock()
            fake_static_ref.iterdir.return_value = [fake_resource]

            def mock_files(package_name):
                if package_name == 'pokepoke.static':
                    return fake_static_ref
                return None

            # Mock as_file context manager
            from contextlib import contextmanager

            @contextmanager
            def mock_as_file(resource):
                temp_resource = temp_dir / "resource_index.html"
                temp_resource.write_text("<html>extracted</html>", encoding="utf-8")
                yield temp_resource

            monkeypatch.setattr("importlib.resources.files", mock_files)
            monkeypatch.setattr("importlib.resources.as_file", mock_as_file)

            result = frontend_discovery_module.find_frontend_dist()

            # Should extract to pokepoke_static directory
            expected_dir = temp_dir / "pokepoke_static"
            assert result == expected_dir
            assert (result / "index.html").exists()

    def test_package_resources_not_available(self, monkeypatch, tmp_path) -> None:
        """Test fallback when package resources are not available."""
        # Mock sys.frozen to False
        monkeypatch.setattr("sys.frozen", False, raising=False)

        with patch('pokepoke.desktop_ui') as mock_desktop_ui:
            mock_desktop_ui.__file__ = str(tmp_path / "src" / "pokepoke" / "desktop_ui.py")

            fake_src = tmp_path / "src" / "pokepoke"
            fake_src.mkdir(parents=True)

            # Mock importlib.resources to raise ImportError
            def mock_files(*args):
                raise ImportError("importlib.resources not available")

            monkeypatch.setattr("importlib.resources.files", mock_files)

            # Create dist directory for fallback
            dist_dir = tmp_path / "desktop" / "dist"
            dist_dir.mkdir(parents=True)
            (dist_dir / "index.html").write_text("<html>fallback</html>", encoding="utf-8")

            result = frontend_discovery_module.find_frontend_dist()
            assert result == dist_dir

    def test_git_worktree_fallback(self, monkeypatch, tmp_path) -> None:
        """Test fallback to git worktree main repository."""
        # Mock sys.frozen to False
        monkeypatch.setattr("sys.frozen", False, raising=False)

        with patch('pokepoke.desktop_ui') as mock_desktop_ui:
            mock_desktop_ui.__file__ = str(tmp_path / "worktree" / "src" / "pokepoke" / "desktop_ui.py")

            # Create worktree structure (no local dist or static)
            worktree_src = tmp_path / "worktree" / "src" / "pokepoke"
            worktree_src.mkdir(parents=True)

            # Create main repo with dist
            main_repo = tmp_path / "main"
            main_dist = main_repo / "desktop" / "dist"
            main_dist.mkdir(parents=True)
            (main_dist / "index.html").write_text("<html>main_repo</html>", encoding="utf-8")

            # Mock tempfile.gettempdir to return empty temp
            empty_temp = tmp_path / "empty_temp"
            empty_temp.mkdir()
            monkeypatch.setattr("tempfile.gettempdir", lambda: str(empty_temp))

            # Mock importlib.resources to fail
            def mock_files(*args):
                raise ImportError("no package resources")

            monkeypatch.setattr("importlib.resources.files", mock_files)

            # Mock subprocess.run to simulate git worktree list
            def mock_run(*args, **kwargs):
                if args and args[0] and len(args[0]) > 1 and "worktree" in str(args[0][1]):
                    result = MagicMock()
                    result.stdout = f"worktree {main_repo}\nHEAD abc123\n\nworktree {tmp_path / 'worktree'}\nHEAD def456"
                    result.returncode = 0
                    return result
                raise FileNotFoundError("git not found")

            monkeypatch.setattr("subprocess.run", mock_run)

            result = frontend_discovery_module.find_frontend_dist()
            assert result == main_dist
            assert (result / "index.html").read_text(encoding="utf-8") == "<html>main_repo</html>"

    def test_returns_none_when_nothing_found(self, monkeypatch, tmp_path) -> None:
        """Test that it returns None when no frontend is found anywhere."""
        # Mock sys.frozen to False
        monkeypatch.setattr("sys.frozen", False, raising=False)

        with patch('pokepoke.desktop_ui') as mock_desktop_ui:
            mock_desktop_ui.__file__ = str(tmp_path / "src" / "pokepoke" / "desktop_ui.py")

            fake_src = tmp_path / "src" / "pokepoke"
            fake_src.mkdir(parents=True)
            # Don't create any dist or static directories

            # Mock tempfile.gettempdir to return empty temp
            empty_temp = tmp_path / "empty_temp"
            empty_temp.mkdir()
            monkeypatch.setattr("tempfile.gettempdir", lambda: str(empty_temp))

            # Mock importlib.resources to fail
            def mock_files(*args):
                raise ImportError("no package resources")

            monkeypatch.setattr("importlib.resources.files", mock_files)

            # Mock subprocess.run to fail
            def mock_run(*args, **kwargs):
                raise FileNotFoundError("git not found")

            monkeypatch.setattr("subprocess.run", mock_run)

            result = frontend_discovery_module.find_frontend_dist()
            assert result is None

    def test_exception_handling_in_package_resources(self, monkeypatch, tmp_path) -> None:
        """Test that exceptions in package resource handling are caught."""
        # Mock sys.frozen to False
        monkeypatch.setattr("sys.frozen", False, raising=False)

        with patch('pokepoke.desktop_ui') as mock_desktop_ui:
            mock_desktop_ui.__file__ = str(tmp_path / "src" / "pokepoke" / "desktop_ui.py")

            fake_src = tmp_path / "src" / "pokepoke"
            fake_src.mkdir(parents=True)

            # Mock importlib.resources.files to raise an exception
            def mock_files(*args):
                raise RuntimeError("Mock package resource error")

            monkeypatch.setattr("importlib.resources.files", mock_files)

            # Create dist directory for fallback
            dist_dir = tmp_path / "desktop" / "dist"
            dist_dir.mkdir(parents=True)
            (dist_dir / "index.html").write_text("<html>fallback</html>", encoding="utf-8")

            # Should handle the exception and fall back to dist directory
            result = frontend_discovery_module.find_frontend_dist()
            assert result == dist_dir

    def test_pkg_resources_simple_fallback(self, monkeypatch, tmp_path) -> None:
        """Test simple scenario that exercises pkg_resources code path."""
        # Mock sys.frozen to False
        monkeypatch.setattr("sys.frozen", False, raising=False)

        with patch('pokepoke.desktop_ui') as mock_desktop_ui:
            mock_desktop_ui.__file__ = str(tmp_path / "src" / "pokepoke" / "desktop_ui.py")

            fake_src = tmp_path / "src" / "pokepoke"
            fake_src.mkdir(parents=True)

            # Mock tempfile.gettempdir
            temp_dir = tmp_path / "temp"
            temp_dir.mkdir()
            monkeypatch.setattr("tempfile.gettempdir", lambda: str(temp_dir))

            # Mock importlib.resources to fail on first try
            # This exercises the pkg_resources fallback code path
            def mock_importlib_files(*args):
                raise AttributeError("No importlib.resources")

            monkeypatch.setattr("importlib.resources.files", mock_importlib_files)

            # Create dist directory as fallback
            dist_dir = tmp_path / "desktop" / "dist"
            dist_dir.mkdir(parents=True)
            (dist_dir / "index.html").write_text("<html>fallback</html>", encoding="utf-8")

            # The function should handle the exception gracefully and fall back
            result = frontend_discovery_module.find_frontend_dist()
            # Test that the function continues to work despite importlib issues
            assert result == dist_dir

    def test_static_directory_filesystem_exists(self, monkeypatch, tmp_path) -> None:
        """Test that filesystem static directory is found when it exists."""
        # Mock sys.frozen to False
        monkeypatch.setattr("sys.frozen", False, raising=False)

        with patch('pokepoke.desktop_ui') as mock_desktop_ui:
            mock_desktop_ui.__file__ = str(tmp_path / "src" / "pokepoke" / "desktop_ui.py")

            fake_src = tmp_path / "src" / "pokepoke"
            fake_src.mkdir(parents=True)

            # Create static directory on filesystem
            static_dir = fake_src / "static"
            static_dir.mkdir()
            (static_dir / "index.html").write_text("<html>filesystem</html>", encoding="utf-8")

            result = frontend_discovery_module.find_frontend_dist()
            assert result == static_dir
            assert (result / "index.html").read_text(encoding="utf-8") == "<html>filesystem</html>"

    def test_package_resources_with_subdirectories(self, monkeypatch, tmp_path) -> None:
        """Test extraction with subdirectories in package resources."""
        # Mock sys.frozen to False
        monkeypatch.setattr("sys.frozen", False, raising=False)

        with patch('pokepoke.desktop_ui') as mock_desktop_ui:
            mock_desktop_ui.__file__ = str(tmp_path / "src" / "pokepoke" / "desktop_ui.py")

            fake_src = tmp_path / "src" / "pokepoke"
            fake_src.mkdir(parents=True)

            # Mock tempfile.gettempdir
            temp_dir = tmp_path / "temp"
            temp_dir.mkdir()
            monkeypatch.setattr("tempfile.gettempdir", lambda: str(temp_dir))

            # Mock resources with subdirectories
            fake_file = MagicMock()
            fake_file.name = "index.html"
            fake_file.is_file.return_value = True
            fake_file.is_dir.return_value = False

            fake_subfile = MagicMock()
            fake_subfile.name = "app.js"
            fake_subfile.is_file.return_value = True
            fake_subfile.is_dir.return_value = False

            fake_subdir = MagicMock()
            fake_subdir.name = "assets"
            fake_subdir.is_file.return_value = False
            fake_subdir.is_dir.return_value = True
            fake_subdir.iterdir.return_value = [fake_subfile]

            fake_static_ref = MagicMock()
            fake_static_ref.__truediv__.side_effect = lambda name: {
                "index.html": fake_file,
                "assets": fake_subdir
            }.get(name, MagicMock())
            fake_static_ref.iterdir.return_value = [fake_file, fake_subdir]

            def mock_files(package_name):
                if package_name == 'pokepoke.static':
                    return fake_static_ref
                return None

            # Mock as_file to create temp files
            from contextlib import contextmanager

            @contextmanager
            def mock_as_file(resource):
                if resource == fake_file:
                    temp_resource = temp_dir / "temp_index.html"
                    temp_resource.write_text("<html>extracted</html>", encoding="utf-8")
                    yield temp_resource
                elif resource == fake_subfile:
                    temp_resource = temp_dir / "temp_app.js"
                    temp_resource.write_text("console.log('test');", encoding="utf-8")
                    yield temp_resource
                else:
                    yield resource

            monkeypatch.setattr("importlib.resources.files", mock_files)
            monkeypatch.setattr("importlib.resources.as_file", mock_as_file)

            result = frontend_discovery_module.find_frontend_dist()

            expected_dir = temp_dir / "pokepoke_static"
            assert result == expected_dir
            assert (result / "index.html").exists()
            assert (result / "assets" / "app.js").exists()

    def test_temp_directory_already_exists(self, monkeypatch, tmp_path) -> None:
        """Test when temp directory already exists and is current."""
        # Mock sys.frozen to False
        monkeypatch.setattr("sys.frozen", False, raising=False)

        with patch('pokepoke.desktop_ui') as mock_desktop_ui:
            mock_desktop_ui.__file__ = str(tmp_path / "src" / "pokepoke" / "desktop_ui.py")

            fake_src = tmp_path / "src" / "pokepoke"
            fake_src.mkdir(parents=True)

            # Mock tempfile.gettempdir
            temp_dir = tmp_path / "temp"
            temp_dir.mkdir()
            monkeypatch.setattr("tempfile.gettempdir", lambda: str(temp_dir))

            # Pre-create temp directory with index.html
            pokepoke_static_dir = temp_dir / "pokepoke_static"
            pokepoke_static_dir.mkdir(parents=True)
            (pokepoke_static_dir / "index.html").write_text("<html>cached</html>", encoding="utf-8")

            # Mock package resources
            fake_resource = MagicMock()
            fake_resource.name = "index.html"
            fake_resource.is_file.return_value = True

            fake_static_ref = MagicMock()
            fake_static_ref.__truediv__ = lambda self, name: fake_resource if name == "index.html" else MagicMock()

            def mock_files(package_name):
                if package_name == 'pokepoke.static':
                    return fake_static_ref
                return None

            monkeypatch.setattr("importlib.resources.files", mock_files)

            result = frontend_discovery_module.find_frontend_dist()

            # Should use the existing cached directory
            assert result == pokepoke_static_dir
            assert (result / "index.html").read_text(encoding="utf-8") == "<html>cached</html>"
