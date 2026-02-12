"""Tests for pokepoke.init module."""

import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest

from pokepoke.init import init_project, main, _SAMPLE_CONFIG


class TestInitProject:
    """Tests for init_project function."""

    def test_creates_pokepoke_directory(self, tmp_path: Path) -> None:
        result = init_project(target_dir=tmp_path)
        assert result is True
        assert (tmp_path / ".pokepoke").is_dir()
        assert (tmp_path / ".pokepoke" / "prompts").is_dir()

    def test_creates_config_yaml(self, tmp_path: Path) -> None:
        init_project(target_dir=tmp_path, project_name="TestProject")
        config = tmp_path / ".pokepoke" / "config.yaml"
        assert config.exists()
        content = config.read_text(encoding="utf-8")
        assert "project_name: TestProject" in content
        assert "models:" in content
        assert "mcp_server:" in content

    def test_creates_beads_item_template(self, tmp_path: Path) -> None:
        init_project(target_dir=tmp_path)
        template = tmp_path / ".pokepoke" / "prompts" / "beads-item.md"
        assert template.exists()
        content = template.read_text(encoding="utf-8")
        assert "{{title}}" in content
        assert "{{item_id}}" in content

    def test_uses_directory_name_as_default_project_name(
        self, tmp_path: Path
    ) -> None:
        init_project(target_dir=tmp_path)
        config = tmp_path / ".pokepoke" / "config.yaml"
        content = config.read_text(encoding="utf-8")
        assert f"project_name: {tmp_path.name}" in content

    def test_refuses_overwrite_without_force(self, tmp_path: Path) -> None:
        init_project(target_dir=tmp_path)
        result = init_project(target_dir=tmp_path)
        assert result is False

    def test_force_overwrites_existing(self, tmp_path: Path) -> None:
        init_project(target_dir=tmp_path, project_name="Old")
        result = init_project(
            target_dir=tmp_path, project_name="New", force=True
        )
        assert result is True
        config = tmp_path / ".pokepoke" / "config.yaml"
        content = config.read_text(encoding="utf-8")
        assert "project_name: New" in content

    def test_config_has_mcp_disabled_by_default(self, tmp_path: Path) -> None:
        init_project(target_dir=tmp_path)
        config = tmp_path / ".pokepoke" / "config.yaml"
        content = config.read_text(encoding="utf-8")
        assert "enabled: false" in content

    def test_config_has_maintenance_agents(self, tmp_path: Path) -> None:
        init_project(target_dir=tmp_path)
        config = tmp_path / ".pokepoke" / "config.yaml"
        content = config.read_text(encoding="utf-8")
        assert "maintenance:" in content
        assert "agents:" in content
        assert "Tech Debt" in content

    def test_defaults_to_cwd_when_no_target(self, tmp_path: Path) -> None:
        with patch("pokepoke.init.Path.cwd", return_value=tmp_path):
            result = init_project()
        assert result is True
        assert (tmp_path / ".pokepoke" / "config.yaml").exists()


class TestMainCli:
    """Tests for main() CLI entry point."""

    def test_main_returns_zero_on_success(self, tmp_path: Path) -> None:
        with patch(
            "sys.argv", ["pokepoke-init", "--dir", str(tmp_path)]
        ):
            result = main()
        assert result == 0

    def test_main_returns_one_on_failure(self, tmp_path: Path) -> None:
        # Create existing config so init fails
        (tmp_path / ".pokepoke").mkdir()
        (tmp_path / ".pokepoke" / "config.yaml").write_text("x")
        with patch(
            "sys.argv", ["pokepoke-init", "--dir", str(tmp_path)]
        ):
            result = main()
        assert result == 1

    def test_main_accepts_name_flag(self, tmp_path: Path) -> None:
        with patch(
            "sys.argv",
            ["pokepoke-init", "--dir", str(tmp_path), "--name", "Foo"],
        ):
            main()
        config = tmp_path / ".pokepoke" / "config.yaml"
        assert "project_name: Foo" in config.read_text(encoding="utf-8")

    def test_main_accepts_force_flag(self, tmp_path: Path) -> None:
        (tmp_path / ".pokepoke").mkdir()
        (tmp_path / ".pokepoke" / "config.yaml").write_text("x")
        with patch(
            "sys.argv",
            ["pokepoke-init", "--dir", str(tmp_path), "--force"],
        ):
            result = main()
        assert result == 0


class TestSampleConfig:
    """Tests for the sample config template string."""

    def test_sample_config_is_valid_yaml_after_format(self) -> None:
        import yaml
        content = _SAMPLE_CONFIG.format(project_name="Test")
        data = yaml.safe_load(content)
        assert data["project_name"] == "Test"
        assert data["mcp_server"]["enabled"] is False

    def test_sample_config_has_all_sections(self) -> None:
        content = _SAMPLE_CONFIG.format(project_name="X")
        for section in ["models:", "git:", "mcp_server:", "maintenance:"]:
            assert section in content
