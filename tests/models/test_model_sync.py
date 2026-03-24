"""Tests for Copilot model sync parsing and registry updates."""

import json
import subprocess
from datetime import UTC, datetime
from unittest.mock import patch

from pokepoke.config import ModelSyncConfig, ProjectConfig
from pokepoke.models.model_sync import (
    _run_copilot_models,
    is_beta_model,
    load_registry,
    normalize_model_entry,
    parse_copilot_models_output,
    save_registry,
    sync_copilot_models,
    update_registry,
)


def test_parse_json_list():
    output = '[{"name":"gpt-5.2","status":"beta"}]'
    models = parse_copilot_models_output(output)
    assert len(models) == 1
    assert models[0]["name"] == "gpt-5.2"


def test_parse_json_envelope():
    output = '{"models":[{"id":"claude-opus-4.6"}]}'
    models = parse_copilot_models_output(output)
    assert len(models) == 1
    assert models[0]["id"] == "claude-opus-4.6"


def test_parse_text_table():
    output = "MODEL STATUS\n gpt-5.2 beta\n claude-opus-4.6 ga"
    models = parse_copilot_models_output(output)
    assert [m["name"] for m in models] == ["gpt-5.2", "claude-opus-4.6"]


def test_normalize_and_beta_detection():
    entry = {"name": "gpt-5.2", "status": "beta", "capabilities": ["tools"]}
    model = normalize_model_entry(entry)
    assert model is not None
    assert model.name == "gpt-5.2"
    assert is_beta_model(model, include_preview=False) is True

    preview_entry = {"name": "gpt-5.3-preview", "status": "preview"}
    preview_model = normalize_model_entry(preview_entry)
    assert preview_model is not None
    assert is_beta_model(preview_model, include_preview=False) is False
    assert is_beta_model(preview_model, include_preview=True) is True

    tagged_entry = {"name": "claude-opus-4.6", "tags": "experimental,tools", "capabilities": "tools,analysis"}
    tagged_model = normalize_model_entry(tagged_entry)
    assert tagged_model is not None
    assert tagged_model.capabilities == ["tools", "analysis"]
    assert tagged_model.tags == ["experimental", "tools"]


def test_update_registry_tracks_availability():
    now = datetime(2026, 2, 25, tzinfo=UTC)
    model = normalize_model_entry({"name": "gpt-5.2", "status": "beta"})
    assert model is not None
    registry, new_models, removed_models = update_registry([model], {"last_sync": None, "models": {}}, now)
    assert "gpt-5.2" in new_models
    assert not removed_models

    registry, new_models, removed_models = update_registry([], registry, now)
    assert not new_models
    assert "gpt-5.2" in removed_models


def test_sync_skips_recent_run():
    config = ProjectConfig()
    config.model_sync = ModelSyncConfig(interval_minutes=60)
    recent = datetime.now(UTC).isoformat()
    with patch("pokepoke.models.model_sync.get_config", return_value=config), \
            patch("pokepoke.models.model_sync.load_registry", return_value={"last_sync": recent, "models": {}}), \
            patch("pokepoke.models.model_sync._run_copilot_models") as mock_models:
        result = sync_copilot_models()
        assert result is not None
        mock_models.assert_not_called()


def test_sync_no_models_returns_none():
    config = ProjectConfig()
    config.model_sync = ModelSyncConfig()
    with patch("pokepoke.models.model_sync.get_config", return_value=config), \
            patch("pokepoke.models.model_sync.load_registry", return_value={"last_sync": None, "models": {}}), \
            patch("pokepoke.models.model_sync._run_copilot_models", return_value=[]):
        assert sync_copilot_models() is None


def test_load_registry_defaults(tmp_path):
    registry = load_registry(path=tmp_path / "missing.json")
    assert registry["models"] == {}
    assert registry["last_sync"] is None


def test_save_registry_round_trip(tmp_path):
    path = tmp_path / "registry.json"
    payload = {"last_sync": "2026-02-25T00:00:00+00:00", "models": {"gpt-5.2": {"available": True}}}
    save_registry(payload, path=path)
    loaded = load_registry(path=path)
    assert loaded["models"]["gpt-5.2"]["available"] is True


def test_run_copilot_models_parses_output():
    output = '[{"name":"gpt-5.2","status":"beta"}]'
    result = subprocess.CompletedProcess(["copilot", "models", "list", "--json"], 0, output, "")
    with patch("pokepoke.models.model_sync.subprocess.run", return_value=result):
        models = _run_copilot_models("copilot")
        assert models[0]["name"] == "gpt-5.2"


def test_sync_creates_and_updates_beads(tmp_path):
    config = ProjectConfig()
    config.model_sync = ModelSyncConfig(beta_only=False, labels=["model", "beta"])

    existing_items = [
        {"id": "PokePoke-123", "title": "Beta test Copilot model: claude-opus-4.6", "metadata": {"copilot_model": "claude-opus-4.6"}}
    ]

    def fake_run_bd(args, check=True, timeout=30, cwd=None):
        if args[0] == "list":
            return subprocess.CompletedProcess(args, 0, json.dumps(existing_items), "")
        return subprocess.CompletedProcess(args, 0, "{}", "")

    with patch("pokepoke.models.model_sync.get_config", return_value=config), \
            patch("pokepoke.models.model_sync._run_copilot_models", return_value=[
                {"name": "gpt-5.2", "status": "beta"},
                {"name": "claude-opus-4.6", "status": "ga"},
            ]), \
            patch("pokepoke.models.model_sync._run_bd", side_effect=fake_run_bd) as mock_bd, \
            patch("pokepoke.models.model_sync._get_main_repo_root", return_value=tmp_path), \
            patch("pokepoke.models.model_sync.REGISTRY_PATH", tmp_path / "model_registry.json"), \
            patch("pokepoke.models.model_sync.run_bd_sync_with_retry") as mock_sync:
        result = sync_copilot_models()
        assert result is not None
        assert any(call.args[0][0] == "create" for call in mock_bd.call_args_list)
        assert any(call.args[0][0] == "update" for call in mock_bd.call_args_list)
        mock_sync.assert_called_once()


def test_sync_prunes_unavailable(tmp_path):
    config = ProjectConfig()
    config.model_sync = ModelSyncConfig(beta_only=False, prune_unavailable=True)

    existing_items = [
        {"id": "PokePoke-999", "title": "Beta test Copilot model: gpt-5.2", "metadata": {"copilot_model": "gpt-5.2"}}
    ]

    def fake_run_bd(args, check=True, timeout=30, cwd=None):
        if args[0] == "list":
            return subprocess.CompletedProcess(args, 0, json.dumps(existing_items), "")
        return subprocess.CompletedProcess(args, 0, "{}", "")

    registry_path = tmp_path / "model_registry.json"
    registry_path.write_text(json.dumps({
        "last_sync": None,
        "models": {"gpt-5.2": {"available": True, "first_seen": "2026-02-25T00:00:00+00:00"}},
    }))

    with patch("pokepoke.models.model_sync.get_config", return_value=config), \
            patch("pokepoke.models.model_sync._run_copilot_models", return_value=[
                {"name": "claude-opus-4.6", "status": "ga"}
            ]), \
            patch("pokepoke.models.model_sync._run_bd", side_effect=fake_run_bd) as mock_bd, \
            patch("pokepoke.models.model_sync._get_main_repo_root", return_value=tmp_path), \
            patch("pokepoke.models.model_sync.REGISTRY_PATH", registry_path):
        result = sync_copilot_models()
        assert result is not None
        assert any(call.args[0][0] == "close" for call in mock_bd.call_args_list)
