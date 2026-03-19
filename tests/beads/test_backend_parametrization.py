"""Tests to verify backend parametrization works correctly for both bd and br.

This test file demonstrates the parametrization patterns and validates that:
1. The backend_config fixture works correctly
2. Both backends are tested with subprocess call expectations
3. Mock patterns remain compatible with FakeBeadsClient
"""

import json
import subprocess

import pytest

from pokepoke.beads import beads_query
from pokepoke.beads.beads_query import (
    BD_CONFIG,
    BR_CONFIG,
    get_active_backend,
    set_active_backend,
)


class TestBackendParametrization:
    """Verify that backend parametrization works for both bd and br."""

    def test_backend_config_fixture_sets_backend(self, backend_config):
        """Verify backend_config fixture properly sets the active backend."""
        active = get_active_backend()
        assert active.binary == backend_config.binary
        assert active in (BD_CONFIG, BR_CONFIG)

    def test_backend_binary_name_matches(self, backend_config):
        """Verify binary name is 'bd' or 'br'."""
        assert backend_config.binary in ("bd", "br")

    def test_get_ready_work_items_uses_correct_backend(
        self, backend_config, monkeypatch
    ):
        """Verify subprocess calls use the correct backend binary."""
        call_log = []

        def mock_run_bd(args, **kwargs):
            # _run_bd is called by get_ready_work_items
            call_log.append({"args": args, "binary": get_active_backend().binary})
            payload = [
                {
                    "id": "test-1",
                    "title": "Task",
                    "status": "open",
                    "priority": 1,
                    "issue_type": "task",
                    "description": "d",
                }
            ]
            return subprocess.CompletedProcess(
                [get_active_backend().binary] + args, 0, stdout=json.dumps(payload)
            )

        monkeypatch.setattr(beads_query, "_run_bd", mock_run_bd)

        items = beads_query.get_ready_work_items()

        assert len(items) == 1
        assert len(call_log) == 1
        assert call_log[0]["binary"] == backend_config.binary
        assert call_log[0]["args"] == ["ready", "--json"]

    def test_subprocess_call_expectations_match_backend(
        self, backend_config, monkeypatch
    ):
        """Verify CompletedProcess args include the correct binary."""
        expected_binary = backend_config.binary

        def mock_run_bd(args, **kwargs):
            # Simulate what subprocess.run would return
            return subprocess.CompletedProcess(
                [expected_binary] + args, 0, stdout="[]"
            )

        monkeypatch.setattr(beads_query, "_run_bd", mock_run_bd)

        result = beads_query._run_bd(["show", "test-123"])

        assert result.args[0] == expected_binary
        assert "show" in result.args
        assert "test-123" in result.args


@pytest.mark.parametrize("backend_config", [BD_CONFIG, BR_CONFIG], ids=["bd", "br"])
class TestDirectParametrization:
    """Example of using mark.parametrize directly on a class."""

    def test_backend_is_parametrized(self, backend_config):
        """This test runs twice: once with BD_CONFIG, once with BR_CONFIG."""
        original = get_active_backend()
        set_active_backend(backend_config)
        try:
            active = get_active_backend()
            assert active.binary == backend_config.binary
            assert active in (BD_CONFIG, BR_CONFIG)
        finally:
            set_active_backend(original)

    def test_binary_name_in_subprocess_mock(self, backend_config, monkeypatch):
        """Verify mocking works with parametrized backend."""
        original = get_active_backend()
        set_active_backend(backend_config)

        try:
            calls = []

            def mock_run_bd(args, **kwargs):
                calls.append(get_active_backend().binary)
                return subprocess.CompletedProcess(
                    [get_active_backend().binary] + args, 0, stdout="[]"
                )

            monkeypatch.setattr(beads_query, "_run_bd", mock_run_bd)

            beads_query._run_bd(["ready", "--json"])

            assert len(calls) == 1
            assert calls[0] == backend_config.binary
        finally:
            set_active_backend(original)


def test_individual_parametrization_with_ids():
    """Example of individual test parametrization with custom IDs."""

    @pytest.mark.parametrize(
        "backend_config",
        [
            pytest.param(BD_CONFIG, id="daemon_backend_bd"),
            pytest.param(BR_CONFIG, id="explicit_backend_br"),
        ],
    )
    def _test_with_custom_ids(backend_config):
        assert backend_config.binary in ("bd", "br")

    # Run the test (normally pytest does this)
    _test_with_custom_ids(BD_CONFIG)
    _test_with_custom_ids(BR_CONFIG)
