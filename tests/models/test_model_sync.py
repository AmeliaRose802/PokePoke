"""Tests for Copilot model sync parsing and registry updates."""

import json
import subprocess
from datetime import UTC, datetime
from unittest.mock import patch

from pokepoke.config import ModelSyncConfig, ProjectConfig
from pokepoke.models.model_sync import (
    _run_copilot_models,
    get_available_model_names,
    get_registry_last_sync,
    load_registry,
    prune_unavailable_from_config,
    save_registry,
    sync_copilot_models,
    update_registry,
)
from pokepoke.models.model_sync_parsing import (
    is_beta_model,
    normalize_model_entry,
    parse_copilot_models_output,
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


def test_parse_markdown_table():
    """Parse markdown table output from Copilot CLI."""
    output = """Here are the available models:
| Model | ID | Tier |
|---|---|---|
| Claude Opus 4.6 | `claude-opus-4.6` | Premium |
| GPT-5.2 | `gpt-5.2` | Standard |
| GPT-4.1 | `gpt-4.1` | Fast/Cheap |

**Current session:** Claude Opus 4.6
"""
    models = parse_copilot_models_output(output)
    assert len(models) == 3
    names = [m["name"] for m in models]
    assert "claude-opus-4.6" in names
    assert "gpt-5.2" in names
    assert "gpt-4.1" in names
    # Check tier/status was captured
    claude = next(m for m in models if m["name"] == "claude-opus-4.6")
    assert claude.get("status") == "Premium"


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


def test_sync_force_ignores_interval():
    """Test that force=True bypasses interval check and always runs sync."""
    config = ProjectConfig()
    config.model_sync = ModelSyncConfig(interval_minutes=60)
    recent = datetime.now(UTC).isoformat()
    mock_model = {"name": "gpt-5.2", "status": "ga"}

    with patch("pokepoke.models.model_sync.get_config", return_value=config), \
            patch("pokepoke.models.model_sync.load_registry", return_value={"last_sync": recent, "models": {}}), \
            patch("pokepoke.models.model_sync._run_copilot_models", return_value=[mock_model]), \
            patch("pokepoke.models.model_sync.save_registry"), \
            patch("pokepoke.models.model_sync._get_main_repo_root", return_value=None), \
            patch("pokepoke.models.model_sync._list_existing_model_items", return_value=[]), \
            patch("pokepoke.models.model_sync.run_bd_sync_with_retry"):
        result = sync_copilot_models(force=True)
        assert result is not None
        # Should have called Copilot CLI despite recent sync
        assert result.wall_duration is not None


def test_sync_disabled_skips_even_when_forced():
    """When model_sync.enabled is False, sync_copilot_models must skip even with force=True."""
    config = ProjectConfig()
    config.model_sync = ModelSyncConfig(enabled=False)
    with patch("pokepoke.models.model_sync.get_config", return_value=config), \
            patch("pokepoke.models.model_sync._run_copilot_models") as mock_models:
        result = sync_copilot_models(force=True)
        assert result is not None
        mock_models.assert_not_called()


def test_sync_disabled_skips_without_force():
    """When model_sync.enabled is False, sync_copilot_models must skip in normal mode."""
    config = ProjectConfig()
    config.model_sync = ModelSyncConfig(enabled=False)
    with patch("pokepoke.models.model_sync.get_config", return_value=config), \
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


def test_save_registry_atomic_write(tmp_path):
    """save_registry uses temp file + rename for atomic writes."""
    path = tmp_path / "registry.json"
    payload = {"last_sync": "2026-02-25T00:00:00+00:00", "models": {}}
    save_registry(payload, path=path)

    # Verify the file exists and no .tmp leftover
    assert path.exists()
    tmp_path_file = path.with_suffix(".tmp")
    assert not tmp_path_file.exists(), "Temp file should be cleaned up after atomic rename"

    # Verify content is valid JSON
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert loaded == payload


def test_save_registry_creates_parent_dirs(tmp_path):
    """save_registry creates parent directories if they don't exist."""
    path = tmp_path / "nested" / "dir" / "registry.json"
    payload = {"last_sync": None, "models": {}}
    save_registry(payload, path=path)
    assert path.exists()


def test_run_copilot_models_parses_output():
    output = '[{"name":"gpt-5.2","status":"beta"}]'
    result = subprocess.CompletedProcess(["copilot", "models", "list", "--json"], 0, output, "")
    with patch("pokepoke.models.model_sync.subprocess.run", return_value=result):
        models = _run_copilot_models("copilot")
        assert models[0]["name"] == "gpt-5.2"


def test_run_copilot_models_logs_nonzero_returncode(caplog):
    """Non-zero returncode is logged and the command is skipped."""
    import logging

    fail = subprocess.CompletedProcess(
        ["copilot", "models", "list", "--json"], 1, "", "auth error"
    )
    with patch("pokepoke.models.model_sync.subprocess.run", return_value=fail), \
            caplog.at_level(logging.DEBUG, logger="pokepoke.models.model_sync"):
        models = _run_copilot_models("copilot")
    assert models == []
    assert any("rc=1" in rec.message for rec in caplog.records)
    assert any("auth error" in rec.message for rec in caplog.records)


def test_run_copilot_models_logs_timeout(caplog):
    """TimeoutExpired is logged and the command is skipped."""
    import logging

    with patch(
        "pokepoke.models.model_sync.subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd="copilot", timeout=5),
    ), caplog.at_level(logging.DEBUG, logger="pokepoke.models.model_sync"):
        models = _run_copilot_models("copilot", timeout=5)
    assert models == []
    assert any("timed out" in rec.message.lower() for rec in caplog.records)


def test_run_copilot_models_logs_file_not_found(caplog):
    """FileNotFoundError is logged and the command is skipped."""
    import logging

    with patch(
        "pokepoke.models.model_sync.subprocess.run",
        side_effect=FileNotFoundError("copilot"),
    ), caplog.at_level(logging.DEBUG, logger="pokepoke.models.model_sync"):
        models = _run_copilot_models("copilot")
    assert models == []
    assert any("not found" in rec.message.lower() for rec in caplog.records)


def test_run_copilot_models_warns_when_all_fail(caplog):
    """A WARNING is emitted when every command variant fails."""
    import logging

    fail = subprocess.CompletedProcess(
        ["copilot", "models", "list", "--json"], 2, "", "server error"
    )
    with patch("pokepoke.models.model_sync.subprocess.run", return_value=fail), \
            caplog.at_level(logging.WARNING, logger="pokepoke.models.model_sync"):
        models = _run_copilot_models("copilot")
    assert models == []
    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert len(warnings) >= 1
    assert "all copilot model commands failed" in warnings[0].message.lower()


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
            patch("pokepoke.models.model_sync_beads._run_bd", side_effect=fake_run_bd) as mock_bd, \
            patch("pokepoke.models.model_sync._get_main_repo_root", return_value=tmp_path), \
            patch("pokepoke.models.model_sync.REGISTRY_PATH", tmp_path / "model_registry.json"), \
            patch("pokepoke.models.model_sync.run_bd_sync_with_retry") as mock_sync, \
            patch("pokepoke.beads.sdk_beads_tracker.record_items_created"):
        result = sync_copilot_models()
        assert result is not None
        assert any(call.args[0][0] == "create" for call in mock_bd.call_args_list)
        assert any(call.args[0][0] == "update" for call in mock_bd.call_args_list)
        mock_sync.assert_called_once()


def test_sync_records_created_items_in_stats(tmp_path):
    """Items created by model sync must be reported to session stats."""
    config = ProjectConfig()
    config.model_sync = ModelSyncConfig(beta_only=False, labels=["model"])

    def fake_run_bd(args, check=True, timeout=30, cwd=None):
        if args[0] == "list":
            return subprocess.CompletedProcess(args, 0, "[]", "")
        if args[0] == "create":
            return subprocess.CompletedProcess(
                args, 0, json.dumps({"id": "PokePoke-new1", "title": args[1]}), "",
            )
        return subprocess.CompletedProcess(args, 0, "{}", "")

    with patch("pokepoke.models.model_sync.get_config", return_value=config), \
            patch("pokepoke.models.model_sync._run_copilot_models", return_value=[
                {"name": "gpt-5.2", "status": "beta"},
            ]), \
            patch("pokepoke.models.model_sync_beads._run_bd", side_effect=fake_run_bd), \
            patch("pokepoke.models.model_sync._get_main_repo_root", return_value=tmp_path), \
            patch("pokepoke.models.model_sync.REGISTRY_PATH", tmp_path / "model_registry.json"), \
            patch("pokepoke.models.model_sync.run_bd_sync_with_retry"), \
            patch("pokepoke.beads.sdk_beads_tracker.record_items_created") as mock_record:
        sync_copilot_models()
        mock_record.assert_called_once()
        items = mock_record.call_args[0][0]
        assert len(items) == 1
        assert items[0][0] == "PokePoke-new1"


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
            patch("pokepoke.models.model_sync_beads._run_bd", side_effect=fake_run_bd) as mock_bd, \
            patch("pokepoke.models.model_sync._get_main_repo_root", return_value=tmp_path), \
            patch("pokepoke.models.model_sync.REGISTRY_PATH", registry_path), \
            patch("pokepoke.beads.sdk_beads_tracker.record_items_created"):
        result = sync_copilot_models()
        assert result is not None
        assert any(call.args[0][0] == "close" for call in mock_bd.call_args_list)


def test_get_available_model_names(tmp_path):
    """get_available_model_names returns only models marked available."""
    registry_path = tmp_path / "registry.json"
    registry_path.write_text(json.dumps({
        "last_sync": "2026-03-25T00:00:00+00:00",
        "models": {
            "gpt-5.2": {"available": True, "name": "gpt-5.2"},
            "claude-opus-4.6": {"available": True, "name": "claude-opus-4.6"},
            "old-model": {"available": False, "name": "old-model"},
        },
    }))
    names = get_available_model_names(registry_path=registry_path)
    assert names == ["claude-opus-4.6", "gpt-5.2"]


def test_get_available_model_names_empty_registry(tmp_path):
    """Returns empty list when no registry exists."""
    names = get_available_model_names(registry_path=tmp_path / "missing.json")
    assert names == []


def test_get_registry_last_sync(tmp_path):
    """get_registry_last_sync returns the timestamp from registry."""
    registry_path = tmp_path / "registry.json"
    ts = "2026-03-25T12:00:00+00:00"
    registry_path.write_text(json.dumps({"last_sync": ts, "models": {}}))
    assert get_registry_last_sync(registry_path=registry_path) == ts


def test_get_registry_last_sync_missing(tmp_path):
    """Returns None when registry doesn't exist."""
    assert get_registry_last_sync(registry_path=tmp_path / "missing.json") is None


def test_prune_unavailable_from_config(tmp_path):
    """prune_unavailable_from_config removes stale models and saves config."""
    # Set up registry with only claude-opus-4.6 available
    registry_path = tmp_path / "registry.json"
    registry_path.write_text(json.dumps({
        "last_sync": "2026-03-25T00:00:00+00:00",
        "models": {
            "claude-opus-4.6": {"available": True},
            "gpt-5": {"available": True},
        },
    }))

    # Set up config with a stale model
    config_path = tmp_path / ".pokepoke" / "config.yaml"
    config_path.parent.mkdir(parents=True, exist_ok=True)

    import yaml
    config_data = {
        "models": {
            "default": "claude-opus-4.6",
            "fallback": "gpt-5",
            "candidate_models": ["claude-opus-4.6", "gpt-5", "stale-model"],
        },
    }
    config_path.write_text(yaml.safe_dump(config_data))

    with patch("pokepoke.models.model_sync.REGISTRY_PATH", registry_path), \
            patch("pokepoke.config._find_repo_root", return_value=tmp_path):
        removed = prune_unavailable_from_config(registry_path=registry_path)

    assert removed == ["stale-model"]

    # Verify config was updated
    updated = yaml.safe_load(config_path.read_text())
    assert "stale-model" not in updated["models"]["candidate_models"]
    assert "claude-opus-4.6" in updated["models"]["candidate_models"]
    assert "gpt-5" in updated["models"]["candidate_models"]


def test_prune_unavailable_from_config_no_stale(tmp_path):
    """No pruning when all candidates are available."""
    registry_path = tmp_path / "registry.json"
    registry_path.write_text(json.dumps({
        "last_sync": "2026-03-25T00:00:00+00:00",
        "models": {
            "claude-opus-4.6": {"available": True},
            "gpt-5": {"available": True},
        },
    }))

    config_path = tmp_path / ".pokepoke" / "config.yaml"
    config_path.parent.mkdir(parents=True, exist_ok=True)

    import yaml
    config_data = {
        "models": {
            "candidate_models": ["claude-opus-4.6", "gpt-5"],
        },
    }
    config_path.write_text(yaml.safe_dump(config_data))

    with patch("pokepoke.models.model_sync.REGISTRY_PATH", registry_path), \
            patch("pokepoke.config._find_repo_root", return_value=tmp_path):
        removed = prune_unavailable_from_config(registry_path=registry_path)

    assert removed == []


def test_prune_unavailable_from_config_no_candidates(tmp_path):
    """No pruning when config has no candidate_models."""
    registry_path = tmp_path / "registry.json"
    registry_path.write_text(json.dumps({
        "last_sync": "2026-03-25T00:00:00+00:00",
        "models": {"claude-opus-4.6": {"available": True}},
    }))

    config_path = tmp_path / ".pokepoke" / "config.yaml"
    config_path.parent.mkdir(parents=True, exist_ok=True)

    import yaml
    config_data = {"models": {"default": "claude-opus-4.6"}}
    config_path.write_text(yaml.safe_dump(config_data))

    with patch("pokepoke.models.model_sync.REGISTRY_PATH", registry_path), \
            patch("pokepoke.config._find_repo_root", return_value=tmp_path):
        removed = prune_unavailable_from_config(registry_path=registry_path)

    assert removed == []
