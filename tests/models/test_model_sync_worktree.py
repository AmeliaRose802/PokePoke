"""Test model registry path resolution for worktree scenarios."""

import json
from unittest.mock import patch

from pokepoke.models.model_sync import (
    get_available_model_names,
    load_registry,
)


def test_registry_path_resolves_to_main_repo(tmp_path):
    """Test that registry path resolves to main repo, not worktree.

    This is the critical fix for PokePoke-z69a4: model discovery must work
    correctly even when code is executed from a worktree, not the main repo.
    """
    # Create a fake main repo registry
    main_repo = tmp_path / "main_repo"
    main_repo.mkdir()
    registry_path = main_repo / ".pokepoke" / "model_registry.json"
    registry_path.parent.mkdir(parents=True, exist_ok=True)

    registry_data = {
        "last_sync": "2026-01-01T00:00:00Z",
        "models": {
            "claude-opus-4.6": {"available": True, "name": "claude-opus-4.6"},
            "gpt-5.2": {"available": True, "name": "gpt-5.2"},
            "old-model": {"available": False, "name": "old-model"},
        },
    }
    registry_path.write_text(json.dumps(registry_data))

    # Mock _get_main_repo_root to return the main repo path
    with patch("pokepoke.models.model_sync._get_main_repo_root", return_value=main_repo):
        # Call load_registry without explicit path (simulates worktree call)
        loaded = load_registry()

        # Should load from main repo, not current directory
        assert loaded["last_sync"] == "2026-01-01T00:00:00Z"
        assert "claude-opus-4.6" in loaded["models"]
        assert "gpt-5.2" in loaded["models"]
        assert "old-model" in loaded["models"]

        # get_available_model_names should only return available models
        available = get_available_model_names()
        assert set(available) == {"claude-opus-4.6", "gpt-5.2"}
        assert "old-model" not in available  # unavailable model filtered out


def test_registry_load_without_git_repo(tmp_path):
    """Test that registry gracefully handles non-git environments."""
    # Mock _get_main_repo_root to return None (not in a git repo)
    with patch("pokepoke.models.model_sync._get_main_repo_root", return_value=None):
        loaded = load_registry()

        # Should return empty registry, not crash
        assert loaded == {"last_sync": None, "models": {}}

        # get_available_model_names should return empty list
        available = get_available_model_names()
        assert available == []
