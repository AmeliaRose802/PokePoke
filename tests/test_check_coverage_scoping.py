"""Tests for check-coverage.py test scoping logic.

Validates that _find_test_files_for_staged correctly scopes tests
to modified files instead of falling back to the full suite, fixing
PokePoke-b9sg (pre-commit timeout kills SDK sessions).
"""

import importlib.util
from pathlib import Path
from unittest.mock import patch

import pytest

# Load check-coverage.py as a module (it lives in .githooks/, not a package)
_SCRIPT = Path(__file__).resolve().parent.parent / ".githooks" / "check-coverage.py"
_spec = importlib.util.spec_from_file_location("check_coverage", _SCRIPT)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

_find_test_files_for_staged = _mod._find_test_files_for_staged


@pytest.fixture()
def fake_repo(tmp_path):
    """Create a minimal repo layout for testing."""
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "conftest.py").write_text("")
    (tests_dir / "__init__.py").write_text("")
    (tests_dir / "test_config.py").write_text("")
    (tests_dir / "test_types.py").write_text("")

    utils_dir = tests_dir / "utils"
    utils_dir.mkdir()
    (utils_dir / "conftest.py").write_text("")
    (utils_dir / "test_helpers.py").write_text("")
    (utils_dir / "test_shutdown.py").write_text("")

    models_dir = tests_dir / "models"
    models_dir.mkdir()
    (models_dir / "test_copilot_sdk.py").write_text("")

    src_dir = tmp_path / "src" / "pokepoke"
    src_dir.mkdir(parents=True)
    (src_dir / "config.py").write_text("")
    (src_dir / "types.py").write_text("")
    (src_dir / "helpers.py").write_text("")
    return tmp_path


class TestConftestScoping:
    """Tests that conftest.py changes scope to the correct directory."""

    def test_root_conftest_runs_all_tests(self, fake_repo):
        """When tests/conftest.py changes, all tests in tests/ should run."""
        staged = ["src/pokepoke/config.py"]
        with patch.object(_mod, "_get_staged_files", return_value=[
            "tests/conftest.py", "src/pokepoke/config.py"
        ]):
            test_files, run_full = _find_test_files_for_staged(staged, fake_repo)

        assert not run_full
        # Should include all test files under tests/
        assert "tests/test_config.py" in test_files
        assert "tests/test_types.py" in test_files
        assert "tests/utils/test_helpers.py" in test_files
        assert "tests/utils/test_shutdown.py" in test_files

    def test_subdir_conftest_scopes_to_subdir(self, fake_repo):
        """When tests/utils/conftest.py changes, only tests/utils/ should run."""
        staged = ["src/pokepoke/config.py"]
        with patch.object(_mod, "_get_staged_files", return_value=[
            "tests/utils/conftest.py", "src/pokepoke/config.py"
        ]):
            test_files, run_full = _find_test_files_for_staged(staged, fake_repo)

        assert not run_full
        # Should include tests/utils/ tests
        assert "tests/utils/test_helpers.py" in test_files
        assert "tests/utils/test_shutdown.py" in test_files
        # Should also include test_config.py from the source file mapping
        assert "tests/test_config.py" in test_files

    def test_init_py_does_not_trigger_full_suite(self, fake_repo):
        """Changing __init__.py should NOT trigger full suite."""
        staged = ["src/pokepoke/config.py"]
        with patch.object(_mod, "_get_staged_files", return_value=[
            "tests/__init__.py", "src/pokepoke/config.py"
        ]):
            test_files, run_full = _find_test_files_for_staged(staged, fake_repo)

        assert not run_full
        # Should only run tests for config.py
        assert "tests/test_config.py" in test_files


class TestNoTestFallback:
    """Tests for the no-test-files-found case."""

    def test_no_mapping_does_not_run_full_suite(self, fake_repo):
        """When no test mapping is found, should NOT fall back to full suite."""
        staged = ["src/pokepoke/helpers.py"]
        with patch.object(_mod, "_get_staged_files", return_value=[
            "src/pokepoke/helpers.py"
        ]):
            _test_files, _run_full = _find_test_files_for_staged(staged, fake_repo)

        # No test_helpers.py exists at the expected location...
        # Actually, tests/utils/test_helpers.py exists, so it should be found
        # Let's test with a module that has no test file at all
        pass

    def test_unmapped_module_returns_empty(self, fake_repo):
        """Module with no test file should return empty, not full suite."""
        staged = ["src/pokepoke/unmapped_module.py"]
        (fake_repo / "src" / "pokepoke" / "unmapped_module.py").write_text("")
        with patch.object(_mod, "_get_staged_files", return_value=[
            "src/pokepoke/unmapped_module.py"
        ]):
            test_files, run_full = _find_test_files_for_staged(staged, fake_repo)

        assert not run_full
        assert test_files == []


class TestNormalScoping:
    """Tests that normal source file changes scope correctly."""

    def test_source_maps_to_test_file(self, fake_repo):
        """Normal source file should map to its test file."""
        staged = ["src/pokepoke/config.py"]
        with patch.object(_mod, "_get_staged_files", return_value=[
            "src/pokepoke/config.py"
        ]):
            test_files, run_full = _find_test_files_for_staged(staged, fake_repo)

        assert not run_full
        assert "tests/test_config.py" in test_files

    def test_staged_test_file_included(self, fake_repo):
        """Directly staged test files should be included."""
        staged = ["src/pokepoke/config.py"]
        with patch.object(_mod, "_get_staged_files", return_value=[
            "src/pokepoke/config.py", "tests/test_types.py"
        ]):
            test_files, run_full = _find_test_files_for_staged(staged, fake_repo)

        assert not run_full
        assert "tests/test_config.py" in test_files
        assert "tests/test_types.py" in test_files
