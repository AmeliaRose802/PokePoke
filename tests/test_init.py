"""Tests for pokepoke.init module."""

import json
import subprocess
from pathlib import Path
from unittest.mock import patch


from pokepoke.init import (
    _SAMPLE_CONFIG,
    _SEED_BEADS_ITEMS,
    _load_existing_beads_titles,
    _seed_setup_beads_items,
    init_project,
    main,
)


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


class TestBeadsSeeding:
    """Tests for beads setup item seeding."""

    def test_load_existing_beads_titles_parses_jsonl(self, tmp_path: Path) -> None:
        beads_dir = tmp_path / ".beads"
        beads_dir.mkdir()
        issues_path = beads_dir / "issues.jsonl"
        issues_path.write_text(
            '{"title": "First"}\n'
            'not-json\n'
            '{"title": "Second"}\n',
            encoding="utf-8",
        )

        titles = _load_existing_beads_titles(tmp_path)

        assert titles == {"first", "second"}

    def test_seed_setup_items_skips_without_beads(self, tmp_path: Path) -> None:
        with patch("pokepoke.init.subprocess.run") as run_mock:
            _seed_setup_beads_items(tmp_path)

        run_mock.assert_not_called()

    def test_seed_setup_items_skips_without_bd(self, tmp_path: Path) -> None:
        (tmp_path / ".beads").mkdir()
        with (
            patch("pokepoke.init.shutil.which", return_value=None),
            patch("pokepoke.init.subprocess.run") as run_mock,
        ):
            _seed_setup_beads_items(tmp_path)

        run_mock.assert_not_called()

    def test_seed_setup_items_creates_missing_item(self, tmp_path: Path) -> None:
        beads_dir = tmp_path / ".beads"
        beads_dir.mkdir()
        issues_path = beads_dir / "issues.jsonl"
        existing_title = str(_SEED_BEADS_ITEMS[0]["title"])
        issues_path.write_text(
            json.dumps({"title": existing_title}) + "\n",
            encoding="utf-8",
        )

        created = subprocess.CompletedProcess(
            args=["bd", "create"],
            returncode=0,
            stdout=json.dumps({"id": "PokePoke-123", "title": "Created"}),
            stderr="",
        )

        with (
            patch("pokepoke.init.shutil.which", return_value="bd"),
            patch("pokepoke.init.subprocess.run", return_value=created) as run_mock,
        ):
            _seed_setup_beads_items(tmp_path)

        run_mock.assert_called_once()
        cmd = run_mock.call_args[0][0]
        assert cmd[0:2] == ["bd", "create"]
        assert cmd[2] == str(_SEED_BEADS_ITEMS[1]["title"])
        assert "--labels" in cmd

    def test_load_existing_returns_empty_set_when_no_issues_file(self, tmp_path: Path) -> None:
        """Covers line 130: issues.jsonl doesn't exist."""
        titles = _load_existing_beads_titles(tmp_path)
        assert titles == set()

    def test_load_existing_skips_blank_lines(self, tmp_path: Path) -> None:
        """Covers line 137: blank lines in issues.jsonl."""
        beads_dir = tmp_path / ".beads"
        beads_dir.mkdir()
        issues_path = beads_dir / "issues.jsonl"
        issues_path.write_text(
            '{"title": "First"}\n\n\n{"title": "Second"}\n',
            encoding="utf-8",
        )
        titles = _load_existing_beads_titles(tmp_path)
        assert titles == {"first", "second"}

    def test_seed_handles_timeout(self, tmp_path: Path) -> None:
        """Covers lines 191-193: subprocess.TimeoutExpired."""
        beads_dir = tmp_path / ".beads"
        beads_dir.mkdir()
        (beads_dir / "issues.jsonl").write_text("", encoding="utf-8")

        with (
            patch("pokepoke.init.shutil.which", return_value="bd"),
            patch("pokepoke.init.subprocess.run",
                  side_effect=subprocess.TimeoutExpired(cmd="bd", timeout=30)),
        ):
            _seed_setup_beads_items(tmp_path)  # Should not raise

    def test_seed_handles_called_process_error(self, tmp_path: Path) -> None:
        """Covers lines 194-197: subprocess.CalledProcessError."""
        beads_dir = tmp_path / ".beads"
        beads_dir.mkdir()
        (beads_dir / "issues.jsonl").write_text("", encoding="utf-8")

        with (
            patch("pokepoke.init.shutil.which", return_value="bd"),
            patch("pokepoke.init.subprocess.run",
                  side_effect=subprocess.CalledProcessError(1, "bd", stderr="error msg")),
        ):
            _seed_setup_beads_items(tmp_path)  # Should not raise

    def test_seed_handles_non_json_stdout(self, tmp_path: Path) -> None:
        """Covers lines 204-205: non-JSON stdout from bd create."""
        beads_dir = tmp_path / ".beads"
        beads_dir.mkdir()
        (beads_dir / "issues.jsonl").write_text("", encoding="utf-8")

        result = subprocess.CompletedProcess(
            args=["bd", "create"],
            returncode=0,
            stdout="Created item successfully",  # Not JSON
            stderr="",
        )

        with (
            patch("pokepoke.init.shutil.which", return_value="bd"),
            patch("pokepoke.init.subprocess.run", return_value=result),
        ):
            _seed_setup_beads_items(tmp_path)  # Should not raise

    def test_seed_prints_title_when_no_id(self, tmp_path: Path) -> None:
        """Covers line 210: JSON output without 'id' field."""
        beads_dir = tmp_path / ".beads"
        beads_dir.mkdir()
        (beads_dir / "issues.jsonl").write_text("", encoding="utf-8")

        result = subprocess.CompletedProcess(
            args=["bd", "create"],
            returncode=0,
            stdout=json.dumps({"title": "Created"}),  # No 'id'
            stderr="",
        )

        with (
            patch("pokepoke.init.shutil.which", return_value="bd"),
            patch("pokepoke.init.subprocess.run", return_value=result),
        ):
            _seed_setup_beads_items(tmp_path)  # Should not raise
