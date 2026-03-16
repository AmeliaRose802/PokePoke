"""Tests for repo_config_loader module -- covers validation and CLI parsing."""



from pokepoke.config import RepoConfig, QualityGateOverrides
from pokepoke.utils.constants import BEADS_DIR
from pokepoke.git.repo_config_loader import (
    _check_beads_available,
    _split_repo_entry,
    parse_repos_cli,
    validate_repo_config,
    validate_repo_configs,
)


# -- _check_beads_available --------------------------------------------------


class TestCheckBeadsAvailable:
    """Tests for _check_beads_available."""

    def test_explicit_path_exists(self, tmp_path):
        db_dir = tmp_path / "custom_beads"
        db_dir.mkdir()
        ok, err = _check_beads_available(tmp_path, str(db_dir))
        assert ok is True
        assert err is None

    def test_explicit_path_does_not_exist(self, tmp_path):
        ok, err = _check_beads_available(tmp_path, str(tmp_path / "missing"))
        assert ok is False
        assert "does not exist" in err

    def test_auto_discover_finds_beads_dir(self, tmp_path):
        (tmp_path / BEADS_DIR).mkdir()
        ok, err = _check_beads_available(tmp_path, None)
        assert ok is True
        assert err is None

    def test_auto_discover_no_beads_dir(self, tmp_path):
        ok, err = _check_beads_available(tmp_path, None)
        assert ok is False
        assert BEADS_DIR in err


# -- validate_repo_config ----------------------------------------------------


class TestValidateRepoConfig:
    """Tests for validate_repo_config."""

    def test_empty_path(self):
        repo = RepoConfig(path="")
        result = validate_repo_config(repo)
        assert result.valid is False
        assert any("empty" in e.lower() for e in result.errors)

    def test_nonexistent_path(self, tmp_path):
        repo = RepoConfig(path=str(tmp_path / "nope"))
        result = validate_repo_config(repo)
        assert result.valid is False
        assert any("does not exist" in e for e in result.errors)

    def test_valid_path(self, tmp_path):
        (tmp_path / BEADS_DIR).mkdir()
        repo = RepoConfig(path=str(tmp_path))
        result = validate_repo_config(repo)
        assert result.valid is True
        assert result.errors == []

    def test_beads_warning(self, tmp_path):
        # Valid dir but no .beads — generates a warning, not an error
        repo = RepoConfig(path=str(tmp_path))
        result = validate_repo_config(repo)
        assert result.valid is True
        assert any(BEADS_DIR in w or "beads" in w.lower() for w in result.warnings)

    def test_copilot_instructions_warning(self, tmp_path):
        (tmp_path / BEADS_DIR).mkdir()
        repo = RepoConfig(
            path=str(tmp_path),
            copilot_instructions_path="nonexistent_instructions.md",
        )
        result = validate_repo_config(repo)
        assert result.valid is True
        assert any("instructions" in w.lower() for w in result.warnings)

    def test_quality_gate_warning(self, tmp_path):
        (tmp_path / BEADS_DIR).mkdir()
        repo = RepoConfig(
            path=str(tmp_path),
            quality_gate_overrides=QualityGateOverrides(coverage_threshold=0.0),
        )
        result = validate_repo_config(repo)
        assert result.valid is True
        assert any("coverage" in w.lower() for w in result.warnings)


# -- validate_repo_configs ---------------------------------------------------


class TestValidateRepoConfigs:
    """Tests for validate_repo_configs."""

    def test_disabled_repos_skipped(self, tmp_path):
        disabled = RepoConfig(path=str(tmp_path / "gone"), enabled=False)
        results = validate_repo_configs([disabled])
        assert len(results) == 1
        assert results[0].valid is True
        assert results[0].errors == []

    def test_mixed_valid_invalid(self, tmp_path):
        good_dir = tmp_path / "good"
        good_dir.mkdir()
        (good_dir / BEADS_DIR).mkdir()

        repos = [
            RepoConfig(path=str(good_dir)),
            RepoConfig(path=str(tmp_path / "bad")),
        ]
        results = validate_repo_configs(repos)
        assert len(results) == 2
        assert results[0].valid is True
        assert results[1].valid is False


# -- _split_repo_entry -------------------------------------------------------


class TestSplitRepoEntry:
    """Tests for _split_repo_entry."""

    def test_plain_path(self):
        assert _split_repo_entry("/home/user/repo") == ["/home/user/repo"]

    def test_path_with_options(self):
        parts = _split_repo_entry("/home/user/repo:weight=5:max_workers=2")
        assert parts == ["/home/user/repo", "weight=5", "max_workers=2"]

    def test_windows_drive_path(self):
        parts = _split_repo_entry("C:\\Users\\repo")
        assert parts == ["C:\\Users\\repo"]

    def test_windows_drive_with_options(self):
        parts = _split_repo_entry("C:\\Users\\repo:weight=3:disabled=true")
        assert parts == ["C:\\Users\\repo", "weight=3", "disabled=true"]


# -- parse_repos_cli ----------------------------------------------------------


class TestParseReposCli:
    """Tests for parse_repos_cli."""

    def test_single_repo(self):
        configs = parse_repos_cli(["/home/user/repo"])
        assert len(configs) == 1
        assert configs[0].path == "/home/user/repo"
        assert configs[0].priority_weight == 1
        assert configs[0].enabled is True

    def test_multiple_repos(self):
        configs = parse_repos_cli(["/repo1", "/repo2"])
        assert len(configs) == 2
        assert configs[0].path == "/repo1"
        assert configs[1].path == "/repo2"

    def test_weight_option(self):
        configs = parse_repos_cli(["/repo:weight=5"])
        assert configs[0].priority_weight == 5

    def test_max_workers_option(self):
        configs = parse_repos_cli(["/repo:max_workers=4"])
        assert configs[0].max_workers == 4

    def test_disabled_option(self):
        configs = parse_repos_cli(["/repo:disabled=true"])
        assert configs[0].enabled is False

    def test_disabled_option_yes(self):
        configs = parse_repos_cli(["/repo:disabled=yes"])
        assert configs[0].enabled is False

    def test_disabled_option_one(self):
        configs = parse_repos_cli(["/repo:disabled=1"])
        assert configs[0].enabled is False

    def test_not_disabled(self):
        configs = parse_repos_cli(["/repo:disabled=false"])
        assert configs[0].enabled is True

    def test_combined_options(self):
        configs = parse_repos_cli(["/repo:weight=3:max_workers=2:disabled=true"])
        assert configs[0].priority_weight == 3
        assert configs[0].max_workers == 2
        assert configs[0].enabled is False

    def test_windows_path(self):
        configs = parse_repos_cli(["C:\\Users\\repo:weight=2"])
        assert configs[0].path == "C:\\Users\\repo"
        assert configs[0].priority_weight == 2
