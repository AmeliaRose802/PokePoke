"""Tests for repo_config_loader module -- covers validation and CLI parsing."""

from pokepoke.config import QualityGateOverrides, RepoConfig
from pokepoke.git.repo_config_loader import (
    _check_beads_available,
    validate_repo_config,
)
from pokepoke.utils.constants import BEADS_DIR

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
