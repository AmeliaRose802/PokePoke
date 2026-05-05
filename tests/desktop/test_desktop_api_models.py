"""Tests for desktop_api_models module."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from pokepoke.desktop.desktop_api import DesktopAPI


@pytest.fixture(autouse=True)
def _isolate(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("pokepoke.desktop.desktop_api.get_repository_name", lambda: "test-repo")


def test_get_available_models_with_results() -> None:
    api = DesktopAPI()
    with patch(
        "pokepoke.models.model_sync.get_available_model_names",
        return_value=["claude-opus-4.6", "gpt-5.2"],
    ), patch(
        "pokepoke.models.model_sync.get_registry_last_sync",
        return_value="2026-03-25T00:00:00+00:00",
    ), patch(
        "pokepoke.models.model_sync.prune_unavailable_from_config",
        return_value=["old-model"],
    ):
        result = api.get_available_models()

    assert result["models"] == ["claude-opus-4.6", "gpt-5.2"]
    assert result["last_sync"] == "2026-03-25T00:00:00+00:00"
    assert result["removed_from_config"] == ["old-model"]


def test_get_available_models_empty_skips_prune() -> None:
    api = DesktopAPI()
    with patch(
        "pokepoke.models.model_sync.get_available_model_names",
        return_value=[],
    ), patch(
        "pokepoke.models.model_sync.get_registry_last_sync",
        return_value=None,
    ), patch(
        "pokepoke.models.model_sync.prune_unavailable_from_config",
    ) as mock_prune:
        result = api.get_available_models()

    assert result["models"] == []
    assert result["last_sync"] is None
    assert result["removed_from_config"] == []
    mock_prune.assert_not_called()
