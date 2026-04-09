"""Shared fixtures for model tests."""

import pytest


@pytest.fixture(autouse=True)
def mock_all_models_available_in_registry(monkeypatch):
    """Make all candidate models available in the registry by default.

    This fixture simulates a fully-populated model registry where all models
    are marked as available. Individual tests can override this behavior by
    patching get_available_model_names directly.

    This is needed because the fix for PokePoke-z69a4 made model selection
    filter candidates based on registry availability to prevent using stale models.
    """
    def fake_get_available(*args, **kwargs):
        # Return a comprehensive list of all models used in tests
        return [
            "claude-opus-4.6",
            "claude-sonnet-4.5",
            "claude-haiku-4.5",
            "gpt-5",
            "gpt-5.1",
            "gpt-5.1-codex",
            "gpt-5.2",
            "gpt-5.3",
            "special-model",
        ]

    # Patch where the function is defined
    monkeypatch.setattr(
        "pokepoke.models.model_sync.get_available_model_names",
        fake_get_available
    )
