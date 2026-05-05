"""Tests for DesktopAPI configuration management functionality.

This module tests configuration operations including:
- Reading and parsing YAML configuration
- Writing and validating configuration
- Configuration file existence checks
- YAML library availability handling
"""

import pytest

from pokepoke.desktop.desktop_api import DesktopAPI


@pytest.fixture(autouse=True)
def _isolate_desktop_api(monkeypatch):
    """Prevent DesktopAPI from loading real historical agents or calling git."""
    monkeypatch.setattr("pokepoke.desktop.desktop_api.get_repository_name", lambda: "test-repo")


def test_get_config_reads_yaml() -> None:
    from unittest.mock import patch

    api = DesktopAPI()
    with patch("pokepoke.config._find_repo_root") as mock_root:
        # Create a fake repo root with .pokepoke/config.yaml
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / ".pokepoke").mkdir(parents=True, exist_ok=True)
            (root / ".pokepoke" / "config.yaml").write_text(
                "project_name: TestProject\nmodels:\n  default: gpt-5\n",
                encoding="utf-8",
            )
            mock_root.return_value = root

            result = api.get_config()

    assert result["exists"] is True
    assert result["config"]["project_name"] == "TestProject"
    assert result["config"]["models"]["default"] == "gpt-5"


def test_save_config_writes_yaml() -> None:
    from unittest.mock import patch

    import yaml

    api = DesktopAPI()
    with patch("pokepoke.config._find_repo_root") as mock_root:
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            mock_root.return_value = root

            save_result = api.save_config({"project_name": "X", "git": {"fallback_branch": "main"}})
            assert save_result["saved"] is True

            cfg_path = root / ".pokepoke" / "config.yaml"
            loaded = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))

    assert loaded["project_name"] == "X"
    assert loaded["git"]["fallback_branch"] == "main"


def test_save_config_with_yaml_string() -> None:
    """save_config should accept a YAML string and parse it."""
    from unittest.mock import patch

    import yaml

    api = DesktopAPI()
    with patch("pokepoke.config._find_repo_root") as mock_root:
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            mock_root.return_value = root

            yaml_str = "project_name: Y\ngit:\n  fallback_branch: dev\n"
            save_result = api.save_config(yaml_str)
            assert save_result["saved"] is True

            cfg_path = root / ".pokepoke" / "config.yaml"
            loaded = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))

    assert loaded["project_name"] == "Y"


def test_save_config_rejects_invalid_type() -> None:
    """save_config should reject non-dict/non-string input."""
    from unittest.mock import patch

    import pytest

    api = DesktopAPI()
    with patch("pokepoke.config._find_repo_root"), pytest.raises(ValueError, match="Config must be a dict or YAML string"):
        api.save_config(42)


def test_save_config_rejects_non_dict_yaml() -> None:
    """save_config should reject YAML strings that don't parse to a dict."""
    from unittest.mock import patch

    import pytest

    api = DesktopAPI()
    with patch("pokepoke.config._find_repo_root"), pytest.raises(ValueError, match="Config YAML must parse to an object"):
        api.save_config("- item1\n- item2\n")


def test_get_config_no_yaml(monkeypatch) -> None:
    """get_config should raise ImportError when yaml is not available."""
    from unittest.mock import patch

    api = DesktopAPI()
    with patch("pokepoke.config._find_repo_root") as mock_root:
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            cfg = root / ".pokepoke" / "config.yaml"
            cfg.parent.mkdir(parents=True)
            cfg.write_text("key: val\n", encoding="utf-8")
            mock_root.return_value = root

            monkeypatch.setattr("pokepoke.desktop.desktop_api_ext.HAS_YAML", False)
            with pytest.raises(ImportError, match="PyYAML"):
                api.get_config()


def test_get_config_file_not_found(monkeypatch) -> None:
    """get_config should return exists=False when config file is missing."""
    from unittest.mock import patch

    api = DesktopAPI()
    with patch("pokepoke.config._find_repo_root") as mock_root:
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            mock_root.return_value = root
            result = api.get_config()

    assert result["exists"] is False


def test_save_config_no_yaml(monkeypatch) -> None:
    """save_config should raise ImportError when yaml is not available."""
    from unittest.mock import patch

    api = DesktopAPI()
    monkeypatch.setattr("pokepoke.desktop.desktop_api_ext.HAS_YAML", False)
    with patch("pokepoke.config._find_repo_root"), pytest.raises(ImportError, match="PyYAML"):
        api.save_config({"key": "val"})
